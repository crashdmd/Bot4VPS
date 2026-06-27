import ipaddress
from storage import (
    load_servers,
    save_servers,
    find_server
)

from state import (
    SSL_SETUP_STATE
)

from ui import (
    build_certificate_buttons
)

from monitor import (
    update_server_certificate
)

async def send_message(target, text, reply_markup=None):

    if hasattr(target, "message"):

        return await target.message.reply_text(
            text,
            reply_markup=reply_markup
        )

    return await target.reply_text(
        text,
        reply_markup=reply_markup
    )

async def start_ssl_setup(
    target,
    server_ids,
    mode,
    return_to
):
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

    await process_ssl_setup(
        target
    )

async def process_ssl_setup(
    target
):
    if hasattr(target, "from_user"):

        user_id = target.from_user.id

    else:

        user_id = target.message.from_user.id
    state = SSL_SETUP_STATE[user_id]

    if state["index"] >= len(state["servers"]):

        await finish_ssl_setup(
            target
        )

        return

    server_id = state["servers"][
        state["index"]
    ]

    server = find_server(server_id)

    if not server:

        state["index"] += 1

        await process_ssl_setup(
            target
        )

        return

    try:

        ipaddress.ip_address(
            server["host"]
        )

        is_ip = True

    except ValueError:

        is_ip = False

    if not is_ip:

        if not server.get("ssl_host"):

            server["ssl_host"] = server["host"]

        server["certificate_check"] = True

        servers = load_servers()

        for i, item in enumerate(servers):

            if item["id"] == server_id:

                servers[i] = server

                break

        save_servers(
            servers
        )

        update_server_certificate(
            server
        )

        state["index"] += 1

        await process_ssl_setup(
            target
        )

        return

    await send_message(
        target,
        (
            f"🖥 {server['name']}\n\n"
            f"Host указан как IP:\n"
            f"{server['host']}\n\n"
            "Введите домен для проверки сертификата:"
        ),
        reply_markup=build_certificate_buttons()
    )

async def handle_ssl_host(
    target,
    ssl_host
):
    if hasattr(target, "from_user"):

        user_id = target.from_user.id

    else:

        user_id = target.message.from_user.id

    state = SSL_SETUP_STATE[user_id]

    server_id = state["servers"][
        state["index"]
    ]

    server = find_server(server_id)

    if not server:

        state["index"] += 1

        await process_ssl_setup(
            target
        )

        return

    server["ssl_host"] = ssl_host.strip()
    server["certificate_check"] = True

    servers = load_servers()

    for i, item in enumerate(servers):

        if item["id"] == server_id:

            servers[i] = server

            break

    save_servers(
        servers
    )

    update_server_certificate(
        server
    )

    state["index"] += 1

    await process_ssl_setup(
        target
    )

async def skip_ssl_host(
    target
):
    if hasattr(target, "from_user"):

        user_id = target.from_user.id

    else:

        user_id = target.message.from_user.id

    state = SSL_SETUP_STATE[user_id]

    server_id = state["servers"][
        state["index"]
    ]

    server = find_server(server_id)

    if not server:

        state["index"] += 1

        await process_ssl_setup(
            target
        )

        return

    server["certificate_check"] = False

    servers = load_servers()

    for i, item in enumerate(servers):

        if item["id"] == server_id:

            servers[i] = server

            break

    save_servers(servers)

    state["index"] += 1

    await process_ssl_setup(
        target
    )

async def finish_ssl_setup(
    target
):
    if hasattr(target, "from_user"):

        user_id = target.from_user.id

    else:

        user_id = target.message.from_user.id

    state = SSL_SETUP_STATE[user_id]

    return_to = state["return_to"]

    del SSL_SETUP_STATE[user_id]

    from state import ADD_SERVER_STATE

    ADD_SERVER_STATE.pop(
        user_id,
        None
    )

    if return_to["type"] == "servers":

        from servers import show_servers

        await show_servers(
            target,
            "✅ Настройка SSL завершена."
        )

        return

    if return_to["type"] == "server":

        if hasattr(target, "edit_message_text"):

            from servers import show_server

            await show_server(
                target,
                return_to["value"]
            )

        else:

            from servers import show_server_message

            await show_server_message(
                target,
                return_to["value"]
            )

        return

    if return_to["type"] == "group":

        from servers import show_group

        await show_group(
            target,
            return_to["value"]
        )