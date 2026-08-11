# -*- coding: utf-8 -*-
"""Валидация входных параметров сервиса Docker (имя, образ, порт, env, restart).

Строгая проверка ДО любых SSH-записей (как в services/wireguard/impl/validation.py):
регэкспы исключают shell-метасимволы, поэтому значения безопасны для сборки
`docker run`. containers.py дополнительно оборачивает каждый токен в shlex.quote.
StepError → роутер отдаёт 400 с человекочитаемым сообщением.
"""
from __future__ import annotations

import re
from typing import Any, List

from core.integrator import StepError

# Имя контейнера: буква/цифра, далее буквы/цифры/_.- (как в самом Docker).
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
# Ссылка на образ: repo[:tag][@sha256:...] с опциональным registry/namespace.
IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}$")
# Порт-маппинг: [ip:]host:container[/proto] — числа, опц. IP и протокол.
PORT_RE = re.compile(
    r"^(?:(\d{1,3}(?:\.\d{1,3}){3}):)?(\d{1,5}):(\d{1,5})(?:/(tcp|udp))?$"
)
# Переменная окружения: KEY=VALUE; ключ — [A-Za-z_][A-Za-z0-9_]*; значение без
# управляющих символов (перевод строки исключён — по одной var на токен).
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

RESTART_POLICIES = ("no", "always", "unless-stopped", "on-failure")


def validate_name(val: Any) -> str:
    name = str(val or "").strip()
    if not NAME_RE.match(name):
        raise StepError(
            "validate_name", -1, title="Имя контейнера",
            detail=f"недопустимое имя: {val!r} (буквы, цифры, _.-, до 64 символов)",
        )
    return name


def validate_image(val: Any) -> str:
    image = str(val or "").strip()
    if not IMAGE_RE.match(image):
        raise StepError(
            "validate_image", -1, title="Образ",
            detail=f"недопустимая ссылка на образ: {val!r}",
        )
    return image


def validate_port(val: Any) -> str:
    """Один порт-маппинг host:container[/proto]. Проверяет диапазон 1..65535."""
    spec = str(val or "").strip()
    m = PORT_RE.match(spec)
    if not m:
        raise StepError(
            "validate_port", -1, title="Порт",
            detail=f"некорректный маппинг: {val!r} (ожидается host:container[/tcp|udp])",
        )
    host_p, cont_p = int(m.group(2)), int(m.group(3))
    for p in (host_p, cont_p):
        if not (1 <= p <= 65535):
            raise StepError(
                "validate_port", -1, title="Порт",
                detail=f"порт вне диапазона 1..65535: {p}",
            )
    return spec


def validate_env(val: Any) -> str:
    """Одна переменная окружения KEY=VALUE. Ключ по ENV_KEY_RE; значение — любые
    печатные символы, кроме перевода строки (одна var на токен)."""
    raw = str(val or "").strip()
    if "=" not in raw:
        raise StepError(
            "validate_env", -1, title="Переменная окружения",
            detail=f"ожидается KEY=VALUE: {val!r}",
        )
    key, value = raw.split("=", 1)
    key = key.strip()
    if not ENV_KEY_RE.match(key):
        raise StepError(
            "validate_env", -1, title="Переменная окружения",
            detail=f"недопустимый ключ: {key!r}",
        )
    if "\n" in value or "\r" in value:
        raise StepError(
            "validate_env", -1, title="Переменная окружения",
            detail="значение не должно содержать перевод строки",
        )
    return f"{key}={value}"


def validate_restart(val: Any) -> str:
    """Политика перезапуска. Пусто → 'no'. on-failure[:N] допускается."""
    policy = str(val or "").strip() or "no"
    base = policy.split(":", 1)[0]
    if base not in RESTART_POLICIES:
        raise StepError(
            "validate_restart", -1, title="Политика перезапуска",
            detail=f"недопустимая политика: {val!r} (одна из {', '.join(RESTART_POLICIES)})",
        )
    if base == "on-failure" and ":" in policy:
        n = policy.split(":", 1)[1]
        if not n.isdigit():
            raise StepError(
                "validate_restart", -1, title="Политика перезапуска",
                detail=f"ожидается on-failure:<число>: {val!r}",
            )
    return policy


def parse_list(val: Any) -> List[str]:
    """Нормализовать вход в список непустых строк.

    Принимает list (из JSON), либо строку с разделителями (перевод строки/запятая).
    UI-форма присылает многострочные textarea — оба варианта поддержаны.
    """
    if val is None:
        return []
    if isinstance(val, (list, tuple)):
        items = [str(x).strip() for x in val]
    else:
        items = re.split(r"[\n,]+", str(val))
        items = [x.strip() for x in items]
    return [x for x in items if x]


def validate_ports(val: Any) -> List[str]:
    return [validate_port(x) for x in parse_list(val)]


def validate_envs(val: Any) -> List[str]:
    return [validate_env(x) for x in parse_list(val)]
