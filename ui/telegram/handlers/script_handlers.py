"""Script handlers for Bot4VPS.

Только скрипты: список, просмотр, удаление, мастер параметров, запуск.
Live Output задач и обобщённые task-маршруты (очередь/retry/clear/лог) живут
в ui.telegram.task_ui — этим же модулем пользуется и service_handlers.
"""

from telegram import InlineKeyboardMarkup, InlineKeyboardButton
import asyncio

from ui.telegram.scripts import (
    show_scripts,
    run_script_select_server,
    run_script_confirm,
    show_script,
    view_script,
    show_script_param,
    finish_script_params,
)
from ui.telegram import task_ui
from core.script_utils import get_script_params, delete_script
from core.scripts import enqueue_script
from core.task_manager import task_manager, TaskStatus
from core.storage import find_server
from state import SCRIPT_RUN_STATE, SCRIPT_CONFIRM_STATE
from core.upload import prompt_upload, SCRIPT_UPLOAD


# ---------- callback parsers (rsplit, устойчивы к ':' в имени) ----------

def _parse_name_page(data: str, prefix: str) -> tuple:
    """prefix + name[:page] → (name, page)."""
    rest = data[len(prefix):]
    if ":" not in rest:
        return rest, 0
    name, tail = rest.rsplit(":", 1)
    try:
        return name, int(tail)
    except ValueError:
        return rest, 0


def _parse_script_server_page(data: str, prefix: str) -> tuple:
    """
    prefix + name:server_id[:page] → (name, server_id, page)

    server_id — без ':'. page — опционально в конце.
    name может содержать ':'.
    """
    rest = data[len(prefix):]
    parts = rest.rsplit(":", 2)
    if len(parts) == 2:
        return parts[0], parts[1], 0
    if len(parts) == 3:
        a, b, c = parts
        try:
            return a, b, int(c)
        except ValueError:
            name, sid = rest.rsplit(":", 1)
            return name, sid, 0
    return rest, "", 0


async def show_scripts_hub(query):
    await query.edit_message_text(
        "📜 Скрипты\n\n"
        "Список — запуск и управление.\n"
        "Загрузить — добавить новый .sh.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📜 Список скриптов", callback_data="scripts_list")],
            [InlineKeyboardButton("📤 Загрузить новый", callback_data="script_upload")],
            [InlineKeyboardButton("⬅️ Задачи", callback_data="tasks")],
        ]),
    )


async def _run_script_with_live_progress(query, script_name, server_id, values):
    server = find_server(server_id)
    server_name = server["name"] if server else server_id
    try:
        task = await enqueue_script(script_name, server_id, values or {})
    except Exception as e:
        await query.message.reply_text(f"❌ Не удалось поставить задачу:\n{e}")
        return

    pos = task_manager.queue_position(task.id)
    ahead = task_manager.tasks_ahead(task.id)
    if task.status == TaskStatus.QUEUED and pos is not None:
        w = "задача" if ahead == 1 else ("задачи" if 2 <= ahead <= 4 else "задач")
        status_line = f"⏳ В очереди · позиция {pos} (перед вами: {ahead} {w})"
    else:
        status_line = "▶ Выполнение запущено"

    text = (
        f"🚀 {status_line}\n\n"
        f"📜 {script_name}\n🖥 {server_name}\nid: `{task.id}`\n\n"
        f"Можете пользоваться ботом дальше\nили открыть лог выполнения."
    )
    kb = task_ui.kb_started(server_id, task.id)
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)

    asyncio.create_task(
        task_ui.watch_task_background(task.id, server_id, query.get_bot(), query.message.chat_id)
    )


