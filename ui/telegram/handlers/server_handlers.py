"""
Server handlers module for Bot4VPS.

Управление серверами: список, карточки, редактирование, группы, reboot, удаление.

Публичный интерфейс модуля — только одна функция:
    process_server_callback(query, data) -> bool

Все остальные функции — внутренние.
"""

from telegram import InlineKeyboardMarkup, InlineKeyboardButton

import ipaddress

from core.storage import (
    load_servers,
    save_servers,
    load_groups,
    save_groups,
    find_server,
    is_group_ssl_enabled,
)
from core.monitor import (
    run_monitor,
    update_server_certificate,
    load_monitor,
    STATUS_VALID,
    STATUS_WARNING,
    STATUS_EXPIRED,
    STATUS_ERROR,
)
from ui.telegram.servers import (
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
from ui.telegram.server_wizard import (
    start_add_server,
    start_add_group,
    cancel_add_server,
    cancel_edit_server,
)
from ui.telegram.ssl_wizard import start_ssl_setup, skip_ssl_host


# === Внутренние функции ===

async def _handle_group_ssl(query, data):
    parts = data.split(":")
    mode = parts[1]
    ssl_monitor = (mode == "on")
    user_id = query.from_user.id

    # Создание новой группы
    if len(parts) == 2:
        from state import ADD_GROUP_STATE
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
        await show_servers(query, "✅ Группа добавлена.")
        return

    # Изменение существующей группы
    group_name = parts[2]
    groups = load_groups()
    changed = False
    for group in groups:
        if group["name"] == group_name:
            group["ssl_monitor"] = ssl_monitor
            changed = True
            break

    if not changed:
        await query.edit_message_text("❌ Группа не найдена.")
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
                ipaddress.ip_address(server["host"])
                is_ip = True
            except ValueError:
                is_ip = False

            if is_ip:
                if server.get("ssl_host"):
                    update_server_certificate(server)
                else:
                    ssl_setup.append(server["id"])
            else:
                if not server.get("ssl_host"):
                    server["ssl_host"] = server["host"]
                update_server_certificate(server)
        else:
            server["certificate_check"] = False
        changed_servers = True

    if changed_servers:
        save_servers(servers)

    if ssl_setup:
        await start_ssl_setup(
            query, ssl_setup, "group_ssl",
            {"type": "group", "value": group_name}
        )
        return

    await show_group(query, group_name)


async def _handle_setgroup(query, data):
    from state import ADD_SERVER_STATE
    group = data.split(":", 1)[1]

    if query.from_user.id not in ADD_SERVER_STATE:
        return

    ADD_SERVER_STATE[query.from_user.id]["group"] = group
    ADD_SERVER_STATE[query.from_user.id]["step"] = "name"

    from ui.telegram.keyboards import CANCEL_KB
    await query.message.reply_text(
        f"Группа: {group.upper()}\n\nВведите имя сервера:",
        reply_markup=CANCEL_KB
    )


async def _handle_edit_group(query, data):
    from ui.telegram.keyboards import build_group_buttons
    server_id = data.split(":", 1)[1]

    keyboard = build_group_buttons("set_edit_group", server_id)
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_edit")])

    await query.message.reply_text(
        "Выберите новую группу:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _handle_set_edit_group(query, data):
    _, group, server_id = data.split(":", 2)

    servers = load_servers()
    server = None
    for item in servers:
        if item["id"] == server_id:
            server = item
            break

    if not server:
        await query.message.reply_text("❌ Сервер не найден.")
        return

    server["group"] = group
    ssl_enabled = is_group_ssl_enabled(group)

    if ssl_enabled:
        try:
            ipaddress.ip_address(server["host"])
            is_ip = True
        except ValueError:
            is_ip = False

        if is_ip:
            if server.get("ssl_host"):
                server["certificate_check"] = True
            else:
                save_servers(servers)
                await start_ssl_setup(
                    query, [server_id], "group_change",
                    {"type": "server", "value": server_id}
                )
                return
        if not server.get("ssl_host"):
            server["ssl_host"] = server["host"]
        server["certificate_check"] = True
    else:
        server["certificate_check"] = False

    save_servers(servers)
    # Если новая группа требует SSL — запускаем проверку
    if ssl_enabled:
        try:
            ipaddress.ip_address(server["host"])
            is_ip = True
        except ValueError:
            is_ip = False

        if is_ip and not server.get("ssl_host"):
            await start_ssl_setup(
                query, [server_id], "group_change",
                {"type": "server", "value": server_id}
            )
            return
        else:
            update_server_certificate(server)
            await query.message.reply_text("✅ Группа изменена. SSL-проверка запущена.")
            await show_server_message(query.message, server_id)
            return
    await query.message.reply_text("✅ Группа изменена.")
    await show_server_message(query.message, server_id)


async def _handle_edit_field(query, data):
    from state import EDIT_SERVER_STATE
    action, server_id = data.split(":", 1)

    server = find_server(server_id)
    if not server:
        await query.edit_message_text("Сервер не найден.")
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

    from ui.telegram.keyboards import EDIT_CANCEL_KB
    await query.message.reply_text(
        f"{prompt}:\n\n{server['name']}",
        reply_markup=EDIT_CANCEL_KB
    )


# === Публичная точка входа ===
async def process_server_callback(query, data: str) -> bool:
    """
    Единая публичная функция модуля Server.
    """
    if data == "servers":
        await show_servers(query)

    elif data == "add_server":
        await start_add_server(query)

    elif data == "add_group":
        await start_add_group(query)

    elif data.startswith("group_ssl:"):
        await _handle_group_ssl(query, data)

    elif data.startswith("group_ssl_menu:"):
        await show_group_ssl_menu(query, data.split(":", 1)[1])

    elif data == "cancel_add":
        await cancel_add_server(query)

    elif data == "cancel_edit":
        await cancel_edit_server(query)

    elif data.startswith("delete_confirm:"):
        await delete_confirm(query, data.split(":", 1)[1])

    elif data.startswith("delete:"):
        await delete_server(query, data.split(":", 1)[1])

    elif data.startswith("edit:"):
        await edit_server_menu(query, data.split(":", 1)[1])

    elif data.startswith("group:"):
        await show_group(query, data.split(":", 1)[1])

    elif data.startswith("setgroup:"):
        await _handle_setgroup(query, data)

    elif data == "add_ssl_host":
        from ui.telegram.keyboards import CANCEL_KB
        await query.message.reply_text(
            "Введите домен для проверки сертификата:",
            reply_markup=CANCEL_KB
        )

    elif data == "skip_ssl_host":
        await skip_ssl_host(query)

    elif data == "ssl_monitor_run":
        await query.answer("Проверка...")

        try:
            from core.monitor import run_daily_monitor
            events = run_daily_monitor()
            print(f"[SSL] run_daily_monitor выполнен, событий: {len(events) if events else 0}")
        except Exception as e:
            print(f"[SSL] Ошибка запуска run_daily_monitor: {e}")

        await query.message.reply_text("✅ SSL мониторинг выполнен.")

    elif (
        data.startswith("edit_name:") or
        data.startswith("edit_host:") or
        data.startswith("edit_ssl_host:") or
        data.startswith("edit_port:") or
        data.startswith("edit_user:")
    ):
        await _handle_edit_field(query, data)

    elif data.startswith("server:"):
        server_id = data.split(":", 1)[1]
        await query.answer("Открываю карточку...")
        await show_server(query, server_id)

    elif data.startswith("reboot_confirm:"):
        await reboot_confirm(query, data.split(":", 1)[1])

    elif data.startswith("reboot:"):
        await perform_reboot(query, data.split(":", 1)[1])

    elif data.startswith("edit_group:"):
        await _handle_edit_group(query, data)

    elif data.startswith("set_edit_group:"):
        await _handle_set_edit_group(query, data)

    elif data.startswith("delete_group_confirm:"):
        await delete_group_confirm(query, data.split(":", 1)[1])

    elif data.startswith("delete_group:"):
        await delete_group(query, data.split(":", 1)[1])

    else:
        return False

    return True


async def process_server_message(update, context):
    """Полная обработка текстовых сообщений для серверов"""
    user_id = update.effective_user.id

    from state import ADD_SERVER_STATE, EDIT_SERVER_STATE, ADD_GROUP_STATE, SSL_SETUP_STATE
    from ui.telegram.server_wizard import (
        handle_add_server,
        handle_edit_server,
        handle_add_group
    )
    from ui.telegram.ssl_wizard import handle_ssl_host

    if user_id in SSL_SETUP_STATE:
        await handle_ssl_host(update.message, update.message.text.strip())
        return True

    if user_id in ADD_GROUP_STATE:
        await handle_add_group(update)
        return True

    if user_id in ADD_SERVER_STATE:
        await handle_add_server(update)
        return True

    if user_id in EDIT_SERVER_STATE:
        await handle_edit_server(update)
        return True

    return False
