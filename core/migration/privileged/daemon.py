"""Local root broker. Its installed copy never imports application code.

Run with /usr/bin/python3 -I /usr/lib/bot4vps-helper/daemon.py.
Only this root-owned directory is appended to the isolated Python path.
"""
from __future__ import annotations

import base64
import fcntl
import json
import os
import pwd
import re
import shlex
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
if __package__:
    from .protocol import APP, HELPER_HOME, MAX_MESSAGE, ROOT_STATE, SERVICE, UNIT, USER, decode, domain, fields, port, transport, unit_text
else:
    from protocol import APP, HELPER_HOME, MAX_MESSAGE, ROOT_STATE, SERVICE, UNIT, USER, decode, domain, fields, port, transport, unit_text
    if __name__ == "__main__":
        sys.modules["daemon"] = sys.modules[__name__]

SOCKET = Path("/run/bot4vps-helper/control.sock")
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "HOME": "/root", "PYTHONDONTWRITEBYTECODE": "1"}
CLIENT_PID = None


def process_stamp(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def ensure_idle():
    path = ROOT_STATE / "active-task.json"
    if not path.exists():
        return
    data = json.loads(protected(path).read_text())
    alive = run(["/usr/bin/systemctl", "is-active", "--quiet", data["unit"]], 10)["returncode"] == 0
    if alive:
        # MainPID can still be zero immediately after systemd-run. Membership
        # of the root-created unit is the authority, not a caller's job/PID.
        owner = run(["/usr/bin/systemctl", "show", data["unit"], "--property=ControlGroup", "--value"], 10)
        group = owner.get("stdout", "").strip()
        try:
            groups = Path(f"/proc/{CLIENT_PID}/cgroup").read_text().splitlines()
        except OSError:
            groups = []
        if not group or not any(line.rsplit(":", 1)[-1] == group for line in groups):
            raise ValueError("Другая локальная системная операция ещё выполняется")
    if not alive:
        path.unlink()


def track(path, **data):
    atomic(path, json.dumps({"pid": CLIENT_PID, "stamp": process_stamp(CLIENT_PID), **data}).encode())


def commit_transport(params):
    ensure_idle()
    fields(params)
    pending = ROOT_STATE / "transport-recovery.json"
    if pending.exists():
        data = json.loads(protected(pending).read_text())
        if data["pid"] != CLIENT_PID or data.get("stamp") != process_stamp(CLIENT_PID):
            raise ValueError("Изменение unit принадлежит другой операции")
        pending.unlink()
    return True


def recover():
    regression_path = ROOT_STATE / 'regression.json'
    if regression_path.exists():
        from regression import load, restore as restore_runtime, reverted
        regression = load()
        if regression['stage'] == 'complete':
            completed_intent = ROOT_STATE / 'update-recovery.json'
            if completed_intent.exists():
                data = json.loads(protected(completed_intent).read_text())
                if data.get('job', {}).get('work_dir') == regression['job']['work_dir']:
                    completed_intent.unlink()
        if regression['stage'] not in ('complete', 'reverted') and (
                not regression.get('stamp') or process_stamp(regression['pid']) != regression['stamp']):
            import runner
            from update_worker import check_tree
            backup = Path(regression['backup'])
            backup.relative_to(ROOT_STATE / 'code-backups')
            check_tree(backup)
            restore_runtime(regression)
            original_write = runner._write_state
            runner._write_state = lambda path, **patches: as_service(lambda: original_write(path, **patches))
            try:
                runner._restore(regression['job'], backup, Path(regression['job']['state_file']), strict=True)
                runner._write_state(Path(regression['job']['state_file']), status='failed', action=None, pid=None,
                                    last_error='Обратная миграция прервана; восстановлена 7.0 с данными и правами')
                reverted(regression)
            finally:
                runner._write_state = original_write
    if (ROOT_STATE / "challenge-firewall.json").exists() or (ROOT_STATE / "challenge-service.json").exists():
        from firewall import LocalApiFirewall as LocalFirewall
        LocalFirewall(ROOT_STATE / "challenge-firewall.json").sync(None)
        (ROOT_STATE / "challenge-firewall.json").unlink(missing_ok=True)
        pending_challenge = ROOT_STATE / "challenge-service.json"
        if pending_challenge.exists():
            protected(pending_challenge)
            if run(["/usr/bin/systemctl", "start", SERVICE])["returncode"]:
                raise RuntimeError("Не удалось восстановить службу после certbot")
            pending_challenge.unlink()
    update_intent = ROOT_STATE / "update-recovery.json"
    if update_intent.exists():
        data = json.loads(protected(update_intent).read_text())
        if not data.get("stamp") or process_stamp(data["pid"]) != data["stamp"]:
            import runner
            from update_worker import check_tree
            backup = Path(data["backup"])
            backup.relative_to(ROOT_STATE / "code-backups")
            check_tree(backup)
            original_write = runner._write_state
            runner._write_state = lambda path, **patches: as_service(lambda: original_write(path, **patches))
            try:
                runner._restore(data["job"], backup, Path(data["job"]["state_file"]), strict=True)
                runner._write_state(Path(data["job"]["state_file"]), status="failed", action=None, pid=None,
                                    last_error="Обновление прервано; восстановлена защищённая копия кода")
                update_intent.unlink()
                journal(0, "update.recovery", "recovered")
            finally:
                runner._write_state = original_write
    code_intent = ROOT_STATE / "code-restore-recovery.json"
    if code_intent.exists():
        data = json.loads(protected(code_intent).read_text())
        if not data.get("stamp") or process_stamp(data["pid"]) != data["stamp"]:
            from code_snapshots import rollback
            rollback()
    for filename in ("transport-recovery.json", "restore-recovery.json"):
        path = ROOT_STATE / filename
        if not path.exists():
            continue
        data = json.loads(protected(path).read_text())
        if data.get("stamp") and process_stamp(data["pid"]) == data["stamp"]:
            continue
        if filename == "transport-recovery.json":
            atomic(UNIT, data["unit"].encode(), 0o644)
            if run(["/usr/bin/systemctl", "daemon-reload"])["returncode"]:
                continue
            result = run(["/usr/bin/systemctl", "restart", SERVICE])
        else:
            result = run(["/usr/bin/systemctl", "start", SERVICE])
        if not result["returncode"]:
            path.unlink()
            journal(0, filename, "recovered")


def legacy_update_needs_recovery():
    """An already-running legacy root updater may restore its old source.

    Only root can change this code tree or the migration journal. A supported
    helper update holds control.lock, so its temporary swap cannot trigger this.
    """
    regression = ROOT_STATE / 'regression.json'
    if regression.exists():
        transition = json.loads(protected(regression).read_text())
        if transition.get('stage') not in ('complete', 'reverted'):
            # A deliberate legacy rollback may have swapped code while the
            # runtime marker is still present. Its full 7.0 snapshot owns
            # recovery, rather than the original forward migration journal.
            return False
    path = ROOT_STATE / 'migration.json'
    if not path.exists() or not (APP / 'data/runtime').is_dir():
        return False
    state = json.loads(protected(path).read_text())
    if state.get('status') != 'complete' or not state.get('automatic'):
        return False
    if (APP / 'core/local_privileges.py').exists():
        return False
    version = APP / 'core/version.py'
    if not version.is_file():
        return False
    protected(version)
    return True


def launch_legacy_recovery():
    with (ROOT_STATE / 'control.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not legacy_update_needs_recovery():
            return
        protected(HELPER_HOME / 'install.py')
        result = run(['/usr/bin/systemd-run', '--collect', '--service-type=exec',
                      '--unit=bot4vps-privilege-recovery', '/usr/bin/python3', '-I',
                      str(HELPER_HOME / 'install.py'), '--recover-legacy-update'], 15)
        if result['returncode']:
            journal(0, 'migration.legacy-recovery', 'launch_failed')


def protected(path: Path, *, directory=False):
    """Reject writable ancestors, symlinks and aliased regular files."""
    for component in (path, *path.parents):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("Незащищённый путь помощника")
    info = path.lstat()
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("Ожидается защищённый каталог")
    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("Ожидается защищённый обычный файл")
    return path


def atomic(path: Path, data: bytes, mode=0o600):
    protected(path.parent, directory=True)
    if path.exists() or path.is_symlink():
        protected(path)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def run(args, timeout=90):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=ENV, cwd="/")
    return {"returncode": result.returncode, "stdout": result.stdout[-32768:], "stderr": result.stderr[-32768:]}


def as_service(fn):
    """Runtime I/O happens with the application's UID, including symlink failures."""
    account = pwd.getpwnam(USER)
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            os.setgroups([])
            os.setgid(account.pw_gid)
            os.setuid(account.pw_uid)
            result = {"ok": True, "value": fn()}
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        with os.fdopen(write_fd, "wb") as pipe:
            pipe.write(json.dumps(result).encode())
        os._exit(0)
    os.close(write_fd)
    with os.fdopen(read_fd, "rb") as pipe:
        data = pipe.read(MAX_MESSAGE + 1)
    os.waitpid(pid, 0)
    result = json.loads(data)
    if not result.get("ok"):
        raise ValueError(result.get("error") or "Ошибка рабочих данных")
    return result.get("value")


def journal(uid, operation, status):
    # Never log parameters, TLS keys, setup codes, or the untrusted exception text.
    line = json.dumps({"time": time.time(), "uid": uid, "operation": operation, "status": status}) + "\n"
    path = ROOT_STATE / "audit.jsonl"
    if path.exists():
        protected(path)
    with path.open("a") as stream:
        os.chmod(path, 0o600)
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())


