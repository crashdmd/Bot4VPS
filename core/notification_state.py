"""Состояние Telegram-доставки: что уже сообщено и когда.

Три поля:

* по каждому серверу — последнее состояние доступности, которое было
  **фактически сообщено пользователю** (основа схлопывания «упал и поднялся»,
  план §6);
* время последней отправки в Telegram — чтобы при открытой панели сообщения
  уходили не чаще одного раза в N (план §4);
* живые сообщения-сводки по чатам — id сообщения, его события и id сводки
  (см. ``live_messages``). Пока такое сообщение не прочитано, новые события
  в него ДОПИСЫВАЮТСЯ, а не уходят вторым сообщением; состояние переживает
  перезапуск панели, иначе каждый рестарт начинал бы новую сводку.

Хранится на диске рядом с очередью доставки: перезапуск Bot4VPS не должен
приводить к повторному сообщению о том же состоянии. В ``monitor.json`` это
состояние не пишется — слой мониторинга отвечает за факт, а не за доставку
(план §7).
"""
import json
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from core.json_store import atomic_write_json, locked, quarantine

STATE_FILE = Path("logs/notification_state.json")
NAME = "NOTIF STATE"

ONLINE = "online"
OFFLINE = "offline"

_thread_lock = threading.RLock()


def _path() -> Path:
    return Path(STATE_FILE)


def _lock_path() -> Path:
    path = _path()
    return path.with_name(path.name + ".lock")


def _read_unlocked() -> dict:
    path = _path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"[{NAME}] Не удалось прочитать {path}: {exc}. "
            "Файл перенесён в карантин.",
            flush=True,
        )
        quarantine(path)
        return {}
    return raw if isinstance(raw, dict) else {}


def _mutate(fn: Callable[[dict], dict]) -> dict:
    with locked(_lock_path(), _thread_lock):
        updated = fn(_read_unlocked())
        atomic_write_json(_path(), updated)
        return updated


def read_state() -> dict:
    """Снимок состояния (для отладки и тестов)."""
    with locked(_lock_path(), _thread_lock):
        return dict(_read_unlocked())


def get_last_reported(server_id) -> Optional[str]:
    """Последнее сообщённое состояние сервера; None — о сервере не сообщали."""
    if not server_id:
        return None
    state = (_read_unlocked().get("servers") or {}).get(str(server_id))
    return state if state in (ONLINE, OFFLINE) else None


def set_last_reported(server_id, state: str) -> None:
    """Запомнить фактически сообщённое состояние сервера."""
    if not server_id or state not in (ONLINE, OFFLINE):
        return
    key = str(server_id)

    def _apply(current: dict) -> dict:
        servers = current.get("servers")
        if not isinstance(servers, dict):
            servers = {}
        servers[key] = state
        current["servers"] = servers
        return current

    _mutate(_apply)


def get_last_sent_at() -> Optional[float]:
    """Время последней отправки в Telegram (epoch); None — ещё не отправляли."""
    value = _read_unlocked().get("last_sent_at")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def set_last_sent_at(timestamp: Optional[float] = None) -> float:
    """Отметить отправку в Telegram (по умолчанию — сейчас)."""
    moment = time.time() if timestamp is None else float(timestamp)

    def _apply(current: dict) -> dict:
        current["last_sent_at"] = moment
        return current

    _mutate(_apply)
    return moment


def get_live_message(chat_id) -> Optional[dict]:
    """Живое сообщение-сводка чата; None — живого сообщения нет.

    Возвращает ``{"message_id": int, "event_ids": [str], "digest_id": str|None}``.
    """
    if chat_id is None:
        return None
    live = _read_unlocked().get("live_messages")
    if not isinstance(live, dict):
        return None
    record = live.get(str(chat_id))
    if not isinstance(record, dict):
        return None
    message_id = record.get("message_id")
    if isinstance(message_id, bool) or not isinstance(message_id, int):
        return None
    event_ids = record.get("event_ids")
    if not isinstance(event_ids, list):
        return None
    digest_id = record.get("digest_id")
    return {
        "message_id": message_id,
        "event_ids": [str(eid) for eid in event_ids if eid],
        "digest_id": digest_id if isinstance(digest_id, str) and digest_id else None,
    }


def set_live_message(chat_id, message_id, event_ids, digest_id=None) -> None:
    """Запомнить живое сообщение-сводку чата (переживает перезапуск панели)."""
    if chat_id is None:
        return
    if isinstance(message_id, bool) or not isinstance(message_id, int):
        return
    record = {
        "message_id": message_id,
        "event_ids": [str(eid) for eid in (event_ids or []) if eid],
        "digest_id": digest_id if isinstance(digest_id, str) and digest_id else None,
    }

    def _apply(current: dict) -> dict:
        live = current.get("live_messages")
        if not isinstance(live, dict):
            live = {}
        live[str(chat_id)] = record
        current["live_messages"] = live
        return current

    _mutate(_apply)


def clear_live_message(chat_id) -> None:
    """Забыть живое сообщение чата (прочитано/закрыто/удалено)."""
    if chat_id is None:
        return

    def _apply(current: dict) -> dict:
        live = current.get("live_messages")
        if isinstance(live, dict):
            live.pop(str(chat_id), None)
            if not live:
                current.pop("live_messages", None)
        return current

    _mutate(_apply)


def reset() -> None:
    """Забыть состояние (тесты, сброс настроек)."""
    def _apply(_current: dict) -> dict:
        return {}

    _mutate(_apply)
