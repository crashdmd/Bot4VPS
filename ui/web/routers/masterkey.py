"""Мастер-ключ шифрования (enc1:): статус, восстановление, просмотр.

ТЗ «Защита и восстановление мастер-ключа». Правила безопасности:

- ключ возвращается только HTTP confirm-маршрутами после подтверждения
  владельца или подписи отдельного ключа операции (2FA приоритетно, код в
  Telegram — запасной канал, консоль — всегда доступный аварийный путь);
- статус/restore/create-new никогда не возвращают значение ключа;
- модели не содержат валидаторов (min_length и т.п.): дефолтный 422
  FastAPI эхает введённое значение в поле ``input``;
- исключения обрабатываются здесь же чистыми 4xx — без deps.err()
  (он печатает traceback в journal, ключ мог бы попасть в кадр);
- введённый ключ/пароль не попадает ни в логи, ни в Telegram.

Сценарии (core/secretbox.py — инвариант мастер-ключа):
  ok               — ключ есть и расшифровывает данные;
  missing_no_data  — ключа нет, enc1: данных нет (штатно, авто-создание);
  missing_with_data / mismatch — нужен recovery-флоу: ввести
                    существующий ключ или создать новый с потерей данных.
"""
from __future__ import annotations

import asyncio
import secrets as pysecrets
import time
from collections import deque

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel

class SensitiveRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def safe_handler(request: Request):
            try:
                if request.url.path.startswith("/api/masterkey/phone/"):
                    _owner(request)
                    _mobile(request)
                return await handler(request)
            except RequestValidationError:
                # FastAPI's normal 422 includes input values, possibly secrets.
                from ui.web.security import set_request_actor
                set_request_actor(request)
                if "/view" in request.url.path or "/phone/" in request.url.path:
                    from core.secretbox import audit_master_key_view
                    audit_master_key_view(success=False, reason="request")
                return JSONResponse({"detail": "Некорректный запрос"}, status_code=400)
        return safe_handler


router = APIRouter(tags=["masterkey"], route_class=SensitiveRoute)

# Просмотр ключа: подтверждение одноразовым кодом (TTL/попытки по образцу
# recovery-флоу пароля — app.py _RECOVERY_*). Pending живёт в памяти
# процесса (один uvicorn-worker, как _pending_otp/_pending_recovery).
_VIEW_TTL_SECONDS = 600.0
_VIEW_MAX_ATTEMPTS = 5
_VIEW_COOLDOWN_SECONDS = 30.0
# Повторная отправка по кнопке «Не пришёл код»: раньше этого срока новый
# код бессмыслен (старый жив и мог просто задержаться в доставке).
_VIEW_RESEND_AFTER_SECONDS = 120.0
_pending_view: dict | None = None  # {channel, code, expires_at, attempts}
_last_view_request_at = 0.0


_bound_views: dict[str, dict] = {}
_view_rates: dict[str, deque] = {}


def _owner(request: Request | None) -> str:
    if request is None:
        return "direct"  # Compatibility for internal route unit tests only.
    from ui.web.security import verified_mobile_device_id, set_request_actor
    set_request_actor(request)
    device = verified_mobile_device_id(request)
    if device:
        return "phone:" + device
    # Binding lives in the signed Web session; external headers cannot choose it.
    session = request.scope.get("session")
    if session is None:
        _deny(403, "Требуется подтверждённая сессия", "session")
    session.setdefault("masterkey_view_binding", pysecrets.token_urlsafe(32))
    return "web:" + session["masterkey_view_binding"]


def _pending(owner: str) -> dict | None:
    global _pending_view
    value = _pending_view if owner == "direct" else _bound_views.get(owner)
    if value and time.monotonic() > value["expires_at"]:
        _store_pending(owner, None)
        return None
    return value


