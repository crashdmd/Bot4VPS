"""Script / Tasks handlers for Bot4VPS."""

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
from core.script_utils import get_script_params, delete_script
from core.scripts import enqueue_script
from core.monitor import refresh_server_state
from core.task_manager import task_manager, TaskStatus, STATUS_EMOJI
from core.storage import load_servers, find_server
from state import SCRIPT_RUN_STATE, SCRIPT_CONFIRM_STATE
from core.upload import prompt_upload, SCRIPT_UPLOAD

_LOG_VIEWS: dict[str, object] = {}


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


async def show_tasks_menu(query):
    await query.edit_message_text(
        "📋 Задачи\n\nВыберите тип:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📜 Скрипты", callback_data="scripts")],
            [InlineKeyboardButton("📋 Очереди", callback_data="task_queues")],
            [InlineKeyboardButton("⬅️ Главное меню", callback_data="main")],
        ]),
    )


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


def _kb_started(server_id: str, task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 Смотреть лог", callback_data=f"task_log:{task_id}")],
        [InlineKeyboardButton("📋 Очередь сервера", callback_data=f"task_queue:{server_id}")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main")],
    ])


def _kb_log(server_id: str, task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить лог", callback_data=f"task_log:{task_id}")],
        [InlineKeyboardButton("📋 Очередь сервера", callback_data=f"task_queue:{server_id}")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main")],
    ])


def _kb_done(server_id: str) -> list:
    rows = []
    st = task_manager.get_queue_state(server_id)
    q = task_manager.get_queue(server_id)
    if st.paused and q:
        rows.append([InlineKeyboardButton("▶ Продолжить очередь", callback_data=f"task_continue:{server_id}")])
        rows.append([
            InlineKeyboardButton("🔄 Повторить", callback_data=f"task_retry:{server_id}"),
            InlineKeyboardButton("⏹ Очистить", callback_data=f"task_clear:{server_id}"),
        ])
    elif st.paused:
        rows.append([InlineKeyboardButton("🔄 Повторить", callback_data=f"task_retry:{server_id}")])
    if q or task_manager.get_running(server_id):
        rows.append([InlineKeyboardButton("📋 Очередь сервера", callback_data=f"task_queue:{server_id}")])
    rows.append([
        InlineKeyboardButton("📜 Скрипты", callback_data="scripts"),
        InlineKeyboardButton("📋 Задачи", callback_data="tasks"),
    ])
    rows.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main")])
    return rows


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
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=_kb_started(server_id, task.id))
    except Exception:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=_kb_started(server_id, task.id))

    asyncio.create_task(
        _watch_task_background(task.id, server_id, query.get_bot(), query.message.chat_id)
    )


async def _watch_task_background(task_id: str, server_id: str, bot, chat_id: int):
    task = task_manager.get_task(task_id)
    if not task:
        return

    async def on_line(line: str):
        msg = _LOG_VIEWS.get(task_id)
        if not msg:
            return
        t = task_manager.get_task(task_id)
        if not t:
            return
        try:
            await msg.edit_text(_format_log_text(t), parse_mode="Markdown", reply_markup=_kb_log(server_id, task_id))
        except Exception:
            pass

    task_manager.subscribe_live(task_id, on_line)
    try:
        await task.wait()
    finally:
        task_manager.unsubscribe_live(task_id, on_line)

    t = task_manager.get_task(task_id) or task
    if t and t.is_successful:
        try:
            await asyncio.to_thread(refresh_server_state, server_id)
        except Exception as e:
            print(f"[BOT] refresh after task: {e}", flush=True)
    if not t:
        return

    final = _format_done_text(t)
    kb = InlineKeyboardMarkup(_kb_done(server_id))
    msg = _LOG_VIEWS.pop(task_id, None)
    if msg:
        try:
            await msg.edit_text(final, reply_markup=kb)
            return
        except Exception:
            pass
    try:
        await bot.send_message(chat_id=chat_id, text=final, reply_markup=kb)
    except Exception as e:
        print(f"[BOT] finish notify failed: {e}", flush=True)


def _format_log_text(task) -> str:
    emoji = STATUS_EMOJI.get(task.status, "•")
    body = "\n".join(task.output_lines[-40:]) or "…ожидание вывода…"
    return f"{emoji} Лог · `{task.id}`\n\n📜 {task.name}\n🖥 {task.server_name}\nСтатус: {task.status.value}\n\n{body}"


def _format_done_text(task) -> str:
    emoji = STATUS_EMOJI.get(task.status, "•")
    out = task.output_text(40)
    if task.result and task.result.output and not out:
        lines = task.result.output.splitlines()
        out = "...\n" + "\n".join(lines[-40:]) if len(lines) > 40 else task.result.output
    text = (
        f"{emoji} Задача завершена\n\n📜 {task.name}\n🖥 {task.server_name}\n"
        f"Статус: {task.status.value}\nПопытка: {task.attempt}\nДлительность: {task.duration_human()}\n"
    )
    if task.error:
        text += f"\nОшибка: {task.error}\n"
    if out:
        text += f"\n{out}"
    return text


