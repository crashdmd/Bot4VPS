"""Настройки приложения: лимиты истории, порт Web UI.

Страница «Настройки» (ui/web/static/js/settings.js) собирает параметры из
нескольких доменных API (auth, telegram, monitor, update); здесь живут только
те, что не имели своего эндпоинта:

- ``/api/settings/timezone`` — фактическая IANA timezone локального хоста и
  подтверждённая смена только через ``timedatectl``;
- ``/api/settings/theme``   — тема Web UI (config.json -> ui_theme): страница
  стартует с неё даже после сброса кеша браузера;
- ``/api/settings/history``  — лимиты logs.tasks / logs.events с горячим
  применением (без перезапуска сервиса);
- ``/api/settings/web``      — текущий порт Web UI + возможность смены;
- ``/api/settings/web/port``  — запуск процедуры смены порта (детached-раннер
  ``core/web_port.py`` переживает restart сервиса и сам откатывает юнит
  при неудачном старте на новом порту).
"""
from __future__ import annotations

import asyncio
import hmac
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..deps import err

router = APIRouter(tags=["settings"])


# ==================================================================
# Пароль резервных копий (шифрование B4VE)
# ==================================================================

class BackupPasswordBody(BaseModel):
    # Непустая строка — задать/сменить пароль (шифруется мастер-ключом).
    # Пустая строка — убрать пароль (новые архивы без шифрования).
    password: str
    # Подтверждение текущим паролем для смены/удаления: если пароль уже
    # задан, ослабить защиту (сменить/убрать) можно только зная его.
    current_password: str | None = None


class VerifyBackupPasswordBody(BaseModel):
    password: str


def _protected_backup_targets() -> int:
    """Сколько целей бэкапа имеют включённую защиту (encrypt=true).

    Для предупреждения при удалении пароля: их новые архивы станут
    создаваться без шифрования.
    """
    try:
        from core.config import get_backup_config
        from core.storage import load_servers

        count = 0
        for server in load_servers():
            profile = server.get("backup") if isinstance(server, dict) else None
            if isinstance(profile, dict) and profile.get("encrypt") is True:
                count += 1
        if get_backup_config().get("bot4vps", {}).get("encrypt") is True:
            count += 1
        return count
    except Exception:
        # Счётчик носит информационный характер — сбой чтения не должен
        # ломать сам эндпоинт.
        return 0


@router.get("/api/settings/backup-password")
async def api_settings_backup_password_get():
    """Только факт настройки: сам пароль (enc1:) через API не отдаётся."""
    from core.config import backup_password_configured
    from core.secretbox import master_key_state

    state = master_key_state()
    return {
        "configured": backup_password_configured(),
        "masterkey_available": state.get("state") == "ok",
        "protected_targets": _protected_backup_targets(),
    }


@router.post("/api/settings/backup-password/verify")
async def api_settings_backup_password_verify(body: VerifyBackupPasswordBody):
    """Сверка пароля без его смены (подтверждение снятия галочки защиты).

    Возвращается только факт совпадения — сам сохранённый пароль (enc1:)
    никогда не отдаётся и не логируется.
    """
    from core.config import get_stored_backup_password
    from core.secretbox import SecretBoxError

    try:
        stored = get_stored_backup_password() or ""
    except SecretBoxError:
        # Мастер-ключ недоступен: сохранить уверенность в совпадении нельзя.
        raise HTTPException(
            409,
            "Мастер-ключ недоступен: восстановите его в Настройки → Безопасность",
        )
    # compare_digest на bytes: пароль может содержать не-ASCII символы,
    # str-вариант их отвергает.
    ok = bool(stored) and hmac.compare_digest(
        stored.encode("utf-8"), (body.password or "").encode("utf-8")
    )
    return {"ok": ok}


@router.post("/api/settings/backup-password")
async def api_settings_backup_password_set(body: BackupPasswordBody):
    from core.config import (
        backup_password_configured,
        get_stored_backup_password,
        set_stored_backup_password,
    )
    from core.secretbox import MasterKeyMissingError, SecretBoxError

    password = body.password
    if len(password) > 256:
        raise HTTPException(400, "Пароль резервных копий — до 256 символов")
    try:
        # Ослабление защиты (смена/удаление существующего пароля) требует
        # подтверждения текущим паролем: тот, кто просто попал в панель,
        # не должен молча отключить шифрование архивов. Задание первого
        # пароля подтверждения не требует — проверять нечего.
        stored = get_stored_backup_password() or None
        if stored is not None:
            if body.current_password is None or not hmac.compare_digest(
                stored.encode("utf-8"),
                (body.current_password or "").encode("utf-8"),
            ):
                raise HTTPException(403, "Неверный текущий пароль резервных копий")
        # Мастер-ключ обязателен: пароль хранится только в зашифрованном
        # виде (enc1:). Пароль никогда не логируется и не возвращается.
        await asyncio.to_thread(set_stored_backup_password, password or None)
    except (MasterKeyMissingError, SecretBoxError):
        raise HTTPException(
            409,
            "Мастер-ключ недоступен: восстановите его в Настройки → Безопасность",
        )
    return {
        "ok": True,
        "configured": backup_password_configured(),
        "protected_targets": _protected_backup_targets(),
    }


