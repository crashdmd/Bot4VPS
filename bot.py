from tzlocal import get_localzone

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
    Defaults,
)

# Core
import core.scripts  # noqa: F401 — register_executor
from core.storage import ensure_server_ids
from core.config import ConfigCorruptedError, load_config
from core.event_types import EventType
from core.event_service import register_notifier, clear_notifiers

from core.upload import (
    process_upload_document,
)

# UI
from ui.telegram.notifications import (
    process_notifications as core_process_notifications,
    handle_critical_event,
    send_event_notification,
)
from ui.telegram.bot_handlers import button
from ui.telegram.common import show_main_menu
from ui.telegram.handlers import (
    process_key_message,
    process_script_message,
    process_service_document,
    process_service_message,
    process_server_message,
)

# --------------------------------------------------
# Глобалы обновляются из config.json при старте/сохранении настроек.
BOT_TOKEN = ""
ALLOWED_USERS: list = []


def refresh_bot_globals() -> None:
    """Перечитать bot_token / allowed_users из config.json."""
    global BOT_TOKEN, ALLOWED_USERS
    from core.config import load_config, get_saved_bot_token
    cfg = load_config()
    # Токен на диске может быть зашифрован (enc1:) — читаем через
    # единственную точку с расшифровкой; дальше по коду plaintext.
    BOT_TOKEN = get_saved_bot_token()
    ALLOWED_USERS = list(cfg.get("allowed_users") or [])


# config.json повреждён без валидных копий: импорт bot НЕ падает —
# Web-вход обязан иметь возможность импортировать этот модуль даже в
# аварийном режиме (ui/web/app.py). Состояние фиксируем флагом; отказ
# происходит в build_application() при повторном чтении конфига, где
# его ловит обработчик настоящего __main__ (чистый выход, без трейсбека).
_CONFIG_CORRUPTED = False

try:
    refresh_bot_globals()
except ConfigCorruptedError:
    _CONFIG_CORRUPTED = True


NOTIFICATION_HANDLERS = {
    EventType.DATABASE.value: handle_critical_event,
    EventType.SSL.value: handle_critical_event,
    EventType.SERVER.value: handle_critical_event,
    EventType.TASK.value: handle_critical_event,
    EventType.BACKUP.value: handle_critical_event,
}

# Единый экземпляр Application (TG + Web в одном процессе)
_application: Application | None = None
# Последняя ошибка старта (для статуса в Web UI)
_last_start_error: str | None = None


def get_application() -> Application | None:
    """Текущий PTB Application (для reschedule monitor из Web и т.п.)."""
    return _application


def get_last_start_error() -> str | None:
    return _last_start_error


