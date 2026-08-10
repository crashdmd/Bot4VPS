from typing import Dict, Any, Optional, Callable, Awaitable, List

from .events import log_event
from .event_types import EventType, EventLevel
from .notification_queue import add_to_queue


def create_event(
    event_type: EventType,
    level: EventLevel,
    title: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    notify: bool = False,
) -> str:
    """
    Создать событие и при необходимости поставить его
    в очередь уведомлений.
    """

    event_id = log_event(
        event_type=event_type,
        level=level,
        title=title,
        message=message,
        details=details,
    )

    if level == EventLevel.CRITICAL or notify:
        add_to_queue(
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

NotifierFn = Callable[[Dict[str, Any], Optional[str]], Awaitable[None]]

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
    notification: Dict[str, Any], event_id: Optional[str] = None
) -> None:
    """Немедленно разослать событие через все зарегистрированные нотификаторы."""
    for fn in list(_NOTIFIERS):
        try:
            await fn(notification, event_id)
        except Exception as e:
            print(f"[NOTIFIER] {e}", flush=True)


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