# ==================================================================
# «Забыл пароль»: аварийное удаление пароля резервных копий
# ==================================================================
# По образцу просмотра мастер-ключа (routers/masterkey.py): подтверждение
# владельца двумя факторами — пароль Web-учётной записи + код 2FA
# (приоритетно) или код в Telegram. Ни того ни другого — только консоль.
# Pending живёт в памяти процесса (один uvicorn-worker), код не логируется.

_BP_FORGOT_TTL_SECONDS = 600.0
_BP_FORGOT_MAX_ATTEMPTS = 5
_BP_FORGOT_COOLDOWN_SECONDS = 30.0
# Повторная отправка по кнопке «Не пришёл код»: раньше этого срока новый
# код бессмыслен (старый жив и мог просто задержаться в доставке).
_BP_FORGOT_RESEND_AFTER_SECONDS = 120.0
_pending_bp_forgot: dict | None = None  # {channel, code, expires_at, attempts}
_last_bp_forgot_request_at = 0.0


def _bp_forgot_clean_expired() -> None:
    global _pending_bp_forgot
    import time as _time

    if _pending_bp_forgot and _time.monotonic() > _pending_bp_forgot["expires_at"]:
        _pending_bp_forgot = None


class BackupPasswordForgotBody(BaseModel):
    # Пароль Web-учётной записи (не пароль резервных копий — он как раз
    # утерян). Без валидаторов: 422-ответ FastAPI содержит введённое значение.
    password: str


@router.post("/api/settings/backup-password/forgot")
async def api_settings_backup_password_forgot(body: BackupPasswordForgotBody):
    """Фаза 1: проверить пароль Web и отправить код подтверждения.

    Пароль резервных копий при этом не проверяется и не отдаётся —
    сценарий ровно тот, где он утерян.
    """
    global _pending_bp_forgot, _last_bp_forgot_request_at
    import time as _time

    from core.config import backup_password_configured, get_web_config
    from ui.web.security import totp_enabled, verify_password

    if not backup_password_configured():
        raise HTTPException(400, "Пароль резервных копий не задан — удалять нечего")

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
        # который пользователь введёт в /forgot/confirm.
        _pending_bp_forgot = {
            "channel": "totp",
            "expires_at": _time.monotonic() + _BP_FORGOT_TTL_SECONDS,
            "attempts": 0,
        }
        return {"ok": True, "channel": "totp"}

    # Telegram-канал: код доставки в TG (доставка — как в recovery-флоу).
    # Выключенный Telegram — осознанное решение владельца: код не отправляем.
    from ui.web.app import _recovery_available, _send_recovery_message

    if _recovery_available():
        # Живой код уже отправлен (пользователь закрыл окно и вернулся):
        # НЕ отправляем новый и НЕ блокируем — переиспользуем pending.
        _bp_forgot_clean_expired()
        pending = _pending_bp_forgot
        if pending and pending.get("channel") == "telegram":
            return {"ok": True, "channel": "telegram", "resent": False}
        return await _send_bp_forgot_code()

    # Ни 2FA, ни доступного Telegram: Web не может подтвердить владельца.
    # Единственный путь — консоль (там пароль Web не требуется).
    raise HTTPException(
        403,
        "С текущими настройками безопасности удалить пароль резервных копий "
        "через Web невозможно. Используйте консоль управления сервисом "
        "Bot4VPS (bot4vps → 2. Безопасность → 6. Очистить пароль резервных копий).",
    )


async def _send_bp_forgot_code() -> dict:
    """Реальная отправка нового TG-кода (первая или повторная по кнопке).

    Повторная стирает старый pending: в силе всегда ровно один код.
    Кулдаун 30 с между отправками (защита от спама кнопкой).
    """
    global _pending_bp_forgot, _last_bp_forgot_request_at
    import secrets as pysecrets
    import time as _time

    from ui.web.app import _send_recovery_message

    now = _time.monotonic()
    if now - _last_bp_forgot_request_at < _BP_FORGOT_COOLDOWN_SECONDS:
        raise HTTPException(429, "Код уже отправлен — повторите чуть позже")
    _last_bp_forgot_request_at = now
    code = f"{pysecrets.randbelow(1_000_000):06d}"
    text = (
        "🔓 <b>Удаление пароля резервных копий Bot4VPS</b>\n\n"
        f"Код подтверждения: <code>{code}</code>\n"
        "Действует 10 минут.\n\n"
        "Если вы не запрашивали удаление — проигнорируйте сообщение: "
        "без кода пароль не удаляется."
    )
    try:
        await _send_recovery_message(text)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "Не удалось отправить код в Telegram") from exc
    _pending_bp_forgot = {
        "channel": "telegram",
        "code": code,
        "expires_at": _time.monotonic() + _BP_FORGOT_TTL_SECONDS,
        "attempts": 0,
    }
    return {"ok": True, "channel": "telegram", "resent": True}


