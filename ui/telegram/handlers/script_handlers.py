"""Script handlers — Task Manager integration."""
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
import asyncio

from ui.telegram.scripts import (
    show_scripts, run_script_select_server, run_script_confirm,
    show_script, view_script, show_script_param, finish_script_params,
)
from core.script_utils import get_script_params, delete_script
from core.scripts import enqueue_script
from core.monitor import refresh_server_state
from core.task_manager import task_manager, TaskStatus, STATUS_EMOJI
from state import SCRIPT_RUN_STATE, SCRIPT_CONFIRM_STATE


async def _run_script_with_live_progress(query, script_name, server_id, values):
    from core.storage import find_server
    server = find_server(server_id)
    server_name = server["name"] if server else server_id
    try:
        task = await enqueue_script(script_name, server_id, values or {})
    except Exception as e:
        await query.message.reply_text(f"❌ Не удалось поставить задачу:\n{e}")
        return

    base_text = f"🚀 Задача\n\n📜 {script_name}\n🖥 {server_name}\nid: `{task.id}`\n\n"
    pos = task_manager.queue_position(task.id)
    ahead = task_manager.tasks_ahead(task.id)

    if task.status == TaskStatus.QUEUED and pos is not None:
        if ahead == 1:
            w = "задача"
        elif 2 <= ahead <= 4:
            w = "задачи"
        else:
            w = "задач"
        msg = await query.message.reply_text(
            base_text + f"⏳ В очереди\nПозиция: {pos}\nПеред вами: {ahead} {w}\n\n"
            "Когда дойдёт очередь — появится вывод.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Очередь сервера", callback_data=f"task_queue:{server_id}")],
                [InlineKeyboardButton("📜 Скрипты", callback_data="scripts")],
                [InlineKeyboardButton("🏠 Меню", callback_data="main")],
            ]),
        )
    else:
        msg = await query.message.reply_text(base_text + "▶ Выполняется...\n", parse_mode="Markdown")

    output_buf = []

    async def on_line(line: str):
        output_buf.append(line)
        if len(output_buf) % 2 != 0:
            return
        display = "\n".join(output_buf[-40:])
        try:
            await msg.edit_text(base_text + f"▶ Выполняется...\n\n{display}", parse_mode="Markdown")
        except Exception:
            pass

    task_manager.subscribe_live(task.id, on_line)
    try:
        await task.wait()
    finally:
        task_manager.unsubscribe_live(task.id, on_line)

    t = task_manager.get_task(task.id) or task
    if t.is_successful:
        try:
            await asyncio.to_thread(refresh_server_state, server_id)
        except Exception as e:
            print(f"[BOT] refresh after task: {e}", flush=True)

    emoji = STATUS_EMOJI.get(t.status, "•")
    out = t.output_text(50)
    if t.result and t.result.output and not out:
        lines = t.result.output.splitlines()
        out = "...\n" + "\n".join(lines[-50:]) if len(lines) > 50 else t.result.output

    final = (
        f"{emoji} Задача завершена\n\n📜 {t.name}\n🖥 {t.server_name}\n"
        f"Статус: {t.status.value}\nПопытка: {t.attempt}\nДлительность: {t.duration_human()}\n"
    )
    if t.error:
        final += f"\nОшибка: {t.error}\n"
    if out:
        final += f"\n{out}"

    kb = _task_result_keyboard(server_id, t)
    try:
        await msg.edit_text(final, reply_markup=InlineKeyboardMarkup(kb))
    except Exception:
        await query.message.reply_text(final, reply_markup=InlineKeyboardMarkup(kb))


