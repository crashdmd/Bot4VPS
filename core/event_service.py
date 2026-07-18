from typing import Dict, Any, Optional

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