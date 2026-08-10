"""Общие хелперы Web UI."""
from __future__ import annotations

import traceback
from typing import Any, Optional

from fastapi.responses import JSONResponse

# Единый источник версии для app.py и /api/ping.
VERSION = "0.6.4"


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
        "is_done": t.is_done,
        "error": t.error,
        "output_lines": len(t.output_lines),
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