def _store_pending(owner: str, value: dict | None) -> None:
    global _pending_view
    if owner == "direct":
        _pending_view = value
    elif value is None:
        _bound_views.pop(owner, None)
    else:
        now = time.monotonic()
        for key in list(_bound_views):
            if _bound_views[key]["expires_at"] <= now:
                del _bound_views[key]
        if owner not in _bound_views and len(_bound_views) >= 64:
            _deny(429, "Слишком много запросов просмотра", "rate")
        _bound_views[owner] = value


def _deny(status: int, message: str, stage: str):
    from core.secretbox import audit_master_key_view
    audit_master_key_view(success=False, reason=stage)
    raise HTTPException(status, message)


def _limit(owner: str) -> None:
    now = time.monotonic()
    for key in list(_view_rates):
        if not _view_rates[key] or _view_rates[key][-1] <= now - 60:
            del _view_rates[key]
    if owner not in _view_rates and len(_view_rates) >= 1024:
        _deny(429, "Слишком много попыток просмотра", "rate")
    attempts = _view_rates.setdefault(owner, deque())
    while attempts and attempts[0] <= now - 60:
        attempts.popleft()
    if len(attempts) >= 10:
        _deny(429, "Слишком много попыток — подождите минуту", "rate")
    attempts.append(now)


def _mobile(request: Request):
    from ui.web.security import verified_mobile_device_id
    from ui.web._internal.device_access.access import MobileAccess
    device = verified_mobile_device_id(request)
    access = request.scope.get("state", {}).get("mobile_access")
    if not device or not isinstance(access, MobileAccess):
        _deny(403, "Требуется привязанный телефон", "device")
    return access, device


@router.get("/api/masterkey/status")
async def api_masterkey_status():
    """Состояние мастер-ключа + доступные каналы подтверждения просмотра.

    Никогда не создаёт ключ и никогда не возвращает его значение.
    """
    from core import secretbox
    from core.config import get_telegram_config

    try:
        state = await asyncio.to_thread(secretbox.master_key_state)
    except Exception as exc:
        raise HTTPException(500, "Не удалось определить состояние мастер-ключа") from exc

    # Каналы подтверждения просмотра. TG-канал требует расшифровки токена:
    # в сценарии потери ключа он недоступен (это нормально — recovery-флоу
    # не требует просмотра, а просмотр в этом сценарии не нужен).
    # Выключенный Telegram — осознанное решение владельца: код не
    # отправляем, даже если токен и user_id сохранены (консоль вместо TG).
    tg_available = False
    try:
        from core.config import _read_config_raw

        raw = _read_config_raw()
        tg_enabled = not ("telegram_enabled" in raw and not raw["telegram_enabled"])
        if tg_enabled:
            tg = get_telegram_config()
            tg_available = bool(tg.get("token_set")) and tg.get("user_id") is not None
    except Exception:
        tg_available = False

    from ui.web.security import totp_enabled

    two_fa = totp_enabled()

    channels = {
        "totp": bool(two_fa),
        "telegram": bool(tg_available),
        # хотя бы один канал — иначе просмотр только из консоли
        "any": bool(two_fa or tg_available),
    }
    # Незашифрованные секреты (перенесённые файлами со старой установки):
    # карточка Мастер-ключ показывает кнопку «Зашифровать все секреты».
    # Только метки и количества — сами значения наружу не уходят.
    try:
        plaintext = await asyncio.to_thread(secretbox.scan_plaintext_secrets)
    except Exception as exc:
        raise HTTPException(500, "Не удалось просканировать секреты") from exc
    return {
        "state": state["state"],
        "encrypted_fields": state["encrypted_fields"],
        "channels": channels,
        "plaintext": plaintext,
    }


@router.post("/api/masterkey/encrypt-secrets")
async def api_masterkey_encrypt_secrets():
    """Зашифровать все секреты, найденные scan_plaintext_secrets().

    Усиливающее действие: не ослабляет защиту, ничего не показывает —
    подтверждения не требует. Значения не возвращаются, только счётчики.
    """
    from core import secretbox

    try:
        result = await asyncio.to_thread(secretbox.encrypt_all_plaintext_secrets)
    except secretbox.MasterKeyMissingError as exc:
        raise HTTPException(409, str(exc)) from exc
    except secretbox.SecretBoxError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, "Не удалось зашифровать секреты") from exc
    return {"ok": True, "encrypted": result["encrypted"], "plaintext": result["plaintext"]}


