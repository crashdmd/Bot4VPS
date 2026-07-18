"""
Admin handlers module for Bot4VPS.
"""

from telegram import InlineKeyboardMarkup, InlineKeyboardButton
import asyncio

from core.storage import load_servers
from core.events import get_events
from ui.telegram.servers import get_server_info


async def _show_admin_menu(query):
    keyboard = [
        [InlineKeyboardButton("🔄 Проверить все сервера", callback_data="check_all_servers")],
        [InlineKeyboardButton("📜 Просмотр уведомлений", callback_data="view_notifications")],
        [InlineKeyboardButton("🔑 Управление SSH-ключами", callback_data="key_manager")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main")]
    ]
    await query.edit_message_text(
        "🛠 Администрирование\n\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _check_all_servers(query):
    await query.answer("Проверка серверов...")
    await query.edit_message_text("🔄 Проверяем все сервера...")

    servers = load_servers()
    lines = []
    for server in servers:
        info = await asyncio.to_thread(get_server_info, server)

        if info["network"] == "ping":
            net_text = f"Ping {info['ping']} ms"
        elif info["network"] == "http":
            net_text = f"HTTP {info.get('ping', '—')} ms"
        else:
            net_text = "Недоступен"

        ssh_text = "✅ Доступен" if info.get("ssh") else "❌ Недоступен"

        lines.append(f"🖥 {server['name']}\n   📡 Сеть: {net_text}\n   🔐 SSH: {ssh_text}\n")

    text = "📊 Проверка всех серверов\n\n" + "\n".join(lines)

    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="admin")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def _clear_events_confirm(query):
    """Подтверждение очистки"""
    keyboard = [
        [InlineKeyboardButton("✅ Да, очистить", callback_data="clear_events_confirm")],
        [InlineKeyboardButton("❌ Отмена", callback_data="view_notifications")]
    ]
    await query.edit_message_text(
        "⚠️ Вы действительно хотите очистить весь журнал событий?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _clear_events(query):
    """Фактическая очистка"""
    from core.events import load_events, save_events
   
    events = load_events()
    count = len(events)
    
    if count == 0:
        await query.edit_message_text("Журнал уже пуст.")
        return

    save_events([])

    await query.edit_message_text(
        f"✅ Журнал событий очищен.\nУдалено записей: {count}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад в админку", callback_data="admin")
        ]])
    )

async def _view_notifications(query):
    """Просмотр уведомлений + кнопка очистки"""
    events = get_events(limit=30)

    if not events:
        await query.edit_message_text(
            "📭 Уведомлений пока нет.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="admin")
            ]])
        )
        return

    text = "📜 Журнал событий (последние 15)\n\n"
    for e in events[:15]:
        emoji = "🔴" if e["level"] == "critical" else "⚠️" if e["level"] == "warning" else "ℹ️"
        text += f"{emoji} {e['title']}\n   {e['timestamp'][:16]}\n\n"

    keyboard = [
        [InlineKeyboardButton("🗑 Очистить весь журнал", callback_data="clear_events")],
        [InlineKeyboardButton("⬅️ Назад в админку", callback_data="admin")]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def process_admin_callback(query, data: str) -> bool:
    if data == "admin":
        await _show_admin_menu(query)
    elif data == "check_all_servers":
        await _check_all_servers(query)
    elif data == "view_notifications":
        await _view_notifications(query)
    elif data == "clear_events":
        await _clear_events_confirm(query)   # теперь с подтверждением
    elif data == "clear_events_confirm":
        await _clear_events(query)
    else:
        return False
    return True