async def _show_task_log(query, task_id: str):
    task = task_manager.get_task(task_id)
    if not task:
        await query.edit_message_text(
            "Задача не найдена.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Задачи", callback_data="tasks")],
                [InlineKeyboardButton("🏠 Меню", callback_data="main")],
            ]),
        )
        return
    text = _format_log_text(task) if not task.is_done else _format_done_text(task)
    kb = _kb_log(task.server_id, task_id) if not task.is_done else InlineKeyboardMarkup(_kb_done(task.server_id))
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
        _LOG_VIEWS[task_id] = query.message
    except Exception:
        msg = await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
        _LOG_VIEWS[task_id] = msg


async def _show_queues_overview(query):
    servers = load_servers()
    rows = []
    text_lines = ["📋 Очереди задач\n"]
    any_active = False
    for server in servers:
        sid = server["id"]
        running = task_manager.get_running(sid)
        queue = task_manager.get_queue(sid)
        st = task_manager.get_queue_state(sid)
        if not running and not queue and not st.paused:
            continue
        any_active = True
        parts = []
        if running:
            parts.append(f"▶ {running.name}")
        if queue:
            parts.append(f"⏳ +{len(queue)}")
        if st.paused:
            parts.append("⏸")
        label = f"{server['name']} · {' · '.join(parts)}"
        rows.append([InlineKeyboardButton(label, callback_data=f"task_queue:{sid}")])
        text_lines.append(f"• {label}")
    text_lines.append("\nСейчас ничего не выполняется." if not any_active else "\nВыберите сервер:")
    rows.append([InlineKeyboardButton("⬅️ Задачи", callback_data="tasks")])
    rows.append([InlineKeyboardButton("🏠 Меню", callback_data="main")])
    await query.edit_message_text("\n".join(text_lines), reply_markup=InlineKeyboardMarkup(rows))


async def _show_server_queue(query, server_id: str):
    server = find_server(server_id)
    name = server["name"] if server else server_id
    running = task_manager.get_running(server_id)
    queue = task_manager.get_queue(server_id)
    st = task_manager.get_queue_state(server_id)
    text = f"📋 Очередь · {name}\n\n"
    if st.paused:
        text += f"⏸ На паузе\nПричина: «{st.failed_task_name or '?'}»\nПовторов: {st.retry_count}\n\n"
    text += (
        f"▶ Сейчас: {running.name}\n   id: `{running.id}` · попытка {running.attempt}\n\n"
        if running else "▶ Активной задачи нет\n\n"
    )
    if queue:
        text += "⏳ В очереди:\n" + "".join(f"  {i}. {t.name}\n" for i, t in enumerate(queue, 1))
    else:
        text += "⏳ Очередь пуста\n"
    kb = []
    if running:
        kb.append([InlineKeyboardButton("📜 Лог текущей задачи", callback_data=f"task_log:{running.id}")])
    if st.paused:
        kb.append([InlineKeyboardButton("▶ Продолжить", callback_data=f"task_continue:{server_id}")])
        kb.append([
            InlineKeyboardButton("🔄 Повторить", callback_data=f"task_retry:{server_id}"),
            InlineKeyboardButton("⏹ Очистить", callback_data=f"task_clear:{server_id}"),
        ])
    kb.append([InlineKeyboardButton("🔄 Обновить", callback_data=f"task_queue:{server_id}")])
    kb.append([InlineKeyboardButton("📋 Все очереди", callback_data="task_queues")])
    kb.append([InlineKeyboardButton("⬅️ Задачи", callback_data="tasks")])
    kb.append([InlineKeyboardButton("🏠 Меню", callback_data="main")])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))


async def process_script_callback(query, data: str) -> bool:
    if data == "tasks":
        await show_tasks_menu(query)
    elif data == "noop":
        await query.answer()
    elif data == "scripts":
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
    elif data == "task_queues":
        await _show_queues_overview(query)
    elif data.startswith("task_queue:"):
        await _show_server_queue(query, data.split(":", 1)[1])
    elif data.startswith("task_log:"):
        await _show_task_log(query, data.split(":", 1)[1])
    elif data.startswith("task_continue:"):
        sid = data.split(":", 1)[1]
        ok = await task_manager.continue_queue(sid)
        await query.answer("Очередь продолжена" if ok else "Очередь не на паузе")
        await _show_server_queue(query, sid)
    elif data.startswith("task_retry:"):
        sid = data.split(":", 1)[1]
        t = await task_manager.retry_last_failed(sid)
        await query.answer(f"Повтор: {t.name}" if t else "Нечего повторять")
        await _show_server_queue(query, sid)
    elif data.startswith("task_clear:"):
        sid = data.split(":", 1)[1]
        n = await task_manager.clear_queue(sid)
        await query.answer(f"Очищено задач: {n}")
        await _show_server_queue(query, sid)
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
