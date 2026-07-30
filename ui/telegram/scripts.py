from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from core.storage import load_servers, find_server
from core.script_utils import load_scripts, get_script_info, read_script, get_script_params

from state import SCRIPT_RUN_STATE, SCRIPT_CONFIRM_STATE


async def show_scripts(query, page: int = 0):
    scripts = sorted(load_scripts())
    per_page = 8
    total = len(scripts)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    start = page * per_page
    chunk = scripts[start:start + per_page]

    keyboard = []
    for script in chunk:
        keyboard.append([
            InlineKeyboardButton(f"📄 {script}", callback_data=f"script:{script}:{page}")
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"scripts_page:{page - 1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"scripts_page:{page + 1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="scripts")])

    text = (
        "📜 Список скриптов\n\nПока пусто."
        if total == 0
        else f"📜 Список скриптов\n\nВсего: {total}"
    )
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def show_script(query, script_name, page: int = 0):
    info = get_script_info(script_name)
    if not info:
        await query.edit_message_text("Скрипт не найден.")
        return
    text = f"📜 {script_name}\n\n📏 Размер: {info['size']} байт\n📄 Строк: {info['lines']}"
    keyboard = [
        [InlineKeyboardButton("▶️ Выполнить", callback_data=f"run_script:{script_name}:{page}")],
        [InlineKeyboardButton("👁 Просмотр", callback_data=f"view_script:{script_name}:{page}")],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_script:{script_name}:{page}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"scripts_page:{page}")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def view_script(query, script_name, page: int = 0):
    content = read_script(script_name)
    if content is None:
        await query.edit_message_text("Скрипт не найден.")
        return
    lines = content.splitlines()
    preview = "\n".join(lines[:40])
    if len(lines) > 40:
        preview += "\n\n... (обрезано)"
    text = f"📜 {script_name}\n\n```bash\n{preview}\n```"
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data=f"script:{script_name}:{page}")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def run_script_select_server(query, script_name, page: int = 0):
    servers = load_servers()
    keyboard = [
        [InlineKeyboardButton(
            s["name"],
            callback_data=f"run_script_server:{script_name}:{s['id']}:{page}",
        )]
        for s in servers
    ]
    keyboard.append([
        InlineKeyboardButton("❌ Отмена", callback_data=f"script:{script_name}:{page}")
    ])
    await query.edit_message_text(
        f"📜 Выполнить {script_name}\n\nВыберите сервер:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def run_script_confirm(query, script_name, server_id, page: int = 0):
    server = find_server(server_id)
    if not server:
        await query.edit_message_text("Сервер не найден.")
        return
    keyboard = [
        [InlineKeyboardButton(
            "✅ Да",
            callback_data=f"run_script_confirm:{script_name}:{server_id}:{page}",
        )],
        [InlineKeyboardButton(
            "❌ Нет",
            callback_data=f"run_script:{script_name}:{page}",
        )],
    ]
    await query.edit_message_text(
        f"⚠️ Выполнить {script_name}\n\nна сервере {server['name']}?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_script_param(query, user_id):
    state = SCRIPT_RUN_STATE.get(user_id)
    if not state or state.get("index", 0) >= len(state.get("params", [])):
        await finish_script_params(query, user_id)
        return
    param = state["params"][state["index"]]
    while param.get("condition"):
        try:
            cond_name, cond_value = param["condition"].split(":", 1)
        except ValueError:
            raise RuntimeError(f"Некорректное условие if= для параметра '{param['name']}'.")
        if str(state["values"].get(cond_name, "")).lower() == cond_value.lower():
            break
        state["index"] += 1
        if state["index"] >= len(state["params"]):
            await finish_script_params(query, user_id)
            return
        param = state["params"][state["index"]]

    if param["type"] == "bool":
        keyboard = [
            [InlineKeyboardButton("✅ Да", callback_data="script_param:true")],
            [InlineKeyboardButton("❌ Нет", callback_data="script_param:false")],
        ]
    elif param["type"] == "select":
        options = param.get("options", [])
        if not options:
            raise RuntimeError(f"BOT_PARAM '{param['name']}' select без BOT_OPTION.")
        keyboard = [
            [InlineKeyboardButton(opt["label"], callback_data=f"script_param:{opt['value']}")]
            for opt in options
        ]
    else:
        keyboard = [[InlineKeyboardButton("⏭ Пропустить", callback_data="script_param_skip")]]

    text = param.get("label") or param["name"]
    if hasattr(query, "edit_message_text"):
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def finish_script_params(query, user_id):
    state = SCRIPT_RUN_STATE[user_id]
    script_name = state["script"]
    server_id = state["server"]
    values = state["values"]
    server = find_server(server_id)
    if not server:
        await query.reply_text("❌ Сервер не найден.")
        SCRIPT_RUN_STATE.pop(user_id, None)
        return
    lines = []
    for key, value in values.items():
        if "PASS" in key:
            value = "********"
        if value == "":
            value = "<пусто>"
        lines.append(f"{key} = {value}")
    text = (
        f"📜 Скрипт: {script_name}\n🖥 Сервер: {server['name']}\n\n"
        f"Параметры:\n\n" + "\n".join(lines) + "\n\n🚀 Запуск..."
    )
    if hasattr(query, "edit_message_text"):
        await query.edit_message_text(text)
    else:
        await query.reply_text(text)
    SCRIPT_RUN_STATE.pop(user_id, None)
    from ui.telegram.handlers.script_handlers import _run_script_with_live_progress
    await _run_script_with_live_progress(
        query=query, script_name=script_name, server_id=server_id, values=values,
    )
