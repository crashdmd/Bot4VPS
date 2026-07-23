import json
import os
import ssl
import socket
from datetime import datetime
from core.storage import (
    load_servers,
    find_server,
    is_group_ssl_enabled
)

MONITOR_FILE = "monitor.json"


def load_monitor():
    if not os.path.exists(MONITOR_FILE):
        return {}
    with open(MONITOR_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_monitor(data):
    with open(MONITOR_FILE, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=4
        )


def get_server_monitor(server_id):
    data = load_monitor()
    return data.get(server_id)


STATUS_VALID = "valid"
STATUS_WARNING = "warning"
STATUS_EXPIRED = "expired"
STATUS_ERROR = "error"


def format_certificate(server_id):
    monitor = get_server_monitor(server_id)
    if not monitor:
        return (
            "🔒 Сертификат\n"
            "⚪ Нет данных\n"
        )

    cert = monitor["certificate"]
    status = cert["status"]

    if status == STATUS_VALID:
        return (
            "🔒 Сертификат\n"
            "🟢 Действует\n\n"
            f"📅 Истекает: {cert['expires']}\n"
            f"⏳ Осталось: {cert['days_left']} дн.\n"
            f"🕒 Проверен: {cert['checked']}\n"
        )

    if status == STATUS_WARNING:
        return (
            "🔒 Сертификат\n"
            "🟡 Скоро истекает\n\n"
            f"📅 Истекает: {cert['expires']}\n"
            f"⏳ Осталось: {cert['days_left']} дн.\n"
            f"🕒 Проверен: {cert['checked']}\n"
        )

    if status == STATUS_EXPIRED:
        return (
            "🔒 Сертификат\n"
            "🔴 Истёк\n\n"
            f"📅 Истёк: {cert['expires']}\n"
            f"🕒 Проверен: {cert['checked']}\n"
        )

    return (
        "🔒 Сертификат\n"
        "⚪ Ошибка проверки\n\n"
        f"{cert.get('error', 'Неизвестная ошибка')}\n"
        f"🕒 Проверен: {cert['checked']}\n"
    )


def check_certificate(host):
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
    except Exception as e:
        return {
            "status": STATUS_ERROR,
            "error": str(e),
            "checked": datetime.now().strftime("%Y-%m-%d %H:%M")
        }

    expires = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
    days_left = (expires - datetime.now()).days

    if days_left < 0:
        status = STATUS_EXPIRED
    elif days_left <= 5:
        status = STATUS_WARNING
    else:
        status = STATUS_VALID

    return {
        "status": status,
        "days_left": days_left,
        "expires": expires.strftime("%Y-%m-%d"),
        "checked": datetime.now().strftime("%Y-%m-%d %H:%M")
    }


def compare_certificate(old_cert, new_cert):
    if (
        old_cert["status"] == STATUS_VALID
        and new_cert["status"] == STATUS_VALID
        and old_cert["expires"] != new_cert["expires"]
    ):
        return "renewed"

    if (
        old_cert["status"] != STATUS_EXPIRED
        and new_cert["status"] == STATUS_EXPIRED
    ):
        return "expired"

    return None


def update_server_certificate(server):
    if not server.get("certificate_check", True):
        return None

    monitor = load_monitor()
    host = server["host"]
    ssl_host = server.get("ssl_host", host)

    try:
        host_ip = socket.gethostbyname(host)
    except OSError:
        host_ip = host

    try:
        ssl_ip = socket.gethostbyname(ssl_host)
    except OSError:
        ssl_ip = ssl_host

    new_cert = check_certificate(ssl_host)
    event = None
    entry = monitor.setdefault(server["id"], {})

    old_cert = entry.get("certificate")
    event = None

    if old_cert:
        event = compare_certificate(old_cert, new_cert)

    entry["name"] = server["name"]
    entry["host"] = host
    entry["host_ip"] = host_ip
    entry["ssl_host"] = ssl_host
    entry["ssl_ip"] = ssl_ip
    entry["certificate"] = new_cert

    save_monitor(monitor)

    if event:
        print(f"{server['name']}: {event}", flush=True)
        return {
            "server_id": server["id"],
            "server_name": server["name"],
            "event": event,
            "old_expires": old_cert["expires"],
            "new_expires": new_cert["expires"]
        }
    return None


def run_monitor(group_name: str | None = None):
    servers = load_servers()
    if group_name:
        servers = [s for s in servers if s.get("group") == group_name]

    events = []
    for server in servers:
        if not is_group_ssl_enabled(server.get("group", "")):
            continue
        if not server.get("certificate_check", False):
            continue

        print(f"SSL: {server['name']}")
        event = update_server_certificate(server)
        if event:
            events.append(event)

    return events


def run_daily_monitor():
    return run_monitor()


def refresh_server_state(server_id: str):
    """
    Обновляет состояние сервера после выполнения скриптов.
    Сейчас обновляет только SSL. В будущем можно расширить.
    """

    server = find_server(server_id)
    if not server:
        return False

    updated = False

    if server.get("certificate_check"):
        try:
            update_server_certificate(server)
            updated = True
            print(f"[STATE] SSL обновлён для сервера: {server.get('name')}", flush=True)
        except Exception as e:
            print(f"[STATE] Ошибка обновления SSL для {server.get('name')}: {e}", flush=True)

    return updated

# ==========================================================
# Мониторинг доступности
# ==========================================================

def update_server_availability(server, online: bool, error: str = ""):
    """
    Обновляет состояние доступности сервера.

    Возвращает:
        None
        {
            "server_id": "...",
            "server_name": "...",
            "event": "offline" | "online",
            "error": "..."
        }
    """

    monitor = load_monitor()

    entry = monitor.setdefault(server["id"], {})

    availability = entry.get("availability")

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Первый запуск / новый сервер
    if availability is None:
        entry["availability"] = {
            "online": online,
            "last_error": error,
            "checked": now
        }

        save_monitor(monitor)
        return None

    previous_online = availability["online"]

    availability["online"] = online
    availability["last_error"] = error
    availability["checked"] = now

    save_monitor(monitor)

    if previous_online == online:
        return None

    if online:
        return {
            "server_id": server["id"],
            "server_name": server["name"],
            "event": "online"
        }

    return {
        "server_id": server["id"],
        "server_name": server["name"],
        "event": "offline",
        "error": error
    }

def check_server_availability(server):
    """
    Проверяет доступность сервера и обновляет состояние мониторинга.
    Возвращает:
        (info, event)
    """
    from core.servers import (
        get_server_info,
        is_server_online,
    )    
    info = get_server_info(server)
    event = update_server_availability(
        server,
        online=is_server_online(info),
        error=info.get("ssh_error") or ""
    )
    return info, event

# ==========================================================
# Job-функции для JobQueue
# ==========================================================

async def online_monitor_job(context):
    """Периодическая проверка доступности серверов (только изменения состояния)"""
    import asyncio
    from core.storage import load_servers
    from core.event_service import create_event
    from core.event_types import EventType, EventLevel, EventReason
    from ui.telegram.notifications import send_event_notification

    servers = load_servers()
    bot = context.bot

    for server in servers:
        try:
            info, event = await asyncio.to_thread(
                check_server_availability, server
            )
            if not event:
                continue

            if event["event"] == "offline":
                details = {
                    **event,
                    "reason": EventReason.SERVER_OFFLINE.value,
                }
                message = (
                    f"Сервер «{event['server_name']}» стал недоступен."
                    + (f"\nОшибка: {event.get('error')}" if event.get("error") else "")
                )
                event_id = create_event(
                    event_type=EventType.SERVER,
                    level=EventLevel.CRITICAL,
                    title="Сервер недоступен",
                    message=message,
                    details=details,
                )
                await send_event_notification(
                    bot,
                    {
                        "type": EventType.SERVER.value,
                        "level": EventLevel.CRITICAL.value,
                        "title": "Сервер недоступен",
                        "message": message,
                        "details": details,
                    },
                    event_id=event_id,
                )

            elif event["event"] == "online":
                details = {
                    **event,
                    "reason": EventReason.SERVER_ONLINE.value,
                }
                message = f"Сервер «{event['server_name']}» снова в сети."
                event_id = create_event(
                    event_type=EventType.SERVER,
                    level=EventLevel.INFO,
                    title="Сервер снова доступен",
                    message=message,
                    details=details,
                    notify=True,
                )
                await send_event_notification(
                    bot,
                    {
                        "type": EventType.SERVER.value,
                        "level": EventLevel.INFO.value,
                        "title": "Сервер снова доступен",
                        "message": message,
                        "details": details,
                    },
                    event_id=event_id,
                )

        except Exception as e:
            print(
                f"[ONLINE MONITOR] Ошибка для {server.get('name', '?')}: {e}",
                flush=True,
            )


async def ssl_monitor_job(context):
    """Периодический SSL-мониторинг"""
    from core.event_service import create_event
    from core.event_types import EventType, EventLevel, EventReason
    from ui.telegram.notifications import send_event_notification

    events = run_daily_monitor()
    bot = context.bot

    if not events:
        return

    for event in events:
        if event["event"] == "renewed":
            details = {
                **event,
                "reason": EventReason.SSL_RENEWED.value,
            }
            message = (
                f"Сертификат сервера "
                f"«{event['server_name']}» успешно обновлён."
            )
            event_id = create_event(
                event_type=EventType.SSL,
                level=EventLevel.INFO,
                title="SSL сертификат обновлён",
                message=message,
                details=details,
                notify=True,
            )
            await send_event_notification(
                bot,
                {
                    "type": EventType.SSL.value,
                    "level": EventLevel.INFO.value,
                    "title": "SSL сертификат обновлён",
                    "message": message,
                    "details": details,
                },
                event_id=event_id,
            )

        elif event["event"] == "expired":
            details = {
                **event,
                "reason": EventReason.SSL_EXPIRED.value,
            }
            message = (
                f"Сертификат сервера "
                f"«{event['server_name']}» истёк."
            )
            event_id = create_event(
                event_type=EventType.SSL,
                level=EventLevel.CRITICAL,
                title="SSL сертификат истёк",
                message=message,
                details=details,
            )
            await send_event_notification(
                bot,
                {
                    "type": EventType.SSL.value,
                    "level": EventLevel.CRITICAL.value,
                    "title": "SSL сертификат истёк",
                    "message": message,
                    "details": details,
                },
                event_id=event_id,
            )


def schedule_monitor_jobs(job_queue):
    """
    Пересоздаёт jobs мониторинга на основе текущего config.json.
    Вызывается при старте и после изменения настроек в админке.
    """
    from core.config import get_monitor_config

    monitor = get_monitor_config()

    for name in ("online_monitor", "ssl_monitor"):
        for job in job_queue.get_jobs_by_name(name):
            job.schedule_removal()

    if monitor["online"]["enabled"]:
        job_queue.run_repeating(
            online_monitor_job,
            interval=monitor["online"]["interval"] * 60,
            first=10,
            name="online_monitor",
        )
        print(
            f"[JOBS] online_monitor: every {monitor['online']['interval']} min",
            flush=True,
        )
    else:
        print("[JOBS] online_monitor: disabled", flush=True)

    if monitor["ssl"]["enabled"]:
        job_queue.run_repeating(
            ssl_monitor_job,
            interval=monitor["ssl"]["interval"] * 60,
            first=15,
            name="ssl_monitor",
        )
        print(
            f"[JOBS] ssl_monitor: every {monitor['ssl']['interval']} min",
            flush=True,
        )
    else:
        print("[JOBS] ssl_monitor: disabled", flush=True)
