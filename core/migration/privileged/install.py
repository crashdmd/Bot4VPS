"""Root installation/migration with an ownership journal and health rollback.

This is an owner-invoked installer, never an operation accepted over the socket.
"""
from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import pwd
import shlex
import shutil
import stat
import subprocess
import sqlite3
import sys
import time
import uuid
from contextlib import closing
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
if __package__:
    from .protocol import APP, HELPER_HOME, ROOT_STATE, UNIT, USER, transport, unit_text
else:
    from protocol import APP, HELPER_HOME, ROOT_STATE, UNIT, USER, transport, unit_text

HELPER_UNIT = Path("/etc/systemd/system/bot4vps-helper.service")
RUNTIME = ("data", "keys", "logs", "scripts")
JSON_FILES = ("config.json", "servers.json", "monitor.json")
WRAPPER = Path("/usr/local/bin/bot4vps")
SOURCE = Path(__file__).resolve().parents[3]

HELPER_UNIT_TEXT = """[Unit]
Description=Bot4VPS local privilege helper
After=network.target

[Service]
Type=simple
User=root
Group=root
ExecStart=/usr/bin/python3 -I /usr/lib/bot4vps-helper/daemon.py
ExecStartPre=/usr/bin/python3 -I /usr/lib/bot4vps-helper/daemon.py --prepare-runtime
Environment=PYTHONDONTWRITEBYTECODE=1
UMask=0077
RuntimeDirectory=bot4vps-helper
RuntimeDirectoryMode=0750
Restart=on-failure
RestartSec=2
NoNewPrivileges=yes
ProtectHome=yes
RestrictSUIDSGID=yes

[Install]
WantedBy=multi-user.target
"""


def systemctl(*args):
    return subprocess.run(["/usr/bin/systemctl", *args], check=True, capture_output=True, text=True, timeout=90)


def walk(root):
    yield root
    if root.is_dir() and not root.is_symlink():
        for directory, names, files in os.walk(root, followlinks=False):
            for name in names + files:
                yield Path(directory) / name


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def restore_owner(path, uid, gid, mode, link):
    """Traverse with no-follow dirfds; changed runtime parents cannot escape."""
    descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        if link:
            os.chown(path.name, uid, gid, dir_fd=descriptor, follow_symlinks=False)
        else:
            item = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
            try:
                info = os.fstat(item)
                if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode) and info.st_nlink == 1):
                    raise ValueError('Подмена файла при откате владельца')
                os.fchown(item, uid, gid)
                os.fchmod(item, mode)
            finally:
                os.close(item)
    finally:
        os.close(descriptor)


def validate_runtime(root):
    for path in walk(root):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            # Explicitly retain links inside the same runtime root only.
            path.resolve(strict=True).relative_to(root.resolve())
        elif not stat.S_ISDIR(info.st_mode) and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise ValueError("Специальный файл или hardlink в рабочих данных: " + str(path))


def validate_storage(root):
    if len(root.parts) < 3 or root.parts[1] in {"etc", "usr", "bin", "sbin", "proc", "sys", "dev", "run", "root"}:
        raise ValueError("Backup storage должен быть отдельным каталогом данных")
    if root.exists():
        # Retain an existing temporary workspace along with the archives.
        allowed = {"bot4vps", "servers", "imports", "staging", "quarantine", "tmp"}
        if any(item.name not in allowed for item in root.iterdir()):
            raise ValueError("В backup storage есть посторонние файлы; их владельцы не изменяются автоматически")
        temporary = root / "tmp"
        if temporary.is_symlink() or temporary.exists() and not temporary.is_dir():
            raise ValueError("tmp в backup storage должен быть обычным каталогом")
    validate_runtime(root) if root.exists() else None


def remember(path, journal):
    key = str(path)
    if key in journal["ownership"]:
        return
    info = path.lstat()
    journal["ownership"][key] = [info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), stat.S_ISLNK(info.st_mode)]


