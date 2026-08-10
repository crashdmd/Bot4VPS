
from __future__ import annotations
import os
import time
from datetime import datetime, timezone
from fastapi import APIRouter, Request

from ..deps import VERSION

router = APIRouter(tags=["meta"])

@router.get("/api/ping")
async def api_ping():
    now = datetime.now().astimezone()
    return {
        "ok": True,
        "cwd": os.getcwd(),
        "version": VERSION,
        "server_time": now.isoformat(timespec="seconds"),
        "server_ts": time.time(),
        "timezone": str(now.tzinfo),
    }

@router.get("/api/routes")
async def api_routes(request: Request):
    routes = []
    for r in request.app.routes:
        path = getattr(r, "path", None)
        methods = sorted(getattr(r, "methods", []) or [])
        if path:
            routes.append({"path": path, "methods": methods})
    return {"routes": routes, "count": len(routes)}