def _humanize_start_error(exc: BaseException) -> str:
    """Понятное сообщение для UI (невалидный токен и т.п.)."""
    name = type(exc).__name__
    msg = str(exc).strip() or name
    low = msg.lower()
    if "unauthorized" in low or name in ("InvalidToken", "Unauthorized"):
        return "невалидный Bot Token (Telegram отклонил авторизацию)"
    if "invalid token" in low or "token" in low and "invalid" in low:
        return "невалидный Bot Token"
    if "conflict" in low:
        return "конфликт getUpdates (бот уже запущен в другом процессе)"
    if "timed out" in low or "timeout" in low:
        return "таймаут связи с Telegram API"
    if "network" in low or "connect" in low:
        return f"сеть: {msg}"
    # коротко, без огромных traceback
    if len(msg) > 160:
        msg = msg[:157] + "..."
    return msg


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Единая точка входа для всех текстовых сообщений"""
    if await process_key_message(update, context):
        return
    if await process_script_message(update, context):
        return
    if await process_service_message(update, context):
        return
    if await process_server_message(update, context):
        return
    await update.message.reply_text("❓ Не понял команду. Используй меню.")


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Единая точка входа для всех документов.

    Сначала спрашиваем сервисные UI (Compose-проекты Docker и т.п.), затем —
    профильный загрузчик core/upload.py (скрипты).
    """
    if await process_service_document(update, context):
        return
    if await process_upload_document(update, context):
        return
    await update.message.reply_text("❓ Этот файл сейчас не ожидается.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await core_process_notifications(update, NOTIFICATION_HANDLERS)
    await show_main_menu(update)


def build_application() -> Application:
    """Собрать Application с handlers (без start/polling)."""
    refresh_bot_globals()
    if not BOT_TOKEN or BOT_TOKEN.startswith("YOUR_"):
        raise RuntimeError("Telegram bot_token не задан")
    app = (
        Application.builder()
        .defaults(Defaults(tzinfo=get_localzone()))
        .token(BOT_TOKEN)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    return app


async def start_telegram(app: Application | None = None) -> Application:
    """
    Ручной lifecycle PTB (для uvicorn lifespan).

    initialize → notifier → monitor jobs → start → start_polling
    Сигналы НЕ перехватываются — ими владеет uvicorn.
    """
    global _application
    ensure_server_ids()
    application = app or build_application()
    _application = application

    async def _immediate_notify(notification, event_id=None):
        return await send_event_notification(application.bot, notification, event_id)

    # replace=True — без дублей при reload
    register_notifier(_immediate_notify, replace=True)

    global _last_start_error
    try:
        await application.initialize()
        # Jobs мониторинга больше не планируются здесь: жизненным циклом
        # фоновых задач владеет ядро (core.jobs_runtime), стартует с любым
        # входом Bot4VPS независимо от Telegram. TG — только уведомления.
        await application.start()
        await application.updater.start_polling(drop_pending_updates=False)
    except Exception as e:
        # Провал старта — откат lifecycle, чтобы lifespan получил чистое
        # состояние: stop/shutdown каждого шага + clear_notifiers +
        # сброс _application. Исключение прокидывается для лога в lifespan.
        _last_start_error = _humanize_start_error(e)
        print(f"[BOT] start_telegram failed — rolling back: {_last_start_error}", flush=True)
        await stop_telegram(application)
        from core.telegram_state import write_state

        # после отката (stop_telegram пишет "stopped") фиксируем причину
        write_state("failed", error=_last_start_error)
        raise

    _last_start_error = None
    from core.telegram_state import write_state

    write_state("running")
    print("🤖 Telegram bot started (manual lifecycle)", flush=True)
    return application


async def stop_telegram(app: Application | None = None) -> None:
    """Корректный shutdown PTB."""
    global _application
    application = app or _application
    if application is None:
        return
    try:
        if application.updater and application.updater.running:
            await application.updater.stop()
    except Exception as e:
        print(f"[BOT] updater.stop: {e}", flush=True)
    try:
        if application.running:
            await application.stop()
    except Exception as e:
        print(f"[BOT] stop: {e}", flush=True)
    try:
        await application.shutdown()
    except Exception as e:
        print(f"[BOT] shutdown: {e}", flush=True)
    clear_notifiers()
    _application = None
    from core.telegram_state import write_state

    write_state("stopped")
    print("🤖 Telegram bot stopped", flush=True)


async def restart_telegram() -> Application:
    """Остановить (если запущен) и запустить заново с актуальным токеном."""
    await stop_telegram()
    return await start_telegram()


def is_telegram_running() -> bool:
    app = _application
    if app is None:
        return False
    try:
        return bool(app.running and app.updater and app.updater.running)
    except Exception:
        return False


# --------------------------------------------------
if __name__ == "__main__":
    # Standalone (без Web): прежний путь run_polling
    ensure_server_ids()
    # Консольная команда bot4vps — часть ui/cli; tg-only вход тоже
    # гарантирует её наличие (обновление/перенос/восстановление).
    try:
        from ui.cli.bootstrap import ensure_cli_command
        ensure_cli_command()
    except Exception as exc:
        print(f"[BOT] cli command ensure failed: {exc}", flush=True)

    # Повреждённый config.json без валидных копий: tg-only вход не может
    # подняться (боту нужен токен из конфига). Чистый выход с понятным
    # сообщением, без трейсбека; Web-вход в этом состоянии живёт в
    # аварийном режиме (ui/web/app.py).
    try:
        application = build_application()
    except ConfigCorruptedError as exc:
        import sys

        print(f"[BOT] АВАРИЙНЫЙ РЕЖИМ: {exc}", flush=True)
        print(
            "[BOT] Восстановите конфигурацию: "
            "cp backup/config_latest.json config.json && systemctl restart bot4vps",
            flush=True,
        )
        sys.exit(1)

    async def _immediate_notify(notification, event_id=None):
        return await send_event_notification(application.bot, notification, event_id)

    register_notifier(_immediate_notify, replace=True)

    print("🤖 Bot standalone (run_polling) — для TG+Web используйте uvicorn ui.web.app:app", flush=True)

    # post_init: ядерная JobQueue (собственность ядра, не TG) + backup-scheduler
    async def _post_init(app: Application) -> None:
        # tg-only вход идёт через run_polling, минуя start_telegram —
        # состояние lifecycle пишем здесь (тот же переход "running")
        from core.telegram_state import write_state

        write_state("running")
        # Self-restore reconcile: восстановленный юнит может быть tg-only —
        # тогда финализацию висящей операции делает этот процесс, а не Web.
        # До core jobs и планировщика (см. тот же hook в ui/web/app.py).
        try:
            from core.backup.manager import BackupManager
            from core.backup.self_restore import reconcile_self_restores
            from core.config import get_backup_config

            for item in reconcile_self_restores(
                BackupManager(get_backup_config())
            ):
                print(
                    "[BOT] self-restore reconcile: операция %s → %s"
                    % (item.get("operation_id"), item.get("status")),
                    flush=True,
                )
        except Exception as exc:
            print(f"[BOT] self-restore reconcile failed: {exc}", flush=True)
        try:
            from core.jobs_runtime import start_core_jobs
            await start_core_jobs()
        except Exception as exc:
            print(f"[BOT] Core jobs start failed: {exc}", flush=True)
        try:
            from core.backup.scheduler import start_automatic_backup_scheduler
            await start_automatic_backup_scheduler()
        except Exception as exc:
            print(f"[BOT] Backup scheduler start failed: {exc}", flush=True)

    async def _post_shutdown(app: Application) -> None:
        del app
        from core.telegram_state import write_state

        write_state("stopped")
        try:
            from core.jobs_runtime import stop_core_jobs
            await stop_core_jobs()
        except Exception as exc:
            print(f"[BOT] Core jobs stop failed: {exc}", flush=True)
        try:
            from core.backup.scheduler import stop_automatic_backup_scheduler
            await stop_automatic_backup_scheduler()
        except Exception as exc:
            print(f"[BOT] Backup scheduler stop failed: {exc}", flush=True)

    application.post_init = _post_init
    application.post_shutdown = _post_shutdown
    application.run_polling()
