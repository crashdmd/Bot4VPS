"""Browser login polling and authenticated, signed phone decisions."""
from __future__ import annotations

import asyncio
import base64
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from .._internal.auth_flows import AuthFlows, browser_id
from .._internal.device_access.access import MobileAccess
from ..security import (auth_enabled, establish_web_session, require_auth,
                        set_request_actor, verified_mobile_device_id)


class AuthTransportMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        protected = (path in ("/api/login", "/api/logout") or path.startswith("/api/login/") or
                     path.startswith("/api/auth/") or "/unlink" in path or
                     path.endswith("/protection") or "/revoke/" in path or
                     path.startswith("/api/mobile/security"))
        if protected:
            mobile_device = verified_mobile_device_id(request)
            https_required = getattr(request.app.state, "auth_https_required", True)
            if request.url.scheme != "https" and (https_required or mobile_device):
                return JSONResponse({"detail": "Для авторизации и управления защитой откройте панель по HTTPS"}, status_code=400)
            if not mobile_device:
                origin = f"{request.url.scheme}://{request.url.netloc}"
                if (request.headers.get("sec-fetch-site", "") not in ("", "same-origin", "none") or
                    (request.method != "GET" and request.headers.get("origin") != origin)):
                    return JSONResponse({"detail": "Откройте действие в самой панели"}, status_code=403)
        response = await call_next(request)
        if protected:
            response.headers["Cache-Control"] = "no-store"
            if request.url.scheme == "https":
                response.raw_headers = [
                    (key, value + b"; Secure" if key.lower() == b"set-cookie" and
                     b"secure" not in {part.strip() for part in value.lower().split(b";")} else value)
                    for key, value in response.raw_headers
                ]
        return response


router = APIRouter()


class FlowBody(BaseModel):
    id: str


@router.post("/api/login/qr")
async def qr_login(request: Request):
    from core.config import get_web_config
    from .._internal.device_access.identity import configured_identity
    if not auth_enabled():
        raise HTTPException(409, "Авторизация выключена")
    cfg = await asyncio.to_thread(get_web_config)
    mobile = cfg.get("mobile_api") or {}
    flows = AuthFlows()
    if not any(r.get("kind") == "device" for r in await asyncio.to_thread(flows.store.read)):
        return {"available": False, "trusted_device": False, "hint": "Вход по QR доступен после привязки телефона"}
    if not mobile.get("enabled") or not mobile.get("public_url"):
        return {"available": False, "trusted_device": True, "hint": "Для входа по QR включите мобильный API в настройках панели"}
    identity = await asyncio.to_thread(configured_identity, mobile)
    row = await asyncio.to_thread(flows.create_login, browser_id(request), "qr", cfg.get("username", "admin"),
                                 ip=request.client.host if request.client else None,
                                 agent=request.headers.get("user-agent", ""))
    request.session["auth_login"] = row["id"]
    payload = {"version": 1, "action": "login", "url": mobile["public_url"],
               "server_pin": identity["server_pin"], "id": row["id"], "nonce": row["nonce"]}
    invitation = "b4vps-auth:" + base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    from ..app import _totp_qr_data_url
    qr = await asyncio.to_thread(_totp_qr_data_url, invitation)
    return {"available": True, "trusted_device": True, "id": row["id"], "qr": qr, "expires_in": 300}


@router.post("/api/login/status")
async def login_status(request: Request, body: FlowBody):
    flows = AuthFlows()
    row = await asyncio.to_thread(flows.login_status, body.id, browser_id(request), consume=True)
    if row["state"] == "approved":
        establish_web_session(request, row["username"], expected_version=row["version"])
        if row.get("approved_by"):
            request.session["auth_device"] = row["approved_by"]
        await asyncio.to_thread(flows.new_ip_notice, row.get("ip"), row.get("agent", ""), notify=False)
        return {"ok": True, "state": "approved", "user": row["username"]}
    return {"ok": False, "state": row["state"], "expires_in": max(0, int(row["expires"] - time.time()))}


@router.post("/api/login/cancel")
async def cancel_login(request: Request):
    await asyncio.to_thread(AuthFlows().cancel_login, browser_id(request))
    request.session.pop("auth_login", None)
    return {"ok": True}


class RecoveryBody(BaseModel):
    code: str


class TotpReplaceBody(BaseModel):
    password: str
    code: str = ""


