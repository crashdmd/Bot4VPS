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
login/me/logout/recover/totp) закрываются зависимостью require_auth.
При включённой 2FA (web.totp_secret) вход двухшаговый: пароль →
``/api/login`` отвечает ``otp_required`` БЕЗ сессии, сессию создаёт
только ``/api/login/otp`` с кодом из приложения-аутентификатора.
"""
from __future__ import annotations

import asyncio
import hmac
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .deps import VERSION
from .security import (
    admin_exists,
    auth_enabled,
    clear_totp_secret,
    emergency_state,
    ensure_web_secrets,
    get_totp_secret,
    login_stub_active,
    make_password,
    make_totp_secret,
    MIN_WEB_PASSWORD_LEN,
    require_auth,
    set_web_password,
    set_totp_secret,
    setup_expired_active,
    setup_wizard_active,
    totp_enabled,
    totp_provisioning_uri,
    verify_password,
    verify_totp_code,
)

STATIC = Path(__file__).resolve().parent / "static"


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles без клиентского кэша для ES-модулей Web UI.

    В интерфейсе нет сборщика, а модули импортируют друг друга по постоянным URL.
    Поэтому браузер иначе может оставить старый docker.js после обновления backend.
    """

    async def get_response(self, path: str, scope: dict):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


# Аварийная страница: полностью автономна от config — только текст
# и инлайн-стили (никаких тем/шаблонов/чтения конфигурации). Пока
# раздела «Восстановление» в CLI нет (Этап 3), текст даёт ручной рецепт.
_EMERGENCY_PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Bot4VPS — аварийный режим</title>
<style>
  body { font-family: system-ui, sans-serif; background: #1a1a1a; color: #eee;
         max-width: 640px; margin: 12vh auto; padding: 0 20px; }
  h1 { font-size: 1.4rem; }
  code, pre { background: #2a2a2a; padding: 2px 6px; border-radius: 4px; }
  pre { padding: 12px; overflow-x: auto; }
</style>
</head>
<body>
<h1>Конфигурация Bot4VPS повреждена</h1>
<p>config.json не читается, и восстановить его автоматически не удалось.
Все функции панели закрыты.</p>
<p>Подключитесь к серверу по SSH и восстановите последнюю рабочую копию:</p>
<pre>cd /opt/bot4vps
cp backup/config_latest.json config.json
systemctl restart bot4vps</pre>
<p>Если config_latest.json тоже повреждён — используйте самую свежую
копию из <code>backup/config_*.json</code>.</p>
</body>
</html>"""


class EmergencyGateMiddleware(BaseHTTPMiddleware):
    """Backend-гейт аварийного режима: закрывает ВСЕ API (не «визуально»).

    Пропускает только аварийную страницу, статику и health-check
    раннера обновлений (без него Web-обновления падали бы на
    health-проверке). Никаких действий восстановления через API
    в аварийном режиме не существует.

    Регистрируется ПОСЛЕДНИМ — в стеке Starlette последний
    добавленный middleware выполняется первым на запросе, т.е. гейт
    стоит раньше сессий, CORS и роутеров.
    """

    _ALLOWED_EXACT = {"/", "/api/upd/health"}
    _ALLOWED_PREFIXES = ("/static/",)

    async def dispatch(self, request: Request, call_next):
        if not emergency_state():
            return await call_next(request)
        path = request.url.path
        if (
            path in self._ALLOWED_EXACT
            or path.startswith(self._ALLOWED_PREFIXES)
        ):
            return await call_next(request)
        return JSONResponse(
            {"detail": "Конфигурация повреждена — сервис в аварийном режиме"},
            status_code=503,
        )


class SetupGateMiddleware(BaseHTTPMiddleware):
    """Гейт первичной настройки: мастер и заглушка закрывают все API.

    Мастер (код установки есть И админа нет): панель не должна
    открыться «сама» у свежей установки — дефолтный auth_enabled=False,
    поэтому закрыто всё, кроме страницы, статики и эндпоинтов мастера,
    НЕЗАВИСИМО от auth_enabled. Заглушка (auth включён, пароля нет,
    кода нет): вход невозможен — открыт только статус, по которому
    фронт показывает команду CLI.

    Аварийный режим не трогаем: им владеет EmergencyGateMiddleware
    (проверка emergency_state() до любых обращений к config — в аварии
    load_config поднимает исключение).
    """

    _WIZARD_EXACT = {
        "/", "/api/setup/status", "/api/setup/complete", "/api/upd/health",
    }
    _STUB_EXACT = {"/", "/api/setup/status", "/api/upd/health"}
    _ALLOWED_PREFIXES = ("/static/",)

    async def dispatch(self, request: Request, call_next):
        if emergency_state():
            # Авария владеет гейтом: config читать нельзя (исключение),
            # дальше запрос разберёт EmergencyGateMiddleware
            return await call_next(request)
        path = request.url.path
        if path.startswith(self._ALLOWED_PREFIXES) or path == "/api/upd/health":
            return await call_next(request)
        if setup_wizard_active():
            if path in self._WIZARD_EXACT:
                return await call_next(request)
            return JSONResponse(
                {"detail": "Требуется первичная настройка — создайте администратора"},
                status_code=503,
            )
        if setup_expired_active():
            # Код выдан, но истёк (TTL): панель не открывается, пока код
            # не перевыпущен из CLI — иначе свежая установка с auth off
            # открылась бы по просроченному коду
            if path in self._STUB_EXACT:
                return await call_next(request)
            return JSONResponse(
                {
                    "detail": (
                        "Код первичной установки истёк — перевыпустите его "
                        "через bot4vps → Восстановление"
                    )
                },
                status_code=503,
            )
        if login_stub_active():
            if path in self._STUB_EXACT:
                return await call_next(request)
            return JSONResponse(
                {
                    "detail": (
                        "Вход невозможен: администратор не задан, "
                        "код первичной установки не выдан"
                    )
                },
                status_code=503,
            )
        return await call_next(request)

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

    # Консольная команда bot4vps — часть ui/cli; первый запуск новой
    # версии (после обновления/переноса/восстановления) гарантирует её
    # наличие. Bootstrap не-фатален и не должен мешать старту Web.
    try:
        from ui.cli.bootstrap import ensure_cli_command
        ensure_cli_command()
    except Exception as e:
        print(f"[WEB] cli command ensure failed: {e}", flush=True)

    # Аварийный режим: конфигурации нет — всё, что её читает, не
    # поднимаем (init_on_startup, core jobs, Telegram, планировщики).
    # Сам Web жив: гейт отдаёт аварийную страницу и health-check.
    if emergency_state():
        print(
            "[WEB] Аварийный режим: init/jobs/Telegram/планировщики пропущены",
            flush=True,
        )
        yield
        return

    # Self-restore reconcile: если предыдущий процесс погиб в окне остановки
    # сервиса (Web сам запускает восстановление установки), висящая операция
    # закрывается по state.json раннера. Обязан идти ДО updater, core jobs,
    # планировщиков и индексатора: до него maintenance-состояние могло
    # остаться от погибшего процесса, а задачи — увидеть ложный запрет.
    try:
        from core.backup.manager import BackupManager
        from core.backup.self_restore import (
            adopt_live_self_restores,
            reconcile_self_restores,
        )
        from core.config import get_backup_config

        self_restore_manager = BackupManager(get_backup_config())
        closed = reconcile_self_restores(self_restore_manager)
        for item in closed:
            print(
                "[WEB] self-restore reconcile: операция %s → %s"
                % (item.get("operation_id"), item.get("status")),
                flush=True,
            )
        # Живой раннер (сервис уже перезапущен им самим) не закрыт —
        # наблюдение обязан довести до конца ЭТОТ процесс, под owner-permit,
        # иначе reconcile_startup планировщика пометит операцию abandoned.
        adopted = adopt_live_self_restores(self_restore_manager)
        for item in adopted:
            print(
                "[WEB] self-restore adopt: операция %s наблюдается новым "
                "процессом" % item.get("operation_id"),
                flush=True,
            )
    except Exception as e:
        print(f"[WEB] self-restore reconcile failed: {e}", flush=True)

    # TLS provenance reconcile: веб-процесс перезапускается в середине
    # операции HTTPS; если раннер к этому моменту уже завершился (done),
    # применяем отложенный web.tls. Идёт ДО отдачи страниц: карточка
    # «Сеть и доступ» с первого запроса видит согласованное состояние.
    try:
        from core.web_tls import finalize_config

        finalize_config()
    except Exception as e:
        print(f"[WEB] TLS config finalize failed: {e}", flush=True)

    # Встроенный updater: локальный changelog + реконсиляция после restart
    try:
        from core.update.updater import init_on_startup
        await init_on_startup()
    except Exception as e:
        print(f"[WEB] update init failed: {e}", flush=True)

    # Ядерная JobQueue: фоновые задачи мониторинга (system_sync,
    # availability, SSL, updates) принадлежат ядру и стартуют вместе
    # с процессом — независимо от Telegram и открытых вкладок Web.
    try:
        from core.jobs_runtime import start_core_jobs
        await start_core_jobs()
    except Exception as e:
        print(f"[WEB] Core jobs start failed: {e}", flush=True)

    # Telegram (опционально: BOT_TOKEN пустой/заглушка — пропускаем)
    tg_app = None
    tg_retry_masterkey = False
    try:
        from core.secretbox import MasterKeyMissingError
        from bot import start_telegram, stop_telegram, BOT_TOKEN
        from core.config import get_telegram_config
        token = (BOT_TOKEN or "").strip()
        telegram_enabled = bool(get_telegram_config().get("enabled", True))
        if not telegram_enabled:
            print("[WEB] Telegram: выключен в настройках — бот не запущен", flush=True)
            from core.telegram_state import write_state

            write_state("disabled")
        elif not token or token.startswith("YOUR_"):
            print("[WEB] Telegram: token не задан — бот не запущен", flush=True)
            from core.telegram_state import write_state

            write_state("no_token")
        else:
            tg_app = await start_telegram()
    except MasterKeyMissingError as e:
        # Ключ может появиться позже (например, восстановят через CLI
        # bot4vps) — тогда watchdog ниже поднимет бота без рестарта.
        # mask_bot_token: текст исключения может нести сам токен.
        from core.telegram_health import mask_bot_token

        print(f"[WEB] Telegram start failed: {mask_bot_token(e)}", flush=True)
        tg_app = None
        tg_retry_masterkey = True
    except Exception as e:
        # Исключение PTB содержит токен («The token `…` was rejected») —
        # в journal пойдёт только маскированный текст.
        from core.telegram_health import mask_bot_token

        print(f"[WEB] Telegram start failed: {mask_bot_token(e)}", flush=True)
        tg_app = None

    inventory_indexer = None
    try:
        from core.backup.inventory_indexer import start_archive_inventory_indexer
        inventory_indexer = await start_archive_inventory_indexer()
    except Exception as e:
        print(f"[WEB] Backup inventory indexer start failed: {e}", flush=True)

    backup_scheduler = None
    backup_retry_masterkey = False
    try:
        from core.backup.scheduler import start_automatic_backup_scheduler
        from core.secretbox import MasterKeyMissingError
        backup_scheduler = await start_automatic_backup_scheduler()
    except MasterKeyMissingError as e:
        print(f"[WEB] Backup scheduler start failed: {e}", flush=True)
        backup_retry_masterkey = True
    except Exception as e:
        print(f"[WEB] Backup scheduler start failed: {e}", flush=True)

    key_registry_scheduler = None
    try:
        from core.quick_setup.registry_scheduler import start_key_registry_scheduler
        key_registry_scheduler = await start_key_registry_scheduler()
    except Exception as e:
        print(f"[WEB] Key registry scheduler start failed: {e}", flush=True)

    # Самовосстановление после появления мастер-ключа: если на старте
    # Telegram/бэкапы не поднялись из-за отсутствия ключа (а ключ потом
    # восстановили — например, через CLI bot4vps на этой же машине),
    # периодически проверяем ключ и поднимаем то, что ждёт. Работает без
    # рестарта сервиса; после успешного подъёма (или ошибки не про ключ)
    # соответствующая часть выключается из ожидания.
    async def _masterkey_watchdog():
        nonlocal tg_app, tg_retry_masterkey
        nonlocal backup_scheduler, backup_retry_masterkey
        from core.secretbox import master_key_state
        while tg_retry_masterkey or backup_retry_masterkey:
            await asyncio.sleep(10)
            try:
                if master_key_state() != "ok":
                    continue
            except Exception:
                continue
            if tg_retry_masterkey:
                try:
                    from bot import start_telegram
                    from core.config import get_telegram_config

                    if bool(get_telegram_config().get("enabled", True)):
                        tg_app = await start_telegram()
                        print(
                            "[WEB] Telegram: запущен после восстановления мастер-ключа",
                            flush=True,
                        )
                    tg_retry_masterkey = False
                except Exception as e:
                    from core.telegram_health import mask_bot_token

                    print(f"[WEB] Telegram retry failed: {mask_bot_token(e)}", flush=True)
                    tg_retry_masterkey = False
            if backup_retry_masterkey:
                try:
                    from core.backup.scheduler import (
                        start_automatic_backup_scheduler,
                    )

                    backup_scheduler = await start_automatic_backup_scheduler()
                    print(
                        "[WEB] Backup scheduler: запущен после восстановления мастер-ключа",
                        flush=True,
                    )
                except Exception as e:
                    print(f"[WEB] Backup scheduler retry failed: {e}", flush=True)
                backup_retry_masterkey = False

    masterkey_watchdog = None
    if tg_retry_masterkey or backup_retry_masterkey:
        masterkey_watchdog = asyncio.create_task(_masterkey_watchdog())

    try:
        yield
    finally:
        if masterkey_watchdog is not None:
            masterkey_watchdog.cancel()
        try:
            from core.jobs_runtime import stop_core_jobs
            await stop_core_jobs()
        except Exception as e:
            print(f"[WEB] Core jobs stop failed: {e}", flush=True)
        if key_registry_scheduler is not None:
            try:
                from core.quick_setup.registry_scheduler import stop_key_registry_scheduler
                await stop_key_registry_scheduler()
            except Exception as e:
                print(f"[WEB] Key registry scheduler stop failed: {e}", flush=True)
        if backup_scheduler is not None:
            try:
                from core.backup.scheduler import stop_automatic_backup_scheduler
                await stop_automatic_backup_scheduler()
            except Exception as e:
                print(f"[WEB] Backup scheduler stop failed: {e}", flush=True)
        if inventory_indexer is not None:
            try:
                from core.backup.inventory_indexer import stop_archive_inventory_indexer
                await stop_archive_inventory_indexer()
            except Exception as e:
                print(f"[WEB] Backup inventory indexer stop failed: {e}", flush=True)
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
# Куку Secure ставим, когда юнит слушает https сам (ssl) или терминирует
# реверс-прокси из trusted_proxies (proxy) — юнит здесь единственная правда
# о схеме: config после отката/restore может расходиться с реальностью.
# Смена схемы всегда сопровождается рестартом, поэтому чтения на старте
# достаточно (после scheme-переключения процесс поднимается заново).
from core.web_tls import unit_tls_state as _unit_tls_state  # noqa: E402

_tls_unit_state = _unit_tls_state()
_tls_https_only = _tls_unit_state["ssl"] or _tls_unit_state["proxy"]

app.add_middleware(
    SessionMiddleware,
    # Пустой secret_key бывает только в аварийном режиме (битый
    # config.json): load_config не смог прочитать настройки, и
    # ensure_web_secrets нечего гарантировать. Литерал здесь быть не
    # должен: известная строка = подпись, которой кука куется извне.
    # Аварийный гейт всё равно режет API до сессий, поэтому случайный
    # per-boot ключ ничего не ломает — но и предсказуемого секрета нет.
    secret_key=_web_cfg.get("secret_key") or secrets.token_urlsafe(32),
    session_cookie="bot4vps_sid",
    max_age=60 * 60 * 24 * 7,  # 7 дней
    same_site="lax",
    https_only=_tls_https_only,
)
# Аварийный гейт — ПОСЛЕДНИМ (в стеке Starlette выполняется первым):
# при повреждённом config.json все API, кроме статической страницы,
# статики и health, закрываются до сессий, CORS и роутеров.
app.add_middleware(EmergencyGateMiddleware)
# Гейт первичной настройки — ещё позже = ещё раньше в стеке: состояния
# мастера/заглушки закрывают API до того, как до них дойдёт очередь
# (сначала сам проверяет emergency, не читая config).
app.add_middleware(SetupGateMiddleware)

from .routers import meta, summary, servers, tasks, scripts, files, monitor, stream, terminal, services, system, update, backups, settings, quick_setup, masterkey, tls  # noqa: E402

app.mount("/static", NoCacheStaticFiles(directory=STATIC), name="static")

_AUTH = [Depends(require_auth)]

# Все /api-роутеры закрыты require_auth; login/me/logout/password/recover добавлены ниже напрямую.
app.include_router(meta.router, dependencies=_AUTH)
app.include_router(summary.router, dependencies=_AUTH)
app.include_router(system.router, dependencies=_AUTH)
app.include_router(servers.router, dependencies=_AUTH)
app.include_router(tasks.router, dependencies=_AUTH)
app.include_router(scripts.router, dependencies=_AUTH)
app.include_router(files.router, dependencies=_AUTH)
app.include_router(backups.router, dependencies=_AUTH)
app.include_router(monitor.router, dependencies=_AUTH)
app.include_router(stream.router, dependencies=_AUTH)
app.include_router(services.router, dependencies=_AUTH)
app.include_router(update.router, dependencies=_AUTH)
app.include_router(settings.router, dependencies=_AUTH)
app.include_router(tls.router, dependencies=_AUTH)
app.include_router(quick_setup.router, dependencies=_AUTH)
# Мастер-ключ: свои каналы подтверждения внутри (2FA/TG-код); весь
# роутер за require_auth — сессия обязательна для всех операций.
app.include_router(masterkey.router, dependencies=_AUTH)

# Health-check встроенного updater'а: без авторизации (его опрашивает runner
# после перезапуска, когда сессии ещё нет), но только с loopback.
app.include_router(update.health_router)

# WebSocket-терминал: авторизация проверяется внутри хендлера (по сессии в scope),
# т.к. router-level deps на WS работают ненадёжно.
app.include_router(terminal.router)


@app.get("/")
async def index():
    # Аварийный режим: автономная страница без config/темы/шаблонов
    if emergency_state():
        return HTMLResponse(
            _EMERGENCY_PAGE,
            status_code=503,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    index_file = STATIC / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>Нет static/index.html</h1>", status_code=500)
    return FileResponse(
        index_file,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


# ------------------------------------------------------------------
# Авторизация (эти эндпоинты — без require_auth)
# ------------------------------------------------------------------

class LoginBody(BaseModel):
    username: str
    password: str


class PasswordBody(BaseModel):
    old: str
    new: str


# ------------------------------------------------------------------
# Первичная настройка: мастер создания администратора (Этап 2).
#
# Мастер активен, пока действует код первичной установки (systemd
# drop-in, см. core/setup_code.py) И администратор не задан. Всё
# остальное в этом состоянии закрыто SetupGateMiddleware — независимо
# от auth_enabled. После создания админа код удаляется: второго
# «первого запуска» не бывает.
# ------------------------------------------------------------------

class SetupCompleteBody(BaseModel):
    username: str
    password: str
    code: str


# Перебор кода: не более N неудач за скользящее окно (образец —
# лимит попыток recovery-кодов ниже)
_SETUP_MAX_ATTEMPTS = 5
_SETUP_WINDOW_SECONDS = 300.0
_setup_failed_at: list[float] = []


@app.get("/api/setup/status")
async def api_setup_status():
    """Состояние входа для загрузки фронтенда (без авторизации).

    Подробности existing_installation отдаются ТОЛЬКО в закрытых
    режимах мастера/заглушки — обычный режим не раскрывает счётчик
    серверов незалогиненному посетителю.
    """
    from core.config import get_ui_theme

    theme = get_ui_theme()
    wizard = setup_wizard_active()
    expired = (not wizard) and setup_expired_active()
    stub = (not wizard) and (not expired) and login_stub_active()
    if not (wizard or expired or stub):
        return {"wizard": False, "stub": False, "theme": theme}

    servers = 0
    try:
        from core.storage import load_data

        servers = len(load_data().get("servers") or [])
    except Exception:
        servers = 0
    existing = servers > 0
    if not existing:
        from core.config import CONFIG_LATEST

        existing = CONFIG_LATEST.exists()
    return {
        "wizard": wizard,
        "expired": expired,
        "stub": stub,
        "theme": theme,
        "existing_installation": existing,
        "servers": servers,
    }


@app.post("/api/setup/complete")
async def api_setup_complete(body: SetupCompleteBody, request: Request):
    """Создать администратора по коду первичной установки.

    Сразу устанавливает сессию: пользователь только что сам задал
    логин и пароль — заставлять вводить их ещё раз на экране логина
    незачем. Фронт после ответа просто перезагружает страницу и
    попадает в панель. Если сессия по какой-то причине не встала
    (например, cookies отключены) — деградация мягкая: reload
    покажет обычный логин.
    """
    global _setup_failed_at
    if admin_exists():
        raise HTTPException(409, "Администратор уже задан")

    from core.setup_code import current_setup_code, remove_setup_code, setup_code_state

    code = current_setup_code()
    if not code:
        if setup_code_state()["expired"]:
            raise HTTPException(
                403,
                "Код первичной установки истёк (действует 10 минут) — "
                "перевыпустите его: bot4vps → Восстановление → "
                "Код первичной установки",
            )
        raise HTTPException(403, "Код первичной установки не выдан")

    # Скользящее окно неудачных попыток ввода кода
    now = time.monotonic()
    _setup_failed_at = [
        t for t in _setup_failed_at if now - t < _SETUP_WINDOW_SECONDS
    ]
    if len(_setup_failed_at) >= _SETUP_MAX_ATTEMPTS:
        raise HTTPException(
            429, "Слишком много неудачных попыток — подождите несколько минут"
        )

    if not hmac.compare_digest((body.code or "").strip(), code):
        _setup_failed_at.append(now)
        remaining = _SETUP_MAX_ATTEMPTS - len(_setup_failed_at)
        if remaining <= 0:
            raise HTTPException(
                429, "Слишком много неудачных попыток — подождите несколько минут"
            )
        raise HTTPException(400, f"Неверный код (осталось попыток: {remaining})")

    username = (body.username or "").strip()
    if not username:
        raise HTTPException(400, "Логин не может быть пустым")
    if len(username) > 64:
        raise HTTPException(400, "Логин не длиннее 64 символов")
    if len(body.password or "") < MIN_WEB_PASSWORD_LEN:
        raise HTTPException(400, f"Пароль не короче {MIN_WEB_PASSWORD_LEN} символов")

    # Атомарный патч секции web одной записью (внутри — ротация
    # страховки config.json, Этап 1)
    from core.config import get_web_config, set_web_config

    web = get_web_config()
    web["username"] = username
    web["password_hash"] = make_password(body.password)
    web["auth_enabled"] = True
    set_web_config(web)

    # Код отработал: drop-in удалён, env процесса очищен. Если удаление
    # вдруг не удалось — админ УЖЕ создан и записан, мастер закрыт через
    # admin_exists(), повторное использование кода невозможно (409).
    # Остаток кода на диске — вопрос консистентности очистки, не
    # безопасности: не роняем создание админа, пишем в журнал.
    try:
        remove_setup_code()
    except Exception as e:
        print(f"[WEB] Администратор создан, но код установки не удалён: {e}", flush=True)
    _setup_failed_at = []
    # Создание админа = первый вход (2FA у свежего админа нет)
    request.session["user"] = username
    print(f"[WEB] Создан администратор первичной настройки: {username}", flush=True)
    return {"ok": True}


@app.get("/api/me")
async def api_me(request: Request):
    # theme отдаём без авторизации: экран логина должен синхронизировать
    # тему сервера (источник истины) ещё до входа — иначе после сброса
    # кеша браузера он рисуется в дефолтной тёмной.
    from core.config import get_ui_theme
    theme = get_ui_theme()
    if not auth_enabled():
        return {"auth_enabled": False, "user": None, "theme": theme}
    return {"auth_enabled": True, "user": request.session.get("user"), "theme": theme}


# Rate-limit первого шага входа (логин+пароль): скользящее окно неудач
# на IP — 10 за 15 минут, затем 429 с Retry-After. Успешная проверка
# пароля сбрасывает счётчик. In-memory/один worker — как OTP-лимиты.
# IP берём из request.client: за доверенным proxy uvicorn уже подставил
# реальный клиентский адрес из X-Forwarded-For, заголовку от произвольного
# прямого клиента доверия нет.
_LOGIN_WINDOW = 15 * 60
_LOGIN_MAX_FAILURES = 10
_login_failures: dict[str, list[float]] = {}


def _login_wait_seconds(ip: str) -> int | None:
    """Сколько секунд IP ждать при исчерпании лимита (None = можно пробовать)."""
    now = time.monotonic()
    stamps = [t for t in _login_failures.get(ip, ()) if now - t < _LOGIN_WINDOW]
    _login_failures[ip] = stamps
    if len(stamps) >= _LOGIN_MAX_FAILURES:
        return max(1, int(_LOGIN_WINDOW - (now - stamps[0])))
    return None


def _login_register_failure(ip: str) -> None:
    _login_failures.setdefault(ip, []).append(time.monotonic())
    # Гигиена размера: чужие окна истекли — ключ больше не нужен.
    if len(_login_failures) > 1000:
        now = time.monotonic()
        for key in [k for k, v in _login_failures.items() if not v or now - v[-1] >= _LOGIN_WINDOW]:
            _login_failures.pop(key, None)


@app.post("/api/login")
async def api_login(request: Request, body: LoginBody):
    if not auth_enabled():
        return {"ok": True, "auth_enabled": False}
    ip = request.client.host if request.client else "unknown"
    wait = _login_wait_seconds(ip)
    if wait is not None:
        raise HTTPException(
            429,
            "Слишком много неудачных попыток входа с этого адреса — "
            "повторите через %d мин" % max(1, wait // 60),
            headers={"Retry-After": str(wait)},
        )
    from core.config import get_web_config
    web = get_web_config()
    if body.username == web.get("username") and verify_password(
        body.password, web.get("password_hash", "")
    ):
        _login_failures.pop(ip, None)
        if totp_enabled():
            # Пароль верен, но сессии ещё нет: ждём код из приложения.
            # Полусессия запрещена — до подтверждения OTP пользователь
            # для require_auth анонимен. Pending живёт 5 минут.
            global _pending_otp
            _pending_otp = {
                "username": body.username,
                "expires_at": time.monotonic() + _OTP_TTL_SECONDS,
                "attempts": 0,
            }
            return {"ok": False, "otp_required": True}
        request.session["user"] = body.username
        return {"ok": True, "user": body.username}
    _login_register_failure(ip)
    raise HTTPException(401, "Неверный логин или пароль")


class OtpBody(BaseModel):
    code: str


# Жизнь ожидания кода и лимит попыток ввода (6 цифр = 10⁶ комбинаций,
# поэтому 5 попыток и окно ±1 шаг 30 с — как у recovery-кода)
_OTP_TTL_SECONDS = 300.0
_OTP_MAX_ATTEMPTS = 5
# {username, expires_at, attempts} — одноразовый «пропуск» на второй шаг
_pending_otp: dict | None = None


@app.post("/api/login/otp")
async def api_login_otp(request: Request, body: OtpBody):
    """Шаг 2 входа при включённой 2FA: код из приложения-аутентификатора.

    Сессия создаётся ТОЛЬКО здесь: первый шаг сознательно без неё.
    """
    global _pending_otp
    if not auth_enabled():
        return {"ok": True, "auth_enabled": False}
    pending = _pending_otp
    if not pending or time.monotonic() > pending["expires_at"]:
        _pending_otp = None
        raise HTTPException(400, "Войдите заново: код не запрашивался или истёк")
    if pending["attempts"] >= _OTP_MAX_ATTEMPTS:
        _pending_otp = None
        raise HTTPException(400, "Попытки исчерпаны — войдите заново")

    secret = get_totp_secret()
    if not verify_totp_code(body.code, secret):
        pending["attempts"] += 1
        remaining = _OTP_MAX_ATTEMPTS - pending["attempts"]
        if remaining <= 0:
            _pending_otp = None
            raise HTTPException(400, "Неверный код. Попытки исчерпаны — войдите заново")
        raise HTTPException(400, f"Неверный код (осталось попыток: {remaining})")

    _pending_otp = None
    request.session["user"] = pending["username"]
    return {"ok": True, "user": pending["username"]}


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
    if len(body.new) < MIN_WEB_PASSWORD_LEN:
        raise HTTPException(400, f"Пароль не короче {MIN_WEB_PASSWORD_LEN} символов")
    set_web_password(body.new)
    return {"ok": True}


# ------------------------------------------------------------------
# Восстановление пароля через Telegram (тоже без require_auth — это путь
# «забыл пароль» на экране логина). Двухфазная схема:
#   1) POST /api/auth/recover        → в Telegram приходит код (10 минут),
#      старый пароль пока НЕ меняется — чужой запрос ничего не ломает;
#   2) POST /api/auth/recover/confirm {code, new_password} → код из TG
#      + новый пароль от пользователя: только теперь меняем пароль
#      и сразу логиним.
# ------------------------------------------------------------------

# Минимальная пауза между запросами кода — защита от спама
# незалогиненным посетителем в сторону Telegram API.
_RECOVER_COOLDOWN_SECONDS = 30.0
# Повторная отправка по кнопке «Не пришёл код»: раньше этого срока новый
# код бессмыслен (старый жив и мог просто задержаться в доставке).
_RECOVER_RESEND_AFTER_SECONDS = 120.0
_last_recover_at = 0.0

# Жизнь кода подтверждения и лимит попыток ввода
_RECOVERY_TTL_SECONDS = 600.0
_RECOVERY_MAX_ATTEMPTS = 5
# {code, expires_at, attempts} — код одноразовый, живёт до подтверждения
_pending_recovery: dict | None = None


def _recovery_available() -> bool:
    """Восстановление возможно, когда Telegram ВКЛЮЧЁН и настроен.

    Выключенный Telegram — осознанное решение владельца (бот не нужен
    или не работает): коды туда не отправляем, даже если токен и user_id
    сохранены. Доставку (когда включён) делает одноразовый Bot по
    сохранённому токену (см. _send_recovery_message), поэтому уйти код
    может и при остановленном боте. Прочее (нет токена/пользователя,
    недоступный мастер-ключ) — тоже недоступно; консольный путь всегда
    виден в окне восстановления.
    """
    from core.config import _read_config_raw, get_telegram_config
    try:
        raw = _read_config_raw()
    except Exception:
        raw = {}
    if "telegram_enabled" in raw and not raw["telegram_enabled"]:
        return False
    try:
        cfg = get_telegram_config()
    except Exception:
        return False
    return bool(cfg.get("token_set")) and cfg.get("user_id") is not None


def _recovery_unavailable_hint() -> str:
    """Подсказка для кнопки восстановления: почему TG недоступен."""
    from core.config import _read_config_raw
    try:
        raw = _read_config_raw()
    except Exception:
        raw = {}
    disabled = "telegram_enabled" in raw and not raw["telegram_enabled"]
    reason = (
        "Telegram выключен — отправка кодов отключена."
        if disabled
        else "Telegram не настроен — код доставить некому."
    )
    return (
        f"{reason} Восстановите пароль через консоль на сервере: "
        "bot4vps → 2. Безопасность → 3. Сменить пароль доступа."
    )


async def _send_recovery_message(text: str) -> None:
    """Отправить сообщение первому allowed-пользователю в Telegram.

    Используем работающего бота, если он запущен с тем же токеном;
    иначе поднимаем одноразовый Bot по сохранённому токену (как check_health).
    При ошибке доставки бросаем HTTPException(502).
    """
    import asyncio

    from core.config import get_saved_bot_token, get_telegram_config
    from core.telegram_health import classify_telegram_error, send_telegram_message

    cfg = get_telegram_config()
    chat_id = cfg.get("user_id")
    token = get_saved_bot_token()
    if not token or chat_id is None:
        raise HTTPException(400, "Telegram не настроен: восстановление недоступно")

    bot_obj = None
    owns_bot = False
    initialized = False
    try:
        try:
            from bot import get_application
            application = get_application()
        except Exception:
            application = None
        if application is not None and str(
            getattr(application.bot, "token", "") or ""
        ) == token:
            bot_obj = application.bot
            initialized = True
        else:
            from telegram import Bot

            bot_obj = Bot(token=token)
            owns_bot = True
            await asyncio.wait_for(bot_obj.initialize(), timeout=10)
            initialized = True
        await asyncio.wait_for(
            send_telegram_message(
                bot_obj, chat_id=chat_id, text=text, parse_mode="HTML"
            ),
            timeout=15,
        )
    except Exception as exc:
        # phase="token" — бот не поднялся (проблема с токеном),
        # phase="send" — поднялся, но доставка не прошла (чат и т.п.)
        result = classify_telegram_error(exc, phase="send" if initialized else "token")
        raise HTTPException(
            502, f"Не удалось отправить сообщение в Telegram: {result.reason}"
        )
    finally:
        if owns_bot and bot_obj is not None:
            try:
                await bot_obj.shutdown()
            except Exception:
                pass


@app.get("/api/auth/recover")
async def api_recover_status():
    """Кнопка «Восстановить пароль» видна всегда (когда включена авторизация).

    available = Telegram настроен (token + user_id): код доставит
    одноразовый Bot даже при остановленном боте. Если настроить нечего —
    frontend показывает подсказку про восстановление через консоль
    (bot4vps → Безопасность → Сменить пароль); она же всегда видна в окне."""
    if not auth_enabled():
        return {"available": False, "hint": None}
    if _recovery_available():
        return {"available": True, "hint": None}
    return {"available": False, "hint": _recovery_unavailable_hint()}


@app.post("/api/auth/recover")
async def api_recover_password():
    """Фаза 1: отправить код подтверждения в Telegram.

    Пароль НЕ меняется — чужой клик по кнопке на странице входа
    ничего не ломает, код просто истечёт.
    """
    global _last_recover_at, _pending_recovery
    if not auth_enabled():
        raise HTTPException(400, "Авторизация выключена")
    if not _recovery_available():
        raise HTTPException(400, _recovery_unavailable_hint())

    # Живой код уже отправлен (пользователь закрыл окно и вернулся):
    # НЕ отправляем новый и НЕ блокируем — переиспользуем pending.
    if _pending_recovery and time.monotonic() <= _pending_recovery["expires_at"]:
        return {"ok": True, "resent": False}
    return await _send_recovery_code()


async def _send_recovery_code() -> dict:
    """Реальная отправка нового TG-кода (первая или повторная по кнопке).

    Повторная стирает старый pending: в силе всегда ровно один код.
    Кулдаун 30 с между отправками (защита от спама кнопкой).
    """
    global _last_recover_at, _pending_recovery

    # Кулдаун — только на реальную повторную отправку в TG.
    now = time.monotonic()
    if now - _last_recover_at < _RECOVER_COOLDOWN_SECONDS:
        raise HTTPException(429, "Код уже отправлен — повторите чуть позже")
    _last_recover_at = now

    # 6 цифр, без ведущих нулей в уме: randbelow честно даёт 000000-999999
    code = f"{secrets.randbelow(1_000_000):06d}"
    text = (
        "🔐 <b>Восстановление доступа к панели Bot4VPS</b>\n\n"
        f"Код подтверждения: <code>{code}</code>\n"
        "Действует 10 минут.\n\n"
        "Введите код на экране входа вместе с новым паролем. "
        "Если вы не запрашивали восстановление — просто игнорируйте: "
        "пока код не введён, пароль не меняется."
    )
    await _send_recovery_message(text)
    # Pending сохраняем только после успешной доставки кода
    _pending_recovery = {
        "code": code,
        "expires_at": now + _RECOVERY_TTL_SECONDS,
        "attempts": 0,
    }
    return {"ok": True, "resent": True}


@app.post("/api/auth/recover/resend")
async def api_recover_resend():
    """«Не пришёл код? Отправить ещё раз» на экране входа.

    Доступна не раньше 2 минут после первой отправки: раньше нового кода
    ждать бессмысленно (старый жив 10 минут и мог задержаться в доставке).
    Новый код стирает старый pending.
    """
    global _pending_recovery
    if not auth_enabled():
        raise HTTPException(400, "Авторизация выключена")
    if not _recovery_available():
        raise HTTPException(400, _recovery_unavailable_hint())
    if not _pending_recovery or time.monotonic() > _pending_recovery["expires_at"]:
        _pending_recovery = None
        raise HTTPException(400, "Код ещё не отправлялся — начните восстановление заново")
    sent_at = _pending_recovery["expires_at"] - _RECOVERY_TTL_SECONDS
    if time.monotonic() - sent_at < _RECOVER_RESEND_AFTER_SECONDS:
        wait = int(_RECOVER_RESEND_AFTER_SECONDS - (time.monotonic() - sent_at))
        raise HTTPException(
            429, "Предыдущий код ещё актуален — новый можно запросить через %d с" % max(1, wait))
    return await _send_recovery_code()


class RecoverConfirmBody(BaseModel):
    code: str
    new_password: str


@app.post("/api/auth/recover/confirm")
async def api_recover_confirm(request: Request, body: RecoverConfirmBody):
    """Фаза 2: код из Telegram + новый пароль от пользователя.

    Код верен → меняем пароль и логиним сразу (уведомляем Telegram,
    пароль в сообщении не отправляем: пользователь задал его сам).
    Исключение — включённая 2FA: автологина нет, вход только через
    пароль + код из приложения (смена пароля не должна обходить 2FA).
    """
    global _pending_recovery
    if not auth_enabled():
        raise HTTPException(400, "Авторизация выключена")

    pending = _pending_recovery
    if not pending or time.monotonic() > pending["expires_at"]:
        _pending_recovery = None
        raise HTTPException(400, "Код не запрашивался или истёк — запросите заново")
    if pending["attempts"] >= _RECOVERY_MAX_ATTEMPTS:
        _pending_recovery = None
        raise HTTPException(400, "Попытки исчерпаны — запросите новый код")

    if body.code.strip() != pending["code"]:
        pending["attempts"] += 1
        remaining = _RECOVERY_MAX_ATTEMPTS - pending["attempts"]
        if remaining <= 0:
            _pending_recovery = None
            raise HTTPException(
                400, "Неверный код. Попытки исчерпаны — запросите новый код"
            )
        raise HTTPException(400, f"Неверный код (осталось попыток: {remaining})")

    if len(body.new_password) < MIN_WEB_PASSWORD_LEN:
        # Код верный, но пароль короткий: pending не жжём — можно исправить
        raise HTTPException(400, f"Пароль не короче {MIN_WEB_PASSWORD_LEN} символов")

    # Код подтверждён → одноразовый, меняем пароль и логиним
    _pending_recovery = None
    set_web_password(body.new_password)
    from core.config import get_web_config
    username = get_web_config().get("username", "admin")

    # При включённой 2FA автологина нет: смена пароля не должна обходить
    # второй фактор. Пользователь входит заново: пароль + код приложения.
    if totp_enabled():
        try:
            await _send_recovery_message(
                "🔐 <b>Пароль панели Bot4VPS изменён</b>\n\n"
                "Включена двухфакторная аутентификация: для входа "
                "по-прежнему нужен код из приложения-аутентификатора."
            )
        except HTTPException:
            pass
        return {"ok": True, "user": username, "otp_required": True}

    request.session["user"] = username

    # Уведомление best-effort: пароль уже сменён, сбой доставки TG
    # не должен ронять успешное восстановление
    try:
        await _send_recovery_message(
            "🔐 <b>Пароль панели Bot4VPS изменён</b>\n\n"
            "Новый пароль задан через восстановление (код из Telegram)."
        )
    except HTTPException:
        pass
    return {"ok": True, "user": username}


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
    return {
        "auth_enabled": bool(w.get("auth_enabled")),
        "username": w.get("username", "admin"),
        # Фронт по этому флагу показывает поле старого пароля: он нужен
        # при заданном пароле независимо от того, включена ли защита.
        "has_password": bool(w.get("password_hash")),
    }


@app.post("/api/auth/account")
async def api_account_set(request: Request, body: AccountBody):
    # В локальном режиме (auth off) пускаем; при включённой — только залогиненный.
    if auth_enabled() and not request.session.get("user"):
        raise HTTPException(401, "Требуется авторизация")

    from core.config import get_web_config, set_web_config
    w = get_web_config()

    if body.new_password is not None:
        # Старый пароль требуется всегда, когда пароль задан: при
        # выключенной защите панель открыта сети, и без этой проверки
        # любой мог бы подменить пароль и включить защиту (угон панели).
        if w.get("password_hash") and not verify_password(
            body.old or "", w.get("password_hash", "")
        ):
            raise HTTPException(400, "Старый пароль неверен")
        if len(body.new_password) < MIN_WEB_PASSWORD_LEN:
            raise HTTPException(400, f"Пароль не короче {MIN_WEB_PASSWORD_LEN} символов")
        w["password_hash"] = make_password(body.new_password)

    if body.username is not None:
        u = body.username.strip()
        if not u:
            raise HTTPException(400, "Логин не может быть пустым")
        w["username"] = u

    if body.auth_enabled is not None:
        # Включить защиту можно здесь; выключение срезает всю защиту
        # (и 2FA де-факто) и живёт в отдельном подтверждённом флоу
        # /api/auth/disable: старый пароль + код второго фактора.
        if not body.auth_enabled:
            raise HTTPException(
                400,
                "Выключение защиты входа требует подтверждения — "
                "используйте флоу отключения защиты",
            )
        if not w.get("password_hash"):
            raise HTTPException(400, "Сначала задайте пароль")
        w["auth_enabled"] = True
        # Включили защиту — текущая сессия сгорает: она могла остаться с
        # периода «выключено» (или вообще с чужого входа). Вход заново,
        # с паролем (и 2FA, если включена) — независимо от куки.
        request.session.clear()

    set_web_config(w)
    return {"ok": True, "auth_enabled": bool(w.get("auth_enabled")), "username": w.get("username")}


# ------------------------------------------------------------------
# Отключение защиты входа (auth off) — подтверждённая операция.
#
# Она срезает сразу всю защиту (пароль И 2FA де-факто), поэтому требует
# подтверждения владельца по образцу просмотра мастер-ключа: старый
# пароль + код второго фактора, если тот настроен (2FA из приложения
# приоритетно, код в Telegram — запасной; нет ни того, ни другого —
# пароль и есть подтверждение, он единственный фактор системы).
# Включение защиты ничего не срезает — обычный путь /api/auth/account.
# Аварийный путь при утере пароля — консоль (CLI), как и для 2FA.
# ------------------------------------------------------------------

# {channel: "totp"|"telegram", code?, expires_at, attempts} — ожидание
# кода второго фактора; одноразовое, живёт 10 минут.
_pending_disable: dict | None = None
_DISABLE_TTL_SECONDS = 600.0
_DISABLE_MAX_ATTEMPTS = 5
_DISABLE_COOLDOWN_SECONDS = 30.0
_DISABLE_RESEND_AFTER_SECONDS = 120.0
_last_disable_request_at = 0.0


def _disable_clean_expired() -> None:
    global _pending_disable
    if _pending_disable and _pending_disable.get("expires_at", 0.0) < time.monotonic():
        _pending_disable = None


class AuthDisableBody(BaseModel):
    old: str


@app.post("/api/auth/disable")
async def api_auth_disable(request: Request, body: AuthDisableBody):
    """Фаза 1: проверить старый пароль и выбрать канал подтверждения."""
    global _pending_disable, _last_disable_request_at
    if not auth_enabled():
        raise HTTPException(400, "Защита входа уже выключена")
    if not request.session.get("user"):
        raise HTTPException(401, "Требуется авторизация")

    # Брутфорс старого пароля делит окно с логином: тот же скользящий
    # лимит на IP, успех сбрасывает счётчик.
    ip = request.client.host if request.client else "unknown"
    wait = _login_wait_seconds(ip)
    if wait is not None:
        raise HTTPException(
            429,
            "Слишком много неудачных попыток с этого адреса — "
            "повторите через %d мин" % max(1, wait // 60),
            headers={"Retry-After": str(wait)},
        )

    from core.config import get_web_config, set_web_config
    web = get_web_config()
    if not verify_password(body.old, web.get("password_hash", "")):
        _login_register_failure(ip)
        raise HTTPException(400, "Старый пароль неверен")
    _login_failures.pop(ip, None)

    if totp_enabled():
        # Пароль проверен; вторым фактором станет код из приложения —
        # его введут в /disable/confirm. Ничего не отправляем.
        _pending_disable = {
            "channel": "totp",
            "expires_at": time.monotonic() + _DISABLE_TTL_SECONDS,
            "attempts": 0,
        }
        return {"ok": True, "channel": "totp"}

    if _recovery_available():
        # Telegram-канал: код доставки в TG. Живой код уже отправлен
        # (окно закрыли и вернулись) — не шлём новый, переиспользуем.
        _disable_clean_expired()
        if _pending_disable and _pending_disable.get("channel") == "telegram":
            return {"ok": True, "channel": "telegram", "resent": False}
        return await _send_disable_code()

    # Второго фактора нет: проверенный пароль — подтверждение владельца.
    web["auth_enabled"] = False
    set_web_config(web)
    return {"ok": True, "disabled": True, "channel": "password"}


async def _send_disable_code() -> dict:
    """Отправка TG-кода отключения (первая или повторная по кнопке).

    Повторная стирает старый pending: в силе всегда ровно один код.
    Кулдаун между отправками — защита от спама кнопкой.
    """
    global _pending_disable, _last_disable_request_at

    now = time.monotonic()
    if now - _last_disable_request_at < _DISABLE_COOLDOWN_SECONDS:
        raise HTTPException(429, "Код уже отправлен — повторите чуть позже")
    _last_disable_request_at = now
    code = f"{secrets.randbelow(1_000_000):06d}"
    text = (
        "🔓 <b>Отключение защиты входа Bot4VPS</b>\n\n"
        f"Код подтверждения: <code>{code}</code>\n"
        "Действует 10 минут.\n\n"
        "Если вы не запрашивали отключение — проигнорируйте сообщение: "
        "без кода защита не снимается."
    )
    try:
        await _send_recovery_message(text)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "Не удалось отправить код в Telegram") from exc
    _pending_disable = {
        "channel": "telegram",
        "code": code,
        "expires_at": time.monotonic() + _DISABLE_TTL_SECONDS,
        "attempts": 0,
    }
    return {"ok": True, "channel": "telegram", "resent": True}


@app.post("/api/auth/disable/resend")
async def api_auth_disable_resend():
    """«Не пришёл код? Отправить ещё раз» — осознанная повторная отправка.

    Не раньше _DISABLE_RESEND_AFTER_SECONDS после первой: раньше нового
    кода ждать бессмысленно (старый живёт 10 минут и мог задержаться).
    Новый код стирает старый pending.
    """
    _disable_clean_expired()
    pending = _pending_disable
    if not pending or pending.get("channel") != "telegram":
        raise HTTPException(400, "Код ещё не отправлялся — начните отключение заново")
    sent_at = pending["expires_at"] - _DISABLE_TTL_SECONDS
    if time.monotonic() - sent_at < _DISABLE_RESEND_AFTER_SECONDS:
        wait = int(_DISABLE_RESEND_AFTER_SECONDS - (time.monotonic() - sent_at))
        raise HTTPException(
            429, "Предыдущий код ещё актуален — новый можно запросить через %d с" % max(1, wait)
        )
    return await _send_disable_code()


class AuthDisableConfirmBody(BaseModel):
    code: str


@app.post("/api/auth/disable/confirm")
async def api_auth_disable_confirm(request: Request, body: AuthDisableConfirmBody):
    """Фаза 2: код 2FA или код из Telegram → защита снимается.

    Введённый код не логируется. Без живого pending операция невозможна:
    фаза 1 уже проверила старый пароль.
    """
    global _pending_disable
    if not auth_enabled():
        raise HTTPException(400, "Защита входа уже выключена")
    if not request.session.get("user"):
        raise HTTPException(401, "Требуется авторизация")

    _disable_clean_expired()
    pending = _pending_disable
    if not pending:
        raise HTTPException(400, "Отключение не начиналось или истёк — начните заново")

    if pending["channel"] == "totp":
        secret = get_totp_secret()
        if not secret or not verify_totp_code(body.code, secret):
            pending["attempts"] += 1
            remaining = _DISABLE_MAX_ATTEMPTS - pending["attempts"]
            if remaining <= 0:
                _pending_disable = None
                raise HTTPException(400, "Неверный код. Попытки исчерпаны — начните заново")
            raise HTTPException(400, f"Неверный код (осталось попыток: {remaining})")
    else:  # telegram
        if body.code.strip() != pending.get("code", ""):
            pending["attempts"] += 1
            remaining = _DISABLE_MAX_ATTEMPTS - pending["attempts"]
            if remaining <= 0:
                _pending_disable = None
                raise HTTPException(400, "Неверный код. Попытки исчерпаны — начните заново")
            raise HTTPException(400, f"Неверный код (осталось попыток: {remaining})")

    _pending_disable = None
    from core.config import get_web_config, set_web_config
    web = get_web_config()
    web["auth_enabled"] = False
    set_web_config(web)
    return {"ok": True, "disabled": True}


# ------------------------------------------------------------------
# Двухфакторная аутентификация (TOTP). Управление — из «Настроек → Web»,
# поэтому при включённой авторизации все эндпоинты требуют сессию.
#
# Включение в два шага: setup генерирует секрет (в config он НЕ пишется —
# живёт в pending 10 минут) и отдаёт QR + otpauth-URI; enable принимает
# код из приложения и только тогда активирует секрет. Отключение —
# только с действующим кодом (защита от «кликнул и снял фактор»).
# ------------------------------------------------------------------

# Секрет, ожидающий подтверждения кодом: {secret, expires_at}
_pending_totp_setup: dict | None = None
_TOTP_SETUP_TTL_SECONDS = 600.0


def _require_totp_session(request: Request) -> None:
    """TOTP-настройки доступны залогиненному (или любому при auth off —
    но тогда и 2FA включать бессмысленно, сразу отказываем)."""
    if not auth_enabled():
        raise HTTPException(400, "Авторизация выключена — 2FA не нужна")
    if not request.session.get("user"):
        raise HTTPException(401, "Требуется авторизация")


@app.get("/api/auth/totp")
async def api_totp_status(request: Request):
    _require_totp_session(request)
    return {"enabled": totp_enabled()}


@app.post("/api/auth/totp/setup")
async def api_totp_setup(request: Request):
    """Шаг 1 включения: новый секрет + QR. Активации ещё нет."""
    global _pending_totp_setup
    _require_totp_session(request)

    from core.config import get_web_config
    username = get_web_config().get("username", "admin")
    secret = make_totp_secret()
    uri = totp_provisioning_uri(secret, username)
    _pending_totp_setup = {
        "secret": secret,
        "expires_at": time.monotonic() + _TOTP_SETUP_TTL_SECONDS,
    }
    return {
        "secret": secret,
        "uri": uri,
        "qr": _totp_qr_data_url(uri),
    }


def _totp_qr_data_url(uri: str) -> str:
    """QR как data:image/png (qrcode[pil] уже в зависимостях — WireGuard)."""
    import base64
    import io

    try:
        import qrcode
    except ImportError:
        raise HTTPException(
            500, "На сервере не установлена библиотека qrcode. "
                 "Установите: pip install 'qrcode[pil]'"
        )
    img = qrcode.make(uri)
    bio = io.BytesIO()
    img.save(bio, "PNG")
    return "data:image/png;base64," + base64.b64encode(bio.getvalue()).decode()


class TotpCodeBody(BaseModel):
    code: str


@app.post("/api/auth/totp/enable")
async def api_totp_enable(request: Request, body: TotpCodeBody):
    """Шаг 2 включения: код из приложения подтверждает секрет."""
    global _pending_totp_setup
    _require_totp_session(request)

    pending = _pending_totp_setup
    if not pending or time.monotonic() > pending["expires_at"]:
        _pending_totp_setup = None
        raise HTTPException(400, "Настройка не начиналась или истекла — начните заново")
    if not verify_totp_code(body.code, pending["secret"]):
        raise HTTPException(400, "Неверный код — сверьте время в приложении и попробуйте ещё раз")

    _pending_totp_setup = None
    set_totp_secret(pending["secret"])
    return {"ok": True, "enabled": True}


@app.post("/api/auth/totp/disable")
async def api_totp_disable(request: Request, body: TotpCodeBody):
    """Отключение — только с действующим кодом из приложения."""
    _require_totp_session(request)

    if not totp_enabled():
        raise HTTPException(400, "Двухфакторная аутентификация не включена")
    if not verify_totp_code(body.code, get_totp_secret()):
        raise HTTPException(400, "Неверный код")
    clear_totp_secret()
    return {"ok": True, "enabled": False}
