from telegram import InlineKeyboardMarkup, InlineKeyboardButton

def build_main_menu():
    """Создаёт главное меню."""
    kb = [
        [InlineKeyboardButton("🖥 Серверы", callback_data="servers")],
        [InlineKeyboardButton("📜 Скрипты", callback_data="scripts")],
        [InlineKeyboardButton("🛠 Администрирование", callback_data="admin")]
    ]
    return InlineKeyboardMarkup(kb)


async def show_main_menu(query_or_update):
    """Показывает главное меню."""
    text = "🏠 Bot4VPS\n\nВыберите действие:"

    try:
        # Если вызов из callback-кнопки
        if hasattr(query_or_update, "edit_message_text"):
            await query_or_update.edit_message_text(
                text,
                reply_markup=build_main_menu()
            )

        # Если вызов из команды /start (Update)
        elif hasattr(query_or_update, "message"):
            await query_or_update.message.reply_text(
                text,
                reply_markup=build_main_menu()
            )

        # Если вдруг передали Message напрямую
        else:
            await query_or_update.reply_text(
                text,
                reply_markup=build_main_menu()
            )

    except Exception as e:
        print(f"[MENU ERROR] {e}", flush=True)