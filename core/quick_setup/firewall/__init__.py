# -*- coding: utf-8 -*-
"""Проверяемый gateway для поддерживаемых firewall backend-ов.

Публичные функции открывают SSH-сессию сами. Варианты ``*_on_ssh`` нужны
составным транзакциям, чтобы вся операция использовала один проверенный
серверный контекст.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Optional

from core.ssh import create_ssh_client

from ..models import FirewallStatus, OpResult
from ..package_manager import detect as detect_package_manager
from .base import (
    FirewallBackend,
    FirewallInfo,
    FirewallMutation,
    FirewallRule,
    FirewallStateChange,
    is_ip_source,
    normalize_source,
)
from .firewalld import FirewalldBackend
from .nftables import NftablesBackend
from .ufw import UfwBackend

_BACKENDS: list[FirewallBackend] = [
    UfwBackend(),
    FirewalldBackend(),
    NftablesBackend(),
]
_BY_NAME = {backend.name: backend for backend in _BACKENDS}
_PROTOCOLS = {"tcp", "udp", "any"}
_CONTINUATION_VERSION = 2
_CONTINUATION_TTL_SECONDS = 15 * 60
_CONTINUATION_KEY = secrets.token_bytes(32)
_CONTINUATION_DECISIONS = {
    "continue_without_rule_migration",
    "skip_ambiguous_rules",
    "skip_failed_rules",
}


class FirewallDetectionError(RuntimeError):
    """Состояние firewall нельзя определить однозначно и безопасно."""


class FirewallMigrationError(RuntimeError):
    """Транзакция миграции не может быть безопасно продолжена."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "firewall_migration_failed",
        phase: str = "migration",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.phase = phase


class FirewallBatchMutation:
    """Совместимый с FirewallMutation результат операции по нескольким backend."""

    def __init__(
        self,
        *,
        operation: str,
        port: int,
        protocol: str,
        mutations: list[FirewallMutation],
        ok: bool,
        message: str,
        error: Optional[str] = None,
    ) -> None:
        self.backend = None
        self.port = port
        self.protocol = protocol
        self.operation = operation
        self.mutations = mutations[:20]
        self.ok = bool(ok)
        self.changed = any(item.changed for item in self.mutations)
        self.existed_before = bool(self.mutations) and all(
            item.existed_before for item in self.mutations
        )
        self.verified = self.ok and all(item.verified for item in self.mutations)
        self.message = str(message or "")[:1000]
        self.error = str(error)[:1200] if error else None
        self.token = {}

    def to_dict(self) -> dict:
        return {
            "backend": None,
            "backends": [item.backend for item in self.mutations[:20]],
            "port": self.port,
            "protocol": self.protocol,
            "operation": self.operation,
            "ok": self.ok,
            "changed": self.changed,
            "existed_before": self.existed_before,
            "verified": self.verified,
            "message": self.message,
            "error": self.error,
            "mutations": [item.to_dict() for item in self.mutations[:20]],
            "cleanup": list(getattr(self, "cleanup", []))[:20],
        }


def _port(value: int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Порт должен быть числом от 1 до 65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError("Порт должен быть числом от 1 до 65535")
    return port


def _protocol(value: str) -> str:
    protocol = str(value or "").strip().lower()
    if protocol not in _PROTOCOLS:
        raise ValueError("Поддерживаются только протоколы tcp, udp и any")
    return protocol


def _source(value) -> str:
    normalized = normalize_source(value)
    if normalized is None:
        raise ValueError("Source должен быть IP-адресом или CIDR (IPv4/IPv6)")
    return normalized


def _backend_name(value: str) -> str:
    name = str(value or "").strip().lower()
    if name not in _BY_NAME:
        raise ValueError(f"Поддерживаются: {', '.join(_BY_NAME)}")
    return name


def _scan_on_ssh(
    ssh, server: dict
) -> tuple[list[tuple[FirewallBackend, FirewallInfo]], list[str]]:
    detected: list[tuple[FirewallBackend, FirewallInfo]] = []
    errors: list[str] = []
    for backend in _BACKENDS:
        try:
            info = backend.detect(ssh, server)
            if info is not None:
                detected.append((backend, info))
        except Exception as exc:
            errors.append(f"{backend.name}: {str(exc)[:500]}")
    return detected, errors


def _logical_scan_on_ssh(
    ssh, server: dict
) -> tuple[list[tuple[FirewallBackend, FirewallInfo]], list[str]]:
    """Скрыть nftables, когда это реализация активного UFW/firewalld."""
    detected, errors = _scan_on_ssh(ssh, server)
    managed = any(
        backend.name in {"ufw", "firewalld"} and info.active is True
        for backend, info in detected
    )
    if not managed:
        return detected, errors

    logical: list[tuple[FirewallBackend, FirewallInfo]] = []
    for backend, info in detected:
        if backend.name != "nftables":
            logical.append((backend, info))
            continue
        logical.append((
            backend,
            FirewallInfo(
                backend=backend.name,
                active=False,
                label="nftables (доступен)",
                rules=[],
                nftables_chains=info.nftables_chains,
                nftables_selected_chain=info.nftables_selected_chain,
                nftables_chain_selection_required=(
                    info.nftables_chain_selection_required
                ),
                nftables_chains_truncated=info.nftables_chains_truncated,
            ),
        ))
    return logical, [error for error in errors if not error.startswith("nftables:")]


def active_backends_on_ssh(
    ssh,
    server: dict,
) -> tuple[list[tuple[FirewallBackend, FirewallInfo]], list[dict]]:
    """Вернуть свежий полный список active backend или поднять detection error."""
    detected, errors = _logical_scan_on_ssh(ssh, server)
    technical_errors = [
        info.reason or info.error or f"{backend.name}: состояние неоднозначно"
        for backend, info in detected
        if info.active is None or not info.manageable
    ]
    if errors or technical_errors:
        raise FirewallDetectionError("; ".join([*errors, *technical_errors])[:1200])
    return (
        [(backend, info) for backend, info in detected if info.active is True],
        _candidates(detected),
    )


def _nftables_chain_token_payload(value) -> Optional[dict[str, str]]:
    if not isinstance(value, dict):
        return None
    token = {
        key: value.get(key)
        for key in ("family", "table", "chain")
    }
    if not all(
        isinstance(item, str)
        and bool(item)
        and len(item) <= 128
        and "\x00" not in item
        for item in token.values()
    ):
        return None
    return token


def _nftables_chains_payload(values) -> list[dict]:
    if not isinstance(values, list):
        return []
    result: list[dict] = []
    for value in values[:20]:
        token = _nftables_chain_token_payload(value)
        if token is None:
            continue
        policy = value.get("policy")
        priority = value.get("priority")
        if isinstance(priority, bool) or not isinstance(priority, (int, str)):
            priority = None
        elif isinstance(priority, str):
            priority = priority[:32]
        rules_count = value.get("rules_count")
        if isinstance(rules_count, bool) or not isinstance(rules_count, int):
            rules_count = 0
        result.append({
            **token,
            "policy": str(policy)[:32] if policy is not None else None,
            "priority": priority,
            "rules_count": max(0, min(rules_count, 1_000_000)),
        })
    return result


def _candidate_payload(
    backend: FirewallBackend,
    info: FirewallInfo,
) -> dict:
    candidate = {
        "backend": str(backend.name)[:32],
        "installed": True,
        "active": info.active,
        "label": str(info.label or "")[:120],
        "manageable": bool(info.manageable),
        "reason": str(info.reason)[:1000] if info.reason else None,
    }
    if backend.name == "nftables":
        candidate["chain_selection"] = {
            "required": bool(info.nftables_chain_selection_required),
            "selected": _nftables_chain_token_payload(
                info.nftables_selected_chain
            ),
            "candidates": _nftables_chains_payload(info.nftables_chains),
            "truncated": bool(info.nftables_chains_truncated),
        }
    return candidate


def _candidates(
    detected: list[tuple[FirewallBackend, FirewallInfo]],
) -> list[dict]:
    return [
        _candidate_payload(backend, info)
        for backend, info in detected[:20]
    ]


def _candidates_payload(candidates: list[dict]) -> list[dict]:
    result: list[dict] = []
    for candidate in candidates[:20]:
        value = {
            "backend": str(candidate.get("backend") or "")[:32],
            "installed": bool(candidate.get("installed", True)),
            "active": candidate.get("active"),
            "label": str(candidate.get("label") or "")[:120],
            "manageable": bool(candidate.get("manageable", True)),
            "reason": (
                str(candidate.get("reason"))[:1000]
                if candidate.get("reason")
                else None
            ),
        }
        if value["backend"] == "nftables":
            selection = candidate.get("chain_selection")
            if not isinstance(selection, dict):
                selection = {}
            value["chain_selection"] = {
                "required": bool(selection.get("required")),
                "selected": _nftables_chain_token_payload(
                    selection.get("selected")
                ),
                "candidates": _nftables_chains_payload(
                    selection.get("candidates")
                ),
                "truncated": bool(selection.get("truncated")),
            }
        result.append(value)
    return result


def _nftables_chain_selection_result(
    ssh,
    server: dict,
    name: str,
    reason: str,
    *,
    action: str = "установку",
) -> Optional[OpResult]:
    """Структурированный ответ, когда операция nftables ждёт выбора chain.

    Если nftables установлен, но выбор input chain не сохранён (или
    сохранённая chain исчезла), initial scan неизбежно вернёт detection
    error. Это не сбой операции: вернуть список chains для выбора в UI,
    а не generic-ошибка вида «Установка firewall остановлена».
    """
    if str(name or "").strip().lower() != "nftables":
        return None
    try:
        info = _BY_NAME["nftables"].detect(ssh, server)
    except Exception:
        return None
    if info is None or not info.nftables_chain_selection_required:
        return None
    return OpResult(
        ok=False,
        message=(
            "Для nftables требуется выбрать существующую input chain; "
            f"после выбора повторите {action}"
        ),
        error="nftables_chain_selection_required",
        data={
            "target": "nftables",
            "phase": "chain_selection",
            "changed": False,
            "backends": [_candidate_payload(_BY_NAME["nftables"], info)],
        },
        details={"reason": str(reason)[:1200]},
    )


def _nftables_provision_pending(ssh, server: dict) -> bool:
    """Будет ли ensure_installed nftables создавать базовую таблицу bot4vps.

    Предусловие автопровижининга: сохранённой цепочки нет и в ruleset нет
    ни одной standalone input chain (state «none») — типично для свежей
    Ubuntu, где ufw работает через iptables-nft. Результат нужен ДО вызова
    ensure_installed, чтобы rollback неудачной миграции знал, что таблица —
    собственность панели и удаляется целиком.
    """
    backend = _BY_NAME["nftables"]
    configured, _ = backend._configured_chain_token(server)
    if configured:
        return False
    try:
        state, _, _ = backend._selection_state(backend._ruleset(ssh, server))
    except Exception:
        return False
    return state == "none"


def _finalize_nftables_persistence(
    ssh,
    server: dict,
) -> Optional[tuple[bool, str]]:
    """Терминальная синхронизация persistence nftables после успеха install/switch.

    Для админских цепочек возвращает None (persistence — ответственность
    админа); для собственной таблицы bot4vps дампит правила и включает
    nftables.service (см. NftablesBackend._persist_owned_ruleset).
    """
    backend = _BY_NAME["nftables"]
    configured, token = backend._configured_chain_token(server)
    if not configured or not backend._owned_chain_token(token):
        return None
    try:
        return backend._persist_owned_ruleset(ssh, server, sync_service=True)
    except Exception as exc:
        return False, str(exc)[:400]


def _summarize_without_active(
    detected: list[tuple[FirewallBackend, FirewallInfo]],
    candidates: list[dict],
) -> FirewallInfo:
    return FirewallInfo(
        backend=None,
        active=False,
        label="Firewall не активен" if detected else "Firewall не обнаружен",
        rules=[],
        backends=candidates,
    )


def detect_on_ssh(ssh, server: dict) -> FirewallInfo:
    """Определить active backend и полный inventory без сокрытия конфликта."""
    detected, errors = _logical_scan_on_ssh(ssh, server)
    candidates = _candidates(detected)
    active = [(backend, info) for backend, info in detected if info.active is True]

    if len(active) > 1:
        names = ", ".join(info.backend or backend.name for backend, info in active)
        return FirewallInfo(
            backend=None,
            active=None,
            label="Обнаружено несколько активных firewall",
            rules=[],
            error=f"ambiguous_active_firewalls: {names}"[:1200],
            backends=candidates,
        )
    uncertain = [
        (backend, info)
        for backend, info in detected
        if info.active is None
    ]
    if uncertain:
        reasons = "; ".join(
            info.reason or info.error or f"{backend.name}: состояние неоднозначно"
            for backend, info in uncertain
        )
        return FirewallInfo(
            backend=None,
            active=None,
            label="Состояние firewall не определено",
            rules=[],
            error=reasons[:1200],
            backends=candidates,
            manageable=False,
            reason=reasons[:1200],
        )
    if errors:
        return FirewallInfo(
            backend=None,
            active=None,
            label="Состояние firewall не определено",
            rules=[],
            error="; ".join(errors)[:1200],
            backends=candidates,
        )
    if active:
        info = active[0][1]
        info.backends = candidates
        return info
    return _summarize_without_active(detected, candidates)


def detect(server: dict) -> FirewallInfo:
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=12)
        return detect_on_ssh(ssh, server)
    except Exception as exc:
        return FirewallInfo(
            backend=None,
            active=None,
            label="Состояние firewall не определено",
            rules=[],
            error=str(exc)[:1200],
        )
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def validate_nftables_input_chain(
    server: dict,
    token: dict,
) -> dict[str, str]:
    """Fresh-read exact existing chain and return its normalized token."""
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=12)
        backend = _BY_NAME["nftables"]
        if not isinstance(backend, NftablesBackend):
            raise RuntimeError("nftables backend недоступен")
        return backend.validate_input_chain(ssh, server, token)
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def to_status(info: FirewallInfo) -> FirewallStatus:
    return FirewallStatus(
        backend=info.backend,
        active=info.active,
        label=info.label,
        error=info.error,
        backends=_candidates_payload(info.backends or []),
    )


def _active_backend_on_ssh(
    ssh,
    server: dict,
) -> tuple[Optional[FirewallBackend], FirewallInfo]:
    detected, errors = _logical_scan_on_ssh(ssh, server)
    candidates = _candidates(detected)
    if errors:
        raise FirewallDetectionError("; ".join(errors)[:1200])
    uncertain = [
        (backend, info)
        for backend, info in detected
        if info.active is None or not info.manageable
    ]
    if uncertain:
        raise FirewallDetectionError("; ".join(
            info.reason or info.error or f"{backend.name}: состояние неоднозначно"
            for backend, info in uncertain
        )[:1200])
    active = [(backend, info) for backend, info in detected if info.active is True]
    if len(active) > 1:
        names = ", ".join(info.backend or backend.name for backend, info in active)
        raise FirewallDetectionError(f"ambiguous_active_firewalls: {names}")
    if active:
        backend, info = active[0]
        info.backends = candidates
        return backend, info
    return None, _summarize_without_active(detected, candidates)


def _verify_real_ssh(server: dict) -> tuple[bool, Optional[str]]:
    probe = None
    try:
        probe = create_ssh_client(server, timeout=15)
        return True, None
    except Exception as exc:
        return False, str(exc)[:500]
    finally:
        if probe:
            try:
                probe.close()
            except Exception:
                pass


def _rule_key(rule: FirewallRule) -> tuple[int, str, str]:
    """Ключ идентичности правила миграции: (port, protocol, source).

    Source — канонический IPv4-адрес/CIDR или пустая строка (без источника).
    Служебные значения source (метки цепочек/зон) считаются отсутствием
    источника. Невалидные значения поднимают ValueError.
    """
    port = _port(rule.port)
    protocol = _protocol(rule.protocol)
    raw_source = str(rule.source or "").strip()
    if not raw_source or not is_ip_source(raw_source):
        source = ""
    else:
        source = normalize_source(raw_source)
        if not source:
            raise ValueError("Некорректный source правила")
    return port, protocol, source


