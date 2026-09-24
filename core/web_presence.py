"""Присутствие веб-панели: открыта ли она прямо сейчас.

Отвечает ровно на один вопрос — есть ли живое подключение к панели (SSE).
За активностью пользователя не следим: мышь, клавиатура, фокус вкладки и
``visibilitychange`` не учитываются (см. ``plans/TELEGRAM_NOTIFICATIONS_PLAN.md``,
раздел 4). Открытая и забытая вкладка считается открытой панелью.

Учёт по «последнему отклику»: клиент продлевает своё присутствие на каждом
витке SSE-потока, просроченные записи отбрасываются при проверке. Потерянный
при аварии ``disconnect`` поэтому не оставляет вечного «панель открыта».
"""
import threading
import time
from typing import Dict

# Во сколько раз дольше витка SSE-потока (3 с) считать клиента живым.
PRESENCE_TTL_SECONDS = 12.0

_clients: Dict[str, float] = {}
_lock = threading.Lock()


def client_connected(client_id: str) -> None:
    """Клиент подключился к панели (открыт SSE-поток)."""
    if not client_id:
        return
    with _lock:
        _clients[str(client_id)] = time.monotonic()


def touch(client_id: str) -> None:
    """Клиент жив: продлить присутствие (вызывается на каждом витке потока)."""
    client_connected(client_id)


def client_disconnected(client_id: str) -> None:
    """Клиент закрыл панель (поток завершился)."""
    if not client_id:
        return
    with _lock:
        _clients.pop(str(client_id), None)


def is_web_open() -> bool:
    """Есть ли сейчас подключённая веб-панель."""
    now = time.monotonic()
    with _lock:
        for client_id in [
            key
            for key, seen in _clients.items()
            if now - seen > PRESENCE_TTL_SECONDS
        ]:
            del _clients[client_id]
        return bool(_clients)


def client_count() -> int:
    """Сколько клиентов считается подключёнными (отладка и тесты)."""
    is_web_open()
    with _lock:
        return len(_clients)


def reset() -> None:
    """Забыть всех клиентов (остановка панели, тесты)."""
    with _lock:
        _clients.clear()
