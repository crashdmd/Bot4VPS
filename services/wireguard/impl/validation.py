# -*- coding: utf-8 -*-
"""Валидация входных параметров сервиса WireGuard (порт, CIDR, имя профиля, host, iface)."""
from __future__ import annotations

import ipaddress
import re
from typing import Any

from core.integrator import StepError

IFACE_RE = re.compile(r"^[A-Za-z0-9._:-]+$")
ADDR_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,30}$")
HOST_RE = re.compile(r"^[A-Za-z0-9._:-]+$")


def is_private_ip(host: str) -> bool:
    """Проверяет, является ли host приватным IP (10.x, 192.168.x, 172.16-31.x)."""
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False  # Это домен, не IP


def validate_port(val: Any) -> str:
    raw = val if val not in (None, "") else 51820
    try:
        p = int(raw)
    except (TypeError, ValueError):
        raise StepError("validate_port", -1, title="Параметр WG_PORT", detail=f"нечисловой порт: {val!r}")
    if not (1 <= p <= 65535):
        raise StepError("validate_port", -1, title="Параметр WG_PORT", detail=f"порт вне диапазона: {p}")
    return str(p)


def validate_addr(val: Any) -> str:
    addr = str(val if val not in (None, "") else "10.66.66.1/24").strip()
    if not ADDR_RE.match(addr):
        raise StepError("validate_addr", -1, title="Параметр WG_ADDR", detail=f"некорректный адрес: {addr!r}")
    return addr


def validate_profile_name(val: Any) -> str:
    name = str(val or "").strip()
    if not NAME_RE.match(name):
        raise StepError("validate_name", -1, title="Имя профиля", detail=f"недопустимое имя: {val!r}")
    return name


def validate_dns(val: Any) -> str:
    """DNS для клиентов: один или несколько (через запятую) IP/доменов. Каждый
    токен проверяется HOST_RE → sed-safe. Возвращает строку вида «1.1.1.1, 8.8.8.8»."""
    raw = str(val if val not in (None, "") else "").strip()
    if not raw:
        raise StepError("validate_dns", -1, title="Параметр DNS", detail="пустой DNS")
    tokens = [t.strip() for t in raw.split(",") if t.strip()]
    for t in tokens:
        if not HOST_RE.match(t):
            raise StepError("validate_dns", -1, title="Параметр DNS", detail=f"некорректный DNS: {t!r}")
    return ", ".join(tokens)


def validate_host(val: Any) -> str:
    """Endpoint сервера: непустой и без опасных для sed/shell символов."""
    host = str(val or "").strip()
    if not host:
        raise StepError(
            "server_host", -1, title="Endpoint сервера",
            detail="Endpoint не настроен. Укажите внешний IP или домен.",
        )
    if not HOST_RE.match(host):
        raise StepError("server_host", -1, title="Endpoint сервера", detail=f"некорректный host: {host!r}")
    return host


def validate_iface(val: str) -> str:
    if not IFACE_RE.match(val):
        raise StepError("detect_iface", -1, title="Определение внешнего интерфейса",
                         detail=f"подозрительное имя: {val!r}")
    return val


def coerce_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("1", "true", "yes", "y", "on", "да")