from tzlocal import get_localzone

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
    Defaults
)

# Core
import core.scripts
from core.storage import ensure_server_ids
from core.config import load_config
from core.monitor import schedule_monitor_jobs
from core.event_types import EventType
from core.event_service import register_notifier
from core.upload import (
    process_upload_document,
    process_upload_callback,
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


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Единая точка входа для всех текстовых сообщений"""
    if await process_key_message(update, context):
        return
    if await process_script_message(update, context):
        return
    if await process_server_message(update, context):
        return
    await update.message.reply_text("❓ Не понял команду. Используй меню.")

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Единая точка входа для всех документов."""
    if await process_upload_document(update, context):
        return

    await update.message.reply_text(
        "❓ Этот файл сейчас не ожидается."
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await core_process_notifications(update, NOTIFICATION_HANDLERS)
    await show_main_menu(update)
# --------------------------------------------------
if __name__ == "__main__":
    ensure_server_ids()

    app = (
        Application.builder()
        .defaults(Defaults(tzinfo=get_localzone()))
        .token(BOT_TOKEN)
        .build()
    )

    # Ядро рассылает уведомления через notify_event(), не зная про Telegram:
    # здесь UI регистрирует свой отправщик в реестре event_service.
    async def _immediate_notify(notification, event_id=None):
        await send_event_notification(app.bot, notification, event_id)

    register_notifier(_immediate_notify)

    # Jobs
    schedule_monitor_jobs(app.job_queue)

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("🤖 Bot started with clean architecture", flush=True)
    app.run_polling()