@router.post("/api/auth/totp/setup/replace", dependencies=[Depends(require_auth)])
async def replace_totp(request: Request, body: TotpReplaceBody):
    from core.config import get_web_config
    from ..security import verify_password, totp_enabled, verify_totp_code, get_totp_secret, auth_version, session_valid
    if not session_valid(request.session):
        raise HTTPException(401, "Требуется авторизация")
    web = await asyncio.to_thread(get_web_config)
    if not await asyncio.to_thread(verify_password, body.password, web.get("password_hash", "")):
        raise HTTPException(403, "Неверный пароль администратора")
    if totp_enabled() and not await asyncio.to_thread(verify_totp_code, body.code, get_totp_secret()):
        raise HTTPException(403, "Подтвердите замену действующим TOTP-кодом")
    if auth_version(web) != auth_version():
        raise HTTPException(409, "Учётные данные изменились — начните заново")
    result = await asyncio.to_thread(AuthFlows().setup_totp, browser_id(request), replace=True, expected_version=auth_version(web))
    request.session["totp_setup"] = result["id"]
    from ..app import _totp_qr_data_url
    result["qr"] = await asyncio.to_thread(_totp_qr_data_url, result["uri"])
    return result


async def cli_recovery(request: Request, body: RecoveryBody):
    # Retained for a possible future design, with no registered HTTP route.
    from .._internal.cli_recovery import require_cli_recovery_enabled
    require_cli_recovery_enabled()
    from core.config import get_web_config
    from core import audit
    flows = AuthFlows()
    version = await asyncio.to_thread(flows.use_cli_access, body.code)
    await asyncio.to_thread(flows.cancel_login, browser_id(request))
    establish_web_session(request, get_web_config().get("username", "admin"), expected_version=version)
    request.session["recovery_until"] = time.time() + 3600
    await asyncio.to_thread(audit.record, "web.recovery_login", result="ok")
    return {"ok": True, "temporary": True, "expires_in": 3600}


def phone(request: Request):
    device_id = verified_mobile_device_id(request)
    if not device_id:
        raise HTTPException(404, "Не найдено")
    set_request_actor(request)
    return device_id


@router.get("/api/mobile/security")
async def mobile_inbox(request: Request, device_id=Depends(phone)):
    from ..security import second_factor_enabled, second_factor_channel, totp_registered
    from core.config import get_web_config
    import hashlib
    web = await asyncio.to_thread(get_web_config)
    stored = web.get("totp_secret")
    generation = hashlib.sha256(stored.encode()).hexdigest()[:24] if isinstance(stored, str) and stored else None
    access = MobileAccess()
    primary = await asyncio.to_thread(access.primary_device_id)
    removed = list(web.get("totp_removed_generations") or [])
    if generation and primary != device_id and web.get("totp_device_id"):
        removed.append(generation)
    return {"requests": await asyncio.to_thread(AuthFlows().inbox, device_id), "receipt_supported": True,
            "totp_registered": totp_registered(), "two_factor_enabled": second_factor_enabled(),
            "two_factor_channel": second_factor_channel(), "primary_device_id": primary,
            "is_primary": primary == device_id, "totp_setup_allowed": await asyncio.to_thread(access.totp_setup_allowed, device_id),
            "device_count": sum(row.get("kind") == "device" for row in await asyncio.to_thread(access.store.read)),
            "unlink_protected": web.get("device_unlink_protected") is True,
            "server_time": time.time(), "totp_generation": generation,
            "totp_removed_generations": removed}


@router.post("/api/mobile/security/disconnect")
async def mobile_disconnect(device_id=Depends(phone)):
    return await asyncio.to_thread(AuthFlows().disconnect_phone, device_id)


@router.get("/api/mobile/security/login/{flow_id}")
async def mobile_login_preview(flow_id: str, device_id=Depends(phone)):
    return await asyncio.to_thread(AuthFlows().login_preview, device_id, flow_id)


class DecisionBody(BaseModel):
    id: str
    action: str
    signature: str


@router.post("/api/mobile/security/decision")
async def mobile_decision(body: DecisionBody, device_id=Depends(phone)):
    return await asyncio.to_thread(AuthFlows().signed_decision, device_id, body.id, body.action, body.signature)


@router.post("/api/mobile/security/ack")
async def mobile_ack(body: FlowBody, device_id=Depends(phone)):
    await asyncio.to_thread(AuthFlows().acknowledge, device_id, body.id)
    return {"ok": True}


