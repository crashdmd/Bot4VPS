"""Transactional return to the legacy root layout during a pre-7.0 rollback.

Called only by the trusted updater with a root-created job, never from IPC
parameters. The helper remains installed until health succeeds so that a
dead worker can restore code, runtime bytes, ownership and the current unit.
"""
from __future__ import annotations

import base64
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import uuid

if __package__:
    from . import install
    from .protocol import APP, ROOT_STATE, UNIT, transport, unit_text
    from .daemon import atomic, protected, process_stamp
else:
    import install
    from protocol import APP, ROOT_STATE, UNIT, transport, unit_text
    from daemon import atomic, protected, process_stamp

LOCAL_ROOTS = ('data', 'keys', 'logs', 'scripts', 'backup')
JSON_FILES = ('config.json', 'servers.json', 'monitor.json')
LOCK_ROOT = Path('/run/lock/bot4vps')
ARCHIVE_LIMIT = 3


def save(data):
    atomic(ROOT_STATE / 'regression.json', json.dumps(data).encode())


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def sync_tree(root):
    for path in install.walk(root):
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as stream:
                os.fsync(stream.fileno())
    for directory, _, _ in os.walk(root, topdown=False):
        sync_directory(directory)
    sync_directory(root.parent)


def load():
    path = ROOT_STATE / 'regression.json'
    return json.loads(protected(path).read_text()) if path.exists() else None


def legacy_unit(text):
    # Rebuild from whitelisted transport only; no hooks or shell from a client.
    canonical = unit_text(transport(text))
    command = next(line for line in canonical.splitlines() if line.startswith('ExecStart='))
    return f'''[Unit]
Description=Bot4VPS
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory={APP}
Environment=PYTHONPATH={APP}
Environment=PYTHONDONTWRITEBYTECODE=1
UMask=0077
{command}
Restart=always
RestartSec=5
TimeoutStopSec=45
KillMode=mixed

[Install]
WantedBy=multi-user.target
'''


def tree_manifest(root):
    result = {}
    for path in install.walk(root):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[relative] = ['link', os.readlink(path)]
        elif path.is_file():
            result[relative] = ['file', install.digest(path)]
        elif path.is_dir():
            result[relative] = ['dir']
        else:
            raise ValueError('Специальный файл в снимке обратной миграции')
    return result


def prepare(job, backup):
    if __package__:
        from core.update.legacy_release import target_version
    else:
        from legacy_release import target_version
    target_version(job['action'], job['target_version'])
    previous = load()
    if previous and previous['stage'] not in ('complete', 'reverted'):
        raise ValueError('Предыдущая обратная миграция ещё не завершена')
    protected(APP, directory=True)
    protected(UNIT)
    unit = UNIT.read_text()
    legacy_unit(unit)
    install.systemctl('stop', 'bot4vps')
    snapshot = ROOT_STATE / 'regression-snapshots' / uuid.uuid4().hex
    snapshot.mkdir(parents=True, mode=0o700)
    runtime = APP / 'data/runtime'
    if not runtime.is_dir() or runtime.is_symlink():
        raise ValueError('Нет установленной разделённой раскладки')
    ownership = {}
    roots = [APP / name for name in LOCAL_ROOTS if (APP / name).exists()]
    cfg = json.loads((runtime / 'config.json').read_text())
    storage = Path((cfg.get('backup') or {}).get('storage', {}).get('root') or '/var/backups/bot4vps')
    if not storage.is_absolute() or '..' in storage.parts or storage == APP or storage.is_relative_to(APP):
        raise ValueError('Некорректный внешний backup storage')
    install.validate_storage(storage)
    for root in [*roots, storage, LOCK_ROOT]:
        if not root.exists():
            continue
        if root.is_symlink() or any(parent.is_symlink() for parent in root.parents):
            raise ValueError('Ссылка в рабочем пути обратной миграции')
        install.validate_runtime(root)
        for path in install.walk(root):
            install.remember(path, {'ownership': ownership})
    for name in JSON_FILES:
        alias, real = APP / name, runtime / name
        if alias.exists() or alias.is_symlink():
            if not alias.is_symlink() or alias.resolve() != real or not real.is_file():
                raise ValueError('Изменён управляемый путь JSON')
    total = sum(path.stat().st_size for root in roots for path in install.walk(root) if path.is_file() and not path.is_symlink())
    if shutil.disk_usage(ROOT_STATE).free < total * 2 + 32 * 1024 * 1024:
        raise ValueError('Недостаточно места для защитной копии обратной миграции')
    for root in roots:
        shutil.copytree(root, snapshot / root.name, symlinks=True)
    # The service is stopped: a full SQLite/WAL snapshot is consistent and also
    # retains logs, task/backup history and every runtime secret, not just config.
    for path in install.walk(snapshot):
        if not path.is_symlink():
            os.chown(path, 0, 0)
            path.chmod(0o700 if path.is_dir() else 0o600)
            if path.is_file():
                with path.open('rb') as stream:
                    os.fsync(stream.fileno())
    for directory, _, _ in os.walk(snapshot, topdown=False):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    sync_directory(snapshot.parent)
    data = {'stage': 'prepared', 'pid': os.getpid(), 'stamp': process_stamp(os.getpid()),
            'job': job, 'backup': str(backup), 'snapshot': str(snapshot),
            'manifest': tree_manifest(snapshot), 'ownership': ownership,
            'roots': [root.name for root in roots], 'unit': unit,
            'wrapper': install.backup_file(install.WRAPPER),
            'migration': install.backup_file(ROOT_STATE / 'migration.json'), 'moves': []}
    ledger = ROOT_STATE / 'mobile-firewall.json'
    if ledger.exists():
        from firewall import LocalApiFirewall
        protected(ledger)
        LocalApiFirewall(ledger)._read()  # Validate the schema without touching firewall rules.
        data['mobile_firewall'] = ledger.read_text()
    save(data)
    return data


