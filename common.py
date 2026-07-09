from telegram import InlineKeyboardMarkup, InlineKeyboardButton


def is_allowed(user_id):
    import json
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    ALLOWED_USERS = config["allowed_users"]
    return user_id in ALLOWED_USERS


def build_main_menu():
    kb = [
        [InlineKeyboardButton("🖥 Серверы", callback_data="servers")],
        [InlineKeyboardButton("📜 Скрипты", callback_data="scripts")],
        [InlineKeyboardButton("🛠 Администрирование", callback_data="admin")]
    ]
    return InlineKeyboardMarkup(kb)


async def show_main_menu(query_or_update):
    text = "🏠 Bot4VPS\n\nВыберите действие:"
    try:
        if hasattr(query_or_update, "edit_message_text"):
            await query_or_update.edit_message_text(text, reply_markup=build_main_menu())
        else:
            await query_or_update.message.edit_message_text(text, reply_markup=build_main_menu())
    except Exception:
        if hasattr(query_or_update, "message"):
            await query_or_update.message.reply_text(text, reply_markup=build_main_menu())
        else:
            await query_or_update.reply_text(text, reply_markup=build_main_menu())