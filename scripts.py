import os
import asyncio

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from storage import (
    load_servers,
    find_server
)

from script_utils import (
    load_scripts,
    get_script_info,
    read_script,
    get_script_params
)

from state import (
    SCRIPT_RUN_STATE,
    SCRIPT_CONFIRM_STATE
)
from ssh_utils import create_ssh_client

async def show_scripts(query):
    scripts = load_scripts()

    keyboard = []

    for script in scripts:
        keyboard.append([
            InlineKeyboardButton(
                f"📄 {script}",
                callback_data=f"script:{script}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Назад",
            callback_data="main"
        )
    ])

    await query.edit_message_text(
        "📜 Скрипты",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_script(query, script_name):
    info = get_script_info(script_name)

    if not info:
        await query.edit_message_text(
            "Скрипт не найден."
        )
        return

    text = (
        f"📜 {script_name}\n\n"
        f"📏 Размер: {info['size']} байт\n"
        f"📄 Строк: {info['lines']}"
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "▶️ Выполнить",
                callback_data=f"run_script:{script_name}"
            )
        ],
        [
            InlineKeyboardButton(
                "👁 Просмотр",
                callback_data=f"view_script:{script_name}"
            )
        ],
        [
            InlineKeyboardButton(
                "🗑 Удалить",
                callback_data=f"delete_script:{script_name}"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Назад",
                callback_data="scripts"
            )
        ]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def view_script(query, script_name):
    content = read_script(script_name)

    if content is None:
        await query.edit_message_text(
            "Скрипт не найден."
        )
        return

    lines = content.splitlines()

    preview = "\n".join(lines[:40])

    if len(lines) > 40:
        preview += "\n\n... (обрезано)"

    text = (
        f"📜 {script_name}\n\n"
        f"```bash\n{preview}\n```"
    )

    keyboard = [[
        InlineKeyboardButton(
            "⬅️ Назад",
            callback_data=f"script:{script_name}"
        )
    ]]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def run_script_select_server(query, script_name):
    servers = load_servers()

    keyboard = []

    for server in servers:
        keyboard.append([
            InlineKeyboardButton(
                server["name"],
                callback_data=f"run_script_server:{script_name}:{server['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "❌ Отмена",
            callback_data=f"script:{script_name}"
        )
    ])

    await query.edit_message_text(
        f"📜 Выполнить {script_name}\n\nВыберите сервер:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def run_script_confirm(
    query,
    script_name,
    server_id
):
    server = find_server(server_id)

    if not server:
        await query.edit_message_text(
            "Сервер не найден."
        )
        return
    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Да",
                callback_data=f"run_script_confirm:{script_name}:{server_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "❌ Нет",
                callback_data=f"run_script:{script_name}"
            )
        ]
    ]

    await query.edit_message_text(
        (
            f"⚠️ Выполнить {script_name}\n\n"
            f"на сервере {server['name']}?"
        ),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def execute_script(script_name, server_id, values):
    server = find_server(server_id)

    if not server:
        print(f"Server not found: {server_id}", flush=True)
        return

    try:
        ssh = create_ssh_client(server)

        print(
            f"SSH connected: {server['name']}",
            flush=True
        )

        local_script = os.path.join(
            "scripts",
            script_name
        )

        remote_script = f"/tmp/{script_name}"

        sftp = ssh.open_sftp()

        sftp.put(
            local_script,
            remote_script
        )

        sftp.close()

        print(
            f"Uploaded: {remote_script}",
            flush=True
        )

        ssh.exec_command(
            f"chmod +x {remote_script}"
        )

        print(
            f"Chmod OK: {remote_script}",
            flush=True
        )

        env = []

        for key, value in values.items():
            env.append(
                f"{key}='{value}'"
            )

        command = (
            " ".join(env)
            + f" timeout 600 bash {remote_script}"
        )

        print(
            f"Executing: {command}",
            flush=True
        )

        stdin, stdout, stderr = ssh.exec_command(
            command
        )

        exit_code = stdout.channel.recv_exit_status()

        out = stdout.read().decode(
            "utf-8",
            errors="ignore"
        )

        err = stderr.read().decode(
            "utf-8",
            errors="ignore"
        )

        print(
            f"Exit code: {exit_code}",
            flush=True
        )

        print(
            f"STDOUT:\n{out}",
            flush=True
        )

        print(
            f"STDERR:\n{err}",
            flush=True
        )

        ssh.exec_command(
            f"rm -f {remote_script}"
        )

        print(
            f"Deleted: {remote_script}",
            flush=True
        )

        output = out.strip()

        if err.strip():
            output += "\n\nSTDERR:\n" + err.strip()

        lines = output.splitlines()

        if len(lines) > 50:
            output = (
                "...\n"
                "Вывод обрезан. Показаны последние 50 строк.\n\n"
                + "\n".join(lines[-50:])
            )

        ssh.close()

        if exit_code == 124:
            return (
                f"⏱ Скрипт прерван по таймауту\n\n"
                f"Сервер: {server['name']}\n"
                f"Лимит: 10 минут\n\n"
                f"{output or 'Без вывода'}"
            )

        if exit_code == 0:
            return (
                f"✅ Скрипт выполнен\n\n"
                f"Сервер: {server['name']}\n"
                f"Код возврата: {exit_code}\n\n"
                f"{output or 'Без вывода'}"
            )

        return (
            f"❌ Скрипт завершился с ошибкой\n\n"
            f"Сервер: {server['name']}\n"
            f"Код возврата: {exit_code}\n\n"
            f"{output or 'Без вывода'}"
        )

    except Exception as e:
        return (
            f"❌ Ошибка выполнения\n\n"
            f"{e}"
        )

async def show_script_param(query, user_id):
    state = SCRIPT_RUN_STATE[user_id]

    param = state["params"][state["index"]]

    while param.get("condition"):
        cond_name, cond_value = param["condition"].split(":", 1)

        if str(state["values"].get(cond_name, "")).lower() == cond_value.lower():
            break

        state["index"] += 1

        if state["index"] >= len(state["params"]):
            await finish_script_params(
                query,
                user_id
            )
            return
        param = state["params"][state["index"]]

    if param["type"] == "bool":
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Да",
                    callback_data="script_param:true"
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Нет",
                    callback_data="script_param:false"
                )
            ]
        ]

        if hasattr(query, "edit_message_text"):
            await query.edit_message_text(
                param["label"],
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.reply_text(
                param["label"],
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        return

    keyboard = [[
        InlineKeyboardButton(
            "⏭ Пропустить",
            callback_data="script_param_skip"
        )
    ]]

    if hasattr(query, "edit_message_text"):
        await query.edit_message_text(
            param["label"],
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.reply_text(
            param["label"],
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def finish_script_params(query, user_id):
    state = SCRIPT_RUN_STATE[user_id]

    SCRIPT_CONFIRM_STATE[user_id] = {
        "script": state["script"],
        "server": state["server"],
        "values": state["values"]
    }
    server = find_server(state["server"])

    if not server:
        await query.reply_text(
            "❌ Сервер не найден."
        )
        return
    lines = []

    for key, value in state["values"].items():
        if "PASS" in key:
            value = "********"

        if value == "":
            value = "<пусто>"

        lines.append(f"{key} = {value}")

    text = (
        f"📜 Скрипт: {state['script']}\n"
        f"🖥 Сервер: {server['name']}\n\n"
        f"Параметры:\n\n"
        + "\n".join(lines)
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Запустить",
                callback_data="script_execute"
            )
        ],
        [
            InlineKeyboardButton(
                "❌ Отмена",
                callback_data="scripts"
            )
        ]
    ]

    if hasattr(query, "edit_message_text"):
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    del SCRIPT_RUN_STATE[user_id]