def _switch_rule_inventory(
    ssh,
    server: dict,
    backend: FirewallBackend,
    *,
    role: str,
) -> tuple[set[tuple[int, str, str]], list[str]]:
    """Прочитать exact rules одного switch backend без догадок о policy."""
    try:
        rules, unclear = backend.migration_rules(ssh, server)
        exact: set[tuple[int, str, str]] = set()
        ambiguous: list[str] = []
        for rule in rules:
            try:
                exact.add(_rule_key(rule))
            except ValueError:
                ambiguous.append(
                    str(rule.raw or f"{rule.port}/{rule.protocol}")[:500]
                )
        ambiguous.extend(
            str(value or "").strip()[:500]
            for value in unclear
            if str(value or "").strip()
        )
    except Exception as exc:
        raise FirewallMigrationError(
            f"Не удалось безопасно прочитать правила {role} firewall",
            code=f"firewall_switch_{role}_inventory_failed",
            phase=f"{role}_inventory",
        ) from exc
    return exact, sorted(set(ambiguous))[:200]


def _switch_exact_verification(
    ssh,
    server: dict,
    backend: FirewallBackend,
    expected: set[tuple[int, str, str]],
) -> tuple[bool, list[dict], list[dict]]:
    actual, _ = _switch_rule_inventory(
        ssh,
        server,
        backend,
        role="target",
    )
    missing = expected - actual
    unexpected = actual - expected
    return (
        not missing and not unexpected,
        _expected_rule_payload(missing),
        _expected_rule_payload(unexpected),
    )


def _switch_rollback(
    ssh,
    server: dict,
    *,
    source_backend: FirewallBackend,
    source_exact: set[tuple[int, str, str]],
    source_ambiguous: list[str],
    source_deactivation_started: bool,
    source_change: Optional[FirewallStateChange],
    target_backend: FirewallBackend,
    target_attempted: bool,
    target_provisioned: bool = False,
    target_snapshot: Optional[set[tuple[int, str, str]]],
    target_mutations: list[FirewallMutation],
    removed_attempts: list[tuple[int, str, str]],
    ssh_port: int,
) -> dict:
    """Вернуть switch target к snapshot, не сокращая доступ до safe source."""
    lifecycle: list[dict] = []
    lifecycle_ok = not source_deactivation_started
    if source_deactivation_started:
        if source_change is None:
            lifecycle.append({
                "backend": source_backend.name,
                "operation": "restore",
                "ok": False,
                "changed": False,
                "verified": False,
                "message": "Состояние source firewall не удалось восстановить",
                "error": "missing_source_state",
            })
            lifecycle_ok = False
        else:
            try:
                restored = source_backend.restore(
                    ssh,
                    server,
                    source_change.state,
                )
                lifecycle.append(restored.to_dict())
                lifecycle_ok = bool(restored.ok and restored.verified)
            except Exception as exc:
                lifecycle.append({
                    "backend": source_backend.name,
                    "operation": "restore",
                    "ok": False,
                    "changed": False,
                    "verified": False,
                    "message": "Состояние source firewall не восстановлено",
                    "error": str(exc)[:800],
                })
                lifecycle_ok = False

    source_active = False
    source_state_error = None
    try:
        source_info = source_backend.detect(ssh, server)
        source_active = bool(
            source_info is not None
            and source_info.active is True
            and source_info.manageable
        )
    except Exception as exc:
        source_state_error = str(exc)[:800]

    source_rules_verified = False
    source_rules_error = None
    try:
        rollback_exact, rollback_ambiguous = _switch_rule_inventory(
            ssh,
            server,
            source_backend,
            role="source",
        )
        source_rules_verified = (
            rollback_exact == source_exact
            and rollback_ambiguous == source_ambiguous
        )
    except Exception as exc:
        source_rules_error = str(exc)[:800]

    source_ssh_ok, source_ssh_error = _verify_real_ssh(server)
    safe_to_reduce_target = bool(
        lifecycle_ok
        and source_active
        and source_rules_verified
        and source_ssh_ok
    )

    restored_rules: list[dict] = []
    for port, protocol, source in reversed(removed_attempts):
        try:
            restored_rule = target_backend.open_port(
                ssh,
                server,
                port,
                protocol,
                source,
            )
            restored_rules.append({
                "port": port,
                "protocol": protocol,
                "source": source,
                "restored": bool(restored_rule.ok and restored_rule.verified),
                "mutation": restored_rule.to_dict(),
            })
        except Exception as exc:
            restored_rules.append({
                "port": port,
                "protocol": protocol,
                "source": source,
                "restored": False,
                "error": str(exc)[:800],
            })

    rollback_target_exact = (
        target_snapshot | {(ssh_port, "tcp", "")}
        if target_snapshot is not None
        else None
    )
    target_unprovisioned = False
    cleanup: list[dict] = []
    if target_provisioned and safe_to_reduce_target:
        # Таблица bot4vps провижинена панелью в ЭТОЙ операции — собственность
        # панели: удаляем целиком (ruleset + conf + include + сервис + выбор
        # цепочки). Per-rule cleanup не нужен: правил без таблицы не бывает.
        try:
            ok, detail = target_backend.rollback_provisioned_ruleset(
                ssh, server
            )
        except Exception as exc:
            ok, detail = False, str(exc)[:800]
        if ok:
            target_unprovisioned = True
            target_state = {
                "backend": target_backend.name,
                "operation": "unprovision",
                "ok": True,
                "changed": True,
                "verified": True,
                "message": "Базовая nftables таблица bot4vps удалена",
                "error": None,
            }
            target_inactive = True
            cleanup = [
                {
                    "attempted": False,
                    "restored": True,
                    "retained": False,
                    "reason": "Таблица bot4vps удалена целиком с persistence",
                    "mutation": item.to_dict(),
                }
                for item in reversed(target_mutations)
            ]
    if not target_unprovisioned:
        for mutation in reversed(target_mutations):
            if not mutation.changed or mutation.existed_before:
                cleanup.append({
                    "attempted": False,
                    "restored": True,
                    "retained": False,
                    "reason": "Правило существовало ранее или не добавлялось операцией",
                    "mutation": mutation.to_dict(),
                })
                continue
            if mutation.port == ssh_port and mutation.protocol == "tcp":
                cleanup.append({
                    "attempted": False,
                    "restored": bool(
                        rollback_target_exact is not None
                        and (ssh_port, "tcp", "") in rollback_target_exact
                    ),
                    "retained": True,
                    "reason": (
                        "Правило текущего SSH-порта сохранено до деактивации target"
                    ),
                    "mutation": mutation.to_dict(),
                })
                continue
            if not safe_to_reduce_target:
                cleanup.append({
                    "attempted": False,
                    "restored": False,
                    "retained": True,
                    "reason": (
                        "Новое правило сохранено: безопасный source не подтверждён"
                    ),
                    "mutation": mutation.to_dict(),
                })
                continue
            try:
                cleaned = target_backend.cleanup_mutation(ssh, server, mutation)
                cleanup.append({
                    "attempted": True,
                    "restored": bool(cleaned.ok and cleaned.verified),
                    "retained": not bool(cleaned.ok and cleaned.verified),
                    "mutation": cleaned.to_dict(),
                })
            except Exception as exc:
                cleanup.append({
                    "attempted": True,
                    "restored": False,
                    "retained": True,
                    "error": str(exc)[:800],
                    "mutation": mutation.to_dict(),
                })

    target_snapshot_verified = False
    target_snapshot_missing: list[dict] = []
    target_snapshot_unexpected: list[dict] = []
    target_snapshot_error = None
    if target_unprovisioned:
        # Таблица удалена целиком — сверять её правила с baseline не с чем.
        target_snapshot_verified = True
    elif rollback_target_exact is not None:
        try:
            (
                target_snapshot_verified,
                target_snapshot_missing,
                target_snapshot_unexpected,
            ) = _switch_exact_verification(
                ssh,
                server,
                target_backend,
                rollback_target_exact,
            )
        except Exception as exc:
            target_snapshot_error = str(exc)[:800]

    if not target_unprovisioned:
        target_state = None
        target_inactive = False
        target_state_error = None
        try:
            target_info = target_backend.detect(ssh, server)
            if target_info is not None and target_info.active is False:
                target_inactive = True
            elif (
                target_info is not None
                and target_info.active is True
                and safe_to_reduce_target
            ):
                target_change = target_backend.deactivate(ssh, server)
                target_state = target_change.to_dict()
                target_inactive = bool(target_change.ok and target_change.verified)
            elif target_info is None:
                target_state_error = "target firewall больше не обнаружен"
            else:
                target_state_error = (
                    "Target оставлен активным: безопасный source не подтверждён"
                )
        except Exception as exc:
            target_state_error = str(exc)[:800]

    final_inventory: list[dict] = []
    final_state_restored = False
    final_scan_error = None
    try:
        final_detected = _verified_logical_scan_on_ssh(ssh, server)
        final_inventory = _candidates_payload(_candidates(final_detected))
        final_active = [
            backend.name
            for backend, info in final_detected
            if info.active is True
        ]
        final_state_restored = final_active == [source_backend.name]
    except Exception as exc:
        final_scan_error = str(exc)[:1200]

    final_ssh_ok, final_ssh_error = _verify_real_ssh(server)
    removed_restored = all(
        item.get("restored") is True for item in restored_rules
    )
    additions_restored = all(
        item.get("restored") is True for item in cleanup
    )
    rollback_verified = bool(
        lifecycle_ok
        and source_active
        and source_rules_verified
        and source_ssh_ok
        and removed_restored
        and additions_restored
        and target_snapshot_verified
        and (not target_attempted or target_inactive)
        and final_state_restored
        and final_ssh_ok
    )
    return {
        "verified": rollback_verified,
        "lifecycle": lifecycle,
        "lifecycle_restored": lifecycle_ok,
        "source_active": source_active,
        "source_state_error": source_state_error,
        "source_rules_verified": source_rules_verified,
        "source_rules_error": source_rules_error,
        "ssh_verified": source_ssh_ok,
        "ssh_error": source_ssh_error,
        "removed_rules": restored_rules[:200],
        "removed_rules_restored": removed_restored,
        "added_rules": cleanup[:200],
        "added_rules_restored": additions_restored,
        "target_snapshot_verified": target_snapshot_verified,
        "target_snapshot_missing": target_snapshot_missing,
        "target_snapshot_unexpected": target_snapshot_unexpected,
        "target_snapshot_error": target_snapshot_error,
        "target": target_state,
        "target_inactive": target_inactive,
        "target_unprovisioned": target_unprovisioned,
        "target_state_error": target_state_error,
        "final_state_restored": final_state_restored,
        "final_ssh_verified": final_ssh_ok,
        "final_ssh_error": final_ssh_error,
        "final_inventory": final_inventory,
        "final_scan_error": final_scan_error,
        "packages_removed": False,
    }


