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
    return [
        [
            InlineKeyboardButton(
                "🔒 Пароль",
                callback_data=f"auth_password:{server_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔑 Ключ",
                callback_data=f"auth_key:{server_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Назад",
                callback_data=f"edit:{server_id}"
            )
        ]
    ]

def build_key_buttons(server_id):
    return [
        [InlineKeyboardButton("📂 Выбрать существующий", callback_data=f"key_select:{server_id}")],
        [InlineKeyboardButton("📋 Вставить ключ", callback_data=f"key_paste:{server_id}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"edit_auth:{server_id}")]
    ]

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