from __future__ import annotations

import os
from pathlib import Path


DEFAULT_STORAGE_ROOT = Path("/var/backups/bot4vps")
DEFAULT_LOCK_ROOT = Path("/run/lock/bot4vps")


def get_install_path() -> Path:
    """Return the actual Bot4VPS installation root, independent of cwd."""
    return Path(__file__).resolve().parents[1]


def get_backup_data_path() -> Path:
    return get_install_path() / "data" / "backup"


def get_backup_lock_path() -> Path:
    override = os.environ.get("BOT4VPS_LOCK_ROOT")
    return Path(override).expanduser().resolve() if override else DEFAULT_LOCK_ROOT


def resolve_storage_root(config: dict | None = None) -> Path:
    backup = (config or {}).get("backup", config or {})
    storage = backup.get("storage", {}) if isinstance(backup, dict) else {}
    raw = storage.get("root") or str(DEFAULT_STORAGE_ROOT)
    return Path(raw).expanduser().resolve()


def assert_storage_root_is_external(
    storage_root: str | Path,
    install_path: str | Path | None = None,
) -> None:
    root = Path(storage_root).expanduser().resolve()
    install = Path(install_path or get_install_path()).resolve()
    try:
        root.relative_to(install)
    except ValueError:
        return
    raise ValueError("Каталог backup не может находиться внутри install_path Bot4VPS")