def service_control(params):
    ensure_idle()
    fields(params, ("args",))
    args = params["args"]
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise ValueError("Некорректная команда systemd")
    allowed = [[a, SERVICE] for a in ("start", "stop", "restart", "enable", "disable")]
    allowed += [["--no-block", "restart", SERVICE], ["disable", "--now", SERVICE], ["daemon-reload"]]
    if args not in allowed:
        raise ValueError("Команда systemd не разрешена")
    restore_intent = ROOT_STATE / "restore-recovery.json"
    if args == ["stop", SERVICE] and CLIENT_PID:
        try:
            command = Path(f"/proc/{CLIENT_PID}/cmdline").read_bytes().split(b"\0")
        except OSError:
            command = []
        if b"core.backup.self_restore_runner" in command:
            track(restore_intent)
    # Do not wait for the app while it may need this same broker during
    # shutdown/startup (Mobile API firewall). The unprivileged client waits
    # for systemd's job after this reply, outside the broker lock.
    command = ["--no-block", *args] if args in [[verb, SERVICE] for verb in ("start", "stop", "restart")] else args
    result = run(["/usr/bin/systemctl", *command])
    return result


def configure(params):
    ensure_idle()
    fields(params, ("text",))
    text = unit_text(transport(params["text"]))
    settings_path = ROOT_STATE / "settings.json"
    if settings_path.exists():
        settings = json.loads(protected(settings_path).read_text())
        storage = settings.get("storage_root")
        if storage and storage != "/var/backups/bot4vps":
            # Root-approved during installation, not supplied by this request.
            text = text.replace("ReadWritePaths=", f'ReadWritePaths="{storage}" ')
    if CLIENT_PID:
        pending = ROOT_STATE / "transport-recovery.json"
        if pending.exists():
            data = json.loads(protected(pending).read_text())
            same = data["pid"] == CLIENT_PID and data.get("stamp") == process_stamp(CLIENT_PID)
            if not same and data.get("stamp") and process_stamp(data["pid"]) == data["stamp"]:
                raise ValueError("Unit изменяется другой операцией")
            if not same:
                # Keep the original unit as rollback target, but transfer the
                # intent to this live transaction after the old owner died.
                track(pending, unit=data["unit"])
        else:
            track(pending, unit=protected(UNIT).read_text())
    atomic(UNIT, text.encode(), 0o644)
    return True


