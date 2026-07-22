import os

from telegram import InlineKeyboardMarkup, InlineKeyboardButton

from core.storage import load_servers, save_servers, load_groups, is_group_ssl_enabled, find_server
from core.ssh import get_available_keys, test_connection
from core.server_wizard import (
    validate_port,
    create_key_file,
    save_new_server,
    test_server_connection,
    update_server_field,
    update_ssl_host
)

from ui.telegram.keyboards import (
    CANCEL_KB,
    EDIT_CANCEL_KB,
    build_group_buttons,
    build_certificate_buttons
)

from ui.telegram.ssl_wizard import start_ssl_setup

from state import (
    ADD_SERVER_STATE,
    EDIT_SERVER_STATE,
    ADD_GROUP_STATE,
    PENDING_SERVER_CHANGES
)

# Временно, пока servers.py не разделён
from ui.telegram.servers import show_servers, show_server, show_server_message


async def start_add_server(query):
    user_id = query.from_user.id

    ADD_SERVER_STATE[user_id] = {
        "step": "group"
    }

    keyboard = build_group_buttons("setgroup")
    keyboard.append([
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")
    ])

    await query.edit_message_text(
        "➕ Добавление сервера\n\nВыберите группу:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def start_add_group(query):
    ADD_GROUP_STATE[query.from_user.id] = {}

    await query.edit_message_text(
        "Введите имя новой группы:",
        reply_markup=CANCEL_KB
    )


async def cancel_add_server(query):
    user_id = query.from_user.id

    if user_id in ADD_SERVER_STATE:
        del ADD_SERVER_STATE[user_id]

    await show_servers(query)


async def cancel_edit_server(query):
    user_id = query.from_user.id

    if user_id not in EDIT_SERVER_STATE:
        await show_servers(query)
        return

    server_id = EDIT_SERVER_STATE[user_id]["server"]
    del EDIT_SERVER_STATE[user_id]

    await show_server(query, server_id)


async def handle_add_group(update):
    user_id = update.effective_user.id
    group_name = update.message.text.strip()

    groups = load_groups()

    if any(g["name"] == group_name for g in groups):
        await update.message.reply_text("❌ Такая группа уже существует.")
        return

    ADD_GROUP_STATE[user_id]["name"] = group_name

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да", callback_data="group_ssl:on")],
        [InlineKeyboardButton("❌ Нет", callback_data="group_ssl:off")]
    ])

    await update.message.reply_text(
        "Проверять SSL сертификаты\nв этой группе?",
        reply_markup=keyboard
    )


