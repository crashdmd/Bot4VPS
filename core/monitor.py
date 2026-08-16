import json
import os
import ssl
import socket
import threading
from datetime import datetime
from core.storage import (
    load_servers,
    find_server,
    is_group_ssl_enabled
)

MONITOR_FILE = "monitor.json"

# Блокировка для атомарных RMW над monitor.json.
# Онлайн- и SSL-мониторинг пишут файл из разных потоков (asyncio.to_thread),
# поэтому нужен потокобезопасный locking.
_MONITOR_LOCK = threading.RLock()


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

    host = server["host"]
    ssl_host = server.get("ssl_host", host)

    # Тяжёлые сетевые операции — вне блокировки, чтобы не держать лок
    # во время DNS/SSL-проверок.
    try:
        host_ip = socket.gethostbyname(host)
    except OSError:
        host_ip = host

    try:
        ssl_ip = socket.gethostbyname(ssl_host)
    except OSError:
        ssl_ip = ssl_host

    new_cert = check_certificate(ssl_host)

    # Атомарный RMW monitor.json — под блокировкой.
    with _MONITOR_LOCK:
        monitor = load_monitor()
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

def update_server_availability(
    server,
    online: bool,
    error: str = "",
    system: dict | None = None,
):
    """
    Обновляет состояние доступности сервера.

    system — опциональный блок системных сведений (hostname, ОС, ядро…),
    собранный в том же SSH-запросе, что и метрики. Пишется только если
    передан (при недоступном SSH прежние данные не затираются).

    Возвращает:
        None
        {
            "server_id": "...",
            "server_name": "...",
            "event": "offline" | "online",
            "error": "..."
        }
    """

    with _MONITOR_LOCK:

        monitor = load_monitor()

        entry = monitor.setdefault(server["id"], {})

        availability = entry.get("availability")

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        if system is not None:
            entry["system"] = system

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

    # system — только при успешном SSH, чтобы не затирать кэш N/A
    system = None
    if info.get("ssh"):
        system = {
            "hostname": info.get("hostname") or "N/A",
            "os": info.get("os") or "N/A",
            "os_version": info.get("os_version") or "N/A",
            "kernel": info.get("kernel") or "N/A",
            "arch": info.get("arch") or "N/A",
            "uptime": info.get("uptime") or "N/A",
        }

    event = update_server_availability(
        server,
        online=is_server_online(info),
        error=info.get("ssh_error") or "",
        system=system,
    )
    return info, event

# ==========================================================
# Job-функции для JobQueue
# ==========================================================

async def online_monitor_job(context):
    """Периодическая проверка доступности серверов (только изменения состояния)"""
    import asyncio
    from core.storage import load_servers
    from core.event_service import notify_event
    from core.event_types import EventType, EventLevel, EventReason

    for server in load_servers():
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
                await notify_event(
                    EventType.SERVER,
                    EventLevel.CRITICAL,
                    "Сервер недоступен",
                    message,
                    details,
                )

            elif event["event"] == "online":
                details = {
                    **event,
                    "reason": EventReason.SERVER_ONLINE.value,
                }
                message = f"Сервер «{event['server_name']}» снова в сети."
                await notify_event(
                    EventType.SERVER,
                    EventLevel.INFO,
                    "Сервер снова доступен",
                    message,
                    details,
                )

        except Exception as e:
            print(
                f"[ONLINE MONITOR] Ошибка для {server.get('name', '?')}: {e}",
                flush=True,
            )


async def ssl_monitor_job(context):
    """Периодический SSL-мониторинг"""
    from core.event_service import notify_event
    from core.event_types import EventType, EventLevel, EventReason

    events = run_daily_monitor()

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
            await notify_event(
                EventType.SSL,
                EventLevel.INFO,
                "SSL сертификат обновлён",
                message,
                details,
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
            await notify_event(
                EventType.SSL,
                EventLevel.CRITICAL,
                "SSL сертификат истёк",
                message,
                details,
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

    # Суточная проверка обновлений Bot4VPS (встроенный updater, 4.0+)
    from core.update.scheduler import schedule_update_jobs

    schedule_update_jobs(job_queue)
