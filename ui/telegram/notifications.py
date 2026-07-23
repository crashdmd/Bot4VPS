from telegram import InlineKeyboardMarkup, InlineKeyboardButton

from core.notification_queue import (
    get_pending_notifications,
    mark_as_sent,
    mark_event_as_sent,
    clear_sent,
)
from core.event_types import EventReason


def format_event_text(notification: dict) -> str:
    """
    Единая точка оформления текста уведомления.
    """
    title = notification.get("title", "Событие")
    message = notification.get("message", "")
    details = notification.get("details") or notification.get("data") or {}
    source = details.get("source", "")
    reason = details.get("reason")
    level = notification.get("level", "critical")

    if reason in (
        EventReason.SERVER_ONLINE.value,
        EventReason.SSL_RENEWED.value,
    ):
        emoji = "✅"
    elif level == "critical":
        emoji = "🚨"
    elif level == "warning":
        emoji = "⚠️"
    else:
        emoji = "ℹ️"

    text = f"{emoji} {title}\n\n{message}"
    if source:
        text += f"\nИсточник: {source}"
    return text


def _menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main")]
    ])


async def send_event_notification(bot, notification: dict, event_id: str = None):
    """
    Отправляет уведомление всем allowed_users с кнопкой возврата в меню.
    Если передан event_id — сразу помечает элемент очереди как sent.
    """
    from core.config import load_config

    text = format_event_text(notification)
    keyboard = _menu_keyboard()
    config = load_config()
    allowed = config.get("allowed_users", [])

    for user_id in allowed:
        try:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=keyboard,
            )
        except Exception as e:
            print(f"[NOTIF] Не удалось отправить {user_id}: {e}", flush=True)

    if event_id:
        mark_event_as_sent(event_id)


async def process_notifications(update, notification_handlers: dict):
    """Обработка очереди уведомлений"""
    pending = get_pending_notifications()
    if not pending:
        return

    remaining = []
    for item in pending:
        handler = notification_handlers.get(item["type"])
        if not handler:
            remaining.append(item)
            continue
        try:
            if update and hasattr(update, "effective_chat") and update.effective_chat:
                processed = await handler(update, item)
            else:
                processed = False

            if processed:
                mark_as_sent(item["id"])
            else:
                remaining.append(item)
        except Exception as e:
            print(f"[NOTIF ERROR] {item['type']}: {e}", flush=True)
            remaining.append(item)

    if not remaining:
        clear_sent()


async def handle_critical_event(update, notification):
    """Обработчик событий из очереди"""
    text = format_event_text(notification)
    keyboard = _menu_keyboard()

    try:
        if update and hasattr(update, "effective_chat") and update.effective_chat:
            bot = update.get_bot()
            await bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                reply_markup=keyboard,
            )

        elif update and hasattr(update, "message") and update.message:
            await update.message.reply_text(text, reply_markup=keyboard)

        event_id = notification.get("event_id") or notification.get("id")
        if event_id:
            from core.events import mark_as_read
            mark_as_read(event_id)
            print(f"[NOTIF] Событие {event_id} отмечено как прочитанное", flush=True)

    except Exception as e:
        print(f"[NOTIF ERROR] {e}", flush=True)

    return True