def save(journal):
    path = ROOT_STATE / "migration.json"
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(journal, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(0o600)
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def backup_file(path):
    if not path.exists():
        return None
    if path.is_symlink():
        raise ValueError("Системный файл не должен быть ссылкой: " + str(path))
    return {"data": base64.b64encode(path.read_bytes()).decode(), "mode": stat.S_IMODE(path.stat().st_mode)}


def refresh_helper():
    """Install copies from root-owned source; helper has no application import path."""
    if __package__:
        from .daemon import atomic, protected
    else:
        from daemon import atomic, protected
    HELPER_HOME.parent.mkdir(parents=True, exist_ok=True)
    HELPER_HOME.mkdir(mode=0o755, exist_ok=True)
    protected(HELPER_HOME, directory=True)
    helper_source = SOURCE / "core/migration/privileged"
    if not (helper_source / "daemon.py").is_file():
        helper_source = SOURCE / "privileged"  # Older protected separated snapshot.
    mapping = {name: helper_source / name for name in ("daemon.py", "protocol.py", "update_worker.py", "code_snapshots.py", "install.py", "regression.py")}
    mapping.update({"runner.py": SOURCE / "core/update/runner.py", "release_verify.py": SOURCE / "core/update/release_verify.py",
                    "bootstrap.py": SOURCE / "core/update/bootstrap.py", "legacy_release.py": SOURCE / 'core/update/legacy_release.py', "atomic_json.py": SOURCE / "core/json_store.py"})
    for name, source in mapping.items():
        if name in ('regression.py', 'legacy_release.py') and not source.exists():
            # Older protected separated snapshots predate the rollback bridge.
            # Retain the current root-owned bridge when restoring their code.
            protected(HELPER_HOME / name)
            continue
        protected(source)
        atomic(HELPER_HOME / name, source.read_bytes(), 0o644)
    source = SOURCE / "core/_internal/device_access/firewall.py"
    protected(source)
    firewall = source.read_text().replace("from core.json_store import", "from atomic_json import")
    firewall = firewall.replace('        from core.local_privileges import separated, request\n        if separated():\n            return request("firewall.sync", port=port)\n', '')
    atomic(HELPER_HOME / "firewall.py", firewall.encode(), 0o644)
    atomic(HELPER_UNIT, HELPER_UNIT_TEXT.encode(), 0o644)
    wrapper = f'''#!/bin/sh
# Data operations run as bot4vps even when the owner invokes the CLI as root.
if [ "$(id -u)" = 0 ]; then
    exec /usr/sbin/runuser -u bot4vps -- /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/opt/bot4vps PYTHONPATH=/opt/bot4vps PYTHONDONTWRITEBYTECODE=1 /opt/bot4vps/venv/bin/python -c 'import os,runpy; os.chdir("/opt/bot4vps"); runpy.run_module("ui.cli", run_name="__main__")' "$@"
fi
cd /opt/bot4vps || exit 1
exec /opt/bot4vps/venv/bin/python -m ui.cli "$@"
'''
    atomic(WRAPPER, wrapper.encode(), 0o755)


def health(settings, seconds=120):
    import ssl
    import urllib.request
    deadline = time.monotonic() + seconds
    streak = 0
    while time.monotonic() < deadline:
        try:
            systemctl("is-active", "--quiet", "bot4vps")
            if settings["mode"] == "web":
                scheme = "https" if settings.get("cert") else "http"
                context = ssl._create_unverified_context() if scheme == "https" else None
                with urllib.request.urlopen(f"{scheme}://127.0.0.1:{settings['port']}/api/upd/health", context=context, timeout=5) as response:
                    if response.status != 200:
                        raise ValueError("health")
            streak += 1
            if streak >= 2:
                return True
        except Exception:
            streak = 0
        time.sleep(2)
    return False


def snapshot_runtime(journal):
    """Consistent pre-start state; never copy a live SQLite WAL trio."""
    paths = [APP / name for name in JSON_FILES if (APP / name).is_file()]
    paths += [p for p in (APP / 'keys').rglob('*') if p.is_file() and not p.is_symlink()]
    paths += [p for p in (APP / 'data').rglob('*') if p.is_file() and not p.is_symlink()
              and p.suffix in {'.json', '.pem', '.key'}]
    paths += [p for p in (APP / 'backup').glob('*.json') if p.is_file() and not p.is_symlink()]
    db = APP / 'data/state.db'
    if db.exists():
        paths.append(db)
    total = sum(p.stat().st_size for p in paths)
    wal = db.with_name(db.name + '-wal')
    if wal.is_file():
        total += wal.stat().st_size
    if shutil.disk_usage(ROOT_STATE).free < total * 2 + 32 * 1024 * 1024:
        raise ValueError('Недостаточно места для защитной копии состояния миграции')
    root = ROOT_STATE / 'runtime-snapshots' / uuid.uuid4().hex
    root.mkdir(parents=True, mode=0o700)
    manifest = {}
    digests = {}
    for source in paths:
        relative = source.relative_to(APP).as_posix()
        target = root / relative
        target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        info = source.stat()
        if source == db:
            with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original, closing(sqlite3.connect(target)) as destination:
                original.backup(destination)
                destination.execute('PRAGMA journal_mode=DELETE')
                if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Защитная копия SQLite повреждена')
        else:
            shutil.copyfile(source, target)
        target.chmod(0o600)
        with target.open('rb') as stream:
            os.fsync(stream.fileno())
        digests[relative] = digest(target)
        manifest[relative] = [info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)]
    for directory, _, _ in os.walk(root, topdown=False):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    journal['runtime_snapshot'] = {'root': str(root), 'files': manifest,
                                   'digests': digests,
                                   'master_key_existed': (APP / 'keys/secret.key').exists(), 'state_db_existed': db.exists()}
    save(journal)


