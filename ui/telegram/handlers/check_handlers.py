import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from core.servers import get_server_info
from core.monitor import (
    load_monitor,
    run_monitor,
    STATUS_ERROR,
    STATUS_EXPIRED,
    STATUS_WARNING,
)
from core.storage import (
    load_servers,
)

PRIORITY_OFFLINE = 0
PRIORITY_PARTIAL = 1
PRIORITY_FULL = 2

def format_days(days: int) -> str:
    if 11 <= days % 100 <= 14:
        return f"{days} дней"

    last = days % 10
    if last == 1:
        return f"{days} день"
    if 2 <= last <= 4:
        return f"{days} дня"

    return f"{days} дней"

async def _show_check_servers_menu(query):
    servers = load_servers()
    groups = sorted({server["group"] for server in servers})

    keyboard = [
        [InlineKeyboardButton("🖥 Проверить все серверы", callback_data="check_all_servers")]
    ]

    for group in groups:
        keyboard.append([
            InlineKeyboardButton(f"📁 {group}", callback_data=f"check_group|{group}")
        ])

    keyboard.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="admin")
    ])

    await query.edit_message_text(
        "🔍 Проверка серверов\n\nВыберите группу:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _show_group_check_menu(query, group):
    servers = [
        s for s in load_servers()
        if s["group"] == group
    ]

    has_ssl = any(
        s.get("certificate_check")
        for s in servers
    )

    if not has_ssl:
        await _check_servers(query, group)
        return

    keyboard = [
        [InlineKeyboardButton(
            "🖥 Проверить доступность",
            callback_data=f"check_availability|{group}"
        )],
        [InlineKeyboardButton(
            "🔒 Проверить SSL",
            callback_data=f"check_ssl|{group}"
        )],
        [InlineKeyboardButton(
            "⬅️ Назад",
            callback_data="check_servers_menu"
        )]
    ]

    await query.edit_message_text(
        f"📁 Группа: {group}\n\n"
        "Что необходимо проверить?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def _check_servers(query, group=None):
    await query.answer()
    await query.edit_message_text(
        "⏳ Идёт проверка доступности серверов"
        + (f" в группе {group}..." if group else "...")
    )
    servers = load_servers()
    if group:
        servers = [s for s in servers if s["group"] == group]

    stats = {
        "total": len(servers),
        "full": 0,
        "partial": 0,
        "offline": 0,
    }
    lines = []
    max_name_len = max((len(server["name"]) for server in servers), default=0)
    for server in servers:
        info = await asyncio.to_thread(get_server_info, server)

        if info["network"] == "offline":
            stats["offline"] += 1

            lines.append({
                "priority": PRIORITY_OFFLINE,
                "name": server["name"],
                "text": f"🔴 {server['name'].ljust(max_name_len)}  Недоступен"
            })

        else:
            method = "HTTP" if info["network"] == "http" else "Ping"
            if info.get("ssh"):
                stats["full"] += 1
                icon = "🟢"
            else:
                stats["partial"] += 1
                icon = "🟡"
            ping = info.get("ping", "—")
            if isinstance(ping, (int, float)):
                ping = f"{ping:.1f}".rstrip("0").rstrip(".")
            name = server["name"].ljust(max_name_len)
            line = f"{icon} {name}  {ping} ms ({method})"
            if not info.get("ssh"):
                line += "\n   🔐 SSH недоступен"
            priority = PRIORITY_FULL if info.get("ssh") else PRIORITY_PARTIAL
            lines.append({
                "priority": priority,
                "name": server["name"],
                "text": line
            })

    lines.sort(key=lambda x: (x["priority"], x["name"].lower()))

    title = f"группы {group}" if group else "всех серверов"

    text = (
        f"📊 Проверка {title}\n\n"
        f"🖥 Всего: {stats['total']}\n"
        f"🟢 Полностью доступны: {stats['full']}\n"
        f"🟡 Частично доступны: {stats['partial']}\n"
        f"🔴 Недоступны: {stats['offline']}\n"
        f"{'─' * 20}\n"
        + "\n".join(item["text"] for item in lines)
    )

    keyboard = [
        [InlineKeyboardButton("⬅️ Назад", callback_data="check_servers_menu")]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def _handle_ssl_check_now(query, group_name):
    await query.answer()
    await query.edit_message_text(
        f"⏳ Идёт проверка SSL-сертификатов в группе {group_name}..."
    )
    events = run_monitor(group_name)
    renewed = 0
    expired = 0

    servers_in_group = [
        s for s in load_servers()
        if s.get("group") == group_name and s.get("certificate_check")
    ]
    checked = len(servers_in_group)

    for ev in events:
        if ev["event"] == "renewed":
            renewed += 1
        elif ev["event"] == "expired":
            expired += 1

    monitor = load_monitor()
    rows = []

    for server in servers_in_group:
        info = monitor.get(server["id"])
        if not info:
            continue

        cert = info["certificate"]
        status = cert["status"]

        if status == STATUS_ERROR:
            priority = 0
            days = -1

            error = cert.get("error", "Ошибка")

            if "Temporary failure in name resolution" in error:
                error = "DNS"

            elif "Name or service not known" in error:
                error = "DNS"

            elif "timed out" in error.lower():
                error = "Timeout"

            elif "refused" in error.lower():
                error = "Refused"

            elif "unreachable" in error.lower():
                error = "Unreachable"

            elif len(error) > 18:
                error = error[:18] + "..."

            value = error
            icon = "⚪"

        elif status == STATUS_EXPIRED:
            priority = 1
            days = -1
            value = "Истёк"
            icon = "🔴"

        elif status == STATUS_WARNING:
            priority = 2
            days = cert["days_left"]
            value = format_days(days)
            icon = "🟡"

        else:
            priority = 3
            days = cert["days_left"]
            value = format_days(days)
            icon = "🟢"

        rows.append({
            "priority": priority,
            "days": days,
            "name": server["name"],
            "icon": icon,
            "value": value,
        })

    rows.sort(key=lambda x: (x["priority"], x["days"], x["name"].lower()))

    if rows:
        width = max(len(r["name"]) for r in rows)
    else:
        width = 0

    text = (
        "✅ Проверка SSL завершена\n\n"
        f"📁 Группа: {group_name}\n\n"
        f"📊 Проверено: {checked}\n"
        f"🔄 Обновлено: {renewed}\n"
        f"🚨 Истекло: {expired}"
    )

    if rows:
        text += "\n\n────────────────────\n"

        for row in rows:
            text += (
                f"{row['icon']} "
                f"{row['name']:<{width}}  "
                f"{row['value']}\n"
            )

    keyboard = [[InlineKeyboardButton("⬅️ Назад",callback_data=f"check_group|{group_name}")]]
    await query.edit_message_text(
        text.rstrip(),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def process_check_callback(query, data: str) -> bool:
    if data == "check_servers_menu":
        await _show_check_servers_menu(query)

    elif data == "check_all_servers":
        await _check_servers(query)

    elif data.startswith("check_group|"):
        _, group = data.split("|", 1)
        await _show_group_check_menu(query, group)

    elif data.startswith("check_availability|"):
        _, group = data.split("|", 1)
        await _check_servers(query, group)

    elif data.startswith("check_ssl|"):
        _, group = data.split("|", 1)
        await _handle_ssl_check_now(query, group)

    else:
        return False

    return True