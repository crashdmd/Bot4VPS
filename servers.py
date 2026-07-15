import asyncio
import time
import socket

from ping3 import ping

from telegram import (
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

from storage import (
    load_servers,
    save_servers,
    load_groups,
    save_groups,
    find_server,
    get_group
)
from ui import build_group_buttons
from ssh_utils import create_ssh_client
from monitor import (
    format_certificate,
    get_server_monitor
)

def get_server_info(server):
    result = {
        "ping": None,
        "network": "none",
        "ssh": False,
        "ssh_error": None,
        "uptime": "N/A",
        "load": "N/A",
        "ram": "N/A",
        "disk": "N/A"
    }

    host = server["host"]

    # 1. Обычный ping
    try:
        latency = ping(host, timeout=2)
        if latency:
            result["ping"] = round(latency * 1000, 1)
            result["network"] = "ping"
    except:
        pass

    # 2. TCP fallback с надёжным измерением времени
    if result["network"] == "none":
        for port in (80, 443):
            sock = None
            try:
                start = time.perf_counter()
                sock = socket.create_connection((host, port), timeout=3)
                duration = round((time.perf_counter() - start) * 1000, 1)
                result["ping"] = duration
                result["network"] = "http"
                break
            except:
                continue
            finally:
                if sock:
                    try:
                        sock.close()
                    except:
                        pass

    # 3. SSH + системная информация
    try:
        ssh = create_ssh_client(server)
        result["ssh"] = True

        cmds = {
            "uptime": "uptime -p",
            "load": "cat /proc/loadavg | awk '{print $1\" \"$2\" \"$3}'",
            "ram": "free -m | awk '/Mem:/ {print $3\" MB / \"$2\" MB\"}'",
            "disk": "df -h / | awk 'NR==2 {print $3\" / \"$2}'",
        }
        for k, cmd in cmds.items():
            _, out, _ = ssh.exec_command(cmd)
            result[k] = out.read().decode().strip() or "N/A"
        ssh.close()
    except Exception as e:
        result["ssh_error"] = str(e)
        print(
            f"Info error {server.get('name')}: {e}",
            flush=True
        )

    return result

def format_ssh_error(error):
    if not error:
        return "Неизвестная ошибка."

    text = error.lower()

    if "authentication failed" in text:
        return (
            "Ошибка аутентификации.\n"
            "Проверьте пароль или SSH-ключ."
        )

    if (
        "password authentication failed" in text
        or "publickey" in text
    ):
        return (
            "Для подключения к серверу "
            "необходимо использовать SSH-ключ."
        )

    if "connection refused" in text:
        return (
            "SSH-порт недоступен.\n"
            "Проверьте настройки сервера."
        )

    if (
        "network is unreachable" in text
        or "errno 101" in text
    ):
        return (
            "Сеть недоступна.\n"
            "Проверьте IP-адрес, сетевое "
            "подключение или маршрут до сервера."
        )

    if (
        "timed out" in text
        or "timeout" in text
    ):
        return (
            "Сервер не отвечает.\n"
            "Проверьте доступность сервера "
            "или соединение."
        )

    if (
        "no valid connections" in text
        or "unable to connect" in text
    ):
        return (
            "Не удалось подключиться "
            "к SSH-серверу."
        )

    if "no such file" in text:
        return (
            "Файл SSH-ключа не найден."
        )

    return error

def reboot_server(server):
    try:
        ssh = create_ssh_client(server)

        cmd = "/sbin/reboot" if server["user"].lower() == "root" else "sudo /sbin/reboot"
        print(f"→ Executing on {server['name']}: {cmd}", flush=True)

        _, stdout, stderr = ssh.exec_command(cmd)
        err = stderr.read().decode().strip()
        status = stdout.channel.recv_exit_status()
        
        print(f"Reboot {server['name']} | status={status} | stderr='{err}'", flush=True)
        ssh.close()
        return True
    except Exception as e:
        print(f"Reboot FAILED {server.get('name')}: {e}", flush=True)
        return False

async def wait_for_reboot(server, timeout=120):
    await asyncio.sleep(10)
    print(f"Waiting for {server['name']}...", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        try:
            ssh = create_ssh_client(server)
            ssh.close()
            return True
        except:
            await asyncio.sleep(5)
    return False

async def build_server_card(server_id):
    server = find_server(server_id)

    if not server:
        return None, None

    info = await asyncio.to_thread(
        get_server_info,
        server
    )

    ping_text = (
        f"{info.get('ping')} ms"
        if info.get("ping")
        else "нет ответа"
    )

    sudo_text = (
        "✅ Есть"
        if server.get("password")
        else "❌ Нет"
    )

    auth_text = (
        "🔑 Ключ"
        if server.get("auth_type") == "key"
        else "🔒 Пароль"
    )

    monitor = get_server_monitor(
        server["id"]
    )

    if monitor:

        host = monitor["host"]
        host_ip = monitor["host_ip"]
        ssl_host = monitor["ssl_host"]
        ssl_ip = monitor["ssl_ip"]

        if host == ssl_host:

            if host == host_ip:

                connection = (
                    f"🌐 IP: {host}"
                )

            else:

                connection = (
                    f"🌐 Host: {host}\n"
                    f"🌐 IP: {host_ip}"
                )

        else:

            connection = (
                f"🌐 IP: {host}\n"
                f"🌐 Домен: {ssl_host}\n"
                f"🌍 Public IP: {ssl_ip}"
            )

    else:

        connection = (
            f"🌐 IP: {server.get('host', 'N/A')}"
        )

    text = (
        f"🖥 {server['name']}\n\n"
        f"{connection}\n"
        f"👤 User: {server.get('user', 'N/A')}\n"
        f"🔐 Auth: {auth_text}\n"
        f"🛡 Sudo: {sudo_text}\n\n"
    )

    if info["ssh"]:

        text += (
            "🟢 Статус: Онлайн\n"
            f"📡 ICMP: {ping_text}\n"
            "🔐 SSH: Доступен\n\n"
            "⏱ Uptime:\n"
            f"{info['uptime']}\n\n"
            "📊 Load:\n"
            f"{info['load']}\n\n"
            "💾 RAM:\n"
            f"{info['ram']}\n\n"
            "🗄 Disk:\n"
            f"{info['disk']}\n"
        )

    else:

        text += (
            f"📡 ICMP: {ping_text}\n"
            "🔐 SSH: Недоступен\n\n"
            "Причина:\n"
            f"{format_ssh_error(info['ssh_error'])}\n"
        )
    if server.get(
        "certificate_check",
        False
    ):

        text += "\n" + format_certificate(
            server["id"]
        )

    kb = [
        [
            InlineKeyboardButton(
                "📊 Обновить",
                callback_data=f"server:{server['id']}"
            ),
            InlineKeyboardButton(
                "🔄 Перезагрузить",
                callback_data=f"reboot_confirm:{server['id']}"
            )
        ],
        [
            InlineKeyboardButton(
                "✏️ Изменить",
                callback_data=f"edit:{server['id']}"
            )
        ],
        [
            InlineKeyboardButton(
                "🗑 Удалить",
                callback_data=f"delete_confirm:{server['id']}"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Назад",
                callback_data=f"group:{server.get('group','')}"
            )
        ]
    ]

    return text, kb

async def show_server(query, server_id):
    text, kb = await build_server_card(server_id)
    if not text:
        await query.edit_message_text(
            "Сервер не найден."
        )
        return

    try:
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(kb)   # ← обернуть в Markup
        )
    except Exception:
        # Если не получилось отредактировать — отправляем новое сообщение
        await query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(kb)
        )

