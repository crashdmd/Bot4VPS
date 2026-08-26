from __future__ import annotations

import json
import shutil
from pathlib import Path

from core.install_paths import get_backup_data_path
from core.json_store import atomic_write_json

from .errors import BackupError, ErrorCode
from .models import SCHEMA_VERSION, DiskState
from .time_utils import parse_utc_timestamp, utc_timestamp


_DISK_STATE_KEYS = {
    "schema_version",
    "state",
    "creation_disabled",
    "free_bytes",
    "filesystem",
    "checked_at",
    "emergency_entered_at",
    "last_transition_at",
    "reason",
}
_DISK_STATE_SEMANTIC_KEYS = (
    "schema_version",
    "filesystem",
    "state",
    "creation_disabled",
    "reason",
    "emergency_entered_at",
    "last_transition_at",
)


class DiskMonitor:
    def __init__(self, storage_root: str | Path, safety: dict, data_root: str | Path | None = None):
        self.storage_root = Path(storage_root)
        self.safety = dict(safety)
        self.path = Path(data_root or get_backup_data_path()) / "disk_state.json"

    def _previous(self) -> dict | None:
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                raw = json.load(stream)
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict) or set(raw) != _DISK_STATE_KEYS:
            return None
        if raw.get("schema_version") != SCHEMA_VERSION:
            return None
        if raw.get("filesystem") != str(self.storage_root):
            return None
        state = raw.get("state")
        if state not in {"normal", "warning", "critical", "emergency", "recovering"}:
            return None
        if (
            not isinstance(raw.get("creation_disabled"), bool)
            or raw["creation_disabled"] != (state in {"emergency", "recovering"})
            or not isinstance(raw.get("free_bytes"), int)
            or isinstance(raw.get("free_bytes"), bool)
            or raw["free_bytes"] < 0
            or raw.get("reason") != ("free_space" if state != "normal" else None)
        ):
            return None
        emergency_entered = raw.get("emergency_entered_at")
        if (state in {"emergency", "recovering"}) != isinstance(emergency_entered, str):
            return None
        try:
            parse_utc_timestamp(raw.get("checked_at"))
            parse_utc_timestamp(raw.get("last_transition_at"))
            if emergency_entered is not None:
                parse_utc_timestamp(emergency_entered)
        except (TypeError, ValueError):
            return None
        return raw

    @staticmethod
    def _semantic_state(value: dict) -> tuple:
        return tuple(value[key] for key in _DISK_STATE_SEMANTIC_KEYS)

    def check(self) -> DiskState:
        self.storage_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        free = shutil.disk_usage(self.storage_root).free
        previous = self._previous()
        previous_state = (previous or {}).get("state")
        emergency = int(self.safety["emergency_free_bytes"])
        recovery = int(self.safety["recovery_free_bytes"])
        critical = int(self.safety["critical_free_bytes"])
        warning = int(self.safety["warning_free_bytes"])

        if previous_state in {"emergency", "recovering"} and free < recovery:
            state = "emergency" if free < emergency else "recovering"
            disabled = True
        elif free < emergency:
            state, disabled = "emergency", True
        elif free < critical:
            state, disabled = "critical", False
        elif free < warning:
            state, disabled = "warning", False
        else:
            state, disabled = "normal", False

        now = utc_timestamp()
        transitioned = previous_state != state
        emergency_entered = (previous or {}).get("emergency_entered_at")
        if state == "emergency" and previous_state != "emergency":
            emergency_entered = now
        if state not in {"emergency", "recovering"}:
            emergency_entered = None
        result = DiskState(
            state=state,
            creation_disabled=disabled,
            free_bytes=free,
            filesystem=str(self.storage_root),
            checked_at=now,
            emergency_entered_at=emergency_entered,
            last_transition_at=now if transitioned else (previous or {}).get("last_transition_at", now),
            reason="free_space" if state != "normal" else None,
        )
        persisted = result.to_dict()
        if previous is None or self._semantic_state(previous) != self._semantic_state(persisted):
            atomic_write_json(self.path, persisted)
        return result

    def require_creation_allowed(self) -> DiskState:
        state = self.check()
        if state.creation_disabled:
            raise BackupError(ErrorCode.DISK_SPACE_EMERGENCY, "Создание backup отключено до восстановления свободного места", retryable=True)
        return state
