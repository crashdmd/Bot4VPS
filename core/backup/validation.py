from __future__ import annotations

import posixpath
import re
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.install_paths import assert_storage_root_is_external

from .errors import BackupError, ErrorCode
from .ids import validate_id
from .source_selection import (
    SourceSelectionError,
    canonicalize_source_records,
    normalize_source_path,
)


_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
MAX_ARCHIVE_FILENAME_LENGTH = 255


def _fail(message: str, code: ErrorCode = ErrorCode.PROFILE_INVALID) -> None:
    raise BackupError(code, message)


def _positive_or_none(value, field: str) -> None:
    if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value <= 0):
        _fail(f"{field} должен быть положительным целым числом или null")


def _validate_schedule(automatic: dict, *, sources_present: bool = True) -> None:
    if not isinstance(automatic, dict):
        _fail("automatic должен быть объектом")
    if not isinstance(automatic.get("enabled"), bool):
        _fail("automatic.enabled должен быть boolean")
    if automatic["enabled"] and not sources_present:
        _fail("Нельзя включить automatic backup без sources", ErrorCode.PROFILE_NO_SOURCES)
    if not _TIME_RE.fullmatch(str(automatic.get("daily_time", ""))):
        _fail("automatic.daily_time должен иметь формат HH:MM")
    try:
        ZoneInfo(str(automatic.get("timezone", "")))
    except (ZoneInfoNotFoundError, ValueError):
        _fail("automatic.timezone должна быть валидной IANA timezone")
    keep_last = automatic.get("keep_last")
    if not isinstance(keep_last, int) or isinstance(keep_last, bool) or keep_last < 1:
        _fail("automatic.keep_last должен быть >= 1")


_NOTIFICATION_DEFAULTS = {
    "backup": {"enabled": False, "success": False, "error": True},
    "restore": {"enabled": True, "success": False, "error": True},
}


def _normalize_notification_category(value, defaults: dict, *, field: str) -> dict:
    if value is None:
        return dict(defaults)
    if not isinstance(value, dict):
        _fail(f"{field} должен быть объектом")
    result = {}
    for key in ("enabled", "success", "error"):
        raw = value.get(key, defaults[key])
        if not isinstance(raw, bool):
            _fail(f"{field}.{key} должен быть boolean")
        result[key] = raw
    return result


def normalize_notifications(value) -> dict:
    """Нормализовать настройки уведомлений во вложенную форму.

    Историческая плоская форма ``{success, error}`` относилась к бэкапу (restore
    тогда событий не эмитил) и мигрируется во вложенную
    ``{backup:{enabled,success,error}, restore:{enabled,success,error}}``.
    Отсутствующие ключи добиваются дефолтами. Идемпотентна.
    """
    if value is None:
        value = {}
    if not isinstance(value, dict):
        _fail("notifications должен быть объектом")
    is_flat = (
        "backup" not in value
        and "restore" not in value
        and ("success" in value or "error" in value)
    )
    if is_flat:
        success = value.get("success", False)
        error = value.get("error", True)
        for name, raw in (("success", success), ("error", error)):
            if not isinstance(raw, bool):
                _fail(f"notifications.{name} должен быть boolean")
        return {
            "backup": {"enabled": bool(success or error), "success": success, "error": error},
            "restore": dict(_NOTIFICATION_DEFAULTS["restore"]),
        }
    return {
        "backup": _normalize_notification_category(
            value.get("backup"), _NOTIFICATION_DEFAULTS["backup"], field="notifications.backup"
        ),
        "restore": _normalize_notification_category(
            value.get("restore"), _NOTIFICATION_DEFAULTS["restore"], field="notifications.restore"
        ),
    }


def _validate_exclusion_pattern(
    value: object,
    field: str,
    *,
    error_code: ErrorCode = ErrorCode.PROFILE_INVALID,
) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        _fail(f"{field} должен быть относительным POSIX glob", error_code)
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        _fail(f"{field} должен оставаться внутри source path", error_code)
    normalized = posixpath.normpath(value)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        _fail(f"{field} должен оставаться внутри source path", error_code)
    return normalized


def _is_secret_shaped_path(value: str) -> bool:
    parts = {part.lower() for part in PurePosixPath(value).parts}
    basename = PurePosixPath(value).name.lower()
    secret_basenames = {
        "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", "authorized_keys",
    }
    return ".ssh" in parts or basename in secret_basenames or basename.endswith((".pem", ".key"))


def normalize_exclusions(
    exclusions: list,
    *,
    field: str = "sources[].exclusions",
    error_code: ErrorCode = ErrorCode.PROFILE_INVALID,
) -> list[str]:
    if not isinstance(exclusions, list):
        _fail(f"{field} должен быть массивом строк", error_code)
    normalized = []
    for index, value in enumerate(exclusions):
        pattern = _validate_exclusion_pattern(
            value,
            f"{field}[{index}]",
            error_code=error_code,
        )
        if _is_secret_shaped_path(pattern):
            _fail(
                f"{field}[{index}] не должен раскрывать secret-shaped path",
                error_code,
            )
        normalized.append(pattern)
    return normalized


