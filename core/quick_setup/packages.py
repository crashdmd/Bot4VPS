# -*- coding: utf-8 -*-
"""Раздел «Пакеты»: каталог по категориям, статус и установка."""
from __future__ import annotations

import re

from core.ssh import create_ssh_client, exec_sudo

from .models import OpResult, PackageItem, PackagesStatus
from .package_manager import detect

# Каталог: логическое имя → категория. Порядок внутри категории = порядок
# в UI. Логические имена с расхождениями между менеджерами (netcat,
# dnsutils, cron) резолвятся через PACKAGE_ALIASES.
PACKAGE_CATALOG: tuple[tuple[str, str], ...] = (
    # Утилиты
    ("curl", "utils"),
    ("wget", "utils"),
    ("git", "utils"),
    ("vim", "utils"),
    ("nano", "utils"),
    ("htop", "utils"),
    ("btop", "utils"),
    ("tree", "utils"),
    ("tmux", "utils"),
    ("screen", "utils"),
    # Сеть
    ("netcat", "net"),
    ("dnsutils", "net"),
    ("traceroute", "net"),
    ("tcpdump", "net"),
    ("socat", "net"),
    # Диагностика
    ("ncdu", "diag"),
    ("iotop", "diag"),
    ("sysstat", "diag"),
    ("psmisc", "diag"),
    ("smartmontools", "diag"),
    ("lsof", "diag"),
    # Сервисы
    ("nginx", "services"),
    ("apache2", "services"),
    ("certbot", "services"),
    ("docker.io", "services"),
    ("python3", "services"),
    ("python3-pip", "services"),
    ("mariadb-server", "services"),
    ("postgresql", "services"),
    ("cron", "services"),
    ("logrotate", "services"),
    ("acl", "services"),
)

CATEGORY_TITLES: dict[str, str] = {
    "utils": "Утилиты",
    "net": "Сеть",
    "diag": "Диагностика",
    "services": "Сервисы",
}

DEFAULT_PACKAGES: tuple[str, ...] = tuple(name for name, _ in PACKAGE_CATALOG)

_PKG_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.+_-]{0,63}$")


def _valid_names(names: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in names:
        name = (raw or "").strip()
        if not name or name in seen:
            continue
        if not _PKG_NAME_RE.match(name):
            raise ValueError(f"Некорректное имя пакета: {name!r}")
        seen.add(name)
        out.append(name)
    return out


def list_packages(server: dict, names: list[str] | None = None) -> PackagesStatus:
    """Статус пакетов каталога — ОДНИМ batch-запросом к менеджеру.

    Имена логические: под фактический менеджер их резолвит aliases_for
    (позиции без алиаса для этого менеджера не показываются). Категория
    берётся из каталога; для имён вне каталога — пустая.
    """
    pkg_names = _valid_names(list(names) if names is not None else list(DEFAULT_PACKAGES))
    status = PackagesStatus(items=[])
    if not pkg_names:
        return status

    catalog_category = dict(PACKAGE_CATALOG)
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=12)
        package_manager = detect(ssh, server)
        resolved = package_manager.aliases_for(pkg_names)
        installed_map = package_manager.is_installed_batch(ssh, server, resolved)
        items = [
            PackageItem(
                name=name,
                installed=bool(installed_map.get(package_manager.resolve(name), False)),
                category=catalog_category.get(name, ""),
            )
            for name in pkg_names
            if package_manager.resolve(name) in resolved
        ]
        status.items = items
        return status
    except Exception as e:
        status.items = [
            PackageItem(name=n, installed=False, category=catalog_category.get(n, ""))
            for n in pkg_names
        ]
        status.error = str(e)[:400]
        return status
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def install_packages(server: dict, names: list[str]) -> OpResult:
    """Установить выбранные пакеты ОДНОЙ командой менеджера.

    Поштучные apt-get update/install (по одному на пакет) заменены общим
    батчем. После установки фактический статус перепроверяется batch-
    запросом; неустановленные позиции попадают в отказ.
    """
    try:
        pkg_names = _valid_names(names)
    except ValueError as e:
        return OpResult(ok=False, message="Некорректный список пакетов", error=str(e))

    if not pkg_names:
        return OpResult(ok=False, message="Не выбран ни один пакет", error="empty")

    catalog_category = dict(PACKAGE_CATALOG)
    ssh = None
    messages: list[str] = []
    try:
        ssh = create_ssh_client(server, timeout=20)
        package_manager = detect(ssh, server)
        resolved = package_manager.aliases_for(pkg_names)
        if not resolved:
            return OpResult(
                ok=False,
                message="Пакеты недоступны для этого package manager",
                error="packages_unavailable",
                data={"package_manager": package_manager.name},
            )

        install_map = package_manager.is_installed_batch(ssh, server, resolved)
        already = [p for p in resolved if install_map.get(p)]
        missing = [p for p in resolved if not install_map.get(p)]
        if already:
            messages.append(f"уже установлены: {', '.join(already)}")
        if not missing:
            return OpResult(
                ok=True,
                message="Все выбранные пакеты уже установлены",
                output="\n".join(messages)[-4000:],
                data={"package_manager": package_manager.name},
            )

        ok, error, batch_messages = package_manager.install_batch(ssh, server, missing)
        messages.extend(batch_messages)
        if not ok:
            return OpResult(
                ok=False,
                message="Не удалось установить пакеты",
                output="\n".join(messages)[-4000:],
                error=str(error or "package_install_failed")[:1000],
                data={"package_manager": package_manager.name},
            )

        verify_map = package_manager.is_installed_batch(ssh, server, resolved)
        reverse = {package_manager.resolve(n): n for n in pkg_names if package_manager.resolve(n) in resolved}
        items = [
            {"name": logical, "installed": bool(verify_map.get(actual, False))}
            for actual, logical in reverse.items()
        ]
        failed = [i["name"] for i in items if not i["installed"]]
        if failed:
            return OpResult(
                ok=False,
                message=f"Не все пакеты подтверждены после установки: {', '.join(failed)}",
                output="\n".join(messages)[-4000:],
                error="package_verification_failed",
                data={"package_manager": package_manager.name, "packages": items},
            )
        return OpResult(
            ok=True,
            message=f"Установлено: {', '.join(i['name'] for i in items)}",
            output="\n".join(messages)[-4000:],
            data={"package_manager": package_manager.name, "packages": items},
        )
    except Exception as e:
        return OpResult(
            ok=False,
            message="Ошибка установки пакетов",
            output="\n".join(messages)[-3000:],
            error=str(e)[:1000],
        )
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass
