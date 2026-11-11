"""Protected code trust anchors used by self-restore, never application backups."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import uuid
from pathlib import Path

if __package__:
    from .protocol import APP, ROOT_STATE, fields
else:
    from protocol import APP, ROOT_STATE, fields

# Retain the old root name for already-created protected restore snapshots.
CODE_PATHS = ("bot.py", "state.py", "core", "ui", "services", "privileged", "deploy",
              "requirements.txt", "requirements.in", "requirements-certbot.txt", "requirements-certbot.in", "install.sh",
              "README.md", "AGENTS.md", "CLAUDE.md", "NAMING.md", "LICENSE", "docs", "plans", "tools", "screenshots", ".gitignore", "pull_from_forgejo.sh", "config.example.json")
IGNORED = {"__pycache__", ".git", ".gradle", ".kotlin", ".build-env", ".signing", ".singning", "build"}


def code_path(relative):
    parts = Path(relative).parts
    return bool(parts) and not Path(relative).is_absolute() and ".." not in parts and parts[0] in CODE_PATHS and not any(p in IGNORED for p in parts)


def files(root):
    for name in CODE_PATHS:
        source = root / name
        if not source.exists():
            continue
        if source.is_file():
            yield source
        else:
            for directory, names, entries in os.walk(source, followlinks=False):
                names[:] = [name for name in names if name not in IGNORED]
                for name in entries:
                    item = Path(directory) / name
                    if code_path(item.relative_to(root).as_posix()):
                        yield item


def create():
    if __package__:
        from .daemon import atomic, protected
    else:
        from daemon import atomic, protected
    manifest = {}
    sources = list(files(APP))
    for source in sources:
        protected(source)
        manifest[source.relative_to(APP).as_posix()] = hashlib.sha256(source.read_bytes()).hexdigest()
    identity = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    destination = ROOT_STATE / "snapshots" / identity
    if not destination.exists():
        destination.mkdir(parents=True, mode=0o700)
        for source in sources:
            target = destination / source.relative_to(APP)
            target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            shutil.copy2(source, target)
        atomic(destination / "manifest.json", json.dumps(manifest, sort_keys=True).encode())
    return identity


def select(params):
    if __package__:
        from .daemon import protected
    else:
        from daemon import protected
    fields(params, ("files",))
    wanted = params["files"]
    if not isinstance(wanted, dict) or len(wanted) > 2000:
        raise ValueError("Некорректный список кода")
    import re
    for name, digest in wanted.items():
        if not code_path(name) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Недопустимый файл кода")
    if not wanted:
        return None
    for path in sorted((ROOT_STATE / "snapshots").glob("*/manifest.json")):
        manifest = json.loads(protected(path).read_text())
        if all(manifest.get(name) == digest for name, digest in wanted.items()):
            return path.parent
    raise ValueError("Код архива не совпадает с защищённой копией. Выберите восстановление данных; код устанавливается подписанным обновлением")


def validate(params):
    snapshot = select(params)
    return snapshot.name if snapshot else None


def restore(params):
    if __package__:
        from .daemon import atomic, protected, track
    else:
        from daemon import atomic, protected, track
    snapshot = select(params)
    if snapshot is None:
        return True
    intent = ROOT_STATE / "code-restore-recovery.json"
    if intent.exists():
        raise ValueError("Предыдущее восстановление кода ещё не завершено")
    # Validate every source and target before the first write.
    for relative in params["files"]:
        protected(snapshot / relative)
        if hashlib.sha256((snapshot / relative).read_bytes()).hexdigest() != params["files"][relative]:
            raise ValueError("Повреждён защищённый снимок кода")
        target = APP / relative
        parent = target.parent
        while not parent.exists():
            parent = parent.parent
        protected(parent, directory=True)
        if target.exists() or target.is_symlink():
            protected(target)
    changed = [relative for relative in params["files"] if not (APP / relative).exists()
               or hashlib.sha256((APP / relative).read_bytes()).hexdigest() != params["files"][relative]]
    if not changed:
        return True
    backup = ROOT_STATE / "restore-code" / uuid.uuid4().hex
    backup.mkdir(parents=True, mode=0o700)
    previous = {}
    for relative in changed:
        target = APP / relative
        previous[relative] = target.exists()
        if target.exists():
            saved = backup / relative
            saved.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            shutil.copy2(target, saved)
    track(intent, backup=str(backup), files=previous, requirements="requirements.txt" in changed)
    try:
        for relative in changed:
            source = snapshot / relative
            target = APP / relative
            target.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
            atomic(target, source.read_bytes(), stat.S_IMODE(source.stat().st_mode) & ~0o022)
        if "requirements.txt" in changed:
            install_dependencies()
        refresh()
    except Exception:
        rollback()
        raise
    return True


def install_dependencies():
    if __package__:
        from .daemon import protected, ENV
    else:
        from daemon import protected, ENV
    lock = protected(APP / "requirements.txt")
    # Lock and executable are root-owned. No options, scripts or requirement
    # paths are obtained from the request or the application archive.
    result = subprocess.run([str(APP / "venv/bin/python"), "-I", "-m", "pip", "--isolated", "install",
                             "--require-hashes", "--no-input", "-r", str(lock)],
                            cwd="/", env=ENV, capture_output=True, text=True, timeout=900)
    if result.returncode:
        raise RuntimeError("Не удалось восстановить зависимости защищённого снимка")


def refresh():
    if __package__:
        from . import install
    else:
        import install
    install.SOURCE = APP
    install.refresh_helper()


def rollback():
    if __package__:
        from .daemon import atomic, protected, run
    else:
        from daemon import atomic, protected, run
    intent = ROOT_STATE / "code-restore-recovery.json"
    data = json.loads(protected(intent).read_text())
    backup = Path(data["backup"])
    backup.relative_to(ROOT_STATE / "restore-code")
    protected(backup, directory=True)
    for relative, existed in data["files"].items():
        if not code_path(relative):
            raise ValueError("Некорректный журнал восстановления кода")
        target = APP / relative
        if existed:
            saved = protected(backup / relative)
            atomic(target, saved.read_bytes(), stat.S_IMODE(saved.stat().st_mode) & ~0o022)
        elif target.exists():
            protected(target).unlink()
    if data["requirements"]:
        install_dependencies()
    refresh()
    if run(["/usr/bin/systemctl", "daemon-reload"])["returncode"]:
        raise RuntimeError("Не удалось перечитать восстановленный unit")
    if run(["/usr/bin/systemctl", "restart", "bot4vps"])["returncode"]:
        raise RuntimeError("Не удалось запустить прежний код")
    intent.unlink()
    shutil.rmtree(backup)


def finish(success):
    if __package__:
        from .daemon import CLIENT_PID, process_stamp, protected, run, reload_helper
    else:
        from daemon import CLIENT_PID, process_stamp, protected, run, reload_helper
    intent = ROOT_STATE / "code-restore-recovery.json"
    if not intent.exists():
        return
    data = json.loads(protected(intent).read_text())
    if data["pid"] != CLIENT_PID or data.get("stamp") != process_stamp(CLIENT_PID):
        raise ValueError("Восстановление кода принадлежит другой операции")
    if not success:
        rollback()
        return
    create()
    backup = Path(data["backup"])
    backup.relative_to(ROOT_STATE / "restore-code")
    protected(backup, directory=True)
    if run(["/usr/bin/systemctl", "daemon-reload"])["returncode"]:
        raise RuntimeError("Не удалось перечитать systemd после восстановления")
    # Refresh was done from trusted source; activate it only after health.
    intent.unlink()
    shutil.rmtree(backup)
    reload_helper()