class MasterKeyRestoreBody(BaseModel):
    # Без валидаторов: 422-ответ FastAPI содержит введённое значение.
    key: str


@router.post("/api/masterkey/restore")
async def api_masterkey_restore(body: MasterKeyRestoreBody):
    """Сценарий Б: ввести существующий мастер-ключ.

    Ключ проверяется расшифровкой ВСЕХ enc1: значений из текущих
    config.json/servers.json. Провал → ничего не перезаписывается.
    """
    from core import secretbox

    try:
        state = await asyncio.to_thread(secretbox.restore_master_key, body.key)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except secretbox.MasterKeyMissingError as exc:
        # Неверный ключ — данные не тронуты, ничего не создано
        raise HTTPException(400, str(exc))
    except Exception:
        # Ввод не в журнал: только код ошибки
        raise HTTPException(500, "Не удалось восстановить мастер-ключ")
    return {"ok": True, **state}


class MasterKeyNewBody(BaseModel):
    confirm: bool


@router.post("/api/masterkey/new")
async def api_masterkey_new(body: MasterKeyNewBody, request: Request):
    """Осознанное создание НОВОГО ключа при наличии enc1: данных.

    Разрушающая операция: подтверждённый клиентом факт, что старые
    enc1: значения (пароли серверов, bot_token, totp_secret) теряются.
    После создания ключа поля очищаются — иначе /api/servers отдавал бы
    500 на каждом запросе из-за нерасшифровываемых значений.
    """
    from core import secretbox
    from core.config import _read_config_raw, _patch_config_keys
    from core import storage
    from ui.web.security import clear_totp_secret

    if not body.confirm:
        raise HTTPException(400, "Требуется явное подтверждение")

    scan = await asyncio.to_thread(secretbox.scan_encrypted)
    if not scan["found"]:
        # Чистая система: ключ создаст штатный авто-механизм при первой
        # записи секрета — отдельное «создание» не нужно и смысла не имеет.
        raise HTTPException(
            400,
            "Зашифрованных данных нет — новый ключ не требуется "
            "(он будет создан автоматически)",
        )

    # Порядок: сначала ключ (расшифровка уже невозможна — старый ключ
    # не подходит по определению сценария), затем очистка полей.
    recovery_archive = await asyncio.to_thread(secretbox.archive_before_key_replacement)
    key = await asyncio.to_thread(secretbox._create_key_exclusive, via="replacement")
    try:
        from cryptography.fernet import Fernet

        Fernet(key)
    except Exception as exc:
        raise HTTPException(500, "Не удалось создать мастер-ключ") from exc

    cleared = []
    try:
        # config.json: bot_token, web.totp_secret
        raw = _read_config_raw()
        updates = {}
        if raw.get("bot_token"):
            updates["bot_token"] = ""
        if raw.get("backup_encryption_password"):
            updates["backup_encryption_password"] = ""
            cleared.append("пароль резервных копий")
        if isinstance(raw.get("web"), dict) and raw["web"].get("totp_secret"):
            web = dict(raw["web"])
            web.pop("totp_secret", None)
            updates["web"] = web
            cleared.append("2FA")
        if updates:
            _patch_config_keys(updates)
            if "bot_token" in updates:
                cleared.append("Telegram Bot Token")
        # servers.json: пароли серверов
        def _clear_passwords() -> int:
            with storage.data_lock():
                data = storage.load_data(decrypt_passwords=False)
                count = 0
                for server in data.get("servers", []):
                    if isinstance(server, dict) and server.get("password"):
                        server["password"] = ""
                        count += 1
                if count:
                    storage.save_data(data)
                return count

        count = await asyncio.to_thread(_clear_passwords)
        if count:
            cleared.append(f"пароли {count} серверов")
        history_count = await asyncio.to_thread(secretbox.retire_old_encrypted_copies)
        if history_count:
            cleared.append(f"приватные данные {history_count} задач")
    except Exception as exc:
        # Ключ уже создан и записан — откат невозможен; поля, которые не
        # удалось очистить, будут падать ошибкой расшифровки до ручной
        # правки. Говорим об этом честно.
        raise HTTPException(
            500,
            "Новый ключ создан, но не все данные очищены (%s): %s" % (", ".join(cleared) or "-", exc),
        ) from exc

    state = await asyncio.to_thread(secretbox.master_key_state)
    if request.session.get("user"):
        from ui.web.security import refresh_web_session
        refresh_web_session(request)
    return {"ok": True, "created": True, "cleared": cleared, "recovery_archive": str(recovery_archive), **state}