def switch_backend(
    server: dict,
    target: str,
    *,
    confirm: bool,
    continuation: Optional[dict] = None,
    selected_rules: Optional[list] = None,
) -> OpResult:
    """Переключить installed inactive target с exact reconciliation правил."""
    if not confirm:
        return OpResult(
            ok=False,
            message="Подтвердите смену firewall",
            error="firewall_switch_confirmation_required",
        )

    ssh = None
    target_backend: Optional[FirewallBackend] = None
    source_backend: Optional[FirewallBackend] = None
    source_name: Optional[str] = None
    source_token: Optional[dict[str, str]] = None
    source_change: Optional[FirewallStateChange] = None
    source_deactivation_started = False
    source_exact: set[tuple[int, str, str]] = set()
    source_ambiguous: list[str] = []
    target_snapshot: Optional[set[tuple[int, str, str]]] = None
    target_mutations: list[FirewallMutation] = []
    removed_attempts: list[tuple[int, str, str]] = []
    target_attempted = False
    target_provisioned = False
    reconcile = False
    phase = "detection"
    failure_details: dict[str, Any] = {}
    ssh_verified = False
    ssh_port = 22
    try:
        target = _backend_name(target)
        ssh_port = _port(server.get("port") or 22)
    except ValueError as exc:
        return OpResult(
            ok=False,
            message="Некорректные параметры переключения firewall",
            error=str(exc)[:500],
            data={
                "source": source_name,
                "target": str(target or "")[:32],
                "switched": False,
                "changed": False,
                "ssh_verified": False,
            },
        )
    try:
        accepted = _validated_continuation(
            continuation,
            server=server,
            target=target,
        )
    except ValueError as exc:
        return _continuation_error(str(exc), target)
    accepted_by_name = {item["decision"]: item for item in accepted}
    if selected_rules is not None and "skip_ambiguous_rules" not in accepted_by_name:
        return _selection_error(
            "Выбор правил требует валидного продолжения транзакции",
            target,
        )
    normalized_selection = (
        _normalized_selected_rules(selected_rules)
        if selected_rules is not None
        else []
    )
    if selected_rules is not None and normalized_selection is None:
        return _selection_error(
            "Некорректная форма списка выбранных правил",
            target,
        )
    selected_keys: Optional[set[tuple[int, str, str]]] = (
        {(item["port"], item["protocol"], item["source"]) for item in normalized_selection}
        if selected_rules is not None
        else None
    )
    if selected_keys is not None:
        # SSH-порт переносится принудительно и не участвует в выборе.
        selected_keys.discard((ssh_port, "tcp", ""))
    try:
        target_backend = _BY_NAME[target]
        ssh = create_ssh_client(server, timeout=20)

        detected, errors = _logical_scan_on_ssh(ssh, server)
        if errors:
            raise FirewallDetectionError(
                "Не удалось однозначно определить текущий firewall"
            )
        uncertain = [
            (backend, info)
            for backend, info in detected
            if info.active is None
        ]
        if uncertain:
            raise FirewallDetectionError("; ".join(
                info.reason
                or info.error
                or f"{backend.name}: состояние неоднозначно"
                for backend, info in uncertain
            )[:1200])
        active = [
            (backend, info)
            for backend, info in detected
            if info.active is True
        ]
        if len(active) > 1:
            names = ", ".join(backend.name for backend, _ in active)
            raise FirewallDetectionError(
                f"Обнаружено несколько активных firewall: {names}"
            )
        if active:
            source_backend, source_info = active[0]
            source_name = source_backend.name
            if source_name == target and source_info.manageable:
                if accepted:
                    return _continuation_error(
                        "Target уже стал активным, поэтому продолжение устарело",
                        target,
                    )
                ssh_verified, ssh_error = _verify_real_ssh(server)
                if not ssh_verified:
                    raise FirewallMigrationError(
                        "SSH для активного firewall не подтверждён: "
                        f"{ssh_error or 'unknown'}"
                    )
                return OpResult(
                    ok=True,
                    message=f"{target} уже является единственным активным firewall",
                    data={
                        "source": source_name,
                        "target": target,
                        "switched": False,
                        "changed": False,
                        "ssh_verified": True,
                    },
                )
        else:
            source_info = None

        unmanaged = [
            (backend, info)
            for backend, info in detected
            if not info.manageable
            and not (
                source_backend is not None
                and backend.name == source_backend.name == "nftables"
            )
        ]
        if unmanaged:
            raise FirewallDetectionError("; ".join(
                info.reason
                or info.error
                or f"{backend.name}: состояние неоднозначно"
                for backend, info in unmanaged
            )[:1200])

        initial_target_info = next(
            (
                info
                for backend, info in detected
                if backend.name == target
            ),
            None,
        )
        # Reconcile определяется наличием активного source, а не
        # установленностью target: инвентарь правил берётся из source и не
        # зависит от того, установлен ли target (live-регрессия №12:
        # ufw→firewalld при неустановленном firewalld переносил только
        # SSH-порт и молча терял остальные правила, включая порт панели —
        # decision-prompt о переносимых правилах тоже не показывался).
        # Установленный target к этому моменту может быть только
        # inactive+manageable: активный target отсечён проверкой выше,
        # unmanageable — проверкой unmanaged.
        reconcile = bool(
            source_backend is not None
            and source_name != target
            and (
                initial_target_info is None
                or (
                    initial_target_info.active is False
                    and initial_target_info.manageable
                )
            )
        )
        if accepted and not reconcile:
            return _continuation_error(
                "Состояние firewall изменилось, продолжение устарело",
                target,
            )
        desired: set[tuple[int, str, str]] = set()
        if reconcile:
            phase = "source_inventory"
            source_exact, source_ambiguous = _switch_rule_inventory(
                ssh,
                server,
                source_backend,
                role="source",
            )
            source_display = [
                (
                    FirewallRule(port=str(port), protocol=protocol, source=source),
                    [source_name],
                )
                for port, protocol, source in sorted(source_exact)
                if (port, protocol, source) != (ssh_port, "tcp", "")
            ]
            source_unclear = [
                {"backend": source_name, "rule": rule}
                for rule in source_ambiguous
            ]
            inventory_fingerprint = _rule_inventory_fingerprint(
                target,
                [source_name],
                source_display,
                source_unclear,
            )
            skip_decision = accepted_by_name.get("skip_ambiguous_rules")
            if skip_decision is not None:
                if skip_decision["fingerprint"] != inventory_fingerprint:
                    return _continuation_error(
                        "Правила source firewall изменились после решения пользователя",
                        target,
                    )
                if selected_keys is not None and not selected_keys <= source_exact:
                    return _selection_error(
                        "Выбраны правила, отсутствующие в правилах source firewall",
                        target,
                    )
            elif source_ambiguous or source_display:
                if source_ambiguous:
                    message = (
                        "Некоторые правила невозможно безопасно перенести. "
                        "Отметьте правила для переноса. Неоднозначные правила "
                        "перенесены не будут; SSH-порт останется открытым. "
                        "Отмена — сохранит текущий firewall без изменений."
                    )
                else:
                    message = (
                        "Отметьте правила для переноса на новый firewall. "
                        "SSH-порт останется открытым. "
                        "Отмена — сохранит текущий firewall без изменений."
                    )
                return OpResult(
                    ok=False,
                    message=message,
                    error="ambiguous_firewall_rules",
                    data={
                        "source": source_name,
                        "target": target,
                        "phase": "source_inventory",
                        "decision_required": "skip_ambiguous_rules",
                        "actions": ["continue", "cancel"],
                        "continue_with": _issue_continuation(
                            server,
                            target,
                            [{
                                "decision": "skip_ambiguous_rules",
                                "fingerprint": inventory_fingerprint,
                            }],
                        ),
                        "ambiguous_rules": source_unclear[:200],
                        "migratable_rules": _public_migratable_rules(
                            source_display
                        ),
                        "changed": False,
                    },
                )
            if selected_keys is not None:
                desired = selected_keys | {(ssh_port, "tcp", "")}
            else:
                desired = source_exact | {(ssh_port, "tcp", "")}

        if source_name == "nftables":
            phase = "source_resolution"
            source_token = _BY_NAME["nftables"].resolve_switch_source(
                ssh,
                server,
            )

        phase = "target_preparation"
        target_attempted = True
        # Автопровижининг базовой таблицы bot4vps (см. migrate): rollback
        # должен знать о ней до вызова ensure_installed.
        target_provisioned = (
            target == "nftables"
            and _nftables_provision_pending(ssh, server)
        )
        try:
            prepared, detail = target_backend.ensure_installed(ssh, server)
        except Exception as exc:
            raise FirewallMigrationError(
                f"Не удалось безопасно подготовить {target}"
            ) from exc
        if not prepared:
            raise FirewallMigrationError(detail)

        if reconcile:
            ssh_rule = target_backend.open_port(
                ssh,
                server,
                ssh_port,
                "tcp",
                "",
            )
            target_mutations.append(ssh_rule)
            if not ssh_rule.ok or not ssh_rule.verified:
                raise FirewallMigrationError(
                    ssh_rule.error
                    or ssh_rule.message
                    or "Allow текущего SSH-порта в target не подтверждён",
                    code="firewall_switch_target_ssh_failed",
                    phase="target_preparation",
                )

        if target == "nftables":
            if not _BY_NAME["nftables"].verify_switch_target(
                ssh,
                server,
                ssh_port,
            ):
                raise FirewallMigrationError(
                    "Активное состояние nftables target и allow SSH не подтверждены"
                )
        else:
            if not reconcile:
                ssh_rule = target_backend.open_port(
                    ssh,
                    server,
                    ssh_port,
                    "tcp",
                    "",
                )
                if not ssh_rule.ok or not ssh_rule.verified:
                    raise FirewallMigrationError(
                        ssh_rule.error
                        or ssh_rule.message
                        or "Allow текущего SSH-порта в target не подтверждён"
                    )
            target_info = target_backend.detect(ssh, server)
            if (
                target_info is None
                or target_info.active is not True
                or not target_info.manageable
            ):
                raise FirewallMigrationError(
                    "Активное состояние target firewall не подтверждено"
                )

        if reconcile:
            phase = "target_inventory"
            # Неактивные UFW/firewalld не отдают тот же exact inventory.
            # Rollback baseline снимается после подготовки; обязательный SSH
            # можно сохранить при возврате target в неактивное состояние.
            target_snapshot, _ = _switch_rule_inventory(
                ssh,
                server,
                target_backend,
                role="target",
            )
            to_add = desired - target_snapshot
            to_remove = target_snapshot - desired
            to_remove.discard((ssh_port, "tcp", ""))

            phase = "target_reconciliation"
            for port, protocol, source in sorted(to_add):
                mutation = target_backend.open_port(
                    ssh,
                    server,
                    port,
                    protocol,
                    source,
                )
                target_mutations.append(mutation)
                if not mutation.ok or not mutation.verified:
                    failure_details["failed_rule"] = {
                        "port": port,
                        "protocol": protocol,
                        "source": source,
                        "operation": "open",
                    }
                    raise FirewallMigrationError(
                        mutation.error
                        or mutation.message
                        or f"Не удалось добавить {port}/{protocol} в target",
                        code="firewall_switch_rule_add_failed",
                        phase="target_reconciliation",
                    )

            preflights: list[FirewallMutation] = []
            for port, protocol, source in sorted(to_remove):
                try:
                    preflight = target_backend.preflight_close_port(
                        ssh,
                        server,
                        port,
                        protocol,
                        source,
                    )
                except Exception as exc:
                    failure_details["failed_rule"] = {
                        "port": port,
                        "protocol": protocol,
                        "source": source,
                        "operation": "preflight_close",
                    }
                    raise FirewallMigrationError(
                        f"Не удалось проверить удаление stale правила {port}/{protocol}",
                        code="firewall_switch_rule_remove_preflight_failed",
                        phase="target_reconciliation",
                    ) from exc
                preflights.append(preflight)
                if not preflight.ok or not preflight.verified:
                    failure_details["failed_rule"] = {
                        "port": port,
                        "protocol": protocol,
                        "source": source,
                        "operation": "preflight_close",
                        "error": str(preflight.error or "")[:800],
                    }
                    raise FirewallMigrationError(
                        preflight.error
                        or preflight.message
                        or f"Stale правило {port}/{protocol} нельзя удалить безопасно",
                        code="firewall_switch_rule_remove_preflight_failed",
                        phase="target_reconciliation",
                    )

            for (port, protocol, source), preflight in zip(sorted(to_remove), preflights):
                removed_attempts.append((port, protocol, source))
                try:
                    removal = target_backend.close_port(
                        ssh,
                        server,
                        port,
                        protocol,
                        source,
                    )
                except Exception as exc:
                    failure_details["failed_rule"] = {
                        "port": port,
                        "protocol": protocol,
                        "source": source,
                        "operation": "close",
                    }
                    raise FirewallMigrationError(
                        "Не удалось удалить stale правило "
                        f"{port}/{protocol}",
                        code="firewall_switch_rule_remove_failed",
                        phase="target_reconciliation",
                    ) from exc
                if not removal.ok or not removal.verified:
                    failure_details["failed_rule"] = {
                        "port": port,
                        "protocol": protocol,
                        "source": source,
                        "operation": "close",
                        "error": str(removal.error or "")[:800],
                    }
                    raise FirewallMigrationError(
                        removal.error
                        or removal.message
                        or (
                            "Удаление stale правила "
                            f"{port}/{protocol} не подтверждено"
                        ),
                        code="firewall_switch_rule_remove_failed",
                        phase="target_reconciliation",
                    )

            phase = "target_verification"
            exact, missing, unexpected = _switch_exact_verification(
                ssh,
                server,
                target_backend,
                desired,
            )
            if not exact:
                failure_details.update({
                    "missing_rules": missing,
                    "unexpected_rules": unexpected,
                })
                raise FirewallMigrationError(
                    "Exact rules target не совпали с актуальными правилами source",
                    code="firewall_switch_target_rules_mismatch",
                    phase="target_verification",
                )

        phase = "ssh_verification"
        ssh_verified, ssh_error = _verify_real_ssh(server)
        if not ssh_verified:
            raise FirewallMigrationError(
                "SSH после подготовки target не подтверждён: "
                f"{ssh_error or 'unknown'}"
            )

        if reconcile and source_backend is not None and source_name is not None:
            phase = "source_confirmation"
            _migration_state_before_source_disable(
                ssh,
                server,
                target=target,
                sources=[source_name],
            )
            confirmed_exact, confirmed_ambiguous = _switch_rule_inventory(
                ssh,
                server,
                source_backend,
                role="source",
            )
            if (
                confirmed_exact != source_exact
                or confirmed_ambiguous != source_ambiguous
            ):
                failure_details.update({
                    "source_rules_before": _expected_rule_payload(source_exact),
                    "source_rules_after": _expected_rule_payload(confirmed_exact),
                    "source_ambiguous_after": confirmed_ambiguous[:200],
                })
                raise FirewallMigrationError(
                    "Правила active source изменились во время подготовки target",
                    code="firewall_switch_source_rules_changed",
                    phase="source_confirmation",
                )

        if source_backend is not None:
            phase = "source_deactivation"
            source_deactivation_started = True
            if source_name == "nftables":
                source_change = _BY_NAME["nftables"].deactivate_exact(
                    ssh,
                    server,
                    source_token or {},
                )
            else:
                source_change = source_backend.deactivate(ssh, server)
            if not source_change.ok or not source_change.verified:
                raise FirewallMigrationError(
                    source_change.error
                    or source_change.message
                    or f"Не удалось отключить {source_name}"
                )

        phase = "final_verification"
        ssh_verified, ssh_error = _verify_real_ssh(server)
        if not ssh_verified:
            raise FirewallMigrationError(
                "SSH после отключения исходного firewall не подтверждён: "
                f"{ssh_error or 'unknown'}"
            )

        final_detected, final_errors = _logical_scan_on_ssh(ssh, server)
        final_uncertain = [
            info.reason
            or info.error
            or f"{backend.name}: состояние неоднозначно"
            for backend, info in final_detected
            if info.active is None or not info.manageable
        ]
        if final_errors or final_uncertain:
            raise FirewallDetectionError(
                "Не удалось подтвердить итоговое состояние firewall"
            )
        final_active = [
            backend.name
            for backend, info in final_detected
            if info.active is True
        ]
        if final_active != [target]:
            raise FirewallMigrationError(
                "После переключения не подтверждён единственный active target firewall"
            )
        if reconcile:
            exact, missing, unexpected = _switch_exact_verification(
                ssh,
                server,
                target_backend,
                desired,
            )
            if not exact:
                failure_details.update({
                    "missing_rules": missing,
                    "unexpected_rules": unexpected,
                })
                raise FirewallMigrationError(
                    "Итоговые exact rules target не совпали с актуальными правилами source",
                    code="firewall_switch_final_rules_mismatch",
                    phase="final_verification",
                )

        persistence_warning = None
        if target == "nftables":
            finalized = _finalize_nftables_persistence(ssh, server)
            if finalized is not None and not finalized[0]:
                persistence_warning = (
                    "firewall работает, но правила не сохранены для загрузки "
                    f"при ребуте: {finalized[1]}"
                )
        message = f"Firewall переключён: активен только {target}"
        if persistence_warning:
            message = f"{message}. Внимание: {persistence_warning}"
        return OpResult(
            ok=True,
            message=message,
            data={
                "source": source_name,
                "target": target,
                "switched": source_name is not None and source_name != target,
                "changed": bool(
                    target_attempted
                    or (source_change is not None and source_change.changed)
                ),
                "ssh_verified": True,
                "nftables_persistence_warning": persistence_warning,
            },
        )
    except ValueError as exc:
        return OpResult(
            ok=False,
            message="Некорректные параметры переключения firewall",
            error=str(exc)[:500],
            data={
                "source": source_name,
                "target": str(target or "")[:32],
                "switched": False,
                "changed": False,
                "ssh_verified": False,
            },
        )
    except Exception as exc:
        if reconcile and source_backend is not None and target_backend is not None:
            rollback = None
            if ssh is not None and target_attempted:
                try:
                    rollback = _switch_rollback(
                        ssh,
                        server,
                        source_backend=source_backend,
                        source_exact=source_exact,
                        source_ambiguous=source_ambiguous,
                        source_deactivation_started=source_deactivation_started,
                        source_change=source_change,
                        target_backend=target_backend,
                        target_attempted=target_attempted,
                        target_provisioned=target_provisioned,
                        target_snapshot=target_snapshot,
                        target_mutations=target_mutations,
                        removed_attempts=removed_attempts,
                        ssh_port=ssh_port,
                    )
                except Exception as rollback_exc:
                    rollback = {
                        "verified": False,
                        "error": str(rollback_exc)[:1200],
                        "packages_removed": False,
                    }
            changed = bool(
                target_attempted
                or (source_change is not None and source_change.changed)
            )
            reason = str(exc)[:1000]
            if rollback is None:
                message = (
                    f"Переключение firewall остановлено: {reason}. "
                    "Можно повторить операцию или отменить её."
                )
            elif rollback.get("verified") is True:
                message = (
                    f"Переключение firewall не завершено: {reason}. Исходный "
                    "firewall и состояние target восстановлены; операцию можно "
                    "повторить."
                )
            else:
                message = (
                    f"Переключение firewall остановлено: {reason}. Безопасное "
                    "исходное состояние firewall не подтверждено; автоматический "
                    "повтор заблокирован."
                )
            error_code = (
                exc.code
                if isinstance(exc, FirewallMigrationError)
                else "firewall_switch_failed"
            )
            error_phase = (
                exc.phase
                if isinstance(exc, FirewallMigrationError)
                else phase
            )
            data = {
                "source": source_name,
                "target": str(target or "")[:32],
                "switched": False,
                "phase": error_phase,
                "critical": True,
                "actions": ["retry", "cancel"],
                "changed": changed,
                "ssh_verified": bool(
                    rollback.get("final_ssh_verified")
                    if rollback is not None
                    else ssh_verified
                ),
            }
            if rollback is not None:
                data["rollback"] = rollback
            return OpResult(
                ok=False,
                message=message,
                error=error_code,
                data=data,
                details={
                    "reason": str(exc)[:1200],
                    **failure_details,
                },
            )

        error = str(exc)[:1200]
        if (
            ssh is not None
            and source_backend is not None
            and source_change is not None
        ):
            try:
                restored = source_backend.restore(
                    ssh,
                    server,
                    source_change.state,
                )
                try:
                    restored_info = source_backend.detect(ssh, server)
                except Exception:
                    restored_info = None
                backend_restored = bool(restored.ok and restored.verified)
                source_active = bool(
                    restored_info is not None
                    and restored_info.active is True
                )
                source_restored = backend_restored and source_active
                ssh_verified, restore_ssh_error = _verify_real_ssh(server)
                if source_restored and ssh_verified:
                    error = f"{error}; исходный firewall восстановлен, SSH подтверждён"
                else:
                    restore_errors = []
                    if not backend_restored:
                        restore_errors.append(
                            restored.error
                            or restored.message
                            or "backend-specific restore не подтверждён"
                        )
                    elif not source_active:
                        restore_errors.append(
                            "активное состояние исходного firewall не подтверждено"
                        )
                    if not ssh_verified:
                        restore_errors.append(
                            "SSH после восстановления не подтверждён: "
                            f"{restore_ssh_error or 'unknown'}"
                        )
                    error = (
                        f"{error}; исходный firewall не восстановлен: "
                        f"{'; '.join(restore_errors)}"
                    )
            except Exception:
                ssh_verified, restore_ssh_error = _verify_real_ssh(server)
                error = f"{error}; ошибка восстановления исходного firewall"
                if ssh_verified:
                    error = f"{error}; SSH подтверждён"
                else:
                    error = (
                        f"{error}; SSH после ошибки восстановления не подтверждён: "
                        f"{restore_ssh_error or 'unknown'}"
                    )
        return OpResult(
            ok=False,
            message="Переключение firewall не завершено",
            error=error[:2000],
            data={
                "source": source_name,
                "target": str(target or "")[:32],
                "switched": False,
                "changed": bool(
                    target_attempted
                    or (source_change is not None and source_change.changed)
                ),
                "ssh_verified": bool(ssh_verified),
            },
        )
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def _verified_scan_on_ssh(
    ssh,
    server: dict,
) -> list[tuple[FirewallBackend, FirewallInfo]]:
    """Перечитать inventory и остановиться при любой технической неоднозначности."""
    detected, errors = _scan_on_ssh(ssh, server)
    uncertain = [
        info.reason or info.error or f"{backend.name}: состояние неоднозначно"
        for backend, info in detected
        if info.active is None or not info.manageable
    ]
    if errors or uncertain:
        raise FirewallDetectionError("; ".join([*errors, *uncertain])[:1200])
    return detected


