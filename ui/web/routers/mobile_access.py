"""Private Web controls for the paired mobile API."""
from __future__ import annotations

import asyncio
import ipaddress
import base64
import io
import secrets
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, StrictBool, StrictInt

from .._internal.device_access.access import AccessDenied, MobileAccess, PAIR_TTL, pairing_invitation
from .._internal.device_access.preview import MANAGEMENT_PREFIX, private_web_request
from ..security import require_auth, auth_version
from .._internal.auth_flows import AuthFlows, browser_id, protection_enabled


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


def _flows():
    return AuthFlows(MobileAccess().store.path)


def _settings():
    from core.config import get_web_config
    cfg = get_web_config().get("mobile_api") or {}
    return {"enabled": cfg.get("enabled") is True, "host": cfg.get("host", "0.0.0.0"),
            "port": cfg.get("port", 8444), "public_url": cfg.get("public_url", ""),
            "public_address": cfg.get("public_address", cfg.get("public_url", ""))}


@router.get(MANAGEMENT_PREFIX)
async def state(request: Request):
    flows = _flows()
    procedures = await asyncio.to_thread(flows.unlink_states)
    settings, devices = await asyncio.gather(asyncio.to_thread(_settings), asyncio.to_thread(MobileAccess().devices))
    listener = getattr(request.app.state, "mobile_api_listener", None)
    from .._internal.device_access.runtime import listener_running
    running = bool(getattr(request.app.state, "mobile_api_enabled", False) and listener_running(listener))
    error = getattr(request.app.state, "mobile_api_error", "")
    if listener is not None and not running and not error:
        error = "Мобильный API остановился"
    pending = listener is not None and any(listener.config.get(k, default) != settings[k] for k, default in (("enabled", False), ("host", "0.0.0.0"), ("port", 8444), ("public_url", "")))
    from ..security import totp_registered, second_factor_enabled, second_factor_channel
    from ..app import _recovery_available
    from core.config import get_web_config
    primary_selection_pending = (await asyncio.to_thread(get_web_config)).get('mobile_primary_selection_pending') is True
    from .._internal.device_access.connection_change import active
    change = active(request.app)
    from .._internal.auth_flows import fingerprint
    primary_transfer = next((row for row in await asyncio.to_thread(flows.store.read) if row.get("kind") == "auth" and row.get("purpose") == "primary_transfer" and
        not row.get("completed") and row.get("state") in ("pending", "approved", "confirming") and row.get("expires", 0) > time.time() and row.get("browser") == fingerprint(browser_id(request))), None)
    return {"settings": settings, "running": running, "restart_required": pending,
            "primary_transfer": {key: primary_transfer[key] for key in ("id", "device_id", "state", "expires", "received_at") if key in primary_transfer} if primary_transfer else None,
            "enabled_locked": bool(devices),
            "settings_change": change.status(include_qr=change.owner == browser_id(request)) if change else None,
            "error": error, "devices": devices, "unlink_protected": protection_enabled(),
            "procedures": procedures, "totp_registered": totp_registered(), "two_factor_enabled": second_factor_enabled(),
            "two_factor_channel": second_factor_channel(),
            "primary_device_id": next((device["id"] for device in devices if device.get("is_primary")), None),
            "primary_selection_pending": primary_selection_pending,
            "telegram_available": _recovery_available()}


class PrimaryBody(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=4096)
    code: str = Field(default="", max_length=16)
    telegram_id: str | None = Field(default=None, max_length=128)