def validate_unit(params):
    fields(params, ("text",))
    unit_text(transport(params["text"]))
    return True


def setup(params):
    fields(params, ("action",), ("code",))
    dropin = UNIT.with_name(UNIT.name + ".d")
    path = dropin / "setup.conf"
    if params["action"] == "read":
        if set(params) != {"action"}:
            raise ValueError("Лишний параметр")
        if not path.exists():
            return None
        protected(path)
        match = re.search(r"^Environment=B4V_SETUP_CODE=([A-Za-z0-9_-]+)$", path.read_text(), re.M)
        return {"code": match.group(1) if match else None, "mtime": path.stat().st_mtime}
    if params["action"] == "write":
        code = params.get("code")
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", code):
            raise ValueError("Некорректный код установки")
        dropin.mkdir(mode=0o755, exist_ok=True)
        atomic(path, f"[Service]\nEnvironment=B4V_SETUP_CODE={code}\n".encode())
    elif params["action"] == "remove" and set(params) == {"action"}:
        if path.exists():
            protected(path).unlink()
    else:
        raise ValueError("Недопустимая операция установки")
    result = run(["/usr/bin/systemctl", "daemon-reload"])
    if result["returncode"]:
        raise RuntimeError("Не удалось перечитать systemd")
    return True


def firewall(params):
    fields(params, ("port",))
    value = params["port"]
    if value is not None:
        port(value)
    # Installed copy imports only the installed atomic-json module.
    from firewall import LocalApiFirewall as LocalFirewall
    return LocalFirewall(ROOT_STATE / "mobile-firewall.json").sync(value)


