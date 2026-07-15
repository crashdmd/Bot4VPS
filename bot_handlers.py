from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

import asyncio
import ipaddress
import os
import subprocess
import time


from storage import (
    load_servers,
    save_servers,
    load_groups,
    save_groups,
    find_server,
    is_group_ssl_enabled,
)
from servers import (
    show_servers,
    show_group,
    show_group_ssl_menu,
    show_server,
    show_server_message,
    edit_server_menu,
    delete_confirm,
    delete_server,
    delete_group_confirm,
    delete_group,
    reboot_confirm,
    perform_reboot,
)
from server_wizard import (
    start_add_server,
    start_add_group,
    cancel_add_server,
    cancel_edit_server,
    handle_add_group,
    handle_edit_server,
    add_auth_password,
    add_auth_key,
    add_key_use,
    add_key_select,
    add_key_new,
    handle_sudo_password_choice
)
from scripts import (
    execute_script,          
    show_scripts,
    show_script,
    view_script,
    run_script_select_server,
    run_script_confirm,
    show_script_param,
    finish_script_params,
)
from script_utils import get_script_params, delete_script
from ssl_wizard import start_ssl_setup, skip_ssl_host
from monitor import run_monitor, update_server_certificate, refresh_server_state
from ssh_utils import get_available_keys, test_connection
from state import (
    ADD_SERVER_STATE,
    EDIT_SERVER_STATE,
    ADD_GROUP_STATE,
    SCRIPT_RUN_STATE,
    SCRIPT_CONFIRM_STATE,
    PENDING_SERVER_CHANGES,
    KEY_CREATE_STATE,
    KEY_RENAME_STATE,
    KEY_REPLACE_STATE,
    KEY_PASTE_NEW_STATE
)
from ui import CANCEL_KB, EDIT_CANCEL_KB, build_group_buttons, build_auth_buttons, build_key_buttons
from common import is_allowed, build_main_menu, show_main_menu
#===============================================
async def process_notifications(update):
    from notifications import get_notifications, save_notifications
    notifications = get_notifications()
    if not notifications:
        return
    remaining = []
    for notification in notifications:
        handler = NOTIFICATION_HANDLERS.get(notification["type"])
        if not handler:
            remaining.append(notification)
            continue
        try:
            processed = await handler(update, notification)
            if not processed:
                remaining.append(notification)
        except Exception:
            remaining.append(notification)
    save_notifications(remaining)