def _verified_logical_scan_on_ssh(
    ssh,
    server: dict,
) -> list[tuple[FirewallBackend, FirewallInfo]]:
    """Перечитать логические backend-ы без технического nftables-дубликата."""
    detected, errors = _logical_scan_on_ssh(ssh, server)
    uncertain = [
        info.reason or info.error or f"{backend.name}: состояние неоднозначно"
        for backend, info in detected
        if info.active is None or not info.manageable
    ]
    if errors or uncertain:
        raise FirewallDetectionError("; ".join([*errors, *uncertain])[:1200])
    return detected


def _migration_rule_inventory(
    ssh,
    server: dict,
    sources: list[tuple[FirewallBackend, FirewallInfo]],
    ssh_port: int,
) -> tuple[
    list[tuple[FirewallRule, list[str]]],
    list[dict],
    list[dict],
]:
    """Собрать exact/ambiguous rules и отдельно bounded ошибки inventory."""
    exact_by_key: dict[tuple[int, str, str], tuple[FirewallRule, list[str]]] = {}
    ambiguous: list[dict] = []
    inventory_errors: list[dict] = []
    seen_ambiguous: set[tuple[str, str]] = set()
    for backend, _ in sources:
        try:
            rules, unclear = backend.migration_rules(ssh, server)
        except Exception as exc:
            inventory_errors.append({
                "backend": str(backend.name)[:32],
                "error": str(exc)[:800],
            })
            continue
        for rule in rules:
            try:
                key = _rule_key(rule)
            except ValueError:
                raw = str(rule.raw or f"{rule.port}/{rule.protocol}")[:500]
                key_amb = (backend.name, raw)
                if key_amb not in seen_ambiguous:
                    seen_ambiguous.add(key_amb)
                    ambiguous.append({"backend": backend.name, "rule": raw})
                continue
            port, protocol, source = key
            if port == ssh_port and protocol == "tcp" and not source:
                continue
            if key not in exact_by_key:
                exact_by_key[key] = (
                    FirewallRule(
                        port=str(port),
                        protocol=protocol,
                        action="allow",
                        direction="in",
                        raw=str(rule.raw or "")[:500],
                        source=source,
                    ),
                    [backend.name],
                )
            elif backend.name not in exact_by_key[key][1]:
                exact_by_key[key][1].append(backend.name)
        for value in unclear:
            raw = str(value or "").strip()[:500]
            if not raw:
                continue
            key = (backend.name, raw)
            if key in seen_ambiguous:
                continue
            seen_ambiguous.add(key)
            ambiguous.append({"backend": backend.name, "rule": raw})
    return (
        list(exact_by_key.values())[:200],
        ambiguous[:200],
        inventory_errors[:20],
    )


def _public_migratable_rules(
    rules: list[tuple[FirewallRule, list[str]]],
) -> list[dict]:
    return [
        {
            "port": int(rule.port),
            "protocol": rule.protocol,
            "source": str(rule.source or ""),
            "from": [str(name)[:32] for name in sources[:10]],
        }
        for rule, sources in rules[:200]
    ]


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _server_continuation_fingerprint(server: dict) -> str:
    identity = {
        key: server.get(key)
        for key in ("id", "host", "port", "user")
    }
    return _fingerprint(identity)


