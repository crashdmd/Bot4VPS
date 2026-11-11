"""Проверка архитектурной совместимости по фактическому core/version.py."""
from __future__ import annotations

import ast
import posixpath
import re
import tarfile

from core.install_paths import get_install_path
from core.version import APP_VERSION

from .archive_format import open_backup_tar
from .errors import BackupError, ErrorCode

MAX_VERSION_BYTES = 64 * 1024


def numeric_version(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", value) or len(value) > 128:
        return None
    parts = tuple(int(part) for part in value.split("."))
    return parts + (0,) * (4 - len(parts))


def _constant_version(data):
    try:
        tree = ast.parse(data)
    except (SyntaxError, ValueError, UnicodeError, RecursionError):
        return None
    writes = [node for node in ast.walk(tree) if isinstance(node, ast.Name)
              and node.id == "APP_VERSION" and isinstance(node.ctx, (ast.Store, ast.Del))]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name == "APP_VERSION":
            return None
        if isinstance(node, ast.alias) and (node.asname == "APP_VERSION" or node.name in {"APP_VERSION", "*"}):
            return None
    assignments = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        else:
            continue
        if isinstance(target, ast.Name) and target.id == "APP_VERSION":
            assignments.append(node.value)
    if len(writes) != 1 or len(assignments) != 1:
        return None
    value = assignments[0]
    return value.value if isinstance(value, ast.Constant) and numeric_version(value.value) else None


def _compatibility_error(version, current):
    if version is None:
        reason = (
            f"Текущая версия Bot4VPS — {current}. "
            "Версию Bot4VPS в архиве определить не удалось.\n\n"
            "Подтвердить совместимость архива с текущей установкой невозможно. "
        )
    else:
        reason = f"Текущая версия Bot4VPS — {current}. Архив содержит Bot4VPS {version}.\n\n"
    return BackupError(
        ErrorCode.RESTORE_PRECHECK_FAILED,
        "Восстановление невозможно\n\n" + reason +
        "Начиная с версии 7.0 изменена архитектура приложения и модель разделения "
        "привилегий. Восстановление такого архива может нарушить работоспособность "
        "текущей установки.\n\n"
        "Для восстановления сначала выполните штатный откат Bot4VPS до совместимой "
        "версии, затем восстановите архив.",
    )


def require_self_restore_compatible(archive_path, full_plan, *, current_version=None):
    """Inspect the full physical archive, independent of the effective selection.

    Mapping comes from the full restore layout, never producer/catalog metadata.
    Python in the archive is parsed only; it is never imported or executed.
    """
    current = APP_VERSION if current_version is None else current_version
    if numeric_version(current) is not None and numeric_version(current) < (7, 0, 0, 0):
        return None
    version_path = (get_install_path() / "core/version.py").as_posix()
    entries = [entry for entry in full_plan.get("entries", ()) if entry.get("path") == version_path]
    version = None
    if len(entries) == 1 and entries[0].get("type") == "file":
        expected = posixpath.normpath(entries[0]["name"])
        try:
            with open_backup_tar(archive_path) as archive:
                members = archive.getmembers()
                matches = [member for member in members if posixpath.normpath(member.name) == expected]
                parents = set()
                parent = posixpath.dirname(expected)
                while parent and parent != ".":
                    parents.add(parent)
                    parent = posixpath.dirname(parent)
                substituted = any(posixpath.normpath(member.name) in parents and not member.isdir()
                                  for member in members)
                if len(matches) == 1 and not substituted:
                    member = matches[0]
                    if member.isfile() and 0 < member.size <= MAX_VERSION_BYTES:
                        with archive.extractfile(member) as stream:
                            data = stream.read(MAX_VERSION_BYTES + 1)
                        if len(data) == member.size:
                            version = _constant_version(data)
        except BackupError:
            raise
        except (OSError, ValueError, tarfile.TarError, EOFError):
            version = None
    if version is None or numeric_version(version) < (7, 0, 0, 0):
        raise _compatibility_error(version, current)
    return version
