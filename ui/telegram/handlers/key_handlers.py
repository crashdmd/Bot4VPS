"""
Key handlers module for Bot4VPS.

Публичный интерфейс модуля — только одна функция:
    process_key_callback(query, data) -> bool

Все остальные функции — внутренние (начинаются с _ ).
bot_handlers.py ничего не знает о внутреннем устройстве модуля.
"""

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

import os
import subprocess

# from ui.telegram.keyboards import CANCEL_KB  # unused
from state import KEY_CREATE_STATE, KEY_RENAME_STATE, KEY_REPLACE_STATE, KEY_PASTE_NEW_STATE


async def _show_key_manager(query):
    """Show list of available SSH private keys in /opt/bot4vps/keys"""
    keys_dir = "/opt/bot4vps/keys"
    keyboard = []

    if os.path.exists(keys_dir):
        all_files = os.listdir(keys_dir)
        private_keys = [
            f for f in all_files
            if os.path.isfile(os.path.join(keys_dir, f)) and not f.endswith(".pub")
        ]

        for key_name in sorted(private_keys):
            size = os.path.getsize(os.path.join(keys_dir, key_name))
            keyboard.append([
                InlineKeyboardButton(f"🔑 {key_name} ({size} байт)", callback_data=f"key_action:{key_name}")
            ])

    # Bottom buttons
    keyboard.append([InlineKeyboardButton("➕ Создать новый ключ", callback_data="key_create")])
    keyboard.append([InlineKeyboardButton("📥 Вставить существующий ключ", callback_data="key_paste_new")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin")])

    await query.edit_message_text(
        "🔑 Управление SSH-ключами\n\nВыберите ключ или создайте новый:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _show_key_action(query, key_name):
    keyboard = [
        [InlineKeyboardButton("✏️ Переименовать", callback_data=f"key_rename:{key_name}")],
        [InlineKeyboardButton("🔄 Заменить ключ", callback_data=f"key_replace:{key_name}")],
        [InlineKeyboardButton("📋 Показать приватный ключ", callback_data=f"key_view_priv:{key_name}")],
        [InlineKeyboardButton("🗑 Удалить ключ", callback_data=f"key_delete:{key_name}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="key_manager")]
    ]

    await query.edit_message_text(
        f"🔑 Ключ: `{key_name}`\n\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def _confirm_key_delete(query, key_name):
    keyboard = [
        [InlineKeyboardButton("✅ Да, удалить", callback_data=f"key_delete_confirm:{key_name}")],
        [InlineKeyboardButton("❌ Отмена", callback_data=f"key_action:{key_name}")]
    ]

    await query.edit_message_text(
        f"⚠️ Удалить ключ `{key_name}` и его публичный ключ?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _delete_ssh_key_confirm(query, key_name):
    keys_dir = "/opt/bot4vps/keys"
    key_path = os.path.join(keys_dir, key_name)
    pub_key_path = key_path + ".pub"

    try:
        if os.path.exists(key_path):
            os.remove(key_path)
        if os.path.exists(pub_key_path):
            os.remove(pub_key_path)

        await query.edit_message_text(
            f"✅ Ключ `{key_name}` и его публичный ключ удалены.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад к ключам", callback_data="key_manager")
            ]])
        )
    except Exception as e:
        await query.edit_message_text(
            f"❌ Ошибка при удалении ключа:\n{e}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад к ключам", callback_data="key_manager")
            ]])
        )