async def show_admin_menu(query):
    keyboard = [
        [InlineKeyboardButton("🔄 Проверить все сервера", callback_data="check_all_servers")],
        [InlineKeyboardButton("🔑 Управление SSH-ключами", callback_data="key_manager")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main")]
    ]
    await query.edit_message_text(
        "🛠 Администрирование\n\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_key_manager(query):
    import os

    keys_dir = "/opt/bot4vps/keys"
    keyboard = []

    if os.path.exists(keys_dir):
        all_files = os.listdir(keys_dir)
        private_keys = [f for f in all_files if os.path.isfile(os.path.join(keys_dir, f)) and not f.endswith(".pub")]

        for key_name in sorted(private_keys):
            size = os.path.getsize(os.path.join(keys_dir, key_name))
            keyboard.append([
                InlineKeyboardButton(f"🔑 {key_name} ({size} байт)", callback_data=f"key_action:{key_name}")
            ])

    # === Кнопки внизу ===
    keyboard.append([InlineKeyboardButton("➕ Создать новый ключ", callback_data="key_create")])
    keyboard.append([InlineKeyboardButton("📥 Вставить существующий ключ", callback_data="key_paste_new")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin")])

    await query.edit_message_text(
        "🔑 Управление SSH-ключами\n\nВыберите ключ или создайте новый:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await process_notifications(update)

    if not is_allowed(query.from_user.id):
        return

    data = query.data

    if data == "main":
        await show_main_menu(query)

    elif data == "servers":
        await show_servers(query)

    elif data == "add_server":
        await start_add_server(query)

    elif data == "add_group":
        await start_add_group(query)

    elif data.startswith("group_ssl:"):

        parts = data.split(":")

        mode = parts[1]

        ssl_monitor = (
            mode == "on"
        )

        user_id = query.from_user.id

        # ---------- Создание новой группы ----------

        if len(parts) == 2:

            if user_id not in ADD_GROUP_STATE:
                return

            state = ADD_GROUP_STATE[user_id]

            groups = load_groups()

            groups.append({
                "name": state["name"],
                "ssl_monitor": ssl_monitor
            })

            save_groups(groups)

            del ADD_GROUP_STATE[user_id]

            await show_servers(
                query,
                "✅ Группа добавлена."
            )

            return

        # ---------- Изменение существующей ----------

        group_name = parts[2]

        groups = load_groups()

        changed = False

        for group in groups:

            if group["name"] == group_name:

                group["ssl_monitor"] = ssl_monitor

                changed = True

                break

        if not changed:

            await query.edit_message_text(
                "❌ Группа не найдена."
            )

            return

        save_groups(groups)

        servers = load_servers()

        changed_servers = False

        ssl_setup = []

        for server in servers:

            if server["group"] != group_name:

                continue

            if ssl_monitor:

                server["certificate_check"] = True

                try:

                    ipaddress.ip_address(
                        server["host"]
                    )

                    is_ip = True

                except ValueError:

                    is_ip = False

                if is_ip:

                    if server.get(
                        "ssl_host"
                    ):

                        update_server_certificate(
                            server
                        )

                    else:

                        ssl_setup.append(
                            server["id"]
                        )

                else:

                    if not server.get(
                        "ssl_host"
                    ):

                        server["ssl_host"] = (
                            server["host"]
                        )

                    update_server_certificate(
                        server
                    )

            else:

                server["certificate_check"] = False

            changed_servers = True

        if changed_servers:

            save_servers(
                servers
            )

        if ssl_setup:

            await start_ssl_setup(
                query,
                ssl_setup,
                "group_ssl",
                {
                    "type": "group",
                    "value": group_name
                }
            )

            return

        await show_group(
            query,
            group_name
        )

    elif data.startswith("group_ssl_menu:"):

        await show_group_ssl_menu(
            query,
            data.split(":", 1)[1]
        )

    elif data.startswith("ssl_check_now:"):
        group_name = data.split(":", 1)[1]
        await query.answer("Проверка SSL...")

        events = run_monitor(group_name)
        checked = 0
        renewed = 0
        expired = 0

        servers_in_group = [
            s for s in load_servers()
            if s.get("group") == group_name and s.get("certificate_check")
        ]
        checked = len(servers_in_group)

        for ev in events:
            if ev["event"] == "renewed":
                renewed += 1
            elif ev["event"] == "expired":
                expired += 1

        text = (
            f"✅ Проверка завершена\n\n"
            f"📁 Группа: {group_name}\n"
            f"📊 Проверено серверов: {checked}\n"
            f"🔄 Обновлено сертификатов: {renewed}\n"
            f"🚨 Истекло: {expired}"
        )

        keyboard = [[
            InlineKeyboardButton(
                "⬅️ Назад",
                callback_data=f"group_ssl_menu:{group_name}"
            )
        ]]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data == "cancel_add":
        await cancel_add_server(query)
    
    elif data == "cancel_edit":
        await cancel_edit_server(query)

    elif data.startswith("delete_confirm:"):
        await delete_confirm(
            query,
            data.split(":", 1)[1]
        )

    elif data.startswith("delete:"):
        await delete_server(
            query,
            data.split(":", 1)[1]
        )

    elif data.startswith("edit:"):
        await edit_server_menu(
            query,
            data.split(":", 1)[1]
        )

    elif data.startswith("edit_auth:"):
        server_id = data.split(":", 1)[1]
        server = find_server(server_id)

        if not server:
            await query.edit_message_text("❌ Сервер не найден.")
            return

        auth_type = server.get("auth_type", "password")
        key_path = server.get("key_path")

        # Проверка ключа при auth_type == "key"
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

        # Обычное меню (если ключ на месте или тип password)
        await query.edit_message_text(
            "Выберите тип аутентификации:",
            reply_markup=InlineKeyboardMarkup(build_auth_buttons(server_id))
        )

    elif data.startswith("auth_key:"):
        server_id = data.split(":", 1)[1]

        await query.edit_message_text(
            "Настройка SSH-ключа:",
            reply_markup=InlineKeyboardMarkup(
                build_key_buttons(server_id)
            )
        )

    elif data.startswith("auth_password:"):
        server_id = data.split(":", 1)[1]

        server = find_server(server_id)

        if not server:
            await query.edit_message_text(
                "❌ Сервер не найден."
            )
            return

        EDIT_SERVER_STATE[query.from_user.id] = {
            "server": server_id,
            "field": "password"
        }

        await query.message.reply_text(
            f"Введите новый пароль:\n\n{server['name']}",
            reply_markup=EDIT_CANCEL_KB
        )

    elif data.startswith("edit_sudo_password:"):
        server_id = data.split(":", 1)[1]
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

    elif data.startswith("delete_sudo_password:"):
        server_id = data.split(":", 1)[1]
        server = find_server(server_id)

        if not server:
            await query.edit_message_text("❌ Сервер не найден.")
            return

        # Формируем предупреждение в зависимости от типа авторизации
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

    elif data.startswith("delete_sudo_password_confirm:"):
        server_id = data.split(":", 1)[1]
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

    elif data.startswith("key_select:"):
        server_id = data.split(":", 1)[1]

        files = get_available_keys()
            
        keyboard = []

        for f in files:
            keyboard.append([
                InlineKeyboardButton(
                    f,
                    callback_data=f"key_use:{server_id}:{f}"
                )
            ])

        keyboard.append([
            InlineKeyboardButton(
                "⬅️ Назад",
                callback_data=f"auth_key:{server_id}"
            )
        ])

        await query.edit_message_text(
            "Выберите ключ:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("key_use:"):
        _, server_id, key_name = data.split(":", 2)

        servers = load_servers()

        current_server = None

        for server in servers:
            if server["id"] == server_id:
                current_server = server.copy()
                break

        if not current_server:
            await query.edit_message_text(
                "❌ Сервер не найден."
            )
            return

        current_server["auth_type"] = "key"
        current_server["key_path"] = (
            f"/opt/bot4vps/keys/{key_name}"
        )
        ok, error = test_connection(
            current_server
        )

        if ok:
            for i, server in enumerate(servers):
                if server["id"] == server_id:
                    servers[i] = current_server
                    break

            save_servers(servers)

            await query.edit_message_text(
                f"✅ Выбран ключ:\n\n{key_name}\n\n"
                "✅ Проверка SSH успешна."
            )

            await show_server_message(
                query.message,
                server_id
            )

            return

        PENDING_SERVER_CHANGES[
            query.from_user.id
        ] = {
            "server": current_server
        }

        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Сохранить",
                    callback_data=(
                        f"confirm_save_change:{server_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Отмена",
                    callback_data=(
                        f"cancel_save_change:{server_id}"
                    )
                )
            ]
        ]

        await query.edit_message_text(
            "⚠️ Проверка SSH не пройдена\n\n"
            f"{error}\n\n"
            "Сохранить изменения несмотря на ошибку?",
            reply_markup=InlineKeyboardMarkup(
                keyboard
            )
        )

    elif data.startswith("key_paste:"):
        server_id = data.split(":", 1)[1]

        EDIT_SERVER_STATE[query.from_user.id] = {
            "server": server_id,
            "field": "new_key"
        }

        await query.edit_message_text(
            "Вставьте приватный SSH-ключ:"
        )

    elif data.startswith("change_auth_type:"):
        server_id = data.split(":", 1)[1]
        server = find_server(server_id)

        if not server:
            await query.edit_message_text("❌ Сервер не найден.")
            return

        current = server.get("auth_type", "password")
        text = f"Текущий тип: {'Пароль' if current == 'password' else 'Ключ'}\n\nВыберите новый тип авторизации:"

        keyboard = []

        if current == "password":
            keyboard.append([
                InlineKeyboardButton("🔑 Перейти на Ключ", callback_data=f"change_to_key:{server_id}")
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("🔒 Перейти на Пароль", callback_data=f"change_to_password:{server_id}")
            ])

        keyboard.append([
            InlineKeyboardButton("❌ Отмена", callback_data=f"edit_auth:{server_id}")
        ])

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("change_to_key:"):
        server_id = data.split(":", 1)[1]
        server = find_server(server_id)

        if not server:
            await query.edit_message_text("❌ Сервер не найден.")
            return

        # Создаём отложенные изменения
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
            # Пароля нет — сразу предлагаем выбрать ключ
            await query.edit_message_text(
                "Выберите SSH-ключ:",
                reply_markup=InlineKeyboardMarkup(build_key_buttons(server_id))
            )

    elif data.startswith("change_to_password:"):
        server_id = data.split(":", 1)[1]
        server = find_server(server_id)

        if not server:
            await query.edit_message_text("❌ Сервер не найден.")
            return

        has_password = bool(server.get("password"))

        if has_password:
            # Если пароль уже есть — просто меняем тип
            servers = load_servers()
            for s in servers:
                if s["id"] == server_id:
                    s["auth_type"] = "password"
                    break
            save_servers(servers)
            await query.edit_message_text("✅ Тип авторизации изменён на Пароль.")
            await show_server_message(query.message, server_id)
        else:
            # Если пароля нет — спрашиваем подтверждение + сразу просим ввести
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

    elif data.startswith("confirm_change_to_password:"):
        server_id = data.split(":", 1)[1]

        # Меняем тип на пароль
        servers = load_servers()
        for s in servers:
            if s["id"] == server_id:
                s["auth_type"] = "password"
                break
        save_servers(servers)

        # Сразу просим ввести пароль
        EDIT_SERVER_STATE[query.from_user.id] = {
            "server": server_id,
            "field": "password"
        }

        await query.message.reply_text(
            "Введите новый пароль:",
            reply_markup=EDIT_CANCEL_KB
        )

    elif data.startswith("confirm_change_to_key:"):
        user_id = query.from_user.id
        pending = PENDING_SERVER_CHANGES.get(user_id)
        if not pending:
            await query.edit_message_text("❌ Изменения потеряны.")
            return

        server_id = data.split(":", 1)[1]

        # Пароль уже сохранён как sudo (он был в pending)
        key_path = pending["server"].get("key_path")
        key_exists = bool(key_path) and os.path.exists(key_path)

        if key_exists:
            # Всё ок — сохраняем
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
            # Ключа нет — предлагаем выбрать
            await query.edit_message_text(
                "Выберите SSH-ключ:",
                reply_markup=InlineKeyboardMarkup(build_key_buttons(server_id))
            )

    elif data.startswith("confirm_change_to_key_no:"):
        user_id = query.from_user.id
        pending = PENDING_SERVER_CHANGES.get(user_id)
        if not pending:
            await query.edit_message_text("❌ Изменения потеряны.")
            return

        server_id = data.split(":", 1)[1]

        # Удаляем пароль
        pending["server"].pop("password", None)

        key_path = pending["server"].get("key_path")
        key_exists = bool(key_path) and os.path.exists(key_path)

        if key_exists:
            # Всё ок — сохраняем
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
            # Ключа нет — предлагаем выбрать
            await query.edit_message_text(
                "Выберите SSH-ключ:",
                reply_markup=InlineKeyboardMarkup(build_key_buttons(server_id))
            )

    elif data.startswith("confirm_save_change:"):
        server_id = data.split(":", 1)[1]

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

    elif data.startswith("cancel_save_change:"):
        server_id = data.split(":", 1)[1]

        if query.from_user.id in PENDING_SERVER_CHANGES:
            del PENDING_SERVER_CHANGES[
                query.from_user.id
            ]

        await query.edit_message_text(
            "❌ Изменения отменены."
        )

        await show_server_message(
            query.message,
            server_id
        )

    elif data.startswith("delete_group_confirm:"):
        await delete_group_confirm(
            query,
            data.split(":", 1)[1]
        )

    elif data.startswith("delete_group:"):
        await delete_group(
            query,
            data.split(":", 1)[1]
        )

    elif data.startswith("group:"):
        await show_group(query, data.split(":", 1)[1])

    elif data.startswith("setgroup:"):
        group = data.split(":", 1)[1]

        if query.from_user.id not in ADD_SERVER_STATE:
            return

        ADD_SERVER_STATE[query.from_user.id]["group"] = group
        ADD_SERVER_STATE[query.from_user.id]["step"] = "name"

        await query.message.reply_text(
            f"Группа: {group.upper()}\n\nВведите имя сервера:",
            reply_markup=CANCEL_KB
        )

    elif data == "add_auth_password":
        await add_auth_password(query)

    elif data == "add_auth_key":
        await add_auth_key(query)

    elif data == "add_key_select":
        await add_key_select(query)

    elif data.startswith("add_key_use:"):
        await add_key_use(query)

    elif data == "add_key_new":
        await add_key_new(query)

    elif data.startswith("add_sudo_password:"):
        choice = data.split(":", 1)[1]
        await handle_sudo_password_choice(query, choice)

    elif data == "add_ssl_host":

        await query.message.reply_text(
            "Введите домен для проверки сертификата:",
            reply_markup=CANCEL_KB
        )

    elif data == "skip_ssl_host":

        await skip_ssl_host(
            query
        )

    elif data == "ssl_monitor_run":

        await query.answer(
            "Проверка..."
        )

        run_daily_monitor()

        await query.message.reply_text(
            "✅ SSL мониторинг выполнен."
        )
  
#Редактор 
    
    elif (
        data.startswith("edit_name:")
        or data.startswith("edit_host:")
        or data.startswith("edit_ssl_host:")
        or data.startswith("edit_port:")
        or data.startswith("edit_user:")
    ):
        action, server_id = data.split(":", 1)

        server = find_server(server_id)

        if not server:
            await query.edit_message_text(
                "Сервер не найден."
            )
            return

        field_map = {
            "edit_name": ("name", "Введите новое имя"),
            "edit_host": ("host", "Введите новый IP или домен"),
            "edit_ssl_host": ("ssl_host", "Введите домен для проверки SSL сертификата"),
            "edit_port": ("port", "Введите новый SSH порт"),
            "edit_user": ("user", "Введите нового пользователя"),
        }

        field, prompt = field_map[action]

        EDIT_SERVER_STATE[query.from_user.id] = {
            "server": server_id,
            "field": field
        }

        await query.message.reply_text(
            f"{prompt}:\n\n{server['name']}",
            reply_markup=EDIT_CANCEL_KB
        )

#----scripts

    elif data == "scripts":
        await show_scripts(query)

    elif data.startswith("script:"):
        await show_script(
            query,
            data.split(":", 1)[1]
        )

    elif data.startswith("view_script:"):
        await view_script(
            query,
            data.split(":", 1)[1]
        )

    elif data.startswith("delete_script:"):
        script_name = data.split(":", 1)[1]

        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Да",
                    callback_data=f"delete_script_confirm:{script_name}"
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Нет",
                    callback_data=f"script:{script_name}"
                )
            ]
        ]

        await query.edit_message_text(
            f"⚠️ Удалить скрипт '{script_name}'?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("delete_script_confirm:"):
        script_name = data.split(":", 1)[1]

        success, error = await delete_script(
            script_name
        )

        if not success:
            await query.edit_message_text(
                f"❌ Ошибка удаления:\n{error}"
            )
            return

        await show_scripts(query)

    elif data.startswith("run_script:"):
        await run_script_select_server(
            query,
            data.split(":", 1)[1]
        )
    
    elif data.startswith("run_script_server:"):
        _, script_name, server_id = data.split(":", 2)

        await run_script_confirm(
            query,
            script_name,
            server_id
        )

    elif data.startswith("run_script_confirm:"):
        _, script_name, server_id = data.split(":", 2)

        params = get_script_params(script_name)

        if not params:
            await run_script_with_live_progress(query, script_name, server_id, {})
            return

        SCRIPT_RUN_STATE[query.from_user.id] = {
            "script": script_name,
            "server": server_id,
            "params": params,
            "index": 0,
            "values": {}
        }

        await show_script_param(
            query,
            query.from_user.id
        )

    elif data.startswith("script_param:"):
        value = data.split(":", 1)[1]

        user_id = query.from_user.id

        state = SCRIPT_RUN_STATE.get(user_id)

        if not state:
            await query.edit_message_text(
                "❌ Состояние ввода параметров потеряно."
            )
            return

        if state["index"] >= len(state["params"]):
            await finish_script_params(
                query,
                user_id
            )
            return    
    
        param = state["params"][state["index"]]

        state["values"][param["name"]] = value

        state["index"] += 1

        if state["index"] >= len(state["params"]):
            await finish_script_params(
                query,
                user_id
            )
            return
        await show_script_param(
            query,
            user_id
        )

    elif data == "script_param_skip":
        user_id = query.from_user.id

        state = SCRIPT_RUN_STATE.get(user_id)

        if not state:
            await query.edit_message_text(
                "❌ Состояние ввода параметров потеряно."
            )
            return

        if state["index"] >= len(state["params"]):
            await finish_script_params(
                query,
                user_id
            )
            return

        param = state["params"][state["index"]]

        state["values"][param["name"]] = ""

        state["index"] += 1

        if state["index"] >= len(state["params"]):
            await finish_script_params(
                query,
                user_id
            )
            return

        await show_script_param(
            query,
            user_id
        )

    elif data == "script_execute":
        user_id = query.from_user.id
        state = SCRIPT_CONFIRM_STATE.get(user_id)

        if not state:
            await query.edit_message_text("❌ Состояние запуска потеряно.")
            return

        # Запускаем скрипт с живым выводом

        await run_script_with_live_progress(
            query=query,
            script_name=state["script"],
            server_id=state["server"],
            values=state["values"]
        )

        # Очищаем состояние
        if user_id in SCRIPT_CONFIRM_STATE:
            del SCRIPT_CONFIRM_STATE[user_id]
        
#-----------
    #elif data.startswith("server:"):
    #    await show_server(query, data.split(":", 1)[1])
    elif data.startswith("server:"):
        server_id = data.split(":", 1)[1]
        await query.answer("Открываю карточку...")
        await show_server(query, server_id)

    elif data.startswith("reboot_confirm:"):
        await reboot_confirm(query, data.split(":", 1)[1])

    elif data.startswith("reboot:"):
        await perform_reboot(query, data.split(":", 1)[1])

    elif data.startswith("edit_group:"):
        server_id = data.split(":", 1)[1]

        keyboard = build_group_buttons(
            "set_edit_group",
            server_id
        )
        keyboard.append([
            InlineKeyboardButton(
                "❌ Отмена",
                callback_data="cancel_edit"
            )
        ])

        await query.message.reply_text(
            "Выберите новую группу:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif data.startswith("set_edit_group:"):

        _, group, server_id = data.split(
            ":",
            2
        )

        servers = load_servers()

        server = None

        for item in servers:

            if item["id"] == server_id:

                server = item
                break

        if not server:

            await query.message.reply_text(
                "❌ Сервер не найден."
            )

            return

        server["group"] = group

        ssl_enabled = is_group_ssl_enabled(
            group
        )
        print("GROUP =", group)
        print("SSL =", ssl_enabled)

        if ssl_enabled:

            try:

                ipaddress.ip_address(
                    server["host"]
                )

                is_ip = True

            except ValueError:

                is_ip = False

            if is_ip:

                if server.get("ssl_host"):

                    server["certificate_check"] = True

                else:

                    save_servers(servers)

                    await start_ssl_setup(
                        query,
                        [server_id],
                        "group_change",
                        {
                            "type": "server",
                            "value": server_id
                        }
                    )

                    return

            if not server.get("ssl_host"):

                server["ssl_host"] = server["host"]

            server["certificate_check"] = True

        else:

            server["certificate_check"] = False

        save_servers(servers)

        await query.message.reply_text(
            "✅ Группа изменена."
        )

        await show_server_message(
            query.message,
            server_id
        )

    elif data == "admin":
        await show_admin_menu(query)

    elif data == "key_manager":
        await show_key_manager(query)

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
        await show_key_action(query, key_name)

    elif data.startswith("key_delete:"):
        key_name = data.split(":", 1)[1]
        await confirm_key_delete(query, key_name)

    elif data.startswith("key_delete_confirm:"):
        key_name = data.split(":", 1)[1]
        await delete_ssh_key_confirm(query, key_name)

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
        await start_key_replace(query, key_name)

    elif data == "key_paste_new":
        await start_key_paste_new(query)

    elif data.startswith("key_view_priv:"):
        key_name = data.split(":", 1)[1]
        await view_private_key(query, key_name)

    elif data == "check_all_servers":
        await query.answer("Проверка серверов...")

        # Промежуточное сообщение
        await query.edit_message_text("🔄 Проверяем все сервера...")

        from servers import get_server_info

        servers = load_servers()
        lines = []

        for server in servers:
            info = await asyncio.to_thread(get_server_info, server)

            if info["network"] == "ping":
                net_text = f"Ping {info['ping']} ms"
            elif info["network"] == "http":
                if info.get("ping"):
                    net_text = f"HTTP {info['ping']} ms"
                else:
                    net_text = "HTTP"
            else:
                net_text = "Недоступен"

            ssh_text = "✅ Доступен" if info.get("ssh") else "❌ Недоступен"

            lines.append(
                f"🖥 {server['name']}\n"
                f"   📡 Сеть: {net_text}\n"
                f"   🔐 SSH: {ssh_text}\n"
            )

        text = "📊 Проверка всех серверов\n\n" + "\n".join(lines)

        keyboard = [[
            InlineKeyboardButton("⬅️ Назад", callback_data="admin")
        ]]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
      
async def show_admin_menu(query):
    keyboard = [
        [InlineKeyboardButton("🔄 Проверить все сервера", callback_data="check_all_servers")],
        [InlineKeyboardButton("🔑 Управление SSH-ключами", callback_data="key_manager")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main")]
    ]
    await query.edit_message_text(
        "🛠 Администрирование\n\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_key_action(query, key_name):
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

async def confirm_key_delete(query, key_name):
    keyboard = [
        [InlineKeyboardButton("✅ Да, удалить", callback_data=f"key_delete_confirm:{key_name}")],
        [InlineKeyboardButton("❌ Отмена", callback_data=f"key_action:{key_name}")]
    ]

    await query.edit_message_text(
        f"⚠️ Удалить ключ `{key_name}` и его публичный ключ?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def delete_ssh_key_confirm(query, key_name):
    import os

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

async def create_new_ssh_key(query):
    import os
    import subprocess

    keys_dir = "/opt/bot4vps/keys"
    os.makedirs(keys_dir, exist_ok=True)

    # Генерируем имя ключа
    counter = 1
    while True:
        key_name = f"key_{counter}"
        key_path = os.path.join(keys_dir, key_name)
        if not os.path.exists(key_path):
            break
        counter += 1

    try:
        # Генерация ключа ed25519
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-f", key_path, "-N", ""],
            check=True,
            capture_output=True
        )

        await query.edit_message_text(
            f"✅ Ключ успешно создан:\n\n`{key_name}`",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад к ключам", callback_data="key_manager")
            ]])
        )
    except Exception as e:
        await query.edit_message_text(
            f"❌ Ошибка при создании ключа:\n{e}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад к ключам", callback_data="key_manager")
            ]])
        )

