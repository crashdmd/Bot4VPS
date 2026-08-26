from __future__ import annotations

import fnmatch
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator

from core.install_paths import get_install_path

from .errors import BackupError, ErrorCode


DEFAULT_SYSTEMD_UNIT = Path("/etc/systemd/system/bot4vps.service")

# These are relative POSIX globs recorded in the manifest for the installation
# source. External Backup Manager storage is not below install_path by contract
# and therefore is never traversed in the first place.
BOT4VPS_INSTALL_EXCLUSIONS = (
    "venv/**",
    ".venv/**",
    "__pycache__",
    "__pycache__/**",
    "**/__pycache__",
    "**/__pycache__/**",
    "*.pyc",
    "**/*.pyc",
    "*.pyo",
    "**/*.pyo",
    "*.tmp",
    "**/*.tmp",
    ".lock",
    "**/.lock",
    "*.lock",
    "**/*.lock",
    # Mutable Backup Manager service state. Active Operation records, disk
    # admission state and scheduler occurrence state are atomically replaced
    # while this self-backup may be built, so they cannot be part of its
    # immutable source snapshot. Durable catalog/history/retention records
    # remain included.
    "data/backup/operations/running",
    "data/backup/operations/running/**",
    "data/backup/disk_state.json",
    "data/backup/automatic_state.json",
    "logs/**/*.corrupt-*.json",
    "logs/**/*.log",
)


@dataclass(frozen=True)
class Bot4VPSSourcePolicy:
    install_path: Path
    systemd_unit: Path
    sources: tuple[dict, ...]


def get_systemd_unit_path() -> Path:
    """Return the live unit used by the installed application."""
    return DEFAULT_SYSTEMD_UNIT


def resolve_bot4vps_sources(
    *,
    install_path: str | Path | None = None,
    systemd_unit: str | Path | None = None,
) -> Bot4VPSSourcePolicy:
    install = Path(install_path or get_install_path()).resolve()
    unit = Path(systemd_unit or get_systemd_unit_path()).resolve()
    if not install.is_dir():
        raise BackupError(ErrorCode.SOURCE_NOT_FOUND, "Каталог установки Bot4VPS не найден")
    if not unit.is_file():
        raise BackupError(ErrorCode.SOURCE_NOT_FOUND, "Активный systemd unit Bot4VPS не найден")
    return Bot4VPSSourcePolicy(
        install_path=install,
        systemd_unit=unit,
        sources=(
            {"path": install.as_posix(), "exclusions": list(BOT4VPS_INSTALL_EXCLUSIONS)},
            {"path": unit.as_posix(), "exclusions": []},
        ),
    )


def _matches_exclusion(relative_path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(relative_path, pattern) for pattern in patterns)


def _persistent_log_path(relative_path: str) -> bool:
    """Allow only the documented durable JSON records below install/logs."""
    path = PurePosixPath(relative_path)
    parts = path.parts
    if relative_path == "logs/notification_queue.json":
        return True
    if len(parts) != 3 or parts[0] != "logs" or parts[1] not in {"events", "tasks"}:
        return False
    name = parts[2]
    stem = name[:-5] if name.endswith(".json") else ""
    return bool(stem) and all(char in "0123456789abcdef" for char in stem.lower())


def include_install_relative(relative_path: str, *, is_directory: bool = False) -> bool:
    """Apply the fixed runtime/cache and logs persistence policy."""
    relative = PurePosixPath(relative_path).as_posix()
    if relative.startswith("./"):
        relative = relative[2:]
    if not relative:
        return True
    if relative == "logs" or (is_directory and relative in {"logs/events", "logs/tasks"}):
        return True
    if relative.startswith("logs/"):
        return _persistent_log_path(relative)
    return not _matches_exclusion(relative, BOT4VPS_INSTALL_EXCLUSIONS)


def iter_source_entries(source: Path, *, install_source: bool) -> Iterator[tuple[Path, str, os.stat_result]]:
    """Yield a deterministic, non-following source walk for local archiving."""
    source = source.resolve()
    root_parent = source.parent

    def walk(path: Path) -> Iterator[tuple[Path, str, os.stat_result]]:
        try:
            metadata = path.lstat()
        except (FileNotFoundError, PermissionError, OSError) as exc:
            raise BackupError(ErrorCode.SOURCE_PERMISSION_DENIED, "Не удалось прочитать source Bot4VPS") from exc
        relative = path.relative_to(root_parent).as_posix()
        policy_relative = path.relative_to(source).as_posix() if path != source else ""
        is_directory = stat.S_ISDIR(metadata.st_mode)
        if install_source and not include_install_relative(policy_relative, is_directory=is_directory):
            return
        yield path, relative, metadata
        if is_directory:
            try:
                children = sorted(path.iterdir(), key=lambda item: item.name)
            except (PermissionError, OSError) as exc:
                raise BackupError(ErrorCode.SOURCE_PERMISSION_DENIED, "Не удалось прочитать source Bot4VPS") from exc
            for child in children:
                yield from walk(child)

    yield from walk(source)