def web_firewall(params):
    ensure_idle()
    fields(params, ("port", "opening"))
    value = port(params["port"])
    if type(params["opening"]) is not bool:
        raise ValueError("Некорректное действие firewall")
    from firewall import LocalApiFirewall as LocalFirewall
    legacy = ROOT_STATE / "legacy-web-firewall.json"
    if legacy.exists():
        previous = json.loads(protected(legacy).read_text())["port"]
        if params["opening"] and value == previous:
            return "ufw"
        if not params["opening"] and value != previous:
            raise ValueError("Запрошен другой прежний порт Web firewall")
    manager = LocalFirewall(ROOT_STATE / "web-firewall.json")
    if not params["opening"]:
        # No unrelated rules are removed, including a different panel port.
        rules = manager._read()
        if rules and not all(rule["port"] == value for rule in rules):
            raise ValueError("Запрошен другой порт Web firewall")
    manager.sync(value if params["opening"] else None)
    if legacy.exists():
        previous = port(previous)
        expected = ["ufw", "allow", f"{previous}/tcp", "comment", "Bot4VPS Web UI"]
        result = run(["/usr/sbin/ufw", "show", "added"], 20)
        if result["returncode"]:
            raise ValueError("Не удалось проверить прежнее правило Web firewall")
        lines = [shlex.split(line) for line in result["stdout"].splitlines() if line.startswith("ufw ")]
        competing = [line for line in lines if f"{previous}/tcp" in line]
        if competing and competing != [expected]:
            raise ValueError("Прежнее правило UFW изменено; очистка остановлена")
        if expected in lines:
            result = run(["/usr/sbin/ufw", "--force", "delete", "allow", f"{previous}/tcp", "comment", "Bot4VPS Web UI"], 20)
            if result["returncode"]:
                raise ValueError("Не удалось убрать прежнее правило Web firewall")
        legacy.unlink()
    return manager._detect() if params["opening"] else "none"


def remove_installation(params):
    fields(params, ("kind",))
    if params["kind"] not in ("service", "all"):
        raise ValueError("Некорректный режим удаления")
    run(["/usr/bin/systemctl", "disable", "--now", SERVICE])
    if UNIT.exists():
        protected(UNIT).unlink()
    wrapper = Path("/usr/local/bin/bot4vps")
    if wrapper.exists():
        protected(wrapper).unlink()
    run(["/usr/bin/systemctl", "daemon-reload"])
    if params["kind"] == "all":
        protected(APP, directory=True)
        shutil.rmtree(APP)
    return True


def code_validate(params):
    from code_snapshots import validate
    return validate(params)


def code_checkpoint(params):
    fields(params)
    from code_snapshots import create
    return create()


def code_restore(params):
    ensure_idle()
    from code_snapshots import restore
    return restore(params)


