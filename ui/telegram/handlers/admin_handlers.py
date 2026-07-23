"""
Admin handlers module for Bot4VPS.
"""

from telegram import InlineKeyboardMarkup, InlineKeyboardButton

from core.events import get_events
from core.config import get_monitor_config, set_monitor_enabled, set_monitor_interval
from ui.telegram.handlers.check_handlers import process_check_callback


# Пресеты интервалов (в минутах)
ONLINE_INTERVALS = [1, 5, 10, 15, 30, 60]
SSL_INTERVALS = [60, 360, 720, 1440]  # 1ч, 6ч, 12ч, 1д


def _format_interval(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} мин"
    hours = minutes // 60
    if hours == 1:
        return "1 час"
    if hours < 24:
        return f"{hours} ч"
    days = hours // 24
    if days == 1:
        return "1 день"
    return f"{days} дн."


async def _show_admin_menu(query):
    keyboard = [
        [InlineKeyboardButton("🔍 Проверить серверы", callback_data="check_servers_menu")],
        [InlineKeyboardButton("⚙️ Автоматический мониторинг", callback_data="monitor_settings")],
        [InlineKeyboardButton("📜 Просмотр уведомлений", callback_data="view_notifications")],
        [InlineKeyboardButton("🔑 Управление SSH-ключами", callback_data="key_manager")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main")],
    ]
    await query.edit_message_text(
        "🛠 Администрирование\n\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _show_monitor_settings(query):
    """Главное меню мониторинга — список типов проверок"""
    monitor = get_monitor_config()
    online = monitor["online"]
    ssl = monitor["ssl"]

    online_status = "🟢" if online["enabled"] else "⚪"
    ssl_status = "🟢" if ssl["enabled"] else "⚪"

    text = (
        "⚙️ Настройки мониторинга\n\n"
        "Выберите тип проверки:"
    )

    keyboard = [
        [
            InlineKeyboardButton(
                f"{online_status} Статус серверов  ·  {_format_interval(online['interval'])}",
                callback_data="monitor_type:online",
            )
        ],
        [
            InlineKeyboardButton(
                f"{ssl_status} Сертификаты доменов ·  {_format_interval(ssl['interval'])}",
                callback_data="monitor_type:ssl",
            )
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin")],
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_monitor_type(query, name: str):
    """Меню конкретного типа проверки (online / ssl)"""
    monitor = get_monitor_config()
    cfg = monitor[name]

    status = "🟢 Включена" if cfg["enabled"] else "⚪ Выключена"
    title = "📡 Статус серверов" if name == "online" else "🔒 Сертификаты доменов"

    text = (
        f"{title}\n\n"
        f"Статус: {status}\n"
        f"Интервал: {_format_interval(cfg['interval'])}"
    )

    toggle_label = "🔴 Выключить" if cfg["enabled"] else "🟢 Включить"

    keyboard = [
        [InlineKeyboardButton(toggle_label, callback_data=f"monitor_toggle:{name}")],
        [InlineKeyboardButton("⏱ Интервал проверки", callback_data=f"monitor_interval_menu:{name}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="monitor_settings")],
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_interval_menu(query, name: str):
    """Меню выбора интервала"""
    monitor = get_monitor_config()
    current = monitor[name]["interval"]
    intervals = ONLINE_INTERVALS if name == "online" else SSL_INTERVALS

    title = "статуса серверов" if name == "online" else "SSL"

    text = (
        f"⏱ Интервал проверки {title}\n\n"
        f"Текущий: {_format_interval(current)}\n\n"
        "Выберите новый интервал:"
    )

    keyboard = []
    for mins in intervals:
        mark = " ✅" if mins == current else ""
        keyboard.append([
            InlineKeyboardButton(
                f"{_format_interval(mins)}{mark}",
                callback_data=f"monitor_set_interval:{name}:{mins}",
            )
        ])

    keyboard.append([
        InlineKeyboardButton("⬅️ Назад", callback_data=f"monitor_type:{name}")
    ])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def _toggle_monitor(query, name: str, context):
    monitor = get_monitor_config()
    new_enabled = not monitor[name]["enabled"]
    set_monitor_enabled(name, new_enabled)

    if context and context.application and context.application.job_queue:
        from core.monitor import schedule_monitor_jobs
        schedule_monitor_jobs(context.application.job_queue)

    status = "включена" if new_enabled else "выключена"
    title = "Проверка статуса серверов" if name == "online" else "Проверка SSL"
    await query.answer(f"{title} {status}")
    await _show_monitor_type(query, name)


async def _set_interval(query, name: str, minutes: int, context):
    set_monitor_interval(name, minutes)

    if context and context.application and context.application.job_queue:
        from core.monitor import schedule_monitor_jobs
        schedule_monitor_jobs(context.application.job_queue)

    await query.answer(f"Интервал: {_format_interval(minutes)}")
    await _show_monitor_type(query, name)


async def _clear_events_confirm(query):
    keyboard = [
        [InlineKeyboardButton("✅ Да, очистить", callback_data="clear_events_confirm")],
        [InlineKeyboardButton("❌ Отмена", callback_data="view_notifications")],
    ]
    await query.edit_message_text(
        "⚠️ Вы действительно хотите очистить весь журнал событий?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _clear_events(query):
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
        ]]),
    )


async def _view_notifications(query):
    """Просмотр уведомлений + кнопка очистки"""
    events = get_events(limit=30)

    if not events:
        await query.edit_message_text(
            "📭 Уведомлений пока нет.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="admin")
            ]]),
        )
        return

    text = "📜 Журнал событий (последние 15)\n\n"
    for e in events[:15]:
        level = e.get("level", "")
        if level == "critical":
            emoji = "🔴"
        elif level == "warning":
            emoji = "⚠️"
        else:
            emoji = "ℹ️"

        # Имя сервера из details
        details = e.get("details") or {}
        server_name = details.get("server_name") or details.get("name") or ""

        line = f"{emoji} {e['title']}"
        if server_name:
            line += f"\n   🖥 {server_name}"
        line += f"\n   {e['timestamp'][:16]}\n\n"
        text += line

    keyboard = [
        [InlineKeyboardButton("🗑 Очистить весь журнал", callback_data="clear_events")],
        [InlineKeyboardButton("⬅️ Назад в админку", callback_data="admin")],
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def process_admin_callback(query, data: str, context=None) -> bool:
    if data == "admin":
        await _show_admin_menu(query)

    elif await process_check_callback(query, data):
        return True

    elif data == "monitor_settings":
        await _show_monitor_settings(query)

    elif data.startswith("monitor_type:"):
        name = data.split(":", 1)[1]
        if name in ("online", "ssl"):
            await _show_monitor_type(query, name)

    elif data.startswith("monitor_toggle:"):
        name = data.split(":", 1)[1]
        if name in ("online", "ssl"):
            await _toggle_monitor(query, name, context)

    elif data.startswith("monitor_interval_menu:"):
        name = data.split(":", 1)[1]
        if name in ("online", "ssl"):
            await _show_interval_menu(query, name)

    elif data.startswith("monitor_set_interval:"):
        parts = data.split(":")
        if len(parts) == 3:
            name = parts[1]
            try:
                minutes = int(parts[2])
                if name in ("online", "ssl"):
                    await _set_interval(query, name, minutes, context)
            except ValueError:
                pass

    elif data == "view_notifications":
        await _view_notifications(query)

    elif data == "clear_events":
        await _clear_events_confirm(query)

    elif data == "clear_events_confirm":
        await _clear_events(query)

    else:
        return False

    return True
