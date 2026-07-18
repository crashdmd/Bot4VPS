"""
Script handlers module for Bot4VPS.

Публичный интерфейс модуля — только одна функция:
    process_script_callback(query, data) -> bool

Все остальные функции — внутренние (начинаются с _ ).
bot_handlers.py ничего не знает о внутреннем устройстве модуля.
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
from core.script_utils import get_script_params, delete_script
from core.scripts import execute_script
from core.monitor import refresh_server_state
from state import SCRIPT_RUN_STATE, SCRIPT_CONFIRM_STATE
from ui.telegram.keyboards import CANCEL_KB, EDIT_CANCEL_KB  # если нужно


# === Внутренние функции (приватные) ===

async def _run_script_with_live_progress(query, script_name, server_id, values):
    from core.storage import find_server  # правильная зависимость: core.storage, а не ui.servers

    server = find_server(server_id)
    server_name = server["name"] if server else server_id

    output_lines = []

    base_text = (
        f"🚀 Выполнение скрипта\n\n"
        f"📜 {script_name}\n"
        f"🖥 Сервер: {server_name}\n\n"
    )

    message = await query.message.reply_text(base_text + "🟡 Выполняется...")

    async def progress_callback(line: str):
        output_lines.append(line)
        if len(output_lines) % 2 == 0:
            display = "\n".join(output_lines[-50:])
            try:
                await message.edit_text(base_text + display)
            except Exception as e:
                print(f"[TG ERROR] {e}", flush=True)

    result = await execute_script(
        script_name=script_name,
        server_id=server_id,
        values=values,
        progress_callback=progress_callback
    )

    try:
        if "успешно" in result or "предупреждениями" in result or "Выполнено с предупреждениями" in result:
            await asyncio.to_thread(refresh_server_state, server_id)
            print(f"[BOT] Состояние сервера {server_id} обновлено после скрипта {script_name}", flush=True)
    except Exception as e:
        print(f"[BOT] Ошибка при обновлении состояния сервера {server_id}: {e}", flush=True)

    keyboard = [
        [InlineKeyboardButton("📜 Скрипты", callback_data="scripts")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main")]
    ]

    final_text = (
        f"✅ Выполнение завершено\n\n"
        f"📜 {script_name}\n"
        f"🖥 Сервер: {server_name}\n\n"
        f"{result}"
    )

    try:
        await message.edit_text(final_text, reply_markup=InlineKeyboardMarkup(keyboard))
    except:
        await query.message.reply_text(final_text, reply_markup=InlineKeyboardMarkup(keyboard))


# === Публичная точка входа модуля ===
async def process_script_callback(query, data: str) -> bool:
    """
    Единая публичная функция модуля Scripts.
    bot_handlers.py вызывает только её.
    """
    if data == "scripts":
        await show_scripts(query)

    elif data.startswith("script:"):
        await show_script(query, data.split(":", 1)[1])

    elif data.startswith("view_script:"):
        await view_script(query, data.split(":", 1)[1])

    elif data.startswith("delete_script:"):
        script_name = data.split(":", 1)[1]
        keyboard = [
            [InlineKeyboardButton("✅ Да", callback_data=f"delete_script_confirm:{script_name}")],
            [InlineKeyboardButton("❌ Нет", callback_data=f"script:{script_name}")]
        ]
        await query.edit_message_text(
            f"⚠️ Удалить скрипт '{script_name}'?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("delete_script_confirm:"):
        script_name = data.split(":", 1)[1]
        success, error = await delete_script(script_name)
        if not success:
            await query.edit_message_text(f"❌ Ошибка удаления:\n{error}")
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
            "script": script_name,
            "server": server_id,
            "params": params,
            "index": 0,
            "values": {}
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

        await _run_script_with_live_progress(
            query=query,
            script_name=state["script"],
            server_id=state["server"],
            values=state["values"]
        )
        if user_id in SCRIPT_CONFIRM_STATE:
            del SCRIPT_CONFIRM_STATE[user_id]

    else:
        return False

    return True

# === Обработка текстовых сообщений для скриптов ===
async def process_script_message(update, context):
    """Обработка текстовых сообщений для SCRIPT_RUN_STATE"""
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