def restore_runtime_snapshot(journal):
    snapshot = journal.get('runtime_snapshot')
    if not snapshot:
        return
    if __package__:
        from .daemon import protected
    else:
        from daemon import protected
    root = Path(snapshot['root'])
    root.relative_to(ROOT_STATE / 'runtime-snapshots')
    protected(root, directory=True)
    for relative, expected in snapshot.get('digests', {}).items():
        if digest(protected(root / relative)) != expected:
            raise ValueError('Повреждена защитная копия состояния миграции')
    db = APP / 'data/state.db'
    for suffix in ('-wal', '-shm', '-journal'):
        if db.with_name(db.name + suffix).exists():
            db.with_name(db.name + suffix).unlink()
    for relative, (uid, gid, mode) in snapshot['files'].items():
        parts = Path(relative).parts
        if not parts or '..' in parts or Path(relative).is_absolute() or (parts[0] not in {'data', 'keys', 'backup'} and relative not in JSON_FILES):
            raise ValueError('Некорректный путь в защитной копии миграции')
        target = APP / relative
        if target.is_symlink() or any(parent.is_symlink() for parent in target.parents if parent != APP):
            raise ValueError('Ссылка в пути возврата данных миграции')
        source = protected(root / relative)
        target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        shutil.copyfile(source, target)
        os.chown(target, uid, gid)
        target.chmod(mode)
    if not snapshot['master_key_existed']:
        (APP / 'keys/secret.key').unlink(missing_ok=True)
    if not snapshot.get('state_db_existed', 'data/state.db' in snapshot['files']):
        db.unlink(missing_ok=True)


def helper_ready():
    """Check both UID and socket access using the actual service account."""
    probe = '''import json,socket,struct
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
 client.settimeout(10); client.connect('/run/bot4vps-helper/control.sock')
 assert struct.unpack('3i',client.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]==0
 client.sendall(json.dumps({'version':1,'operation':'unit.validate','params':{'text':'ExecStart=/opt/bot4vps/venv/bin/python bot.py'}}).encode()+b'\\n')
 reply=client.recv(4096)
 assert json.loads(reply)['ok'] is True
'''
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = subprocess.run(['/usr/sbin/runuser', '-u', USER, '--', '/usr/bin/python3', '-I', '-c', probe],
                                capture_output=True, text=True, timeout=15)
        if not result.returncode:
            return
        time.sleep(0.25)
    raise RuntimeError('Пользователь службы не смог проверить root-помощника')


def migrate_backup_paths(account, journal=None):
    """Keep old root updater paths protected; move JSON history to runtime."""
    old = APP / 'backup'
    target = APP / 'data/config-backup'
    target.mkdir(parents=True, mode=0o700, exist_ok=True)
    old.mkdir(mode=0o755, exist_ok=True)
    validate_runtime(old)
    for item in old.iterdir():
        if item.name.startswith('update_backup_'):
            continue
        destination = target / item.name
        if destination.exists() or destination.is_symlink():
            raise ValueError('Конфликт переноса истории конфигурации')
        if journal is not None:
            move = [str(item), str(destination)]
            if move not in journal.setdefault('moved_runtime_backups', []):
                journal['moved_runtime_backups'].append(move)
            save(journal)
        shutil.move(item, destination)
    for path in walk(old):
        os.chown(path, 0, 0, follow_symlinks=False)
        if not path.is_symlink():
            path.chmod(stat.S_IMODE(path.stat().st_mode) & ~0o022)
    old.chmod(0o755)
    for path in walk(target):
        os.chown(path, account.pw_uid, account.pw_gid, follow_symlinks=False)
        if not path.is_symlink():
            path.chmod(0o700 if path.is_dir() else 0o600)


