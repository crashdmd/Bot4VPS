"""Очередь доставки уведомлений — служебный state, ``logs/notification_queue.json``.

Весь read-modify-write проходит под одним lock (sidecar lock-файл +
``fcntl.flock`` + потоковая блокировка), запись атомарна
(tmp + ``os.replace`` + fsync файла и каталога). Повреждённый JSON
переносится в карантин, очередь считается пустой.

Успешно доставленные элементы удаляются из очереди сразу — файл содержит
только pending. Лимитов истории нет: очередь не показывается пользователю.
"""
import math
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from core.json_store import JsonDocumentStore

QUEUE_FILE = Path("logs/notification_queue.json")

_store = JsonDocumentStore(QUEUE_FILE, name="NOTIF QUEUE")

_DELIVERY_CLAIM_KEY = "delivery_claim"
_DELIVERY_CLAIM_TTL_SECONDS = 5 * 60


def _claim_is_active(item: Dict[str, Any], now: float) -> bool:
    claim = item.get(_DELIVERY_CLAIM_KEY)
    if not isinstance(claim, dict):
        return False
    owner = claim.get("owner")
    expires_at = claim.get("expires_at")
    return bool(
        isinstance(owner, str)
        and owner
        and isinstance(expires_at, (int, float))
        and not isinstance(expires_at, bool)
        and math.isfinite(float(expires_at))
        and expires_at > now
    )


def add_to_queue(
    event_id: str,
    event_type: str,
    level: str,
    title: str,
    message: str,
    details: Optional[Dict] = None
):
    """Добавляет событие в очередь идемпотентно по ``event_id``."""
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
    queue_id = item["id"]

    def _add(queue: List[Dict]) -> List[Dict]:
        nonlocal queue_id
        if isinstance(event_id, str) and event_id:
            for existing in queue:
                if (
                    existing.get("event_id") == event_id
                    and not existing.get("sent")
                    and isinstance(existing.get("id"), str)
                    and existing.get("id")
                ):
                    queue_id = str(existing["id"])
                    return list(queue)
        return list(queue) + [item]

    _store.mutate(_add)
    return queue_id


def load_queue() -> List[Dict]:
    return _store.read()


def save_queue(queue: List[Dict]):
    _store.write(queue)


def get_pending_notifications() -> List[Dict]:
    """Вернуть не более одного свободного item на durable event."""
    now = time.time()
    queue = load_queue()
    active_events = {
        item.get("event_id")
        for item in queue
        if (
            not item.get("sent")
            and isinstance(item.get("event_id"), str)
            and item.get("event_id")
            and _claim_is_active(item, now)
        )
    }
    pending = []
    seen_events = set()
    for item in queue:
        if item.get("sent") or _claim_is_active(item, now):
            continue
        event_id = item.get("event_id")
        if isinstance(event_id, str) and event_id:
            if event_id in active_events or event_id in seen_events:
                continue
            seen_events.add(event_id)
        pending.append(item)
    return pending


