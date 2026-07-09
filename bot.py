import json
import asyncio
import paramiko
import time
import os
import uuid
import secrets
import ipaddress
from tzlocal import get_localzone
from datetime import (
	time,
	timezone
)

from ping3 import ping
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
    Defaults
)
from storage import (
    load_servers,
    save_servers,
    load_groups,
    save_groups,
    find_server,
    ensure_server_ids,
    is_group_ssl_enabled,
)
from script_utils import (
    load_scripts,
    get_script_info,
    read_script,
    get_script_params,
    delete_script
)
from scripts import (
    execute_script,
    show_scripts,
    run_script_select_server,
    run_script_confirm,
    show_script,
    view_script,
    show_script_param,
    finish_script_params
)
from ui import (
    CANCEL_KB,
    EDIT_CANCEL_KB,
    build_group_buttons,
    build_auth_buttons,
    build_key_buttons
)
from servers import (
    show_servers,
    show_group,
    show_group_ssl_menu,
    show_server,
    show_server_message,

    edit_server_menu,

    delete_confirm,
    delete_server,

    delete_group_confirm,
    delete_group,

    reboot_confirm,
    perform_reboot
)
from server_wizard import (
    start_add_server,
    start_add_group,
    cancel_add_server,
    cancel_edit_server,
    handle_add_group,
    handle_edit_server,
    handle_add_server,
    add_auth_password,
    add_auth_key,
    add_key_use,
    add_key_select,
    add_key_new,
)
from state import (
    ADD_SERVER_STATE,
    EDIT_SERVER_STATE,
    ADD_GROUP_STATE,
    ADD_GROUP_SSL_STATE,
    SCRIPT_RUN_STATE,
    SCRIPT_CONFIRM_STATE,
    PENDING_SERVER_CHANGES,
    SSL_SETUP_STATE,
    KEY_CREATE_STATE,
    KEY_RENAME_STATE,
    KEY_REPLACE_STATE,
    KEY_PASTE_NEW_STATE
)
from ssh_utils import (
    get_available_keys,
    test_connection
)
from ssl_wizard import (
    start_ssl_setup,
    handle_ssl_host,
    skip_ssl_host
)
from notifications import (
    get_notifications,
    save_notifications
)
from monitor import (
    update_server_certificate,
    run_daily_monitor,
    run_monitor
)
from bot_handlers import (
    button,
    finish_key_creation,
    finish_key_rename,
    finish_key_replace,
    finish_key_paste_new
)
from common import is_allowed, build_main_menu, show_main_menu
# --------------------------------------------------
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

BOT_TOKEN = config["bot_token"]
ALLOWED_USERS = config["allowed_users"]

async def handle_restore(
    update,
    notification
):

    await update.effective_chat.send_message(
        "⚠️ Обнаружено повреждение файла servers.json.\n\n"
        "✅ Конфигурация автоматически восстановлена.\n\n"
        "📦 Источник:\n"
        f"{notification['data']['source']}"
    )

    return True

NOTIFICATION_HANDLERS = {

    "restore": handle_restore,

}

async def process_notifications(
    update
):

    notifications = get_notifications()

    if not notifications:

        return

    remaining = []

    for notification in notifications:

        handler = NOTIFICATION_HANDLERS.get(
            notification["type"]
        )

        if not handler:

            remaining.append(
                notification
            )

            continue

        try:

            processed = await handler(
                update,
                notification
            )

            if not processed:

                remaining.append(
                    notification
                )

        except Exception:

            remaining.append(
                notification
            )

    save_notifications(
        remaining
    )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in SSL_SETUP_STATE:

        await handle_ssl_host(
            update.message,
            update.message.text.strip()
        )

        return

    if user_id in ADD_GROUP_STATE:
        await handle_add_group(update)
        return       

    # === Новая проверка для создания ключа ===
    if user_id in KEY_CREATE_STATE:
        key_name = update.message.text.strip()
        await finish_key_creation(update.message, user_id, key_name)
        return
    # === Переименование ключа ===
    if user_id in KEY_RENAME_STATE:
        new_key_name = update.message.text.strip()
        old_key_name = KEY_RENAME_STATE[user_id]
        await finish_key_rename(update.message, user_id, old_key_name, new_key_name)
        return
    # =========================================

    if user_id in KEY_REPLACE_STATE:
        new_key_content = update.message.text
        key_name = KEY_REPLACE_STATE[user_id]
        await finish_key_replace(update.message, user_id, key_name, new_key_content)
        return

    if user_id in KEY_PASTE_NEW_STATE:
        if "name" not in KEY_PASTE_NEW_STATE[user_id]:
            key_name = update.message.text.strip()
            KEY_PASTE_NEW_STATE[user_id] = {"name": key_name}
            await update.message.reply_text("Вставьте приватный SSH-ключ:")
            return
        else:
            key_name = KEY_PASTE_NEW_STATE[user_id]["name"]
            key_content = update.message.text
            await finish_key_paste_new(update.message, user_id, key_name, key_content)
            return

    if user_id in EDIT_SERVER_STATE:
        await handle_edit_server(update)
        return

    if user_id in SCRIPT_RUN_STATE:
        state = SCRIPT_RUN_STATE[user_id]

        if state["index"] >= len(state["params"]):
            await finish_script_params(
                update.message,
                user_id
            )
            return
 
        param = state["params"][state["index"]]

        state["values"][param["name"]] = (
            update.message.text.strip()
        )

        state["index"] += 1

        if state["index"] >= len(state["params"]):
            await finish_script_params(
                update.message,
                user_id
            )
            return
        await show_script_param(
            update.message,
            user_id
        )
        return

    if user_id not in ADD_SERVER_STATE:
        return

    await handle_add_server(update)    
 
# --------------------------------------------------
async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await process_notifications(
        update
    )

    await show_main_menu(
        update
    )

async def daily_ssl_job(context):
    events = run_monitor()
    if not events:
        return

    main_menu = build_main_menu()

    for ev in events:
        if ev["event"] == "renewed":
            text = (
                f"✅ Сертификат успешно обновлён\n\n"
                f"🖥 {ev['server_name']}\n\n"
                f"Было: {ev['old_expires']}\n"
                f"Стало: {ev['new_expires']}"
            )
        elif ev["event"] == "expired":
            text = (
                f"🚨 Сертификат истёк\n\n"
                f"🖥 {ev['server_name']}\n\n"
                f"Истёк: {ev['new_expires']}"
            )
        else:
            continue

        for user_id in ALLOWED_USERS:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=main_menu
                )
            except Exception as e:
                print(f"SSL notify failed to {user_id}: {e}", flush=True)


# --------------------------------------------------
if __name__ == "__main__":
    ensure_server_ids()
    app = Application.builder().defaults(
        Defaults(tzinfo=get_localzone())
    ).token(BOT_TOKEN).build()

    app.job_queue.run_daily(
        daily_ssl_job,
        time=time(hour=6)
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", show_main_menu))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    async def post_init(application: Application) -> None:
        await application.bot.set_my_commands([
            ("start", "Запустить бота"),
            ("menu", "Открыть главное меню")   # ← добавь эту строку
        ])

    app.post_init = post_init

    print("🤖 Bot v0.2.2 started", flush=True)
    app.run_polling()