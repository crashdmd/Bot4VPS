"""Межпроцессное состояние Telegram-бота (data/telegram_state.json).

Проблема: runtime-состояние бота (запущен / ошибка старта / выключен)
живёт в глобалах процесса bot.py (``_application``, ``_last_start_error``).
Web UI видит его, потому что в режиме web+tg хостит бота сам; для CLI
(третий процесс) нужен внешний носитель — по образцу data/update/state.json.

Точки записи — ровно четыре, по одной на переход lifecycle
(см. bot.py start_telegram/stop_telegram и ui/web/app.py lifespan):

  running   — бот запущен (polling работает)
  failed    — старт провалился, error — человекочитаемая причина
  stopped   — бот корректно остановлен (shutdown/rollback)
  disabled  — telegram_enabled=false
  no_token  — токен не задан

Свежесть для внешнего читателя: ``updated_at`` (локальное время, ISO).
CLI сравнивает его с systemd ActiveEnterTimestamp: состояние, записанное
до старта текущего запуска сервиса, — протухшее (процесс падал).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
STATE_FILE = APP_DIR / "data" / "telegram_state.json"

# Валидные статусы lifecycle
STATUSES = ("running", "failed", "stopped", "disabled", "no_token")


def read_state() -> dict:
    """Толерантное чтение: битый/отсутствующий файл -> пустой dict."""
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("telegram_state.json: ожидается объект")
        return data
    except (OSError, ValueError):
        return {}


def write_state(status: str, error: str | None = None) -> dict:
    """Атомарная запись состояния (tmp -> fsync -> os.replace).

    Ошибка записи не должна ронять lifecycle бота — глотаем OSError.
    """
    state = {
        "status": status,
        "error": error,
        "updated_at": datetime.now().isoformat(),
    }
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass
    return state