def move(data, source, destination):
    if destination.exists() or destination.is_symlink():
        raise ValueError('Конфликт переноса данных обратной миграции')
    data['moves'].append([str(source), str(destination)])
    save(data)  # Intent before mutation; snapshot recovery does not depend on it.
    try:
        os.replace(source, destination)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        # Retain the source until a verified, durable destination is committed.
        # Interrupted copies are disposable: rollback restores the full snapshot.
        staging = destination.with_name('.regression-move-' + uuid.uuid4().hex)
        data.setdefault('move_staging', []).append(str(staging))
        save(data)
        try:
            source_manifest = tree_manifest(source) if source.is_dir() and not source.is_symlink() else None
            if source.is_symlink():
                staging.symlink_to(os.readlink(source))
            elif source.is_dir():
                shutil.copytree(source, staging, symlinks=True)
                if source_manifest != tree_manifest(staging):
                    raise ValueError('Не удалось проверить перенос между файловыми системами')
                sync_tree(staging)
            else:
                if not stat.S_ISREG(source.lstat().st_mode):
                    raise ValueError('Специальный файл при переносе данных')
                shutil.copy2(source, staging, follow_symlinks=False)
                if install.digest(source) != install.digest(staging):
                    raise ValueError('Не удалось проверить перенос между файловыми системами')
                with staging.open('rb') as stream:
                    os.fsync(stream.fileno())
            for original in install.walk(source) if source_manifest is not None else [source]:
                copied = staging / original.relative_to(source) if source_manifest is not None else staging
                metadata = original.lstat()
                os.chown(copied, metadata.st_uid, metadata.st_gid, follow_symlinks=False)
            if source_manifest is not None:
                sync_tree(staging)
            os.replace(staging, destination)
            sync_directory(destination.parent)
            if source.is_dir() and not source.is_symlink():
                shutil.rmtree(source)
            else:
                source.unlink()
        finally:
            if staging.is_dir() and not staging.is_symlink():
                shutil.rmtree(staging)
            else:
                staging.unlink(missing_ok=True)
    sync_directory(source.parent)
    sync_directory(destination.parent)


def switch(data):
    data['stage'] = 'switching'
    save(data)
    # Freeze each recorded path with no-follow dirfds. In particular, no chmod
    # or chown follows an application-controlled link to a system file.
    for raw, (_, _, mode, link) in data['ownership'].items():
        path = Path(raw)
        private_mode = mode & 0o700 or (0o700 if path.is_dir() else 0o600)
        install.restore_owner(path, 0, 0, private_mode if not link else mode, link)
    runtime = APP / 'data/runtime'
    for name in JSON_FILES:
        alias, real = APP / name, runtime / name
        if alias.is_symlink():
            if alias.resolve() != real:
                raise ValueError('Подмена JSON перед обратной миграцией')
            alias.unlink()
        if real.exists():
            move(data, real, alias)
    history = APP / 'data/config-backup'
    destination = APP / 'backup'
    destination.mkdir(mode=0o700, exist_ok=True)
    if history.exists():
        for source in history.iterdir():
            move(data, source, destination / source.name)
        history.rmdir()
    # Preserve leftover lock/diagnostic files, but remove the separated marker.
    move(data, runtime, ROOT_STATE / ('regression-runtime-' + uuid.uuid4().hex))
    if 'mobile_firewall' in data:
        # Return current rule ownership to the path understood by legacy code.
        # Existing rules and all unrelated firewall configuration are retained.
        atomic(APP / 'data/mobile-api-firewall.json', data['mobile_firewall'].encode(), 0o600)
    atomic(UNIT, legacy_unit(data['unit']).encode(), 0o644)
    wrapper = f'#!/bin/sh\ncd {APP} || exit 1\nexec {APP}/venv/bin/python -m ui.cli "$@"\n'
    atomic(install.WRAPPER, wrapper.encode(), 0o755)
    install.systemctl('daemon-reload')
    data['stage'] = 'switched'
    save(data)


