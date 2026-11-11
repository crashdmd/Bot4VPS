"""Trusted detached updater; root jobs/code, service-user runtime I/O."""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

if __package__:
    from .protocol import APP, HELPER_HOME, ROOT_STATE
    from .daemon import as_service, protected
else:
    from protocol import APP, HELPER_HOME, ROOT_STATE
    from daemon import as_service, protected


def check_tree(root):
    for path in [Path(root), *Path(root).rglob("*")]:
        if any(part in {"__pycache__", ".gradle", ".kotlin", ".build-env", ".signing", ".singning", "build"} for part in path.parts):
            continue
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("Код содержит незащищённый путь")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ValueError("Код содержит hardlink")
        if not stat.S_ISREG(info.st_mode) and not stat.S_ISDIR(info.st_mode):
            raise ValueError("Код содержит специальный файл")


def execute(job_file):
    import runner
    import bootstrap
    from release_verify import verify_envelope
    if __package__:
        from core.update.legacy_release import target_version, resolve
    else:
        from legacy_release import target_version, resolve
    if __package__:
        from .daemon import atomic, process_stamp
    else:
        from daemon import atomic, process_stamp

    job = json.loads(protected(job_file).read_text())
    if (job.get("app_dir") != str(APP) or job.get("state_file") != str(APP / "data/update/state.json")
            or job.get("backup_root") != str(ROOT_STATE / "code-backups") or not job.get("privilege_separation")):
        raise ValueError("Некорректный защищённый job")
    with (ROOT_STATE / "control.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for name in runner.CODE_PATHS:
            root = APP / name
            if root.exists() or root.is_symlink():
                check_tree(root)

        from release_verify import normalized_version
        target = tuple(map(int, normalized_version(job['target_version']).split('.')))
        legacy = job['action'] == 'rollback' and (3, 0, 0) <= target < (7, 0, 0)
        if bool(job.get('legacy_rollback')) != legacy:
            raise ValueError('Режим доверия не соответствует целевой версии')
        regression_data = None
        if legacy:
            target_version(job['action'], job['target_version'])
            old = resolve(job['action'], job['target_version'])
            payload = {'version': old['version'], 'commit': old['commit'], 'archive': None}
            runner._verified_release = lambda _: {'legacy': True, 'payload': payload, 'archive_url': old['archive_url']}
        else:
            payload = verify_envelope(job["release_envelope"], job["target_version"])
        original_write = runner._write_state
        def write(path, **patches):
            if legacy and regression_data is not None and regression_data['stage'] not in ('prepared', 'reverted', 'reverting'):
                return original_write(path, **patches)
            return as_service(lambda: original_write(path, **patches))
        runner._write_state = write
        original_backup = runner._backup_code

        def backup(app, destination):
            nonlocal regression_data
            original_backup(app, destination)
            atomic(ROOT_STATE / "update-recovery.json", json.dumps({"pid": os.getpid(), "stamp": process_stamp(os.getpid()),
                   "job": job, "backup": str(destination)}).encode())
            if legacy:
                if __package__:
                    from . import install
                else:
                    import install
                regression_data = install.regress(job, destination)

        runner._backup_code = backup

        def extract(archive, destination):
            if legacy:
                # HTTPS origin and immutable commit were resolved by this root
                # process; the shared extractor rejects paths/links/duplicates.
                return original_extract(archive, destination)
            staging = destination / "verified"
            staging.mkdir(mode=0o700)
            root = bootstrap.extract_verified(archive, staging, payload)
            if not (root / "core/local_privileges.py").is_file() or not (root / "core/migration/privileged/protocol.py").is_file():
                raise ValueError("Релиз не поддерживает разделение прав; восстановите его данные или используйте аварийный CLI владельца")
            return root

        original_extract = runner._extract_tar
        runner._extract_tar = extract
        original_swap = runner._swap_code

        def swap(app, source):
            # Preserve local Android build/signing artifacts outside the code
            # swap, without putting them in the updater's code trust anchor.
            preserved = ROOT_STATE / "development-artifacts" / job_file.parent.name
            for relative in ("ui/Bot4VPS-Mobile/.gradle", "ui/Bot4VPS-Mobile/.kotlin", "ui/Bot4VPS-Mobile/.build-env", "ui/Bot4VPS-Mobile/.signing", "ui/Bot4VPS-Mobile/.singning", "ui/Bot4VPS-Mobile/app/build"):
                existing = app / relative
                if existing.exists():
                    if existing.is_symlink():
                        raise ValueError("Ссылка вместо локального build-каталога")
                    target = preserved / relative
                    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                    shutil.move(existing, target)
            for name in runner.CODE_PATHS:
                if (app / name).exists() or (app / name).is_symlink():
                    check_tree(app / name)
            original_swap(app, source)
            for name in runner.CODE_PATHS:
                if (app / name).exists():
                    check_tree(app / name)
            if legacy:
                if __package__:
                    from .regression import switch
                else:
                    from regression import switch
                switch(regression_data)

        runner._swap_code = swap
        original_changelog = runner._extract_changelog_to
        runner._extract_changelog_to = lambda app, version, output: original_changelog(app, version, output) if legacy else as_service(lambda: original_changelog(app, version, output))

        original_pip = runner._pip_install_if_changed
        original_restore = runner._restore
        original_restart = runner._restart_service
        if legacy:
            def dependencies(current, old_req):
                if regression_data and regression_data['stage'] in ('switching', 'switched', 'committing'):
                    # Historical requirements had no hash lock. This exception
                    # only installs the immutable legacy GitHub source's deps.
                    result = subprocess.run([current['venv_python'], '-I', '-m', 'pip', '--isolated', 'install',
                                             '--no-input', '-q', '-r', str(APP / 'requirements.txt')],
                                            cwd='/', capture_output=True, text=True, timeout=900)
                    if result.returncode:
                        raise RuntimeError('Не удалось установить зависимости старого релиза')
                else:
                    original_pip(current, old_req)
            runner._pip_install_if_changed = dependencies
            def restore(current, saved, state, **kwargs):
                if regression_data:
                    if __package__:
                        from .regression import restore as restore_runtime, reverted
                    else:
                        from regression import restore as restore_runtime, reverted
                    restore_runtime(regression_data)
                original_restore(current, saved, state, strict=True)
                if regression_data:
                    reverted(regression_data)
            runner._restore = restore
            runner._restart_service = lambda current: original_restart(current)

        def cleanup(work, app):
            shutil.rmtree(work)
            backups = sorted((ROOT_STATE / "code-backups").glob("update_backup_*"))
            for old in backups[:-runner.BACKUP_KEEP]:
                check_tree(old)
                shutil.rmtree(old)

        runner._cleanup = cleanup
        if __package__:
            from .code_snapshots import create
        else:
            from code_snapshots import create
        create()
        result = runner.main([str(HELPER_HOME / "runner.py"), str(job_file)])
        if legacy:
            if result == 0:
                try:
                    if __package__:
                        from .regression import commit
                    else:
                        from regression import commit
                    commit(regression_data)
                except Exception:
                    runner._restore(job, Path(regression_data['backup']), Path(job['state_file']), strict=True)
                    runner._write_state(Path(job['state_file']), status='failed', action=None, pid=None,
                                        last_error='Обратная миграция не завершилась; восстановлена 7.0')
                    return 1
            elif regression_data is None:
                # Preparation can fail after stop, before runner marks its
                # backup as ready. Restore immediately rather than waiting for
                # helper recovery to notice the persisted backup intent.
                intent = ROOT_STATE / 'update-recovery.json'
                if intent.exists():
                    saved = json.loads(protected(intent).read_text())
                    if __package__:
                        from .regression import load
                    else:
                        from regression import load
                    candidate = load()
                    if candidate and candidate.get('job', {}).get('work_dir') == job['work_dir'] and candidate['stage'] == 'prepared':
                        regression_data = candidate
                    runner._restore(job, Path(saved['backup']), Path(job['state_file']), strict=True)
                    runner._write_state(Path(job['state_file']), status='failed', action=None, pid=None,
                                        last_error='Подготовка обратной миграции не завершилась; восстановлена 7.0')
                    intent.unlink(missing_ok=True)
            return result
        if result == 0:
            create()
            # Only code whose release signature was checked above is executed
            # for helper refresh; the application does not supply this command.
            subprocess.run(["/usr/bin/python3", "-I", str(APP / "core/migration/privileged/install.py"), "--refresh-helper"],
                           check=True, timeout=90, cwd="/", env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"})
            subprocess.run(["/usr/bin/systemctl", "daemon-reload"], check=True, timeout=60)
            (ROOT_STATE / "update-recovery.json").unlink(missing_ok=True)
            subprocess.run(["/usr/bin/systemctl", "--no-block", "restart", "bot4vps-helper"], check=True, timeout=15)
        return result
