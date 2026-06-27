import os
import secrets
import ipaddress

from storage import (
    load_servers,
    save_servers,
    load_groups,
    save_groups,
    is_group_ssl_enabled
)

from ui import (
    CANCEL_KB,
    EDIT_CANCEL_KB,
    build_group_buttons,
    build_certificate_buttons
)

from servers import (
    show_servers,
    show_server,
    show_server_message
)

from state import (
    ADD_SERVER_STATE,
    EDIT_SERVER_STATE,
    ADD_GROUP_STATE,
    PENDING_SERVER_CHANGES,
    SSL_SETUP_STATE
)
from telegram import (
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from ssh_utils import (
    get_available_keys,
    test_connection
)
from ssl_wizard import (
    start_ssl_setup,
    handle_ssl_host,
    skip_ssl_host
)

async def start_add_server(query):
    user_id = query.from_user.id

    ADD_SERVER_STATE[user_id] = {
        "step": "group"
    }

    keyboard = build_group_buttons("setgroup")
    keyboard.append([
        InlineKeyboardButton(
            "❌ Отмена",
            callback_data="cancel_add"
        )
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

    await show_server(
        query,
        server_id
    )

async def handle_add_group(update):
    user_id = update.effective_user.id

    group_name = update.message.text.strip()

    groups = load_groups()

    if any(
        g["name"] == group_name
        for g in groups
    ):
        await update.message.reply_text(
            "❌ Такая группа уже существует."
        )
        return

    ADD_GROUP_STATE[user_id]["name"] = group_name

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Да",
                callback_data="group_ssl:on"
            )
        ],
        [
            InlineKeyboardButton(
                "❌ Нет",
                callback_data="group_ssl:off"
            )
        ]
    ])

    await update.message.reply_text(
        "Проверять SSL сертификаты\nв этой группе?",
        reply_markup=keyboard
    )

