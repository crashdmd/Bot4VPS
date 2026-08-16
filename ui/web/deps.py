"""Общие хелперы Web UI."""
from __future__ import annotations

import traceback
from typing import Any, Optional

from fastapi.responses import JSONResponse

# Единый источник версии для app.py и /api/ping.
from core.version import APP_VERSION as VERSION


def err(e: Exception, code: int = 500) -> JSONResponse:
    print(f"[WEB] ERROR: {e}\n{traceback.format_exc()}", flush=True)
    return JSONResponse(
        status_code=code,
        content={"detail": str(e), "type": type(e).__name__},
    )


def task_brief(t) -> Optional[dict[str, Any]]:
    if not t:
        return None
    from core.task_manager import STATUS_EMOJI

    return {
        "id": t.id,
        "name": t.name,
        "status": t.status.value,
        "emoji": STATUS_EMOJI.get(t.status, "•"),
        "attempt": t.attempt,
        "kind": t.kind,
        "server_id": t.server_id,
        "server_name": t.server_name,
        "duration": t.duration_human(),
        "duration_seconds": t.duration_seconds,
        "created_at": t.created_at.isoformat(),
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "finished_at": t.finished_at.isoformat() if t.finished_at else None,
        "is_done": t.is_done,
        "error": t.error,
        # История и очереди используют краткое представление, но результат
        # задачи тоже должен быть доступен Web UI (например, при пустом
        # списке серверов). Сохраняем live output как строки, а не только
        # количество строк, чтобы UI мог применить приоритет отображения.
        "output_lines": t.output_lines[-200:],
        "result": {
            "success": t.result.success,
            "exit_code": t.result.exit_code,
            "output": (t.result.output or "")[-4000:],
            "error": t.result.error,
            "warnings": t.result.warnings,
        } if t.result else None,
    }


def queue_state_dict(server_id: str) -> dict:
    from core.task_manager import task_manager

    st = task_manager.get_queue_state(server_id)
    return {
        "paused": st.paused,
        "failed_task_id": st.failed_task_id,
        "failed_task_name": st.failed_task_name,
        "retry_count": st.retry_count,
        "paused_at": st.paused_at.isoformat() if st.paused_at else None,
    }