def _continuation_signature(payload: dict) -> str:
    return hmac.new(
        _CONTINUATION_KEY,
        _canonical_json(payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _issue_continuation(
    server: dict,
    target: str,
    accepted: list[dict],
) -> dict:
    now = int(time.time())
    payload = {
        "version": _CONTINUATION_VERSION,
        "target": target,
        "server": _server_continuation_fingerprint(server),
        "issued_at": now,
        "expires_at": now + _CONTINUATION_TTL_SECONDS,
        "nonce": secrets.token_hex(12),
        "accepted": accepted,
    }
    return {**payload, "signature": _continuation_signature(payload)}


def _normalized_rule_source(value: Any) -> Optional[str]:
    """Source правила в форме решений: '' или канонический IPv4 IP/CIDR."""
    source = value if isinstance(value, str) else ""
    if not source:
        return ""
    if len(source) > 64:
        return None
    normalized = normalize_source(source)
    if not normalized or is_ip_source(normalized) is False:
        return None
    if normalized != source:
        # Неканоническая форма не совпадёт с inventory-ключом.
        return None
    return normalized


def _normalized_failed_rules(value: Any) -> Optional[list[dict]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 200:
        return None
    result: list[dict] = []
    seen: set[tuple[int, str, str]] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"port", "protocol", "source"}:
            return None
        try:
            port = _port(item.get("port"))
            protocol = _protocol(item.get("protocol"))
        except ValueError:
            return None
        source = _normalized_rule_source(item.get("source"))
        if source is None:
            return None
        key = (port, protocol, source)
        if key in seen:
            return None
        seen.add(key)
        result.append({"port": port, "protocol": protocol, "source": source})
    normalized = sorted(
        result, key=lambda item: (item["port"], item["protocol"], item["source"])
    )
    return normalized if result == normalized else None


def _normalized_selected_rules(value: Any) -> Optional[list[dict]]:
    """Форма выбора правил: 0–200 элементов {port, protocol, source} без дублей.

    В отличие от failed_rules, пустой список допустим — это осознанное
    решение не переносить ни одного exact-правила (SSH добавляется принудительно).
    """
    if not isinstance(value, list) or len(value) > 200:
        return None
    result: list[dict] = []
    seen: set[tuple[int, str, str]] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"port", "protocol", "source"}:
            return None
        try:
            port = _port(item.get("port"))
            protocol = _protocol(item.get("protocol"))
        except ValueError:
            return None
        source = _normalized_rule_source(item.get("source"))
        if source is None:
            return None
        key = (port, protocol, source)
        if key in seen:
            return None
        seen.add(key)
        result.append({"port": port, "protocol": protocol, "source": source})
    result.sort(key=lambda item: (item["port"], item["protocol"], item["source"]))
    return result


def _validated_continuation(
    continuation: Any,
    *,
    server: dict,
    target: str,
) -> list[dict]:
    if continuation is None:
        return []
    if not isinstance(continuation, dict):
        raise ValueError("Некорректное продолжение firewall-транзакции")
    try:
        encoded = _canonical_json(continuation)
    except (TypeError, ValueError) as exc:
        raise ValueError("Некорректное продолжение firewall-транзакции") from exc
    if len(encoded.encode("utf-8")) > 32 * 1024:
        raise ValueError("Продолжение firewall-транзакции превышает допустимый размер")

    expected_keys = {
        "version",
        "target",
        "server",
        "issued_at",
        "expires_at",
        "nonce",
        "accepted",
        "signature",
    }
    if set(continuation) != expected_keys:
        raise ValueError("Некорректная структура продолжения firewall-транзакции")
    signature = continuation.get("signature")
    if (
        not isinstance(signature, str)
        or len(signature) != 64
        or any(character not in "0123456789abcdef" for character in signature)
    ):
        raise ValueError("Подпись продолжения firewall-транзакции некорректна")
    payload = {key: continuation[key] for key in expected_keys if key != "signature"}
    if not hmac.compare_digest(signature, _continuation_signature(payload)):
        raise ValueError("Продолжение firewall-транзакции не было выдано сервером")

    if continuation.get("version") != _CONTINUATION_VERSION:
        raise ValueError("Версия продолжения firewall-транзакции не поддерживается")
    if continuation.get("target") != target:
        raise ValueError("Продолжение выдано для другого target firewall")
    if continuation.get("server") != _server_continuation_fingerprint(server):
        raise ValueError("Продолжение выдано для другого сервера")
    issued_at = continuation.get("issued_at")
    expires_at = continuation.get("expires_at")
    if (
        isinstance(issued_at, bool)
        or not isinstance(issued_at, int)
        or isinstance(expires_at, bool)
        or not isinstance(expires_at, int)
        or expires_at <= issued_at
        or expires_at - issued_at != _CONTINUATION_TTL_SECONDS
    ):
        raise ValueError("Срок действия продолжения firewall-транзакции некорректен")
    now = int(time.time())
    if issued_at > now + 30 or expires_at < now:
        raise ValueError("Продолжение firewall-транзакции устарело")
    nonce = continuation.get("nonce")
    if (
        not isinstance(nonce, str)
        or len(nonce) != 24
        or any(character not in "0123456789abcdef" for character in nonce)
    ):
        raise ValueError("Nonce продолжения firewall-транзакции некорректен")

    accepted = continuation.get("accepted")
    if not isinstance(accepted, list) or not 1 <= len(accepted) <= 2:
        raise ValueError("Последовательность решений firewall-транзакции некорректна")
    decisions: list[str] = []
    normalized: list[dict] = []
    for item in accepted:
        if not isinstance(item, dict):
            raise ValueError("Решение firewall-транзакции некорректно")
        decision = item.get("decision")
        fingerprint = item.get("fingerprint")
        if decision not in _CONTINUATION_DECISIONS:
            raise ValueError("Неизвестное решение firewall-транзакции")
        if (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
        ):
            raise ValueError("Fingerprint решения firewall-транзакции некорректен")
        expected_item_keys = {"decision", "fingerprint"}
        normalized_item = {
            "decision": decision,
            "fingerprint": fingerprint,
        }
        if decision == "skip_failed_rules":
            expected_item_keys.add("failed_rules")
            failed_rules = _normalized_failed_rules(item.get("failed_rules"))
            if failed_rules is None:
                raise ValueError("Список неперенесённых правил некорректен")
            normalized_item["failed_rules"] = failed_rules
        if set(item) != expected_item_keys:
            raise ValueError("Параметры решения firewall-транзакции некорректны")
        decisions.append(decision)
        normalized.append(normalized_item)

    allowed_sequences = {
        ("continue_without_rule_migration",),
        ("skip_ambiguous_rules",),
        ("skip_failed_rules",),
        ("skip_ambiguous_rules", "skip_failed_rules"),
    }
    if tuple(decisions) not in allowed_sequences:
        raise ValueError("Порядок решений firewall-транзакции некорректен")
    return normalized


def _source_context_fingerprint(target: str, sources: list[str]) -> str:
    return _fingerprint({
        "target": target,
        "sources": sorted(str(name)[:32] for name in sources),
    })


def _rule_inventory_fingerprint(
    target: str,
    sources: list[str],
    exact_rules: list[tuple[FirewallRule, list[str]]],
    ambiguous: list[dict],
) -> str:
    exact = sorted(
        _public_migratable_rules(exact_rules),
        key=lambda item: (item["port"], item["protocol"], item["source"], item["from"]),
    )
    unclear = sorted(
        [
            {
                "backend": str(item.get("backend") or "")[:32],
                "rule": str(item.get("rule") or "")[:500],
            }
            for item in ambiguous[:200]
        ],
        key=lambda item: (item["backend"], item["rule"]),
    )
    return _fingerprint({
        "target": target,
        "sources": sorted(str(name)[:32] for name in sources),
        "exact": exact,
        "ambiguous": unclear,
    })


def _expected_rule_payload(rules: set[tuple[int, str, str]]) -> list[dict]:
    return [
        {"port": port, "protocol": protocol, "source": source}
        for port, protocol, source in sorted(rules)
    ][:200]


def _verify_expected_rules(
    ssh,
    server: dict,
    backend: FirewallBackend,
    expected: set[tuple[int, str, str]],
) -> tuple[bool, list[dict], Optional[str]]:
    try:
        rules, _ = backend.migration_rules(ssh, server)
    except Exception as exc:
        return False, _expected_rule_payload(expected), str(exc)[:800]
    actual: set[tuple[int, str, str]] = set()
    for rule in rules:
        try:
            actual.add(_rule_key(rule))
        except ValueError:
            continue
    missing = expected - actual
    return not missing, _expected_rule_payload(missing), None


def _migration_state_before_source_disable(
    ssh,
    server: dict,
    *,
    target: str,
    sources: list[str],
    require_target: bool = True,
) -> list[tuple[FirewallBackend, FirewallInfo]]:
    """Fresh-read target/source, не считая managed nftables отдельным firewall.

    require_target=False — для rollback после неудачной ПОДГОТОВКИ target:
    target тогда никогда не активировался, требовать его active нельзя
    (иначе rollback сам падал «состояние изменилось» и подменял настоящую
    ошибку подготовки страхилкой rollback_unverified).
    """
    detected, errors = _scan_on_ssh(ssh, server)
    nftables_is_logical = target == "nftables" or "nftables" in sources
    relevant_errors = [
        error
        for error in errors
        if nftables_is_logical or not error.startswith("nftables:")
    ]
    relevant_uncertain = [
        info.reason or info.error or f"{backend.name}: состояние неоднозначно"
        for backend, info in detected
        if (backend.name != "nftables" or nftables_is_logical)
        and (info.active is None or not info.manageable)
    ]
    if relevant_errors or relevant_uncertain:
        raise FirewallDetectionError(
            "; ".join([*relevant_errors, *relevant_uncertain])[:1200]
        )

    by_name = {backend.name: info for backend, info in detected}
    for name in [target, *sources]:
        if name == target and not require_target:
            continue
        info = by_name.get(name)
        if info is None or info.active is not True or not info.manageable:
            raise FirewallMigrationError(
                f"Активное состояние {name} изменилось во время подготовки target",
                code="firewall_source_state_changed",
                phase="source_confirmation",
            )

    active_managed = {
        backend.name
        for backend, info in detected
        if backend.name in {"ufw", "firewalld"} and info.active is True
    }
    expected_managed = {
        name for name in [target, *sources] if name in {"ufw", "firewalld"}
    }
    if active_managed != expected_managed:
        raise FirewallMigrationError(
            "Набор активных firewall изменился во время подготовки target",
            code="firewall_source_state_changed",
            phase="source_confirmation",
        )
    return detected


def _continuation_error(message: str, target: str) -> OpResult:
    return OpResult(
        ok=False,
        message=(
            "Продолжение операции отклонено до изменений: "
            f"{message}. Повторить — начнёт транзакцию заново; "
            "Отмена — сохранит текущий firewall."
        ),
        error="invalid_firewall_continuation",
        data={
            "target": str(target or "")[:32],
            "phase": "decision_validation",
            "critical": True,
            "actions": ["retry", "cancel"],
            "changed": False,
        },
        details={"reason": str(message)[:1000]},
    )


def _selection_error(message: str, target: str) -> OpResult:
    return OpResult(
        ok=False,
        message=(
            "Выбор правил отклонён до изменений: "
            f"{message}. Повторить — начнёт транзакцию заново; "
            "Отмена — сохранит текущий firewall."
        ),
        error="invalid_firewall_rule_selection",
        data={
            "target": str(target or "")[:32],
            "phase": "decision_validation",
            "critical": True,
            "actions": ["retry", "cancel"],
            "changed": False,
        },
        details={"reason": str(message)[:1000]},
    )


def _rollback_lifecycle(
    ssh,
    server: dict,
    changed: list[tuple[FirewallBackend, FirewallStateChange]],
) -> tuple[list[dict], bool]:
    restored: list[dict] = []
    for backend, change in reversed(changed):
        try:
            result = backend.restore(ssh, server, change.state)
            restored.append(result.to_dict())
        except Exception as exc:
            restored.append({
                "backend": backend.name,
                "operation": "restore",
                "ok": False,
                "changed": False,
                "verified": False,
                "message": "Состояние firewall не восстановлено",
                "error": str(exc)[:800],
            })
    return restored, all(
        item.get("ok") is True and item.get("verified") is True
        for item in restored
    )


def _cleanup_exact_mutation(
    ssh,
    server: dict,
    mutation: FirewallMutation,
) -> dict:
    if not mutation.changed or mutation.existed_before:
        return {
            "attempted": False,
            "restored": True,
            "retained": False,
            "reason": "Правило существовало ранее или не добавлялось операцией",
            "mutation": mutation.to_dict(),
        }
    try:
        cleanup = cleanup_mutation_on_ssh(ssh, server, mutation)
        restored = bool(cleanup.ok and cleanup.verified)
        return {
            "attempted": True,
            "restored": restored,
            "retained": not restored,
            "mutation": cleanup.to_dict(),
        }
    except Exception as exc:
        return {
            "attempted": True,
            "restored": False,
            "retained": True,
            "error": str(exc)[:800],
            "mutation": mutation.to_dict(),
        }


def _migration_rollback(
    ssh,
    server: dict,
    *,
    target_backend: FirewallBackend,
    target_was_active: bool,
    target_prepared: bool,
    target_mutations: list[FirewallMutation],
    changed_competitors: list[tuple[FirewallBackend, FirewallStateChange]],
    expected_competitors: list[str],
    target_provisioned: bool = False,
) -> dict:
    lifecycle, lifecycle_ok = _rollback_lifecycle(
        ssh, server, changed_competitors
    )
    inventory: list[dict] = []
    competitors_restored = False
    scan_error = None
    try:
        detected = _migration_state_before_source_disable(
            ssh,
            server,
            target=target_backend.name,
            sources=expected_competitors,
            # target мог и не активироваться (подготовка не удалась до
            # всяких изменений) — требовать его active нельзя
            require_target=bool(target_was_active or target_prepared),
        )
        inventory = _candidates_payload(_candidates(detected))
        active_names = {
            backend.name for backend, info in detected if info.active is True
        }
        competitors_restored = set(expected_competitors).issubset(active_names)
    except Exception as exc:
        scan_error = str(exc)[:1200]

    access_ok, access_error = _verify_real_ssh(server)
    safe_to_restore_target = (
        lifecycle_ok
        and competitors_restored
        and access_ok
        and bool(expected_competitors)
    )
    target_state = None
    target_inactive = False

    cleanup: list[dict] = []
    target_unprovisioned = False
    if (
        target_provisioned
        and not target_was_active
        and safe_to_restore_target
    ):
        # Таблица bot4vps провижинена панелью в ЭТОЙ операции — собственность
        # панели: удаляем целиком (ruleset + conf + include + сервис + выбор
        # цепочки). Per-rule cleanup не нужен: правил без таблицы не бывает.
        try:
            ok, detail = target_backend.rollback_provisioned_ruleset(
                ssh, server
            )
        except Exception as exc:
            ok, detail = False, str(exc)[:800]
        if ok:
            target_unprovisioned = True
            target_state = {
                "backend": target_backend.name,
                "operation": "unprovision",
                "ok": True,
                "changed": True,
                "verified": True,
                "message": "Базовая nftables таблица bot4vps удалена",
                "error": None,
            }
            target_inactive = True
            cleanup = [
                {
                    "attempted": False,
                    "restored": True,
                    "retained": False,
                    "reason": "Таблица bot4vps удалена целиком с persistence",
                    "mutation": item.to_dict(),
                }
                for item in reversed(target_mutations)
            ]
    if not target_unprovisioned and (
        target_was_active or (target_prepared and safe_to_restore_target)
    ):
        current_ssh_port = _port(server.get("port") or 22)
        for mutation in reversed(target_mutations):
            if (
                not target_was_active
                and mutation.changed
                and not mutation.existed_before
                and mutation.port == current_ssh_port
                and mutation.protocol == "tcp"
            ):
                cleanup.append({
                    "attempted": False,
                    "restored": False,
                    "retained": True,
                    "reason": (
                        "Новое правило текущего SSH-порта не удалено до "
                        "деактивации target"
                    ),
                    "mutation": mutation.to_dict(),
                })
                continue
            cleanup.append(_cleanup_exact_mutation(ssh, server, mutation))
    elif not target_unprovisioned:
        cleanup = [
            {
                "attempted": False,
                "restored": not bool(item.changed and not item.existed_before),
                "retained": bool(item.changed and not item.existed_before),
                "reason": (
                    "Правило сохранено, чтобы не потерять SSH-доступ"
                    if item.changed and not item.existed_before
                    else "Правило существовало ранее или не добавлялось операцией"
                ),
                "mutation": item.to_dict(),
            }
            for item in reversed(target_mutations)
        ]
    rules_restored = all(item.get("restored") is True for item in cleanup)

    if not target_unprovisioned and target_prepared and not target_was_active:
        if safe_to_restore_target:
            try:
                state_change = target_backend.deactivate(ssh, server)
                target_state = state_change.to_dict()
                target_inactive = bool(state_change.ok and state_change.verified)
            except Exception as exc:
                target_state = {
                    "backend": target_backend.name,
                    "operation": "deactivate",
                    "ok": False,
                    "verified": False,
                    "error": str(exc)[:800],
                }
        else:
            target_state = {
                "backend": target_backend.name,
                "operation": "deactivate",
                "ok": False,
                "verified": False,
                "message": (
                    "Target оставлен активным: безопасное восстановление "
                    "source не подтверждено"
                ),
            }
    elif target_was_active:
        target_inactive = False

    final_inventory: list[dict] = []
    final_scan_error = None
    final_state_restored = False
    try:
        final_detected = _verified_logical_scan_on_ssh(ssh, server)
        final_inventory = _candidates_payload(_candidates(final_detected))
        final_active = sorted(
            backend.name
            for backend, info in final_detected
            if info.active is True
        )
        expected_active = sorted([
            *expected_competitors,
            *([target_backend.name] if target_was_active else []),
        ])
        final_state_restored = final_active == expected_active
    except Exception as exc:
        final_scan_error = str(exc)[:1200]

    final_ssh_ok, final_ssh_error = _verify_real_ssh(server)
    target_restored = (
        target_was_active
        or not target_prepared
        or target_inactive
    )
    rollback_verified = bool(
        lifecycle_ok
        and competitors_restored
        and access_ok
        and target_restored
        and rules_restored
        and final_state_restored
        and final_ssh_ok
    )

    return {
        "verified": rollback_verified,
        "lifecycle": lifecycle,
        "lifecycle_restored": lifecycle_ok,
        "competitors_restored": competitors_restored,
        "ssh_verified": access_ok,
        "ssh_error": access_error,
        "target": target_state,
        "target_unprovisioned": target_unprovisioned,
        "target_preparation_retained": bool(
            target_prepared and not target_was_active and not target_inactive
        ),
        "rules": cleanup,
        "rules_restored": rules_restored,
        "final_state_restored": final_state_restored,
        "final_ssh_verified": final_ssh_ok,
        "final_ssh_error": final_ssh_error,
        "post_cleanup_ssh": {
            "verified": final_ssh_ok,
            "error": final_ssh_error,
        },
        "inventory": inventory,
        "final_inventory": final_inventory,
        "scan_error": scan_error,
        "final_scan_error": final_scan_error,
        "packages_removed": False,
    }


def migrate(
    server: dict,
    target: str,
    *,
    confirm: bool,
    continuation: Optional[dict] = None,
    migrate_rules: Optional[bool] = None,
    skip_ambiguous_rules: bool = False,
) -> OpResult:
    """Подготовить target, перенести exact rules и безопасно отключить source."""
    if not confirm:
        return OpResult(
            ok=False,
            message=(
                "Подтвердите установку, перенос доступных правил и смену "
                "активного firewall"
            ),
            error="firewall_migration_confirmation_required",
            data={
                "target": str(target or "")[:32],
                "phase": "confirmation",
                "changed": False,
            },
        )

    try:
        target = _backend_name(target)
        ssh_port = _port(server.get("port") or 22)
    except ValueError as exc:
        return OpResult(
            ok=False,
            message=(
                "Операция остановлена до изменений: параметры firewall или "
                "текущего SSH-порта некорректны"
            ),
            error="invalid_firewall_migration_parameters",
            data={
                "target": str(target or "")[:32],
                "phase": "validation",
                "critical": True,
                "actions": ["retry", "cancel"],
                "changed": False,
            },
            details={"reason": str(exc)[:1000]},
        )
    if migrate_rules is not None and not isinstance(migrate_rules, bool):
        return _continuation_error(
            "Параметр переноса правил имеет некорректный формат",
            target,
        )
    if skip_ambiguous_rules:
        return _continuation_error(
            "Решение о неоднозначных правилах должно быть выдано сервером",
            target,
        )
    try:
        accepted = _validated_continuation(
            continuation,
            server=server,
            target=target,
        )
    except ValueError as exc:
        return _continuation_error(str(exc), target)

    ssh = None
    target_backend = _BY_NAME[target]
    target_was_active = False
    target_prepared = False
    target_provisioned = False
    target_mutations: list[FirewallMutation] = []
    changed_competitors: list[tuple[FirewallBackend, FirewallStateChange]] = []
    lifecycle_results: list[dict] = []
    expected_competitors: list[str] = []
    migrated: list[dict] = []
    ambiguous: list[dict] = []
    inventory_errors: list[dict] = []
    skipped_failed_rules: list[dict] = []
    mutation_started = False
    phase = "initial_scan"
    try:
        ssh = create_ssh_client(server, timeout=20)
        initial = _verified_logical_scan_on_ssh(ssh, server)
        target_found = next(
            ((backend, info) for backend, info in initial if backend.name == target),
            None,
        )
        target_was_active = bool(
            target_found is not None and target_found[1].active is True
        )
        competitors = [
            (backend, info)
            for backend, info in initial
            if info.active is True and backend.name != target
        ]
        if len(competitors) > 1:
            names = ", ".join(backend.name for backend, _ in competitors)
            raise FirewallMigrationError(
                f"Обнаружено несколько исходных firewall: {names}",
                code="ambiguous_active_firewalls",
                phase="initial_scan",
            )
        expected_competitors = sorted(backend.name for backend, _ in competitors)
        source_fingerprint = _source_context_fingerprint(
            target,
            expected_competitors,
        )
        accepted_by_name = {item["decision"]: item for item in accepted}

        if target_was_active and not competitors:
            if accepted:
                return _continuation_error(
                    "Target уже стал единственным активным firewall",
                    target,
                )
            ssh_ok, ssh_error = _verify_real_ssh(server)
            if not ssh_ok:
                raise FirewallMigrationError(
                    "Реальное SSH-подключение к активному target не подтверждено",
                    code="ssh_verification_failed",
                    phase="target_verification",
                )
            return OpResult(
                ok=True,
                message=f"{target} уже является единственным активным firewall",
                data={
                    "target": target,
                    "phase": "complete",
                    "switched": False,
                    "changed": False,
                    "ssh_verified": True,
                    "migrated_rules": [],
                    "skipped_ambiguous_rules": [],
                    "skipped_failed_rules": [],
                },
            )

        if accepted and not competitors:
            return _continuation_error(
                "Исходный firewall больше не активен",
                target,
            )

        exact_rules: list[tuple[FirewallRule, list[str]]] = []
        inventory_fingerprint: Optional[str] = None
        continue_without_rules = accepted_by_name.get(
            "continue_without_rule_migration"
        )
        phase = "source_inventory"
        if continue_without_rules is not None:
            if continue_without_rules["fingerprint"] != source_fingerprint:
                return _continuation_error(
                    "Набор исходных firewall изменился после решения пользователя",
                    target,
                )
        elif competitors:
            exact_rules, ambiguous, inventory_errors = _migration_rule_inventory(
                ssh,
                server,
                competitors,
                ssh_port,
            )
            if inventory_errors:
                if accepted:
                    return _continuation_error(
                        "Inventory исходного firewall изменился и теперь недоступен",
                        target,
                    )
                decision = {
                    "decision": "continue_without_rule_migration",
                    "fingerprint": source_fingerprint,
                }
                return OpResult(
                    ok=False,
                    message=(
                        "Не удалось прочитать правила текущего firewall на этапе "
                        "инвентаризации. Продолжить — начнёт новую попытку без "
                        "автоматического переноса правил; Отмена — сохранит "
                        "текущий firewall без изменений."
                    ),
                    error="firewall_source_inventory_unavailable",
                    data={
                        "target": target,
                        "phase": "source_inventory",
                        "decision_required": "continue_without_rule_migration",
                        "actions": ["continue", "cancel"],
                        "continue_with": _issue_continuation(
                            server,
                            target,
                            [decision],
                        ),
                        "inventory_errors": inventory_errors,
                        "backends": _candidates_payload(_candidates(initial)),
                        "changed": False,
                    },
                )

            inventory_fingerprint = _rule_inventory_fingerprint(
                target,
                expected_competitors,
                exact_rules,
                ambiguous,
            )
            for item in accepted:
                if item["decision"] != "continue_without_rule_migration" and (
                    item["fingerprint"] != inventory_fingerprint
                ):
                    return _continuation_error(
                        "Правила исходного firewall изменились после решения пользователя",
                        target,
                    )

            skip_ambiguous = "skip_ambiguous_rules" in accepted_by_name
            if ambiguous and not skip_ambiguous:
                if accepted:
                    return _continuation_error(
                        "Последовательность решений больше не соответствует правилам source",
                        target,
                    )
                decision = {
                    "decision": "skip_ambiguous_rules",
                    "fingerprint": inventory_fingerprint,
                }
                return OpResult(
                    ok=False,
                    message=(
                        "Некоторые правила невозможно безопасно перенести. "
                        "Продолжить без них? Продолжить — перенесёт точные правила; "
                        "Отмена — сохранит текущий firewall без изменений."
                    ),
                    error="ambiguous_firewall_rules",
                    data={
                        "target": target,
                        "phase": "source_inventory",
                        "decision_required": "skip_ambiguous_rules",
                        "actions": ["continue", "cancel"],
                        "continue_with": _issue_continuation(
                            server,
                            target,
                            [decision],
                        ),
                        "ambiguous_rules": ambiguous,
                        "migratable_rules": _public_migratable_rules(exact_rules),
                        "backends": _candidates_payload(_candidates(initial)),
                        "changed": False,
                    },
                )

            failed_decision = accepted_by_name.get("skip_failed_rules")
            if failed_decision is not None:
                exact_keys = {
                    _rule_key(rule) for rule, _ in exact_rules
                }
                failed_keys = {
                    (item["port"], item["protocol"], item["source"])
                    for item in failed_decision["failed_rules"]
                }
                if not failed_keys.issubset(exact_keys):
                    return _continuation_error(
                        "Список пропускаемых правил больше не соответствует source",
                        target,
                    )
                skipped_failed_rules = list(failed_decision["failed_rules"])

        source_tokens: dict[str, dict[str, str]] = {}
        if "nftables" in expected_competitors:
            phase = "source_resolution"
            try:
                source_tokens["nftables"] = _BY_NAME[
                    "nftables"
                ].resolve_switch_source(ssh, server)
            except Exception as exc:
                raise FirewallMigrationError(
                    "Точный nftables source нельзя безопасно подтвердить",
                    code="nftables_source_resolution_failed",
                    phase="source_resolution",
                ) from exc

        phase = "target_preparation"
        if not target_was_active:
            # mutation_started — ДО вызова: ensure_installed может открыть
            # SSH-порт в target и упасть позже, такие мутации обязан чистить
            # rollback. target_prepared — только по факту успеха: иначе
            # rollback после неудачной подготовки думал, что target
            # активирован, и падал сам вместо честной ошибки подготовки.
            mutation_started = True
            # Автопровижининг базовой таблицы bot4vps: rollback должен
            # знать о нём ДО вызова — ensure_installed сохранит выбор
            # цепочки в storage, и при неудаче его придётся убрать.
            target_provisioned = (
                target == "nftables"
                and _nftables_provision_pending(ssh, server)
            )
            try:
                prepared, detail = target_backend.ensure_installed(ssh, server)
            except Exception as exc:
                raise FirewallMigrationError(
                    f"Не удалось безопасно подготовить {target}",
                    code="target_preparation_failed",
                    phase="target_preparation",
                ) from exc
            if not prepared:
                raise FirewallMigrationError(
                    detail or f"Не удалось подготовить {target}",
                    code="target_preparation_failed",
                    phase="target_preparation",
                )
            target_prepared = True

        target_info = target_backend.detect(ssh, server)
        if (
            target_info is None
            or target_info.active is not True
            or not target_info.manageable
        ):
            reason = (
                target_info.reason or target_info.error
                if target_info is not None
                else "target firewall не обнаружен"
            )
            raise FirewallMigrationError(
                f"Активное состояние target firewall не подтверждено: {reason}",
                code="target_verification_failed",
                phase="target_verification",
            )

        phase = "ssh_rule"
        mutation_started = True
        ssh_mutation = target_backend.open_port(
            ssh,
            server,
            ssh_port,
            "tcp",
            "",
        )
        target_mutations.append(ssh_mutation)
        if not ssh_mutation.ok or not ssh_mutation.verified:
            raise FirewallMigrationError(
                ssh_mutation.message
                or "Allow текущего SSH-порта в target не подтверждён",
                code=ssh_mutation.error or "ssh_rule_verification_failed",
                phase="ssh_rule",
            )

        skipped_failed_keys = {
            (item["port"], item["protocol"], item["source"])
            for item in skipped_failed_rules
        }
        untracked_rule_failure = False
        failed_rules: list[dict] = []
        phase = "rule_migration"
        for rule, sources in exact_rules:
            key = _rule_key(rule)
            if key in skipped_failed_keys:
                continue
            try:
                mutation = target_backend.open_port(
                    ssh,
                    server,
                    key[0],
                    key[1],
                    key[2],
                )
                target_mutations.append(mutation)
            except Exception as exc:
                untracked_rule_failure = True
                failed_rules.append({
                    "port": key[0],
                    "protocol": key[1],
                    "source": key[2],
                    "from": [str(name)[:32] for name in sources[:10]],
                    "reason": str(exc)[:800],
                })
                continue
            if not mutation.ok or not mutation.verified:
                failed_rules.append({
                    "port": key[0],
                    "protocol": key[1],
                    "source": key[2],
                    "from": [str(name)[:32] for name in sources[:10]],
                    "reason": str(
                        mutation.message or mutation.error or "изменение не подтверждено"
                    )[:800],
                })
                continue
            migrated.append({
                "port": key[0],
                "protocol": key[1],
                "source": key[2],
                "from": [str(name)[:32] for name in sources[:10]],
                "changed": bool(mutation.changed),
                "existed_before": bool(mutation.existed_before),
            })

        if failed_rules:
            rollback = _migration_rollback(
                ssh,
                server,
                target_backend=target_backend,
                target_was_active=target_was_active,
                target_prepared=target_prepared,
                target_provisioned=target_provisioned,
                target_mutations=target_mutations,
                changed_competitors=changed_competitors,
                expected_competitors=expected_competitors,
            )
            if untracked_rule_failure or not rollback.get("verified"):
                return OpResult(
                    ok=False,
                    message=(
                        "Перенос правил остановлен, но полный rollback source, "
                        "target и SSH не подтверждён. Небезопасное продолжение "
                        "недоступно; Отмена сохранит операцию остановленной."
                    ),
                    error="firewall_migration_rollback_unverified",
                    data={
                        "target": target,
                        "phase": "rollback",
                        "critical": True,
                        "actions": ["retry", "cancel"],
                        "changed": True,
                        "failed_rules": failed_rules,
                        "untracked_rule_failure": untracked_rule_failure,
                        "rollback": rollback,
                    },
                    details={"failed_rules": failed_rules},
                )

            current_failed = [
                {
                    "port": item["port"],
                    "protocol": item["protocol"],
                    "source": item["source"],
                }
                for item in failed_rules
            ]
            combined_failed = sorted(
                {
                    (item["port"], item["protocol"], item["source"])
                    for item in [*skipped_failed_rules, *current_failed]
                },
            )
            failed_decision = {
                "decision": "skip_failed_rules",
                "fingerprint": inventory_fingerprint
                or _rule_inventory_fingerprint(
                    target,
                    expected_competitors,
                    exact_rules,
                    ambiguous,
                ),
                "failed_rules": [
                    {"port": port, "protocol": protocol, "source": source}
                    for port, protocol, source in combined_failed
                ],
            }
            next_accepted = [
                item for item in accepted if item["decision"] != "skip_failed_rules"
            ]
            next_accepted.append(failed_decision)
            count = len(failed_rules)
            return OpResult(
                ok=False,
                message=(
                    f"Не удалось перенести {count} правил. Продолжить без них? "
                    "Изменения firewall текущей попытки откатаны, source и SSH "
                    "подтверждены; установленный пакет target не удалён. "
                    "Отмена оставит source активным."
                ),
                error="firewall_rule_migration_failed",
                data={
                    "target": target,
                    "phase": "rule_migration_rollback",
                    "decision_required": "skip_failed_rules",
                    "actions": ["continue", "cancel"],
                    "continue_with": _issue_continuation(
                        server,
                        target,
                        next_accepted,
                    ),
                    "changed": bool(target_prepared or target_mutations),
                    "failed_rules": failed_rules,
                    "skipped_failed_rules": skipped_failed_rules,
                    "rollback": rollback,
                },
            )

        expected_rules = {
            (ssh_port, "tcp", ""),
            *{
                (item["port"], item["protocol"], item["source"])
                for item in migrated
            },
        }
        phase = "target_verification"
        target_info = target_backend.detect(ssh, server)
        if (
            target_info is None
            or target_info.active is not True
            or not target_info.manageable
        ):
            raise FirewallMigrationError(
                "Target firewall не прошёл проверку после настройки правил",
                code="target_verification_failed",
                phase="target_verification",
            )
        rules_ok, missing_rules, rules_error = _verify_expected_rules(
            ssh,
            server,
            target_backend,
            expected_rules,
        )
        if not rules_ok:
            reason = rules_error or f"Отсутствуют правила: {missing_rules}"
            raise FirewallMigrationError(
                f"Ожидаемые правила target не подтверждены: {reason}",
                code="target_verification_failed",
                phase="target_rule_verification",
            )

        phase = "pre_switch_ssh"
        first_ssh, first_error = _verify_real_ssh(server)
        if not first_ssh:
            raise FirewallMigrationError(
                "Реальное SSH-подключение после подготовки target не подтверждено",
                code="ssh_verification_failed",
                phase="pre_switch_ssh",
            ) from RuntimeError(first_error or "unknown")

        phase = "source_confirmation"
        _migration_state_before_source_disable(
            ssh,
            server,
            target=target,
            sources=expected_competitors,
        )
        if "nftables" in expected_competitors:
            try:
                current_token = _BY_NAME["nftables"].resolve_switch_source(
                    ssh,
                    server,
                )
            except Exception as exc:
                raise FirewallMigrationError(
                    "Точный nftables source изменился перед отключением",
                    code="nftables_source_state_changed",
                    phase="source_confirmation",
                ) from exc
            if current_token != source_tokens.get("nftables"):
                raise FirewallMigrationError(
                    "Точный nftables source изменился перед отключением",
                    code="nftables_source_state_changed",
                    phase="source_confirmation",
                )

        phase = "source_deactivation"
        for backend, _ in competitors:
            if backend.name == "nftables":
                change = _BY_NAME["nftables"].deactivate_exact(
                    ssh,
                    server,
                    source_tokens["nftables"],
                )
            else:
                change = backend.deactivate(ssh, server)
            lifecycle_results.append(change.to_dict())
            if change.changed:
                changed_competitors.append((backend, change))
            if not change.ok or not change.verified:
                raise FirewallMigrationError(
                    change.message or f"Не удалось отключить {backend.name}",
                    code=change.error or "source_deactivation_failed",
                    phase="source_deactivation",
                )

        phase = "final_scan"
        final_detected = _verified_logical_scan_on_ssh(ssh, server)
        final_active = [
            backend.name
            for backend, info in final_detected
            if info.active is True
        ]
        if final_active != [target]:
            raise FirewallMigrationError(
                "После переключения не подтверждён единственный active target firewall",
                code="target_verification_failed",
                phase="final_scan",
            )

        phase = "final_ssh"
        final_ssh, final_error = _verify_real_ssh(server)
        if not final_ssh:
            raise FirewallMigrationError(
                "Реальное SSH-подключение после отключения source не подтверждено",
                code="ssh_verification_failed",
                phase="final_ssh",
            ) from RuntimeError(final_error or "unknown")

        phase = "final_rule_verification"
        rules_ok, missing_rules, rules_error = _verify_expected_rules(
            ssh,
            server,
            target_backend,
            expected_rules,
        )
        if not rules_ok:
            reason = rules_error or f"Отсутствуют правила: {missing_rules}"
            raise FirewallMigrationError(
                f"Итоговая проверка правил target не пройдена: {reason}",
                code="target_verification_failed",
                phase="final_rule_verification",
            )

        persistence_warning = None
        if target == "nftables":
            finalized = _finalize_nftables_persistence(ssh, server)
            if finalized is not None and not finalized[0]:
                persistence_warning = (
                    "firewall работает, но правила не сохранены для загрузки "
                    f"при ребуте: {finalized[1]}"
                )
        message = f"Firewall переключён: активен только {target}"
        if persistence_warning:
            message = f"{message}. Внимание: {persistence_warning}"
        return OpResult(
            ok=True,
            message=message,
            data={
                "target": target,
                "phase": "complete",
                "switched": bool(expected_competitors),
                "changed": bool(
                    target_prepared
                    or any(item.changed for item in target_mutations)
                    or any(item.get("changed") for item in lifecycle_results)
                ),
                "ssh_verified": True,
                "nftables_persistence_warning": persistence_warning,
                "automatic_rule_migration": continue_without_rules is None,
                "migrated_rules": migrated,
                "skipped_ambiguous_rules": (
                    ambiguous
                    if "skip_ambiguous_rules" in accepted_by_name
                    else []
                ),
                "skipped_failed_rules": skipped_failed_rules,
                "target_mutations": [item.to_dict() for item in target_mutations],
                "lifecycle": lifecycle_results,
                "backends": _candidates_payload(_candidates(final_detected)),
            },
        )
    except Exception as exc:
        if isinstance(exc, FirewallMigrationError):
            error_code = exc.code
            phase = exc.phase
        elif isinstance(exc, FirewallDetectionError):
            error_code = "firewall_detection_failed"
        else:
            error_code = "firewall_migration_failed"
        rollback = None
        if ssh is not None and mutation_started:
            rollback = _migration_rollback(
                ssh,
                server,
                target_backend=target_backend,
                target_was_active=target_was_active,
                target_prepared=target_prepared,
                target_provisioned=target_provisioned,
                target_mutations=target_mutations,
                changed_competitors=changed_competitors,
                expected_competitors=expected_competitors,
            )
        rollback_unverified = bool(rollback and not rollback.get("verified"))
        if rollback_unverified:
            error_code = "firewall_migration_rollback_unverified"
            phase = "rollback"
            message = (
                "Операция остановлена, но восстановление source, target и SSH "
                "подтверждено не полностью. Небезопасное продолжение недоступно; "
                "Отмена оставит операцию остановленной."
            )
        else:
            message = (
                f"Операция firewall остановлена на этапе «{phase}»: {str(exc)[:700]}. "
                "Повторить — начнёт новую транзакцию с повторной проверкой; "
                "Отмена — не продолжит переключение."
            )
        return OpResult(
            ok=False,
            message=message,
            error=error_code,
            data={
                "target": str(target or "")[:32],
                "phase": phase,
                "critical": True,
                "actions": ["retry", "cancel"],
                "changed": bool(
                    mutation_started
                    or any(item.changed for item in target_mutations)
                    or changed_competitors
                ),
                "migrated_rules": migrated,
                "skipped_ambiguous_rules": (
                    ambiguous
                    if any(
                        item["decision"] == "skip_ambiguous_rules"
                        for item in accepted
                    )
                    else []
                ),
                "skipped_failed_rules": skipped_failed_rules,
                "target_mutations": [item.to_dict() for item in target_mutations],
                "lifecycle": lifecycle_results,
                "rollback": rollback,
            },
            details={"reason": str(exc)[:1200]},
        )
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def install_backend(
    server: dict,
    name: str,
    *,
    confirm_switch: bool = False,
    continuation: Optional[dict] = None,
) -> OpResult:
    """Установить/активировать backend либо делегировать безопасную миграцию."""
    try:
        name = _backend_name(name)
        ssh_port = _port(server.get("port") or 22)
    except ValueError as exc:
        return OpResult(
            ok=False,
            message="Параметры установки firewall некорректны",
            error="invalid_firewall_install_parameters",
            data={"phase": "validation", "changed": False},
            details={"reason": str(exc)[:1000]},
        )
    try:
        _validated_continuation(
            continuation,
            server=server,
            target=name,
        )
    except ValueError as exc:
        return _continuation_error(str(exc), name)

    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=20)
        try:
            active, _ = active_backends_on_ssh(ssh, server)
        except FirewallDetectionError as exc:
            selection_result = _nftables_chain_selection_result(
                ssh, server, name, str(exc)
            )
            if selection_result is not None:
                return selection_result
            raise
        if len(active) > 1:
            return OpResult(
                ok=False,
                message=(
                    "Обнаружено несколько активных firewall; установка остановлена "
                    "до изменений"
                ),
                error="ambiguous_active_firewalls",
                data={
                    "target": name,
                    "phase": "initial_scan",
                    "critical": True,
                    "actions": ["retry", "cancel"],
                    "backends": [backend.name for backend, _ in active],
                    "changed": False,
                },
            )
        if active and active[0][0].name == name:
            if continuation is not None:
                return _continuation_error(
                    "Target уже стал активным, поэтому продолжение устарело",
                    name,
                )
            # Повторная установка после автопровижининга могла пройти мимо
            # finalize (первая попытка оборвалась после создания таблицы) —
            # синхроним persistence безусловно, предупреждение не фатально.
            persistence_warning = None
            if name == "nftables":
                finalized = _finalize_nftables_persistence(ssh, server)
                if finalized is not None and not finalized[0]:
                    persistence_warning = finalized[1]
            message = f"{name} уже активен"
            if persistence_warning:
                message = f"{message}. Внимание: {persistence_warning}"
            return OpResult(
                ok=True,
                message=message,
                data={
                    "backend": name,
                    "phase": "complete",
                    "changed": False,
                    "nftables_persistence_warning": persistence_warning,
                },
            )
        if active:
            current = active[0][1]
            source = active[0][0].name
            if not confirm_switch:
                return OpResult(
                    ok=False,
                    message=(
                        f"Установить и активировать {name}? Сейчас активен {source}. "
                        f"Bot4VPS установит {name}, перенесёт доступные правила, "
                        "разрешит текущий SSH-порт, проверит target и реальное SSH-"
                        "подключение и только затем отключит текущий firewall."
                    ),
                    error="firewall_switch_confirmation_required",
                    data={
                        "source": source,
                        "source_label": str(current.label or source)[:120],
                        "target": name,
                        "phase": "confirmation",
                        "confirmation_required": True,
                        "actions": ["confirm", "cancel"],
                        "changed": False,
                    },
                )
            try:
                ssh.close()
            except Exception:
                pass
            ssh = None
            return migrate(
                server,
                name,
                confirm=True,
                continuation=continuation,
            )

        if continuation is not None:
            return _continuation_error(
                "Исходный firewall больше не активен",
                name,
            )
        backend = _BY_NAME[name]
        ok, detail = backend.ensure_installed(ssh, server)
        if not ok:
            # Пакет мог только что установиться, а выбор nftables input
            # chain ещё не сделан — это не сбой установки, а штатный
            # шаг выбора chain для повторной попытки.
            selection_result = _nftables_chain_selection_result(
                ssh, server, name, str(detail)
            )
            if selection_result is not None:
                return selection_result
            return OpResult(
                ok=False,
                message=f"Не удалось установить и активировать {name}",
                error="target_preparation_failed",
                data={
                    "target": name,
                    "phase": "target_preparation",
                    "critical": True,
                    "actions": ["retry", "cancel"],
                    "changed": True,
                },
                details={"reason": str(detail)[:1000]},
            )
        info = backend.detect(ssh, server)
        if not info or info.active is not True or not info.manageable:
            return OpResult(
                ok=False,
                message=(
                    f"{name} подготовлен, но активное управляемое состояние "
                    "не подтверждено"
                ),
                error="target_verification_failed",
                data={
                    "target": name,
                    "phase": "target_verification",
                    "critical": True,
                    "actions": ["retry", "cancel"],
                    "changed": True,
                },
                details={
                    "reason": str(
                        info.reason or info.error
                        if info is not None
                        else "target firewall не обнаружен"
                    )[:1000],
                },
            )
        ssh_mutation = backend.open_port(
            ssh,
            server,
            ssh_port,
            "tcp",
            "",
        )
        if not ssh_mutation.ok or not ssh_mutation.verified:
            return OpResult(
                ok=False,
                message=(
                    f"{name} активирован, но обязательное правило текущего "
                    "SSH-порта не удалось применить и подтвердить"
                ),
                error="target_verification_failed",
                data={
                    "target": name,
                    "phase": "ssh_rule_operation",
                    "critical": True,
                    "actions": ["retry", "cancel"],
                    "changed": True,
                    "ssh_rule": ssh_mutation.to_dict(),
                },
                details={
                    "reason": str(
                        ssh_mutation.error
                        or ssh_mutation.message
                        or "SSH rule не подтверждён"
                    )[:1000],
                },
            )
        rules_ok, missing, rules_error = _verify_expected_rules(
            ssh,
            server,
            backend,
            {(ssh_port, "tcp", "")},
        )
        if not rules_ok:
            return OpResult(
                ok=False,
                message=(
                    f"{name} активирован, но правило текущего SSH-порта "
                    "не подтверждено"
                ),
                error="target_verification_failed",
                data={
                    "target": name,
                    "phase": "ssh_rule_verification",
                    "critical": True,
                    "actions": ["retry", "cancel"],
                    "changed": True,
                    "missing_rules": missing,
                },
                details={"reason": str(rules_error or missing)[:1000]},
            )
        ssh_ok, ssh_error = _verify_real_ssh(server)
        if not ssh_ok:
            return OpResult(
                ok=False,
                message=(
                    f"{name} активирован, но реальное SSH-подключение после "
                    "активации не подтверждено"
                ),
                error="ssh_verification_failed",
                data={
                    "target": name,
                    "phase": "ssh_verification",
                    "critical": True,
                    "actions": ["retry", "cancel"],
                    "changed": True,
                },
                details={"reason": str(ssh_error or "unknown")[:1000]},
            )
        final_detected = _verified_logical_scan_on_ssh(ssh, server)
        final_active = [
            detected_backend.name
            for detected_backend, detected_info in final_detected
            if detected_info.active is True
        ]
        if final_active != [name]:
            return OpResult(
                ok=False,
                message=(
                    f"{name} активирован, но итоговое состояние единственного "
                    "активного firewall не подтверждено"
                ),
                error="target_verification_failed",
                data={
                    "target": name,
                    "phase": "final_scan",
                    "critical": True,
                    "actions": ["retry", "cancel"],
                    "changed": True,
                    "backends": _candidates_payload(_candidates(final_detected)),
                },
            )
        persistence_warning = None
        if name == "nftables":
            finalized = _finalize_nftables_persistence(ssh, server)
            if finalized is not None and not finalized[0]:
                persistence_warning = (
                    "правила не сохранены для загрузки при ребуте: "
                    f"{finalized[1]}"
                )
        if persistence_warning:
            detail = f"{detail}. Внимание: {persistence_warning}"
        return OpResult(
            ok=True,
            message=detail,
            data={
                "backend": info.backend,
                "active": info.active,
                "label": info.label,
                "phase": "complete",
                "changed": True,
                "ssh_verified": True,
                "nftables_persistence_warning": persistence_warning,
                "backends": _candidates_payload(_candidates(final_detected)),
            },
        )
    except Exception as exc:
        return OpResult(
            ok=False,
            message=(
                "Установка firewall остановлена; повторите после обновления "
                "состояния сервера"
            ),
            error="firewall_install_failed",
            data={
                "target": name,
                "phase": "installation",
                "critical": True,
                "actions": ["retry", "cancel"],
            },
            details={"reason": str(exc)[:1200]},
        )
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass

