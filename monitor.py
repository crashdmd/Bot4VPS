import json
import os
import ssl
import socket

from datetime import datetime
from storage import (
    load_servers,
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

        with socket.create_connection(
            (host, 443),
            timeout=5
        ) as sock:

            with context.wrap_socket(
                sock,
                server_hostname=host
            ) as ssock:

                cert = ssock.getpeercert()

    except Exception as e:

        return {
            "status": STATUS_ERROR,
            "error": str(e),
            "checked": datetime.now().strftime(
                "%Y-%m-%d %H:%M"
            )
        }

    expires = datetime.strptime(
        cert["notAfter"],
        "%b %d %H:%M:%S %Y %Z"
    )

    days_left = (
        expires - datetime.now()
    ).days

    if days_left < 0:
        status = STATUS_EXPIRED

    elif days_left <= 5:
        status = STATUS_WARNING

    else:
        status = STATUS_VALID

    return {
        "status": status,
        "days_left": days_left,
        "expires": expires.strftime(
            "%Y-%m-%d"
        ),
        "checked": datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        )
    }

def compare_certificate(
    old_cert,
    new_cert
):

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
    old = monitor.get(server["id"])

    if old:
        event = compare_certificate(old["certificate"], new_cert)

    monitor[server["id"]] = {
        "name": server["name"],
        "host": host,
        "host_ip": host_ip,
        "ssl_host": ssl_host,
        "ssl_ip": ssl_ip,
        "certificate": new_cert
    }
    save_monitor(monitor)

    if event:
        print(f"{server['name']}: {event}", flush=True)
        return {
            "server_id": server["id"],
            "server_name": server["name"],
            "event": event,
            "old_expires": old["certificate"]["expires"] if old else None,
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