def regress(job, backup):
    """Prepare reversible legacy regression for a root-created updater job."""
    if __package__:
        from .regression import prepare
    else:
        from regression import prepare
    return prepare(job, backup)


def rollback(journal, *, restart=True, restore_state=False):
    try:
        systemctl("stop", "bot4vps")
    except subprocess.SubprocessError:
        pass
    systemctl('stop', 'bot4vps-helper')
    if not journal.get('helper_was_enabled', False):
        systemctl('disable', 'bot4vps-helper')
    for name in (*RUNTIME, 'backup'):
        root = APP / name
        if root.is_symlink():
            raise ValueError('Подмена рабочего каталога перед откатом')
        if root.exists():
            validate_runtime(root)
    for name in JSON_FILES:
        alias, data = APP / name, APP / "data/runtime" / name
        if name in journal["moved_json"]:
            if alias.is_symlink() and alias.resolve() == data:
                alias.unlink()
            elif alias.exists() and not data.exists():
                continue  # Intent persisted before the move, no mutation yet.
            elif alias.exists() or not data.exists():
                raise ValueError("Путь JSON изменился после миграции")
            shutil.move(data, alias)
    for source, destination in journal.get("moved_code_backups", []):
        if Path(destination).exists():
            if Path(source).exists():
                raise ValueError('Защитная копия кода имеет два расположения')
            shutil.move(destination, source)
    for source, destination in journal.get('moved_runtime_backups', []):
        if Path(destination).exists():
            if Path(source).exists():
                raise ValueError('Рабочая копия данных имеет два расположения')
            shutil.move(destination, source)
    for raw, (uid, gid, mode, link) in journal["ownership"].items():
        path = Path(raw)
        if path.exists() or path.is_symlink():
            restore_owner(path, uid, gid, mode, link)
    for raw, backup in journal["system_files"].items():
        path = Path(raw)
        if backup is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(backup["data"]))
            path.chmod(backup["mode"])
    # Removing the marker restores the old core paths on the next process start.
    runtime = APP / "data/runtime"
    if not journal["runtime_existed"] and runtime.exists():
        # Keep diagnostic files/locks created by the unsuccessful first start.
        destination = ROOT_STATE / ("migration-runtime-leftovers-" + str(time.time_ns()))
        shutil.move(runtime, destination)
    if restore_state:
        restore_runtime_snapshot(journal)
    journal["status"] = "rolled_back"
    save(journal)
    systemctl("daemon-reload")
    if journal.get('helper_was_active', False):
        systemctl('start', 'bot4vps-helper')
    if restart and journal["was_active"]:
        systemctl("start", "bot4vps")