# ==================================================================
# Просмотр мастер-ключа (с подтверждением владельца)
# ==================================================================

class MasterKeyViewBody(BaseModel):
    password: str = ""
    operation_public_key: str = ""  # Optional enrollment, bound to both factors.


@router.post("/api/masterkey/view")
async def api_masterkey_view(body: MasterKeyViewBody, request: Request = None):
    owner = _owner(request)
    _limit(owner)
    from core.config import get_web_config
    from ui.web.security import totp_enabled, verify_password
    from ui.web._internal.device_access.access import _public_key, AccessDenied

    if not body.password:
        _store_pending(owner, None)
        _deny(400, "Введите пароль", "password")
    web = get_web_config()
    if not await asyncio.to_thread(verify_password, body.password, web.get("password_hash", "")):
        _store_pending(owner, None)
        _deny(400, "Неверный пароль", "password")
    enrollment = body.operation_public_key
    if enrollment:
        _mobile(request)
        try:
            _public_key(enrollment)
        except AccessDenied:
            _deny(400, "Некорректный ключ операции", "enrollment")
    if totp_enabled():
        _store_pending(owner, {"channel": "totp", "expires_at": time.monotonic() + _VIEW_TTL_SECONDS,
                               "attempts": 0, "enrollment": enrollment, "password_hash": web.get("password_hash", "")})
        return {"ok": True, "channel": "totp"}
    from ui.web.app import _recovery_available
    if _recovery_available():
        pending = _pending(owner)
        if pending and pending.get("channel") == "telegram" and pending.get("enrollment", "") == enrollment:
            return {"ok": True, "channel": "telegram", "resent": False}
        return await _send_view_code(owner, enrollment, web.get("password_hash", ""))
    _store_pending(owner, None)
    _deny(403, "С текущими настройками безопасности просмотр мастер-ключа невозможен. "
          "Используйте консоль управления сервисом Bot4VPS (bot4vps → 2. Безопасность → 5. Мастер-ключ).", "channel")


async def _send_view_code(owner: str = "direct", enrollment: str = "", password_hash: str = "") -> dict:
    global _last_view_request_at
    from ui.web.app import _send_recovery_message
    now = time.monotonic()
    # Global delivery cooldown also prevents spamming Telegram via many sessions.
    if now - _last_view_request_at < _VIEW_COOLDOWN_SECONDS:
        _deny(429, "Код уже отправлен — повторите чуть позже", "rate")
    _last_view_request_at = now
    code = f"{pysecrets.randbelow(1_000_000):06d}"
    text = ("🔑 <b>Просмотр мастер-ключа Bot4VPS</b>\n\n"
            f"Код подтверждения: <code>{code}</code>\nДействует 10 минут.\n\n"
            "Если вы не запрашивали просмотр — проигнорируйте сообщение: без кода ключ не показывается.")
    try:
        await _send_recovery_message(text)
    except Exception:
        _deny(502, "Не удалось отправить код в Telegram", "delivery")
    _store_pending(owner, {"channel": "telegram", "code": code,
                          "expires_at": time.monotonic() + _VIEW_TTL_SECONDS, "attempts": 0, "enrollment": enrollment,
                          "password_hash": password_hash})
    return {"ok": True, "channel": "telegram", "resent": True}


