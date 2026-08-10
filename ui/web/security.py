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


def ensure_web_secrets() -> dict:
    """
    Гарантирует наличие ``secret_key`` (подпись сессионной куки) и, если
    авторизация включена, — валидного ``password_hash``. Вызывается при старте.
    Если auth включён, а пароль пуст — генерирует одноразовый и печатает в лог.
    """
    from core.config import load_config, save_config

    config = load_config()
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

    if web.get("auth_enabled") and not web.get("password_hash"):
        one_time = secrets.token_urlsafe(12)
        web["password_hash"] = make_password(one_time)
        changed = True
        print("[WEB] Авторизация включена, но пароль не задан.", flush=True)
        print(f"[WEB] Одноразовый пароль: {one_time}", flush=True)
        print("[WEB] Смените его через POST /api/auth/password.", flush=True)

    if changed:
        config["web"] = web
        save_config(config)
    return web


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
