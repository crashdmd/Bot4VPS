"""Self-restore adaptation for the privilege-separated local installation."""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from core.install_paths import get_install_path
from core.local_privileges import request
from .archive_format import open_backup_tar

# The legacy root name identifies code in archives made before its removal.
CODE_ROOTS = {"bot.py", "state.py", "core", "ui", "services", "privileged", "deploy", "install.sh",
              "requirements.txt", "requirements.in", "requirements-certbot.txt", "requirements-certbot.in",
              "README.md", "AGENTS.md", "CLAUDE.md", "NAMING.md", "LICENSE", "docs", "plans", "tools", "screenshots", ".gitignore", "pull_from_forgejo.sh", "config.example.json"}
DATA_ROOTS = {"data", "keys", "logs", "scripts"}
LEGACY_JSON = {"config.json", "servers.json", "monitor.json"}
UNIT = "/etc/systemd/system/bot4vps.service"
EMPTY_ENV_DIRS = {Path('venv'), Path('.venv')}


def relative_data(path):
    install = get_install_path()
    relative = Path(path).relative_to(install)
    if relative.as_posix() in LEGACY_JSON:
        relative = Path("data/runtime") / relative
    elif relative.parts and relative.parts[0] == 'backup':
        relative = Path('data/config-backup', *relative.parts[1:])
    return relative


def prepare(archive, plan):
    """Hash selected code and validate the full local scope before mutation."""
    code, unit = {}, None
    install = get_install_path()
    with open_backup_tar(archive) as tar:
        for entry in plan.get("entries") or ():
            path = str(entry["path"])
            if path == UNIT:
                member = tar.getmember(entry["name"])
                if not member.isfile() or member.size > 32768:
                    raise ValueError("Некорректный unit в архиве")
                unit = tar.extractfile(member).read().decode("utf-8")
                # Validation only: the helper reconstructs its own non-root unit.
                request("unit.validate", text=unit)
                continue
            relative = relative_data(path)
            if relative in EMPTY_ENV_DIRS and tar.getmember(entry['name']).isdir():
                continue  # Old self-backups included the excluded venv container.
            if not relative.parts or relative == Path("."):
                continue
            if relative.parts[0] in CODE_ROOTS:
                member = tar.getmember(entry["name"])
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ValueError("Код архива содержит ссылку или специальный файл")
                digest = hashlib.sha256()
                with tar.extractfile(member) as stream:
                    while chunk := stream.read(256 * 1024):
                        digest.update(chunk)
                code[relative.as_posix()] = digest.hexdigest()
            elif relative.parts[0] not in DATA_ROOTS:
                raise ValueError("Архив содержит файл вне разрешённых рабочих каталогов: " + str(relative))
    request("code.validate", files=code)
    return {"code": code, "unit": unit, "entries": plan.get("entries") or ()}


def extract(job):
    """Application UID writes runtime data only; numeric archive owners aren't applied."""
    install = get_install_path()
    policy = job["separated_restore"]
    directories = []
    with open_backup_tar(job["archive"]) as tar:
        for entry in policy["entries"]:
            if str(entry["path"]) == UNIT:
                continue
            member = tar.getmember(entry['name'])
            original = Path(entry['path']).relative_to(install).as_posix()
            if original in LEGACY_JSON and member.issym():
                # Managed root aliases already exist. The same archive holds
                # the real data/runtime file; remapping the alias would link
                # that file to a second nested data/runtime path.
                continue
            relative = relative_data(entry["path"])
            if relative in EMPTY_ENV_DIRS and member.isdir():
                continue
            if not relative.parts or relative == Path(".") or relative.parts[0] in CODE_ROOTS:
                continue
            if relative.parts[0] not in DATA_ROOTS or ".." in relative.parts:
                raise ValueError("Недопустимый путь рабочих данных")
            target = install / relative
            for parent in (target.parent, *target.parent.parents):
                if parent == install:
                    break
                if parent.is_symlink():
                    raise ValueError("Ссылка в пути восстановления")
            if member.isdir():
                if target.is_symlink():
                    raise ValueError("Ссылка вместо каталога восстановления")
                target.mkdir(parents=True, exist_ok=True)
                directories.append((target, member.mode & 0o700))
            elif member.isfile():
                if target.is_symlink():
                    raise ValueError("Ссылка вместо файла восстановления")
                target.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".restore-")
                try:
                    with os.fdopen(fd, "wb") as stream, tar.extractfile(member) as source:
                        shutil.copyfileobj(source, stream)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.chmod(temporary, member.mode & 0o700 or 0o600)
                    os.replace(temporary, target)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            elif member.issym():
                # Existing archive validation ensures the link target stays in scope;
                # recheck after remapping legacy JSON destinations.
                link = Path(member.linkname)
                resolved = (target.parent / link).resolve() if not link.is_absolute() else link.resolve()
                resolved.relative_to(install / relative.parts[0])
                if target.exists() or target.is_symlink():
                    target.unlink()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(member.linkname)
            else:
                raise ValueError("Неподдерживаемый член архива")
    request("code.restore", files=policy["code"])
    if policy.get("unit") is not None:
        request("unit.configure", text=policy["unit"])
