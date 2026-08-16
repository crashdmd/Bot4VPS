import json
import uuid
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from .event_types import EventType, EventLevel

EVENTS_FILE = Path("logs/events.json")
EVENTS_FILE.parent.mkdir(exist_ok=True)

# Лимит размера журнала событий (старые сверх лимита обрезаются).
MAX_EVENTS = 100

# Блокировка для атомарных RMW над журналом (писатели в разных потоках).
_EVENTS_LOCK = threading.RLock()


def log_event(
    event_type: EventType,
    level: EventLevel,
    title: str,
    message: str,
    details: Optional[Dict[str, Any]] = None
) -> str:
    """Создаёт событие в журнале."""
    event = {
        "id": uuid.uuid4().hex,
        "timestamp": datetime.now().isoformat(),
        "type": event_type.value,
        "level": level.value,
        "title": title,
        "message": message,
        "details": details or {},
        "read": False,
        "read_time": None
    }

    with _EVENTS_LOCK:
        events = load_events()
        events.append(event)
        # Не даём журналу расти без границы — оставляем свежие.
        if len(events) > MAX_EVENTS:
            events = events[-MAX_EVENTS:]
        save_events(events)

    # Журнал событий только сохраняет событие.
    # Доставка уведомлений выполняется через event_service.

    print(f"[{level.value.upper()}] {title}", flush=True)
    return event["id"]


def load_events() -> List[Dict]:
    if not EVENTS_FILE.exists():
        return []
    try:
        with open(EVENTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_events(events: List[Dict]):
    with open(EVENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, indent=2)


def get_event(event_id: str) -> Optional[Dict]:
    """Возвращает актуальное событие по id или None, если оно отсутствует."""
    with _EVENTS_LOCK:
        for event in load_events():
            if event.get("id") == event_id:
                return event
    return None


def get_events(limit: int = 100, level: Optional[EventLevel] = None) -> List[Dict]:
    events = load_events()
    if level:
        events = [e for e in events if e["level"] == level.value]
    return sorted(events, key=lambda x: x["timestamp"], reverse=True)[:limit]


def mark_as_read(event_id: str):
    with _EVENTS_LOCK:
        events = load_events()
        for e in events:
            if e["id"] == event_id:
                e["read"] = True
                e["read_time"] = datetime.now().isoformat()
                break
        save_events(events)