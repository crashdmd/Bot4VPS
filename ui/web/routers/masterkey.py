"""Мастер-ключ шифрования (enc1:): статус, восстановление, просмотр.

ТЗ «Защита и восстановление мастер-ключа». Правила безопасности:

- ключ возвращается РОВНО ОДНИМ эндпоинтом — ``POST /api/masterkey/view/confirm``
  и только после пройденного подтверждения (2FA приоритетно, код в
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

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(tags=["masterkey"])

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


def _clean_expired() -> None:
    global _pending_view
    if _pending_view and time.monotonic() > _pending_view["expires_at"]:
        _pending_view = None


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

    try:
        two_fa = totp_enabled()
    except Exception:
        two_fa = False

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
async def api_masterkey_new(body: MasterKeyNewBody):
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
    key = await asyncio.to_thread(secretbox._create_key_exclusive)
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
                data = storage.load_data()
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
    except Exception as exc:
        # Ключ уже создан и записан — откат невозможен; поля, которые не
        # удалось очистить, будут падать ошибкой расшифровки до ручной
        # правки. Говорим об этом честно.
        raise HTTPException(
            500,
            "Новый ключ создан, но не все данные очищены (%s): %s" % (", ".join(cleared) or "-", exc),
        ) from exc

    state = await asyncio.to_thread(secretbox.master_key_state)
    return {"ok": True, "created": True, "cleared": cleared, **state}


# ==================================================================
# Просмотр мастер-ключа (с подтверждением владельца)
# ==================================================================

class MasterKeyViewBody(BaseModel):
    password: str  # пароль Web-учётной записи (канал totp)


@router.post("/api/masterkey/view")
async def api_masterkey_view(body: MasterKeyViewBody):
    """Фаза 1 просмотра: проверить пароль и отправить код подтверждения.

    2FA включена → код в приложение-аутентификатор не отправляем:
    подтверждением служит сам код 2FA на следующем шаге. Telegram-канал
    → код доставки в TG. Нет ни того, ни другого → консоль.
    """
    global _pending_view, _last_view_request_at
    from core.config import get_web_config
    from ui.web.security import totp_enabled, verify_password

    if not body.password:
        raise HTTPException(400, "Введите пароль")

    web = get_web_config()
    if not verify_password(body.password, web.get("password_hash", "")):
        raise HTTPException(400, "Неверный пароль")

    two_fa = False
    try:
        two_fa = totp_enabled()
    except Exception:
        two_fa = False

    if two_fa:
        # Пароль уже проверен; вторым фактором станет код из приложения,
        # который пользователь введёт в /view/confirm.
        _pending_view = {
            "channel": "totp",
            "expires_at": time.monotonic() + _VIEW_TTL_SECONDS,
            "attempts": 0,
        }
        return {"ok": True, "channel": "totp"}

    # Telegram-канал: код доставки в TG (доставка — как в recovery-флоу).
    # _recovery_available() не пустит сюда выключенный Telegram — владелец
    # мог отключить его именно потому, что TG не работает.
    from ui.web.app import _recovery_available, _send_recovery_message

    if _recovery_available():
        # Живой код уже отправлен (пользователь закрыл окно и вернулся):
        # НЕ отправляем новый и НЕ блокируем — переиспользуем pending,
        # окно ввода кода открывается сразу.
        _clean_expired()
        pending = _pending_view
        if pending and pending.get("channel") == "telegram":
            return {"ok": True, "channel": "telegram", "resent": False}
        return await _send_view_code()

    # Ни 2FA, ни доступного Telegram: Web не может подтвердить владельца.
    # Единственный путь — консоль. Без советов «включите 2FA»: тот, кто
    # вводит пароль, может и не быть владельцем.
    raise HTTPException(
        403,
        "С текущими настройками безопасности просмотр мастер-ключа "
        "через Web невозможен. Используйте консоль управления сервисом "
        "Bot4VPS (bot4vps → 2. Безопасность → 5. Мастер-ключ).",
    )


async def _send_view_code() -> dict:
    """Реальная отправка нового TG-кода (первая или повторная по кнопке).

    Повторная стирает старый pending: в силе всегда ровно один код.
    Кулдаун 30 с между отправками (защита от спама кнопкой).
    """
    global _pending_view, _last_view_request_at
    from ui.web.app import _send_recovery_message

    now = time.monotonic()
    if now - _last_view_request_at < _VIEW_COOLDOWN_SECONDS:
        raise HTTPException(429, "Код уже отправлен — повторите чуть позже")
    _last_view_request_at = now
    code = f"{pysecrets.randbelow(1_000_000):06d}"
    text = (
        "🔑 <b>Просмотр мастер-ключа Bot4VPS</b>\n\n"
        f"Код подтверждения: <code>{code}</code>\n"
        "Действует 10 минут.\n\n"
        "Если вы не запрашивали просмотр — проигнорируйте сообщение: "
        "без кода ключ не показывается."
    )
    try:
        await _send_recovery_message(text)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "Не удалось отправить код в Telegram")
    _pending_view = {
        "channel": "telegram",
        "code": code,
        "expires_at": time.monotonic() + _VIEW_TTL_SECONDS,
        "attempts": 0,
    }
    return {"ok": True, "channel": "telegram", "resent": True}


@router.post("/api/masterkey/view/resend")
async def api_masterkey_view_resend():
    """«Не пришёл код? Отправить ещё раз» — осознанная повторная отправка.

    Доступна не раньше _VIEW_RESEND_AFTER_SECONDS после первой отправки:
    раньше нового кода ждать бессмысленно (старый жив 10 минут и мог
    просто задержаться в доставке). Новый код стирает старый pending.
    """
    _clean_expired()
    pending = _pending_view
    if not pending or pending.get("channel") != "telegram":
        raise HTTPException(400, "Код ещё не отправлялся — начните просмотр заново")
    sent_at = pending["expires_at"] - _VIEW_TTL_SECONDS
    if time.monotonic() - sent_at < _VIEW_RESEND_AFTER_SECONDS:
        wait = int(_VIEW_RESEND_AFTER_SECONDS - (time.monotonic() - sent_at))
        raise HTTPException(
            429, "Предыдущий код ещё актуален — новый можно запросить через %d с" % max(1, wait))
    return await _send_view_code()


class MasterKeyViewConfirmBody(BaseModel):
    code: str


@router.post("/api/masterkey/view/confirm")
async def api_masterkey_view_confirm(body: MasterKeyViewConfirmBody):
    """Фаза 2: код 2FA или код из Telegram → единственный ответ с ключом.

    Выполняется ТОЛЬКО при подтверждении фазы 1 и живом pending.
    Введённый код не логируется; ответ содержит ключ и не попадает
    в какие-либо журналы/историю (event-логи здесь не пишутся).
    """
    global _pending_view
    from core import secretbox
    from ui.web.security import get_totp_secret, verify_totp_code

    _clean_expired()
    pending = _pending_view
    if not pending:
        raise HTTPException(400, "Просмотр не начинался или истёк — начните заново")

    if pending["channel"] == "totp":
        secret = get_totp_secret()
        if not secret or not verify_totp_code(body.code, secret):
            pending["attempts"] += 1
            remaining = _VIEW_MAX_ATTEMPTS - pending["attempts"]
            if remaining <= 0:
                _pending_view = None
                raise HTTPException(400, "Неверный код. Попытки исчерпаны — начните заново")
            raise HTTPException(400, f"Неверный код (осталось попыток: {remaining})")
    else:  # telegram
        if body.code.strip() != pending.get("code", ""):
            pending["attempts"] += 1
            remaining = _VIEW_MAX_ATTEMPTS - pending["attempts"]
            if remaining <= 0:
                _pending_view = None
                raise HTTPException(400, "Неверный код. Попытки исчерпаны — начните заново")
            raise HTTPException(400, f"Неверный код (осталось попыток: {remaining})")

    # Подтверждение пройдено — одноразовый pending, единственный возврат ключа
    _pending_view = None
    try:
        key = await asyncio.to_thread(secretbox.read_master_key)
    except secretbox.SecretBoxError as exc:
        raise HTTPException(409, str(exc))
    except Exception:
        raise HTTPException(500, "Не удалось прочитать мастер-ключ")
    return {"ok": True, "key": key}
