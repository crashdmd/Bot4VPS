from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request

from core.timezone import (
    HostTimezoneError,
    current_timezone_name,
    fallback_local_timezone_name,
)

from ..deps import VERSION

router = APIRouter(tags=["meta"])


@router.get("/api/ping")
async def api_ping():
    try:
        timezone_name = await asyncio.to_thread(current_timezone_name)
    except HostTimezoneError:
        timezone_name = fallback_local_timezone_name()
    now = datetime.now(timezone.utc)
    server_time = now.astimezone(ZoneInfo(timezone_name))
    return {
        "ok": True,
        "cwd": os.getcwd(),
        "version": VERSION,
        "server_time": server_time.isoformat(timespec="seconds"),
        "server_ts": now.timestamp(),
        "timezone": timezone_name,
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
