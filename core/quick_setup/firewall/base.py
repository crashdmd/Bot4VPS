# -*- coding: utf-8 -*-
"""Контракты поддерживаемых firewall backend-ов."""
from __future__ import annotations

import ipaddress
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


def normalize_source(value: Any) -> Optional[str]:
    """Канонизировать source: '' — без ограничения, IP/CIDR, None — невалидно."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        if "/" in text:
            return str(ipaddress.ip_network(text, strict=False))
        return str(ipaddress.ip_address(text))
    except ValueError:
        return None


def is_ip_source(value: Any) -> bool:
    """Источник является каноническим IP/CIDR (не служебным значением source)."""
    return bool(normalize_source(value))


def source_ip_version(value: Any) -> Optional[int]:
    """IP-версия канонического source (4/6) либо None."""
    normalized = normalize_source(value)
    if not normalized:
        return None
    try:
        return ipaddress.ip_network(normalized).version
    except ValueError:
        return None


def source_keeps_access(rule_source: Any, request_source: Any) -> bool:
    """Оставляет ли правило с rule_source доступ для request_source.

    '' в request_source — закрытие полного доступа: любое правило на том же
    порту оставляет частичный доступ. Служебные значения rule_source
    (anywhere, chain label, zone:) означают отсутствие ограничения.
    """
    request = str(request_source or "").strip()
    if not request:
        return True
    rule_net = normalize_source(rule_source)
    if not rule_net:
        return True
    request_net = normalize_source(request)
    if not request_net:
        return True
    try:
        rule_network = ipaddress.ip_network(rule_net)
        request_network = ipaddress.ip_network(request_net)
    except ValueError:
        return True
    if rule_network.version != request_network.version:
        return False
    return rule_network.supernet_of(request_network)


@dataclass
class FirewallRule:
    port: str
    protocol: str
    action: str = "allow"
    direction: str = "in"
    raw: str = ""
    handle: Optional[str] = None
    source: str = ""


@dataclass
class FirewallInfo:
    backend: Optional[str]
    active: Optional[bool]
    label: str
    rules: list[FirewallRule] = field(default_factory=list)
    error: Optional[str] = None
    backends: list[dict[str, Any]] = field(default_factory=list)
    manageable: bool = True
    reason: Optional[str] = None
    nftables_chains: list[dict[str, Any]] = field(default_factory=list)
    nftables_selected_chain: Optional[dict[str, str]] = None
    nftables_chain_selection_required: bool = False
    nftables_chains_truncated: bool = False


@dataclass
class FirewallStateChange:
    backend: str
    operation: str
    ok: bool
    changed: bool = False
    verified: bool = False
    message: str = ""
    error: Optional[str] = None
    state: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict:
        return {
            "backend": str(self.backend)[:32],
            "operation": str(self.operation)[:40],
            "ok": bool(self.ok),
            "changed": bool(self.changed),
            "verified": bool(self.verified),
            "message": str(self.message or "")[:1000],
            "error": str(self.error)[:2000] if self.error else None,
        }


@dataclass
class FirewallMutation:
    backend: Optional[str]
    port: int
    protocol: str
    operation: str
    ok: bool
    changed: bool = False
    existed_before: bool = False
    verified: bool = False
    message: str = ""
    error: Optional[str] = None
    token: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        value = asdict(self)
        value["message"] = str(value.get("message") or "")[:1000]
        if value.get("error") is not None:
            value["error"] = str(value["error"])[:2000]
        value["token"] = _bounded_token(value.get("token") or {})
        return value


def _bounded_token(value: Any, *, depth: int = 0) -> Any:
    if depth > 3:
        return "…"
    if isinstance(value, dict):
        return {
            str(key)[:80]: _bounded_token(item, depth=depth + 1)
            for key, item in list(value.items())[:20]
        }
    if isinstance(value, (list, tuple)):
        return [_bounded_token(item, depth=depth + 1) for item in list(value)[:20]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:500]


class FirewallBackend(ABC):
    name: str

    @abstractmethod
    def detect(self, ssh, server: dict) -> Optional[FirewallInfo]:
        """Вернуть info, если backend установлен, иначе None."""

    @abstractmethod
    def ensure_installed(self, ssh, server: dict) -> tuple[bool, str]:
        ...

    def deactivate(self, ssh, server: dict) -> FirewallStateChange:
        return FirewallStateChange(
            backend=self.name,
            operation="deactivate",
            ok=False,
            message="Firewall не отключён",
            error="deactivation_not_supported",
        )

    def activate(self, ssh, server: dict) -> FirewallStateChange:
        return FirewallStateChange(
            backend=self.name,
            operation="activate",
            ok=False,
            message="Firewall не включён",
            error="activation_not_supported",
        )

    def verify_inactive(self, ssh, server: dict) -> bool:
        info = self.detect(ssh, server)
        return info is not None and info.active is False

    def restore(
        self,
        ssh,
        server: dict,
        state: dict[str, Any],
    ) -> FirewallStateChange:
        return FirewallStateChange(
            backend=self.name,
            operation="restore",
            ok=False,
            message="Состояние firewall не восстановлено",
            error="restore_not_supported",
        )

    def migration_rules(
        self,
        ssh,
        server: dict,
    ) -> tuple[list[FirewallRule], list[str]]:
        """Разделить правила на переносимые exact allow и неоднозначные."""
        exact: list[FirewallRule] = []
        ambiguous: list[str] = []
        for rule in self.list_rules(ssh, server):
            if (
                str(rule.port).isdigit()
                and rule.protocol in {"tcp", "udp"}
                and rule.action.lower() == "allow"
                and rule.direction.lower() == "in"
            ):
                exact.append(rule)
            elif rule.raw:
                ambiguous.append(rule.raw)
        return exact, ambiguous

    @abstractmethod
    def open_port(self, ssh, server: dict, port: int, protocol: str) -> FirewallMutation:
        ...

    def preflight_close_port(
        self,
        ssh,
        server: dict,
        port: int,
        protocol: str,
    ) -> FirewallMutation:
        """Проверить возможность точного удаления без изменения firewall."""
        return FirewallMutation(
            self.name,
            port,
            protocol,
            "preflight_close",
            True,
            verified=True,
            message="Точное закрытие порта поддерживается",
        )

    @abstractmethod
    def close_port(self, ssh, server: dict, port: int, protocol: str) -> FirewallMutation:
        ...

    @abstractmethod
    def cleanup_mutation(
        self, ssh, server: dict, mutation: FirewallMutation
    ) -> FirewallMutation:
        """Откатить только точное изменение, записанное в token мутации."""

    @abstractmethod
    def list_rules(self, ssh, server: dict) -> list[FirewallRule]:
        ...
