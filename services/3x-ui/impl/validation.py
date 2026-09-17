# -*- coding: utf-8 -*-
"""Валидация параметров установки 3x-ui (доменная, единая точка правды).

Официальный скрипт валидирует ввод в interactive-циклах; мы выносим те же
правила сюда — модалка установки (Web) и любые другие фронты проверяют
значения ДО запуска установки. Установщик (SSH) доверяет прошедшим
валидацию параметрам.

Правила синхронизированы с install.sh (MHSanaei/3x-ui):
    - логин: непустой, печатные ASCII, без ':' и пробелов;
    - пароль: ≥ 8 символов (генератор даёт 16 — с запасом);
    - порт: 1-65535, панель не должна слушать 80 (нужен для ACME);
    - web base path: 4-64 симв., [A-Za-z0-9], без слэшей;
    - домен: буквы/цифры/точки/дефис, ≥ 1 точка, метки 1-63;
    - пути сертификатов: абсолютные, без '..'.
"""
from __future__ import annotations

import re
from typing import Optional

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
PASSWORD_MIN = 8
PATH_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
    r"[a-zA-Z]{2,63}$"
)
SSL_MODES = ("domain", "ip", "custom", "none")

class ValidationError(ValueError):
    """Параметр не прошёл доменную валидацию. message — для UI."""


def validate_username(value: str) -> str:
    v = str(value or "").strip()
    if not USERNAME_RE.match(v):
        raise ValidationError(
            "Логин: 3-32 символа, латиница/цифры/точка/дефис/подчёркивание"
        )
    return v


def validate_password(value: str) -> str:
    v = str(value or "")
    if len(v) < PASSWORD_MIN:
        raise ValidationError(f"Пароль: минимум {PASSWORD_MIN} символов")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in v):
        raise ValidationError("Пароль содержит управляющие символы")
    return v


def validate_port(value, *, allow_80: bool = False) -> int:
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValidationError("Порт: целое число 1-65535")
    if not (1 <= port <= 65535):
        raise ValidationError("Порт: целое число 1-65535")
    if port == 80 and not allow_80:
        # порт 80 нужен ACME для HTTP-01; панель на нём ломает выпуск
        raise ValidationError("Порт 80 зарезервирован (нужен для сертификата)")
    return port


def validate_web_base_path(value: str) -> str:
    v = str(value or "").strip().strip("/")
    if not PATH_RE.match(v):
        raise ValidationError(
            "Web base path: 4-64 символа, латиница, цифры, дефис и подчёркивание (без слэшей)"
        )
    return v


def validate_domain(value: str) -> str:
    v = str(value or "").strip().rstrip(".")
    if not DOMAIN_RE.match(v):
        raise ValidationError("Домен: например panel.example.com")
    return v


def validate_ipv4(value: str) -> str:
    v = str(value or "").strip()
    try:
        import ipaddress
        return str(ipaddress.IPv4Address(v))
    except ValueError:
        raise ValidationError("IPv4: например 203.0.113.10")


def validate_certificate_identifier(value: str) -> str:
    """Имя управляемого сертификата из карточки.

    Обычные сертификаты идентифицируются доменом. Короткоживущий
    IP-сертификат 3x-ui намеренно хранится под служебным именем ``ip`` в
    /root/cert/ip, поэтому его продление и отзыв не должны проходить через
    валидатор DNS-имён.
    """
    v = str(value or "").strip()
    return "ip" if v == "ip" else validate_domain(v)


def validate_ipv6(value: str) -> str:
    v = str(value or "").strip()
    try:
        import ipaddress
        return str(ipaddress.IPv6Address(v))
    except ValueError:
        raise ValidationError("IPv6: например 2001:db8::1")


def validate_cert_path(value: str) -> str:
    v = str(value or "").strip()
    if not v.startswith("/"):
        raise ValidationError("Путь сертификата: абсолютный путь от /")
    if ".." in v.split("/"):
        raise ValidationError("Путь сертификата: без '..'")
    if not re.match(r"^[\w./@+-]+$", v):
        raise ValidationError("Путь сертификата: недопустимые символы")
    return v


def validate_ssl_params(params: dict) -> dict:
    """Проверить блок SSL-параметров по режиму. Возвращает нормализованный словарь.

    ssl_mode: domain (XUI_DOMAIN обязателен) | ip (ipv6 опционален) |
              custom (домен + 2 абсолютных пути) | none (bind_local опционален).
    """
    mode = str(params.get("ssl_mode") or "none")
    if mode not in SSL_MODES:
        raise ValidationError(f"Неизвестный SSL-режим: {mode}")
    out = {"ssl_mode": mode}
    if mode == "domain":
        out["domain"] = validate_domain(params.get("domain") or "")
    elif mode == "ip":
        if params.get("ipv6"):
            out["ipv6"] = validate_ipv6(params["ipv6"])
    elif mode == "custom":
        out["domain"] = validate_domain(params.get("domain") or "")
        out["cert_file"] = validate_cert_path(params.get("cert_file") or "")
        out["key_file"] = validate_cert_path(params.get("key_file") or "")
        if out["cert_file"] == out["key_file"]:
            raise ValidationError("Пути сертификата и ключа совпадают")
    elif mode == "none":
        out["bind_local"] = bool(params.get("bind_local"))
    return out


def validate_install_params(params: dict) -> dict:
    """Полная нормализация+валидация параметров установки.

    Возвращает готовый к installer.run_install словарь:
        username, password, port, web_base_path, ssl_mode (+поля режима),
        arch, tag (опционально — резолвер дополнит).
    """
    out = {
        "username": validate_username(params.get("username") or ""),
        "password": validate_password(params.get("password") or ""),
        "port": validate_port(params.get("port")),
        "web_base_path": validate_web_base_path(params.get("web_base_path") or ""),
    }
    out.update(validate_ssl_params(params))
    if params.get("arch"):
        out["arch"] = str(params["arch"])
    if params.get("tag"):
        out["tag"] = str(params["tag"])
    return out