def _task_result_keyboard(server_id, task):
    rows = []
    st = task_manager.get_queue_state(server_id)
    q = task_manager.get_queue(server_id)
    if st.paused and q:
        rows.append([InlineKeyboardButton("▶ Продолжить очередь", callback_data=f"task_continue:{server_id}")])
        rows.append([
            InlineKeyboardButton("🔄 Повторить", callback_data=f"task_retry:{server_id}"),
            InlineKeyboardButton("⏹ Очистить очередь", callback_data=f"task_clear:{server_id}"),
        ])
    elif st.paused:
        rows.append([InlineKeyboardButton("🔄 Повторить", callback_data=f"task_retry:{server_id}")])
    if q or task_manager.get_running(server_id):
        rows.append([InlineKeyboardButton("📋 Очередь сервера", callback_data=f"task_queue:{server_id}")])
    rows.append([InlineKeyboardButton("📜 Скрипты", callback_data="scripts")])
    rows.append([InlineKeyboardButton("🏠 Меню", callback_data="main")])
    return rows


async def _show_server_queue(query, server_id):
    from core.storage import find_server
    server = find_server(server_id)
    name = server["name"] if server else server_id
    running = task_manager.get_running(server_id)
    queue = task_manager.get_queue(server_id)
    st = task_manager.get_queue_state(server_id)
    text = f"📋 Очередь · {name}\n\n"
    if st.paused:
        text += f"⏸ На паузе\nПричина: «{st.failed_task_name or '?'}»\nПовторов: {st.retry_count}\n\n"
    if running:
        text += f"▶ Сейчас: {running.name}\n   id: {running.id} · попытка {running.attempt}\n\n"
    else:
        text += "▶ Активной задачи нет\n\n"
    if queue:
        text += "⏳ В очереди:\n"
        for i, t in enumerate(queue, 1):
            text += f"  {i}. {t.name}\n"
    else:
        text += "⏳ Очередь пуста\n"
    kb = []
    if st.paused:
        kb.append([InlineKeyboardButton("▶ Продолжить", callback_data=f"task_continue:{server_id}")])
        kb.append([
            InlineKeyboardButton("🔄 Повторить", callback_data=f"task_retry:{server_id}"),
            InlineKeyboardButton("⏹ Очистить", callback_data=f"task_clear:{server_id}"),
        ])
    kb.append([InlineKeyboardButton("🔄 Обновить", callback_data=f"task_queue:{server_id}")])
    kb.append([InlineKeyboardButton("📜 Скрипты", callback_data="scripts")])
    kb.append([InlineKeyboardButton("🏠 Меню", callback_data="main")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))


async def process_script_callback(query, data: str) -> bool:
    if data == "scripts":
        await show_scripts(query)
    elif data.startswith("script:"):
        await show_script(query, data.split(":", 1)[1])
    elif data.startswith("view_script:"):
        await view_script(query, data.split(":", 1)[1])
    elif data.startswith("delete_script:"):
        name = data.split(":", 1)[1]
        await query.edit_message_text(
            f"⚠️ Удалить скрипт '{name}'?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да", callback_data=f"delete_script_confirm:{name}")],
                [InlineKeyboardButton("❌ Нет", callback_data=f"script:{name}")],
            ]),
        )
    elif data.startswith("delete_script_confirm:"):
        name = data.split(":", 1)[1]
        ok, err = await delete_script(name)
        if not ok:
            await query.edit_message_text(f"❌ Ошибка удаления:\n{err}")
            return True
        await show_scripts(query)
    elif data.startswith("run_script:"):
        await run_script_select_server(query, data.split(":", 1)[1])
    elif data.startswith("run_script_server:"):
        _, script_name, server_id = data.split(":", 2)
        await run_script_confirm(query, script_name, server_id)
    elif data.startswith("run_script_confirm:"):
        _, script_name, server_id = data.split(":", 2)
        params = get_script_params(script_name)
        if not params:
            await _run_script_with_live_progress(query, script_name, server_id, {})
            return True
        SCRIPT_RUN_STATE[query.from_user.id] = {
            "script": script_name, "server": server_id,
            "params": params, "index": 0, "values": {},
        }
        await show_script_param(query, query.from_user.id)
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
    elif data.startswith("task_queue:"):
        await _show_server_queue(query, data.split(":", 1)[1])
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