def finish_restore(params):
    ensure_idle()
    fields(params, ("success",))
    if type(params["success"]) is not bool:
        raise ValueError("Некорректный результат восстановления")
    from code_snapshots import finish
    finish(params["success"])
    pending = ROOT_STATE / "transport-recovery.json"
    if params["success"]:
        commit_transport({})
    elif pending.exists():
        data = json.loads(protected(pending).read_text())
        if data["pid"] != CLIENT_PID or data.get("stamp") != process_stamp(CLIENT_PID):
            raise ValueError("Unit принадлежит другой операции")
        atomic(UNIT, data["unit"].encode(), 0o644)
        if run(["/usr/bin/systemctl", "daemon-reload"])["returncode"]:
            raise RuntimeError("Не удалось восстановить unit")
        if run(["/usr/bin/systemctl", "restart", SERVICE])["returncode"]:
            raise RuntimeError("Не удалось запустить прежнюю службу")
        pending.unlink()
    service_intent = ROOT_STATE / "restore-recovery.json"
    if service_intent.exists():
        data = json.loads(protected(service_intent).read_text())
        if data["pid"] == CLIENT_PID and data.get("stamp") == process_stamp(CLIENT_PID):
            service_intent.unlink()
    return True


def timezone(params):
    fields(params, ("name",))
    from zoneinfo import ZoneInfo
    name = params["name"]
    if not isinstance(name, str) or len(name) > 128 or ".." in name or name.startswith("/"):
        raise ValueError("Некорректный часовой пояс")
    ZoneInfo(name)
    return run(["/usr/bin/timedatectl", "set-timezone", name], 10)


def read_journal(params):
    fields(params, ("cursor",))
    cursor = params["cursor"]
    if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 512 or not re.fullmatch(r"[A-Za-z0-9=;_-]+", cursor)):
        raise ValueError("Некорректный cursor журнала")
    args = ["/usr/bin/journalctl", "-u", SERVICE, "--no-pager", "-o", "json", "-n", "200" if cursor else "30"]
    if cursor:
        args.append("--after-cursor=" + cursor)
    result = run(args, 10)
    if result["returncode"]:
        raise ValueError("Не удалось прочитать журнал службы")
    lines = []
    for raw in result["stdout"].splitlines():
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        message = entry.get("MESSAGE", "")
        if isinstance(message, str):
            lines.append(message[:4096])
        cursor = entry.get("__CURSOR", cursor)
    return {"lines": lines, "cursor": cursor}


