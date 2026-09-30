"""Контекстный мост отмены из asyncio в синхронные SSH-исполнители."""
from __future__ import annotations

import contextvars
import threading
from typing import Optional


_flag: contextvars.ContextVar[Optional[threading.Event]] = contextvars.ContextVar(
    "task_cancel_flag", default=None
)


def set_flag(flag: threading.Event) -> contextvars.Token[Optional[threading.Event]]:
    return _flag.set(flag)


def reset(token: contextvars.Token[Optional[threading.Event]]) -> None:
    _flag.reset(token)


def current() -> Optional[threading.Event]:
    return _flag.get()