@router.post("/api/masterkey/view/resend")
async def api_masterkey_view_resend(request: Request = None):
    owner = _owner(request)
    pending = _pending(owner)
    if not pending or pending.get("channel") != "telegram":
        _deny(400, "Код ещё не отправлялся — начните просмотр заново", "pending")
    elapsed = time.monotonic() - (pending["expires_at"] - _VIEW_TTL_SECONDS)
    if elapsed < _VIEW_RESEND_AFTER_SECONDS:
        _deny(429, "Предыдущий код ещё актуален — новый можно запросить через %d с" %
              max(1, int(_VIEW_RESEND_AFTER_SECONDS - elapsed)), "rate")
    return await _send_view_code(owner, pending.get("enrollment", ""), pending.get("password_hash", ""))


class MasterKeyViewConfirmBody(BaseModel):
    code: str = ""


async def _read_view_key() -> dict:
    from core import secretbox
    try:
        key = await asyncio.to_thread(secretbox.read_master_key)
    except secretbox.SecretBoxError:
        raise HTTPException(409, "Мастер-ключ недоступен — проверьте его состояние")
    except Exception:
        raise HTTPException(500, "Не удалось прочитать мастер-ключ")
    return {"ok": True, "key": key}


@router.post("/api/masterkey/view/confirm")
async def api_masterkey_view_confirm(body: MasterKeyViewConfirmBody, request: Request = None):
    owner = _owner(request)
    from ui.web.security import get_totp_secret, verify_totp_code, totp_enabled
    pending = _pending(owner)
    if not pending:
        _deny(400, "Просмотр не начинался или истёк — начните заново", "pending")
    # A security configuration change invalidates pending confirmation.
    channel = pending["channel"]
    if request is not None:
        from core.config import get_web_config
        if pending.get("password_hash") != get_web_config().get("password_hash", ""):
            _store_pending(owner, None)
            _deny(400, "Пароль изменился — начните заново", "password")
    if request is not None and (channel == "totp") != bool(totp_enabled()):
        _store_pending(owner, None)
        _deny(400, "Настройки подтверждения изменились — начните заново", "channel")
    if channel == "totp":
        secret = get_totp_secret()
        valid = bool(secret and verify_totp_code(body.code, secret))
    else:
        valid = bool(body.code.strip() and pysecrets.compare_digest(body.code.strip(), pending.get("code", "")))
    if not valid:
        pending["attempts"] += 1
        remaining = _VIEW_MAX_ATTEMPTS - pending["attempts"]
        if remaining <= 0:
            _store_pending(owner, None)
            _deny(400, "Неверный код. Попытки исчерпаны — начните заново", "second_factor")
        _deny(400, f"Неверный код (осталось попыток: {remaining})", "second_factor")
    _store_pending(owner, None)  # Consume before any await; no concurrent replay.
    enrollment = pending.get("enrollment")
    if enrollment:
        from ui.web._internal.device_access.access import AccessDenied
        access, device = _mobile(request)
        try:
            await asyncio.to_thread(access.enroll_masterkey, device, enrollment)
        except AccessDenied:
            _deny(403, "Не удалось настроить ключ операции", "enrollment")
        return {"ok": True, "enrolled": True}
    return await _read_view_key()


@router.get("/api/masterkey/phone/status")
async def api_masterkey_phone_status(request: Request):
    _owner(request)
    access, device = _mobile(request)
    status = await api_masterkey_status()
    return {"ok": True, "public_key": await asyncio.to_thread(access.masterkey_public_key, device),
            "device_operation_public_key": await asyncio.to_thread(access.masterkey_device_public_key, device), **status}


class MasterKeyAvailabilityBody(BaseModel):
    protected: bool = False