def certbot(params):
    fields(params, ("domain", "email", "force"))
    name = domain(params["domain"])
    email, force = params["email"], params["force"]
    if type(force) is not bool or (email is not None and (not isinstance(email, str) or len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+", email) or email.startswith("-"))):
        raise ValueError("Некорректные параметры сертификата")
    executable = APP / "venv/bin/certbot"
    if not executable.exists():
        # The published 6.5 updater replaces core/, but does not know new
        # top-level dependency files. Carry this lock inside its allowlist.
        bundled = APP / "core/migration/privileged/requirements-certbot.txt"
        lock = protected(bundled if bundled.exists() or bundled.is_symlink()
                         else APP / "requirements-certbot.txt")
        result = run([str(APP / "venv/bin/python"), "-I", "-m", "pip", "--isolated", "install", "--require-hashes", "--no-input", "-r", str(lock)], 900)
        if result["returncode"]:
            raise RuntimeError("Не удалось установить certbot")
    protected(executable)
    certificate_root = ROOT_STATE / "letsencrypt"
    args = [str(executable), "certonly", "--standalone", "-d", name, "--non-interactive", "--agree-tos", "--force-renewal" if force else "--keep-until-expiring",
            "--config-dir", str(certificate_root), "--work-dir", str(ROOT_STATE / "certbot-work"), "--logs-dir", str(ROOT_STATE / "certbot-logs")]
    args += ["-m", email] if email else ["--register-unsafely-without-email"]
    from firewall import LocalApiFirewall as LocalFirewall
    lease = LocalFirewall(ROOT_STATE / "challenge-firewall.json")
    own_port80 = transport(protected(UNIT).read_text()).get("port") == 80
    stopped = False
    try:
        lease.sync(80)
        if own_port80:
            atomic(ROOT_STATE / "challenge-service.json", json.dumps({"restart": True}).encode())
            stopped_result = run(["/usr/bin/systemctl", "stop", SERVICE])
            if stopped_result["returncode"]:
                raise ValueError("Не удалось освободить HTTP-порт панели")
            stopped = True
        result = run(args, 600)
    finally:
        try:
            lease.sync(None)
            (ROOT_STATE / "challenge-firewall.json").unlink(missing_ok=True)
        finally:
            if stopped:
                started = run(["/usr/bin/systemctl", "start", SERVICE])
                if not started["returncode"]:
                    (ROOT_STATE / "challenge-service.json").unlink(missing_ok=True)
    if result["returncode"]:
        return {"ok": False, "stdout": result["stdout"], "stderr": result["stderr"]}
    # Certbot live files are legitimate links into its protected archive only.
    archive = certificate_root / "archive"
    output = {}
    for key, filename in (("cert", "fullchain.pem"), ("key", "privkey.pem")):
        resolved = (certificate_root / "live" / name / filename).resolve(strict=True)
        resolved.relative_to(archive)
        protected(resolved)
        blob = resolved.read_bytes()
        if len(blob) > 65536:
            raise ValueError("Слишком большой сертификат")
        output[key] = base64.b64encode(blob).decode()
    return {"ok": True, "stdout": result["stdout"], "stderr": result["stderr"], **output}


def launch(params):
    ensure_idle()
    fields(params, ("kind", "job_path"))
    kind, job_path = params["kind"], params["job_path"]
    modules = {"port": "core.web_port", "tls": "core.web_tls", "self_restore": "core.backup.self_restore_runner"}
    if kind not in modules:
        raise ValueError("Неизвестный раннер")
    if kind == "self_restore":
        if not isinstance(job_path, str) or ".." in Path(job_path).parts:
            raise ValueError("Некорректный job")
        Path(job_path).relative_to(APP / "data/backup")
        args = [job_path]
    elif job_path is not None:
        raise ValueError("Раннер не принимает job")
    else:
        args = []
    # transient services survive the main service's stop and run without root.
    name = "bot4vps-" + kind.replace("_", "-") + "-" + uuid.uuid4().hex
    result = run(["/usr/bin/systemd-run", "--collect", "--service-type=exec", "--unit=" + name,
                  "--uid=" + USER, "--gid=" + USER, "--working-directory=" + str(APP),
                  "--setenv=PYTHONPATH=" + str(APP), "--setenv=PYTHONDONTWRITEBYTECODE=1",
                  "--property=NoNewPrivileges=yes", "--property=UMask=0077",
                  str(APP / "venv/bin/python"), "-m", modules[kind], *args])
    if result["returncode"]:
        raise RuntimeError("Не удалось запустить отдельный раннер")
    pid = run(["/usr/bin/systemctl", "show", name, "--property=MainPID", "--value"])
    value = int(pid["stdout"].strip() or "0")
    atomic(ROOT_STATE / "active-task.json", json.dumps({"unit": name, "pid": value}).encode())
    return {"pid": value}


def update(params):
    ensure_idle()
    fields(params, ("action", "target", "envelope"))
    if params["action"] not in ("update", "rollback"):
        raise ValueError("Некорректное действие обновления")
    from release_verify import verify_envelope, archive_url, normalized_version
    target = normalized_version(params['target'])
    legacy = params['action'] == 'rollback' and (3, 0, 0) <= tuple(map(int, target.split('.'))) < (7, 0, 0)
    if legacy:
        from legacy_release import resolve
        old = resolve(params['action'], target)
        payload = {'version': old['version']}
        download_url = old['archive_url']
    else:
        payload = verify_envelope(params["envelope"], params["target"])
        download_url = archive_url(payload)
    settings = transport(protected(UNIT).read_text())
    work = ROOT_STATE / "updates" / uuid.uuid4().hex
    work.mkdir(parents=True, mode=0o700)
    version_source = protected(APP / "core/version.py").read_text()
    version = re.search(r'^APP_VERSION\s*=\s*[\'"]([^\'"]+)[\'"]', version_source, re.M).group(1)
    job = {"action": params["action"], "target_version": payload["version"], "previous_version": version,
           "app_dir": str(APP), "venv_python": str(APP / "venv/bin/python"), "service_name": SERVICE,
           "release_envelope": params["envelope"], "download_url": download_url, 'legacy_rollback': legacy,
           "state_file": str(APP / "data/update/state.json"), "work_dir": str(work),
           "health_port": settings.get("port", 8080), "health_scheme": "https" if settings.get("cert") else "http",
           "health_mode": "web" if settings["mode"] == "web" else "service", "health_timeout": 120,
           "dev_no_systemd": False, "privilege_separation": True,
           "backup_root": str(ROOT_STATE / "code-backups")}
    shutil.copyfile(protected(HELPER_HOME / "release_verify.py"), work / "release_verify.py")
    atomic(work / "job.json", json.dumps(job).encode())
    name = "bot4vps-update-" + uuid.uuid4().hex
    result = run(["/usr/bin/systemd-run", "--collect", "--service-type=exec", "--unit=" + name,
                  "/usr/bin/python3", "-I", str(HELPER_HOME / "daemon.py"), "--update", str(work / "job.json")])
    if result["returncode"]:
        raise RuntimeError("Не удалось запустить защищённое обновление")
    pid = run(["/usr/bin/systemctl", "show", name, "--property=MainPID", "--value"])
    value = int(pid["stdout"].strip() or "0")
    atomic(ROOT_STATE / "active-task.json", json.dumps({"unit": name, "pid": value}).encode())
    return {"pid": value}


OPERATIONS = {"service.control": service_control, "unit.configure": configure, "unit.validate": validate_unit, "unit.commit": commit_transport, "setup.code": setup,
              "firewall.sync": firewall, "firewall.web": web_firewall, "tls.certbot": certbot,
              "task.launch": launch, "update.install": update, "installation.remove": remove_installation,
              "code.validate": code_validate, "code.restore": code_restore, "code.checkpoint": code_checkpoint,
              "host.timezone": timezone, "journal.read": read_journal, "restore.finish": finish_restore}


def prepare_runtime():
    """Fixed boot provisioning before the dependent main unit starts."""
    if os.geteuid() != 0:
        raise ValueError("Runtime provisioning требует root")
    account = pwd.getpwnam(USER)
    path = Path("/run/lock/bot4vps")
    protected(path.parent.parent, directory=True)
    parent = os.open(path.parent, os.O_DIRECTORY | os.O_NOFOLLOW)
    if os.fstat(parent).st_uid != 0:
        os.close(parent)
        raise ValueError("Незащищённый родитель runtime lock directory")
    try:
        try:
            os.mkdir(path.name, mode=0o700, dir_fd=parent)
        except FileExistsError:
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid not in (0, account.pw_uid):
                raise ValueError("Недопустимый runtime lock directory")
        child = os.open(path.name, os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            if os.fstat(child).st_uid not in (0, account.pw_uid):
                raise ValueError("Недопустимый владелец runtime lock directory")
            os.fchown(child, account.pw_uid, account.pw_gid)
            os.fchmod(child, 0o700)
        finally:
            os.close(child)
    finally:
        os.close(parent)


def handle_connection(connection, account):
    global CLIENT_PID
    with connection:
        operation = "invalid"
        uid = -1
        try:
            connection.settimeout(5)
            CLIENT_PID, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid not in (0, account.pw_uid):
                raise ValueError("UID клиента не разрешён")
            body = bytearray()
            while not body.endswith(b"\n"):
                chunk = connection.recv(min(65536, MAX_MESSAGE + 1 - len(body)))
                if not chunk or len(body) + len(chunk) > MAX_MESSAGE:
                    raise ValueError("Некорректный запрос")
                body.extend(chunk)
            operation, params = decode(body)
            if operation not in OPERATIONS:
                raise ValueError("Операция не разрешена")
            journal(uid, operation, "started")
            independent = operation in ("firewall.sync", "journal.read") or (operation == "setup.code" and params.get("action") == "read")
            lock_name = "firewall.lock" if operation == "firewall.sync" else "read.lock" if independent else "control.lock"
            with (ROOT_STATE / lock_name).open("a") as lock:
                deadline = time.monotonic() + 2
                while True:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise ValueError("Другая локальная системная операция ещё выполняется")
                        time.sleep(0.02)
                # Unresolved recovery is a mutation fence. Reads remain
                # available to diagnose an interrupted operation.
                if not independent and operation not in ("unit.validate", "code.validate", "restore.finish"):
                    recover()
                if not independent and operation not in ("unit.validate", "code.validate"):
                    ensure_idle()
                value = OPERATIONS[operation](params)
            journal(uid, operation, "finished")
            reply = {"ok": True, "result": value}
        except Exception as exc:
            journal(uid, operation, "failed")
            reply = {"ok": False, "error": str(exc)}
        try:
            connection.sendall(json.dumps(reply, ensure_ascii=False).encode() + b"\n")
        except OSError:
            pass


SERVER_PID = None


def reload_helper():
    if SERVER_PID is not None:
        os.kill(SERVER_PID, signal.SIGHUP)
    else:
        run(["/usr/bin/systemctl", "--no-block", "restart", "bot4vps-helper"])


def serve():
    global CLIENT_PID, SERVER_PID
    if os.geteuid() != 0:
        raise RuntimeError("Помощник требует root")
    protected(HELPER_HOME, directory=True)
    ROOT_STATE.mkdir(mode=0o700, exist_ok=True)
    protected(ROOT_STATE, directory=True)
    SOCKET.parent.mkdir(mode=0o750, exist_ok=True)
    account = pwd.getpwnam(USER)
    os.chown(SOCKET.parent, 0, account.pw_gid)
    os.chmod(SOCKET.parent, 0o750)
    if SOCKET.exists():
        if not stat.S_ISSOCK(SOCKET.lstat().st_mode) or SOCKET.lstat().st_uid != 0:
            raise RuntimeError("Недопустимый файл сокета")
        SOCKET.unlink()
    SERVER_PID = os.getpid()
    reload_requested = False
    def request_reload(signum, frame):
        nonlocal reload_requested
        reload_requested = True
    signal.signal(signal.SIGHUP, request_reload)
    children = set()
    recovery_pid = None
    legacy_missing_since = None
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(SOCKET))
        os.chown(SOCKET, 0, account.pw_gid)
        os.chmod(SOCKET, 0o660)
        listener.listen(16)
        listener.settimeout(2)
        while True:
            try:
                for pid in list(children):
                    if os.waitpid(pid, os.WNOHANG)[0]:
                        children.remove(pid)
                        if pid == recovery_pid:
                            recovery_pid = None
                if reload_requested and not children:
                    listener.close()
                    os.execv("/usr/bin/python3", ["/usr/bin/python3", "-I", str(HELPER_HOME / "daemon.py")])
                if legacy_update_needs_recovery():
                    if legacy_missing_since is None:
                        legacy_missing_since = time.monotonic()
                    elif time.monotonic() - legacy_missing_since >= 2:
                        try:
                            launch_legacy_recovery()
                        except BlockingIOError:
                            pass
                        legacy_missing_since = time.monotonic()
                else:
                    legacy_missing_since = None
                has_recovery = any((ROOT_STATE / name).exists() for name in (
                    "update-recovery.json", "transport-recovery.json", "restore-recovery.json",
                    "code-restore-recovery.json", "challenge-service.json", "challenge-firewall.json"))
                regression_path = ROOT_STATE / 'regression.json'
                if regression_path.exists():
                    from regression import load
                    has_recovery = has_recovery or load()['stage'] not in ('complete', 'reverted')
                if recovery_pid is None and has_recovery:
                    recovery_pid = os.fork()
                    if recovery_pid == 0:
                        listener.close()
                        try:
                            with (ROOT_STATE / "control.lock").open("a") as lock:
                                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                                recover()
                        except BlockingIOError:
                            pass
                        except Exception:
                            journal(0, "recovery", "failed")
                        finally:
                            os._exit(0)
                    children.add(recovery_pid)
                if len(children) >= 32:
                    # Bounded worker count, including stalled/slow peers.
                    time.sleep(0.05)
                    continue
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            pid = os.fork()
            if pid == 0:
                listener.close()
                try:
                    handle_connection(connection, account)
                finally:
                    os._exit(0)
            connection.close()
            children.add(pid)


if __name__ == "__main__":
    if sys.argv[1:] == ["--prepare-runtime"]:
        prepare_runtime()
        raise SystemExit(0)
    if len(sys.argv) == 3 and sys.argv[1] == "--update":
        protected(Path(sys.argv[2]))
        from update_worker import execute
        raise SystemExit(execute(Path(sys.argv[2])))
    if len(sys.argv) != 1:
        raise SystemExit(2)
    serve()