@router.post("/api/settings/backup-password/forgot/resend")
async def api_settings_backup_password_forgot_resend():
    """«Не пришёл код? Отправить ещё раз» — осознанная повторная отправка.

    Доступна не раньше _BP_FORGOT_RESEND_AFTER_SECONDS после первой:
    раньше нового кода ждать бессмысленно. Новый код стирает старый.
    """
    import time as _time

    _bp_forgot_clean_expired()
    pending = _pending_bp_forgot
    if not pending or pending.get("channel") != "telegram":
        raise HTTPException(400, "Код ещё не отправлялся — начните заново")
    sent_at = pending["expires_at"] - _BP_FORGOT_TTL_SECONDS
    if _time.monotonic() - sent_at < _BP_FORGOT_RESEND_AFTER_SECONDS:
        wait = int(_BP_FORGOT_RESEND_AFTER_SECONDS - (_time.monotonic() - sent_at))
        raise HTTPException(
            429, "Предыдущий код ещё актуален — новый можно запросить через %d с" % max(1, wait))
    return await _send_bp_forgot_code()


class BackupPasswordForgotConfirmBody(BaseModel):
    code: str


@router.post("/api/settings/backup-password/forgot/confirm")
async def api_settings_backup_password_forgot_confirm(
    body: BackupPasswordForgotConfirmBody,
):
    """Фаза 2: код 2FA или код из Telegram → удалить пароль резервных копий.

    Выполняется ТОЛЬКО при подтверждённой фазе 1 и живом pending.
    После удаления новые архивы создаются без шифрования; старые архивы
    по-прежнему открываются своим (утерянным) паролем.
    """
    global _pending_bp_forgot
    from core.config import backup_password_configured, set_stored_backup_password
    from core.secretbox import MasterKeyMissingError, SecretBoxError
    from ui.web.security import get_totp_secret, verify_totp_code

    _bp_forgot_clean_expired()
    pending = _pending_bp_forgot
    if not pending:
        raise HTTPException(400, "Удаление не начиналось или истёк — начните заново")

    if pending["channel"] == "totp":
        secret = get_totp_secret()
        if not secret or not verify_totp_code(body.code, secret):
            pending["attempts"] += 1
            remaining = _BP_FORGOT_MAX_ATTEMPTS - pending["attempts"]
            if remaining <= 0:
                _pending_bp_forgot = None
                raise HTTPException(400, "Неверный код. Попытки исчерпаны — начните заново")
            raise HTTPException(400, f"Неверный код (осталось попыток: {remaining})")
    else:  # telegram
        if (body.code or "").strip() != pending.get("code", ""):
            pending["attempts"] += 1
            remaining = _BP_FORGOT_MAX_ATTEMPTS - pending["attempts"]
            if remaining <= 0:
                _pending_bp_forgot = None
                raise HTTPException(400, "Неверный код. Попытки исчерпаны — начните заново")
            raise HTTPException(400, f"Неверный код (осталось попыток: {remaining})")

    # Подтверждение пройдено — одноразовый pending, удаляем пароль
    _pending_bp_forgot = None
    try:
        await asyncio.to_thread(set_stored_backup_password, None)
    except (MasterKeyMissingError, SecretBoxError):
        raise HTTPException(
            409,
            "Мастер-ключ недоступен: восстановите его в Настройки → Безопасность",
        )
    return {
        "ok": True,
        "configured": backup_password_configured(),
        "protected_targets": _protected_backup_targets(),
    }


# ==================================================================
# Часовой пояс локального хоста
# ==================================================================

class TimezoneBody(BaseModel):
    timezone: str


@router.get("/api/settings/timezone")
async def api_settings_timezone_get():
    from core.timezone import HostTimezoneError, timezone_payload

    try:
        return await asyncio.to_thread(timezone_payload, include_options=True)
    except HostTimezoneError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/api/settings/timezone")
async def api_settings_timezone_set(body: TimezoneBody):
    from core.config import set_host_timezone_config
    from core.timezone import (
        HostTimezoneError,
        InvalidTimezoneError,
        set_timezone_verified,
        timezone_details,
    )

    try:
        confirmed = await asyncio.to_thread(
            set_timezone_verified,
            body.timezone,
            set_host_timezone_config,
        )
        return timezone_details(confirmed)
    except InvalidTimezoneError as exc:
        raise HTTPException(400, str(exc)) from exc
    except HostTimezoneError as exc:
        raise HTTPException(500, str(exc)) from exc