async def process_script_callback(query, data: str) -> bool:
    if data == "scripts":
        await show_scripts_hub(query)
    elif data == "scripts_list":
        await show_scripts(query, page=0)
    elif data.startswith("scripts_page:"):
        try:
            page = int(data.split(":", 1)[1])
        except ValueError:
            page = 0
        await show_scripts(query, page=page)
    elif data == "script_upload":
        await prompt_upload(query, SCRIPT_UPLOAD)
    elif data.startswith("script:"):
        name, page = _parse_name_page(data, "script:")
        await show_script(query, name, page=page)
    elif data.startswith("view_script:"):
        name, page = _parse_name_page(data, "view_script:")
        await view_script(query, name, page=page)
    elif data.startswith("delete_script_confirm:"):
        name, page = _parse_name_page(data, "delete_script_confirm:")
        ok, err = await delete_script(name)
        if not ok:
            await query.edit_message_text(f"❌ Ошибка удаления:\n{err}")
            return True
        await show_scripts(query, page=page)
    elif data.startswith("delete_script:"):
        name, page = _parse_name_page(data, "delete_script:")
        await query.edit_message_text(
            f"⚠️ Удалить скрипт '{name}'?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да", callback_data=f"delete_script_confirm:{name}:{page}")],
                [InlineKeyboardButton("❌ Нет", callback_data=f"script:{name}:{page}")],
            ]),
        )
    elif data.startswith("run_script_confirm:"):
        script_name, server_id, page = _parse_script_server_page(data, "run_script_confirm:")
        params = get_script_params(script_name)
        if not params:
            await _run_script_with_live_progress(query, script_name, server_id, {})
            return True
        SCRIPT_RUN_STATE[query.from_user.id] = {
            "script": script_name, "server": server_id,
            "params": params, "index": 0, "values": {}, "page": page,
        }
        await show_script_param(query, query.from_user.id)
    elif data.startswith("run_script_server:"):
        script_name, server_id, page = _parse_script_server_page(data, "run_script_server:")
        await run_script_confirm(query, script_name, server_id, page=page)
    elif data.startswith("run_script:"):
        name, page = _parse_name_page(data, "run_script:")
        await run_script_select_server(query, name, page=page)
    elif data.startswith("script_param:"):
        value = data.split(":", 1)[1]
        user_id = query.from_user.id
        state = SCRIPT_RUN_STATE.get(user_id)
        if not state:
            await query.edit_message_text("❌ Состояние ввода параметров потеряно.")
            return True
        if state["index"] >= len(state["params"]):
            await finish_script_params(query, user_id)
            return True
        param = state["params"][state["index"]]
        state["values"][param["name"]] = value
        state["index"] += 1
        if state["index"] >= len(state["params"]):
            await finish_script_params(query, user_id)
            return True
        await show_script_param(query, user_id)
    elif data == "script_param_skip":
        user_id = query.from_user.id
        state = SCRIPT_RUN_STATE.get(user_id)
        if not state:
            await query.edit_message_text("❌ Состояние ввода параметров потеряно.")
            return True
        if state["index"] >= len(state["params"]):
            await finish_script_params(query, user_id)
            return True
        param = state["params"][state["index"]]
        state["values"][param["name"]] = ""
        state["index"] += 1
        if state["index"] >= len(state["params"]):
            await finish_script_params(query, user_id)
            return True
        await show_script_param(query, user_id)
    elif data == "script_execute":
        user_id = query.from_user.id
        state = SCRIPT_CONFIRM_STATE.get(user_id)
        if not state:
            await query.edit_message_text("❌ Состояние запуска потеряно.")
            return True
        await _run_script_with_live_progress(query, state["script"], state["server"], state["values"])
        SCRIPT_CONFIRM_STATE.pop(user_id, None)
    else:
        return False
    return True


async def process_script_message(update, context):
    user_id = update.effective_user.id
    if user_id not in SCRIPT_RUN_STATE:
        return False
    state = SCRIPT_RUN_STATE[user_id]
    if state["index"] >= len(state["params"]):
        await finish_script_params(update.message, user_id)
        return True
    param = state["params"][state["index"]]
    state["values"][param["name"]] = update.message.text.strip()
    state["index"] += 1
    if state["index"] >= len(state["params"]):
        await finish_script_params(update.message, user_id)
        return True
    await show_script_param(update.message, user_id)
    return True
