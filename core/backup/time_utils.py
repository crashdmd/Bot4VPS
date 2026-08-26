from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo


_UTC_OFFSET_RE = re.compile(r"^([+-])(\d{2}):?(\d{2})$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_timestamp(value: datetime | None = None) -> str:
    current = value or utc_now()
    if current.tzinfo is None:
        raise ValueError("Timestamp должен содержать timezone")
    return current.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_utc_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Ожидается UTC timestamp в формате RFC 3339 с Z")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    return parsed.astimezone(timezone.utc)


def normalize_utc_offset(value: object) -> str:
    """Return a canonical ``+HH:MM`` offset safe for historical projection."""
    if not isinstance(value, str):
        raise ValueError("UTC offset должен быть строкой")
    match = _UTC_OFFSET_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError("UTC offset должен иметь формат +HH:MM")
    sign, hours_raw, minutes_raw = match.groups()
    hours = int(hours_raw)
    minutes = int(minutes_raw)
    if hours > 23 or minutes > 59:
        raise ValueError("UTC offset выходит за допустимый диапазон")
    return f"{sign}{hours:02d}:{minutes:02d}"


def timezone_from_utc_offset(value: object) -> timezone:
    normalized = normalize_utc_offset(value)
    sign = -1 if normalized[0] == "-" else 1
    hours = int(normalized[1:3])
    minutes = int(normalized[4:6])
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def local_timezone() -> tzinfo:
    """Return the canonical IANA timezone of the local Bot4VPS host."""
    try:
        from core.timezone import HostTimezoneError, current_timezone_name

        return ZoneInfo(current_timezone_name())
    except HostTimezoneError:
        try:
            from tzlocal import get_localzone
        except ImportError:
            detected = datetime.now().astimezone().tzinfo
            return detected or timezone.utc
        return get_localzone()


def _utc_offset_for_tzinfo(value: str, timezone_value: tzinfo) -> str:
    localized = parse_utc_timestamp(value).astimezone(timezone_value)
    offset = localized.utcoffset()
    if offset is None:
        raise ValueError("Timezone не содержит UTC offset")
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    hours, minutes = divmod(total_minutes, 60)
    return normalize_utc_offset(f"{sign}{hours:02d}:{minutes:02d}")


def utc_offset_for_timezone(value: str, timezone_name: str) -> str:
    """Capture the historical offset of an explicit IANA timezone."""
    return _utc_offset_for_tzinfo(value, ZoneInfo(timezone_name))


def local_utc_offset(value: str) -> str:
    """Capture the Bot4VPS host offset at ``value`` from the operating system."""
    return _utc_offset_for_tzinfo(value, local_timezone())
