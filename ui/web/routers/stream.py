
from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(tags=["stream"])


async def _light_checks():
    """Фоновые лёгкие TCP-пинги для stale-серверов + события в журнал."""
    try:
        from core.storage import load_servers
        from core.monitor import light_check_servers
        from core.event_service import notify_event
        from core.event_types import EventType, EventLevel, EventReason

        events = await asyncio.to_thread(light_check_servers, load_servers())
        for event in events:
            kind = event["event"]
            if kind == "offline":
                details = {**event, "reason": EventReason.SERVER_OFFLINE.value}
                message = (
                    f"Сервер «{event['server_name']}» стал недоступен."
                    + (f"\nОшибка: {event.get('error')}" if event.get('error') else "")
                )
                await notify_event(
                    EventType.SERVER, EventLevel.CRITICAL,
                    "Сервер недоступен", message, details,
                )
            elif kind == "online":
                details = {**event, "reason": EventReason.SERVER_ONLINE.value}
                await notify_event(
                    EventType.SERVER, EventLevel.INFO,
                    "Сервер снова доступен",
                    f"Сервер «{event['server_name']}» снова в сети.", details,
                )
    except Exception as e:
        print(f"[STREAM] light checks: {e}", flush=True)


def _security_revision():
    """Сигнатура файлов секретов (config.json / servers.json / мастер-ключ)
    для SSE. Меняется при любой записи — из Web, CLI или TG (это разные
    процессы, общего события нет, поэтому сравниваем mtime файлов). Клиент
    по смене сигнатуры перечитывает карточки «Безопасность»."""
    import os

    from core import secretbox

    parts = []
    for path in (secretbox.SCAN_CONFIG_FILE, secretbox.SCAN_SERVERS_FILE, secretbox.KEY_FILE):
        try:
            parts.append(f"{os.path.getmtime(path):.9f}")
        except OSError:
            parts.append("-")
    return ":".join(parts)


def _xui_cache_revision():
    """Непрозрачная сигнатура кэш-файлов 3x-ui для межпроцессного SSE."""
    import hashlib

    from core import integrator

    cache_dir = integrator.CACHE_DIR / "3x-ui"
    if not cache_dir.is_dir():
        parts = ["missing"]
    else:
        parts = []
        for path in sorted(cache_dir.glob("*.json")):
            try:
                stat = path.stat()
            except OSError:
                continue
            parts.append(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}:{stat.st_ino}")
        if not parts:
            parts = ["empty"]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _snapshot():
    """Короткий снимок для SSE (без тяжёлых SSH)."""
    out = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "servers": None,
        "queues": None,
        "events": None,
        "summary": None,
        "monitor": None,
        "task_history_revision": None,
    }
    try:
        from core.storage import load_servers
        from core.monitor import load_monitor
        from core.task_manager import task_manager
        from ..deps import task_brief, queue_state_dict

        mon_all = {}
        try:
            mon_all = load_monitor() or {}
        except Exception:
            pass

        # Серверы + очереди собираем одним проходом через публичный API task_manager
        # (get_running/get_queue/get_queue_state) — приватных атрибутов не трогаем.
        servers = []
        queues = []
        running_n = 0
        online_n = 0
        offline_n = 0
        for s in load_servers():
            sid = s["id"]
            mon = mon_all.get(sid) or {}
            avail = mon.get("availability") or {}
            cert = mon.get("certificate") or {}

            running = task_manager.get_running(sid)
            queue = task_manager.get_queue(sid)
            st = task_manager.get_queue_state(sid)
            has_running = running is not None

            if has_running:
                running_n += 1
            if avail.get("online") is True:
                online_n += 1
            elif avail.get("online") is False:
                offline_n += 1

            servers.append({
                "id": sid,
                "name": s.get("name"),
                "host": s.get("host"),
                "host_ip": mon.get("host_ip"),
                "group": s.get("group"),
                "online": avail.get("online"),
                "port_ok": avail.get("port_ok"),
                "ssh_error": avail.get("ssh_error") or "",
                "last_error": avail.get("last_error") or "",
                "uptime": (mon.get("system") or {}).get("uptime"),
                "uptime_seconds": (mon.get("system") or {}).get("uptime_seconds"),
                "has_running": has_running,
                "running_task_id": running.id if running else None,
                "queue_len": len(queue),
                "certificate_check": bool(s.get("certificate_check")),
                "ssl_status": cert.get("status"),
                "ssl_days_left": cert.get("days_left"),
            })

            if has_running or queue or st.paused:
                queues.append({
                    "server_id": sid,
                    "server_name": s.get("name"),
                    "running": task_brief(running),
                    "queue": [task_brief(t) for t in queue],
                    "paused": st.paused,
                    "failed_task_name": st.failed_task_name,
                    "retry_count": st.retry_count,
                })

        out["servers"] = servers
        out["queues"] = queues
        out["task_history_revision"] = task_manager.history_revision()
        out["summary"] = {
            "servers": len(servers),
            "online": online_n,
            "offline": offline_n,
            "running_tasks": running_n,
            "active_queues": len(queues),
        }
    except Exception as e:
        out["servers_error"] = str(e)

    try:
        from core.events import get_events
        out["events"] = get_events(limit=8)
    except Exception as e:
        out["events_error"] = str(e)

    try:
        from core.config import get_monitor_config, get_update_check_config
        cfg = get_monitor_config()
        cfg["update"] = get_update_check_config()
        out["monitor"] = cfg
    except Exception as e:
        out["monitor_error"] = str(e)

    try:
        out["security_revision"] = _security_revision()
    except Exception as e:
        out["security_revision_error"] = str(e)

    try:
        out["xui_cache_revision"] = _xui_cache_revision()
    except Exception as e:
        out["xui_cache_revision_error"] = str(e)

    return out


@router.get("/api/stream")
async def api_stream(request: Request):
    """
    Server-Sent Events.
    Каждые ~3с — снимок dashboard (серверы, события, monitor).
    Клиент может отказаться от polling.
    """
    async def event_gen():
        # hello
        yield f"event: hello\ndata: {json.dumps({'ok': True})}\n\n"
        # Лёгкие TCP-пинги stale-серверов идут в фоне, пока есть хоть один
        # подключённый SSE-клиент (панель открыта). Следующий снапшот (через 3 с)
        # подхватит обновлённый статус. Событие online/offline — в журнал.
        light_task = None
        while True:
            if await request.is_disconnected():
                break
            try:
                if light_task is None or light_task.done():
                    light_task = asyncio.create_task(_light_checks())
                snap = await asyncio.to_thread(_snapshot)
                yield f"event: snapshot\ndata: {json.dumps(snap, ensure_ascii=False, default=str)}\n\n"
            except Exception as e:
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
            await asyncio.sleep(3)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
