"""Авторизация Web UI.

Учётка хранится в config.json (секция ``web``). Пароль хешируется
PBKDF2-HMAC-SHA256 (только stdlib, без сторонних зависимостей).

По умолчанию ``auth_enabled=False`` — локальный режим без логина
(сервис крутится дома). Включается одним флагом, после чего все ``/api``-роуты
(кроме login/me) закрываются зависимостью ``require_auth``.
"""
from __future__ import annotations

import hashlib
import secrets
from typing import Optional

from fastapi import HTTPException, Request, status

from core.actor import Actor, ActorRole, set_actor


# ------------------------------------------------------------------
# Хеширование пароля.
# Формат хранения: pbkdf2_sha256$<iterations>$<salt>$<hex>
# ------------------------------------------------------------------

_ITERATIONS = 200_000

# Минимальная длина НОВОГО пароля панели (security hardening 5.1).
# Проверяется только в set/change-путях (создание админа, смена пароля,
# recovery): существующие пароли короче минимума остаются валидными —
# вход с ними не ломается.
MIN_WEB_PASSWORD_LEN = 10


def make_password(password: str, iterations: int = _ITERATIONS) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
    )
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Постоянное время сравнения через secrets.compare_digest."""
    if not stored or "$" not in stored:
        return False
    parts = stored.split("$", 3)
    if len(parts) != 4:
        return False
    algo, iters_s, salt, hex_hash = parts
    if algo != "pbkdf2_sha256":
        return False
    try:
        iterations = int(iters_s)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
    )
    return secrets.compare_digest(digest.hex(), hex_hash)


# ------------------------------------------------------------------
# Мутации config.json
# ------------------------------------------------------------------

def _audit_web(action, **params) -> None:
    """Пометка аудита о действии с учёткой панели (§8.2, коды ``web.*``).

    Пишется здесь, в единственной точке смены пароля/2FA, а не в роутерах:
    у пароля и у 2FA по несколько входов (карточка настроек, восстановление
    через Telegram, консоль, аварийное создание нового мастер-ключа), и
    «кто снял 2FA» обязано попадать в историю из любого.

    Значения сюда не передаются вовсе — ни пароль, ни TOTP-секрет: в
    ``params`` уходят только факты (``via`` — каким входом).

    Актор — из контекста: Web-сессия или консоль.
    """
    try:
        from core import audit

        audit.record(action, result=audit.AuditResult.OK, params=params or None)
    except Exception as exc:  # аудит не имеет права сломать действие
        print(f"[AUDIT] учётка панели: пометка не удалась: {exc}", flush=True)


def set_web_password(new_password: str, *, via: str = "settings") -> None:
    """Сменить пароль панели.

    ``via`` — каким входом: ``settings`` (карточка настроек), ``account``
    (общая карточка учётки), ``setup`` (первичная настройка), ``recovery``
    (восстановление через код в Telegram) или ``cli`` (консоль). Актор
    отвечает «кто», ``via`` — «каким путём»: смена пароля
    аварийным путём и смена из настроек — разные события для истории.
    """
    from core.config import get_web_config, set_web_config

    web = get_web_config()
    web["password_hash"] = make_password(new_password)
    set_web_config(web)

    from core.audit_actions import AuditAction

    _audit_web(AuditAction.WEB_PASSWORD_CHANGE, via=via)


def set_web_auth(enabled: bool, *, via: str = "settings") -> None:
    """Включить или выключить защиту панели и записать успешную операцию."""
    from core.config import get_web_config, set_web_config
    from core.audit_actions import AuditAction

    enabled = bool(enabled)
    web = get_web_config()
    web["auth_enabled"] = enabled
    set_web_config(web)
    _audit_web(
        AuditAction.WEB_AUTH_ENABLE if enabled else AuditAction.WEB_AUTH_DISABLE,
        via=via,
    )


# ------------------------------------------------------------------
# Двухфакторная аутентификация (TOTP)
#
# Секрет хранится в config.json -> web.totp_secret, зашифрованный
# enc1: (core.secretbox) — как Telegram Bot Token. Пустого поля/отсутствия
# ключа достаточно: 2FA «выключена» = секрета нет.
# ------------------------------------------------------------------

def get_totp_secret() -> str:
    """Активный TOTP-секрет (расшифрованный) или '' если 2FA выключена."""
    from core.config import get_web_config
    from core.secretbox import decrypt

    try:
        return decrypt(str(get_web_config().get("totp_secret") or ""))
    except Exception:
        # Повреждённый ciphertext не должен ронять логин: считаем 2FA
        # невключённой и ждём диагностики (консольный сброс это лечит)
        return ""


def totp_enabled() -> bool:
    return bool(get_totp_secret())


def make_totp_secret() -> str:
    """Новый секрет для приложения-аутентификатора (Base32)."""
    import pyotp

    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, username: str) -> str:
    """otpauth://-URI: то, что кодируется в QR и показывается вручную."""
    import pyotp

    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=username, issuer_name="Bot4VPS"
    )


