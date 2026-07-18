"""
Auth handlers module for Bot4VPS.

Управление способом аутентификации сервера (password ↔ key, выбор ключа и т.д.).

Публичный интерфейс модуля — только одна функция:
    process_auth_callback(query, data) -> bool

Все остальные функции — внутренние (начинаются с _ ).
bot_handlers.py ничего не знает о внутреннем устройстве модуля.
"""

from telegram import InlineKeyboardMarkup, InlineKeyboardButton

import os

from core.storage import load_servers, save_servers, find_server
from core.ssh import get_available_keys, test_connection
from state import ADD_SERVER_STATE, EDIT_SERVER_STATE, PENDING_SERVER_CHANGES
from ui.telegram.keyboards import EDIT_CANCEL_KB, build_auth_buttons, build_key_buttons
from ui.telegram.servers import show_server_message
from ui.telegram.server_wizard import add_auth_key, add_auth_password, add_key_select, add_key_new


# === Внутренние функции ===

async def _edit_auth_menu(query, server_id):
    server = find_server(server_id)
    if not server:
        await query.edit_message_text("❌ Сервер не найден.")
        return

    auth_type = server.get("auth_type", "password")
    key_path = server.get("key_path")

    if auth_type == "key":
        key_missing = True
        if key_path and os.path.exists(key_path):
            key_missing = False

        if key_missing:
            text = (
                f"⚠️ Файл ключа не найден!\n\n"
                f"Сервер: {server['name']}\n"
                f"Текущий тип: Ключ\n\n"
                f"Выберите действие:"
            )
            keyboard = [
                [InlineKeyboardButton("📂 Выбрать существующий ключ", callback_data=f"key_select:{server_id}")],
                [InlineKeyboardButton("📋 Вставить новый ключ", callback_data=f"key_paste:{server_id}")],
                [InlineKeyboardButton("🔒 Сменить на авторизацию по паролю", callback_data=f"change_to_password:{server_id}")],
                [InlineKeyboardButton("⬅️ Назад", callback_data=f"edit:{server_id}")]
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

    await query.edit_message_text(
        "Выберите тип аутентификации:",
        reply_markup=InlineKeyboardMarkup(build_auth_buttons(server_id))
    )


async def _auth_key_menu(query, server_id):
    await query.edit_message_text(
        "Настройка SSH-ключа:",
        reply_markup=InlineKeyboardMarkup(build_key_buttons(server_id))
    )


async def _auth_password_flow(query, server_id):
    server = find_server(server_id)
    if not server:
        await query.edit_message_text("❌ Сервер не найден.")
        return

    EDIT_SERVER_STATE[query.from_user.id] = {
        "server": server_id,
        "field": "password"
    }

    await query.message.reply_text(
        f"Введите новый пароль:\n\n{server['name']}",
        reply_markup=EDIT_CANCEL_KB
    )


async def _edit_sudo_password_flow(query, server_id):
    server = find_server(server_id)
    if not server:
        await query.edit_message_text("❌ Сервер не найден.")
        return

    EDIT_SERVER_STATE[query.from_user.id] = {
        "server": server_id,
        "field": "sudo_password"
    }

    current = " (текущий пароль будет заменён)" if server.get("password") else ""
    await query.message.reply_text(
        f"Введите новый пароль для sudo{current}:",
        reply_markup=EDIT_CANCEL_KB
    )


async def _delete_sudo_password_confirm_flow(query, server_id):
    server = find_server(server_id)
    if not server:
        await query.edit_message_text("❌ Сервер не найден.")
        return

    if server.get("auth_type") == "password":
        warning_text = (
            "⚠️ Внимание!\n\n"
            "Сейчас у сервера стоит авторизация **по паролю**.\n"
            "Если ты удалишь sudo-пароль, то потеряешь возможность выполнять команды с правами root через бота.\n\n"
            "Ты уверен, что хочешь удалить sudo-пароль?"
        )
    else:
        warning_text = (
            "⚠️ Удалить sudo-пароль?\n\n"
            "После удаления бот больше не сможет выполнять команды, требующие прав root (через sudo)."
        )

    keyboard = [
        [InlineKeyboardButton("✅ Да, удалить", callback_data=f"delete_sudo_password_confirm:{server_id}")],
        [InlineKeyboardButton("❌ Отмена", callback_data=f"edit_auth:{server_id}")]
    ]

    await query.edit_message_text(
        warning_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def _delete_sudo_password_execute(query, server_id):
    server = find_server(server_id)
    if not server:
        await query.edit_message_text("❌ Сервер не найден.")
        return

    servers = load_servers()
    for s in servers:
        if s["id"] == server_id:
            s.pop("password", None)
            break
    save_servers(servers)

    await query.edit_message_text("✅ Sudo-пароль удалён.")
    await show_server_message(query.message, server_id)


async def _key_select_menu(query, server_id):
    files = get_available_keys()

    keyboard = []
    for f in files:
        keyboard.append([
            InlineKeyboardButton(f, callback_data=f"key_use:{server_id}:{f}")
        ])

    keyboard.append([
        InlineKeyboardButton("⬅️ Назад", callback_data=f"auth_key:{server_id}")
    ])

    await query.edit_message_text(
        "Выберите ключ:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _key_use_flow(query, server_id, key_name):
    servers = load_servers()
    current_server = None

    for server in servers:
        if server["id"] == server_id:
            current_server = server.copy()
            break

    if not current_server:
        await query.edit_message_text("❌ Сервер не найден.")
        return

    current_server["auth_type"] = "key"
    current_server["key_path"] = f"/opt/bot4vps/keys/{key_name}"

    ok, error = test_connection(current_server)

    if ok:
        for i, server in enumerate(servers):
            if server["id"] == server_id:
                servers[i] = current_server
                break
        save_servers(servers)

        await query.edit_message_text(
            f"✅ Выбран ключ:\n\n{key_name}\n\n✅ Проверка SSH успешна."
        )
        await show_server_message(query.message, server_id)
        return

    PENDING_SERVER_CHANGES[query.from_user.id] = {
        "server": current_server
    }

    keyboard = [
        [InlineKeyboardButton("✅ Сохранить", callback_data=f"confirm_save_change:{server_id}")],
        [InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_save_change:{server_id}")]
    ]

    await query.edit_message_text(
        "⚠️ Проверка SSH не пройдена\n\n"
        f"{error}\n\n"
        "Сохранить изменения несмотря на ошибку?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _key_paste_flow(query, server_id):
    EDIT_SERVER_STATE[query.from_user.id] = {
        "server": server_id,
        "field": "new_key"
    }
    await query.edit_message_text("Вставьте приватный SSH-ключ:")


async def _change_auth_type_menu(query, server_id):
    server = find_server(server_id)
    if not server:
        await query.edit_message_text("❌ Сервер не найден.")
        return

    current = server.get("auth_type", "password")
    text = f"Текущий тип: {'Пароль' if current == 'password' else 'Ключ'}\n\nВыберите новый тип авторизации:"

    keyboard = []
    if current == "password":
        keyboard.append([InlineKeyboardButton("🔑 Перейти на Ключ", callback_data=f"change_to_key:{server_id}")])
    else:
        keyboard.append([InlineKeyboardButton("🔒 Перейти на Пароль", callback_data=f"change_to_password:{server_id}")])

    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data=f"edit_auth:{server_id}")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def _change_to_key_flow(query, server_id):
    server = find_server(server_id)
    if not server:
        await query.edit_message_text("❌ Сервер не найден.")
        return

    PENDING_SERVER_CHANGES[query.from_user.id] = {
        "server": server.copy(),
        "original": server.copy()
    }
    pending = PENDING_SERVER_CHANGES[query.from_user.id]["server"]
    pending["auth_type"] = "key"

    if server.get("password"):
        keyboard = [
            [InlineKeyboardButton("✅ Да, сохранить как sudo", callback_data=f"confirm_change_to_key:{server_id}")],
            [InlineKeyboardButton("❌ Нет, не сохранять", callback_data=f"confirm_change_to_key_no:{server_id}")],
            [InlineKeyboardButton("❌ Отмена", callback_data=f"edit_auth:{server_id}")]
        ]
        await query.edit_message_text(
            "У сервера есть сохранённый пароль.\n\nСохранить его как sudo-пароль?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.edit_message_text(
            "Выберите SSH-ключ:",
            reply_markup=InlineKeyboardMarkup(build_key_buttons(server_id))
        )


async def _change_to_password_flow(query, server_id):
    server = find_server(server_id)
    if not server:
        await query.edit_message_text("❌ Сервер не найден.")
        return

    has_password = bool(server.get("password"))

    if has_password:
        servers = load_servers()
        for s in servers:
            if s["id"] == server_id:
                s["auth_type"] = "password"
                break
        save_servers(servers)
        await query.edit_message_text("✅ Тип авторизации изменён на Пароль.")
        await show_server_message(query.message, server_id)
    else:
        keyboard = [
            [InlineKeyboardButton("✅ Да, сменить и ввести пароль", callback_data=f"confirm_change_to_password:{server_id}")],
            [InlineKeyboardButton("❌ Отмена (оставить ключ)", callback_data=f"edit_auth:{server_id}")]
        ]
        await query.edit_message_text(
            "⚠️ У сервера сейчас нет сохранённого пароля.\n\n"
            "После смены типа на «Пароль» нужно будет ввести новый пароль.\n\n"
            "Продолжить?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def _confirm_change_to_password(query, server_id):
    servers = load_servers()
    for s in servers:
        if s["id"] == server_id:
            s["auth_type"] = "password"
            break
    save_servers(servers)

    EDIT_SERVER_STATE[query.from_user.id] = {
        "server": server_id,
        "field": "password"
    }

    await query.message.reply_text("Введите новый пароль:", reply_markup=EDIT_CANCEL_KB)


async def _confirm_change_to_key(query, server_id):
    user_id = query.from_user.id
    pending = PENDING_SERVER_CHANGES.get(user_id)
    if not pending:
        await query.edit_message_text("❌ Изменения потеряны.")
        return

    key_path = pending["server"].get("key_path")
    key_exists = bool(key_path) and os.path.exists(key_path)

    if key_exists:
        servers = load_servers()
        for i, s in enumerate(servers):
            if s["id"] == server_id:
                servers[i] = pending["server"]
                break
        save_servers(servers)
        del PENDING_SERVER_CHANGES[user_id]

        await query.edit_message_text("✅ Тип авторизации изменён на Ключ.")
        await show_server_message(query.message, server_id)
    else:
        await query.edit_message_text(
            "Выберите SSH-ключ:",
            reply_markup=InlineKeyboardMarkup(build_key_buttons(server_id))
        )


async def _confirm_change_to_key_no(query, server_id):
    user_id = query.from_user.id
    pending = PENDING_SERVER_CHANGES.get(user_id)
    if not pending:
        await query.edit_message_text("❌ Изменения потеряны.")
        return

    pending["server"].pop("password", None)

    key_path = pending["server"].get("key_path")
    key_exists = bool(key_path) and os.path.exists(key_path)

    if key_exists:
        servers = load_servers()
        for i, s in enumerate(servers):
            if s["id"] == server_id:
                servers[i] = pending["server"]
                break
        save_servers(servers)
        del PENDING_SERVER_CHANGES[user_id]

        await query.edit_message_text("✅ Тип авторизации изменён на Ключ.")
        await show_server_message(query.message, server_id)
    else:
        await query.edit_message_text(
            "Выберите SSH-ключ:",
            reply_markup=InlineKeyboardMarkup(build_key_buttons(server_id))
        )


async def _confirm_save_change(query, server_id):
    pending = PENDING_SERVER_CHANGES.get(query.from_user.id)
    if not pending:
        await query.edit_message_text("❌ Изменения не найдены.")
        return

    servers = load_servers()
    for i, server in enumerate(servers):
        if server["id"] == server_id:
            servers[i] = pending["server"]
            break

    save_servers(servers)
    del PENDING_SERVER_CHANGES[query.from_user.id]

    await query.edit_message_text("✅ Изменения сохранены.")
    await show_server_message(query.message, server_id)


async def _cancel_save_change(query, server_id):
    if query.from_user.id in PENDING_SERVER_CHANGES:
        del PENDING_SERVER_CHANGES[query.from_user.id]

    await query.edit_message_text("❌ Изменения отменены.")
    await show_server_message(query.message, server_id)


# === Публичная точка входа модуля ===
async def process_auth_callback(query, data: str) -> bool:
    """
    Единая публичная функция модуля Auth.
    """
    if data.startswith("edit_auth:"):
        server_id = data.split(":", 1)[1]
        await _edit_auth_menu(query, server_id)

    elif data.startswith("auth_key:"):
        server_id = data.split(":", 1)[1]
        await _auth_key_menu(query, server_id)

    elif data == "add_auth_password":
        await add_auth_password(query)

    elif data == "add_auth_key":
        await add_auth_key(query)

    elif data == "add_key_select":
        await add_key_select(query)
        return True

    elif data == "add_key_new":
        await add_key_new(query)
        return True

    elif data == "add_key_select":
        await add_key_select(query)
        return True

    elif data == "add_key_new":
        await add_key_new(query)
        return True

    elif data.startswith("auth_password:"):
        server_id = data.split(":", 1)[1]
        await _auth_password_flow(query, server_id)

    elif data.startswith("edit_sudo_password:"):
        server_id = data.split(":", 1)[1]
        await _edit_sudo_password_flow(query, server_id)

    elif data.startswith("delete_sudo_password:"):
        server_id = data.split(":", 1)[1]
        await _delete_sudo_password_confirm_flow(query, server_id)

    elif data.startswith("delete_sudo_password_confirm:"):
        server_id = data.split(":", 1)[1]
        await _delete_sudo_password_execute(query, server_id)

    elif data.startswith("key_select:"):
        server_id = data.split(":", 1)[1]
        await _key_select_menu(query, server_id)

    elif data.startswith("key_use:"):
        _, server_id, key_name = data.split(":", 2)
        await _key_use_flow(query, server_id, key_name)

    elif data.startswith("key_paste:"):
        server_id = data.split(":", 1)[1]
        await _key_paste_flow(query, server_id)

    elif data.startswith("change_auth_type:"):
        server_id = data.split(":", 1)[1]
        await _change_auth_type_menu(query, server_id)

    elif data.startswith("change_to_key:"):
        server_id = data.split(":", 1)[1]
        await _change_to_key_flow(query, server_id)

    elif data.startswith("change_to_password:"):
        server_id = data.split(":", 1)[1]
        await _change_to_password_flow(query, server_id)

    elif data.startswith("confirm_change_to_password:"):
        server_id = data.split(":", 1)[1]
        await _confirm_change_to_password(query, server_id)

    elif data.startswith("confirm_change_to_key:"):
        server_id = data.split(":", 1)[1]
        await _confirm_change_to_key(query, server_id)

    elif data.startswith("confirm_change_to_key_no:"):
        server_id = data.split(":", 1)[1]
        await _confirm_change_to_key_no(query, server_id)

    elif data.startswith("confirm_save_change:"):
        server_id = data.split(":", 1)[1]
        await _confirm_save_change(query, server_id)

    elif data.startswith("cancel_save_change:"):
        server_id = data.split(":", 1)[1]
        await _cancel_save_change(query, server_id)

    else:
        return False

    return True