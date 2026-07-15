import os
import asyncio
import shlex

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


def log(server, text: str):
    """Безопасное логирование с именем сервера."""
    if not server:
        print(f"[?] {text}", flush=True)
        return

    name = server.get("name") or server.get("host") or "?"
    print(f"[{name}] {text}", flush=True)

async def execute_script(
    script_name: str,
    server_id: str,
    values: dict,
    progress_callback=None
):
    server = find_server(server_id)
    if not server:
        return "❌ Сервер не найден."

    ssh = None
    remote_script = f"/tmp/{script_name}"

    try:
        log(server, "Подключаемся по SSH")
        if progress_callback:
            await progress_callback("🔌 Подключаемся по SSH...")

        ssh = create_ssh_client(server)
        log(server, "SSH подключен")
        if progress_callback:
            await progress_callback("✅ SSH подключен")

        local_script = os.path.join("scripts", script_name)

        log(server, "Загружаем скрипт")
        if progress_callback:
            await progress_callback("📤 Загружаем скрипт...")

        with ssh.open_sftp() as sftp:
            sftp.put(local_script, remote_script)

        log(server, "Скрипт загружен")
        if progress_callback:
            await progress_callback("✅ Скрипт загружен")

        log(server, "Делаем скрипт исполняемым")
        if progress_callback:
            await progress_callback("🔧 Делаем скрипт исполняемым...")

        _, chmod_stdout, _ = ssh.exec_command(f"chmod +x {remote_script}")
        if chmod_stdout.channel.recv_exit_status() != 0:
            raise RuntimeError("Не удалось сделать скрипт исполняемым.")

        # Формируем переменные окружения
        env = " ".join(
            f"{key}={shlex.quote(str(value))}"
            for key, value in values.items()
        )

        is_root = server.get("user", "").lower() == "root"

        if env:
            if is_root:
                command = f"{env} timeout 600 bash {remote_script}"
            else:
                command = f"sudo -S -p '' env {env} timeout 600 bash {remote_script}"
        else:
            if is_root:
                command = f"timeout 600 bash {remote_script}"
            else:
                command = f"sudo -S -p '' timeout 600 bash {remote_script}"

        log(server, "Запускаем скрипт")
        if progress_callback:
            await progress_callback("🚀 Запускаем скрипт...")

        stdin, stdout, stderr = ssh.exec_command(command)

        if not is_root:
            stdin.write(server.get("password", "") + "\n")
            stdin.flush()
            stdin.channel.shutdown_write()

        log(server, "Команда отправлена")
        if progress_callback:
            await progress_callback("📡 Команда отправлена")

        log(server, "Ожидаем завершения...")
        if progress_callback:
            await progress_callback("⏳ Ожидаем завершения...")

        # Чтение вывода построчно
        out_lines = []
        while True:
            line = stdout.readline()
            if not line:
                if stdout.channel.exit_status_ready():
                    break
                continue

            line = line.rstrip("\n\r")
            if line.strip():
                log(server, line)
                if progress_callback:
                    try:
                        await progress_callback(line)
                    except Exception as e:
                        log(server, f"Callback error: {e}")
            out_lines.append(line + "\n")

        exit_code = stdout.channel.recv_exit_status()
        log(server, f"Скрипт завершён (код {exit_code})")

        out = "".join(out_lines)
        err = stderr.read().decode("utf-8", errors="ignore")

        output = out.strip()
        if err.strip():
            output += "\n\nSTDERR:\n" + err.strip()

        # Обрезка длинного вывода
        lines = output.splitlines()
        if len(lines) > 60:
            output = (
                "...\n"
                "Вывод обрезан. Показаны последние 60 строк.\n\n"
                + "\n".join(lines[-60:])
            )

        # === Обработка кодов возврата ===
        if exit_code == 124:
            return (
                f"⏱ Скрипт прерван по таймауту\n\n"
                f"Сервер: {server['name']}\n"
                f"Лимит: 10 минут\n\n"
                f"{output or 'Без вывода'}"
            )

        elif exit_code == 0:
            return (
                f"✅ Скрипт выполнен успешно\n\n"
                f"Сервер: {server['name']}\n\n"
                f"{output or 'Без вывода'}"
            )

        elif exit_code == 30:
            return (
                f"⚠️ Выполнено с предупреждениями\n\n"
                f"Сервер: {server['name']}\n\n"
                f"{output or 'Без вывода'}"
            )

        else:
            return (
                f"❌ Скрипт завершился с ошибкой (код {exit_code})\n\n"
                f"Сервер: {server['name']}\n\n"
                f"{output or 'Без вывода'}"
            )

    except Exception as e:
        log(server, f"Ошибка: {e}")
        if progress_callback:
            await progress_callback(f"❌ Ошибка: {e}")
        return f"❌ Ошибка выполнения скрипта\n\n{e}"

    finally:
        if ssh:
            try:
                ssh.exec_command(f"rm -f {remote_script}")
            except Exception:
                pass
            try:
                ssh.close()
            except Exception:
                pass

