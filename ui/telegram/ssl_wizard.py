import ipaddress

from core.storage import find_server
from core.ssl import is_ip_address, enable_ssl_check, disable_ssl_check
from state import SSL_SETUP_STATE
from ui.telegram.keyboards import build_certificate_buttons
from core.server_wizard import (
    validate_port,
    create_key_file,
    save_new_server,
    test_server_connection,
    update_server_field,
    update_ssl_host
)

async def send_message(target, text, reply_markup=None):
    """Универсальная отправка сообщения."""
    if hasattr(target, "message"):
        return await target.message.reply_text(
            text, reply_markup=reply_markup
        )
    return await target.reply_text(
        text, reply_markup=reply_markup
    )


async def start_ssl_setup(target, server_ids, mode, return_to):
    """Начинает процесс настройки SSL."""
    if hasattr(target, "from_user"):
        user_id = target.from_user.id
    else:
        user_id = target.message.from_user.id

    SSL_SETUP_STATE[user_id] = {
        "servers": server_ids,
        "index": 0,
        "mode": mode,
        "return_to": return_to
    }

    await process_ssl_setup(target)


async def process_ssl_setup(target):
    """Обрабатывает следующий сервер в очереди."""
    if hasattr(target, "from_user"):
        user_id = target.from_user.id
    else:
        user_id = target.message.from_user.id

    state = SSL_SETUP_STATE[user_id]

    if state["index"] >= len(state["servers"]):
        await finish_ssl_setup(target)
        return

    server_id = state["servers"][state["index"]]
    server = find_server(server_id)

    if not server:
        state["index"] += 1
        await process_ssl_setup(target)
        return

    if not is_ip_address(server["host"]):
        # Не IP — можно сразу включить
        enable_ssl_check(server_id)
        state["index"] += 1
        await process_ssl_setup(target)
        return

    # IP — просим ввести домен
    await send_message(
        target,
        f"🖥 {server['name']}\n\n"
        f"Host указан как IP:\n{server['host']}\n\n"
        "Введите домен для проверки сертификата:",
        reply_markup=build_certificate_buttons()
    )


async def handle_ssl_host(target, ssl_host: str):
    """Обработка введённого домена."""
    if hasattr(target, "from_user"):
        user_id = target.from_user.id
    else:
        user_id = target.message.from_user.id

    state = SSL_SETUP_STATE[user_id]
    server_id = state["servers"][state["index"]]

    enable_ssl_check(server_id, ssl_host)

    state["index"] += 1
    await process_ssl_setup(target)


async def skip_ssl_host(target):
    """Пропуск ввода домена."""
    if hasattr(target, "from_user"):
        user_id = target.from_user.id
    else:
        user_id = target.message.from_user.id

    state = SSL_SETUP_STATE[user_id]
    server_id = state["servers"][state["index"]]

    disable_ssl_check(server_id)

    state["index"] += 1
    await process_ssl_setup(target)


async def finish_ssl_setup(target):
    """Завершение настройки SSL."""
    if hasattr(target, "from_user"):
        user_id = target.from_user.id
    else:
        user_id = target.message.from_user.id

    state = SSL_SETUP_STATE[user_id]
    return_to = state["return_to"]

    del SSL_SETUP_STATE[user_id]

    # Очищаем состояние добавления сервера
    from state import ADD_SERVER_STATE
    ADD_SERVER_STATE.pop(user_id, None)

    # Возврат в нужное место
    if return_to["type"] == "servers":
        from ui.telegram.servers import show_servers   # предположительно
        await show_servers(target, "✅ Настройка SSL завершена.")

    elif return_to["type"] == "server":
        from ui.telegram.servers import show_server, show_server_message
        if hasattr(target, "edit_message_text"):
            await show_server(target, return_to["value"])
        else:
            await show_server_message(target, return_to["value"])

    elif return_to["type"] == "group":
        from ui.telegram.servers import show_group
        await show_group(target, return_to["value"])