@router.post(MANAGEMENT_PREFIX + "/primary")
async def choose_primary(body: PrimaryBody, request: Request):
    from core.config import get_web_config
    from ..security import verify_password
    from ..app import _require_totp_session
    from .._internal.device_access.connection_change import active
    if active(request.app):
        raise HTTPException(409, "Сначала завершите смену подключения")
    _require_totp_session(request)
    access = MobileAccess()
    await asyncio.to_thread(access.rate_limit, "primary:" + browser_id(request))
    web = await asyncio.to_thread(get_web_config)
    if not await asyncio.to_thread(verify_password, body.password, web.get("password_hash", "")):
        raise HTTPException(403, "Неверный пароль администратора")
    flows = _flows()
    if body.telegram_id:
        row = await asyncio.to_thread(flows._find, flows.store.read(), body.telegram_id, "auth")
        flows._browser(row, browser_id(request))
        if not row.get("completed"):
            await asyncio.to_thread(flows.confirm_telegram_factor, body.telegram_id, browser_id(request), body.code, purpose="primary_authorization")
    result = await asyncio.to_thread(flows.request_primary, browser_id(request), body.device_id,
        expected_version=auth_version(web), code=body.code, telegram_id=body.telegram_id)
    if result.get("pending"):
        request.session["two_factor_flow"] = result["id"]
        request.session["two_factor_expires"] = time.time() + 600
    return result


@router.post(MANAGEMENT_PREFIX + "/primary/telegram")
async def primary_telegram(body: PrimaryBody, request: Request):
    from core.config import get_web_config
    from ..security import verify_password, telegram_delivery_fingerprint
    from ..app import _require_totp_session, _recovery_available
    from ..telegram_otp import send_telegram_code
    _require_totp_session(request)
    web = await asyncio.to_thread(get_web_config)
    access = MobileAccess()
    await asyncio.to_thread(access.rate_limit, "primary-telegram:" + browser_id(request))
    if not await asyncio.to_thread(verify_password, body.password, web.get("password_hash", "")):
        raise HTTPException(403, "Неверный пароль администратора")
    device = next((device for device in await asyncio.to_thread(access.devices) if device["id"] == body.device_id), None)
    if not device:
        raise HTTPException(404, "Телефон уже отвязан")
    if not _recovery_available():
        raise HTTPException(409, "Telegram выключен или не настроен")
    delivery = telegram_delivery_fingerprint()
    try:
        pending = await send_telegram_code("Назначение основного телефона Bot4VPS",
            "Назначение устройства «" + device["name"] + "» основным на панели " + str(request.base_url) + ". Введите код в этой панели для подтверждения.", clock=time.time)
    except Exception:
        raise HTTPException(503, "Не удалось отправить код Telegram") from None
    return await asyncio.to_thread(_flows().setup_telegram_factor, browser_id(request), True, pending,
        expected_version=auth_version(web), delivery=delivery, purpose="primary_authorization", device_id=body.device_id)


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
    if url:
        try:
            hostname = parsed.hostname.encode("idna").decode("ascii").lower()
            authority = f"[{hostname}]" if ":" in hostname else hostname
            url = "https://" + authority + (f":{port}" if port is not None else "")
        except UnicodeError:
            raise HTTPException(400, "Укажите корректный домен API")
    if body.enabled:
        from .._internal.device_access.identity import server_identity
        try:
            server_identity(_settings()["public_url"] or url)
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
    access = MobileAccess()
    try:
        cfg = await asyncio.to_thread(_validate_settings, body)
        devices = await asyncio.to_thread(access.devices)
    except OSError as error:
        raise HTTPException(503, "Не удалось проверить настройки мобильного API. Прежнее подключение сохранено") from error
    if devices:
        if not cfg["enabled"]:
            raise HTTPException(409, "Нельзя выключить API, пока есть привязанный телефон")
        previous = await asyncio.to_thread(_settings)
        if any(previous.get(key) != value for key, value in cfg.items() if key != "enabled"):
            from .._internal.device_access.connection_change import begin
            try:
                return await asyncio.shield(begin(request.app, cfg, browser_id(request), access))
            except (RuntimeError, OSError) as error:
                raise HTTPException(503, str(error)) from error
    # Finish the transaction even if the browser disconnects during a save.
    try:
        return await asyncio.shield(apply_mobile_settings(request.app, cfg, access=access))
    except (RuntimeError, OSError) as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post(MANAGEMENT_PREFIX + "/start")
