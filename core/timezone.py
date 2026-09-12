from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_TIMEDATECTL_TIMEOUT = 10
_CHANGE_LOCK = threading.Lock()


class HostTimezoneError(RuntimeError):
    """The local operating-system timezone could not be read or changed."""

    def __init__(self, message: str, *, actual_timezone: str | None = None):
        super().__init__(message)
        self.actual_timezone = actual_timezone


class InvalidTimezoneError(HostTimezoneError):
    """The requested timezone is not in the host's IANA timezone list."""


def _run_timedatectl(*args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["timedatectl", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=_TIMEDATECTL_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise HostTimezoneError("timedatectl не ответил вовремя") from exc
    except (FileNotFoundError, OSError) as exc:
        raise HostTimezoneError("timedatectl недоступен на этом хосте") from exc


def _successful_output(*args: str) -> str:
    result = _run_timedatectl(*args)
    if result.returncode != 0:
        raise HostTimezoneError("Не удалось прочитать часовой пояс локального хоста")
    return result.stdout.strip()


def current_timezone_name() -> str:
    name = _successful_output("show", "--property=Timezone", "--value")
    if not name:
        raise HostTimezoneError("Локальный хост вернул пустой часовой пояс")
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HostTimezoneError("Локальный хост вернул неизвестный часовой пояс") from exc
    return name


def available_timezone_names() -> tuple[str, ...]:
    output = _successful_output("list-timezones", "--no-pager")
    names: list[str] = []
    for raw_name in output.splitlines():
        name = raw_name.strip()
        if not name:
            continue
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            continue
        names.append(name)
    if not names:
        raise HostTimezoneError("Системный список часовых поясов пуст")
    return tuple(sorted(set(names)))


def validate_timezone_name(name: object) -> str:
    if not isinstance(name, str) or not name.strip() or name != name.strip():
        raise InvalidTimezoneError("Укажите часовой пояс IANA из системного списка")
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidTimezoneError("Неизвестный часовой пояс IANA") from exc
    if name not in available_timezone_names():
        raise InvalidTimezoneError("Часовой пояс отсутствует в системном списке")
    return name


def format_utc_offset(name: str, *, at: datetime | None = None) -> str:
    instant = at or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("Момент для UTC offset должен содержать timezone")
    offset = instant.astimezone(ZoneInfo(name)).utcoffset()
    if offset is None:
        raise HostTimezoneError("Не удалось вычислить UTC offset часового пояса")
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def timezone_label(name: str, *, at: datetime | None = None) -> str:
    return f"{name} ({format_utc_offset(name, at=at)})"


def _offset_minutes(name: str, *, at: datetime) -> int:
    offset = at.astimezone(ZoneInfo(name)).utcoffset()
    if offset is None:
        raise HostTimezoneError("Не удалось вычислить UTC offset часового пояса")
    return int(offset.total_seconds() // 60)


def _format_offset_short(minutes: int) -> str:
    """Компактное смещение для заголовка группы: UTC-3, UTC+5:30, UTC."""
    if minutes == 0:
        return "UTC"
    sign = "+" if minutes >= 0 else "-"
    hours, rem = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours}" if rem == 0 else f"UTC{sign}{hours}:{rem:02d}"


def timezone_option_groups(names: tuple[str, ...], *, at: datetime | None = None) -> list[dict]:
    """Зоны, сгруппированные по UTC offset: «UTC-3» → все города этого пояса.

    Группы отсортированы по смещению (от западных к восточным), зоны внутри
    группы — алфавитно. Иначе в списке на ~350 зон творится солянка:
    +12, 0, +8 вперемежку.
    """
    now = at or datetime.now(timezone.utc)
    groups: dict[int, list[dict]] = {}
    for name in names:
        try:
            minutes = _offset_minutes(name, at=now)
        except (HostTimezoneError, ZoneInfoNotFoundError, ValueError):
            continue
        groups.setdefault(minutes, []).append({"value": name, "label": name})
    return [
        {
            "offset": _format_offset_short(minutes),
            "zones": sorted(zones, key=lambda zone: zone["value"]),
        }
        for minutes, zones in sorted(groups.items())
    ]


def timezone_details(name: str, *, at: datetime | None = None) -> dict:
    now = at or datetime.now(timezone.utc)
    return {
        "timezone": name,
        "utc_offset": format_utc_offset(name, at=now),
        "label": timezone_label(name, at=now),
        "server_ts": now.timestamp(),
    }


def timezone_payload(*, include_options: bool) -> dict:
    now = datetime.now(timezone.utc)
    name = current_timezone_name()
    payload = timezone_details(name, at=now)
    if include_options:
        payload["options"] = timezone_option_groups(
            available_timezone_names(), at=now
        )
    return payload


def fallback_local_timezone_name() -> str:
    """Best-effort canonical local zone for informational endpoints only."""
    try:
        from tzlocal import get_localzone_name

        name = get_localzone_name()
        ZoneInfo(name)
        return name
    except (ImportError, OSError, ZoneInfoNotFoundError, ValueError):
        return "UTC"


def _refresh_process_timezone() -> None:
    if hasattr(time, "tzset"):
        try:
            time.tzset()
        except OSError as exc:
            print(
                f"[TIMEZONE] не удалось применить timezone в процессе: {type(exc).__name__}",
                flush=True,
            )
    try:
        from tzlocal import reload_localzone

        reload_localzone()
    except (ImportError, OSError, ValueError, ZoneInfoNotFoundError) as exc:
        print(
            f"[TIMEZONE] не удалось обновить cache tzlocal: {type(exc).__name__}",
            flush=True,
        )


def _set_timezone(name: str) -> None:
    result = _run_timedatectl("set-timezone", name)
    if result.returncode != 0:
        raise HostTimezoneError("Не удалось изменить часовой пояс локального хоста")


def _read_timezone_after_change() -> str | None:
    try:
        return current_timezone_name()
    except HostTimezoneError:
        return None


def _rollback_timezone(previous: str) -> tuple[bool, str | None]:
    try:
        _set_timezone(previous)
        actual = current_timezone_name()
    except HostTimezoneError:
        return False, _read_timezone_after_change()
    if actual != previous:
        return False, actual
    _refresh_process_timezone()
    return True, actual


def set_timezone_verified(
    requested: object,
    persist: Callable[[str], object],
) -> str:
    """Set, verify and persist the host timezone as one serialized operation."""
    with _CHANGE_LOCK:
        previous = current_timezone_name()
        target = validate_timezone_name(requested)

        try:
            _set_timezone(target)
            actual = current_timezone_name()
            if actual != target:
                raise HostTimezoneError(
                    "Проверка часового пояса после изменения не пройдена",
                    actual_timezone=actual,
                )
            persist(actual)
        except Exception as exc:
            actual = _read_timezone_after_change()
            rollback_ok = actual == previous
            if not rollback_ok:
                rollback_ok, actual = _rollback_timezone(previous)
            if isinstance(exc, InvalidTimezoneError):
                raise
            message = "Не удалось изменить часовой пояс сервера. Настройка не сохранена."
            if rollback_ok:
                actual = previous
            elif actual:
                message += f" Фактический часовой пояс хоста: {actual}."
            else:
                message += " Фактический часовой пояс хоста определить не удалось."
            raise HostTimezoneError(
                message,
                actual_timezone=actual,
            ) from exc

        _refresh_process_timezone()
        return actual
