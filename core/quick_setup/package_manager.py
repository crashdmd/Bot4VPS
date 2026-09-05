# -*- coding: utf-8 -*-
"""Минимальный проверяемый package-manager gateway для Quick Setup."""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Iterable, Sequence

from core.ssh import exec_sudo

_PACKAGE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9+._-]{0,127}$")

# Логическое имя → фактическое имя пакета у конкретного менеджера.
# Только расхождения; отсутствующий ключ = имя одинаково везде.
# Пакет из каталога с алиасом у НЕподдерживаемого менеджера не попадает
# в статус/установку (aliases_for его отфильтрует).
PACKAGE_ALIASES: dict[str, dict[str, str]] = {
    "netcat": {"apt": "netcat-openbsd", "dnf": "nmap-ncat", "yum": "nmap-ncat"},
    "dnsutils": {"apt": "dnsutils", "dnf": "bind-utils", "yum": "bind-utils"},
    "cron": {"apt": "cron", "dnf": "cronie", "yum": "cronie"},
}


@dataclass(frozen=True)
class PackageManager:
    name: str

    def _package(self, package: str) -> str:
        value = str(package or "").strip()
        if not _PACKAGE_RE.fullmatch(value):
            raise ValueError("Некорректное имя пакета")
        return value

    def resolve(self, package: str) -> str:
        """Логическое имя → имя пакета у этого менеджера."""
        package = self._package(package)
        return PACKAGE_ALIASES.get(package, {}).get(self.name, package)

    def aliases_for(self, packages: Iterable[str]) -> list[str]:
        """Имена под текущий менеджер; конфликтные логические имена без
        алиаса для него (например, netcat на zypper) отфильтровываются."""
        out: list[str] = []
        for package in packages:
            package = self._package(package)
            table = PACKAGE_ALIASES.get(package)
            if table is not None and self.name not in table:
                continue
            resolved = table.get(self.name, package) if table else package
            if resolved not in out:
                out.append(resolved)
        return out

    def is_installed(self, ssh, server: dict, package: str) -> bool:
        package = self._package(package)
        q = shlex.quote(package)
        commands = {
            "apt": f"dpkg-query -W -f='${{Status}}' {q} 2>/dev/null | grep -qx 'install ok installed'",
            "dnf": f"rpm -q -- {q} >/dev/null 2>&1",
            "yum": f"rpm -q -- {q} >/dev/null 2>&1",
            "zypper": f"rpm -q -- {q} >/dev/null 2>&1",
            "pacman": f"pacman -Q -- {q} >/dev/null 2>&1",
        }
        code, _, _ = exec_sudo(ssh, server, commands[self.name], timeout=30)
        return code == 0

    def is_installed_batch(self, ssh, server: dict, packages: Sequence[str]) -> dict[str, bool]:
        """Статус всех пакетов ОДНИМ запросом (N round-trip'ов → 1).

        Возвращает {имя_пакета_у_менеджера: установлен}. Имена уже должны
        быть resolve()-нуты под этот менеджер.
        """
        resolved = [self._package(p) for p in packages if p]
        if not resolved:
            return {}
        joined = " ".join(shlex.quote(p) for p in resolved)
        if self.name == "apt":
            command = (
                "dpkg-query -W -f='${binary:Package}\\t${Status}\\n' "
                f"{joined} 2>/dev/null | grep -P '^[^\\t]+\\tinstall ok installed$' "
                "|| true"
            )
        elif self.name in {"dnf", "yum", "zypper"}:
            command = (
                f"rpm -q --qf '%{{NAME}}\\n' -- {joined} 2>/dev/null || true"
            )
        else:
            command = f"pacman -Q -- {joined} 2>/dev/null || true"
        code, out, _ = exec_sudo(ssh, server, command, timeout=60)
        if code != 0:
            # Батч-запрос не удался — честный пустой результат, вызовущий
            # может провалиться на is_installed по одному.
            return {}
        installed: set[str] = set()
        for line in (out or "").splitlines():
            value = line.split("\t", 1)[0].strip()
            if value:
                installed.add(value)
        return {p: (p in installed) for p in resolved}

    def install_batch(self, ssh, server: dict, packages: Sequence[str]) -> tuple[bool, str, list[str]]:
        """Установить список пакетов одной командой менеджера.

        apt: один apt-get update, затем один install на весь список.
        Возвращает (ok, error, messages). Проверка факта установки
        остаётся на вызывающем (is_installed_batch).
        """
        resolved = [self._package(p) for p in packages if p]
        if not resolved:
            return True, "", []
        joined = " ".join(shlex.quote(p) for p in resolved)
        if self.name == "apt":
            command = (
                "DEBIAN_FRONTEND=noninteractive apt-get update -qq && "
                f"DEBIAN_FRONTEND=noninteractive apt-get install -y {joined}"
            )
        else:
            commands = {
                "dnf": f"dnf install -y -- {joined}",
                "yum": f"yum install -y -- {joined}",
                "zypper": f"zypper --non-interactive install -- {joined}",
                "pacman": f"pacman --noconfirm -S --needed -- {joined}",
            }
            command = commands[self.name]
        code, out, err = exec_sudo(ssh, server, command, timeout=1200)
        if code != 0:
            return False, (err or out or f"exit {code}")[-2000:], [f"{p}: не установлен" for p in resolved]
        return True, "", [f"{p}: команда установки выполнена" for p in resolved]

    def install(self, ssh, server: dict, package: str) -> tuple[bool, str]:
        package = self._package(package)
        q = shlex.quote(package)
        commands = {
            "apt": f"DEBIAN_FRONTEND=noninteractive apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y {q}",
            "dnf": f"dnf install -y -- {q}",
            "yum": f"yum install -y -- {q}",
            "zypper": f"zypper --non-interactive install -- {q}",
            "pacman": f"pacman --noconfirm -S --needed -- {q}",
        }
        code, out, err = exec_sudo(ssh, server, commands[self.name], timeout=600)
        if code != 0:
            return False, (err or out or f"exit {code}")[-2000:]
        if not self.is_installed(ssh, server, package):
            return False, "Менеджер пакетов завершил работу успешно, но пакет не обнаружен"
        return True, f"Пакет {package} установлен"

    def remove(self, ssh, server: dict, package: str, *, purge: bool = False) -> tuple[bool, str]:
        package = self._package(package)
        q = shlex.quote(package)
        apt_action = "purge" if purge else "remove"
        commands = {
            "apt": f"DEBIAN_FRONTEND=noninteractive apt-get {apt_action} -y {q}",
            "dnf": f"dnf remove -y -- {q}",
            "yum": f"yum remove -y -- {q}",
            "zypper": f"zypper --non-interactive remove -- {q}",
            "pacman": f"pacman --noconfirm -R -- {q}",
        }
        code, out, err = exec_sudo(ssh, server, commands[self.name], timeout=600)
        if code != 0:
            return False, (err or out or f"exit {code}")[-2000:]
        if self.is_installed(ssh, server, package):
            return False, "После удаления пакет всё ещё установлен"
        return True, f"Пакет {package} удалён"


def detect(ssh, server: dict) -> PackageManager:
    command = (
        "for x in apt-get dnf yum zypper pacman; do "
        "command -v \"$x\" >/dev/null 2>&1 && { echo \"$x\"; exit 0; }; done; exit 1"
    )
    code, out, err = exec_sudo(ssh, server, command, timeout=20)
    if code != 0:
        raise RuntimeError((err or "Поддерживаемый package manager не найден")[:800])
    raw = (out or "").strip().splitlines()[0] if out else ""
    name = "apt" if raw == "apt-get" else raw
    if name not in {"apt", "dnf", "yum", "zypper", "pacman"}:
        raise RuntimeError("Не удалось определить package manager")
    return PackageManager(name)