def _single_mutation_error(
    port: int,
    protocol: str,
    operation: str,
    message: str,
    error: str,
) -> FirewallMutation:
    return FirewallMutation(
        None,
        port,
        protocol,
        operation,
        False,
        message=message,
        error=error[:1200],
    )


def open_port_on_ssh(
    ssh,
    server: dict,
    port: int,
    protocol: str = "tcp",
    source: str = "",
    *,
    acknowledge_firewall_conflict: bool = False,
):
    port = _port(port)
    protocol = _protocol(protocol)
    source = _source(source)
    try:
        active, _ = active_backends_on_ssh(ssh, server)
    except FirewallDetectionError as exc:
        return _single_mutation_error(
            port,
            protocol,
            "open",
            "Состояние firewall не определено; изменение остановлено",
            str(exc),
        )
    if not active:
        return _single_mutation_error(
            port, protocol, "open", "Активный firewall не обнаружен", "no_active_firewall"
        )
    if len(active) > 1 and not acknowledge_firewall_conflict:
        names = ", ".join(backend.name for backend, _ in active)
        return _single_mutation_error(
            port,
            protocol,
            "open",
            "Обнаружено несколько активных firewall; требуется явное подтверждение",
            f"ambiguous_active_firewalls: {names}",
        )
    mutations: list[FirewallMutation] = []
    for backend, _ in active:
        mutation = backend.open_port(ssh, server, port, protocol, source)
        mutations.append(mutation)
        if not mutation.ok or not mutation.verified:
            break
    if len(mutations) == 1 and len(active) == 1:
        return mutations[0]
    complete = len(mutations) == len(active)
    ok = complete and all(item.ok and item.verified for item in mutations)
    cleanup_results: list[dict] = []
    if not ok:
        for item in reversed(mutations):
            if item.ok and item.verified and item.changed and not item.existed_before:
                cleanup = _cleanup_exact_mutation(ssh, server, item)
                if cleanup is not None:
                    cleanup_results.append(cleanup)
    errors = "; ".join(
        f"{item.backend}: {item.error or item.message}"
        for item in mutations
        if not item.ok or not item.verified
    )
    result = FirewallBatchMutation(
        operation="open",
        port=port,
        protocol=protocol,
        mutations=mutations,
        ok=ok,
        message=(
            f"Порт {port}/{protocol} открыт во всех активных firewall"
            if ok
            else "Порт открыт не во всех активных firewall"
        ),
        error=errors or (None if ok else "incomplete_firewall_open"),
    )
    result.cleanup = cleanup_results
    return result


