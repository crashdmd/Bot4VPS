from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from core.storage import load_servers, find_server
from core.script_utils import load_scripts, get_script_info, read_script, get_script_params

from state import SCRIPT_RUN_STATE, SCRIPT_CONFIRM_STATE

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
    from ui.telegram.handlers.script_handlers import _run_script_with_live_progress
    await _run_script_with_live_progress(
        query=query,
        script_name=script_name,
        server_id=server_id,
        values=values
    )