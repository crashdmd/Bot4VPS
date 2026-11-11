"""Closed protocol and systemd unit construction; no application imports."""
from __future__ import annotations

import ipaddress
import json
import re
import shlex
from pathlib import Path

MAX_MESSAGE = 192 * 1024
APP = Path("/opt/bot4vps")
SERVICE = "bot4vps"
UNIT = Path("/etc/systemd/system/bot4vps.service")
ROOT_STATE = Path("/var/lib/bot4vps-helper")
HELPER_HOME = Path("/usr/lib/bot4vps-helper")
USER = "bot4vps"


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError("Повторное поле запроса")
        result[key] = value
    return result


def decode(data: bytes):
    if len(data) > MAX_MESSAGE:
        raise ValueError("Слишком большой запрос")
    value = json.loads(data, object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Некорректное число")))
    if (not isinstance(value, dict) or set(value) != {"version", "operation", "params"}
            or type(value["version"]) is not int or value["version"] != 1
            or not isinstance(value["operation"], str) or not isinstance(value["params"], dict)):
        raise ValueError("Некорректная схема запроса")
    return value["operation"], value["params"]


def fields(params, required=(), optional=()):
    if not set(required) <= set(params) or set(params) - set(required) - set(optional):
        raise ValueError("Недопустимые параметры операции")


def port(value):
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError("Некорректный TCP-порт")
    return value


def domain(value):
    if (not isinstance(value, str) or len(value) > 253
            or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value)
            or "." not in value or any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in value.split("."))):
        raise ValueError("Некорректный домен")
    return value.lower()


def safe_path(value):
    # systemd expands % specifiers and $ variables even without a shell.
    if (not isinstance(value, str) or len(value) > 4096 or not value.startswith("/")
            or any(c in value for c in '\n\r\x00%$\\"') or ".." in Path(value).parts):
        raise ValueError("Недопустимый путь systemd")
    return '"' + value + '"'


def transport(text: str):
    """Read only allowed ExecStart arguments. All other unit directives are discarded."""
    if not isinstance(text, str) or len(text) > 32768:
        raise ValueError("Некорректный unit")
    entries = re.findall(r"^ExecStart=(.*)$", text, re.M)
    if len(entries) != 1:
        raise ValueError("Ожидается один ExecStart")
    args = shlex.split(entries[0])
    python = str(APP / "venv/bin/python")
    if args == [python, "bot.py"]:
        return {"mode": "tg"}
    if args[:4] != [python, "-m", "uvicorn", "ui.web.app:app"]:
        raise ValueError("Недопустимая команда службы")
    values, flags = {}, set()
    i = 4
    while i < len(args):
        name = args[i]
        if name == "--proxy-headers":
            if name in flags:
                raise ValueError("Повторный параметр")
            flags.add(name)
            i += 1
            continue
        if name not in {"--host", "--port", "--ssl-certfile", "--ssl-keyfile", "--forwarded-allow-ips", "--timeout-graceful-shutdown"} or name in values or i + 1 >= len(args):
            raise ValueError("Недопустимые аргументы службы")
        values[name] = args[i + 1]
        i += 2
    if values.get("--host") != "0.0.0.0" or not values.get("--port", "").isdigit():
        raise ValueError("Некорректный адрес службы")
    result = {"mode": "web", "port": port(int(values["--port"]))}
    if "--timeout-graceful-shutdown" in values and values["--timeout-graceful-shutdown"] != "10":
        raise ValueError("Некорректное время остановки")
    if "--ssl-certfile" in values or "--ssl-keyfile" in values:
        for name in ("--ssl-certfile", "--ssl-keyfile"):
            safe_path(values.get(name))
        result.update(cert=values["--ssl-certfile"], key=values["--ssl-keyfile"])
    if "--proxy-headers" in flags or "--forwarded-allow-ips" in values:
        if "--proxy-headers" not in flags or "--forwarded-allow-ips" not in values:
            raise ValueError("Неполная настройка proxy")
        proxies = values["--forwarded-allow-ips"].split(",")
        if not 1 <= len(proxies) <= 20:
            raise ValueError("Некорректные proxy")
        result["proxies"] = [str(ipaddress.ip_network(p, strict=False)) if "/" in p else str(ipaddress.ip_address(p)) for p in proxies]
    return result


def unit_text(settings):
    fields(settings, ("mode",), ("port", "cert", "key", "proxies"))
    if settings["mode"] == "tg":
        if set(settings) != {"mode"}:
            raise ValueError("Лишние параметры TG")
        command = f"{APP}/venv/bin/python bot.py"
    elif settings["mode"] == "web":
        command = f"{APP}/venv/bin/python -m uvicorn ui.web.app:app --host 0.0.0.0 --port {port(settings.get('port'))} --timeout-graceful-shutdown 10"
        if "cert" in settings or "key" in settings:
            command += f" --ssl-certfile {safe_path(settings.get('cert'))} --ssl-keyfile {safe_path(settings.get('key'))}"
        if "proxies" in settings:
            proxies = settings["proxies"]
            if not isinstance(proxies, list) or not 1 <= len(proxies) <= 20:
                raise ValueError("Некорректные proxy")
            canonical = [str(ipaddress.ip_network(p, strict=False)) if "/" in p else str(ipaddress.ip_address(p)) for p in proxies]
            command += " --proxy-headers --forwarded-allow-ips " + ",".join(canonical)
    else:
        raise ValueError("Неизвестный режим службы")
    return f"""[Unit]
Description=Bot4VPS
After=network.target bot4vps-helper.service
Wants=network-online.target bot4vps-helper.service

[Service]
Type=simple
User=bot4vps
Group=bot4vps
WorkingDirectory={APP}
Environment=PYTHONPATH={APP}
Environment=PYTHONDONTWRITEBYTECODE=1
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
InaccessiblePaths=/root /run/user
PrivateTmp=yes
RestrictSUIDSGID=yes
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_BIND_SERVICE
ReadWritePaths={APP}/data {APP}/keys {APP}/logs {APP}/scripts -/var/backups/bot4vps /run/lock/bot4vps
ExecStart={command}
Restart=always
RestartSec=5
TimeoutStopSec=45
KillMode=mixed

[Install]
WantedBy=multi-user.target
"""