def preflight_close_port_on_ssh(
    ssh,
    server: dict,
    port: int,
    protocol: str = "tcp",
    source: str = "",
    *,
    protect_current_ssh: bool = True,
    acknowledge_firewall_conflict: bool = False,
):
    port = _port(port)
    protocol = _protocol(protocol)
    source = _source(source)
    current_ssh_port = _port(server.get("port") or 22)
    if protect_current_ssh and protocol in {"tcp", "any"} and port == current_ssh_port:
        return _single_mutation_error(
            port,
            protocol,
            "preflight_close",
            f"Нельзя закрыть текущий SSH-порт ({current_ssh_port})",
            "ssh_port_protected",
        )
    try:
        active, _ = active_backends_on_ssh(ssh, server)
    except FirewallDetectionError as exc:
        return _single_mutation_error(
            port,
            protocol,
            "preflight_close",
            "Состояние firewall не определено; проверка остановлена",
            str(exc),
        )
    if not active:
        return FirewallMutation(
            None,
            port,
            protocol,
            "preflight_close",
            True,
            verified=True,
            message="Активный firewall отсутствует; закрывать правило не требуется",
        )
    if len(active) > 1 and not acknowledge_firewall_conflict:
        names = ", ".join(backend.name for backend, _ in active)
        return _single_mutation_error(
            port,
            protocol,
            "preflight_close",
            "Обнаружено несколько активных firewall; требуется явное подтверждение",
            f"ambiguous_active_firewalls: {names}",
        )
    mutations = [
        backend.preflight_close_port(ssh, server, port, protocol, source)
        for backend, _ in active
    ]
    if len(mutations) == 1:
        return mutations[0]
    ok = all(item.ok and item.verified for item in mutations)
    errors = "; ".join(
        f"{item.backend}: {item.error or item.message}"
        for item in mutations
        if not item.ok or not item.verified
    )
    return FirewallBatchMutation(
        operation="preflight_close",
        port=port,
        protocol=protocol,
        mutations=mutations,
        ok=ok,
        message=(
            "Точное закрытие подтверждено во всех активных firewall"
            if ok
            else "Не во всех активных firewall порт можно закрыть безопасно"
        ),
        error=errors or None,
    )


def close_port_on_ssh(
    ssh,
    server: dict,
    port: int,
    protocol: str = "tcp",
    source: str = "",
    *,
    protect_current_ssh: bool = True,
    acknowledge_firewall_conflict: bool = False,
):
    port = _port(port)
    protocol = _protocol(protocol)
    source = _source(source)
    try:
        active_before, _ = active_backends_on_ssh(ssh, server)
    except FirewallDetectionError as exc:
        return _single_mutation_error(
            port,
            protocol,
            "close",
            "Состояние firewall изменилось; закрытие остановлено",
            str(exc),
        )
    names_before = tuple(sorted(backend.name for backend, _ in active_before))
    preflight = preflight_close_port_on_ssh(
        ssh,
        server,
        port,
        protocol,
        source,
        protect_current_ssh=protect_current_ssh,
        acknowledge_firewall_conflict=acknowledge_firewall_conflict,
    )
    if not preflight.ok or not preflight.verified:
        return preflight
    try:
        active, _ = active_backends_on_ssh(ssh, server)
    except FirewallDetectionError as exc:
        return _single_mutation_error(
            port,
            protocol,
            "close",
            "Состояние firewall изменилось; закрытие остановлено",
            str(exc),
        )
    names_after = tuple(sorted(backend.name for backend, _ in active))
    if names_after != names_before:
        return _single_mutation_error(
            port,
            protocol,
            "close",
            "Набор активных firewall изменился после проверки; закрытие остановлено",
            "firewall_backend_set_changed",
        )
    if not active:
        return FirewallMutation(
            None,
            port,
            protocol,
            "close",
            True,
            verified=True,
            message="Активный firewall отсутствует; закрывать правило не требуется",
        )
    if len(active) > 1 and not acknowledge_firewall_conflict:
        names = ", ".join(backend.name for backend, _ in active)
        return _single_mutation_error(
            port,
            protocol,
            "close",
            "Обнаружено несколько активных firewall; требуется явное подтверждение",
            f"ambiguous_active_firewalls: {names}",
        )
    mutations = [
        backend.close_port(ssh, server, port, protocol, source)
        for backend, _ in active
    ]
    if len(mutations) == 1:
        return mutations[0]
    ok = all(item.ok and item.verified for item in mutations)
    errors = "; ".join(
        f"{item.backend}: {item.error or item.message}"
        for item in mutations
        if not item.ok or not item.verified
    )
    return FirewallBatchMutation(
        operation="close",
        port=port,
        protocol=protocol,
        mutations=mutations,
        ok=ok,
        message=(
            f"Порт {port}/{protocol} закрыт во всех активных firewall"
            if ok
            else "Порт закрыт не во всех активных firewall"
        ),
        error=errors or None,
    )


def cleanup_mutation_on_ssh(ssh, server: dict, mutation: FirewallMutation) -> FirewallMutation:
    """Откатить только точное правило, зафиксированное token мутации."""
    if not isinstance(mutation, FirewallMutation):
        raise TypeError("Некорректный token firewall-операции")
    backend = _BY_NAME.get(str(mutation.backend or ""))
    if backend is None:
        return FirewallMutation(
            mutation.backend,
            mutation.port,
            mutation.protocol,
            "cleanup",
            False,
            message="Backend правила неизвестен; правило не удалено",
            error="unknown_mutation_backend",
        )
    if not mutation.changed or mutation.existed_before:
        return FirewallMutation(
            mutation.backend,
            mutation.port,
            mutation.protocol,
            "cleanup",
            False,
            message="Правило существовало ранее или не было новым точным изменением и не удалено",
            error="cleanup_refused_not_exact_change",
        )
    return backend.cleanup_mutation(ssh, server, mutation)


def _mutation_result(ssh, server: dict, mutation) -> OpResult:
    if isinstance(mutation, FirewallBatchMutation):
        return OpResult(
            ok=mutation.ok,
            message=mutation.message,
            error=mutation.error,
            data={"mutation": mutation.to_dict(), "backend": None, "rules": []},
        )
    data = {"mutation": mutation.to_dict(), "backend": mutation.backend, "rules": []}
    if mutation.backend in _BY_NAME:
        try:
            rules = _BY_NAME[mutation.backend].list_rules(ssh, server)
            data["rules"] = [_rule_dict(rule) for rule in rules]
        except Exception as exc:
            if mutation.ok:
                mutation.ok = False
                mutation.verified = False
                mutation.error = f"Не удалось перечитать правила: {str(exc)[:500]}"
                mutation.message = "Изменение firewall не подтверждено"
                data["mutation"] = mutation.to_dict()
    return OpResult(ok=mutation.ok, message=mutation.message, error=mutation.error, data=data)