async def _finish_key_creation(message, user_id, key_name):
    """Called from MessageHandler when user enters key name for creation"""
    keys_dir = "/opt/bot4vps/keys"
    os.makedirs(keys_dir, exist_ok=True)

    key_path = os.path.join(keys_dir, key_name)

    if os.path.exists(key_path):
        await message.reply_text(
            f"❌ Ключ с именем `{key_name}` уже существует.\n\n"
            "Введите другое имя:"
        )
        return

    try:
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-f", key_path, "-N", ""],
            check=True,
            capture_output=True
        )

        pub_key_path = key_path + ".pub"
        with open(pub_key_path, "r") as f:
            pub_key = f.read().strip()

        if user_id in KEY_CREATE_STATE:
            del KEY_CREATE_STATE[user_id]

        keyboard = [
            [InlineKeyboardButton("⬅️ Назад к ключам", callback_data="key_manager")]
        ]

        await message.reply_text(
            f"✅ Ключ `{key_name}` успешно создан!\n\n"
            f"**Публичный ключ** (добавь его на сервер):\n\n"
            f"`{pub_key}`",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    except Exception as e:
        if user_id in KEY_CREATE_STATE:
            del KEY_CREATE_STATE[user_id]
        await message.reply_text(
            f"❌ Ошибка при создании ключа:\n{e}"
        )


async def _finish_key_rename(message, user_id, old_key_name, new_key_name):
    """Called from MessageHandler for key rename input"""
    keys_dir = "/opt/bot4vps/keys"
    old_path = os.path.join(keys_dir, old_key_name)
    new_path = os.path.join(keys_dir, new_key_name)
    old_pub = old_path + ".pub"
    new_pub = new_path + ".pub"

    if os.path.exists(new_path):
        await message.reply_text(
            f"❌ Ключ с именем `{new_key_name}` уже существует."
        )
        return

    try:
        os.rename(old_path, new_path)
        if os.path.exists(old_pub):
            os.rename(old_pub, new_pub)

        if user_id in KEY_RENAME_STATE:
            del KEY_RENAME_STATE[user_id]

        await message.reply_text(
            f"✅ Ключ переименован:\n`{old_key_name}` → `{new_key_name}`",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад к ключам", callback_data="key_manager")
            ]])
        )
    except Exception as e:
        if user_id in KEY_RENAME_STATE:
            del KEY_RENAME_STATE[user_id]
        await message.reply_text(
            f"❌ Ошибка при переименовании:\n{e}"
        )


async def _start_key_replace(query, key_name):
    from state import KEY_REPLACE_STATE
    KEY_REPLACE_STATE[query.from_user.id] = key_name
    await query.edit_message_text(
        f"Вставьте новый приватный ключ для `{key_name}`:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="key_manager")]])
    )


async def _finish_key_replace(message, user_id, key_name, new_content):
    keys_dir = "/opt/bot4vps/keys"
    key_path = os.path.join(keys_dir, key_name)

    try:
        with open(key_path, "w", encoding="utf-8") as f:
            f.write(new_content.strip())

        if user_id in KEY_REPLACE_STATE:
            del KEY_REPLACE_STATE[user_id]

        await message.reply_text(
            f"✅ Ключ `{key_name}` успешно заменён.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад к ключам", callback_data="key_manager")
            ]])
        )
    except Exception as e:
        if user_id in KEY_REPLACE_STATE:
            del KEY_REPLACE_STATE[user_id]
        await message.reply_text(
            f"❌ Ошибка при замене ключа:\n{e}"
        )


async def _start_key_paste_new(query):
    from state import KEY_PASTE_NEW_STATE
    KEY_PASTE_NEW_STATE[query.from_user.id] = {}
    await query.edit_message_text(
        "Введите имя для нового ключа:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="key_manager")]])
    )


async def _finish_key_paste_new(message, user_id, key_name, key_content):
    keys_dir = "/opt/bot4vps/keys"
    key_path = os.path.join(keys_dir, key_name)

    if os.path.exists(key_path):
        await message.reply_text(
            f"❌ Ключ с именем `{key_name}` уже существует."
        )
        if user_id in KEY_PASTE_NEW_STATE:
            del KEY_PASTE_NEW_STATE[user_id]
        return

    try:
        with open(key_path, "w", encoding="utf-8") as f:
            f.write(key_content.strip())

        if user_id in KEY_PASTE_NEW_STATE:
            del KEY_PASTE_NEW_STATE[user_id]

        await message.reply_text(
            f"✅ Ключ `{key_name}` успешно вставлен.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад к ключам", callback_data="key_manager")
            ]])
        )
    except Exception as e:
        if user_id in KEY_PASTE_NEW_STATE:
            del KEY_PASTE_NEW_STATE[user_id]
        await message.reply_text(
            f"❌ Ошибка при вставке ключа:\n{e}"
        )


