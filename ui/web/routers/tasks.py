
from __future__ import annotations
from typing import Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..deps import err, task_brief

router = APIRouter(tags=["tasks"])

class EnqueueBody(BaseModel):
    script_name: str
    server_id: str
    values: Optional[dict[str, Any]] = None


@router.get("/api/queues")
async def api_queues():
    try:
        from core.storage import load_servers
        from core.task_manager import task_manager
        rows = []
        for s in load_servers():
            sid = s["id"]
            running = task_manager.get_running(sid)
            queue = task_manager.get_queue(sid)
            st = task_manager.get_queue_state(sid)
            if not running and not queue and not st.paused:
                continue
            rows.append({
                "server_id": sid,
                "server_name": s["name"],
                "running": task_brief(running),
                "queue": [task_brief(t) for t in queue],
                "paused": st.paused,
                "failed_task_name": st.failed_task_name,
                "retry_count": st.retry_count,
            })
        return {"queues": rows}
    except Exception as e:
        return err(e)


@router.get("/api/tasks/history")
async def api_history(limit: int = 20, server_id: Optional[str] = None):
    try:
        from core.task_manager import task_manager
        return {"tasks": [task_brief(t) for t in task_manager.get_history(limit=limit, server_id=server_id)]}
    except Exception as e:
        return err(e)


@router.post("/api/tasks/enqueue")
async def api_enqueue(body: EnqueueBody):
    try:
        import core.scripts  # noqa: F401
        from core.scripts import enqueue_script
        from core.task_manager import task_manager
        task = await enqueue_script(body.script_name, body.server_id, body.values or {})
        return {
            "ok": True,
            "task": task_brief(task),
            "position": task_manager.queue_position(task.id),
            "ahead": task_manager.tasks_ahead(task.id),
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        return err(e)


@router.post("/api/queues/{server_id}/continue")
async def api_continue(server_id: str):
    try:
        from core.task_manager import task_manager
        return {"ok": await task_manager.continue_queue(server_id)}
    except Exception as e:
        return err(e)


@router.post("/api/queues/{server_id}/retry")
async def api_retry(server_id: str):
    try:
        from core.task_manager import task_manager
        t = await task_manager.retry_last_failed(server_id)
        return {"ok": t is not None, "task": task_brief(t)}
    except Exception as e:
        return err(e)


@router.post("/api/queues/{server_id}/clear")
async def api_clear(server_id: str):
    try:
        from core.task_manager import task_manager
        return {"ok": True, "cleared": await task_manager.clear_queue(server_id)}
    except Exception as e:
        return err(e)


@router.get("/api/tasks/{task_id}")
async def api_task(task_id: str):
    """Полное состояние задачи: поля Task + emoji/duration/is_done для UI.

    Плоская форма (без обёртки) — её читают live-вывод задачи и модалка лога.
    Поиск по running/queue/history делает task_manager.get_task().
    """
    try:
        from core.task_manager import task_manager, STATUS_EMOJI
        t = task_manager.get_task(task_id)
        if not t:
            raise HTTPException(404, "Задача не найдена")
        data = t.to_dict()
        data["emoji"] = STATUS_EMOJI.get(t.status, "•")
        data["duration"] = t.duration_human()
        data["is_done"] = t.is_done
        data["success"] = t.is_successful
        return data
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.post("/api/tasks/{task_id}/cancel")
async def api_cancel_task(task_id: str):
    """Отмена конкретной задачи (в очереди или выполняющейся).

    Отличие от clear_queue: удаляется только одна задача, остальные продолжают работу.
    """
    try:
        from core.task_manager import task_manager
        ok = await task_manager.cancel(task_id)
        if not ok:
            raise HTTPException(404, "Задача не найдена")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        return err(e)
