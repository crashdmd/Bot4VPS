"""Настройки приложения: лимиты истории, порт Web UI.

Страница «Настройки» (ui/web/static/js/settings.js) собирает параметры из
нескольких доменных API (auth, telegram, monitor, update); здесь живут только
те, что не имели своего эндпоинта:

- ``/api/settings/timezone`` — фактическая IANA timezone локального хоста и
  подтверждённая смена только через ``timedatectl``;
- ``/api/settings/history``  — лимиты logs.tasks / logs.events с горячим
  применением (без перезапуска сервиса);
- ``/api/settings/web``      — текущий порт Web UI + возможность смены;
- ``/api/settings/web/port``  — запуск процедуры смены порта (детached-раннер
  ``core/web_port.py`` переживает restart сервиса и сам откатывает юнит
  при неудачном старте на новом порту).
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..deps import err

router = APIRouter(tags=["settings"])


# ==================================================================
# Часовой пояс локального хоста
# ==================================================================

class TimezoneBody(BaseModel):
    timezone: str


@router.get("/api/settings/timezone")
async def api_settings_timezone_get():
    from core.timezone import HostTimezoneError, timezone_payload

    try:
        return await asyncio.to_thread(timezone_payload, include_options=True)
    except HostTimezoneError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/api/settings/timezone")
async def api_settings_timezone_set(body: TimezoneBody):
    from core.config import set_host_timezone_config
    from core.timezone import (
        HostTimezoneError,
        InvalidTimezoneError,
        set_timezone_verified,
        timezone_details,
    )

    try:
        confirmed = await asyncio.to_thread(
            set_timezone_verified,
            body.timezone,
            set_host_timezone_config,
        )
        return timezone_details(confirmed)
    except InvalidTimezoneError as exc:
        raise HTTPException(400, str(exc)) from exc
    except HostTimezoneError as exc:
        raise HTTPException(500, str(exc)) from exc


# ==================================================================
# История и данные (лимиты хранения)
# ==================================================================

class HistoryLimits(BaseModel):
    tasks: int | None = None
    events: int | None = None


def _validated_limit(value: int, name: str) -> int:
    # bool — подкласс int: чекбокс не должен превращаться в 0/1
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(400, "%s: ожидается целое число" % name)
    if not 1 <= value <= 10000:
        raise HTTPException(400, "%s: от 1 до 10000" % name)
    return value


@router.get("/api/settings/history")
async def api_settings_history_get():
    try:
        from core.config import get_logs_limits
        return get_logs_limits()
    except Exception as e:
        return err(e)


@router.post("/api/settings/history")
async def api_settings_history_set(body: HistoryLimits):
    try:
        tasks = _validated_limit(body.tasks, "tasks") if body.tasks is not None else None
        events = _validated_limit(body.events, "events") if body.events is not None else None
        if tasks is None and events is None:
            raise HTTPException(400, "укажите tasks и/или events")

        # Config сначала — это долговременное намерение. Runtime-применение
        # вторым: если оно упадёт, лимит всё равно вступит в силу после
        # перезапуска (applied: false). Обратный порядок опасен: prune
        # удаляет старые файлы безвозвратно ещё до сохранения config.
        from core.config import set_logs_limits
        set_logs_limits(tasks=tasks, events=events)

        applied = True
        if tasks is not None:
            try:
                from core.task_manager import task_manager
                task_manager.set_history_limit(tasks)
            except Exception as e:
                print("[WEB] set tasks limit: %s" % e, flush=True)
                applied = False
        if events is not None:
            try:
                from core.events import set_events_limit
                set_events_limit(events)
            except Exception as e:
                print("[WEB] set events limit: %s" % e, flush=True)
                applied = False

        from core.config import get_logs_limits
        result = get_logs_limits()
        result["ok"] = True
        result["applied"] = applied
        if not applied:
            result["note"] = "Сохранено; применится полностью после перезапуска сервиса"
        return result
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


# ==================================================================
# Web: порт панели
# ==================================================================

class WebPortBody(BaseModel):
    port: int


@router.get("/api/settings/web")
async def api_settings_web_get():
    try:
        from core.web_port import changeable, current_port_from_unit, busy
        ok, reason = changeable()
        return {
            "port": current_port_from_unit(),
            "changeable": ok,
            "reason": reason,
            "busy": busy(),
        }
    except Exception as e:
        return err(e)


@router.get("/api/settings/web/port-status")
async def api_settings_web_port_status():
    """Состояние процедуры смены порта (раннер пишет в data/web_port.json)."""
    try:
        from core.web_port import read_state
        return read_state()
    except Exception as e:
        return err(e)


@router.post("/api/settings/web/port")
async def api_settings_web_port_set(body: WebPortBody):
    try:
        from core.web_port import (
            busy, changeable, current_port_from_unit, launch, write_state,
        )

        if isinstance(body.port, bool) or not 1 <= body.port <= 65535:
            raise HTTPException(400, "port: от 1 до 65535")

        current = current_port_from_unit()
        if current is None:
            raise HTTPException(400, "порт Web UI не найден в systemd-юните")
        if body.port == current:
            raise HTTPException(400, "порт уже используется: %d" % current)

        ok, reason = changeable()
        if not ok:
            raise HTTPException(400, reason or "смена порта недоступна")
        if busy():
            raise HTTPException(409, "Смена порта уже выполняется")

        write_state(
            status="pending",
            old_port=current,
            new_port=body.port,
            started_at=datetime.now().isoformat(),
            finished_at=None,
            pid=None,
            error=None,
            log=[],
        )
        # Дальше работает detached-раннер: этот процесс будет убит restart'ом
        pid = await asyncio.to_thread(launch, body.port)
        write_state(pid=pid)
        return {
            "ok": True,
            "status": "pending",
            "old_port": current,
            "new_port": body.port,
        }
    except HTTPException:
        raise
    except Exception as e:
        return err(e)