async def show_server_message(message, server_id):
    text, kb = await build_server_card(server_id)

    if not text:
        await message.reply_text(
            "Сервер не найден."
        )
        return

    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb)
    )
# Перезагрузка
async def reboot_confirm(query, server_id):
    server = find_server(server_id)
    if not server:
        await query.edit_message_text("Сервер не найден.")
        return

    text = f"⚠️ Перезагрузить {server['name']}?\nIP: {server.get('host', 'N/A')}"
    keyboard = [
        [InlineKeyboardButton("✅ Да", callback_data=f"reboot:{server_id}")],
        [InlineKeyboardButton("❌ Нет", callback_data=f"server:{server_id}")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))  # убрал Markdown

async def perform_reboot(query, server_id):
    server = find_server(server_id)
    if not server:
        await query.edit_message_text("Сервер не найден.")
        return

    await query.edit_message_text(f"🔄 Перезагружаю {server['name']}...")

    success = await asyncio.to_thread(reboot_server, server)
    if not success:
        await query.edit_message_text("❌ Не удалось выполнить команду.")
        return

    returned = await wait_for_reboot(server)
    if returned:
        info = await asyncio.to_thread(get_server_info, server)
        text = f"✅ {server['name']} вернулся!\nUptime: {info['uptime']}"
    else:
        text = f"❌ {server['name']} не вернулся за 2 минуты."

    kb = [
        [InlineKeyboardButton("📊 Обновить", callback_data=f"server:{server_id}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="servers")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))


async def show_servers(query, status_message=None):
    if status_message:
        text = (
            f"{status_message}\n\n"
            "🖥 Серверы\n\n"
            "Выберите группу:"
        )
    else:
        text = (
            "🖥 Серверы\n\n"
            "Выберите группу:"
        )
    keyboard = build_group_buttons("group")

    keyboard.append([
        InlineKeyboardButton(
            "➕ Добавить группу",
            callback_data="add_group"
        )
    ])
    keyboard.append([
        InlineKeyboardButton(
            "➕ Добавить сервер",
            callback_data="add_server"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Назад",
            callback_data="main"
        )
    ])
    if hasattr(query, "edit_message_text"):
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def show_group(query, group_name):
    servers = load_servers()

    group_servers = [
        s for s in servers
        if s.get("group", "").lower() == group_name.lower()
    ]

    group = get_group(group_name)

    ssl_status = (
        "🟢 Включён"
        if group and group.get("ssl_monitor")
        else "⚪ Выключен"
    )

    if group_name == "home":
        title = "🏠 Домашние серверы"

    elif group_name == "vps":
        title = "☁️ VPS"

    else:
        title = f"📁 {group_name}"

    text = (
        f"{title}\n\n"
        f"🔒 SSL мониторинг: {ssl_status}"
    )

    keyboard = []

    for server in group_servers:
        keyboard.append([
            InlineKeyboardButton(
                server["name"],
                callback_data=f"server:{server['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "⚙️ SSL мониторинг",
            callback_data=f"group_ssl_menu:{group_name}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "🗑 Удалить группу",
            callback_data=f"delete_group_confirm:{group_name}"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            "⬅️ Назад",
            callback_data="servers"
        )
    ])

    if hasattr(
        query,
        "edit_message_text"
    ):

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            )
        )

    else:

        await query.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            )
        )

