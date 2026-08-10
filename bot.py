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
from core.config import load_config
from core.monitor import schedule_monitor_jobs
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
    process_service_message,
    process_server_message,
)

# --------------------------------------------------
config = load_config()

BOT_TOKEN = config["bot_token"]
ALLOWED_USERS = config["allowed_users"]

NOTIFICATION_HANDLERS = {
    EventType.DATABASE.value: handle_critical_event,
    EventType.SSL.value: handle_critical_event,
    EventType.SERVER.value: handle_critical_event,
}

# Единый экземпляр Application (TG + Web в одном процессе)
_application: Application | None = None


def get_application() -> Application | None:
    """Текущий PTB Application (для reschedule monitor из Web и т.п.)."""
    return _application


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
    """Единая точка входа для всех документов."""
    if await process_upload_document(update, context):
        return
    await update.message.reply_text("❓ Этот файл сейчас не ожидается.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await core_process_notifications(update, NOTIFICATION_HANDLERS)
    await show_main_menu(update)


def build_application() -> Application:
    """Собрать Application с handlers (без start/polling)."""
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
        await send_event_notification(application.bot, notification, event_id)

    # replace=True — без дублей при reload
    register_notifier(_immediate_notify, replace=True)

    await application.initialize()
    if application.job_queue is not None:
        schedule_monitor_jobs(application.job_queue)
    else:
        print("[BOT] job_queue отсутствует — мониторинг не запланирован "
              "(нужен пакет python-telegram-bot[job-queue])", flush=True)

    await application.start()
    await application.updater.start_polling(drop_pending_updates=False)
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
    print("🤖 Telegram bot stopped", flush=True)


# --------------------------------------------------
if __name__ == "__main__":
    # Standalone (без Web): прежний путь run_polling
    ensure_server_ids()
    application = build_application()

    async def _immediate_notify(notification, event_id=None):
        await send_event_notification(application.bot, notification, event_id)

    register_notifier(_immediate_notify, replace=True)
    if application.job_queue is not None:
        # job_queue доступен после initialize; run_polling сам init'ит
        pass

    print("🤖 Bot standalone (run_polling) — для TG+Web используйте uvicorn ui.web.app:app", flush=True)

    # post_init: schedule jobs после initialize внутри run_polling
    async def _post_init(app: Application) -> None:
        if app.job_queue is not None:
            schedule_monitor_jobs(app.job_queue)

    application.post_init = _post_init
    application.run_polling()
