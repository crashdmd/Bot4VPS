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

from fastapi import HTTPException, Request, status


# ------------------------------------------------------------------
# Хеширование пароля.
# Формат хранения: pbkdf2_sha256$<iterations>$<salt>$<hex>
# ------------------------------------------------------------------

_ITERATIONS = 200_000


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

def set_web_password(new_password: str) -> None:
    from core.config import get_web_config, set_web_config

    web = get_web_config()
    web["password_hash"] = make_password(new_password)
    set_web_config(web)


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


def clear_totp_secret() -> None:
    """Выключить 2FA (консольный аварийный сброс или отключение по коду)."""
    from core.config import get_web_config, set_web_config

    web = get_web_config()
    web.pop("totp_secret", None)
    set_web_config(web)


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


async def require_auth(request: Request) -> None:
    """Пропускает запрос, если авторизация выключена; иначе требует сессию."""
    if not auth_enabled():
        return
    if request.session.get("user"):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Требуется авторизация",
        headers={"WWW-Authenticate": "Session"},
    )