async def start_saved_api(request: Request):
    """Retry the saved address without a phone or any editable form values."""
    from .._internal.device_access.runtime import apply_mobile_settings
    cfg = await asyncio.to_thread(_settings)
    cfg["enabled"] = True
    validated = await asyncio.to_thread(_validate_settings, SettingsBody(**cfg))
    try:
        return await asyncio.shield(apply_mobile_settings(request.app, validated, access=MobileAccess()))
    except (RuntimeError, OSError) as error:
        raise HTTPException(503, str(error)) from error


class ChangeStatusBody(BaseModel):
    id: str = Field(min_length=20, max_length=128)


@router.post(MANAGEMENT_PREFIX + "/settings/status")
async def settings_status(body: ChangeStatusBody, request: Request):
    from .._internal.device_access.connection_change import status
    return await status(request.app, body.id, browser_id(request))


@router.post(MANAGEMENT_PREFIX + "/settings/cancel")
async def settings_cancel(body: ChangeStatusBody, request: Request):
    from .._internal.device_access.connection_change import cancel
    return await asyncio.shield(cancel(request.app, body.id, browser_id(request)))


class PairBody(BaseModel):
    name: str = Field(default="Мой телефон", max_length=80)


@router.post(MANAGEMENT_PREFIX + "/pair")
async def pair(body: PairBody, request: Request):
    from .._internal.device_access.connection_change import active
    if active(request.app):
        raise HTTPException(409, "Сначала завершите или отмените смену подключения")
    listener = getattr(request.app.state, "mobile_api_listener", None)
    if not getattr(request.app.state, "mobile_api_enabled", False) or listener is None:
        raise HTTPException(409, "API ещё не запущен. Сохраните настройки подключения.")
    cfg = await asyncio.to_thread(_settings)
    if not cfg["public_url"] or any(listener.config.get(k, default) != cfg[k] for k, default in (("enabled", False), ("host", "0.0.0.0"), ("port", 8444), ("public_url", ""))):
        raise HTTPException(409, "Настройки API изменились. Сначала сохраните настройки подключения.")
    access = MobileAccess()
    status_token = secrets.token_urlsafe(32)
    from ..security import session_valid
    from .._internal.auth_flows import fingerprint
    web_binding = None
    if session_valid(request.session):
        web_binding = {"browser": fingerprint(browser_id(request)), "version": request.session["auth_version"]}
        request.session["mobile_pairing_status"] = fingerprint(status_token)
    try:
        code = await asyncio.to_thread(access.issue_pairing_code, body.name, status_token=status_token, web_binding=web_binding)
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
async def revoke(device_id: str, request: Request):
    # Legacy endpoint obeys the same policy; it cannot bypass waiting periods.
    result = await asyncio.to_thread(_flows().start_unlink, device_id, "immediate", browser_id(request))
    return {"ok": True, "procedure": result}


class UnlinkBody(BaseModel):
    method: str


@router.post(MANAGEMENT_PREFIX + "/unlink/{device_id}")
async def start_unlink(device_id: str, request: Request, body: UnlinkBody):
    flows = _flows()
    method = body.method if protection_enabled() else "immediate"
    result = await asyncio.to_thread(flows.start_unlink, device_id, method, browser_id(request))
    if method == "telegram":
        from ..app import _recovery_available
        from ..telegram_otp import send_telegram_code
        try:
            if not _recovery_available():
                raise HTTPException(409, "Telegram недоступен. Выберите другой способ отвязки.")
            pending = await send_telegram_code("Отвязка телефона Bot4VPS",
                "Введите код в веб-панели. После подтверждения телефон будет отвязан через час. "
                "Если вы не запрашивали отвязку — отмените её на доверенном телефоне.", clock=time.time)
            await asyncio.to_thread(flows.attach_telegram_code, result["id"], browser_id(request), pending)
        except Exception:
            await asyncio.to_thread(flows.web_unlink_action, result["id"], "cancel")
            raise
    return result


