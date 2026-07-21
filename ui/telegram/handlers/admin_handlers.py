"""
Admin handlers module for Bot4VPS.
"""

from telegram import InlineKeyboardMarkup, InlineKeyboardButton
import asyncio

from core.events import get_events
from ui.telegram.handlers.check_handlers import process_check_callback

async def _show_admin_menu(query):
    keyboard = [
        [InlineKeyboardButton("🔍 Проверить серверы", callback_data="check_servers_menu")],
        [InlineKeyboardButton("📜 Просмотр уведомлений", callback_data="view_notifications")],
        [InlineKeyboardButton("🔑 Управление SSH-ключами", callback_data="key_manager")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main")]
    ]
    await query.edit_message_text(
        "🛠 Администрирование\n\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _clear_events_confirm(query):
    """Подтверждение очистки"""
    keyboard = [
        [InlineKeyboardButton("✅ Да, очистить", callback_data="clear_events_confirm")],
        [InlineKeyboardButton("❌ Отмена", callback_data="view_notifications")]
    ]
    await query.edit_message_text(
        "⚠️ Вы действительно хотите очистить весь журнал событий?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _clear_events(query):
    """Фактическая очистка"""
    from core.events import load_events, save_events
   
    events = load_events()
    count = len(events)
    
    if count == 0:
        await query.edit_message_text("Журнал уже пуст.")
        return

    save_events([])

    await query.edit_message_text(
        f"✅ Журнал событий очищен.\nУдалено записей: {count}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад в админку", callback_data="admin")
        ]])
    )

async def _view_notifications(query):
    """Просмотр уведомлений + кнопка очистки"""
    events = get_events(limit=30)

    if not events:
        await query.edit_message_text(
            "📭 Уведомлений пока нет.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="admin")
            ]])
        )
        return

    text = "📜 Журнал событий (последние 15)\n\n"
    for e in events[:15]:
        emoji = "🔴" if e["level"] == "critical" else "⚠️" if e["level"] == "warning" else "ℹ️"
        text += f"{emoji} {e['title']}\n   {e['timestamp'][:16]}\n\n"

    keyboard = [
        [InlineKeyboardButton("🗑 Очистить весь журнал", callback_data="clear_events")],
        [InlineKeyboardButton("⬅️ Назад в админку", callback_data="admin")]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def process_admin_callback(query, data: str) -> bool:
    if data == "admin":
        await _show_admin_menu(query)

    elif await process_check_callback(query, data):
        return True

    elif data == "view_notifications":
        await _view_notifications(query)

    elif data == "clear_events":
        await _clear_events_confirm(query)

    elif data == "clear_events_confirm":
        await _clear_events(query)

    else:
        return False

    return True