def open_port(
    server: dict,
    port: int,
    protocol: str = "tcp",
    source: str = "",
    *,
    acknowledge_firewall_conflict: bool = False,
) -> OpResult:
    try:
        port = _port(port)
        protocol = _protocol(protocol)
        source = _source(source)
    except ValueError as exc:
        return OpResult(ok=False, message=str(exc), error="bad_firewall_rule")
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=12)
        return _mutation_result(
            ssh,
            server,
            open_port_on_ssh(
                ssh,
                server,
                port,
                protocol,
                source,
                acknowledge_firewall_conflict=acknowledge_firewall_conflict,
            ),
        )
    except Exception as exc:
        return OpResult(ok=False, message="Не удалось открыть порт", error=str(exc)[:1200])
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def close_port(
    server: dict,
    port: int,
    protocol: str = "tcp",
    source: str = "",
    *,
    acknowledge_firewall_conflict: bool = False,
) -> OpResult:
    try:
        port = _port(port)
        protocol = _protocol(protocol)
        source = _source(source)
    except ValueError as exc:
        return OpResult(ok=False, message=str(exc), error="bad_firewall_rule")
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=12)
        mutation = close_port_on_ssh(
            ssh,
            server,
            port,
            protocol,
            source,
            acknowledge_firewall_conflict=acknowledge_firewall_conflict,
        )
        return _mutation_result(ssh, server, mutation)
    except Exception as exc:
        return OpResult(ok=False, message="Не удалось закрыть порт", error=str(exc)[:1200])
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def disable(server: dict) -> OpResult:
    """Отключить единственный активный логический firewall.

    Семантика backend-ов сохраняется: deactivate() только отключает
    фильтрацию (правила/конфигурация не удаляются), затем отключение
    подтверждается свежей проверкой и финальным scan-ом.
    """
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=12)
        try:
            active, candidates = active_backends_on_ssh(ssh, server)
        except FirewallDetectionError as exc:
            return OpResult(
                ok=False,
                message="Состояние firewall не определено; отключение остановлено",
                error=str(exc)[:1200],
                data={"phase": "initial_scan", "changed": False},
            )
        if not active:
            return OpResult(
                ok=True,
                message="Активный firewall не обнаружен; отключение не требуется",
                data={
                    "phase": "complete",
                    "changed": False,
                    "backends": _candidates_payload(candidates),
                },
            )
        if len(active) > 1:
            names = ", ".join(backend.name for backend, _ in active)
            return OpResult(
                ok=False,
                message="Обнаружено несколько активных firewall; отключение остановлено",
                error="ambiguous_active_firewalls",
                data={
                    "phase": "initial_scan",
                    "changed": False,
                    "backends": _candidates_payload(candidates),
                    "backends_active": [backend.name for backend, _ in active],
                },
                details={"active": names[:500]},
            )
        backend, info = active[0]
        source = backend.name
        source_label = str(info.label or source)[:120]
        change = backend.deactivate(ssh, server)
        if not change.ok:
            return OpResult(
                ok=False,
                message=f"{source_label} не отключён",
                error="firewall_disable_failed",
                data={
                    "backend": source,
                    "phase": "deactivate",
                    "changed": bool(change.changed),
                    "state_change": change.to_dict(),
                },
            )
        verify_error = None
        try:
            inactive = backend.verify_inactive(ssh, server)
        except Exception as exc:
            inactive = False
            verify_error = str(exc)[:800]
        if not inactive:
            return OpResult(
                ok=False,
                message=f"{source_label} отключён, но неактивность не подтверждена",
                error="firewall_disable_unverified",
                data={
                    "backend": source,
                    "phase": "verification",
                    "changed": bool(change.changed),
                    "state_change": change.to_dict(),
                },
                details={"reason": verify_error or "Состояние firewall после отключения не подтверждено"},
            )
        try:
            final_detected = _verified_logical_scan_on_ssh(ssh, server)
        except FirewallDetectionError as exc:
            return OpResult(
                ok=False,
                message=f"{source_label} отключён, но итоговое состояние не подтверждено",
                error=str(exc)[:1200],
                data={
                    "backend": source,
                    "phase": "final_scan",
                    "changed": bool(change.changed),
                    "state_change": change.to_dict(),
                },
            )
        final_active = [
            detected_backend.name
            for detected_backend, detected_info in final_detected
            if detected_info.active is True
        ]
        if final_active:
            return OpResult(
                ok=False,
                message=(
                    f"{source_label} отключён, но остался активный firewall: "
                    f"{', '.join(final_active)}"
                ),
                error="active_firewall_remains",
                data={
                    "backend": source,
                    "phase": "final_scan",
                    "changed": bool(change.changed),
                    "state_change": change.to_dict(),
                    "backends": _candidates_payload(_candidates(final_detected)),
                    "backends_active": final_active,
                },
            )
        return OpResult(
            ok=True,
            message=change.message or f"{source_label} отключён",
            data={
                "backend": source,
                "phase": "complete",
                "changed": bool(change.changed),
                "state_change": change.to_dict(),
                "backends": _candidates_payload(_candidates(final_detected)),
            },
        )
    except Exception as exc:
        return OpResult(
            ok=False,
            message="Не удалось отключить firewall",
            error=str(exc)[:1200],
            data={"phase": "deactivate", "changed": False},
        )
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def enable(server: dict, name: str) -> OpResult:
    """Включить установленный, но неактивный firewall (без миграции).

    Прямое включение доступно только когда ни один firewall не активен
    (например, после «Отключить firewall»). При активном другом backend
    для смены используется переключение (switch с переносом правил).
    """
    try:
        backend = _BY_NAME[_backend_name(name)]
    except ValueError as exc:
        return OpResult(
            ok=False,
            message="Параметры включения firewall некорректны",
            error="invalid_firewall_enable_parameters",
            data={"phase": "validation", "changed": False},
            details={"reason": str(exc)[:1000]},
        )
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=12)
        try:
            active, candidates = active_backends_on_ssh(ssh, server)
        except FirewallDetectionError as exc:
            selection_result = _nftables_chain_selection_result(
                ssh, server, backend.name, str(exc), action="включение"
            )
            if selection_result is not None:
                return selection_result
            return OpResult(
                ok=False,
                message="Состояние firewall не определено; включение остановлено",
                error=str(exc)[:1200],
                data={"phase": "initial_scan", "changed": False},
            )
        if any(item[0].name == backend.name for item in active):
            return OpResult(
                ok=True,
                message=f"{backend.name} уже активен",
                data={
                    "backend": backend.name,
                    "phase": "complete",
                    "changed": False,
                    "backends": _candidates_payload(candidates),
                },
            )
        if active:
            current = active[0][0].name
            return OpResult(
                ok=False,
                message=(
                    f"Активен другой firewall ({current}); для смены "
                    "используйте переключение"
                ),
                error="firewall_enable_conflict",
                data={
                    "backend": backend.name,
                    "phase": "initial_scan",
                    "changed": False,
                    "backends": _candidates_payload(candidates),
                    "active_backend": current,
                },
            )
        if backend.name not in {
            str(item.get("backend") or "") for item in candidates
        }:
            return OpResult(
                ok=False,
                message=(
                    f"{backend.name} не установлен; используйте установку "
                    "и активацию"
                ),
                error="firewall_enable_not_installed",
                data={
                    "backend": backend.name,
                    "phase": "initial_scan",
                    "changed": False,
                    "backends": _candidates_payload(candidates),
                },
            )
        change = backend.activate(ssh, server)
        if not change.ok:
            return OpResult(
                ok=False,
                message=f"{backend.name} не включён",
                error="firewall_enable_failed",
                data={
                    "backend": backend.name,
                    "phase": "activate",
                    "changed": bool(change.changed),
                    "state_change": change.to_dict(),
                },
                details={"reason": (change.error or "")[:1000]},
            )
        verified = backend.detect(ssh, server)
        if verified is None or verified.active is not True:
            return OpResult(
                ok=False,
                message=(
                    f"{backend.name} включён, но активное состояние "
                    "не подтверждено"
                ),
                error="firewall_enable_unverified",
                data={
                    "backend": backend.name,
                    "phase": "verification",
                    "changed": bool(change.changed),
                    "state_change": change.to_dict(),
                },
            )
        try:
            final_detected = _verified_logical_scan_on_ssh(ssh, server)
        except FirewallDetectionError as exc:
            return OpResult(
                ok=False,
                message=(
                    f"{backend.name} включён, но итоговое состояние "
                    "не подтверждено"
                ),
                error=str(exc)[:1200],
                data={
                    "backend": backend.name,
                    "phase": "final_scan",
                    "changed": bool(change.changed),
                    "state_change": change.to_dict(),
                },
            )
        final_active = [
            detected_backend.name
            for detected_backend, detected_info in final_detected
            if detected_info.active is True
        ]
        if final_active != [backend.name]:
            return OpResult(
                ok=False,
                message=(
                    f"{backend.name} включён, но итоговое состояние "
                    "не подтверждено"
                ),
                error="active_firewall_mismatch",
                data={
                    "backend": backend.name,
                    "phase": "final_scan",
                    "changed": bool(change.changed),
                    "state_change": change.to_dict(),
                    "backends": _candidates_payload(_candidates(final_detected)),
                    "backends_active": final_active,
                },
            )
        return OpResult(
            ok=True,
            message=change.message or f"{backend.name} включён",
            data={
                "backend": backend.name,
                "phase": "complete",
                "changed": bool(change.changed),
                "state_change": change.to_dict(),
                "backends": _candidates_payload(_candidates(final_detected)),
            },
        )
    except Exception as exc:
        return OpResult(
            ok=False,
            message="Не удалось включить firewall",
            error=str(exc)[:1200],
            data={"phase": "activate", "changed": False},
        )
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def remove(server: dict, name: str) -> OpResult:
    """Удалить установленный firewall: пакет, без purge.

    Активный firewall сначала отключается (существующий deactivate из
    Ч3); неактивность и отсутствие других активных firewall
    подтверждаются ДО удаления пакета. Удаление пакета не равно
    удалению ruleset: правила nftables, уже загруженные в kernel,
    не удалялись и остаются до перезагрузки сервера.
    """
    try:
        backend = _BY_NAME[_backend_name(name)]
    except ValueError as exc:
        return OpResult(
            ok=False,
            message="Параметры удаления firewall некорректны",
            error="invalid_firewall_remove_parameters",
            data={"phase": "validation", "changed": False},
            details={"reason": str(exc)[:1000]},
        )
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=20)
        try:
            active, candidates = active_backends_on_ssh(ssh, server)
        except FirewallDetectionError as exc:
            return OpResult(
                ok=False,
                message="Состояние firewall не определено; удаление остановлено",
                error=str(exc)[:1200],
                data={
                    "backend": backend.name,
                    "phase": "initial_scan",
                    "changed": False,
                },
            )
        installed = any(
            candidate.get("backend") == backend.name for candidate in candidates
        )
        if not installed:
            return OpResult(
                ok=True,
                message=f"{backend.name} не установлен; удаление не требуется",
                data={
                    "backend": backend.name,
                    "phase": "complete",
                    "changed": False,
                    "backends": _candidates_payload(candidates),
                },
            )
        target_active = any(item[0].name == backend.name for item in active)
        deactivated = False
        state_change: Optional[dict] = None
        if target_active:
            if len(active) > 1:
                names = ", ".join(item[0].name for item in active)
                return OpResult(
                    ok=False,
                    message=(
                        "Обнаружено несколько активных firewall; "
                        "удаление остановлено"
                    ),
                    error="ambiguous_active_firewalls",
                    data={
                        "backend": backend.name,
                        "phase": "initial_scan",
                        "changed": False,
                        "backends": _candidates_payload(candidates),
                        "backends_active": [item[0].name for item in active],
                    },
                    details={"active": names[:500]},
                )
            change = backend.deactivate(ssh, server)
            if not change.ok:
                return OpResult(
                    ok=False,
                    message=f"{backend.name} не отключён; удаление остановлено",
                    error="firewall_remove_deactivate_failed",
                    data={
                        "backend": backend.name,
                        "phase": "deactivate",
                        "changed": False,
                        "state_change": change.to_dict(),
                    },
                    details={"reason": change.error or change.message},
                )
            deactivated = True
            state_change = change.to_dict()
            verify_error = None
            try:
                inactive = backend.verify_inactive(ssh, server)
            except Exception as exc:
                inactive = False
                verify_error = str(exc)[:800]
            if not inactive:
                return OpResult(
                    ok=False,
                    message=(
                        f"{backend.name} отключён, но неактивность "
                        "не подтверждена; удаление остановлено"
                    ),
                    error="firewall_remove_deactivate_unverified",
                    data={
                        "backend": backend.name,
                        "phase": "verification",
                        "changed": True,
                        "deactivated": True,
                        "state_change": state_change,
                    },
                    details={
                        "reason": verify_error
                        or "Состояние firewall после отключения не подтверждено"
                    },
                )
            try:
                final_detected = _verified_logical_scan_on_ssh(ssh, server)
            except FirewallDetectionError as exc:
                return OpResult(
                    ok=False,
                    message=(
                        f"{backend.name} отключён, но итоговое состояние "
                        "не подтверждено; удаление остановлено"
                    ),
                    error=str(exc)[:1200],
                    data={
                        "backend": backend.name,
                        "phase": "final_scan",
                        "changed": True,
                        "deactivated": True,
                        "state_change": state_change,
                    },
                )
            remaining = [
                detected_backend.name
                for detected_backend, detected_info in final_detected
                if detected_info.active is True
            ]
            if remaining:
                return OpResult(
                    ok=False,
                    message=(
                        f"{backend.name} отключён, но остался активный "
                        f"firewall: {', '.join(remaining)}; удаление остановлено"
                    ),
                    error="active_firewall_remains",
                    data={
                        "backend": backend.name,
                        "phase": "final_scan",
                        "changed": True,
                        "deactivated": True,
                        "state_change": state_change,
                        "backends": _candidates_payload(
                            _candidates(final_detected)
                        ),
                        "backends_active": remaining,
                    },
                )
        try:
            package_manager = detect_package_manager(ssh, server)
        except RuntimeError as exc:
            return OpResult(
                ok=False,
                message="Не удалось определить package manager; удаление остановлено",
                error="package_manager_unknown",
                data={
                    "backend": backend.name,
                    "phase": "remove",
                    "changed": False,
                    "deactivated": deactivated,
                },
                details={"reason": str(exc)[:800]},
            )
        removed, detail = package_manager.remove(ssh, server, backend.name)
        if not removed:
            return OpResult(
                ok=False,
                message=f"Не удалось удалить {backend.name}",
                error="firewall_remove_failed",
                data={
                    "backend": backend.name,
                    "phase": "remove",
                    "changed": False,
                    "deactivated": deactivated,
                    "state_change": state_change,
                },
                details={"reason": str(detail)[:800]},
            )
        if backend.detect(ssh, server) is not None:
            return OpResult(
                ok=False,
                message=f"{backend.name} удалён, но по-прежнему обнаружен на сервере",
                error="firewall_remove_unverified",
                data={
                    "backend": backend.name,
                    "phase": "verify_removed",
                    "changed": True,
                    "deactivated": deactivated,
                },
            )
        message = f"{backend.name} удалён; конфигурация сохранена (без purge)"
        data = {
            "backend": backend.name,
            "phase": "complete",
            "changed": True,
            "deactivated": deactivated,
        }
        if state_change is not None:
            data["state_change"] = state_change
        if backend.name == "nftables":
            data["kernel_rules_remain"] = True
            message = (
                "nftables удалён. Правила, загруженные в kernel, не удалялись "
                "и остаются до перезагрузки сервера"
            )
        return OpResult(ok=True, message=message, data=data)
    except Exception as exc:
        return OpResult(
            ok=False,
            message="Не удалось удалить firewall",
            error=str(exc)[:1200],
            data={"phase": "remove", "changed": False},
        )
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def list_rules(server: dict) -> OpResult:
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=12)
        try:
            backend, info = _active_backend_on_ssh(ssh, server)
        except FirewallDetectionError as exc:
            return OpResult(
                ok=False,
                message="Не удалось безопасно определить firewall",
                error=str(exc)[:1200],
                data={"backend": None, "rules": []},
            )
        if backend is None or info.active is not True:
            return OpResult(
                ok=True,
                message=info.label,
                data={
                    "backend": info.backend,
                    "active": info.active,
                    "label": info.label,
                    "rules": [],
                },
            )
        rules = backend.list_rules(ssh, server)
        return OpResult(
            ok=True,
            message=info.label,
            data={
                "backend": info.backend,
                "active": info.active,
                "label": info.label,
                "rules": [_rule_dict(rule) for rule in rules],
            },
        )
    except Exception as exc:
        return OpResult(ok=False, message="Не удалось прочитать правила firewall", error=str(exc)[:1200])
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def _rule_dict(rule: FirewallRule) -> dict:
    # В API отдаём только канонический IP/CIDR: служебные значения backend'ов
    # (метка цепочки, zone:) не предназначены для обратной отправки.
    source = normalize_source(rule.source)
    return {
        "port": str(rule.port)[:32],
        "protocol": str(rule.protocol)[:16],
        "action": str(rule.action)[:32],
        "direction": str(rule.direction)[:16],
        "raw": str(rule.raw or "")[:500],
        "handle": str(rule.handle)[:40] if rule.handle is not None else None,
        "source": source or "",
    }