class CodeBody(BaseModel):
    code: str


@router.post(MANAGEMENT_PREFIX + "/unlink/{flow_id}/code")
async def unlink_code(flow_id: str, request: Request, body: CodeBody):
    return await asyncio.to_thread(_flows().confirm_unlink_code, flow_id, browser_id(request), body.code)


@router.post(MANAGEMENT_PREFIX + "/unlink/{flow_id}/cancel")
async def cancel_unlink(flow_id: str):
    return await asyncio.to_thread(_flows().web_unlink_action, flow_id, "cancel")


@router.post(MANAGEMENT_PREFIX + "/unlink/{flow_id}/finish")
async def finish_unlink(flow_id: str):
    return await asyncio.to_thread(_flows().web_unlink_action, flow_id, "finish")


class ProtectionBody(BaseModel):
    enabled: StrictBool
    method: str = "web"
    password: str = ""
    code: str = ""
    device_id: str = ""


@router.post(MANAGEMENT_PREFIX + "/protection")
async def protection(request: Request, body: ProtectionBody):
    from core.config import get_web_config
    from ..security import verify_password, totp_enabled, get_totp_secret, verify_totp_code
    flows = _flows()
    if body.enabled:
        await asyncio.to_thread(flows.set_protection, True, via="web")
        return {"ok": True, "enabled": True}
    if body.method == "mobile":
        return await asyncio.to_thread(flows.request_protection_disable, browser_id(request), body.device_id)
    if body.method != "web":
        raise HTTPException(400, "Выберите подтверждение на телефоне или в веб-панели")
    web = await asyncio.to_thread(get_web_config)
    version = auth_version(web)
    if not await asyncio.to_thread(verify_password, body.password, web.get("password_hash", "")):
        raise HTTPException(403, "Неверный пароль администратора")
    from ..security import second_factor_channel, telegram_delivery_fingerprint
    if second_factor_channel() == "telegram":
        browser = browser_id(request)
        flow_id = request.session.get("telegram_protection_flow")
        if body.code:
            if not flow_id:
                raise HTTPException(400, "Сначала запросите код Telegram")
            await asyncio.to_thread(flows.confirm_telegram_factor, flow_id, browser, body.code,
                                    purpose="protection_telegram_disable")
            request.session.pop("telegram_protection_flow", None)
            return {"ok": True, "enabled": False}
        if flow_id:
            try:
                row = await asyncio.to_thread(flows._find, flows.store.read(), flow_id, "auth")
                flows._browser(row, browser)
                flows._live(row)
                if row.get("purpose") == "protection_telegram_disable" and row.get("state") == "pending":
                    return {"ok": False, "pending": True, "id": flow_id, "message": "Введите код из Telegram"}
            except HTTPException:
                pass
        from ..app import _recovery_available
        from ..telegram_otp import send_telegram_code
        if not _recovery_available():
            raise HTTPException(409, "Telegram для подтверждения недоступен")
        delivery = await asyncio.to_thread(telegram_delivery_fingerprint)
        try:
            pending = await send_telegram_code("Отключение защиты от отвязки Bot4VPS", "Введите код в окне отключения защиты. Никому не передавайте код.", clock=time.time)
        except Exception:
            raise HTTPException(503, "Не удалось отправить код Telegram. Защита остаётся включённой") from None
        result = await asyncio.to_thread(flows.setup_telegram_factor, browser, False, pending,
                                        expected_version=version, delivery=delivery, purpose="protection_telegram_disable")
        request.session["telegram_protection_flow"] = result["id"]
        return {**result, "message": "Введите код из Telegram"}
    if totp_enabled() and not await asyncio.to_thread(verify_totp_code, body.code, get_totp_secret()):
        raise HTTPException(403, "Подтвердите отключение действующим TOTP-кодом")
    await asyncio.to_thread(flows.set_protection, False, via="web_password_2fa" if totp_enabled() else "web_password", expected_version=version)
    return {"ok": True, "enabled": False}