def migrate(start=True, *, automatic=False):
    if os.geteuid() != 0 or SOURCE != APP:
        raise ValueError("Миграция запускается владельцем из /opt/bot4vps от root")
    ROOT_STATE.mkdir(parents=True, mode=0o700, exist_ok=True)
    ROOT_STATE.chmod(0o700)
    if __package__:
        from .daemon import protected
    else:
        from daemon import protected
    protected(ROOT_STATE, directory=True)
    path = ROOT_STATE / 'migration.lock'
    if path.exists() or path.is_symlink():
        protected(path)
    with path.open('a') as lock:
        path.chmod(0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Миграция уже выполняется отдельным установщиком') from exc
        saved = ROOT_STATE / 'migration.json'
        if saved.exists():
            previous = json.loads(protected(saved).read_text())
            if previous['status'] in ('preparing', 'switched'):
                rollback(previous, restart=False, restore_state=True)
                if automatic:
                    raise RuntimeError('Прерванная миграция откачена; updater должен вернуть предыдущий код')
            elif previous['status'] == 'rolled_back' and automatic:
                raise RuntimeError('Повтор автоматической миграции после отказа запрещён')
        print('Обновление: проверка установки и состояния миграции — готово', flush=True)
        result = _migrate(start, automatic=automatic)
        if start:
            try:
                if __package__:
                    from .regression import rotate_archives
                else:
                    from regression import rotate_archives
                rotate_archives()
            except Exception:
                # Retention is maintenance after successful health, not a
                # reason to roll back a completed migration or expose secrets.
                print('Ротация защитных снимков отложена до следующей успешной миграции', flush=True)
        return result


def _migrate(start, *, automatic=False):
    if (APP / "data/runtime").is_dir():
        if __package__:
            from .daemon import configure, protected
        else:
            from daemon import configure, protected
        settings_file = protected(ROOT_STATE / "settings.json")
        storage = Path(json.loads(settings_file.read_text())["storage_root"])
        validate_storage(storage)
        account = pwd.getpwnam(USER)
        if start:
            systemctl('stop', 'bot4vps')
        saved = ROOT_STATE / 'migration.json'
        previous = json.loads(protected(saved).read_text()) if saved.exists() else None
        migrate_backup_paths(account, previous)
        for root in [APP / name for name in RUNTIME] + [storage, Path("/run/lock/bot4vps")]:
            root.mkdir(parents=True, mode=0o700, exist_ok=True)
            validate_runtime(root)
            for path in walk(root):
                os.chown(path, account.pw_uid, account.pw_gid, follow_symlinks=False)
                if not path.is_symlink():
                    path.chmod(stat.S_IMODE(path.stat().st_mode) & 0o700 or (0o700 if path.is_dir() else 0o600))
        refresh_helper()
        configure({"text": UNIT.read_text()})
        if __package__:
            from .code_snapshots import create
        else:
            from code_snapshots import create
        create()
        systemctl("daemon-reload")
        systemctl("enable", "--now", "bot4vps-helper")
        systemctl('restart', 'bot4vps-helper')
        helper_ready()
        if start:
            settings = transport(UNIT.read_text())
            systemctl('restart', 'bot4vps')
            if not health(settings):
                raise RuntimeError('Проверка повторного запуска мигрированной службы не пройдена')
        return
    try:
        account = pwd.getpwnam(USER)
    except KeyError:
        subprocess.run(["/usr/sbin/useradd", "--system", "--user-group", "--home-dir", str(APP), "--no-create-home", "--shell", "/usr/sbin/nologin", USER], check=True)
        account = pwd.getpwnam(USER)
    if account.pw_uid == 0:
        raise ValueError("Некорректный системный пользователь")
    print('Подготовка системного пользователя — готово', flush=True)
    settings = transport(UNIT.read_text())
    config = APP / "config.json"
    if config.is_symlink():
        raise ValueError("До миграции config.json не должен быть ссылкой")
    storage = Path((json.loads(config.read_text()).get("backup") or {}).get("storage", {}).get("root") or "/var/backups/bot4vps")
    if not storage.is_absolute() or ".." in storage.parts or any(c in str(storage) for c in '\n\r%$\\"'):
        raise ValueError("Некорректное backup storage")
    try:
        storage.relative_to(APP)
        raise ValueError("Backup storage должен находиться вне установки")
    except ValueError as exc:
        if str(exc) == "Backup storage должен находиться вне установки":
            raise
    for path in (APP, *APP.parents):
        if path.is_symlink():
            raise ValueError("Ссылка в пути установки")
    validate_storage(storage)
    for name in (*RUNTIME, 'backup'):
        path = APP / name
        if path.exists():
            if path.is_symlink():
                raise ValueError("Рабочий каталог не должен быть ссылкой")
            validate_runtime(path)
    for name in JSON_FILES:
        path = APP / name
        if path.exists() and (path.is_symlink() or path.stat().st_nlink != 1):
            raise ValueError("Ссылка в рабочем JSON")
    try:
        was_active = systemctl("is-active", "--quiet", "bot4vps").returncode == 0
    except subprocess.CalledProcessError:
        was_active = False
    journal = {"status": "preparing", "was_active": was_active, "ownership": {}, "moved_json": [],
               "automatic": automatic,
               "moved_code_backups": [], "runtime_existed": False,
               "system_files": {str(path): backup_file(path) for path in (UNIT, HELPER_UNIT, WRAPPER)}}
    for field, action in (('helper_was_active', 'is-active'), ('helper_was_enabled', 'is-enabled')):
        try:
            journal[field] = systemctl(action, '--quiet', 'bot4vps-helper').returncode == 0
        except subprocess.CalledProcessError:
            journal[field] = False
    if HELPER_HOME.exists():
        for path in HELPER_HOME.glob('*.py'):
            journal['system_files'][str(path)] = backup_file(path)
    dropins = UNIT.with_name(UNIT.name + ".d")
    if dropins.exists():
        for path in dropins.glob("*.conf"):
            text = path.read_text()
            if any(line.split("=", 1)[0].strip() in {"User", "Group", "ExecStart", "ExecStartPre", "ExecStartPost", "ExecStop", "ExecStopPost", "ReadWritePaths", "ProtectSystem", "NoNewPrivileges"}
                   for line in text.splitlines() if "=" in line):
                raise ValueError("Drop-in меняет границу привилегий; перенесите эти настройки в фиксированный unit: " + str(path))
            journal["system_files"][str(path)] = backup_file(path)
    paths = []
    # Code is protected individually. Cache/build/signing files retain their
    # existing modes; stripping world-read from private secrets is never undone.
    if __package__:
        from .code_snapshots import CODE_PATHS, IGNORED
    else:
        from code_snapshots import CODE_PATHS, IGNORED
    for name in CODE_PATHS:
        item = APP / name
        if not item.exists():
            continue
        for path in walk(item):
            if any(part in IGNORED for part in path.relative_to(APP).parts):
                continue
            if path.is_symlink():
                raise ValueError("Ссылка в дереве кода: " + str(path))
            if path.is_file() and path.stat().st_nlink != 1:
                raise ValueError("Hardlink в дереве кода")
            remember(path, journal)
            paths.append(path)
    remember(APP, journal)
    for name in (*RUNTIME, 'backup'):
        if (APP / name).exists():
            for path in walk(APP / name):
                remember(path, journal)
    for name in JSON_FILES:
        if (APP / name).exists():
            remember(APP / name, journal)
    for path in (storage, Path("/run/lock/bot4vps")):
        for component in (path, *path.parents):
            if component.is_symlink():
                raise ValueError("Ссылка в storage/lock path")
        if path.exists():
            validate_runtime(path)
            for entry in walk(path):
                remember(entry, journal)
    venv = APP / "venv"
    for path in walk(venv):
        info = path.lstat()
        if info.st_uid != 0 or info.st_mode & 0o022 and not path.is_symlink():
            raise ValueError("Venv должен принадлежать root без записи другим пользователям")
        if path.is_symlink():
            resolved = path.resolve(strict=True)
            if not str(resolved).startswith(("/usr/bin/python", "/usr/local/bin/python", str(venv) + "/")):
                raise ValueError("Непредусмотренная ссылка в venv")
    save(journal)
    if was_active:
        systemctl("stop", "bot4vps")
    try:
        snapshot_runtime(journal)
        print('Защитная копия конфигурации, ключей и SQLite — готово', flush=True)
        APP.chmod(0o755)
        os.chown(APP, 0, 0)
        for path in paths:
            os.chown(path, 0, 0)
            path.chmod(stat.S_IMODE(path.stat().st_mode) & ~0o022)
        for name in RUNTIME:
            (APP / name).mkdir(mode=0o700, exist_ok=True)
        runtime = APP / "data/runtime"
        runtime.mkdir(mode=0o700)
        for name in JSON_FILES:
            path = APP / name
            if path.exists():
                journal["moved_json"].append(name)
                save(journal)
                shutil.move(path, runtime / name)
                path.symlink_to(Path("data/runtime") / name)
        backup_root = ROOT_STATE / "code-backups"
        backup_root.mkdir(mode=0o700, exist_ok=True)
        for old in (APP / "backup").glob("update_backup_*"):
            target = backup_root / (old.name + '-' + uuid.uuid4().hex)
            if target.exists() or old.is_symlink():
                raise ValueError("Невозможно перенести прежнюю защитную копию кода")
            # A legacy updater already holds this original path. Retain a
            # root-protected copy there until its own cleanup/rollback finishes.
            shutil.copytree(old, target)
        migrate_backup_paths(account, journal)
        for root in [APP / name for name in RUNTIME] + [storage, Path("/run/lock/bot4vps")]:
            root.mkdir(parents=True, mode=0o700, exist_ok=True)
            for path in walk(root):
                os.chown(path, account.pw_uid, account.pw_gid, follow_symlinks=False)
                if not path.is_symlink():
                    path.chmod(stat.S_IMODE(path.stat().st_mode) & 0o700 or (0o700 if path.is_dir() else 0o600))
        if settings.get("cert") and not str(settings["cert"]).startswith(str(APP / "keys") + "/"):
            # Owner-invoked migration imports the existing pair once. The
            # service never gains general access to root's certificate files.
            destination = APP / "keys/web"
            destination.mkdir(mode=0o700, exist_ok=True)
            os.chown(destination, account.pw_uid, account.pw_gid)
            for key, filename in (("cert", "cert.pem"), ("key", "key.pem")):
                source = Path(settings[key])
                target = destination / filename
                target.write_bytes(source.read_bytes())
                target.chmod(0o600)
                os.chown(target, account.pw_uid, account.pw_gid)
                settings[key] = str(target)
        # Existing API rule ownership is transferred once, before the app loses root.
        ledger = APP / "data/mobile-api-firewall.json"
        if ledger.exists():
            if ledger.is_symlink():
                raise ValueError("Ссылка вместо журнала API firewall")
            shutil.copyfile(ledger, ROOT_STATE / "mobile-firewall.json")
            (ROOT_STATE / "mobile-firewall.json").chmod(0o600)
        # A legacy firewalld port carries no ownership tag: preserve it. Only
        # the exact UFW command with Bot4VPS's comment can be adopted safely.
        if settings.get("port") and shutil.which("ufw"):
            result = subprocess.run(["/usr/sbin/ufw", "show", "added"], capture_output=True, text=True, timeout=20)
            expected = ["ufw", "allow", f"{settings['port']}/tcp", "comment", "Bot4VPS Web UI"]
            lines = [shlex.split(line) for line in result.stdout.splitlines() if line.startswith("ufw ")]
            if not result.returncode and [line for line in lines if f"{settings['port']}/tcp" in line] == [expected]:
                legacy = ROOT_STATE / "legacy-web-firewall.json"
                legacy.write_text(json.dumps({"port": settings["port"]}))
                legacy.chmod(0o600)
        (ROOT_STATE / "settings.json").write_text(json.dumps({"storage_root": str(storage)}))
        (ROOT_STATE / "settings.json").chmod(0o600)
        refresh_helper()
        sys.path.append(str(HELPER_HOME))
        if __package__:
            from .code_snapshots import create
        else:
            from code_snapshots import create
        create()
        text = unit_text(settings)
        if str(storage) != "/var/backups/bot4vps":
            text = text.replace("ReadWritePaths=", f'ReadWritePaths="{storage}" ')
        UNIT.write_text(text)
        UNIT.chmod(0o644)
        systemctl("daemon-reload")
        systemctl("enable", "--now", "bot4vps-helper")
        systemctl('restart', 'bot4vps-helper')
        helper_ready()
        print('Root-помощник и Unix socket — проверены', flush=True)
        journal["status"] = "switched"
        save(journal)
        print('Переключение systemd на bot4vps — готово', flush=True)
        if start:
            systemctl("start", "bot4vps")
            if not health(settings):
                raise RuntimeError("После миграции сервис не прошёл health")
        journal["status"] = "complete"
        save(journal)
        print('Проверка запуска — готово; миграция завершена' if start else
              'Разделение подготовлено; запуск приложения отложен владельцем', flush=True)
    except BaseException:
        rollback(journal, restore_state=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-start", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--refresh-helper", action="store_true")
    parser.add_argument("--automatic", action="store_true")
    parser.add_argument('--recover-legacy-update', action='store_true')
    args = parser.parse_args()
    if args.recover_legacy_update:
        from daemon import legacy_update_needs_recovery, protected
        if os.geteuid() != 0 or not legacy_update_needs_recovery():
            raise SystemExit('Нет подтверждённого legacy-отката миграции')
        rollback(json.loads(protected(ROOT_STATE / 'migration.json').read_text()), restore_state=True)
    elif args.rollback:
        rollback(json.loads((ROOT_STATE / "migration.json").read_text()))
    elif args.refresh_helper:
        refresh_helper()
    else:
        migrate(start=not args.no_start, automatic=args.automatic)