def parse_server_profile(profile: dict) -> dict:
    """Validate every submitted source record without collapsing any record."""
    if not isinstance(profile, dict) or profile.get("schema_version") != 1:
        _fail("Поддерживается только schema_version=1")
    sources = profile.get("sources")
    if not isinstance(sources, list):
        _fail("sources должен быть массивом")
    normalized_sources = []
    for source in sources:
        if not isinstance(source, dict):
            _fail("Каждый source должен быть объектом")
        unexpected = set(source) - {"path", "exclusions"}
        if unexpected:
            _fail("Source содержит неподдерживаемые поля")
        try:
            path = normalize_source_path(source.get("path"))
        except SourceSelectionError as exc:
            _fail(str(exc))
        exclusions = source.get("exclusions", [])
        normalized_exclusions = normalize_exclusions(exclusions)
        normalized_sources.append({"path": path, "exclusions": normalized_exclusions})
    _validate_schedule(profile.get("automatic", {}), sources_present=bool(normalized_sources))
    limits = profile.get("limits", {})
    if not isinstance(limits, dict):
        _fail("limits должен быть объектом")
    _positive_or_none(limits.get("max_source_bytes"), "limits.max_source_bytes")
    _positive_or_none(limits.get("max_archive_bytes"), "limits.max_archive_bytes")
    return {
        "schema_version": 1,
        "sources": normalized_sources,
        "automatic": dict(profile["automatic"]),
        "limits": dict(limits),
        "notifications": normalize_notifications(profile.get("notifications")),
    }


def normalize_server_profile(profile: dict) -> dict:
    parsed = parse_server_profile(profile)
    parsed["sources"] = canonicalize_source_records(parsed["sources"])
    return parsed


def normalize_backup_config(config: dict, *, install_path: Path | None = None) -> dict:
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        _fail("Поддерживается только backup.schema_version=1")
    storage = config.get("storage", {})
    if not isinstance(storage, dict) or storage.get("backend") != "local":
        _fail("В v1 поддерживается только storage.backend=local")
    root = storage.get("root")
    if not isinstance(root, str) or not Path(root).expanduser().is_absolute():
        _fail("storage.root должен быть абсолютным path")
    try:
        assert_storage_root_is_external(root, install_path)
    except ValueError as exc:
        _fail(str(exc))
    bot = config.get("bot4vps", {})
    if not isinstance(bot, dict):
        _fail("bot4vps должен быть объектом")
    _validate_schedule(bot.get("automatic", {}))
    limits = bot.get("limits", {})
    if not isinstance(limits, dict):
        _fail("bot4vps.limits должен быть объектом")
    _positive_or_none(limits.get("max_source_bytes"), "bot4vps.limits.max_source_bytes")
    _positive_or_none(limits.get("max_archive_bytes"), "bot4vps.limits.max_archive_bytes")
    safety = config.get("safety", {})
    required = (
        "warning_free_bytes", "critical_free_bytes", "emergency_free_bytes",
        "recovery_free_bytes", "staging_ttl_seconds", "claim_ttl_seconds",
    )
    if not isinstance(safety, dict):
        _fail("safety должен быть объектом")
    for field in required:
        value = safety.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            _fail(f"safety.{field} должен быть положительным целым числом")
    if not (safety["warning_free_bytes"] > safety["critical_free_bytes"] > safety["recovery_free_bytes"] > safety["emergency_free_bytes"]):
        _fail("Пороговые значения disk safety имеют неверный порядок")
    return {
        "schema_version": 1,
        "storage": {"backend": "local", "root": str(Path(root).expanduser())},
        "bot4vps": {
            "automatic": dict(bot["automatic"]),
            "limits": dict(limits),
            "notifications": normalize_notifications(bot.get("notifications")),
        },
        "safety": dict(safety),
    }


def validate_archive_filename(
    value: object,
    *,
    error_code: ErrorCode = ErrorCode.INVALID_REQUEST,
) -> str:
    """Validate a user-facing archive basename without turning it into a path."""
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or len(value) > MAX_ARCHIVE_FILENAME_LENGTH
        or "/" in value
        or "\\" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise BackupError(error_code, "Некорректное имя backup archive")
    return value


def validate_storage_key(
    value: object,
    *,
    error_code: ErrorCode = ErrorCode.INVALID_REQUEST,
) -> str:
    """Validate a relative POSIX storage key."""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise BackupError(error_code, "Некорректный storage key")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts) or "\\" in value:
        raise BackupError(error_code, "Некорректный storage key")
    return value


def validate_entity_id(value: str, field: str) -> str:
    try:
        return validate_id(value, field=field)
    except ValueError as exc:
        raise BackupError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
