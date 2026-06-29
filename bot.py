import json
import asyncio
import paramiko
import time
import os
import uuid
import secrets
import ipaddress
from tzlocal import get_localzone
from datetime import (
	time,
	timezone
)

from ping3 import ping
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
    Defaults
)
from storage import (
    load_servers,
    save_servers,
    load_groups,
    save_groups,
    find_server,
    ensure_server_ids,
    is_group_ssl_enabled,
)
from script_utils import (
    load_scripts,
    get_script_info,
    read_script,
    get_script_params,
    delete_script
)
from scripts import (
    execute_script,
    show_scripts,
    run_script_select_server,
    run_script_confirm,
    show_script,
    view_script,
    show_script_param,
    finish_script_params
)
from ui import (
    CANCEL_KB,
    EDIT_CANCEL_KB,
    build_group_buttons,
    build_auth_buttons,
    build_key_buttons
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
    perform_reboot
)
from server_wizard import (
    start_add_server,
    start_add_group,
    cancel_add_server,
    cancel_edit_server,
    handle_add_group,
    handle_edit_server,
    handle_add_server,
    add_auth_password,
    add_auth_key,
    add_key_use,
    add_key_select,
    add_key_new,
)
from state import (
    ADD_SERVER_STATE,
    EDIT_SERVER_STATE,
    ADD_GROUP_STATE,
    ADD_GROUP_SSL_STATE,
    SCRIPT_RUN_STATE,
    SCRIPT_CONFIRM_STATE,
    PENDING_SERVER_CHANGES,
    SSL_SETUP_STATE
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
from notifications import (
    get_notifications,
    save_notifications
)
from monitor import (
    update_server_certificate,
    run_daily_monitor,
    run_monitor
)
# --------------------------------------------------
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

BOT_TOKEN = config["bot_token"]
ALLOWED_USERS = config["allowed_users"]
def is_allowed(user_id):
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
        # Пытаемся отредактировать текущее сообщение
        if hasattr(query_or_update, "edit_message_text"):
            await query_or_update.edit_message_text(
                text,
                reply_markup=build_main_menu()
            )
        else:
            await query_or_update.message.edit_message_text(
                text,
                reply_markup=build_main_menu()
            )
    except Exception:
        # Если не получилось отредактировать — отправляем новое
        if hasattr(query_or_update, "message"):
            await query_or_update.message.reply_text(
                text,
                reply_markup=build_main_menu()
            )
        else:
            await query_or_update.reply_text(
                text,
                reply_markup=build_main_menu()
            )

async def handle_restore(
    update,
    notification
):

    await update.effective_chat.send_message(
        "⚠️ Обнаружено повреждение файла servers.json.\n\n"
        "✅ Конфигурация автоматически восстановлена.\n\n"
        "📦 Источник:\n"
        f"{notification['data']['source']}"
    )

    return True

NOTIFICATION_HANDLERS = {

    "restore": handle_restore,

}

async def process_notifications(
    update
):

    notifications = get_notifications()

    if not notifications:

        return

    remaining = []

    for notification in notifications:

        handler = NOTIFICATION_HANDLERS.get(
            notification["type"]
        )

        if not handler:

            remaining.append(
                notification
            )

            continue

        try:

            processed = await handler(
                update,
                notification
            )

            if not processed:

                remaining.append(
                    notification
                )

        except Exception:

            remaining.append(
                notification
            )

    save_notifications(
        remaining
    )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in SSL_SETUP_STATE:

        await handle_ssl_host(
            update.message,
            update.message.text.strip()
        )

        return

    if user_id in ADD_GROUP_STATE:
        await handle_add_group(update)
        return       

    if user_id in EDIT_SERVER_STATE:
        await handle_edit_server(update)
        return

    if user_id in SCRIPT_RUN_STATE:
        state = SCRIPT_RUN_STATE[user_id]

        if state["index"] >= len(state["params"]):
            await finish_script_params(
                update.message,
                user_id
            )
            return
 
        param = state["params"][state["index"]]

        state["values"][param["name"]] = (
            update.message.text.strip()
        )

        state["index"] += 1

        if state["index"] >= len(state["params"]):
            await finish_script_params(
                update.message,
                user_id
            )
            return
        await show_script_param(
            update.message,
            user_id
        )
        return

    if user_id not in ADD_SERVER_STATE:
        return

    await handle_add_server(update)
    
 
# --------------------------------------------------
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await process_notifications(
        update
    )

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

        await query.edit_message_text(
            "Выберите тип аутентификации:",
            reply_markup=InlineKeyboardMarkup(
                build_auth_buttons(server_id)
            )
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
        current_server.pop("password", None)

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
            await query.edit_message_text(
                "   Запуск скрипта..."
            )

            result = await execute_script(
                script_name,
                server_id,
                {}
            )

            keyboard = [
                [
                    InlineKeyboardButton(
                        "📜 Скрипты",
                        callback_data="scripts"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏠 Главное меню",
                        callback_data="main"
                    )
                ]
            ]

            await query.edit_message_text(
                result,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

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
            await query.edit_message_text(
                "❌ Состояние запуска потеряно."
            )
            return

        await query.edit_message_text(
            "🚀 Запуск скрипта..."
        )

        result = await execute_script(
            state["script"],
            state["server"],
            state["values"]
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "📜 Скрипты",
                    callback_data="scripts"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 Главное меню",
                    callback_data="main"
                )
            ]
        ]

        await query.edit_message_text(
            result or "❌ Скрипт не вернул результат",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        del SCRIPT_CONFIRM_STATE[user_id]
        
#-----------
    elif data.startswith("server:"):
        await show_server(query, data.split(":", 1)[1])

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

    elif data == "check_all_servers":
        await query.answer("Проверка серверов...")

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

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await process_notifications(
        update
    )

    await show_main_menu(
        update
    )

async def daily_ssl_job(context):
    events = run_monitor()
    if not events:
        return

    main_menu = build_main_menu()

    for ev in events:
        if ev["event"] == "renewed":
            text = (
                f"✅ Сертификат успешно обновлён\n\n"
                f"🖥 {ev['server_name']}\n\n"
                f"Было: {ev['old_expires']}\n"
                f"Стало: {ev['new_expires']}"
            )
        elif ev["event"] == "expired":
            text = (
                f"🚨 Сертификат истёк\n\n"
                f"🖥 {ev['server_name']}\n\n"
                f"Истёк: {ev['new_expires']}"
            )
        else:
            continue

        for user_id in ALLOWED_USERS:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=main_menu
                )
            except Exception as e:
                print(f"SSL notify failed to {user_id}: {e}", flush=True)

async def show_admin_menu(query):
    keyboard = [
        [InlineKeyboardButton("🔄 Проверить все сервера", callback_data="check_all_servers")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main")]
    ]
    await query.edit_message_text(
        "🛠 Администрирование\n\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --------------------------------------------------
if __name__ == "__main__":
    ensure_server_ids()

    app = Application.builder().defaults(
        Defaults(tzinfo=get_localzone())
    ).token(BOT_TOKEN).build()

    app.job_queue.run_daily(
        daily_ssl_job,
        time=time(hour=6)
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    print("🤖 Bot v0.2.2 started", flush=True)

    app.run_polling()