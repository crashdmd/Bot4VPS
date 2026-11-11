"""Private Web controls for the paired mobile API."""
from __future__ import annotations

import asyncio
import ipaddress
import base64
import io
import secrets
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, StrictBool, StrictInt

from .._internal.device_access.access import AccessDenied, MobileAccess, PAIR_TTL, pairing_invitation
from .._internal.device_access.preview import MANAGEMENT_PREFIX, private_web_request
from ..security import require_auth


async def private_management(request: Request, response: Response):
    if not private_web_request(request):
        raise HTTPException(404, "Не найдено")
    if request.headers.get("sec-fetch-site", "") not in ("", "same-origin", "none"):
        raise HTTPException(403, "Откройте настройки в самой панели")
    origin = request.headers.get("origin")
    expected = f"{request.url.scheme}://{request.url.netloc}"
    if origin is not None and origin != expected:
        raise HTTPException(403, "Откройте настройки в самой панели")
    if request.headers.get("x-bot4vps-pairing-web") != "1" or (request.method != "GET" and origin != expected):
        raise HTTPException(403, "Откройте настройки в самой панели")
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(dependencies=[Depends(private_management), Depends(require_auth)], include_in_schema=False)


def _settings():
    from core.config import get_web_config
    cfg = get_web_config().get("mobile_api") or {}
    return {"enabled": cfg.get("enabled") is True, "host": cfg.get("host", "0.0.0.0"),
            "port": cfg.get("port", 8444), "public_url": cfg.get("public_url", ""),
            "public_address": cfg.get("public_address", cfg.get("public_url", ""))}


@router.get(MANAGEMENT_PREFIX)
async def state(request: Request):
    settings, devices = await asyncio.gather(asyncio.to_thread(_settings), asyncio.to_thread(MobileAccess().devices))
    listener = getattr(request.app.state, "mobile_api_listener", None)
    task = getattr(listener, "task", None)
    running = bool(getattr(request.app.state, "mobile_api_enabled", False) and listener is not None
                   and (task is None or not task.done())
                   and not getattr(getattr(listener, "server", None), "should_exit", False))
    error = getattr(request.app.state, "mobile_api_error", "")
    if listener is not None and not running and not error:
        error = "Мобильный API остановился"
    pending = listener is not None and any(listener.config.get(k, default) != settings[k] for k, default in (("enabled", False), ("host", "0.0.0.0"), ("port", 8444), ("public_url", "")))
    return {"settings": settings, "running": running, "restart_required": pending,
            "error": error, "devices": devices}


class SettingsBody(BaseModel):
    enabled: StrictBool
    host: str = Field(default="0.0.0.0", max_length=64)
    port: StrictInt = Field(default=8444, ge=1, le=65535)
    public_url: str = Field(default="", max_length=512)
    public_address: str | None = Field(default=None, max_length=512)


def _validate_settings(body: SettingsBody):
    from core.web_port import current_port_from_unit
    try:
        ipaddress.ip_address(body.host)
    except ValueError:
        raise HTTPException(400, "Укажите IP интерфейса сервера Bot4VPS, например 0.0.0.0")
    if body.port == current_port_from_unit():
        raise HTTPException(400, "Порт API должен отличаться от порта веб-панели")
    url = body.public_url.strip().rstrip("/")
    try:
        parsed = urlsplit(url)
        port = parsed.port
        valid = parsed.scheme == "https" and parsed.hostname and not (parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path)
        if not valid or port is not None and not 1 <= port <= 65535:
            raise ValueError()
    except ValueError:
        if url or body.enabled:
            raise HTTPException(400, "Адрес API — https://IP-или-домен:порт, без пути и пароля")
    if body.enabled:
        from .._internal.device_access.identity import server_identity
        try:
            server_identity(url)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    settings = {"enabled": body.enabled, "host": body.host, "port": body.port,
                "public_url": url}
    if body.public_address is not None:
        settings["public_address"] = body.public_address
    return settings


@router.post(MANAGEMENT_PREFIX + "/settings")
async def settings(body: SettingsBody, request: Request):
    from .._internal.device_access.runtime import apply_mobile_settings
    cfg = await asyncio.to_thread(_validate_settings, body)
    # Finish the transaction even if the browser disconnects during a save.
    try:
        return await asyncio.shield(apply_mobile_settings(request.app, cfg))
    except (RuntimeError, OSError) as exc:
        raise HTTPException(503, str(exc)) from exc


class PairBody(BaseModel):
    name: str = Field(default="Мой телефон", max_length=80)


@router.post(MANAGEMENT_PREFIX + "/pair")
async def pair(body: PairBody, request: Request):
    listener = getattr(request.app.state, "mobile_api_listener", None)
    if not getattr(request.app.state, "mobile_api_enabled", False) or listener is None:
        raise HTTPException(409, "API ещё не запущен. Сохраните настройки подключения.")
    cfg = await asyncio.to_thread(_settings)
    if not cfg["public_url"] or any(listener.config.get(k, default) != cfg[k] for k, default in (("enabled", False), ("host", "0.0.0.0"), ("port", 8444), ("public_url", ""))):
        raise HTTPException(409, "Настройки API изменились. Сначала сохраните настройки подключения.")
    access = MobileAccess()
    status_token = secrets.token_urlsafe(32)
    try:
        code = await asyncio.to_thread(access.issue_pairing_code, body.name, status_token=status_token)
    except AccessDenied as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    invitation_code = pairing_invitation(cfg["public_url"], code, listener.identity["server_pin"])
    def render_qr():
        import qrcode
        image = qrcode.make(invitation_code)
        output = io.BytesIO()
        image.save(output, format="PNG")
        return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    qr = await asyncio.to_thread(render_qr)
    from core import audit
    await asyncio.to_thread(audit.record, audit.AuditAction.MOBILE_PAIR_CODE, result=audit.AuditResult.OK,
                            params={"name": body.name, "expires_in": PAIR_TTL})
    from fastapi.responses import JSONResponse
    return JSONResponse({"code": invitation_code, "qr": qr, "status_token": status_token,
                         "expires_in": PAIR_TTL, "public_url": cfg["public_url"]}, headers={"Cache-Control": "no-store"})


class PairStatusBody(BaseModel):
    status_token: str = Field(min_length=40, max_length=64)


@router.post(MANAGEMENT_PREFIX + "/pair/status")
async def pair_status(body: PairStatusBody):
    return await asyncio.to_thread(MobileAccess().pairing_status, body.status_token)


@router.post(MANAGEMENT_PREFIX + "/revoke/{device_id}")
async def revoke(device_id: str):
    removed = await asyncio.to_thread(MobileAccess().revoke, device_id)
    if removed:
        from core import audit
        await asyncio.to_thread(audit.record, audit.AuditAction.MOBILE_DEVICE_REVOKE, result=audit.AuditResult.OK,
                                params={"device_id": removed["id"], "name": removed.get("name")})
    return {"ok": True}
