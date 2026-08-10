
from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(tags=["stream"])


def _snapshot():
    """Короткий снимок для SSE (без тяжёлых SSH)."""
    out = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "servers": None,
        "queues": None,
        "events": None,
        "summary": None,
        "monitor": None,
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
                "group": s.get("group"),
                "online": avail.get("online"),
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
        from core.config import get_monitor_config
        out["monitor"] = get_monitor_config()
    except Exception as e:
        out["monitor_error"] = str(e)

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
        while True:
            if await request.is_disconnected():
                break
            try:
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
