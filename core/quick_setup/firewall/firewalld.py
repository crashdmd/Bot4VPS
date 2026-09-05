# -*- coding: utf-8 -*-
"""firewalld backend с zone/runtime/permanent verification."""
from __future__ import annotations

import re
import shlex
from typing import Optional

from core.ssh import exec_sudo

from ..package_manager import detect as detect_package_manager
from .base import (
    FirewallBackend,
    FirewallInfo,
    FirewallMutation,
    FirewallRule,
    FirewallStateChange,
    is_ip_source,
    normalize_source,
    source_ip_version,
    source_keeps_access,
)

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_PORT_RE = re.compile(r"^(\d+)(?:-(\d+))?/(tcp|udp)$", re.I)
# Каноническая форма наших source-правил: rich rule с address + port + accept.
_RICH_SOURCE_RE = re.compile(
    r'^rule\s+family="(ipv4|ipv6)"\s+source\s+address="([^"]+)"\s+'
    r'port\s+port="(\d+)"\s+protocol="(tcp|udp)"\s+accept$',
    re.I,
)


class FirewalldBackend(FirewallBackend):
    name = "firewalld"

    def detect(self, ssh, server: dict) -> Optional[FirewallInfo]:
        code, out, _ = exec_sudo(
            ssh,
            server,
            "command -v firewall-cmd >/dev/null && echo yes || echo no",
            timeout=15,
        )
        if code != 0 or "yes" not in (out or ""):
            return None
        code, state, err = exec_sudo(ssh, server, "firewall-cmd --state", timeout=15)
        active = code == 0 and (state or "").strip().lower() == "running"
        if code not in (0, 252):
            raise RuntimeError((err or state or "firewall-cmd --state failed")[:800])
        rules = self.list_rules(ssh, server) if active else []
        return FirewallInfo(
            backend=self.name,
            active=active,
            label="firewalld" if active else "firewalld (остановлен)",
            rules=rules,
        )

    def ensure_installed(self, ssh, server: dict) -> tuple[bool, str]:
        info = self.detect(ssh, server)
        if info is None:
            manager = detect_package_manager(ssh, server)
            ok, message = manager.install(ssh, server, "firewalld")
            if not ok:
                return False, message
            info = self.detect(ssh, server)
        port = int(server.get("port") or 22)
        if not info or not info.active:
            # До запуска записываем allow в default zone, чтобы старт не оборвал SSH.
            command = (
                "zone=$(firewall-offline-cmd --get-default-zone) && "
                "case \"$zone\" in (*[!A-Za-z0-9_.-]*|'') exit 42;; esac && "
                f"firewall-offline-cmd --zone=\"$zone\" --add-port={port}/tcp && "
                "systemctl enable --now firewalld"
            )
            code, out, err = exec_sudo(ssh, server, command, timeout=60)
            if code != 0:
                return False, (err or out or "Не удалось безопасно запустить firewalld")[:800]
        opened = self.open_port(ssh, server, port, "tcp")
        if not opened.ok:
            return False, opened.error or opened.message
        verified = self.detect(ssh, server)
        if not verified or not verified.active:
            return False, "firewalld установлен, но не запущен"
        return True, "firewalld установлен; текущий SSH-порт разрешён"

    @staticmethod
    def _service_state(ssh, server: dict) -> tuple[Optional[bool], Optional[bool], Optional[str]]:
        code, out, err = exec_sudo(
            ssh,
            server,
            "active=$(systemctl is-active firewalld 2>/dev/null || true); "
            "enabled=$(systemctl is-enabled firewalld 2>/dev/null || true); "
            "printf '%s\\n%s\\n' \"$active\" \"$enabled\"",
            timeout=20,
        )
        if code != 0:
            return None, None, (err or out or "service state failed")[:800]
        lines = (out or "").splitlines()
        if len(lines) < 2:
            return None, None, "Некорректный ответ systemctl"
        active_raw, enabled_raw = lines[0].strip(), lines[1].strip()
        if active_raw not in {"active", "inactive", "failed", "unknown"}:
            return None, None, "Не удалось однозначно определить active state firewalld"
        if enabled_raw not in {"enabled", "disabled", "static", "indirect", "masked", "generated", "transient"}:
            return None, None, "Не удалось однозначно определить enabled state firewalld"
        return active_raw == "active", enabled_raw == "enabled", None

    def deactivate(self, ssh, server: dict) -> FirewallStateChange:
        active, enabled, error = self._service_state(ssh, server)
        if error or active is None or enabled is None:
            return FirewallStateChange(
                self.name,
                "deactivate",
                False,
                message="firewalld не отключён",
                error=error or "Состояние firewalld не определено",
            )
        state = {"active": active, "enabled": enabled}
        commands = []
        if active:
            commands.append("systemctl stop firewalld")
        if enabled:
            commands.append("systemctl disable firewalld")
        if commands:
            code, out, err = exec_sudo(ssh, server, " && ".join(commands), timeout=50)
        else:
            code, out, err = 0, "", ""
        verify_error = None
        try:
            inactive = code == 0 and self.verify_inactive(ssh, server)
        except Exception:
            inactive = False
            verify_error = "Состояние firewalld после отключения не подтверждено"
        return FirewallStateChange(
            self.name,
            "deactivate",
            inactive,
            changed=bool(commands) and code == 0,
            verified=inactive,
            message="firewalld остановлен; конфигурация сохранена" if inactive else "Отключение firewalld не подтверждено",
            error=None if inactive else (verify_error or err or out or "firewalld remains active")[:800],
            state=state,
        )

    def activate(self, ssh, server: dict) -> FirewallStateChange:
        if self.detect(ssh, server) is None:
            return FirewallStateChange(
                self.name,
                "activate",
                False,
                message="firewalld не включён",
                error="firewalld не установлен; включение невозможно",
                state={"active": False},
            )
        active, enabled, error = self._service_state(ssh, server)
        if error or active is None or enabled is None:
            return FirewallStateChange(
                self.name,
                "activate",
                False,
                message="firewalld не включён",
                error=error or "Состояние firewalld не определено",
            )
        state = {"active": active, "enabled": enabled}
        if active:
            return FirewallStateChange(
                self.name,
                "activate",
                True,
                verified=True,
                message="firewalld уже активен",
                state=state,
            )
        # Демон запускается первым: runtime-правила доступны только при
        # работающем firewalld; затем разрешается текущий SSH-порт.
        code, out, err = exec_sudo(
            ssh, server, "systemctl start firewalld", timeout=50
        )
        if code != 0:
            return FirewallStateChange(
                self.name,
                "activate",
                False,
                message="firewalld не включён",
                error=(err or out or "systemctl start firewalld failed")[:800],
                state=state,
            )
        port = int(server.get("port") or 22)
        opened = self.open_port(ssh, server, port, "tcp")
        if not opened.ok and not opened.token.get("deferred_verification"):
            return FirewallStateChange(
                self.name,
                "activate",
                False,
                message="firewalld не включён",
                error=(
                    opened.error
                    or opened.message
                    or "Allow текущего SSH-порта не подтверждён"
                ),
                state=state,
            )
        code, out, err = exec_sudo(
            ssh, server, "systemctl enable firewalld", timeout=50
        )
        if code != 0:
            return FirewallStateChange(
                self.name,
                "activate",
                False,
                message="firewalld не включён",
                error=(err or out or "systemctl enable firewalld failed")[:800],
                state=state,
            )
        verified = self.detect(ssh, server)
        active_now = verified is not None and verified.active is True
        return FirewallStateChange(
            self.name,
            "activate",
            active_now,
            changed=True,
            verified=active_now,
            message=(
                "firewalld запущен и включён; текущий SSH-порт разрешён"
                if active_now
                else "Включение firewalld не подтверждено"
            ),
            error=None if active_now else "firewalld activate unverified",
            state=state,
        )

    def restore(
        self,
        ssh,
        server: dict,
        state: dict,
    ) -> FirewallStateChange:
        if not {"active", "enabled"}.issubset(state):
            return FirewallStateChange(
                self.name,
                "restore",
                False,
                message="firewalld не восстановлен",
                error="missing_firewalld_state",
            )
        commands = []
        if bool(state.get("enabled")):
            commands.append("systemctl enable firewalld")
        else:
            commands.append("systemctl disable firewalld")
        if bool(state.get("active")):
            commands.append("systemctl start firewalld")
        else:
            commands.append("systemctl stop firewalld")
        code, out, err = exec_sudo(ssh, server, " && ".join(commands), timeout=50)
        active, enabled, state_error = self._service_state(ssh, server) if code == 0 else (None, None, None)
        restored = (
            code == 0
            and active is bool(state.get("active"))
            and enabled is bool(state.get("enabled"))
        )
        return FirewallStateChange(
            self.name,
            "restore",
            restored,
            changed=code == 0,
            verified=restored,
            message="Исходное состояние firewalld восстановлено" if restored else "firewalld восстановлен не полностью",
            error=None if restored else (state_error or err or out or "firewalld restore failed")[:800],
        )

    def migration_rules(
        self,
        ssh,
        server: dict,
    ) -> tuple[list[FirewallRule], list[str]]:
        zone = self._zone(ssh, server)
        all_rules = self.list_rules(ssh, server)
        # Переносятся single-port tcp/udp/ANY правила без источника и с
        # IPv4-источником (rich rules). IPv6-источники и диапазоны
        # портов остаются неоднозначными.
        exact = [
            rule
            for rule in all_rules
            if str(rule.port).isdigit()
            and rule.protocol in {"tcp", "udp", "any"}
            and (
                not is_ip_source(rule.source)
                or source_ip_version(rule.source) == 4
            )
        ]
        # Канонические IPv4 source-правила уже входят в exact — не дублируем
        # их в ambiguous при перечислении rich rules.
        exact_source_pairs = {
            (str(rule.port), rule.source)
            for rule in exact
            if is_ip_source(rule.source)
        }
        ambiguous: list[str] = []
        for permanent in (False, True):
            prefix = "--permanent " if permanent else ""
            scope = "permanent" if permanent else "runtime"
            code, services, err = exec_sudo(
                ssh,
                server,
                f"firewall-cmd {prefix}--zone={shlex.quote(zone)} --list-services",
                timeout=20,
            )
            if code != 0:
                raise RuntimeError((err or services or "firewalld service inventory failed")[:800])
            ambiguous.extend(
                f"{scope} service:{service[:100]}"
                for service in (services or "").split()
            )
            code, rich_rules, err = exec_sudo(
                ssh,
                server,
                f"firewall-cmd {prefix}--zone={shlex.quote(zone)} --list-rich-rules",
                timeout=20,
            )
            if code != 0:
                raise RuntimeError((err or rich_rules or "firewalld rich-rule inventory failed")[:800])
            for rule in (rich_rules or "").splitlines():
                rule = rule.strip()
                if not rule:
                    continue
                match = _RICH_SOURCE_RE.fullmatch(rule)
                if match:
                    address = normalize_source(match.group(2))
                    if address and (match.group(3), address) in exact_source_pairs:
                        continue
                ambiguous.append(f"{scope} rich:{rule[:400]}")
        for rule in all_rules:
            if (
                not str(rule.port).isdigit()
                or rule.protocol not in {"tcp", "udp", "any"}
                or (
                    is_ip_source(rule.source)
                    and source_ip_version(rule.source) != 4
                )
            ):
                ambiguous.append(f"zone:{zone} port:{rule.raw or rule.port}")
        return exact, list(dict.fromkeys(ambiguous))

    def _zone(self, ssh, server: dict) -> str:
        code, out, err = exec_sudo(
            ssh, server, "firewall-cmd --get-active-zones", timeout=20
        )
        if code != 0:
            raise RuntimeError((err or out or "Не удалось определить firewalld zone")[:800])
        zones = []
        for raw in (out or "").splitlines():
            if not raw or raw[0].isspace():
                continue
            name = raw.split()[0]
            if _NAME_RE.fullmatch(name):
                zones.append(name)
            else:
                raise RuntimeError("Некорректное имя активной firewalld zone")
        zones = list(dict.fromkeys(zones))
        if len(zones) > 1:
            raise RuntimeError(
                f"ambiguous_firewalld_zones: {', '.join(zones[:10])}"
            )
        if zones:
            return zones[0]
        code, out, err = exec_sudo(
            ssh, server, "firewall-cmd --get-default-zone", timeout=15
        )
        zone = (out or "").strip()
        if code != 0 or not _NAME_RE.fullmatch(zone):
            raise RuntimeError((err or out or "Не удалось определить default zone")[:800])
        return zone

    def _query(
        self,
        ssh,
        server: dict,
        zone: str,
        port: int,
        protocol: str,
        *,
        permanent: bool,
    ) -> bool:
        if protocol == "any":
            # Логическое ANY-правило firewalld — это пара записей tcp + udp.
            return (
                self._query(ssh, server, zone, port, "tcp", permanent=permanent)
                and self._query(ssh, server, zone, port, "udp", permanent=permanent)
            )
        flag = "--permanent " if permanent else ""
        code, _, _ = exec_sudo(
            ssh,
            server,
            f"firewall-cmd {flag}--zone={shlex.quote(zone)} --query-port={port}/{protocol}",
            timeout=20,
        )
        return code == 0

    def open_port(
        self,
        ssh,
        server: dict,
        port: int,
        protocol: str,
        source: str = "",
    ) -> FirewallMutation:
        zone = self._zone(ssh, server)
        if source:
            return self._open_source_port(ssh, server, zone, port, protocol, source)
        # ANY-протокол выражается парой native-записей tcp + udp в каждом scope.
        targets = ("tcp", "udp") if protocol == "any" else (protocol,)
        runtime_before = {
            item: self._query(ssh, server, zone, port, item, permanent=False)
            for item in targets
        }
        permanent_before = {
            item: self._query(ssh, server, zone, port, item, permanent=True)
            for item in targets
        }
        if all(runtime_before.values()) and all(permanent_before.values()):
            return FirewallMutation(
                self.name,
                port,
                protocol,
                "open",
                True,
                existed_before=True,
                verified=True,
                message=f"Порт {port}/{protocol} уже открыт",
                token={"zone": zone, "runtime": True, "permanent": True},
            )

        commands = []
        for item in targets:
            if not permanent_before[item]:
                commands.append(
                    f"firewall-cmd --permanent --zone={shlex.quote(zone)} --add-port={port}/{item}"
                )
        for item in targets:
            if not runtime_before[item]:
                commands.append(
                    f"firewall-cmd --zone={shlex.quote(zone)} --add-port={port}/{item}"
                )
        code, out, err = exec_sudo(
            ssh, server, " && ".join(commands), timeout=40
        )
        runtime_after = {
            item: (
                self._query(ssh, server, zone, port, item, permanent=False)
                if code == 0
                else runtime_before[item]
            )
            for item in targets
        }
        permanent_after = {
            item: (
                self._query(ssh, server, zone, port, item, permanent=True)
                if code == 0
                else permanent_before[item]
            )
            for item in targets
        }
        verified = all(runtime_after.values()) and all(permanent_after.values())
        any_created = any(
            runtime_before[item] != runtime_after[item]
            or permanent_before[item] != permanent_after[item]
            for item in targets
        )
        return FirewallMutation(
            self.name,
            port,
            protocol,
            "open",
            code == 0 and verified,
            changed=any_created,
            existed_before=any(runtime_before.values()) or any(permanent_before.values()),
            verified=verified,
            message=f"Открыт {port}/{protocol}" if verified else "Не удалось открыть порт",
            error=None if code == 0 and verified else (err or out or "Правило не подтверждено")[:800],
            token={
                "zone": zone,
                "runtime_created": any(
                    runtime_before[item] != runtime_after[item] for item in targets
                ),
                "permanent_created": any(
                    permanent_before[item] != permanent_after[item] for item in targets
                ),
            },
        )

    @staticmethod
    def _source_targets(protocol: str) -> tuple[str, ...]:
        """Native-протоколы, через которые выражается запрошенное правило."""
        return ("tcp", "udp") if protocol == "any" else (protocol,)

    @staticmethod
    def _rich_rule(port: int, protocol: str, source: str) -> str:
        """Канонический rich rule для source-правила (port + source)."""
        family = "ipv4" if source_ip_version(source) == 4 else "ipv6"
        return (
            f'rule family="{family}" source address="{source}" '
            f'port port="{port}" protocol="{protocol}" accept'
        )

    def _query_rich(
        self,
        ssh,
        server: dict,
        zone: str,
        rich: str,
        *,
        permanent: bool,
    ) -> bool:
        flag = "--permanent " if permanent else ""
        code, _, _ = exec_sudo(
            ssh,
            server,
            f"firewall-cmd {flag}--zone={shlex.quote(zone)} "
            f"--query-rich-rule={shlex.quote(rich)}",
            timeout=20,
        )
        return code == 0

    def _open_source_port(
        self,
        ssh,
        server: dict,
        zone: str,
        port: int,
        protocol: str,
        source: str,
    ) -> FirewallMutation:
        """Открыть port/protocol для источника через rich rules (оба scope)."""
        targets = self._source_targets(protocol)
        rich_rules = {item: self._rich_rule(port, item, source) for item in targets}
        runtime_before = {
            item: self._query_rich(
                ssh, server, zone, rich_rules[item], permanent=False
            )
            for item in targets
        }
        permanent_before = {
            item: self._query_rich(
                ssh, server, zone, rich_rules[item], permanent=True
            )
            for item in targets
        }
        if all(runtime_before.values()) and all(permanent_before.values()):
            return FirewallMutation(
                self.name,
                port,
                protocol,
                "open",
                True,
                existed_before=True,
                verified=True,
                message=f"Порт {port}/{protocol} от {source} уже открыт",
                token={"zone": zone, "source": source, "rich": True},
            )
        commands = []
        for item in targets:
            if not permanent_before[item]:
                commands.append(
                    f"firewall-cmd --permanent --zone={shlex.quote(zone)} "
                    f"--add-rich-rule={shlex.quote(rich_rules[item])}"
                )
        for item in targets:
            if not runtime_before[item]:
                commands.append(
                    f"firewall-cmd --zone={shlex.quote(zone)} "
                    f"--add-rich-rule={shlex.quote(rich_rules[item])}"
                )
        code, out, err = exec_sudo(
            ssh, server, " && ".join(commands), timeout=40
        )
        runtime_after = {
            item: (
                self._query_rich(ssh, server, zone, rich_rules[item], permanent=False)
                if code == 0
                else runtime_before[item]
            )
            for item in targets
        }
        permanent_after = {
            item: (
                self._query_rich(ssh, server, zone, rich_rules[item], permanent=True)
                if code == 0
                else permanent_before[item]
            )
            for item in targets
        }
        verified = all(runtime_after.values()) and all(permanent_after.values())
        any_created = any(
            runtime_before[item] != runtime_after[item]
            or permanent_before[item] != permanent_after[item]
            for item in targets
        )
        return FirewallMutation(
            self.name,
            port,
            protocol,
            "open",
            code == 0 and verified,
            changed=any_created,
            existed_before=any(runtime_before.values()) or any(permanent_before.values()),
            verified=verified,
            message=(
                f"Открыт {port}/{protocol} от {source}"
                if verified
                else "Не удалось открыть порт"
            ),
            error=None if code == 0 and verified else (err or out or "Правило не подтверждено")[:800],
            token={"zone": zone, "source": source, "rich": True},
        )

    def preflight_close_port(
        self,
        ssh,
        server: dict,
        port: int,
        protocol: str,
        source: str = "",
    ) -> FirewallMutation:
        zone = self._zone(ssh, server)
        if source:
            return self._preflight_close_source_port(
                ssh, server, zone, port, protocol, source
            )
        runtime = self._query(ssh, server, zone, port, protocol, permanent=False)
        permanent = self._query(ssh, server, zone, port, protocol, permanent=True)
        ambiguous = []
        for permanent_flag in (False, True):
            prefix = "--permanent " if permanent_flag else ""
            code, services_out, err = exec_sudo(
                ssh,
                server,
                f"firewall-cmd {prefix}--zone={shlex.quote(zone)} --list-services",
                timeout=20,
            )
            if code != 0:
                return FirewallMutation(
                    self.name, port, protocol, "preflight_close", False,
                    message="Не удалось проверить firewalld services",
                    error=(err or services_out or "service inventory failed")[:800],
                )
            for service in (services_out or "").split():
                if not _NAME_RE.fullmatch(service):
                    ambiguous.append(f"service:{service[:80]}")
                    continue
                if self._service_covers(
                    ssh, server, service, port, protocol, permanent=permanent_flag
                ):
                    ambiguous.append(
                        f"{'permanent' if permanent_flag else 'runtime'} service:{service}"
                    )

            code, rich_out, err = exec_sudo(
                ssh,
                server,
                f"firewall-cmd {prefix}--zone={shlex.quote(zone)} --list-rich-rules",
                timeout=20,
            )
            if code != 0:
                return FirewallMutation(
                    self.name, port, protocol, "preflight_close", False,
                    message="Не удалось проверить firewalld rich rules",
                    error=(err or rich_out or "rich-rule inventory failed")[:800],
                )
            for rule in (rich_out or "").splitlines():
                covers = self._rich_rule_covers(
                    ssh, server, rule.strip(), port, protocol, permanent_flag
                )
                if covers is not False:
                    ambiguous.append(
                        f"{'permanent' if permanent_flag else 'runtime'} rich:{rule.strip()}"
                    )
        if ambiguous:
            return FirewallMutation(
                self.name,
                port,
                protocol,
                "preflight_close",
                False,
                existed_before=runtime or permanent,
                message="Старый порт разрешён broad/shared правилом firewalld",
                error="ambiguous_shared_rule",
                token={"zone": zone, "rules": " | ".join(ambiguous[:5])[:500]},
            )
        return FirewallMutation(
            self.name,
            port,
            protocol,
            "preflight_close",
            True,
            existed_before=runtime or permanent,
            verified=True,
            message=(
                f"Точное правило {port}/{protocol} можно удалить"
                if runtime or permanent
                else f"Отдельное правило {port}/{protocol} отсутствует"
            ),
            token={"zone": zone, "runtime": runtime, "permanent": permanent},
        )

    def _preflight_close_source_port(
        self,
        ssh,
        server: dict,
        zone: str,
        port: int,
        protocol: str,
        source: str,
    ) -> FirewallMutation:
        """Проверить точное удаление source-правила (rich rules, оба scope)."""
        targets = self._source_targets(protocol)
        rich_rules = {item: self._rich_rule(port, item, source) for item in targets}
        runtime = {
            item: self._query_rich(
                ssh, server, zone, rich_rules[item], permanent=False
            )
            for item in targets
        }
        permanent = {
            item: self._query_rich(
                ssh, server, zone, rich_rules[item], permanent=True
            )
            for item in targets
        }
        existed = any(runtime.values()) or any(permanent.values())
        ambiguous = []
        for permanent_flag in (False, True):
            prefix = "--permanent " if permanent_flag else ""
            code, services_out, err = exec_sudo(
                ssh,
                server,
                f"firewall-cmd {prefix}--zone={shlex.quote(zone)} --list-services",
                timeout=20,
            )
            if code != 0:
                return FirewallMutation(
                    self.name, port, protocol, "preflight_close", False,
                    message="Не удалось проверить firewalld services",
                    error=(err or services_out or "service inventory failed")[:800],
                )
            for service in (services_out or "").split():
                if not _NAME_RE.fullmatch(service):
                    ambiguous.append(f"service:{service[:80]}")
                    continue
                if self._service_covers(
                    ssh, server, service, port, protocol, permanent=permanent_flag
                ):
                    ambiguous.append(
                        f"{'permanent' if permanent_flag else 'runtime'} service:{service}"
                    )

            code, rich_out, err = exec_sudo(
                ssh,
                server,
                f"firewall-cmd {prefix}--zone={shlex.quote(zone)} --list-rich-rules",
                timeout=20,
            )
            if code != 0:
                return FirewallMutation(
                    self.name, port, protocol, "preflight_close", False,
                    message="Не удалось проверить firewalld rich rules",
                    error=(err or rich_out or "rich-rule inventory failed")[:800],
                )
            for rule in (rich_out or "").splitlines():
                rule = rule.strip()
                if rule in rich_rules.values():
                    # Само закрываемое правило не является помехой.
                    continue
                covers = self._rich_rule_covers(
                    ssh, server, rule, port, protocol, permanent_flag,
                    request_source=source,
                )
                if covers is not False:
                    ambiguous.append(
                        f"{'permanent' if permanent_flag else 'runtime'} rich:{rule}"
                    )
        if ambiguous:
            return FirewallMutation(
                self.name,
                port,
                protocol,
                "preflight_close",
                False,
                existed_before=existed,
                message="Старый порт разрешён broad/shared правилом firewalld",
                error="ambiguous_shared_rule",
                token={"zone": zone, "rules": " | ".join(ambiguous[:5])[:500]},
            )
        return FirewallMutation(
            self.name,
            port,
            protocol,
            "preflight_close",
            True,
            existed_before=existed,
            verified=True,
            message=(
                f"Точное правило {port}/{protocol} от {source} можно удалить"
                if existed
                else f"Отдельное правило {port}/{protocol} от {source} отсутствует"
            ),
            token={"zone": zone, "source": source, "rich": True},
        )

    def _close_source_port(
        self,
        ssh,
        server: dict,
        zone: str,
        port: int,
        protocol: str,
        source: str,
    ) -> FirewallMutation:
        """Удалить rich rules source-правила (tcp/udp при any) в обоих scope."""
        targets = self._source_targets(protocol)
        rich_rules = {item: self._rich_rule(port, item, source) for item in targets}
        runtime_present = {
            item: self._query_rich(
                ssh, server, zone, rich_rules[item], permanent=False
            )
            for item in targets
        }
        permanent_present = {
            item: self._query_rich(
                ssh, server, zone, rich_rules[item], permanent=True
            )
            for item in targets
        }
        if not any(runtime_present.values()) and not any(permanent_present.values()):
            return FirewallMutation(
                self.name,
                port,
                protocol,
                "close",
                True,
                verified=True,
                message=f"Отдельное правило {port}/{protocol} от {source} отсутствует",
            )
        commands = []
        for item in targets:
            if permanent_present[item]:
                commands.append(
                    f"firewall-cmd --permanent --zone={shlex.quote(zone)} "
                    f"--remove-rich-rule={shlex.quote(rich_rules[item])}"
                )
        for item in targets:
            if runtime_present[item]:
                commands.append(
                    f"firewall-cmd --zone={shlex.quote(zone)} "
                    f"--remove-rich-rule={shlex.quote(rich_rules[item])}"
                )
        code, out, err = exec_sudo(
            ssh, server, " && ".join(commands), timeout=40
        )
        runtime_after = {
            item: (
                self._query_rich(ssh, server, zone, rich_rules[item], permanent=False)
                if code == 0
                else runtime_present[item]
            )
            for item in targets
        }
        permanent_after = {
            item: (
                self._query_rich(ssh, server, zone, rich_rules[item], permanent=True)
                if code == 0
                else permanent_present[item]
            )
            for item in targets
        }
        absent = (
            code == 0
            and not any(runtime_after.values())
            and not any(permanent_after.values())
        )
        return FirewallMutation(
            self.name,
            port,
            protocol,
            "close",
            absent,
            changed=absent,
            existed_before=True,
            verified=absent,
            message=(
                f"Закрыт {port}/{protocol} от {source}"
                if absent
                else "Не удалось закрыть порт"
            ),
            error=None if absent else (err or out or "Удаление не подтверждено")[:800],
            token={"zone": zone, "source": source, "rich": True},
        )

    def close_port(
        self,
        ssh,
        server: dict,
        port: int,
        protocol: str,
        source: str = "",
    ) -> FirewallMutation:
        preflight = self.preflight_close_port(ssh, server, port, protocol, source)
        if not preflight.ok:
            return preflight
        zone = str(preflight.token.get("zone") or "")
        if source:
            return self._close_source_port(ssh, server, zone, port, protocol, source)
        if protocol == "any":
            return self._close_any_port(ssh, server, zone, port)
        runtime_before = bool(preflight.token.get("runtime"))
        permanent_before = bool(preflight.token.get("permanent"))
        if not runtime_before and not permanent_before:
            return FirewallMutation(
                self.name,
                port,
                protocol,
                "close",
                True,
                verified=True,
                message=f"Отдельное правило {port}/{protocol} отсутствует",
            )
        commands = []
        if permanent_before:
            commands.append(
                f"firewall-cmd --permanent --zone={shlex.quote(zone)} --remove-port={port}/{protocol}"
            )
        if runtime_before:
            commands.append(
                f"firewall-cmd --zone={shlex.quote(zone)} --remove-port={port}/{protocol}"
            )
        code, out, err = exec_sudo(
            ssh, server, " && ".join(commands), timeout=40
        )
        runtime = self._query(
            ssh, server, zone, port, protocol, permanent=False
        ) if code == 0 else runtime_before
        permanent = self._query(
            ssh, server, zone, port, protocol, permanent=True
        ) if code == 0 else permanent_before
        absent = code == 0 and not runtime and not permanent
        return FirewallMutation(
            self.name,
            port,
            protocol,
            "close",
            absent,
            changed=absent,
            existed_before=True,
            verified=absent,
            message=f"Закрыт {port}/{protocol}" if absent else "Не удалось закрыть порт",
            error=None if absent else (err or out or "Удаление не подтверждено")[:800],
            token={"zone": zone},
        )

    def _close_any_port(
        self,
        ssh,
        server: dict,
        zone: str,
        port: int,
    ) -> FirewallMutation:
        """Удалить обе native-записи (tcp и udp) логического ANY-правила."""
        targets = ("tcp", "udp")
        runtime_present = {
            item: self._query(ssh, server, zone, port, item, permanent=False)
            for item in targets
        }
        permanent_present = {
            item: self._query(ssh, server, zone, port, item, permanent=True)
            for item in targets
        }
        if not any(runtime_present.values()) and not any(permanent_present.values()):
            return FirewallMutation(
                self.name,
                port,
                "any",
                "close",
                True,
                verified=True,
                message=f"Отдельное правило {port}/any отсутствует",
            )
        commands = []
        for item in targets:
            if permanent_present[item]:
                commands.append(
                    f"firewall-cmd --permanent --zone={shlex.quote(zone)} --remove-port={port}/{item}"
                )
        for item in targets:
            if runtime_present[item]:
                commands.append(
                    f"firewall-cmd --zone={shlex.quote(zone)} --remove-port={port}/{item}"
                )
        code, out, err = exec_sudo(
            ssh, server, " && ".join(commands), timeout=40
        )
        runtime_after = {
            item: (
                self._query(ssh, server, zone, port, item, permanent=False)
                if code == 0
                else runtime_present[item]
            )
            for item in targets
        }
        permanent_after = {
            item: (
                self._query(ssh, server, zone, port, item, permanent=True)
                if code == 0
                else permanent_present[item]
            )
            for item in targets
        }
        absent = (
            code == 0
            and not any(runtime_after.values())
            and not any(permanent_after.values())
        )
        return FirewallMutation(
            self.name,
            port,
            "any",
            "close",
            absent,
            changed=absent,
            existed_before=True,
            verified=absent,
            message=f"Закрыт {port}/any" if absent else "Не удалось закрыть порт",
            error=None if absent else (err or out or "Удаление не подтверждено")[:800],
            token={"zone": zone},
        )

    def cleanup_mutation(self, ssh, server: dict, mutation: FirewallMutation) -> FirewallMutation:
        if mutation.backend != self.name or not mutation.changed or mutation.existed_before:
            return FirewallMutation(
                self.name,
                mutation.port,
                mutation.protocol,
                "cleanup",
                False,
                message="Правило не было новым точным изменением этой операции и не удалено",
                error="cleanup_refused_not_exact_change",
            )
        current_zone = self._zone(ssh, server)
        if current_zone != str(mutation.token.get("zone") or ""):
            return FirewallMutation(
                self.name,
                mutation.port,
                mutation.protocol,
                "cleanup",
                False,
                message="Активная firewalld zone изменилась; правило не удалено",
                error="firewalld_zone_changed",
            )
        return self.close_port(
            ssh,
            server,
            mutation.port,
            mutation.protocol,
            str(mutation.token.get("source") or ""),
        )

    def list_rules(self, ssh, server: dict) -> list[FirewallRule]:
        zone = self._zone(ssh, server)
        code, out, err = exec_sudo(
            ssh,
            server,
            f"firewall-cmd --zone={shlex.quote(zone)} --list-ports",
            timeout=20,
        )
        if code != 0:
            raise RuntimeError((err or out or "Не удалось прочитать правила firewalld")[:800])
        protocols_by_spec: dict[str, set[str]] = {}
        for token in (out or "").replace("\n", " ").split():
            match = _PORT_RE.fullmatch(token)
            if not match:
                continue
            spec = (
                match.group(1)
                if not match.group(2)
                else f"{match.group(1)}-{match.group(2)}"
            )
            protocols_by_spec.setdefault(spec, set()).add(match.group(3).lower())
        rules: list[FirewallRule] = []
        for spec, protocols in protocols_by_spec.items():
            # Пара native-записей tcp + udp — одно логическое ANY-правило.
            if protocols == {"tcp", "udp"}:
                rules.append(FirewallRule(
                    spec,
                    "any",
                    raw=f"{spec}/any",
                    source=f"zone:{zone}",
                ))
            else:
                protocol = next(iter(protocols))
                rules.append(FirewallRule(
                    spec,
                    protocol,
                    raw=f"{spec}/{protocol}",
                    source=f"zone:{zone}",
                ))
        rules.extend(self._source_rules(ssh, server, zone))
        return rules

    def _source_rules(self, ssh, server: dict, zone: str) -> list[FirewallRule]:
        """Прочитать наши source-правила из rich rules активной zone."""
        code, out, err = exec_sudo(
            ssh,
            server,
            f"firewall-cmd --zone={shlex.quote(zone)} --list-rich-rules",
            timeout=20,
        )
        if code != 0:
            raise RuntimeError((err or out or "Не удалось прочитать rich rules firewalld")[:800])
        # (port, source) -> множество native-протоколов; пара tcp+udp = any.
        by_pair: dict[tuple[str, str], set[str]] = {}
        for raw_rule in (out or "").splitlines():
            match = _RICH_SOURCE_RE.fullmatch(raw_rule.strip())
            if not match:
                continue
            address = normalize_source(match.group(2))
            if not address:
                continue
            by_pair.setdefault((match.group(3), address), set()).add(
                match.group(4).lower()
            )
        result: list[FirewallRule] = []
        for (spec, address), protocols in by_pair.items():
            if protocols == {"tcp", "udp"}:
                result.append(FirewallRule(
                    spec,
                    "any",
                    raw=f"{spec}/any from {address}",
                    source=address,
                ))
            else:
                protocol = next(iter(protocols))
                result.append(FirewallRule(
                    spec,
                    protocol,
                    raw=f"{spec}/{protocol} from {address}",
                    source=address,
                ))
        return result

    def _service_covers(
        self,
        ssh,
        server: dict,
        service: str,
        port: int,
        protocol: str,
        *,
        permanent: bool,
    ) -> bool:
        prefix = "--permanent " if permanent else ""
        code, out, _ = exec_sudo(
            ssh,
            server,
            f"firewall-cmd {prefix}--info-service={shlex.quote(service)}",
            timeout=20,
        )
        if code != 0:
            return True
        for line in (out or "").splitlines():
            if not line.strip().lower().startswith("ports:"):
                continue
            for token in line.split(":", 1)[1].split():
                if self._port_token_covers(token, port, protocol):
                    return True
        return False

    def _rich_rule_covers(
        self,
        ssh,
        server: dict,
        rule: str,
        port: int,
        protocol: str,
        permanent: bool,
        request_source: str = "",
    ) -> Optional[bool]:
        lowered = rule.lower()
        if not rule or "accept" not in lowered:
            return False
        port_match = re.search(
            r'port\s+port="([0-9]+(?:-[0-9]+)?)"\s+protocol="(tcp|udp)"',
            rule,
            re.I,
        )
        if port_match:
            if not self._port_token_covers(
                f"{port_match.group(1)}/{port_match.group(2)}", port, protocol
            ):
                return False
            # Rich rule с ограничением источника покрывает запрос, только
            # если его источник включает запрашиваемый source.
            source_match = re.search(r'source\s+address="([^"]+)"', rule)
            if source_match and request_source:
                return source_keeps_access(source_match.group(1), request_source)
            return True
        service_match = re.search(r'service\s+name="([A-Za-z0-9_.-]+)"', rule)
        if service_match:
            return self._service_covers(
                ssh,
                server,
                service_match.group(1),
                port,
                protocol,
                permanent=permanent,
            )
        if "icmp" in lowered:
            return False
        return None

    @staticmethod
    def _port_token_covers(token: str, port: int, protocol: str) -> bool:
        if protocol == "any":
            # ANY-запрос покрыт, если сервис/rich rule открывает порт по tcp или udp.
            return (
                FirewalldBackend._port_token_covers(token, port, "tcp")
                or FirewalldBackend._port_token_covers(token, port, "udp")
            )
        match = _PORT_RE.fullmatch(token.strip())
        if not match or match.group(3).lower() != protocol:
            return False
        start = int(match.group(1))
        end = int(match.group(2) or start)
        return min(start, end) <= port <= max(start, end)
