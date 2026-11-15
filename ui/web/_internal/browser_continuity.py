"""Keep only the browser that initiated an exact, approved security change."""
from __future__ import annotations

import asyncio
import time

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware


class BrowserContinuityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path.startswith('/api/'):
            await resume_approved_browser_session(request)
        return await call_next(request)


def _approved_version(session):
    from ..security import auth_version
    from .auth_flows import AuthFlows, fingerprint
    from .device_access.access import MobileAccess
    browser = session.get("auth_browser")
    previous = session.get("auth_version")
    if not isinstance(browser, str) or not isinstance(previous, str):
        return None
    access = MobileAccess()
    flow_id = session.get("two_factor_flow")
    if flow_id:
        try:
            row = AuthFlows().two_factor_status(flow_id, browser)
        except HTTPException:
            row = {}
        if (row.get("completed") and row.get("state") == "approved"
                and row.get("initiating_version") == previous and row.get("username") == session.get("user")
                and row.get("version") == auth_version()
                and (not row.get("device_id") or access.device_exists(row["device_id"]))):
            return row["version"]
    status_hash = session.get("mobile_pairing_status")
    if not isinstance(status_hash, str):
        return None
    for device in access.store.read():
        binding = device.get("pairing_auth_continuity") or {}
        if (device.get("kind") == "device" and device.get("status_hash") == status_hash
                and binding.get("browser") == fingerprint(browser) and binding.get("version") == previous
                and binding.get("expires", 0) > time.time() and binding.get("approved_version") == auth_version()):
            return binding["approved_version"]
    return None


async def resume_approved_browser_session(request):
    from ..security import auth_enabled, session_valid, verified_mobile_device_id, auth_version
    from core.config import get_web_config
    session = request.session
    if (verified_mobile_device_id(request) or not auth_enabled() or not session.get("user")
            or "recovery_until" in session or session_valid(session)
            or session.get("user") != get_web_config().get("username")):
        return
    try:
        version = await asyncio.to_thread(_approved_version, dict(session))
    except (OSError, ValueError, HTTPException):
        return
    if version is not None and version == auth_version():
        session["auth_version"] = version
