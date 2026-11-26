"""Keep only the browser that initiated an exact, approved security change."""
from __future__ import annotations

import asyncio
import time

from fastapi import HTTPException
from itsdangerous import BadSignature
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import HTTPConnection
from starlette.routing import get_route_path

from ..security import verified_mobile_device_id, web_session_active


class BrowserSessionMiddleware(SessionMiddleware):
    """Keep the original cookie deadline for WebSocket and SSE authorization."""

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket" or (
            scope["type"] == "http" and get_route_path(scope) == "/api/stream"
        ):
            connection = HTTPConnection(scope)
            cookie = connection.cookies.get(self.session_cookie)
            if cookie and not verified_mobile_device_id(connection):
                try:
                    _, issued = self.signer.unsign(cookie, max_age=self.max_age, return_timestamp=True)
                except BadSignature:
                    pass  # SessionMiddleware treats this cookie as anonymous.
                else:
                    scope["web_session_expires"] = issued.timestamp() + self.max_age
        await super().__call__(scope, receive, send)


class BrowserContinuityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = get_route_path(request.scope)
        if path != "/" and not path.startswith("/api/"):
            return await call_next(request)

        session = request.session
        if session.get("user") and not web_session_active(session):
            # Discard a revoked Web identity before any handler can re-sign it,
            # including when the request has an independent Mobile identity.
            session.clear()
        elif not verified_mobile_device_id(request):
            await resume_approved_browser_session(request)

        response = await call_next(request)
        if session.modified and session.get("user") and not web_session_active(session):
            # An API handler may have updated the cookie while logout was in progress.
            session.clear()
        return response


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
    from ..security import auth_enabled, session_valid, auth_version
    from core.config import get_web_config

    session = request.session
    if (not session.get("user") or not auth_enabled() or "recovery_until" in session or session_valid(session)
            or session.get("user") != get_web_config().get("username")):
        return
    try:
        version = await asyncio.to_thread(_approved_version, dict(session))
    except (OSError, ValueError, HTTPException):
        return
    if version is not None and version == auth_version():
        session["auth_version"] = version