async def handle_edit_server(update):
    user_id = update.effective_user.id
    edit = EDIT_SERVER_STATE[user_id]
    servers = load_servers()
    new_value = update.message.text.strip()
    found = None

    for server in servers:
        if server["id"] == edit["server"]:

            if edit["field"] == "port":
                try:
                    port = int(new_value)
                except ValueError:
                    await update.message.reply_text(
                        "❌ Порт должен быть числом.\n\nВведите порт заново:",
                        reply_markup=EDIT_CANCEL_KB
                    )
                    return
                if port < 1 or port > 65535:
                    await update.message.reply_text(
                        "❌ Порт должен быть от 1 до 65535.\n\nВведите порт заново:",
                        reply_markup=EDIT_CANCEL_KB
                    )
                    return
                server["port"] = port

            elif edit["field"] == "password":
                server["auth_type"] = "password"
                server["password"] = new_value
                server.pop("key_path", None)

            elif edit["field"] == "new_key":
                key_name = f"key_{server['name']}"
                key_path = f"/opt/bot4vps/keys/{key_name}"
                counter = 1
                while os.path.exists(key_path):
                    key_path = f"/opt/bot4vps/keys/{key_name}_{counter}"
                    counter += 1

                with open(key_path, "w") as f:
                    f.write(new_value)
                os.chmod(key_path, 0o600)

                server["auth_type"] = "key"
                server["key_path"] = key_path
                server.pop("password", None)

            elif edit["field"] == "ssl_host":
                server["ssl_host"] = new_value
                server["certificate_check"] = True
                found = server.copy()
                save_servers(servers)
                from monitor import update_server_certificate
                update_server_certificate(found)
                del EDIT_SERVER_STATE[user_id]
                await update.message.reply_text("✅ Домен SSL изменён. Сертификат обновлён.")
                from servers import show_server_message
                await show_server_message(update.message, edit["server"])
                return

            else:
                server[edit["field"]] = new_value

            found = server.copy()
            break

    if not found:
        await update.message.reply_text("❌ Сервер не найден.")
        del EDIT_SERVER_STATE[user_id]
        return

    # Проверка SSH только для важных полей
    check_fields = {"host", "port", "user", "password", "new_key"}
    if edit["field"] in check_fields:
        ok, error = test_connection(found)
        if not ok:
            PENDING_SERVER_CHANGES[user_id] = {"server": found}
            keyboard = [
                [InlineKeyboardButton("✅ Сохранить", callback_data=f"confirm_save_change:{found['id']}")],
                [InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_save_change:{found['id']}")]
            ]
            del EDIT_SERVER_STATE[user_id]
            await update.message.reply_text(
                f"⚠️ Проверка SSH не пройдена\n\n{error}\n\nСохранить изменения несмотря на ошибку?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

    save_servers(servers)
    server_id = found["id"]
    del EDIT_SERVER_STATE[user_id]
    await update.message.reply_text("✅ Параметр изменён.")
    from servers import show_server_message
    await show_server_message(update.message, server_id)

async def handle_add_server(update):
    user_id = update.effective_user.id

    state = ADD_SERVER_STATE[user_id]
    text = update.message.text.strip()

    if state["step"] == "name":
        state["name"] = text
        state["step"] = "host"

        await update.message.reply_text(
            "Введите IP или домен:",
            reply_markup=CANCEL_KB
        )

    elif state["step"] == "host":
        state["host"] = text
        state["step"] = "port"

        await update.message.reply_text(
            "Введите SSH порт:",
            reply_markup=CANCEL_KB
        )

    elif state["step"] == "port":

        try:
            port = int(text)

        except ValueError:
            await update.message.reply_text(
                "❌ Порт должен быть числом.\n\n"
                "Введите порт заново:",
                reply_markup=CANCEL_KB
            )
            return

        if port < 1 or port > 65535:
            await update.message.reply_text(
                "❌ Порт должен быть от 1 до 65535.\n\n"
                "Введите порт заново:",
                reply_markup=CANCEL_KB
            )
            return

        state["port"] = port
        state["step"] = "user"

        await update.message.reply_text(
            "Введите пользователя:",
            reply_markup=CANCEL_KB
        )

    elif state["step"] == "user":
        state["user"] = text
        state["step"] = "auth"

        keyboard = [
            [
                InlineKeyboardButton(
                    "🔒 Пароль",
                    callback_data="add_auth_password"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔑 Ключ",
                    callback_data="add_auth_key"
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Отмена",
                    callback_data="cancel_add"
                )
            ]
        ]
        await update.message.reply_text(
            "Выберите тип аутентификации:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif state["step"] == "password":

        state["password"] = text

        test_server = {
            "host": state["host"],
            "port": state["port"],
            "user": state["user"],
            "auth_type": "password",
            "password": state["password"]
        }

        ok, error = test_connection(
            test_server
        )

        ssh_message = (
            "\n\n✅ Проверка SSH успешна."
            if ok
            else f"\n\n⚠️ Проверка SSH не пройдена:\n{error}"
        )

        await finish_add_server(
            update.message,
            user_id,
            "password",
            ssh_message,
            password=state["password"]
        )

    elif state["step"] == "new_key":

        key_data = text

        server_name = state["name"]

        key_name = f"key_{server_name}"

        key_path = f"/opt/bot4vps/keys/{key_name}"

        counter = 1

        while os.path.exists(key_path):
            key_path = (
                f"/opt/bot4vps/keys/"
                f"{key_name}_{counter}"
            )
            counter += 1

        with open(key_path, "w") as f:
            f.write(key_data)

        os.chmod(key_path, 0o600)

        test_server = {
            "host": state["host"],
            "port": state["port"],
            "user": state["user"],
            "auth_type": "key",
            "key_path": key_path
        }

        ok, error = test_connection(
            test_server
        )

        ssh_message = (
            "\n\n✅ Проверка SSH успешна."
            if ok
            else f"\n\n⚠️ Проверка SSH не пройдена:\n{error}"
        )

        await finish_add_server(
            update.message,
            user_id,
            "key",
            ssh_message,
            key_path=key_path
        )

async def save_new_server(
    user_id,
    auth_type,
    password=None,
    key_path=None
):
    state = ADD_SERVER_STATE[user_id]

    server = {
        "id": secrets.token_hex(4),
        "name": state["name"],
        "group": state["group"],
        "host": state["host"],
        "port": state["port"],
        "user": state["user"],
        "auth_type": auth_type
    }

    if password:
        server["password"] = password

    if key_path:
        server["key_path"] = key_path

    if "certificate_check" in state:
        server["certificate_check"] = (
            state["certificate_check"]
        )

    if "ssl_host" in state:
        server["ssl_host"] = (
            state["ssl_host"]
        )

    servers = load_servers()

    servers.append(server)

    save_servers(servers)

    return server["id"]


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

    ssl_enabled = is_group_ssl_enabled(
        state["group"]
    )

    state["certificate_check"] = ssl_enabled

    server_id = await save_new_server(
        user_id,
        auth_type,
        password=password,
        key_path=key_path
    )

    if ssl_enabled:

        await start_ssl_setup(
            target,
            [server_id],
            "server_add",
            {
                "type": "servers"
            }
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

    await query.message.reply_text(
        "Введите пароль:",
        reply_markup=CANCEL_KB
    )

async def add_auth_key(query):
    keyboard = [
        [
            InlineKeyboardButton(
                "📂 Выбрать существующий",
                callback_data="add_key_select"
            )
        ],
        [
            InlineKeyboardButton(
                "📋 Ввести новый",
                callback_data="add_key_new"
            )
        ],
        [
            InlineKeyboardButton(
                "❌ Отмена",
                callback_data="cancel_add"
            )
        ]
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
            InlineKeyboardButton(
                f,
                callback_data=f"add_key_use:{f}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Назад",
            callback_data="add_auth_key"
        )
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

    test_server = {
        "host": state["host"],
        "port": state["port"],
        "user": state["user"],
        "auth_type": "key",
        "key_path": key_path
    }

    ok, error = test_connection(test_server)

    ssh_message = (
        "\n\n✅ Проверка SSH успешна."
        if ok
        else f"\n\n⚠️ Проверка SSH не пройдена:\n{error}"
    )

    await finish_add_server(
        query.message,
        user_id,
        "key",
        ssh_message,
        key_path=key_path
    )
async def add_key_new(query):
    user_id = query.from_user.id

    if user_id not in ADD_SERVER_STATE:
        return

    ADD_SERVER_STATE[user_id]["step"] = "new_key"

    await query.edit_message_text(
        "Вставьте приватный SSH-ключ:"
    )
