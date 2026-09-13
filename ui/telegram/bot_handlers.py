import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from core.auth import is_allowed
from core.telegram_health import TEST_MESSAGE_OK_CALLBACK
from core.upload import process_upload_callback

from ui.telegram.notifications import (
    mark_message_event_read,
    process_notification_digest_callback,
)

from ui.telegram.common import show_main_menu
from ui.telegram.handlers import (
    process_key_callback,
    process_script_callback,
    process_auth_callback,
    process_server_callback,
    process_admin_callback,
    process_service_callback,
    process_task_callback,
    process_backup_callback,
)

logger = logging.getLogger(__name__)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главный роутер callback-запросов."""
    query = update.callback_query
    try:
        await query.answer()
    except BadRequest:
        # Query is too old / already answered — игнорируем
        pass

    logger.debug(
        "Button pressed. User=%s, Data=%s",
        query.from_user.id,
        query.data,
    )

    # Накопленные уведомления доставляет фоновый дрейн ядра
    # (notifications.drain_pending_notifications, раз в 5с) — кнопки к
    # доставке больше не имеют отношения.
    if not is_allowed(query.from_user.id):
        await query.edit_message_text("⛔ Доступ запрещён.")
        return

    # Кнопка на живом сообщении-уведомлении: закрывает аккумулятор любая,
    # а помечает ли события прочитанными — решает mark_message_event_read
    # по кнопке (навигация и «Главное меню» под сводкой — нет, «✅ Прочитано»
    # и любые кнопки одиночного сообщения — да). Сообщения вне
    # аккумулятора — no-op.
    data = query.data
    pressed_message = query.message
    if pressed_message is not None:
        try:
            await asyncio.to_thread(
                mark_message_event_read,
                pressed_message.chat_id,
                pressed_message.message_id,
                action=data,
            )
        except Exception as exc:
            logger.debug("mark_message_event_read failed: %s", exc)

    # Кнопка [ОК] под тестовым сообщением проверки Telegram возвращает в
    # главное меню тем же механизмом, что и обычный callback "main".
    if data == "main" or data == TEST_MESSAGE_OK_CALLBACK:
        await show_main_menu(query)
        return
    elif await process_upload_callback(query, data):
        return
    elif await process_auth_callback(query, data):
        return
    elif await process_server_callback(query, data):
        return
    elif await process_admin_callback(query, data, context):
        return
    elif await process_backup_callback(query, data, context):
        return
    elif await process_notification_digest_callback(query, data):
        return
    elif await process_key_callback(query, data):
        return
    elif await process_service_callback(query, data):
        return
    elif await process_task_callback(query, data):
        return
    elif await process_script_callback(query, data):
        return
    else:
        await query.edit_message_text(f"❌ Неизвестная команда.\n\nCallback: {data}")
