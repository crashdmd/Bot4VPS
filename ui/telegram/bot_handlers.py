import logging
from telegram import Update
from telegram.ext import ContextTypes

from core.auth import is_allowed
from core.event_types import EventType

from ui.telegram.notifications import (
    process_notifications as core_process_notifications,
    handle_critical_event,
)

NOTIFICATION_HANDLERS = {
    EventType.DATABASE.value: handle_critical_event,
    EventType.SSL.value: handle_critical_event,
    EventType.SERVER.value: handle_critical_event,
}

from ui.telegram.common import show_main_menu
from ui.telegram.handlers import (
    process_key_callback,
    process_script_callback,
    process_auth_callback,
    process_server_callback,
    process_admin_callback,
)

logger = logging.getLogger(__name__)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главный роутер callback-запросов."""
    query = update.callback_query
    await query.answer()

    print(f"[DEBUG] Button pressed. User: {query.from_user.id}, Data: {query.data}", flush=True)

    await core_process_notifications(update, NOTIFICATION_HANDLERS)

    if not is_allowed(query.from_user.id):
        await query.edit_message_text("⛔ Доступ запрещён.")
        return

    data = query.data

    if data == "main":
        await show_main_menu(query)
        return
    elif await process_auth_callback(query, data):
        return
    elif await process_server_callback(query, data):
        return
    elif await process_admin_callback(query, data, context):
        return
    elif await process_key_callback(query, data):
        return
    elif await process_script_callback(query, data):
        return
    else:
        await query.edit_message_text(f"❌ Неизвестная команда.\n\nCallback: {data}")