async def finish_key_creation(message, user_id, key_name):
    import os
    import subprocess

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

        # Читаем публичный ключ
        pub_key_path = key_path + ".pub"
        with open(pub_key_path, "r") as f:
            pub_key = f.read().strip()

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
        del KEY_CREATE_STATE[user_id]
        await message.reply_text(
            f"❌ Ошибка при создании ключа:\n{e}"
        )

async def finish_key_rename(message, user_id, old_key_name, new_key_name):
    import os

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

        del KEY_RENAME_STATE[user_id]

        await message.reply_text(
            f"✅ Ключ переименован:\n`{old_key_name}` → `{new_key_name}`",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад к ключам", callback_data="key_manager")
            ]])
        )
    except Exception as e:
        del KEY_RENAME_STATE[user_id]
        await message.reply_text(
            f"❌ Ошибка при переименовании:\n{e}"
        )

async def start_key_replace(query, key_name):
    KEY_REPLACE_STATE[query.from_user.id] = key_name
    await query.edit_message_text(
        f"Вставьте новый приватный ключ для `{key_name}`:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="key_manager")]])
    )

async def finish_key_replace(message, user_id, key_name, new_content):
    import os

    keys_dir = "/opt/bot4vps/keys"
    key_path = os.path.join(keys_dir, key_name)

    try:
        with open(key_path, "w", encoding="utf-8") as f:
            f.write(new_content.strip())

        del KEY_REPLACE_STATE[user_id]

        await message.reply_text(
            f"✅ Ключ `{key_name}` успешно заменён.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад к ключам", callback_data="key_manager")
            ]])
        )
    except Exception as e:
        del KEY_REPLACE_STATE[user_id]
        await message.reply_text(
            f"❌ Ошибка при замене ключа:\n{e}"
        )

