from telegram import (
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

from storage import load_groups


CANCEL_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")]
])

EDIT_CANCEL_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("❌ Отмена", callback_data="cancel_edit")]
])


def build_group_buttons(callback_prefix, suffix=""):
    keyboard = []

    for group in load_groups():

        group_name = group["name"]

        if group_name == "home":
            title = "🏠 Дом"

        elif group_name == "vps":
            title = "☁️ VPS"

        else:
            title = f"📁 {group_name}"

        callback_data = f"{callback_prefix}:{group_name}"

        if suffix:
            callback_data += f":{suffix}"

        keyboard.append([
            InlineKeyboardButton(
                title,
                callback_data=callback_data
            )
        ])

    return keyboard

def build_auth_buttons(server_id):
    from storage import find_server
    import os

    server = find_server(server_id)
    if not server:
        return []

    auth_type = server.get("auth_type", "password")
    has_password = bool(server.get("password"))
    key_path = server.get("key_path")

    keyboard = []
    key_is_valid = False

    if auth_type == "key" and key_path:
        if os.path.exists(key_path):
            key_is_valid = True

    if auth_type == "password":
        keyboard.append([
            InlineKeyboardButton("🔒 Сейчас: Пароль", callback_data="noop")
        ])
        if has_password:
            keyboard.append([
                InlineKeyboardButton("✏️ Изменить пароль", callback_data=f"auth_password:{server_id}")
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("➕ Добавить пароль", callback_data=f"auth_password:{server_id}")
            ])

    else:  # auth_type == "key"
        if key_is_valid:
            keyboard.append([
                InlineKeyboardButton("🔑 Сейчас: Ключ", callback_data="noop")
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("⚠️ Ключ не найден!", callback_data="noop")
            ])

        # Кнопка выбора другого ключа всегда доступна
        keyboard.append([
            InlineKeyboardButton("🔑 Выбрать другой ключ", callback_data=f"auth_key:{server_id}")
        ])

        has_sudo = bool(server.get("password"))

        if has_sudo:
            keyboard.append([
                InlineKeyboardButton("✏️ Изменить sudo-пароль", callback_data=f"edit_sudo_password:{server_id}")
            ])
            keyboard.append([
                InlineKeyboardButton("🗑 Удалить sudo-пароль", callback_data=f"delete_sudo_password:{server_id}")
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("➕ Добавить sudo-пароль", callback_data=f"edit_sudo_password:{server_id}")
            ])

    # Кнопка смены типа
    keyboard.append([
        InlineKeyboardButton("🔄 Сменить тип авторизации", callback_data=f"change_auth_type:{server_id}")
    ])

    keyboard.append([
        InlineKeyboardButton("⬅️ Назад", callback_data=f"edit:{server_id}")
    ])

    return keyboard

def build_certificate_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🌐 Ввести домен",
                callback_data="add_ssl_host"
            )
        ],
        [
            InlineKeyboardButton(
                "⏭ Пропустить",
                callback_data="skip_ssl_host"
            )
        ]
    ])

def build_key_buttons(server_id):
    return [
        [InlineKeyboardButton("📂 Выбрать существующий", callback_data=f"key_select:{server_id}")],
        [InlineKeyboardButton("📋 Вставить ключ", callback_data=f"key_paste:{server_id}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"edit_auth:{server_id}")]
    ]