def verify_totp_code(code: str, secret: str) -> bool:
    """Проверить 6-значный код; окно ±1 шаг (30 c) на рассинхрон часов."""
    import pyotp

    if not code or not secret:
        return False
    try:
        return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)
    except Exception:
        return False


def set_totp_secret(secret: str) -> None:
    """Активировать 2FA: секрет на диск только в зашифрованном виде."""
    from core.config import get_web_config, set_web_config
    from core.secretbox import encrypt

    web = get_web_config()
    web["totp_secret"] = encrypt(secret)
    set_web_config(web)

    from core.audit_actions import AuditAction

    _audit_web(AuditAction.WEB_2FA_ENABLE)


def clear_totp_secret(*, via: str = "settings") -> None:
    """Выключить 2FA (консольный аварийный сброс или отключение по коду).

    ``via`` — каким входом: ``settings`` (отключение по коду из приложения),
    ``cli`` (аварийный сброс из консоли) или ``masterkey_new`` (создание
    нового мастер-ключа: секрет становится нерасшифровываемым и снимается
    вместе с остальными enc1-значениями).
    """
    from core.config import get_web_config, set_web_config

    web = get_web_config()
    web.pop("totp_secret", None)
    set_web_config(web)

    from core.audit_actions import AuditAction

    _audit_web(AuditAction.WEB_2FA_DISABLE, via=via)


# ------------------------------------------------------------------
# Аварийный режим (Этап 1 «Стойкость config.json»)
#
# Единственная причина — ConfigCorruptedError: config.json повреждён и
# валидных копий не нашлось. Отсутствие файла аварией НЕ является
# (тихо создаётся DEFAULT_CONFIG, как всегда). Определяется один раз
# при старте в ensure_web_secrets() — это самый ранний переключатель:
# до создания FastAPI, SessionMiddleware и импорта роутеров.
# ------------------------------------------------------------------

# None | "corrupt"
EMERGENCY: str | None = None


def emergency_state() -> str | None:
    """Аварийный режим Web ('corrupt') или None (обычный запуск)."""
    return EMERGENCY


def ensure_web_secrets() -> dict:
    """
    Гарантирует наличие ``secret_key`` (подпись сессионной куки). Вызывается
    при старте.

    Пароль здесь больше НЕ генерируется: администратора создаёт мастер
    первичной установки (код + /api/setup/complete, см. app.py). Если
    авторизация включена, а пароль пуст — это состояние «заглушки»
    (вход невозможен, подсказка с командой CLI), а не повод печатать
    одноразовый пароль в журнал.

    При повреждённом config.json без валидных копий не падает, а включает
    аварийный режим: приложение поднимется, но все API (кроме статической
    страницы и health) закроет гейт в app.py.
    """
    from core.config import ConfigCorruptedError, load_config, save_config

    global EMERGENCY

    try:
        config = load_config()
    except ConfigCorruptedError as e:
        EMERGENCY = "corrupt"
        print(f"[WEB] АВАРИЙНЫЙ РЕЖИМ: {e}", flush=True)
        print(
            "[WEB] Восстановите конфигурацию: "
            "cp backup/config_latest.json config.json && systemctl restart bot4vps",
            flush=True,
        )
        # Возвратить нечего: конфига нет. Секрет сессии — заглушка
        # (сессий в аварийном режиме не существует, гейт закрывает всё).
        return {
            "auth_enabled": False,
            "username": "",
            "password_hash": "",
            "secret_key": "",
        }

    web = config.get("web")
    if not isinstance(web, dict):
        web = {
            "auth_enabled": False,
            "username": "admin",
            "password_hash": "",
            "secret_key": "",
        }

    changed = False
    if not web.get("secret_key"):
        web["secret_key"] = secrets.token_hex(32)
        changed = True

    if changed:
        config["web"] = web
        save_config(config)
    return web


# ------------------------------------------------------------------
# Первичная настройка (Этап 2): состояния входа
#
# Состояния различаются ПРИЧИНОЙ, а не только наличием админа:
#   normal  — администратор задан (password_hash непуст) → обычный логин;
#   wizard  — код первичной установки есть И админа нет → всё закрыто
#             кроме мастера, НЕЗАВИСИМО от auth_enabled (у дефолтного
#             конфига свежей установки auth_enabled=False — панель не
#             должна открыться «сама»);
#   stub    — авторизация включена, пароля нет, кода нет → вход
#             невозможен, заглушка с командой CLI (миграция со старого
#             механизма одноразовых паролей, сброс без кода);
#   emergency — config.json повреждён (владелец — EMERGENCY выше).
# ------------------------------------------------------------------