class ReceiptBody(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    nonce: str = Field(min_length=1, max_length=128)


@router.post("/api/mobile/security/received")
async def mobile_received(body: ReceiptBody, device_id=Depends(phone)):
    return await asyncio.to_thread(AuthFlows().received_primary, device_id, body.id, body.nonce)


@router.get("/api/mobile/security/devices")
async def mobile_devices(device_id=Depends(phone)):
    from .._internal.device_access.primary import require
    access = MobileAccess()
    await asyncio.to_thread(lambda: require(access.store.read(), device_id))
    return {"devices": await asyncio.to_thread(access.devices), "device_id": device_id}


class PhoneManagementBody(BaseModel):
    operation: str
    target_device_id: str = ""
    name: str = "Телефон"


@router.post("/api/mobile/security/devices/challenge")
async def mobile_devices_challenge(body: PhoneManagementBody, device_id=Depends(phone)):
    from .._internal.device_access.phone_management import challenge
    return await asyncio.to_thread(challenge, AuthFlows(), device_id, body.operation,
                                   target_id=body.target_device_id, name=body.name)


class PhoneManagementConfirm(FlowBody):
    signature: str


@router.post("/api/mobile/security/devices/confirm")
async def mobile_devices_confirm(body: PhoneManagementConfirm, device_id=Depends(phone)):
    from .._internal.device_access.phone_management import execute
    result = await asyncio.to_thread(execute, AuthFlows(), device_id, body.id, body.signature)
    if result.get("code"):
        from ..app import _totp_qr_data_url
        result["qr"] = await asyncio.to_thread(_totp_qr_data_url, result["code"])
    return result


class PhoneInvitationStatus(BaseModel):
    status_token: str


@router.post("/api/mobile/security/devices/pair/status")
async def mobile_phone_pair_status(body: PhoneInvitationStatus, device_id=Depends(phone)):
    from .._internal.device_access.primary import require
    access = MobileAccess()
    await asyncio.to_thread(lambda: require(access.store.read(), device_id))
    return await asyncio.to_thread(access.pairing_status, body.status_token)


class MobileTotpSetupBody(BaseModel):
    enable_request_id: str | None = None


class TwoFactorBody(BaseModel):
    device_id: str | None = None
    enabled: bool


class TelegramFactorBody(BaseModel):
    enabled: bool


class TelegramConfirmBody(FlowBody):
    code: str


_telegram_factor_sent = {}


@router.post("/api/auth/two-factor/telegram")
async def start_telegram_factor(request: Request, body: TelegramFactorBody):
    from ..app import _require_totp_session, _recovery_available
    from ..security import second_factor_channel, telegram_delivery_fingerprint
    from ..telegram_otp import send_telegram_code
    _require_totp_session(request)
    if not _recovery_available():
        raise HTTPException(409, "Включите и настройте Telegram-бота для второго фактора")
    if body.enabled and second_factor_channel() == "telegram":
        raise HTTPException(409, "Второй фактор Telegram уже включён")
    if not body.enabled and second_factor_channel() != "telegram":
        raise HTTPException(409, "Второй фактор Telegram не включён")
    browser = browser_id(request)
    now = time.monotonic()
    if browser in _telegram_factor_sent and now - _telegram_factor_sent[browser] < 30:
        raise HTTPException(429, "Код уже отправлялся. Повторите через 30 секунд")
    _telegram_factor_sent[browser] = now
    for key in [key for key, value in _telegram_factor_sent.items() if now - value >= 30]:
        _telegram_factor_sent.pop(key, None)
    delivery = await asyncio.to_thread(telegram_delivery_fingerprint)
    try:
        pending = await send_telegram_code("Включение 2FA Bot4VPS" if body.enabled else "Отключение 2FA Bot4VPS",
            "Введите код в окне настройки второго фактора. Если действие выполняли не вы, не вводите код.", clock=time.time)
    except Exception:
        raise HTTPException(503, "Не удалось отправить код в Telegram. Прежние настройки сохранены") from None
    result = await asyncio.to_thread(AuthFlows().setup_telegram_factor, browser, body.enabled, pending,
                                    expected_version=request.session.get("auth_version"), delivery=delivery)
    request.session["two_factor_flow"] = result["id"]
    request.session["two_factor_expires"] = time.time() + 600
    return result


@router.post("/api/auth/two-factor/mobile")
async def start_two_factor(request: Request, body: TwoFactorBody):
    from ..app import _require_totp_session
    _require_totp_session(request)
    result = await asyncio.to_thread(AuthFlows().request_two_factor, browser_id(request), body.device_id, body.enabled,
        ip=request.client.host if request.client else None, agent=request.headers.get("user-agent", ""),
        expected_version=request.session.get("auth_version"))
    request.session["two_factor_flow"] = result["id"]
    request.session["two_factor_expires"] = time.time() + 300
    return result


def _two_factor_browser(request, flow_id):
    if request.session.get("two_factor_flow") != flow_id or not request.session.get("user") or "recovery_until" in request.session:
        raise HTTPException(403, "Запрос принадлежит другой браузерной сессии")
    return browser_id(request)


@router.post("/api/auth/two-factor/status")
async def two_factor_status(request: Request, body: FlowBody):
    from ..security import session_valid
    from .._internal.device_access.access import MobileAccess
    row = await asyncio.to_thread(AuthFlows().two_factor_status, body.id, _two_factor_browser(request, body.id))
    if row.get("completed") and row["state"] == "approved":
        # Only the initiating, browser-bound session may survive this exact change.
        if (request.session.get("user") != row["username"] or request.session.get("auth_version") not in (row.get("initiating_version"), row["version"]) or
            (row.get("device_id") and not await asyncio.to_thread(MobileAccess().device_exists, row["device_id"]))):
            raise HTTPException(401, "Войдите в панель заново")
        request.session["auth_version"] = row["version"]
        set_request_actor(request)
        return {"ok": True, "state": "approved", "enabled": row["purpose"] in ("two_factor_enable", "two_factor_telegram_enable", "primary_transfer")}
    if not session_valid(request.session):
        raise HTTPException(401, "Требуется авторизация")
    if row["state"] == "rejected":
        request.session.pop("two_factor_flow", None)
        request.session.pop("two_factor_expires", None)
    return {"ok": False, "state": row["state"], "expires_in": max(0, int(row["expires"] - time.time())),
            "received_at": row.get("received_at")}


@router.post("/api/auth/two-factor/cancel")
async def cancel_two_factor(request: Request, body: FlowBody):
    from ..app import _require_totp_session
    browser = _two_factor_browser(request, body.id)
    _require_totp_session(request)
    await asyncio.to_thread(AuthFlows().cancel_two_factor, body.id, browser)
    request.session.pop("two_factor_flow", None)
    request.session.pop("two_factor_expires", None)
    return {"ok": True}


@router.post("/api/auth/two-factor/telegram/confirm")
async def confirm_telegram_factor(request: Request, body: TelegramConfirmBody):
    from ..security import second_factor_enabled, second_factor_channel
    flows = AuthFlows()
    browser = _two_factor_browser(request, body.id)
    row = await asyncio.to_thread(flows.two_factor_status, body.id, browser)
    if (request.session.get("user") != row["username"] or
            request.session.get("auth_version") not in (row.get("initiating_version"), row["version"])):
        raise HTTPException(401, "Войдите в панель заново")
    version = await asyncio.to_thread(flows.confirm_telegram_factor, body.id, browser, body.code)
    request.session["auth_version"] = version
    set_request_actor(request)
    return {"ok": True, "enabled": second_factor_enabled(), "channel": second_factor_channel()}


@router.post("/api/mobile/security/totp/setup")
async def mobile_totp_setup(body: MobileTotpSetupBody = MobileTotpSetupBody(), device_id=Depends(phone)):
    return await asyncio.to_thread(AuthFlows().setup_totp, "phone:" + device_id, device_id=device_id, enable_flow_id=body.enable_request_id)


class TotpConfirmBody(FlowBody):
    code: str


@router.post("/api/mobile/security/totp/confirm")
async def mobile_totp_confirm(body: TotpConfirmBody, device_id=Depends(phone)):
    flows = AuthFlows()
    await asyncio.to_thread(flows.confirm_totp, body.id, "phone:" + device_id, body.code, enabled=True)
    status = await asyncio.to_thread(flows.mobile_totp_setup_status, device_id, body.id)
    return {"ok": True, "enabled": status["two_factor_enabled"], **status}


@router.get("/api/mobile/security/totp/setup/{flow_id}")
async def mobile_totp_setup_status(flow_id: str, device_id=Depends(phone)):
    return await asyncio.to_thread(AuthFlows().mobile_totp_setup_status, device_id, flow_id)
