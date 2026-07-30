from telegram import InlineKeyboardMarkup, InlineKeyboardButton


def build_main_menu():
    """Создаёт главное меню."""
    kb = [
        [InlineKeyboardButton("🖥 Серверы", callback_data="servers")],
        [InlineKeyboardButton("📋 Задачи", callback_data="tasks")],
        [InlineKeyboardButton("🛠 Администрирование", callback_data="admin")],
    ]
    return InlineKeyboardMarkup(kb)


async def show_main_menu(query_or_update):
    """Показывает главное меню."""
    text = "🏠 Bot4VPS\n\nВыберите действие:"

    try:
        if hasattr(query_or_update, "edit_message_text"):
            await query_or_update.edit_message_text(
                text,
                reply_markup=build_main_menu(),
            )
        elif hasattr(query_or_update, "message"):
            await query_or_update.message.reply_text(
                text,
                reply_markup=build_main_menu(),
            )
        else:
            await query_or_update.reply_text(
                text,
                reply_markup=build_main_menu(),
            )
    except Exception as e:
        print(f"[MENU ERROR] {e}", flush=True)
