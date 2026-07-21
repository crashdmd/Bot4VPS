import json
import asyncio
from datetime import time
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
from core.storage import ensure_server_ids
from core.monitor import run_daily_monitor
from core.event_service import create_event
from core.event_types import EventType, EventLevel, EventReason

# UI
from ui.telegram.notifications import (
    process_notifications as core_process_notifications,
    handle_critical_event,
)
from ui.telegram.bot_handlers import button
from ui.telegram.common import build_main_menu, show_main_menu
from ui.telegram.handlers import (
    process_key_callback,
    process_script_callback,
    process_auth_callback,
    process_server_callback,
    process_admin_callback,
    process_key_message,
    process_script_message,
    process_server_message,
)

# --------------------------------------------------
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

BOT_TOKEN = config["bot_token"]
ALLOWED_USERS = config["allowed_users"]


NOTIFICATION_HANDLERS = {
    EventType.DATABASE.value: handle_critical_event,
    EventType.SSL.value: handle_critical_event,
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await core_process_notifications(update, NOTIFICATION_HANDLERS)
    await show_main_menu(update)

async def daily_ssl_job(context):
    """Ежедневный SSL-мониторинг"""

    events = run_daily_monitor()

    if not events:
        return

    for event in events:

        if event["event"] == "renewed":
            create_event(
                event_type=EventType.SSL,
                level=EventLevel.INFO,
                title="SSL сертификат обновлён",
                message=(
                    f"Сертификат сервера "
                    f"«{event['server_name']}» успешно обновлён."
                ),
                details={
                    **event,
                    "reason": EventReason.SSL_RENEWED.value,
                },
                notify=True,
            )

        elif event["event"] == "expired":
            create_event(
                event_type=EventType.SSL,
                level=EventLevel.CRITICAL,
                title="SSL сертификат истёк",
                message=(
                    f"Сертификат сервера "
                    f"«{event['server_name']}» истёк."
                ),
                details={
                    **event,
                    "reason": EventReason.SSL_EXPIRED.value,
                },
            )

# --------------------------------------------------
if __name__ == "__main__":
    ensure_server_ids()

    app = Application.builder().defaults(
        Defaults(tzinfo=get_localzone())
    ).token(BOT_TOKEN).build()

    # Jobs
    app.job_queue.run_daily(daily_ssl_job, time=time(hour=6))

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("🤖 Bot started with clean architecture", flush=True)
    app.run_polling()