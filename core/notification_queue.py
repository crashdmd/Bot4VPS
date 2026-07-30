import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

QUEUE_FILE = Path("backup/notification_queue.json")
QUEUE_FILE.parent.mkdir(exist_ok=True)

# Максимум элементов в очереди: все unsent + хвост последних отправленных.
MAX_QUEUE = 500


def add_to_queue(
    event_id: str,
    event_type: str,
    level: str,
    title: str,
    message: str,
    details: Optional[Dict] = None
):
    """Добавляет событие в очередь на доставку."""
    queue = load_queue()

    item = {
        "id": uuid.uuid4().hex,
        "event_id": event_id,
        "type": event_type,
        "level": level,
        "title": title,
        "message": message,
        "details": details or {},
        "created": datetime.now().isoformat(),
        "sent": False,
        "sent_time": None
    }

    queue.append(item)

    # Ограничиваем рост: никогда не удаляем unsent,
    # старые отправленные отбрасываем первыми.
    if len(queue) > MAX_QUEUE:
        unsent = [it for it in queue if not it.get("sent")]
        sent = [it for it in queue if it.get("sent")]
        keep_sent = max(0, MAX_QUEUE - len(unsent))
        queue = unsent + sent[-keep_sent:]

    save_queue(queue)
    return item["id"]


def load_queue() -> List[Dict]:
    if not QUEUE_FILE.exists():
        return []
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_queue(queue: List[Dict]):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


def get_pending_notifications() -> List[Dict]:
    """Возвращает ещё не отправленные уведомления."""
    return [item for item in load_queue() if not item["sent"]]


def mark_as_sent(queue_id: str):
    """Отмечает уведомление как отправленное (по id элемента очереди)."""
    queue = load_queue()
    for item in queue:
        if item["id"] == queue_id:
            item["sent"] = True
            item["sent_time"] = datetime.now().isoformat()
            break
    save_queue(queue)


def mark_event_as_sent(event_id: str):
    """Отмечает уведомление как отправленное (по event_id из журнала)."""
    queue = load_queue()
    changed = False
    for item in queue:
        if item.get("event_id") == event_id and not item.get("sent"):
            item["sent"] = True
            item["sent_time"] = datetime.now().isoformat()
            changed = True
    if changed:
        save_queue(queue)


def clear_sent():
    """Очищает отправленные уведомления (оставляет только pending)."""
    queue = [item for item in load_queue() if not item["sent"]]
    save_queue(queue)
