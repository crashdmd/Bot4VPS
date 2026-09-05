# -*- coding: utf-8 -*-
"""UFW backend с точными numbered-rule мутациями."""
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
    normalize_source,
    source_ip_version,
    source_keeps_access,
)

_DIRECT_TARGET_RE = re.compile(
    r"^(\d+)(?:[:\-](\d+))?(?:/(tcp|udp|any))?(?:\s+\(v6\))?$",
    re.I,
)
_PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()+\-]{0,127}$")
_EXISTING_RULE_NOTICE_RE = re.compile(
    r"^Skipping adding existing rule(?: \(v6\))?$",
    re.I,
)


def _rule_label(port: int, protocol: str, source: str = "") -> str:
    label = f"{port}/{protocol}"
    return f"{label} от {source}" if source else label


class UfwBackend(FirewallBackend):
    name = "ufw"

    def detect(self, ssh, server: dict) -> Optional[FirewallInfo]:
        code, out, _ = exec_sudo(
            ssh, server, "command -v ufw >/dev/null && echo yes || echo no", timeout=15
        )
        if code != 0 or "yes" not in (out or ""):
            return None
        code, status, err = exec_sudo(ssh, server, "ufw status numbered", timeout=20)
        if code != 0:
            raise RuntimeError((err or status or "ufw status failed")[:800])
        text = (status or "").strip()
        first = text.splitlines()[0].lower() if text else ""
        active = "active" in first and "inactive" not in first
        return FirewallInfo(
            backend=self.name,
            active=active,
            label="UFW" if active else "UFW (неактивен)",
            rules=self._parse_status(text),
        )

    def ensure_installed(self, ssh, server: dict) -> tuple[bool, str]:
        info = self.detect(ssh, server)
        if info is None:
            manager = detect_package_manager(ssh, server)
            ok, message = manager.install(ssh, server, "ufw")
            if not ok:
                return False, message
        port = int(server.get("port") or 22)
        opened = self.open_port(ssh, server, port, "tcp")
        if not opened.ok and not opened.token.get("deferred_verification"):
            return False, opened.error or opened.message
        code, out, err = exec_sudo(ssh, server, "ufw --force enable", timeout=40)
        if code != 0:
            return False, (err or out or "ufw enable failed")[:800]
        verified = self.detect(ssh, server)
        if (
            not verified
            or not verified.active
            or not self._standard_exact(verified.rules, port, "tcp")
        ):
            return False, "UFW включён без подтверждённого allow текущего SSH-порта"
        return True, "UFW установлен и включён; текущий SSH-порт разрешён"

    def deactivate(self, ssh, server: dict) -> FirewallStateChange:
        info = self.detect(ssh, server)
        if info is None:
            return FirewallStateChange(
                self.name,
                "deactivate",
                True,
                verified=True,
                message="UFW не установлен; изменение не требуется",
                state={"active": False},
            )
        active_before = info.active is True
        state = {"active": active_before}
        if not active_before:
            return FirewallStateChange(
                self.name,
                "deactivate",
                True,
                verified=self.verify_inactive(ssh, server),
                message="UFW уже неактивен",
                state=state,
            )
        code, out, err = exec_sudo(ssh, server, "ufw --force disable", timeout=40)
        verify_error = None
        try:
            inactive = code == 0 and self.verify_inactive(ssh, server)
        except Exception:
            inactive = False
            verify_error = "Состояние UFW после отключения не подтверждено"
        return FirewallStateChange(
            self.name,
            "deactivate",
            inactive,
            changed=code == 0,
            verified=inactive,
            message="UFW отключён; правила сохранены" if inactive else "Отключение UFW не подтверждено",
            error=None if inactive else (verify_error or err or out or "ufw remains active")[:800],
            state=state,
        )

    def activate(self, ssh, server: dict) -> FirewallStateChange:
        info = self.detect(ssh, server)
        if info is None:
            return FirewallStateChange(
                self.name,
                "activate",
                False,
                message="UFW не включён",
                error="UFW не установлен; включение невозможно",
                state={"active": False},
            )
        state = {"active": info.active is True}
        if info.active is True:
            return FirewallStateChange(
                self.name,
                "activate",
                True,
                verified=True,
                message="UFW уже активен",
                state=state,
            )
        port = int(server.get("port") or 22)
        opened = self.open_port(ssh, server, port, "tcp")
        if not opened.ok and not opened.token.get("deferred_verification"):
            return FirewallStateChange(
                self.name,
                "activate",
                False,
                message="UFW не включён",
                error=opened.error or opened.message,
                state=state,
            )
        code, out, err = exec_sudo(ssh, server, "ufw --force enable", timeout=40)
        if code != 0:
            return FirewallStateChange(
                self.name,
                "activate",
                False,
                message="UFW не включён",
                error=(err or out or "ufw enable failed")[:800],
                state=state,
            )
        verified = self.detect(ssh, server)
        active_now = (
            verified is not None
            and verified.active is True
            and bool(self._standard_exact(verified.rules, port, "tcp"))
        )
        return FirewallStateChange(
            self.name,
            "activate",
            active_now,
            changed=True,
            verified=active_now,
            message=(
                "UFW включён; текущий SSH-порт разрешён"
                if active_now
                else "UFW включён без подтверждённого allow текущего SSH-порта"
            ),
            error=None if active_now else "ufw enable unverified",
            state=state,
        )

    def restore(
        self,
        ssh,
        server: dict,
        state: dict,
    ) -> FirewallStateChange:
        if state.get("active") is not True:
            return FirewallStateChange(
                self.name,
                "restore",
                True,
                verified=True,
                message="Восстановление UFW не требуется",
            )
        code, out, err = exec_sudo(ssh, server, "ufw --force enable", timeout=40)
        info = self.detect(ssh, server) if code == 0 else None
        restored = bool(info and info.active is True)
        return FirewallStateChange(
            self.name,
            "restore",
            restored,
            changed=code == 0,
            verified=restored,
            message="Исходное активное состояние UFW восстановлено" if restored else "UFW не восстановлен",
            error=None if restored else (err or out or "ufw restore failed")[:800],
        )

    def migration_rules(
        self,
        ssh,
        server: dict,
    ) -> tuple[list[FirewallRule], list[str]]:
        exact: list[FirewallRule] = []
        ambiguous: list[str] = []
        for rule in self.list_rules(ssh, server):
            parsed = self._direct_target(rule.port)
            if not (
                parsed
                and parsed[0] == parsed[1]
                and parsed[2] in {"tcp", "udp", "any"}
                and rule.action.lower() == "allow"
                and rule.direction.lower() == "in"
            ):
                if rule.raw:
                    ambiguous.append(rule.raw)
                continue
            raw_source = rule.source.strip()
            if raw_source.lower() in {"anywhere", "anywhere (v6)"}:
                source = ""
            else:
                source = normalize_source(raw_source)
                # Переносятся только IPv4-источники; IPv6 и нераспознанные
                # значения остаются неоднозначными.
                if not source or source_ip_version(source) != 4:
                    if rule.raw:
                        ambiguous.append(rule.raw)
                    continue
            exact.append(FirewallRule(
                port=str(parsed[0]),
                protocol=parsed[2],
                raw=rule.raw,
                source=source,
            ))
        return exact, ambiguous

    def open_port(
        self,
        ssh,
        server: dict,
        port: int,
        protocol: str,
        source: str = "",
    ) -> FirewallMutation:
        before = self.list_rules(ssh, server)
        standard_before = self._standard_exact(before, port, protocol, source)
        if standard_before:
            safe, reason = self._numbered_rules_safe(standard_before)
            return FirewallMutation(
                self.name,
                port,
                protocol,
                "open",
                safe,
                existed_before=True,
                verified=safe,
                message=(
                    f"Порт {_rule_label(port, protocol, source)} уже открыт"
                    if safe
                    else "Существующее правило UFW неоднозначно"
                ),
                error=None if safe else reason,
                token={"count_before": len(standard_before), "source": source},
            )

        if source:
            command = f"ufw allow from {source} to any port {port}"
            if protocol != "any":
                command += f" proto {protocol}"
        else:
            command = (
                f"ufw allow {port}"
                if protocol == "any"
                else f"ufw allow {port}/{protocol}"
            )
        code, out, err = exec_sudo(
            ssh,
            server,
            command,
            timeout=30,
        )
        after = self.list_rules(ssh, server) if code == 0 else before
        standard_after = self._standard_exact(after, port, protocol, source)
        changed = not standard_before and bool(standard_after)
        safe, reason = self._numbered_rules_safe(standard_after)
        verified = code == 0 and bool(standard_after) and safe
        deferred_verification = code == 0 and not standard_after
        skipped_existing = code == 0 and self._only_existing_rule_notices(out)
        return FirewallMutation(
            self.name,
            port,
            protocol,
            "open",
            verified,
            changed=changed,
            existed_before=skipped_existing,
            verified=verified,
            message=(
                f"Открыт {_rule_label(port, protocol, source)}"
                if verified
                else (
                    f"Порт {_rule_label(port, protocol, source)} уже есть в конфигурации UFW"
                    if skipped_existing
                    else (
                        "Правило UFW принято; проверка ожидает включения firewall"
                        if deferred_verification
                        else "Не удалось открыть порт"
                    )
                )
            ),
            error=(
                None
                if verified or deferred_verification
                else (reason or err or out or "Правило не подтверждено")[:800]
            ),
            token={
                "spec": f"{port}/{protocol}",
                "source": source,
                "count_after": len(standard_after),
                "families": ",".join(sorted(self._family(rule) for rule in standard_after)),
                "deferred_verification": deferred_verification,
            },
        )

    def preflight_close_port(
        self,
        ssh,
        server: dict,
        port: int,
        protocol: str,
        source: str = "",
    ) -> FirewallMutation:
        rules = self.list_rules(ssh, server)
        exact = self._standard_exact(rules, port, protocol, source)
        safe, reason = self._numbered_rules_safe(exact)
        if not safe:
            return FirewallMutation(
                self.name,
                port,
                protocol,
                "preflight_close",
                False,
                existed_before=bool(exact),
                message="Точное правило UFW нельзя определить однозначно",
                error=reason,
            )

        ambiguous: list[str] = []
        for rule in rules:
            if rule.action.lower() != "allow" or rule.direction.lower() != "in":
                continue
            if rule in exact:
                continue
            coverage = self._rule_covers(ssh, server, rule, port, protocol, source)
            if coverage is True:
                ambiguous.append(rule.raw)
            elif coverage is None:
                ambiguous.append(rule.raw)
        if ambiguous:
            return FirewallMutation(
                self.name,
                port,
                protocol,
                "preflight_close",
                False,
                existed_before=bool(exact),
                message="Старый порт разрешён broad/shared правилом UFW",
                error="ambiguous_shared_rule",
                token={"rules": " | ".join(ambiguous[:5])[:500]},
            )
        return FirewallMutation(
            self.name,
            port,
            protocol,
            "preflight_close",
            True,
            existed_before=bool(exact),
            verified=True,
            message=(
                f"Точное правило {_rule_label(port, protocol, source)} можно удалить"
                if exact
                else f"Отдельное правило {_rule_label(port, protocol, source)} отсутствует"
            ),
            token={"count": len(exact), "source": source},
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
        matching = self._standard_exact(
            self.list_rules(ssh, server), port, protocol, source
        )
        if not matching:
            return FirewallMutation(
                self.name,
                port,
                protocol,
                "close",
                True,
                verified=True,
                message=f"Отдельное правило {_rule_label(port, protocol, source)} отсутствует",
            )
        return self._delete_standard(
            ssh, server, port, protocol, matching, "close", source
        )

    def cleanup_mutation(self, ssh, server: dict, mutation: FirewallMutation) -> FirewallMutation:
        if mutation.backend != self.name or not mutation.changed or mutation.existed_before:
            return FirewallMutation(
                self.name,
                mutation.port,
                mutation.protocol,
                "cleanup",
                False,
                error="cleanup_refused_not_exact_change",
                message="Правило не было новым точным изменением этой операции и не удалено",
            )
        source = str(mutation.token.get("source") or "")
        matching = self._standard_exact(
            self.list_rules(ssh, server), mutation.port, mutation.protocol, source
        )
        expected_count = int(mutation.token.get("count_after") or 0)
        expected_families = str(mutation.token.get("families") or "")
        actual_families = ",".join(sorted(self._family(rule) for rule in matching))
        safe, reason = self._numbered_rules_safe(matching)
        if (
            not matching
            or not safe
            or len(matching) != expected_count
            or actual_families != expected_families
        ):
            return FirewallMutation(
                self.name,
                mutation.port,
                mutation.protocol,
                "cleanup",
                False,
                message="Созданное правило UFW изменилось; автоматическое удаление остановлено",
                error=reason or "mutation_rule_changed",
            )
        return self._delete_standard(
            ssh,
            server,
            mutation.port,
            mutation.protocol,
            matching,
            "cleanup",
            source,
        )

    def _delete_standard(
        self,
        ssh,
        server: dict,
        port: int,
        protocol: str,
        matching: list[FirewallRule],
        operation: str,
        source: str = "",
    ) -> FirewallMutation:
        safe, reason = self._numbered_rules_safe(matching)
        if not safe:
            return FirewallMutation(
                self.name,
                port,
                protocol,
                operation,
                False,
                existed_before=bool(matching),
                message="Правило UFW нельзя удалить точно",
                error=reason,
            )
        numbers = sorted((int(rule.handle) for rule in matching), reverse=True)
        command = " && ".join(f"ufw --force delete {number}" for number in numbers)
        code, out, err = exec_sudo(ssh, server, command, timeout=40)
        remaining = (
            self._standard_exact(
                self.list_rules(ssh, server), port, protocol, source
            )
            if code == 0
            else matching
        )
        absent = code == 0 and not remaining
        return FirewallMutation(
            self.name,
            port,
            protocol,
            operation,
            absent,
            changed=absent,
            existed_before=True,
            verified=absent,
            message=(
                f"Закрыт {_rule_label(port, protocol, source)}"
                if absent
                else "Не удалось закрыть порт"
            ),
            error=None if absent else (err or out or "Удаление правила не подтверждено")[:800],
            token={
                "deleted_numbers": ",".join(str(number) for number in numbers),
                "source": source,
            },
        )

    def list_rules(self, ssh, server: dict) -> list[FirewallRule]:
        code, out, err = exec_sudo(ssh, server, "ufw status numbered", timeout=20)
        if code != 0:
            raise RuntimeError((err or out or "ufw status failed")[:800])
        return self._parse_status(out or "")

    @staticmethod
    def _only_existing_rule_notices(text: str) -> bool:
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        return bool(lines) and all(
            _EXISTING_RULE_NOTICE_RE.fullmatch(line) for line in lines
        )

    @classmethod
    def _standard_exact(
        cls,
        rules: list[FirewallRule],
        port: int,
        protocol: str,
        source: str = "",
    ) -> list[FirewallRule]:
        result = []
        for rule in rules:
            parsed = cls._direct_target(rule.port)
            if not parsed:
                continue
            start, end, rule_protocol = parsed
            if not (
                start == end == int(port)
                and rule_protocol == protocol
                and rule.action.lower() == "allow"
                and rule.direction.lower() == "in"
            ):
                continue
            if source:
                if rule.source.strip().lower() != source.lower():
                    continue
            elif rule.source.lower() not in {"anywhere", "anywhere (v6)"}:
                continue
            result.append(rule)
        return result

    @staticmethod
    def _numbered_rules_safe(rules: list[FirewallRule]) -> tuple[bool, Optional[str]]:
        if any(not str(rule.handle or "").isdigit() for rule in rules):
            return False, "missing_exact_rule_number"
        families = [UfwBackend._family(rule) for rule in rules]
        if len(families) != len(set(families)):
            return False, "duplicate_family_rule"
        return True, None

    @staticmethod
    def _family(rule: FirewallRule) -> str:
        return "v6" if "(v6)" in f"{rule.port} {rule.source}".lower() else "v4"

    @staticmethod
    def _direct_target(target: str) -> Optional[tuple[int, int, str]]:
        match = _DIRECT_TARGET_RE.fullmatch(str(target or "").strip())
        if not match:
            return None
        start = int(match.group(1))
        end = int(match.group(2) or start)
        return start, end, (match.group(3) or "any").lower()

    def _rule_covers(
        self,
        ssh,
        server: dict,
        rule: FirewallRule,
        port: int,
        protocol: str,
        source: str = "",
    ) -> Optional[bool]:
        parsed = self._direct_target(rule.port)
        if parsed:
            start, end, rule_protocol = parsed
            return (
                start <= port <= end
                and rule_protocol in {protocol, "any"}
                and source_keeps_access(rule.source, source)
            )

        profile = re.sub(r"\s+\(v6\)$", "", rule.port, flags=re.I).strip()
        if not _PROFILE_RE.fullmatch(profile):
            return None
        code, out, err = exec_sudo(
            ssh,
            server,
            f"ufw app info {shlex.quote(profile)}",
            timeout=15,
        )
        if code != 0:
            return None
        ports_text = " ".join(
            line.split(":", 1)[1].strip()
            for line in (out or "").splitlines()
            if line.strip().lower().startswith("ports:") and ":" in line
        )
        if not ports_text:
            return None
        for token in re.split(r"[ ,]+", ports_text):
            parsed_profile = self._direct_target(token)
            if not parsed_profile:
                continue
            start, end, rule_protocol = parsed_profile
            if start <= port <= end and rule_protocol in {protocol, "any"}:
                return True
        return False

    @staticmethod
    def _parse_status(text: str) -> list[FirewallRule]:
        rules: list[FirewallRule] = []
        numbered = re.compile(
            r"^\[\s*(\d+)\]\s+(.+?)\s{2,}(ALLOW|DENY|REJECT)(?:\s+(IN|OUT))?\s{2,}(.+)$",
            re.I,
        )
        plain = re.compile(
            r"^(.+?)\s{2,}(ALLOW|DENY|REJECT)(?:\s+(IN|OUT))?\s{2,}(.+)$",
            re.I,
        )
        for raw in text.splitlines():
            line = raw.strip()
            match = numbered.match(line)
            handle = match.group(1) if match else None
            if match:
                target, action, direction, source = (
                    match.group(2),
                    match.group(3),
                    match.group(4),
                    match.group(5),
                )
            else:
                fallback = plain.match(line)
                if not fallback:
                    continue
                target, action, direction, source = fallback.groups()
            parsed = UfwBackend._direct_target(target)
            rule_protocol = parsed[2] if parsed else "profile"
            rules.append(FirewallRule(
                port=target.strip(),
                protocol=rule_protocol,
                action=action.lower(),
                direction=(direction or "in").lower(),
                raw=line,
                handle=handle,
                source=source.strip(),
            ))
        return rules