def claim_notification(
    owner: str,
    *,
    queue_id: Optional[str] = None,
    event_id: Optional[str] = None,
    lease_seconds: float = _DELIVERY_CLAIM_TTL_SECONDS,
) -> Optional[Dict]:
    """Атомарно закрепить durable event за одной попыткой доставки."""
    if not isinstance(owner, str) or not owner:
        raise ValueError("owner должен быть непустой строкой")
    if (queue_id is None) == (event_id is None):
        raise ValueError("нужно указать ровно один queue_id или event_id")
    if (
        not isinstance(lease_seconds, (int, float))
        or isinstance(lease_seconds, bool)
        or not math.isfinite(float(lease_seconds))
        or lease_seconds <= 0
    ):
        raise ValueError("lease_seconds должен быть положительным числом")

    now = time.time()
    claimed: Optional[Dict] = None

    def _claim(queue: List[Dict]) -> List[Dict]:
        nonlocal claimed
        updated_queue = list(queue)
        candidate_index = None
        candidate_event_id = None

        for index, item in enumerate(updated_queue):
            matches = (
                item.get("id") == queue_id
                if queue_id is not None
                else item.get("event_id") == event_id
            )
            if matches and not item.get("sent"):
                candidate_index = index
                candidate_event_id = item.get("event_id")
                break

        if candidate_index is None:
            return updated_queue

        for item in updated_queue:
            same_event = (
                isinstance(candidate_event_id, str)
                and bool(candidate_event_id)
                and item.get("event_id") == candidate_event_id
            )
            same_item = item.get("id") == updated_queue[candidate_index].get("id")
            if (
                not item.get("sent")
                and (same_event or same_item)
                and _claim_is_active(item, now)
            ):
                return updated_queue

        for index, item in enumerate(updated_queue):
            same_event = (
                isinstance(candidate_event_id, str)
                and bool(candidate_event_id)
                and item.get("event_id") == candidate_event_id
            )
            same_item = item.get("id") == updated_queue[candidate_index].get("id")
            if same_event or same_item:
                without_stale_claim = dict(item)
                without_stale_claim.pop(_DELIVERY_CLAIM_KEY, None)
                updated_queue[index] = without_stale_claim

        updated = dict(updated_queue[candidate_index])
        updated[_DELIVERY_CLAIM_KEY] = {
            "owner": owner,
            "expires_at": now + float(lease_seconds),
        }
        updated_queue[candidate_index] = updated
        claimed = dict(updated)
        return updated_queue

    _store.mutate(_claim)
    return claimed


def complete_notification(queue_id: str, owner: str) -> bool:
    """Завершить owned attempt и удалить все rows того же event."""
    completed = False

    def _complete(queue: List[Dict]) -> List[Dict]:
        nonlocal completed
        owned_event_id = None
        for item in queue:
            claim = item.get(_DELIVERY_CLAIM_KEY)
            if (
                item.get("id") == queue_id
                and isinstance(claim, dict)
                and claim.get("owner") == owner
            ):
                owned_event_id = item.get("event_id")
                completed = True
                break

        if not completed:
            return list(queue)
        if isinstance(owned_event_id, str) and owned_event_id:
            return [
                item
                for item in queue
                if item.get("event_id") != owned_event_id
            ]
        return [item for item in queue if item.get("id") != queue_id]

    _store.mutate(_complete)
    return completed


def release_notification(queue_id: str, owner: str) -> bool:
    """Освободить item после неуспешной попытки, сохранив его pending."""
    released = False

    def _release(queue: List[Dict]) -> List[Dict]:
        nonlocal released
        updated_queue = []
        for item in queue:
            claim = item.get(_DELIVERY_CLAIM_KEY)
            owned = (
                item.get("id") == queue_id
                and isinstance(claim, dict)
                and claim.get("owner") == owner
            )
            if not owned:
                updated_queue.append(item)
                continue
            updated = dict(item)
            updated.pop(_DELIVERY_CLAIM_KEY, None)
            updated_queue.append(updated)
            released = True
        return updated_queue

    _store.mutate(_release)
    return released


def mark_as_sent(queue_id: str):
    """Успешно доставленный элемент удаляется из очереди."""
    _store.mutate(
        lambda queue: [it for it in queue if it.get("id") != queue_id]
    )


def mark_event_as_sent(event_id: str):
    """Удаляет все ещё не доставленные элементы с данным event_id."""
    def _drop(queue: List[Dict]) -> List[Dict]:
        return [
            it for it in queue
            if not (it.get("event_id") == event_id and not it.get("sent"))
        ]

    _store.mutate(_drop)


def clear_sent():
    """Совместимость: отправленные элементы удаляются сразу при доставке,
    поэтому здесь чистить нечего."""
    _store.mutate(
        lambda queue: [it for it in queue if not it.get("sent")]
    )