async def start_key_paste_new(query):
    KEY_PASTE_NEW_STATE[query.from_user.id] = {}
    await query.edit_message_text(
        "Введите имя для нового ключа:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="key_manager")]])
    )

async def finish_key_paste_new(message, user_id, key_name, key_content):
    import os

    keys_dir = "/opt/bot4vps/keys"
    key_path = os.path.join(keys_dir, key_name)

    if os.path.exists(key_path):
        await message.reply_text(
            f"❌ Ключ с именем `{key_name}` уже существует."
        )
        del KEY_PASTE_NEW_STATE[user_id]
        return

    try:
        with open(key_path, "w", encoding="utf-8") as f:
            f.write(key_content.strip())

        del KEY_PASTE_NEW_STATE[user_id]

        await message.reply_text(
            f"✅ Ключ `{key_name}` успешно вставлен.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад к ключам", callback_data="key_manager")
            ]])
        )
    except Exception as e:
        del KEY_PASTE_NEW_STATE[user_id]
        await message.reply_text(
            f"❌ Ошибка при вставке ключа:\n{e}"
        )

async def view_private_key(query, key_name):
    import os

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

async def run_script_with_live_progress(query, script_name, server_id, values):

    server = find_server(server_id)
    server_name = server["name"] if server else server_id

    output_lines = []

    base_text = (
        f"🚀 Выполнение скрипта\n\n"
        f"📜 {script_name}\n"
        f"🖥 Сервер: {server_name}\n\n"
    )

    # Отправляем первое сообщение
    message = await query.message.reply_text(base_text + "🟡 Выполняется...")

    async def progress_callback(line: str):
        output_lines.append(line)

        # Обновляем не чаще чем раз в ~1.5 секунды
        if len(output_lines) % 2 == 0:
            display = "\n".join(output_lines[-50:])
            try:
                await message.edit_text(base_text + display)
            except Exception as e:
                print(f"[TG ERROR] {e}", flush=True)

    # === Выполняем скрипт ===
    result = await execute_script(
        script_name=script_name,
        server_id=server_id,
        values=values,
        progress_callback=progress_callback
    )

    # === Обновляем состояние сервера (SSL и т.д.) ===
    try:
        # Обновляем, если скрипт завершился успешно или с предупреждением
        if "успешно" in result or "предупреждениями" in result or "Выполнено с предупреждениями" in result:
            await asyncio.to_thread(refresh_server_state, server_id)
            print(f"[BOT] Состояние сервера {server_id} обновлено после скрипта {script_name}", flush=True)
    except Exception as e:
        print(f"[BOT] Ошибка при обновлении состояния сервера {server_id}: {e}", flush=True)

    # === Формируем финальное сообщение ===
    keyboard = [
        [InlineKeyboardButton("📜 Скрипты", callback_data="scripts")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main")]
    ]

    final_text = (
        f"✅ Выполнение завершено\n\n"
        f"📜 {script_name}\n"
        f"🖥 Сервер: {server_name}\n\n"
        f"{result}"
    )

    try:
        await message.edit_text(final_text, reply_markup=InlineKeyboardMarkup(keyboard))
    except:
        await query.message.reply_text(final_text, reply_markup=InlineKeyboardMarkup(keyboard))