async def _view_private_key(query, key_name):
    keys_dir = "/opt/bot4vps/keys"
    key_path = os.path.join(keys_dir, key_name)

    if not os.path.exists(key_path):
        await query.edit_message_text("❌ Приватный ключ не найден.")
        return

    with open(key_path, "r") as f:
        private_key = f.read().strip()

    keyboard = [[
        InlineKeyboardButton("⬅️ Назад", callback_data=f"key_action:{key_name}")
    ]]

    await query.edit_message_text(
        f"⚠️ **Приватный ключ** `{key_name}` (скопируй и храни в безопасном месте):\n\n"
        f"```\n{private_key}\n```",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


# === Публичная точка входа модуля ===
async def process_key_callback(query, data: str) -> bool:
    """
    Единая публичная функция модуля.
    bot_handlers.py вызывает только её.

    Returns True если callback обработан этим модулем.
    """
    if data == "key_manager":
        await _show_key_manager(query)
    elif data == "key_create":
        KEY_CREATE_STATE[query.from_user.id] = {}
        await query.message.reply_text(
            "Введите имя нового ключа (например: vps1, home, github):",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data="key_manager")
            ]])
        )
    elif data.startswith("key_action:"):
        key_name = data.split(":", 1)[1]
        await _show_key_action(query, key_name)
    elif data.startswith("key_delete:"):
        key_name = data.split(":", 1)[1]
        await _confirm_key_delete(query, key_name)
    elif data.startswith("key_delete_confirm:"):
        key_name = data.split(":", 1)[1]
        await _delete_ssh_key_confirm(query, key_name)
    elif data.startswith("key_rename:"):
        old_key_name = data.split(":", 1)[1]
        KEY_RENAME_STATE[query.from_user.id] = old_key_name
        await query.edit_message_text(
            f"Введите новое имя для ключа `{old_key_name}`:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data="key_manager")
            ]])
        )
    elif data.startswith("key_replace:"):
        key_name = data.split(":", 1)[1]
        await _start_key_replace(query, key_name)
    elif data == "key_paste_new":
        await _start_key_paste_new(query)
    elif data.startswith("key_view_priv:"):
        key_name = data.split(":", 1)[1]
        await _view_private_key(query, key_name)
    else:
        return False
    return True

# === Обработка текстовых сообщений для ключей ===
async def process_key_message(update, context):
    """Обработка текстовых сообщений для key_handlers"""
    user_id = update.effective_user.id

    if user_id in KEY_CREATE_STATE:
        key_name = update.message.text.strip()
        await _finish_key_creation(update.message, user_id, key_name)
        return True

    if user_id in KEY_RENAME_STATE:
        new_key_name = update.message.text.strip()
        old_key_name = KEY_RENAME_STATE[user_id]
        await _finish_key_rename(update.message, user_id, old_key_name, new_key_name)
        return True

    if user_id in KEY_REPLACE_STATE:
        new_key_content = update.message.text
        key_name = KEY_REPLACE_STATE[user_id]
        await _finish_key_replace(update.message, user_id, key_name, new_key_content)
        return True

    if user_id in KEY_PASTE_NEW_STATE:
        if "name" not in KEY_PASTE_NEW_STATE[user_id]:
            key_name = update.message.text.strip()
            KEY_PASTE_NEW_STATE[user_id] = {"name": key_name}
            await update.message.reply_text("Вставьте приватный SSH-ключ:")
            return True
        else:
            key_name = KEY_PASTE_NEW_STATE[user_id]["name"]
            key_content = update.message.text
            await _finish_key_paste_new(update.message, user_id, key_name, key_content)
            return True

    return False
