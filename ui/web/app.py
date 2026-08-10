"""
Bot4VPS Web UI

Единый процесс (Web + Telegram):

    cd /opt/bot4vps
    source venv/bin/activate
    PYTHONPATH=. uvicorn ui.web.app:app --host 0.0.0.0 --port 8080

Только Telegram (без Web):

    PYTHONPATH=. python bot.py

Авторизация по умолчанию выключена (локальный режим). Включается флагом
``web.auth_enabled`` в config.json — после этого все /api-роуты (кроме
login/me) закрываются зависимостью require_auth.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from .deps import VERSION
from .security import (
    auth_enabled,
    ensure_web_secrets,
    make_password,
    require_auth,
    set_web_password,
    verify_password,
)

STATIC = Path(__file__).resolve().parent / "static"

# Гарантируем secret_key (и при включённой авторизации — password_hash)
# до сборки приложения, чтобы SessionMiddleware получила корректный ключ.
_web_cfg = ensure_web_secrets()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Единая точка старта: Web + Telegram в одном процессе.

    uvicorn владеет сигналами и event loop.
    PTB — ручной lifecycle (без run_polling), чтобы не конфликтовать с handlers.
    """
    print(
        f"[WEB] Bot4VPS Web UI {VERSION} "
        f"(auth={'on' if _web_cfg.get('auth_enabled') else 'off'})",
        flush=True,
    )
    for r in _app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None)
        if path and methods:
            print(f"[WEB] {sorted(methods)} {path}", flush=True)

    # Telegram (опционально: BOT_TOKEN пустой/заглушка — пропускаем)
    tg_app = None
    try:
        from bot import start_telegram, stop_telegram, BOT_TOKEN
        token = (BOT_TOKEN or "").strip()
        if not token or token.startswith("YOUR_"):
            print("[WEB] Telegram: token не задан — бот не запущен", flush=True)
        else:
            tg_app = await start_telegram()
    except Exception as e:
        print(f"[WEB] Telegram start failed: {e}", flush=True)
        tg_app = None

    try:
        yield
    finally:
        if tg_app is not None:
            try:
                from bot import stop_telegram
                await stop_telegram(tg_app)
            except Exception as e:
                print(f"[WEB] Telegram stop failed: {e}", flush=True)


app = FastAPI(title="Bot4VPS Web UI", version=VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    SessionMiddleware,
    secret_key=_web_cfg.get("secret_key") or "dev-insecure-secret",
    session_cookie="bot4vps_sid",
    max_age=60 * 60 * 24 * 7,  # 7 дней
    same_site="lax",
    https_only=False,
)

from .routers import meta, summary, servers, tasks, scripts, files, monitor, stream, terminal, services  # noqa: E402

app.mount("/static", StaticFiles(directory=STATIC), name="static")

_AUTH = [Depends(require_auth)]

# Все /api-роутеры закрыты require_auth; login/me/logout/password добавлены ниже напрямую.
app.include_router(meta.router, dependencies=_AUTH)
app.include_router(summary.router, dependencies=_AUTH)
app.include_router(servers.router, dependencies=_AUTH)
app.include_router(tasks.router, dependencies=_AUTH)
app.include_router(scripts.router, dependencies=_AUTH)
app.include_router(files.router, dependencies=_AUTH)
app.include_router(monitor.router, dependencies=_AUTH)
app.include_router(stream.router, dependencies=_AUTH)
app.include_router(services.router, dependencies=_AUTH)

# WebSocket-терминал: авторизация проверяется внутри хендлера (по сессии в scope),
# т.к. router-level deps на WS работают ненадёжно.
app.include_router(terminal.router)


@app.get("/")
async def index():
    index_file = STATIC / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>Нет static/index.html</h1>", status_code=500)
    return FileResponse(index_file)


# ------------------------------------------------------------------
# Авторизация (эти эндпоинты — без require_auth)
# ------------------------------------------------------------------

class LoginBody(BaseModel):
    username: str
    password: str


class PasswordBody(BaseModel):
    old: str
    new: str


@app.get("/api/me")
async def api_me(request: Request):
    if not auth_enabled():
        return {"auth_enabled": False, "user": None}
    return {"auth_enabled": True, "user": request.session.get("user")}


@app.post("/api/login")
async def api_login(request: Request, body: LoginBody):
    if not auth_enabled():
        return {"ok": True, "auth_enabled": False}
    from core.config import get_web_config
    web = get_web_config()
    if body.username == web.get("username") and verify_password(
        body.password, web.get("password_hash", "")
    ):
        request.session["user"] = body.username
        return {"ok": True, "user": body.username}
    raise HTTPException(401, "Неверный логин или пароль")


@app.post("/api/logout")
async def api_logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.post("/api/auth/password")
async def api_change_password(request: Request, body: PasswordBody):
    if not auth_enabled():
        raise HTTPException(400, "Авторизация выключена")
    if not request.session.get("user"):
        raise HTTPException(401, "Требуется авторизация")
    from core.config import get_web_config
    web = get_web_config()
    if not verify_password(body.old, web.get("password_hash", "")):
        raise HTTPException(400, "Старый пароль неверен")
    if len(body.new) < 6:
        raise HTTPException(400, "Пароль не короче 6 символов")
    set_web_password(body.new)
    return {"ok": True}


# Управление учёткой из страницы «Настройки»: логин/пароль + тумблер авторизации.
class AccountBody(BaseModel):
    old: str | None = None
    username: str | None = None
    new_password: str | None = None
    auth_enabled: bool | None = None


@app.get("/api/auth/account")
async def api_account_get():
    from core.config import get_web_config
    w = get_web_config()
    return {"auth_enabled": bool(w.get("auth_enabled")), "username": w.get("username", "admin")}


@app.post("/api/auth/account")
async def api_account_set(request: Request, body: AccountBody):
    # В локальном режиме (auth off) пускаем; при включённой — только залогиненный.
    if auth_enabled() and not request.session.get("user"):
        raise HTTPException(401, "Требуется авторизация")

    from core.config import get_web_config, set_web_config
    w = get_web_config()
    currently_on = bool(w.get("auth_enabled"))

    if body.new_password is not None:
        # При включённой авторизации смена пароля требует подтверждения старым.
        if currently_on and not verify_password(body.old or "", w.get("password_hash", "")):
            raise HTTPException(400, "Старый пароль неверен")
        if len(body.new_password) < 6:
            raise HTTPException(400, "Пароль не короче 6 символов")
        w["password_hash"] = make_password(body.new_password)

    if body.username is not None:
        u = body.username.strip()
        if not u:
            raise HTTPException(400, "Логин не может быть пустым")
        w["username"] = u

    if body.auth_enabled is not None:
        if body.auth_enabled and not w.get("password_hash"):
            raise HTTPException(400, "Сначала задайте пароль")
        w["auth_enabled"] = bool(body.auth_enabled)

    set_web_config(w)
    return {"ok": True, "auth_enabled": bool(w.get("auth_enabled")), "username": w.get("username")}