def restore(data):
    """Restore complete 7.0 runtime before restarting the protected code backup."""
    snapshot = Path(data['snapshot'])
    snapshot.relative_to(ROOT_STATE / 'regression-snapshots')
    protected(snapshot, directory=True)
    if tree_manifest(snapshot) != data['manifest']:
        raise ValueError('Повреждён снимок обратной миграции')
    data['stage'] = 'reverting'
    save(data)
    install.systemctl('stop', 'bot4vps')
    for name in JSON_FILES:
        alias = APP / name
        if alias.exists() or alias.is_symlink():
            alias.unlink()
    for raw in data.get('move_staging', []):
        staging = Path(raw)
        suffix = staging.name.removeprefix('.regression-move-')
        if (staging.parent not in (APP, APP / 'backup', ROOT_STATE) or not staging.name.startswith('.regression-move-')
                or len(suffix) != 32 or any(c not in '0123456789abcdef' for c in suffix)):
            raise ValueError('Некорректный промежуточный путь переноса')
        if staging.is_dir() and not staging.is_symlink():
            shutil.rmtree(staging)
        else:
            staging.unlink(missing_ok=True)
    for name in data['roots']:
        if name not in LOCAL_ROOTS:
            raise ValueError('Некорректный рабочий каталог снимка')
        target = APP / name
        if target.is_symlink():
            raise ValueError('Ссылка вместо рабочего каталога')
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(snapshot / name, target, symlinks=True)
    for name in JSON_FILES:
        if (APP / 'data/runtime' / name).exists():
            (APP / name).symlink_to(Path('data/runtime') / name)
    for raw, metadata in reversed(list(data['ownership'].items())):
        path = Path(raw)
        if path.exists() or path.is_symlink():
            install.restore_owner(path, *metadata)
    for name in data['roots']:
        sync_tree(APP / name)
    sync_directory(APP)
    atomic(UNIT, data['unit'].encode(), 0o644)
    wrapper = data['wrapper']
    if wrapper:
        atomic(install.WRAPPER, base64.b64decode(wrapper['data']), wrapper['mode'])
    else:
        install.WRAPPER.unlink(missing_ok=True)
    migration = data.get('migration')
    if migration:
        atomic(ROOT_STATE / 'migration.json', base64.b64decode(migration['data']), migration['mode'])
    install.systemctl('enable', '--now', 'bot4vps-helper')
    install.systemctl('daemon-reload')


def commit(data):
    data['stage'] = 'committing'
    save(data)
    # A subsequent update to 7.0 must run a fresh forward migration using the
    # current legacy data, rather than reusing the original transition journal.
    migration = ROOT_STATE / 'migration.json'
    if migration.exists():
        os.replace(migration, ROOT_STATE / ('migration-before-regression-' + uuid.uuid4().hex + '.json'))
    data['stage'] = 'complete'
    save(data)
    (ROOT_STATE / 'update-recovery.json').unlink(missing_ok=True)
    install.systemctl('disable', '--now', 'bot4vps-helper')


def reverted(data):
    data['stage'] = 'reverted'
    save(data)
    (ROOT_STATE / 'update-recovery.json').unlink(missing_ok=True)


def rotate_archives(keep=ARCHIVE_LIMIT):
    """Called after a healthy forward migration, never during recovery/rollback."""
    if not isinstance(keep, int) or keep < 1:
        raise ValueError('Некорректный предел защитных снимков')
    protected(ROOT_STATE, directory=True)
    current = load()
    if current and current.get('stage') not in ('complete', 'reverted'):
        return
    retained = set()
    if current:
        if current.get('snapshot'):
            retained.add(Path(current['snapshot']))
        for source, destination in current.get('moves', []):
            path = Path(destination)
            if path.parent == ROOT_STATE and path.name.startswith('regression-runtime-'):
                retained.add(path)
    groups = ((ROOT_STATE / 'regression-snapshots', '', '', True),
              (ROOT_STATE, 'regression-runtime-', '', True),
              (ROOT_STATE, 'migration-before-regression-', '.json', False))
    for parent, prefix, suffix, directory in groups:
        if not parent.exists():
            continue
        protected(parent, directory=True)
        candidates = []
        for path in parent.iterdir():
            name = path.name
            if not name.startswith(prefix) or (suffix and not name.endswith(suffix)):
                continue
            identity = name[len(prefix):len(name) - len(suffix) if suffix else None]
            if len(identity) != 32 or any(c not in '0123456789abcdef' for c in identity) or path.is_symlink():
                continue
            if path.is_dir() != directory:
                continue
            protected(path, directory=directory)
            candidates.append(path)
        candidates.sort(key=lambda path: path.lstat().st_mtime_ns, reverse=True)
        preserve = {path for path in candidates if path in retained}
        for path in candidates:
            if path in preserve:
                continue
            if len(preserve) < keep:
                preserve.add(path)
                continue
            if directory:
                shutil.rmtree(path)
            else:
                path.unlink()
            sync_directory(parent)