# ==================================================================
# Тема Web UI
# ==================================================================

class ThemeBody(BaseModel):
    theme: str


@router.get("/api/settings/theme")
async def api_settings_theme_get():
    from core.config import get_ui_theme

    return {"theme": get_ui_theme()}


@router.post("/api/settings/theme")
async def api_settings_theme_set(body: ThemeBody):
    from core.config import set_ui_theme

    try:
        theme = await asyncio.to_thread(set_ui_theme, body.theme)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "theme": theme}


# ==================================================================
# История и данные (лимиты хранения)
# ==================================================================

class HistoryLimits(BaseModel):
    tasks: int | None = None
    events: int | None = None


def _validated_limit(value: int, name: str) -> int:
    # bool — подкласс int: чекбокс не должен превращаться в 0/1
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(400, "%s: ожидается целое число" % name)
    if not 1 <= value <= 10000:
        raise HTTPException(400, "%s: от 1 до 10000" % name)
    return value


@router.get("/api/settings/history")
async def api_settings_history_get():
    try:
        from core.config import get_logs_limits
        return get_logs_limits()
    except Exception as e:
        return err(e)


@router.post("/api/settings/history")
async def api_settings_history_set(body: HistoryLimits):
    try:
        tasks = _validated_limit(body.tasks, "tasks") if body.tasks is not None else None
        events = _validated_limit(body.events, "events") if body.events is not None else None
        if tasks is None and events is None:
            raise HTTPException(400, "укажите tasks и/или events")

        # Config сначала — это долговременное намерение. Runtime-применение
        # вторым: если оно упадёт, лимит всё равно вступит в силу после
        # перезапуска (applied: false). Обратный порядок опасен: prune
        # удаляет старые файлы безвозвратно ещё до сохранения config.
        from core.config import set_logs_limits
        set_logs_limits(tasks=tasks, events=events)

        applied = True
        if tasks is not None:
            try:
                from core.task_manager import task_manager
                task_manager.set_history_limit(tasks)
            except Exception as e:
                print("[WEB] set tasks limit: %s" % e, flush=True)
                applied = False
        if events is not None:
            try:
                from core.events import set_events_limit
                set_events_limit(events)
            except Exception as e:
                print("[WEB] set events limit: %s" % e, flush=True)
                applied = False

        from core.config import get_logs_limits
        result = get_logs_limits()
        result["ok"] = True
        result["applied"] = applied
        if not applied:
            result["note"] = "Сохранено; применится полностью после перезапуска сервиса"
        return result
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


# ==================================================================
# Web: порт панели
# ==================================================================

class WebPortBody(BaseModel):
    port: int


@router.get("/api/settings/web")
async def api_settings_web_get():
    try:
        from core.web_port import changeable, current_port_from_unit, busy
        ok, reason = changeable()
        return {
            "port": current_port_from_unit(),
            "changeable": ok,
            "reason": reason,
            "busy": busy(),
        }
    except Exception as e:
        return err(e)


@router.get("/api/settings/web/port-status")
async def api_settings_web_port_status():
    """Состояние процедуры смены порта (раннер пишет в data/web_port.json)."""
    try:
        from core.web_port import read_state
        return read_state()
    except Exception as e:
        return err(e)


@router.post("/api/settings/web/port")
async def api_settings_web_port_set(body: WebPortBody):
    try:
        from core.web_port import (
            busy, changeable, current_port_from_unit, launch, write_state,
        )

        if isinstance(body.port, bool) or not 1 <= body.port <= 65535:
            raise HTTPException(400, "port: от 1 до 65535")

        current = current_port_from_unit()
        if current is None:
            raise HTTPException(400, "порт Web UI не найден в systemd-юните")
        if body.port == current:
            raise HTTPException(400, "порт уже используется: %d" % current)

        ok, reason = changeable()
        if not ok:
            raise HTTPException(400, reason or "смена порта недоступна")
        if busy():
            raise HTTPException(409, "Смена порта уже выполняется")

        write_state(
            status="pending",
            old_port=current,
            new_port=body.port,
            started_at=datetime.now().isoformat(),
            finished_at=None,
            pid=None,
            error=None,
            log=[],
        )
        # Дальше работает detached-раннер: этот процесс будет убит restart'ом
        pid = await asyncio.to_thread(launch, body.port)
        write_state(pid=pid)
        return {
            "ok": True,
            "status": "pending",
            "old_port": current,
            "new_port": body.port,
        }
    except HTTPException:
        raise
    except Exception as e:
        return err(e)
