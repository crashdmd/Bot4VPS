"""Журнал событий: одна запись — один файл ``logs/events/<event_id>.json``.

Все операции проходят через sidecar lock каталога и атомарную запись
(tmp + ``os.replace`` + fsync файла и каталога), поэтому журнал безопасен
при одновременной работе Web, Telegram и фоновых заданий. Повреждённый
файл изолируется в карантин и не влияет на остальные записи.

Журнал хранит состояние события (``read``); доставка уведомлений
выполняется через ``event_service`` и ``notification_queue``.
"""
import time
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, Any, List, Optional

from core.json_store import JsonItemStore
from .event_types import EventType, EventLevel

EVENTS_DIR = Path("logs/events")


def _events_limit_from_config() -> int:
    """Лимит журнала из config.json (секция logs.events)."""
    try:
        from core.config import load_config
        value = (load_config().get("logs") or {}).get("events")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
    except Exception:
        pass
    return 200


# Лимит размера журнала событий (старые сверх лимита обрезаются).
MAX_EVENTS = _events_limit_from_config()

_store = JsonItemStore(EVENTS_DIR, limit=MAX_EVENTS, name="EVENTS")


def set_events_limit(limit: int) -> None:
    """Горячая смена лимита журнала (Настройки → История и данные).

    Обновляет лимит стора и сразу обрезает журнал под новый размер,
    не дожидаясь следующей записи.
    """
    global MAX_EVENTS
    n = max(1, int(limit))
    _store.limit = n
    MAX_EVENTS = n
    _store.prune()


def _normalize_reason(value: Any) -> Optional[str]:
    """Машинный код причины из свободного значения.

    На сегодня причина живёт в ``details["reason"]`` (её читает политика
    уведомлений, ``core/notification_policy.py``) и всегда содержит
    ``EventReason``. Верхнеуровневое поле ``reason`` нужно как отдельное
    измерение для фильтров аудита, поэтому берём значение только если оно
    похоже на код; свободный текст остаётся в ``details`` и не засоряет
    поле, по которому будут строиться выборки.
    """
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, str) and 0 < len(value) <= 64:
        return value
    return None


def log_event(
    event_type: EventType,
    level: EventLevel,
    title: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    *,
    reason: Any = None,
) -> str:
    """Создаёт событие в журнале.

    ``reason`` — машинный код причины (см. ``EventReason``). Параметр
    явный: собирать код из свободного ``details`` — источник опечаток,
    которые невозможно отфильтровать. Если не передан, значение берётся
    из ``details["reason"]`` — так все существующие вызовы продолжают
    работать без правок.
    """
    details = details or {}
    event = {
        "id": uuid.uuid4().hex,
        "timestamp": datetime.now().isoformat(),
        # Рядом со строкой, не вместо неё: строку читает UI, epoch нужен
        # для сопоставления с метриками и аудитом (§3 плана). Обе метки —
        # момент создания записи, локальная строка остаётся для совместимости.
        "ts_epoch": int(time.time()),
        "type": event_type.value,
        "level": level.value,
        "title": title,
        "message": message,
        "details": details,
        "reason": _normalize_reason(reason if reason is not None else details.get("reason")),
        "read": False,
        "read_time": None
    }

    _store.append(event)

    # Журнал событий только сохраняет событие.
    # Доставка уведомлений выполняется через event_service.

    print(f"[{level.value.upper()}] {title}", flush=True)
    return event["id"]


def load_events() -> List[Dict]:
    """Полный журнал (по возрастанию timestamp)."""
    return _store.load()


def save_events(events: List[Dict]):
    """Полная замена журнала (совместимость, фактически — очистка)."""
    _store.replace_all(events)


def get_event(event_id: str) -> Optional[Dict]:
    """Возвращает актуальное событие по id или None, если оно отсутствует."""
    return _store.get(event_id)


def get_events(limit: int = 100, level: Optional[EventLevel] = None) -> List[Dict]:
    events = load_events()
    if level:
        events = [e for e in events if e["level"] == level.value]
    return sorted(events, key=lambda x: x["timestamp"], reverse=True)[:limit]


def mark_as_read(event_id: str):
    _store.update(event_id, read=True, read_time=datetime.now().isoformat())


def clear_events() -> int:
    """Очистить журнал; возвращает число удалённых событий."""
    return _store.clear()
