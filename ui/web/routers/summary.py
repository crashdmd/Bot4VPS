
from __future__ import annotations
from fastapi import APIRouter
from ..deps import err

router = APIRouter(tags=["summary"])

@router.get("/api/summary")
async def api_summary():
    try:
        from core.storage import load_servers
        from core.config import get_monitor_config
        from core.task_manager import task_manager, list_executors
        import core.scripts  # noqa: F401

        servers = load_servers()
        running = queued = paused = active = 0
        for s in servers:
            sid = s["id"]
            has = task_manager.get_running(sid) is not None
            q = task_manager.get_queue(sid)
            st = task_manager.get_queue_state(sid)
            if has:
                running += 1
            queued += len(q)
            if st.paused:
                paused += 1
            if has or q or st.paused:
                active += 1
        return {
            "ok": True,
            "servers": len(servers),
            "running_tasks": running,
            "queued_tasks": queued,
            "active_queues": active,
            "paused_queues": paused,
            "monitor": get_monitor_config(),
            "executors": list_executors(),
        }
    except Exception as e:
        return err(e)