async def show_group_ssl_menu(query, group_name):
    group = get_group(group_name)

    if not group:
        await query.edit_message_text("❌ Группа не найдена.")
        return

    status = "🟢 Включён" if group["ssl_monitor"] else "⚪ Выключен"

    text = f"📁 {group_name}\n\nSSL мониторинг:\n{status}"

    keyboard = [
        [
            InlineKeyboardButton("🟢 Включить", callback_data=f"group_ssl:on:{group_name}")
        ],
        [
            InlineKeyboardButton("⚪ Выключить", callback_data=f"group_ssl:off:{group_name}")
        ],
    ]

    if group.get("ssl_monitor"):
        keyboard.append([
            InlineKeyboardButton("🔄 Проверить сейчас", callback_data=f"ssl_check_now:{group_name}")
        ])

    keyboard.append([
        InlineKeyboardButton("⬅️ Назад", callback_data=f"group:{group_name}")
    ])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Карточка сервера


async def edit_server_menu(query, server_id):
    server = find_server(server_id)

    if not server:
        await query.edit_message_text("Сервер не найден.")
        return

    kb = [
        [InlineKeyboardButton("📝 Имя", callback_data=f"edit_name:{server_id}")],
        [InlineKeyboardButton("🌐 Адрес подключения", callback_data=f"edit_host:{server_id}")],
        [InlineKeyboardButton("🌐 Домен SSL", callback_data=f"edit_ssl_host:{server_id}")],
        [InlineKeyboardButton("🔌 Порт", callback_data=f"edit_port:{server_id}")],
        [InlineKeyboardButton("👤 Пользователь", callback_data=f"edit_user:{server_id}")],
        [InlineKeyboardButton("🔐 Аутентификация", callback_data=f"edit_auth:{server_id}")],
        [InlineKeyboardButton("🏠 Группа", callback_data=f"edit_group:{server_id}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"server:{server_id}")]
    ]

    await query.edit_message_text(
        f"✏️ Редактирование\n\nСервер: {server['name']}",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def delete_confirm(query, server_id):
    server = find_server(server_id)

    if not server:
        await query.edit_message_text(
            "Сервер не найден."
        )
        return

    text = f"⚠️ Удалить сервер {server['name']}?"

    kb = [
        [InlineKeyboardButton(
            "✅ Да",
            callback_data=f"delete:{server_id}"
        )],
        [InlineKeyboardButton(
            "❌ Нет",
            callback_data=f"server:{server_id}"
        )]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def delete_server(query, server_id):
    server = find_server(server_id)

    if not server:
        await show_servers(
            query,
            "❌ Сервер не найден."
        )
        return

    server_name = server["name"]

    servers = [
        s for s in load_servers()
        if s["id"] != server_id
    ]

    save_servers(servers)

    await show_servers(
        query,
        f"✅ Сервер {server_name} удалён."
    )

#удаление группы
async def delete_group_confirm(query, group_name):
    servers = load_servers()

    used = any(
        s.get("group") == group_name
        for s in servers
    )

    if used:
        await query.edit_message_text(
            "❌ В группе есть серверы.\n\n"
            "Сначала удалите или перенесите их.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data=f"group:{group_name}"
                    )
                ]
            ])
        )
        return

    await query.edit_message_text(
        f"⚠️ Удалить группу '{group_name}'?",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Да",
                    callback_data=f"delete_group:{group_name}"
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Нет",
                    callback_data=f"group:{group_name}"
                )
            ]
        ])
    )

async def delete_group(
    query,
    group_name
):
    groups = load_groups()

    groups = [
        group
        for group in groups
        if group["name"] != group_name
    ]

    save_groups(groups)

    await show_servers(
        query,
        f"✅ Группа {group_name} удалена."
    )