async def handle_edit_server(update):
    user_id = update.effective_user.id
    edit = EDIT_SERVER_STATE[user_id]
    new_value = update.message.text.strip()

    if edit["field"] == "port":
        ok, port, error = validate_port(new_value)
        if not ok:
            await update.message.reply_text(
                f"{error}\n\nВведите порт заново:",
                reply_markup=EDIT_CANCEL_KB
            )
            return

        success, message = update_server_field(edit["server"], "port", port)
        if not success:
            await update.message.reply_text(message)
            del EDIT_SERVER_STATE[user_id]
            return

    elif edit["field"] == "password":
        success, message = update_server_field(edit["server"], "password", new_value)
        if success:
            # Переводим на авторизацию по паролю
            update_server_field(edit["server"], "auth_type", "password")

    elif edit["field"] == "new_key":
        server = find_server(edit["server"])
        if not server:
            await update.message.reply_text("❌ Сервер не найден.")
            del EDIT_SERVER_STATE[user_id]
            return

        key_path = create_key_file(new_value, server["name"])

        current_server = server.copy()
        current_server["key_path"] = key_path
        current_server["auth_type"] = "key"

        ok, error = test_connection(current_server)

        if ok:
            servers = load_servers()
            for i, s in enumerate(servers):
                if s["id"] == edit["server"]:
                    servers[i] = current_server
                    break

            save_servers(servers)

            success = True
            message = "Параметр успешно обновлён."

        else:
            PENDING_SERVER_CHANGES[user_id] = {
                "server": current_server
            }

            keyboard = [
                [InlineKeyboardButton("✅ Сохранить", callback_data=f"confirm_save_change:{current_server['id']}")],
                [InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_save_change:{current_server['id']}")]
            ]

            del EDIT_SERVER_STATE[user_id]

            await update.message.reply_text(
                f"⚠️ Проверка SSH не пройдена\n\n{error}\n\nСохранить изменения несмотря на ошибку?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

    elif edit["field"] == "sudo_password":
        success, message = update_server_field(edit["server"], "password", new_value)
        if success and edit.get("auth_type") != "key":
            update_server_field(edit["server"], "auth_type", "key")

    elif edit["field"] == "ssl_host":
        if update_ssl_host(edit["server"], new_value):
            await update.message.reply_text("✅ Домен SSL изменён. Сертификат обновлён.")
        else:
            await update.message.reply_text("❌ Не удалось обновить домен.")
        del EDIT_SERVER_STATE[user_id]
        await show_server_message(update.message, edit["server"])
        return

    else:
        # Обычное поле
        success, message = update_server_field(edit["server"], edit["field"], new_value)

    if not success:
        await update.message.reply_text(message)
        del EDIT_SERVER_STATE[user_id]
        return

    # Проверка SSH для важных полей
    check_fields = {"host", "port", "user", "password"}
    if edit["field"] in check_fields:
        server = find_server(edit["server"])
        ok, error = test_connection(server)
        if not ok:
            PENDING_SERVER_CHANGES[user_id] = {"server": server}
            keyboard = [
                [InlineKeyboardButton("✅ Сохранить", callback_data=f"confirm_save_change:{server['id']}")],
                [InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_save_change:{server['id']}")]
            ]
            del EDIT_SERVER_STATE[user_id]
            await update.message.reply_text(
                f"⚠️ Проверка SSH не пройдена\n\n{error}\n\nСохранить изменения несмотря на ошибку?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

    await update.message.reply_text("✅ Параметр изменён.")
    del EDIT_SERVER_STATE[user_id]
    await show_server_message(update.message, edit["server"])

async def handle_add_server(update):
    user_id = update.effective_user.id
    state = ADD_SERVER_STATE[user_id]
    text = update.message.text.strip()

    if state["step"] == "name":
        state["name"] = text
        state["step"] = "host"
        await update.message.reply_text("Введите IP или домен:", reply_markup=CANCEL_KB)

    elif state["step"] == "host":
        state["host"] = text
        state["step"] = "port"
        await update.message.reply_text("Введите SSH порт:", reply_markup=CANCEL_KB)

    elif state["step"] == "port":
        ok, port, error = validate_port(text)
        if not ok:
            await update.message.reply_text(f"{error}\n\nВведите порт заново:", reply_markup=CANCEL_KB)
            return

        state["port"] = port
        state["step"] = "user"
        await update.message.reply_text("Введите пользователя:", reply_markup=CANCEL_KB)

    elif state["step"] == "user":
        state["user"] = text
        state["step"] = "auth"

        keyboard = [
            [InlineKeyboardButton("🔒 Пароль", callback_data="add_auth_password")],
            [InlineKeyboardButton("🔑 Ключ", callback_data="add_auth_key")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")]
        ]
        await update.message.reply_text(
            "Выберите тип аутентификации:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif state["step"] == "password":
        state["password"] = text

        ok, error = test_server_connection(
            host=state["host"],
            port=state["port"],
            user=state["user"],
            auth_type="password",
            password=text
        )

        ssh_message = "\n\n✅ Проверка SSH успешна." if ok else f"\n\n⚠️ Проверка SSH не пройдена:\n{error}"

        await finish_add_server(
            update.message,
            user_id,
            "password",
            ssh_message,
            password=text
        )

    elif state["step"] == "new_key":
        key_path = create_key_file(text, state["name"])

        ok, error = test_server_connection(
            host=state["host"],
            port=state["port"],
            user=state["user"],
            auth_type="key",
            key_path=key_path
        )

        ssh_message = "\n\n✅ Проверка SSH успешна." if ok else f"\n\n⚠️ Проверка SSH не пройдена:\n{error}"

        await finish_add_server(
            update.message,
            user_id,
            "key",
            ssh_message,
            key_path=key_path
        )

    elif state["step"] == "sudo_password":
        state["password"] = text
        await finish_add_server(
            update.message,
            user_id,
            "key",
            "\n\n✅ Сервер добавлен с sudo-паролем",
            key_path=state.get("key_path"),
            password=text
        )


async def finish_add_server(
    target,
    user_id,
    auth_type,
    ssh_message,
    password=None,
    key_path=None
):
    state = ADD_SERVER_STATE[user_id]

    state["auth_type"] = auth_type
    if password:
        state["password"] = password
    if key_path:
        state["key_path"] = key_path

    ssl_enabled = is_group_ssl_enabled(state["group"])
    state["certificate_check"] = ssl_enabled

    server_id = save_new_server(state, auth_type, password=password, key_path=key_path)

    if ssl_enabled:
        await start_ssl_setup(
            target,
            [server_id],
            "server_add",
            {"type": "servers"}
        )
        return

    del ADD_SERVER_STATE[user_id]

    await show_servers(
        target,
        "✅ Сервер добавлен." + ssh_message
    )


async def add_auth_password(query):
    user_id = query.from_user.id

    if user_id not in ADD_SERVER_STATE:
        return

    ADD_SERVER_STATE[user_id]["auth_type"] = "password"
    ADD_SERVER_STATE[user_id]["step"] = "password"

    await query.message.reply_text("Введите пароль:", reply_markup=CANCEL_KB)


async def add_auth_key(query):
    keyboard = [
        [InlineKeyboardButton("📂 Выбрать существующий", callback_data="add_key_select")],
        [InlineKeyboardButton("📋 Ввести новый", callback_data="add_key_new")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")]
    ]

    await query.edit_message_text(
        "Настройка SSH-ключа:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def add_key_select(query):
    files = get_available_keys()

    keyboard = []
    for f in files:
        keyboard.append([
            InlineKeyboardButton(f, callback_data=f"add_key_use:{f}")
        ])

    keyboard.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="add_auth_key")
    ])

    await query.edit_message_text(
        "Выберите ключ:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def add_key_use(query):
    key_name = query.data.split(":", 1)[1]
    user_id = query.from_user.id

    if user_id not in ADD_SERVER_STATE:
        return

    state = ADD_SERVER_STATE[user_id]
    key_path = f"/opt/bot4vps/keys/{key_name}"

    state["key_path"] = key_path
    state["step"] = "ask_sudo_password"

    keyboard = [
        [InlineKeyboardButton("✅ Да, нужен sudo-пароль", callback_data="add_sudo_password:yes")],
        [InlineKeyboardButton("❌ Нет, не нужен", callback_data="add_sudo_password:no")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")]
    ]

    await query.edit_message_text(
        "Нужен ли пароль для выполнения команд через sudo?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def add_key_new(query):
    user_id = query.from_user.id

    if user_id not in ADD_SERVER_STATE:
        return

    ADD_SERVER_STATE[user_id]["step"] = "new_key"

    await query.edit_message_text("Вставьте приватный SSH-ключ:")


async def handle_sudo_password_choice(query, choice):
    user_id = query.from_user.id

    if user_id not in ADD_SERVER_STATE:
        return

    state = ADD_SERVER_STATE[user_id]

    if choice == "yes":
        state["step"] = "sudo_password"
        await query.message.reply_text(
            "Введите пароль для sudo:",
            reply_markup=CANCEL_KB
        )
    else:
        await finish_add_server(
            query.message,
            user_id,
            "key",
            "\n\n✅ Сервер добавлен (без sudo-пароля)",
            key_path=state.get("key_path")
        )