@router.post("/api/masterkey/phone/view/availability")
async def api_masterkey_phone_availability(body: MasterKeyAvailabilityBody, request: Request):
    _owner(request)
    _mobile(request)
    status = await api_masterkey_phone_status(request)
    if status["state"] != "ok":
        _deny(409, "Мастер-ключ недоступен — проверьте его состояние", "state")
    # This flag selects an explanation only. No credential, enrollment or
    # signature checks are skipped by it, and no key is ever returned here.
    if not body.protected and not status["channels"]["any"]:
        _deny(403, "Для просмотра включите PIN/биометрию приложения либо настройте 2FA/Telegram. "
              "Также ключ доступен через CLI: bot4vps → Безопасность → Мастер-ключ.", "channel")
    return status


@router.post("/api/masterkey/phone/view")
async def api_masterkey_phone_view(body: MasterKeyViewBody, request: Request):
    _owner(request)
    _mobile(request)
    if body.operation_public_key:
        _deny(400, "Настройте защищённый просмотр через протокол телефона", "enrollment")
    return await api_masterkey_view(body, request)


@router.post("/api/masterkey/phone/view/confirm")
async def api_masterkey_phone_view_confirm(body: MasterKeyViewConfirmBody, request: Request):
    _owner(request)
    _mobile(request)
    return await api_masterkey_view_confirm(body, request)


@router.post("/api/masterkey/phone/view/resend")
async def api_masterkey_phone_view_resend(request: Request):
    _owner(request)
    _mobile(request)
    return await api_masterkey_view_resend(request)


class MasterKeyEnrollmentBody(BaseModel):
    public_key: str = ""
    device_operation_public_key: str = ""


@router.post("/api/masterkey/phone/enroll/challenge")
async def api_masterkey_phone_enrollment_challenge(body: MasterKeyEnrollmentBody, request: Request):
    _owner(request)
    access, device = _mobile(request)
    _limit("phone:" + device)
    from ui.web._internal.device_access.access import AccessDenied
    try:
        return await asyncio.to_thread(access.masterkey_enrollment_challenge, device, body.public_key, body.device_operation_public_key)
    except AccessDenied as exc:
        _deny(exc.status, str(exc), "enrollment")


class MasterKeyEnrollmentProofBody(BaseModel):
    challenge_id: str = ""
    device_signature: str = ""
    operation_signature: str = ""
    keystore_signature: str = ""


@router.post("/api/masterkey/phone/enroll/confirm")
async def api_masterkey_phone_enrollment_confirm(body: MasterKeyEnrollmentProofBody, request: Request):
    _owner(request)
    access, device = _mobile(request)
    from ui.web._internal.device_access.access import AccessDenied
    try:
        await asyncio.to_thread(access.confirm_masterkey_enrollment, device, body.challenge_id,
                                body.device_signature, body.operation_signature, body.keystore_signature)
    except AccessDenied:
        _deny(403, "Подтверждение настройки недействительно или истекло", "enrollment_proof")
    return {"ok": True, "enrolled": True}


@router.post("/api/masterkey/phone/challenge")
async def api_masterkey_phone_challenge(request: Request):
    _owner(request)
    access, device = _mobile(request)
    from ui.web._internal.device_access.access import AccessDenied
    try:
        return await asyncio.to_thread(access.masterkey_challenge, device)
    except AccessDenied as exc:
        _deny(exc.status, str(exc), "challenge")


class MasterKeyProofBody(BaseModel):
    challenge_id: str = ""
    signature: str = ""
    keystore_signature: str = ""


@router.post("/api/masterkey/phone/confirm")
async def api_masterkey_phone_confirm(body: MasterKeyProofBody, request: Request):
    _owner(request)
    access, device = _mobile(request)
    from ui.web._internal.device_access.access import AccessDenied
    try:
        await asyncio.to_thread(access.confirm_masterkey, device, body.challenge_id, body.signature, body.keystore_signature)
    except AccessDenied:
        _deny(403, "Подтверждение операции недействительно или истекло", "proof")
    return await _read_view_key()