def admin_exists() -> bool:
    """Администратор задан = password_hash непуст (логин вторичен)."""
    from core.config import get_web_config

    return bool(get_web_config().get("password_hash"))


def setup_wizard_active() -> bool:
    """Мастер первичной установки активен: код есть И админа нет.

    Истёкший код кодом не считается (TTL, см. core/setup_code.py):
    current_setup_code() возвращает None — мастер закрывается.
    """
    from core.setup_code import current_setup_code

    if admin_exists():
        return False
    return bool(current_setup_code())


def setup_expired_active() -> bool:
    """Код установки выдан, но истёк: панель остаётся закрытой.

    Без этого состояния истёкший код на свежей установке
    (auth_enabled=False) переоткрыл бы панель: мастер закрылся (кода
    «нет»), а заглушка не активна (авторизация выключена). Страница
    показывает, как перевыпустить код (CLI «Восстановление»).
    """
    from core.setup_code import setup_code_state

    if admin_exists():
        return False
    return bool(setup_code_state()["expired"])


def login_stub_active() -> bool:
    """Заглушка: авторизация включена, пароля нет, кода не выдано.

    auth_enabled=False + нет админа + нет кода — НЕ заглушка (обычный
    открытый режим tg-only установок, как сегодня); admin_exists
    проверяется первым — с админом заглушки не бывает.
    """
    from core.setup_code import current_setup_code

    if admin_exists():
        return False
    if current_setup_code():
        return False
    return auth_enabled()


# ------------------------------------------------------------------
# FastAPI dependency
# ------------------------------------------------------------------

def auth_enabled() -> bool:
    from core.config import get_web_config

    return bool(get_web_config().get("auth_enabled"))


# ------------------------------------------------------------------
# Актор web-запроса (аудит действий, см. core/actor.py)
# ------------------------------------------------------------------

# Ключ сессии со снимком роли. Роль попадает сюда при входе и живёт до
# выхода/истечения сессии: запись аудита хранит снимок, а не ссылку на
# текущую роль, иначе смена прав переписала бы историю задним числом.
ROLE_SESSION_KEY = "role"


def _client_ip(request: Request) -> Optional[str]:
    client = getattr(request, "client", None)
    return getattr(client, "host", None) or None


def _session(request: Request) -> dict:
    """Сессия запроса, если SessionMiddleware установлен.

    Без middleware ``Request.session`` бросает AssertionError. В панели он
    стоит всегда, но актор не должен быть точкой отказа: определённый без
    сессии запрос — это web-действие без имени, а не 500.
    """
    try:
        return request.session
    except Exception:
        return {}


def actor_from_request(request: Request) -> Actor:
    """Снимок действующего субъекта web-запроса.

    Логин и роль — из сессии, IP — из соединения. Без логина (панель без
    авторизации) остаётся ``type=web`` без имени: роль не выдумываем.
    """
    session = _session(request)
    return Actor.web(
        session.get("user"),
        role=session.get(ROLE_SESSION_KEY),
        ip=_client_ip(request),
    )


def set_request_actor(request: Request) -> Actor:
    """Выставить актора запроса в контекст (и в ``request.state`` для хендлеров)."""
    actor = actor_from_request(request)
    request.state.actor = actor
    set_actor(actor)
    return actor


def establish_web_session(request: Request, username: str) -> None:
    """Открыть web-сессию: логин, снимок роли и актор — одним действием.

    Единая точка входа вместо россыпи ``session["user"] = ...``: место,
    где сессия появляется, обязано заодно зафиксировать роль, иначе
    аудит останется без неё в одном из путей входа (их четыре: мастер
    первичной настройки, вход, второй шаг 2FA, восстановление пароля).
    """
    request.session["user"] = username
    request.session[ROLE_SESSION_KEY] = ActorRole.ADMIN.value
    set_request_actor(request)

    from core.audit_actions import AuditAction

    _audit_web(AuditAction.WEB_LOGIN)


async def require_auth(request: Request) -> None:
    """Пропускает запрос, если авторизация выключена; иначе требует сессию."""
    # Актор выставляется до проверки: он нужен и в режиме без авторизации
    # (тогда у актора нет имени), а отказанный запрос до хендлера не дойдёт
    # и в аудит не попадёт.
    set_request_actor(request)
    if not auth_enabled():
        return
    if request.session.get("user"):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Требуется авторизация",
        headers={"WWW-Authenticate": "Session"},
    )
