from typing import Dict, Any, Optional, Callable, Awaitable, List

from .events import log_event
from .event_types import EventType, EventLevel
from .notification_queue import add_to_queue


def enqueue_event(
    event_id: str,
    event_type: str,
    level: str,
    title: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
):
    """Put an already journaled event into the idempotent fallback queue."""
    return add_to_queue(
        event_id=event_id,
        event_type=event_type,
        level=level,
        title=title,
        message=message,
        details=details,
    )


def create_event(
    event_type: EventType,
    level: EventLevel,
    title: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    notify: bool = False,
    *,
    enqueue: Optional[bool] = None,
) -> str:
    """
    Создать journal event и, если выбрано, поставить его в очередь уведомлений.

    ``enqueue=None`` сохраняет прежнее поведение. ``enqueue=False`` позволяет
    сначала попробовать immediate delivery, оставляя queue только fallback-путём.
    """

    event_id = log_event(
        event_type=event_type,
        level=level,
        title=title,
        message=message,
        details=details,
    )

    should_enqueue = (
        level == EventLevel.CRITICAL or notify
        if enqueue is None
        else bool(enqueue)
    )
    if should_enqueue:
        enqueue_event(
            event_id=event_id,
            event_type=event_type.value,
            level=level.value,
            title=title,
            message=message,
            details=details,
        )

    return event_id


# --------------------------------------------------
# Реестр нотификаторов немедленной доставки.
# Ядро не знает про Telegram: UI регистрирует здесь свой
# отправщик при старте (bot.py), а асинхронные источники
# событий (job'ы мониторинга) зовут notify_event().
# --------------------------------------------------

NotifierFn = Callable[[Dict[str, Any], Optional[str]], Awaitable[bool]]

_NOTIFIERS: List[NotifierFn] = []


def register_notifier(fn: NotifierFn, *, replace: bool = False) -> None:
    """Зарегистрировать асинхронный отправщик уведомлений.

    replace=True — очистить реестр и поставить только этот fn
    (идемпотентный старт / uvicorn --reload).
    Иначе fn добавляется один раз (без дублей по identity).
    """
    global _NOTIFIERS
    if replace:
        _NOTIFIERS = [fn]
        return
    if fn not in _NOTIFIERS:
        _NOTIFIERS.append(fn)


def clear_notifiers() -> None:
    """Сбросить все нотификаторы (shutdown / reload)."""
    _NOTIFIERS.clear()


def unregister_notifier(fn: NotifierFn) -> None:
    if fn in _NOTIFIERS:
        _NOTIFIERS.remove(fn)


async def dispatch_notifiers(
    notification: Dict[str, Any],
    event_id: Optional[str] = None,
    *,
    fallback_to_queue: bool = False,
) -> bool:
    """Немедленно разослать событие и вернуть, была ли доставка успешной.

    При ``fallback_to_queue`` journal-only event ставится в существующую
    idempotent queue только после полного провала immediate delivery.
    """
    delivery_notification = notification
    if fallback_to_queue:
        # The fallback path starts from a journal-only event, so a notifier must
        # not try to claim a queue row that is intentionally absent.
        delivery_notification = dict(notification)
        delivery_notification["_journal_only"] = True

    delivered = False
    for fn in list(_NOTIFIERS):
        try:
            delivered = bool(await fn(delivery_notification, event_id)) or delivered
        except Exception as e:
            print(f"[NOTIFIER] {e}", flush=True)

    if fallback_to_queue and not delivered and isinstance(event_id, str) and event_id:
        enqueue_event(
            event_id=event_id,
            event_type=notification.get("type", ""),
            level=notification.get("level", ""),
            title=notification.get("title", "Событие"),
            message=notification.get("message", ""),
            details=notification.get("details") or notification.get("data") or {},
        )
    return delivered


async def notify_event(
    event_type: EventType,
    level: EventLevel,
    title: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Лог + очередь + немедленная рассылка.

    Единая точка для асинхронных источников событий: записывает событие
    в журнал, ставит в очередь (для досылки при /start) и сразу рассылает
    через зарегистрированные нотификаторы.
    """
    event_id = create_event(
        event_type=event_type,
        level=level,
        title=title,
        message=message,
        details=details,
        notify=True,
    )
    await dispatch_notifiers(
        {
            "type": event_type.value,
            "level": level.value,
            "title": title,
            "message": message,
            "details": details or {},
        },
        event_id,
    )
    return event_id