async def show_script_param(query, user_id):
    state = SCRIPT_RUN_STATE.get(user_id)

    # Проверка состояния
    if not state or state.get("index", 0) >= len(state.get("params", [])):
        await finish_script_params(query, user_id)
        return

    param = state["params"][state["index"]]

    # Пропускаем параметры, не подходящие по условию
    while param.get("condition"):
        try:
            cond_name, cond_value = param["condition"].split(":", 1)
        except ValueError:
            raise RuntimeError(
                f"Некорректное условие if= для параметра '{param['name']}'."
            )

        if str(state["values"].get(cond_name, "")).lower() == cond_value.lower():
            break

        state["index"] += 1
        if state["index"] >= len(state["params"]):
            await finish_script_params(query, user_id)
            return
        param = state["params"][state["index"]]

    # --------------------------------------------------
    # Формируем клавиатуру
    # --------------------------------------------------
    if param["type"] == "bool":
        keyboard = [
            [InlineKeyboardButton("✅ Да", callback_data="script_param:true")],
            [InlineKeyboardButton("❌ Нет", callback_data="script_param:false")]
        ]

    elif param["type"] == "select":
        options = param.get("options", [])
        if not options:
            raise RuntimeError(
                f"BOT_PARAM '{param['name']}' имеет тип select, "
                f"но не содержит ни одного BOT_OPTION."
            )
        keyboard = [
            [InlineKeyboardButton(opt["label"], callback_data=f"script_param:{opt['value']}")]
            for opt in options
        ]

    else:
        keyboard = [[
            InlineKeyboardButton("⏭ Пропустить", callback_data="script_param_skip")
        ]]

    # --------------------------------------------------
    # Показываем параметр
    # --------------------------------------------------
    text = param.get("label") or param["name"]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if hasattr(query, "edit_message_text"):
        await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await query.reply_text(text, reply_markup=reply_markup)

async def finish_script_params(query, user_id):
    state = SCRIPT_RUN_STATE[user_id]
    script_name = state["script"]
    server_id = state["server"]
    values = state["values"]

    server = find_server(server_id)
    if not server:
        await query.reply_text("❌ Сервер не найден.")
        if user_id in SCRIPT_RUN_STATE:
            del SCRIPT_RUN_STATE[user_id]
        return

    # Показываем параметры пользователю (кратко)
    lines = []
    for key, value in values.items():
        if "PASS" in key:
            value = "********"
        if value == "":
            value = "<пусто>"
        lines.append(f"{key} = {value}")

    text = (
        f"📜 Скрипт: {script_name}\n"
        f"🖥 Сервер: {server['name']}\n\n"
        f"Параметры:\n\n" +
        "\n".join(lines) +
        "\n\n🚀 Запуск..."
    )

    if hasattr(query, "edit_message_text"):
        await query.edit_message_text(text)
    else:
        await query.reply_text(text)

    # Очищаем состояние параметров
    if user_id in SCRIPT_RUN_STATE:
        del SCRIPT_RUN_STATE[user_id]

    # === Запускаем скрипт с живым выводом ===
    from bot_handlers import run_script_with_live_progress

    await run_script_with_live_progress(
        query=query,
        script_name=script_name,
        server_id=server_id,
        values=values
    )
