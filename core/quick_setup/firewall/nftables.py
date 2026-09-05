# -*- coding: utf-8 -*-
"""nftables backend с обнаружением фактической input base chain."""
from __future__ import annotations

import json
import re
import shlex
from typing import Any, Optional

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

_BYPASS_COMMENT = "Bot4VPS firewall switch bypass"


class NftablesBackend(FirewallBackend):
    name = "nftables"

    def detect(self, ssh, server: dict) -> Optional[FirewallInfo]:
        code, out, _ = exec_sudo(
            ssh, server, "command -v nft >/dev/null && echo yes || echo no", timeout=15
        )
        if code != 0 or "yes" not in (out or ""):
            return None
        snapshot = self._ruleset(ssh, server)
        classified = self._classified_input_chains(snapshot)
        chains, truncated = self._selection_candidates(classified)
        configured, token = self._configured_chain_token(server)
        if configured:
            selected = self._chain_from_snapshot(snapshot, token)
            if selected is None:
                return FirewallInfo(
                    backend=self.name,
                    active=None,
                    label="nftables (требуется выбор chain)",
                    rules=[],
                    manageable=False,
                    reason=(
                        "Сохранённая nftables input chain исчезла или больше "
                        "не является standalone input base chain; требуется выбор"
                    ),
                    nftables_chains=chains,
                    nftables_chain_selection_required=True,
                    nftables_chains_truncated=truncated,
                )
            active = not (
                selected["rules"]
                and self._unconditional_accept(selected["rules"][0])
            )
            return FirewallInfo(
                backend=self.name,
                active=active,
                label="nftables" if active else "nftables (неактивен)",
                rules=self._exact_rules(selected),
                nftables_chains=chains,
                nftables_selected_chain=self._chain_token(selected),
                nftables_chains_truncated=truncated,
            )

        if any(
            item["classification"] == "ambiguous"
            for item in classified
        ):
            return FirewallInfo(
                backend=self.name,
                active=None,
                label="nftables (структура неоднозначна)",
                rules=[],
                manageable=False,
                reason=(
                    "Структура nftables input chains неоднозначна; "
                    "автоматический выбор остановлен"
                ),
                nftables_chains=chains,
                nftables_chain_selection_required=bool(chains),
                nftables_chains_truncated=truncated,
            )
        selectable = [
            item["raw"] for item in classified
            if item["classification"] == "selectable"
        ]
        if not selectable:
            return FirewallInfo(
                backend=self.name,
                active=False,
                label="nftables (неактивен)",
                rules=[],
                nftables_chains=chains,
                nftables_chains_truncated=truncated,
            )
        active = any(
            not (
                chain["rules"]
                and self._unconditional_accept(chain["rules"][0])
            )
            for chain in selectable
        )
        if len(selectable) > 1:
            return FirewallInfo(
                backend=self.name,
                active=active,
                label="nftables" if active else "nftables (неактивен)",
                rules=[],
                manageable=False,
                reason=(
                    "Обнаружено несколько standalone nftables input chains; "
                    "требуется выбор"
                ),
                nftables_chains=chains,
                nftables_chain_selection_required=True,
                nftables_chains_truncated=truncated,
            )

        chain = selectable[0]
        return FirewallInfo(
            backend=self.name,
            active=active,
            label="nftables" if active else "nftables (неактивен)",
            rules=self._exact_rules(chain),
            nftables_chains=chains,
            nftables_selected_chain=self._chain_token(chain),
            nftables_chains_truncated=truncated,
        )

    def ensure_installed(self, ssh, server: dict) -> tuple[bool, str]:
        code, out, _ = exec_sudo(
            ssh, server, "command -v nft >/dev/null && echo yes || echo no", timeout=15
        )
        if code != 0 or "yes" not in (out or ""):
            manager = detect_package_manager(ssh, server)
            ok, message = manager.install(ssh, server, "nftables")
            if not ok:
                return False, message
            code, out, _ = exec_sudo(
                ssh,
                server,
                "command -v nft >/dev/null && echo yes || echo no",
                timeout=15,
            )
            if code != 0 or "yes" not in (out or ""):
                return False, "nftables установлен, но команда nft недоступна"

        try:
            port = int(server.get("port") or 22)
        except (TypeError, ValueError):
            return False, "Текущий SSH-порт некорректен"
        if not 1 <= port <= 65535:
            return False, "Текущий SSH-порт некорректен"

        configured, token = self._configured_chain_token(server)
        if not configured:
            return False, (
                "Выберите существующую nftables input chain перед "
                "использованием nftables"
            )
        try:
            validated = self.validate_input_chain(ssh, server, token)
            chain = self._find_chain(ssh, server, validated)
        except (TypeError, ValueError, RuntimeError):
            return False, (
                "Выбранная nftables input chain не прошла свежую проверку; "
                "изменения остановлены"
            )
        if chain is None:
            return False, (
                "Выбранная nftables input chain изменилась во время подготовки; "
                "изменения остановлены"
            )

        bypasses = self._bypass_handles(chain)
        first_is_bypass = bool(chain["rules"] and self._bypass_rule(chain["rules"][0]))
        if bypasses and (len(bypasses) != 1 or not first_is_bypass):
            return False, (
                "Состояние nftables bypass в выбранной input chain неоднозначно; "
                "изменения остановлены"
            )
        if (
            chain["rules"]
            and self._unconditional_accept(chain["rules"][0])
            and not first_is_bypass
        ):
            return False, (
                "Выбранная nftables input chain не является активным firewall; "
                "изменения остановлены"
            )

        try:
            ssh_rule = self.open_port(ssh, server, port, "tcp")
        except Exception:
            return False, (
                "Не удалось безопасно открыть текущий SSH-порт в выбранной "
                "nftables input chain"
            )
        if not ssh_rule.ok or not ssh_rule.verified:
            return False, (
                ssh_rule.error
                or ssh_rule.message
                or "Allow текущего SSH-порта в nftables не подтверждён"
            )

        if first_is_bypass:
            refreshed = self._find_chain(ssh, server, validated)
            if refreshed is None:
                return False, "Выбранная nftables input chain исчезла во время подготовки"
            ok, detail = self._delete_bypass_handle(
                ssh,
                server,
                refreshed,
                bypasses[0],
            )
            if not ok:
                return False, detail

        if not self.verify_switch_target(ssh, server, port):
            return False, (
                "Активное состояние выбранной nftables input chain и allow SSH "
                "не подтверждены"
            )
        return True, (
            "nftables подготовлен на выбранной существующей input chain; "
            "текущий SSH-порт разрешён"
        )

    def verify_switch_target(self, ssh, server: dict, port: int) -> bool:
        try:
            port = int(port)
        except (TypeError, ValueError):
            return False
        if not 1 <= port <= 65535:
            return False
        configured, token = self._configured_chain_token(server)
        if not configured or not self._valid_chain_token(token):
            return False
        try:
            chain = self._chain_from_snapshot(self._ruleset(ssh, server), token)
        except Exception:
            return False
        if chain is None or (
            chain["rules"] and self._unconditional_accept(chain["rules"][0])
        ):
            return False
        return bool(self._matching(self._exact_rules(chain), port, "tcp"))

    def resolve_switch_source(self, ssh, server: dict) -> dict[str, str]:
        try:
            chain = self._resolve_chain(server, self._ruleset(ssh, server))
        except Exception as exc:
            raise RuntimeError(
                "Текущий nftables firewall нельзя безопасно отключить автоматически"
            ) from exc
        if (
            chain is None
            or not chain["rules"]
            or self._unconditional_accept(chain["rules"][0])
        ):
            raise RuntimeError(
                "Текущий nftables firewall нельзя безопасно отключить автоматически"
            )
        return self._chain_token(chain)

    def deactivate_exact(
        self,
        ssh,
        server: dict,
        token: dict[str, str],
    ) -> FirewallStateChange:
        try:
            chain = self._find_chain(ssh, server, token)
        except Exception:
            chain = None
        if chain is None or (
            chain["rules"] and self._unconditional_accept(chain["rules"][0])
        ):
            return FirewallStateChange(
                self.name,
                "deactivate",
                False,
                message="nftables source не отключён",
                error=(
                    "Текущий nftables firewall изменился; автоматическое "
                    "отключение остановлено"
                ),
                state={"chain": token, "handles": []},
            )
        return self._insert_bypass(ssh, server, chain)

    def deactivate(self, ssh, server: dict) -> FirewallStateChange:
        snapshot = self._ruleset(ssh, server)
        chain = self._resolve_chain(server, snapshot)
        if chain is None:
            return FirewallStateChange(
                self.name,
                "deactivate",
                True,
                verified=True,
                message="nftables input filtering уже неактивен",
                state={"chain": None, "handles": []},
            )
        if chain["rules"] and self._unconditional_accept(chain["rules"][0]):
            return FirewallStateChange(
                self.name,
                "deactivate",
                True,
                verified=True,
                message="nftables input filtering уже обойдён",
                state={"chain": self._chain_token(chain), "handles": []},
            )
        return self._insert_bypass(ssh, server, chain)

    def _insert_bypass(
        self,
        ssh,
        server: dict,
        chain: dict[str, Any],
    ) -> FirewallStateChange:
        before_handles = {
            int(rule["handle"])
            for rule in chain["rules"]
            if isinstance(rule.get("handle"), int)
        }
        chain_args = self._chain_args(chain)
        command = (
            f"nft insert rule {chain_args} counter accept comment "
            f"{shlex.quote(json.dumps(_BYPASS_COMMENT))}"
        )
        code, out, err = exec_sudo(ssh, server, command, timeout=20)
        refreshed = None
        if code == 0:
            try:
                refreshed = self._find_chain(
                    ssh,
                    server,
                    self._chain_token(chain),
                )
            except Exception:
                refreshed = None
        new_handles = []
        if refreshed is not None:
            new_handles = [
                int(rule["handle"])
                for rule in refreshed["rules"]
                if isinstance(rule.get("handle"), int)
                and int(rule["handle"]) not in before_handles
                and self._bypass_rule(rule)
            ]
        inactive = (
            code == 0
            and len(new_handles) == 1
            and bool(refreshed and refreshed["rules"])
            and self._bypass_rule(refreshed["rules"][0])
        )
        return FirewallStateChange(
            self.name,
            "deactivate",
            inactive,
            changed=bool(new_handles),
            verified=inactive,
            message=(
                "nftables input filtering обойдён; ruleset и сервис сохранены"
                if inactive
                else "Отключение nftables input filtering не подтверждено"
            ),
            error=(
                None
                if inactive
                else (
                    "Не удалось установить nftables bypass: "
                    f"{err or out or 'изменение не подтверждено'}"
                )[:800]
            ),
            state={"chain": self._chain_token(chain), "handles": new_handles},
        )

    def activate(self, ssh, server: dict) -> FirewallStateChange:
        """Включить nftables: убрать собственный bypass из input chain."""
        info = self.detect(ssh, server)
        if info is None:
            return FirewallStateChange(
                self.name,
                "activate",
                False,
                message="nftables не включён",
                error="nftables не установлен; включение невозможно",
                state={"active": False},
            )
        state = {"active": info.active is True}
        if info.active is True:
            return FirewallStateChange(
                self.name,
                "activate",
                True,
                verified=True,
                message="nftables уже активен",
                state=state,
            )
        if not info.manageable or info.nftables_chain_selection_required:
            return FirewallStateChange(
                self.name,
                "activate",
                False,
                message="nftables не включён",
                error=(
                    info.reason
                    or "Требуется выбор nftables input chain перед включением"
                ),
                state=state,
            )
        snapshot = self._ruleset(ssh, server)
        chain = self._resolve_chain(server, snapshot)
        if chain is None:
            return FirewallStateChange(
                self.name,
                "activate",
                False,
                message="nftables не включён",
                error="Не найдена nftables input chain; включать нечего",
                state=state,
            )
        bypasses = self._bypass_handles(chain)
        first_is_bypass = bool(
            chain["rules"] and self._bypass_rule(chain["rules"][0])
        )
        if bypasses and (len(bypasses) != 1 or not first_is_bypass):
            return FirewallStateChange(
                self.name,
                "activate",
                False,
                message="nftables не включён",
                error=(
                    "Состояние nftables bypass в input chain неоднозначно; "
                    "включение остановлено"
                ),
                state=state,
            )
        if not bypasses:
            # Неактивность без нашего bypass-правила — чужая конфигурация;
            # удалять чужие правила запрещено.
            return FirewallStateChange(
                self.name,
                "activate",
                False,
                message="nftables не включён",
                error=(
                    "В nftables input chain нет bypass-правила Bot4VPS; "
                    "включать нечего"
                ),
                state=state,
            )
        # Bypass пропускает весь трафик; перед его снятием нужно
        # гарантировать, что в chain разрешён текущий SSH-порт (в lifecycle
        # он мог быть утерян — например, установка прервалась до open_port).
        try:
            port = int(server.get("port") or 22)
        except (TypeError, ValueError):
            port = 22
        if not 1 <= port <= 65535:
            port = 22
        opened_ssh_port = False
        if not self._matching(self._exact_rules(chain), port, "tcp"):
            try:
                ssh_rule = self.open_port(ssh, server, port, "tcp")
            except Exception:
                ssh_rule = None
            if ssh_rule is None or not ssh_rule.ok or not ssh_rule.verified:
                detail = (
                    (ssh_rule.error or ssh_rule.message)
                    if ssh_rule is not None
                    else None
                )
                error = (
                    "Не удалось открыть текущий SSH-порт в выбранной "
                    "nftables input chain"
                )
                if detail:
                    error = f"{error}: {detail}"
                return FirewallStateChange(
                    self.name,
                    "activate",
                    False,
                    message="nftables не включён",
                    error=error[:800],
                    state=state,
                )
            opened_ssh_port = True
        code, out, err = exec_sudo(
            ssh,
            server,
            f"nft delete rule {self._chain_args(chain)} handle {bypasses[0]}",
            timeout=20,
        )
        if code != 0:
            return FirewallStateChange(
                self.name,
                "activate",
                False,
                message="nftables не включён",
                error=(err or out or "nft delete rule failed")[:800],
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
                (
                    "nftables input filtering включён"
                    + (f"; SSH-порт {port}/tcp разрешён" if opened_ssh_port else "")
                )
                if active_now
                else "Включение nftables не подтверждено"
            ),
            error=None if active_now else "nftables activate unverified",
            state=state,
        )

    def restore(
        self,
        ssh,
        server: dict,
        state: dict[str, Any],
    ) -> FirewallStateChange:
        token = state.get("chain")
        handles = state.get("handles")
        if token is None and handles == []:
            return FirewallStateChange(
                self.name,
                "restore",
                True,
                verified=True,
                message="Восстановление nftables не требуется",
            )
        if not self._valid_chain_token(token) or not isinstance(handles, list):
            return FirewallStateChange(
                self.name,
                "restore",
                False,
                message="nftables не восстановлен",
                error="missing_exact_nftables_state",
            )
        errors: list[str] = []
        changed = False
        for value in handles:
            if not isinstance(value, int) or value < 0:
                errors.append("invalid_bypass_handle")
                continue
            chain = self._find_chain(ssh, server, token)
            if chain is None:
                errors.append("nftables_chain_changed")
                continue
            ok, detail = self._delete_bypass_handle(ssh, server, chain, value)
            changed = changed or ok
            if not ok:
                errors.append(detail)
        chain = self._find_chain(ssh, server, token)
        restored = bool(
            not errors
            and chain is not None
            and not (chain["rules"] and self._unconditional_accept(chain["rules"][0]))
        )
        return FirewallStateChange(
            self.name,
            "restore",
            restored,
            changed=changed,
            verified=restored,
            message="Исходное nftables input filtering восстановлено" if restored else "nftables восстановлен не полностью",
            error=None if restored else "; ".join(errors or ["nftables restore failed"])[:800],
        )

    def migration_rules(
        self,
        ssh,
        server: dict,
    ) -> tuple[list[FirewallRule], list[str]]:
        chain = self._selected_chain(ssh, server)
        if chain is None:
            return [], []
        # Переносятся tcp/udp/ANY правила без источника и с IPv4-источником.
        # IPv6-источники не переносятся: целевая цепочка может иметь family ip.
        exact = [
            rule
            for rule in self._exact_rules(chain)
            if rule.protocol in {"tcp", "udp", "any"}
            and (
                not is_ip_source(rule.source)
                or source_ip_version(rule.source) == 4
            )
        ]
        exact_handles = {rule.handle for rule in exact}
        ambiguous: list[str] = []
        for rule in chain["rules"]:
            handle = str(rule.get("handle")) if rule.get("handle") is not None else None
            if handle in exact_handles or self._boilerplate_rule(rule) or self._bypass_rule(rule):
                continue
            ambiguous.append(self._migration_rule_label(rule))
        return exact, ambiguous

    @classmethod
    def _migration_rule_label(cls, rule: dict[str, Any]) -> str:
        """Человекочитаемое описание неоднозначного правила (как в списке правил).

        Правила с точной интерпретацией показываются нормализованно
        (port/protocol · allow · source); raw nft JSON остаётся только
        для правил без однозначного разбора.
        """
        parsed = cls._exact_allow(rule)
        if parsed is None:
            return cls._rule_description(rule)
        protocol, port, source = parsed
        label = f"{port}/{protocol} · allow"
        if source:
            label += f" · {source}"
        handle = rule.get("handle")
        if isinstance(handle, int):
            label += f" # handle {handle}"
        return label

    def open_port(
        self,
        ssh,
        server: dict,
        port: int,
        protocol: str,
        source: str = "",
    ) -> FirewallMutation:
        chain = self._selected_chain(ssh, server)
        if chain is None:
            return FirewallMutation(
                self.name,
                port,
                protocol,
                "open",
                False,
                message="Однозначная nftables input chain не найдена",
                error="inactive_or_ambiguous_nftables",
            )
        mismatch = self._source_family_mismatch(chain, port, protocol, source)
        if mismatch:
            return mismatch
        before = self._matching(self._exact_rules(chain), port, protocol, source)
        if before:
            if len(before) != 1 or not str(before[0].handle or "").isdigit():
                return FirewallMutation(
                    self.name,
                    port,
                    protocol,
                    "open",
                    False,
                    existed_before=True,
                    message="Существующее правило nftables неоднозначно",
                    error="ambiguous_exact_rule",
                )
            return FirewallMutation(
                self.name,
                port,
                protocol,
                "open",
                True,
                existed_before=True,
                verified=True,
                message=f"Порт {port}/{protocol} уже открыт",
                token={
                    **self._chain_token(chain),
                    "handle": before[0].handle,
                    "source": source,
                },
            )
        # Ограничение источника пишется префиксом ip/ip6 saddr (family chain
        # проверена выше): в inet-цепочке допустимы оба квалификатора.
        saddr_prefix = ""
        if source:
            saddr_prefix = (
                f"{'ip' if source_ip_version(source) == 4 else 'ip6'} "
                f"saddr {source} "
            )
        code, out, err = exec_sudo(
            ssh,
            server,
            (
                f"nft add rule {self._chain_args(chain)} "
                + saddr_prefix
                + (
                    f"meta l4proto {{ tcp, udp }} th dport {port} accept"
                    if protocol == "any"
                    else f"{protocol} dport {port} accept"
                )
            ),
            timeout=20,
        )
        refreshed = self._find_chain(ssh, server, self._chain_token(chain)) if code == 0 else None
        after = self._matching(self._exact_rules(refreshed), port, protocol, source) if refreshed else []
        created = after[0] if len(after) == 1 and str(after[0].handle or "").isdigit() else None
        verified = code == 0 and created is not None
        return FirewallMutation(
            self.name,
            port,
            protocol,
            "open",
            verified,
            changed=created is not None,
            existed_before=False,
            verified=verified,
            message=(
                f"Открыт {port}/{protocol} от {source}"
                if verified and source
                else f"Открыт {port}/{protocol}"
                if verified
                else "Не удалось открыть порт"
            ),
            error=None if verified else (err or out or "Правило не подтверждено однозначно")[:800],
            token={
                **self._chain_token(chain),
                "handle": created.handle if created else "",
                "source": source,
            },
        )

    @classmethod
    def _source_family_mismatch(
        cls,
        chain: dict[str, Any],
        port: int,
        protocol: str,
        source: str,
    ) -> Optional[FirewallMutation]:
        """Проверить совместимость IP-версии source с family цепочки."""
        if not source:
            return None
        version = source_ip_version(source)
        family = str(chain.get("family") or "")
        if (
            version not in (4, 6)
            or family not in {"ip", "ip6", "inet"}
            or (family == "ip" and version != 4)
            or (family == "ip6" and version != 6)
        ):
            return FirewallMutation(
                "nftables",
                port,
                protocol,
                "open",
                False,
                message=(
                    "Источник несовместим с family выбранной nftables chain; "
                    "изменение остановлено"
                ),
                error="nftables_source_family_mismatch",
                token=cls._chain_token(chain),
            )
        return None

    def preflight_close_port(
        self,
        ssh,
        server: dict,
        port: int,
        protocol: str,
        source: str = "",
    ) -> FirewallMutation:
        chain = self._selected_chain(ssh, server)
        if chain is None:
            return FirewallMutation(
                self.name,
                port,
                protocol,
                "preflight_close",
                False,
                message="Однозначная nftables input chain не найдена",
                error="inactive_or_ambiguous_nftables",
            )
        matching = self._matching(self._exact_rules(chain), port, protocol, source)
        if len(matching) > 1 or (matching and not str(matching[0].handle or "").isdigit()):
            return FirewallMutation(
                self.name,
                port,
                protocol,
                "preflight_close",
                False,
                existed_before=True,
                message="Точное правило nftables нельзя определить однозначно",
                error="ambiguous_rule",
            )
        code, out, err = exec_sudo(
            ssh,
            server,
            f"nft -a list chain {self._chain_args(chain)}",
            timeout=20,
        )
        if code != 0:
            return FirewallMutation(
                self.name,
                port,
                protocol,
                "preflight_close",
                False,
                message="Не удалось прочитать nftables input chain",
                error=(err or out or "nft list failed")[:800],
            )
        ambiguous = self._covering_shared_rules(out or "", port, protocol, source)
        if ambiguous:
            return FirewallMutation(
                self.name,
                port,
                protocol,
                "preflight_close",
                False,
                existed_before=bool(matching),
                message="Старый порт разрешён broad/shared правилом nftables",
                error="ambiguous_shared_rule",
                token={"rules": " | ".join(ambiguous[:5])[:500]},
            )
        label = f"{port}/{protocol} от {source}" if source else f"{port}/{protocol}"
        return FirewallMutation(
            self.name,
            port,
            protocol,
            "preflight_close",
            True,
            existed_before=bool(matching),
            verified=True,
            message=(
                f"Точное правило {label} можно удалить"
                if matching
                else f"Отдельное правило {label} отсутствует"
            ),
            token={
                **self._chain_token(chain),
                "handle": matching[0].handle if matching else "",
                "source": source,
            },
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
        handle = str(preflight.token.get("handle") or "")
        if not handle:
            label = f"{port}/{protocol} от {source}" if source else f"{port}/{protocol}"
            return FirewallMutation(
                self.name,
                port,
                protocol,
                "close",
                True,
                verified=True,
                message=f"Отдельное правило {label} отсутствует",
            )
        return self._delete_exact_rule(
            ssh,
            server,
            port,
            protocol,
            preflight.token,
            operation="close",
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
        return self._delete_exact_rule(
            ssh,
            server,
            mutation.port,
            mutation.protocol,
            mutation.token,
            operation="cleanup",
        )

    def list_rules(self, ssh, server: dict) -> list[FirewallRule]:
        chain = self._selected_chain(ssh, server)
        return self._exact_rules(chain) if chain is not None else []

    def _delete_exact_rule(
        self,
        ssh,
        server: dict,
        port: int,
        protocol: str,
        token: dict[str, Any],
        *,
        operation: str,
    ) -> FirewallMutation:
        if not self._valid_chain_token(token) or not str(token.get("handle") or "").isdigit():
            return FirewallMutation(
                self.name,
                port,
                protocol,
                operation,
                False,
                message="Правило nftables нельзя удалить безопасно",
                error="missing_exact_rule_token",
            )
        handle = int(token["handle"])
        source = str(token.get("source") or "")
        chain = self._find_chain(ssh, server, token)
        rule = self._rule_by_handle(chain, handle) if chain else None
        parsed = self._exact_allow(rule) if rule else None
        if parsed != (protocol, port, source):
            return FirewallMutation(
                self.name,
                port,
                protocol,
                operation,
                False,
                message="Правило nftables изменилось; автоматическое удаление остановлено",
                error="mutation_rule_changed",
            )
        code, out, err = exec_sudo(
            ssh,
            server,
            f"nft delete rule {self._chain_args(chain)} handle {handle}",
            timeout=20,
        )
        refreshed = self._find_chain(ssh, server, token) if code == 0 else chain
        absent = bool(refreshed is not None and self._rule_by_handle(refreshed, handle) is None)
        verified = code == 0 and absent
        return FirewallMutation(
            self.name,
            port,
            protocol,
            operation,
            verified,
            changed=verified,
            existed_before=True,
            verified=verified,
            message=(
                f"Закрыт {port}/{protocol} от {source}"
                if verified and source
                else f"Закрыт {port}/{protocol}"
                if verified
                else "Не удалось закрыть порт"
            ),
            error=None if verified else (err or out or "Удаление не подтверждено")[:800],
            token={**self._chain_token(chain), "handle": handle, "source": source},
        )

    def _ruleset(self, ssh, server: dict) -> dict[str, list[dict[str, Any]]]:
        code, out, err = exec_sudo(ssh, server, "nft -j -a list ruleset", timeout=30)
        if code != 0:
            raise RuntimeError((err or out or "Не удалось прочитать nftables ruleset")[:800])
        try:
            document = json.loads(out or "")
        except (TypeError, ValueError) as exc:
            raise RuntimeError("nftables вернул некорректный JSON ruleset") from exc
        entries = document.get("nftables") if isinstance(document, dict) else None
        if not isinstance(entries, list):
            raise RuntimeError("nftables JSON ruleset не содержит список nftables")

        tables: list[dict[str, Any]] = []
        chains_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
        rules: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            table = entry.get("table")
            if isinstance(table, dict):
                tables.append(table)
            chain = entry.get("chain")
            if isinstance(chain, dict):
                key = self._object_key(chain)
                if key in chains_by_key:
                    raise RuntimeError(
                        f"Дублирующееся описание nftables chain: {'/'.join(key)}"
                    )
                copied = dict(chain)
                copied["rules"] = []
                chains_by_key[key] = copied
            rule = entry.get("rule")
            if isinstance(rule, dict):
                rules.append(rule)
        for rule in rules:
            chain = chains_by_key.get(self._object_key(rule))
            if chain is not None:
                chain["rules"].append(rule)
        input_chains = [
            chain
            for chain in chains_by_key.values()
            if str(chain.get("type") or "").lower() == "filter"
            and str(chain.get("hook") or "").lower() == "input"
        ]
        return {"tables": tables, "input_chains": input_chains}

    def validate_input_chain(
        self,
        ssh,
        server: dict,
        token: dict[str, Any],
    ) -> dict[str, str]:
        """Проверить exact token по свежему ruleset без firewall-мутаций."""
        if not self._valid_chain_token(token):
            raise ValueError("Некорректный nftables chain token")
        chain = self._chain_from_snapshot(self._ruleset(ssh, server), token)
        if chain is None:
            raise RuntimeError(
                "Выбранная nftables chain исчезла или больше не является "
                "standalone input base chain"
            )
        return self._chain_token(chain)

    def _selected_chain(self, ssh, server: dict) -> Optional[dict[str, Any]]:
        return self._resolve_chain(server, self._ruleset(ssh, server))

    def _resolve_chain(
        self,
        server: dict,
        snapshot: dict[str, list[dict[str, Any]]],
    ) -> Optional[dict[str, Any]]:
        configured, token = self._configured_chain_token(server)
        if configured:
            chain = self._chain_from_snapshot(snapshot, token)
            if chain is None:
                raise RuntimeError(
                    "Сохранённая nftables input chain исчезла или больше "
                    "не является standalone input base chain; требуется выбор"
                )
            return chain
        state, chain, _ = self._selection_state(snapshot)
        if state == "ambiguous":
            raise RuntimeError(
                "Структура nftables input chains неоднозначна; "
                "автоматический выбор остановлен"
            )
        if state == "selection_required":
            raise RuntimeError(
                "Обнаружено несколько standalone nftables input chains; "
                "требуется выбор"
            )
        return chain

    @staticmethod
    def _configured_chain_token(server: dict) -> tuple[bool, Any]:
        quick_setup = server.get("quick_setup")
        if not isinstance(quick_setup, dict):
            return False, None
        firewall = quick_setup.get("firewall")
        if not isinstance(firewall, dict) or "nftables_input_chain" not in firewall:
            return False, None
        return True, firewall.get("nftables_input_chain")

    @classmethod
    def _selection_candidates(
        cls,
        classified: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], bool]:
        selectable = [
            item for item in classified
            if item["classification"] == "selectable"
            and cls._valid_chain_token(item)
        ]
        result: list[dict[str, Any]] = []
        for item in selectable[:20]:
            chain = item["raw"]
            priority = chain.get("prio")
            if isinstance(priority, bool) or not isinstance(priority, (int, str)):
                priority = None
            elif isinstance(priority, str):
                priority = priority[:32]
            policy = chain.get("policy")
            result.append({
                "family": item["family"],
                "table": item["table"],
                "chain": item["chain"],
                "policy": str(policy)[:32] if policy is not None else None,
                "priority": priority,
                "rules_count": min(len(chain.get("rules") or []), 1_000_000),
            })
        return result, len(selectable) > len(result)

    @classmethod
    def _selection_state(
        cls,
        snapshot: dict[str, list[dict[str, Any]]],
    ) -> tuple[str, Optional[dict[str, Any]], list[dict[str, Any]]]:
        candidates = cls._classified_input_chains(snapshot)
        if any(item["classification"] == "ambiguous" for item in candidates):
            return "ambiguous", None, candidates
        selectable = [
            item for item in candidates
            if item["classification"] == "selectable"
        ]
        if len(selectable) > 1:
            return "selection_required", None, candidates
        if not selectable:
            return "none", None, candidates
        return "selected", selectable[0]["raw"], candidates

    @classmethod
    def _input_chain_candidates(
        cls,
        snapshot: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, str]]:
        return [
            {
                "family": item["family"],
                "table": item["table"],
                "chain": item["chain"],
                "classification": item["classification"],
                "reason": item["reason"],
            }
            for item in cls._classified_input_chains(snapshot)
        ]

    @classmethod
    def _classified_input_chains(
        cls,
        snapshot: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for chain in sorted(snapshot["input_chains"], key=cls._object_key):
            classification, reason = cls._classify_input_chain(chain)
            result.append({
                **cls._chain_token(chain),
                "classification": classification,
                "reason": reason,
                "raw": chain,
            })
        return result

    @classmethod
    def _classify_input_chain(
        cls,
        chain: dict[str, Any],
    ) -> tuple[str, str]:
        family, table, name = cls._object_key(chain)
        family_lower = family.lower()
        table_lower = table.lower()
        name_lower = name.lower()
        if (
            str(chain.get("type") or "").lower() != "filter"
            or str(chain.get("hook") or "").lower() != "input"
        ):
            return "ambiguous", "not_an_input_filter_base_chain"

        rules = chain.get("rules")
        if not isinstance(rules, list):
            return "ambiguous", "invalid_rule_list"
        targets: list[str] = []
        for rule in rules:
            expressions = rule.get("expr") if isinstance(rule, dict) else None
            if not isinstance(expressions, list):
                return "ambiguous", "invalid_rule_expression"
            for expression in expressions:
                if not isinstance(expression, dict):
                    return "ambiguous", "invalid_rule_expression"
                for verdict in ("jump", "goto"):
                    if verdict not in expression:
                        continue
                    target = cls._verdict_target(expression[verdict])
                    if target is None:
                        return "ambiguous", "unrecognized_dispatch"
                    targets.append(target.lower())

        if (
            table_lower.startswith("firewalld")
            or name_lower.startswith("firewalld")
            or any("firewalld" in target for target in targets)
        ):
            return "technical", "firewalld_dispatch"
        if (
            table_lower.startswith("ufw-")
            or name_lower.startswith("ufw-")
            or any(target.startswith("ufw-") for target in targets)
        ):
            return "technical", "ufw_dispatch"

        legacy_input = (
            family_lower in {"ip", "ip6"}
            and table_lower == "filter"
            and name == "INPUT"
        )
        if legacy_input and cls._contains_key(rules, {"compat", "xt"}):
            return "technical", "iptables_nft_compat"
        if targets:
            return "ambiguous", "unrecognized_dispatch"
        if legacy_input:
            return "ambiguous", "legacy_input_without_compat_marker"
        return "selectable", "standalone_input_base_chain"

    @staticmethod
    def _verdict_target(value: Any) -> Optional[str]:
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            target = value.get("target")
            if isinstance(target, str) and target:
                return target
        return None

    @classmethod
    def _contains_key(cls, value: Any, keys: set[str]) -> bool:
        if isinstance(value, dict):
            return bool(
                any(str(key).lower() in keys for key in value)
                or any(cls._contains_key(item, keys) for item in value.values())
            )
        if isinstance(value, list):
            return any(cls._contains_key(item, keys) for item in value)
        return False

    @classmethod
    def _chain_from_snapshot(
        cls,
        snapshot: dict[str, list[dict[str, Any]]],
        token: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        if not cls._valid_chain_token(token):
            return None
        key = (str(token["family"]), str(token["table"]), str(token["chain"]))
        chain = next(
            (
                candidate
                for candidate in snapshot["input_chains"]
                if cls._object_key(candidate) == key
            ),
            None,
        )
        if chain is None:
            return None
        classification, _ = cls._classify_input_chain(chain)
        return chain if classification == "selectable" else None

    def _find_chain(
        self,
        ssh,
        server: dict,
        token: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        if not self._valid_chain_token(token):
            return None
        return self._chain_from_snapshot(self._ruleset(ssh, server), token)

    def _delete_bypass_handle(
        self,
        ssh,
        server: dict,
        chain: dict[str, Any],
        handle: int,
    ) -> tuple[bool, str]:
        rule = self._rule_by_handle(chain, handle)
        if rule is None or not self._bypass_rule(rule):
            return False, "nftables bypass rule изменилось; удаление остановлено"
        code, _, _ = exec_sudo(
            ssh,
            server,
            f"nft delete rule {self._chain_args(chain)} handle {handle}",
            timeout=20,
        )
        if code != 0:
            return False, "Не удалось удалить подтверждённый nftables bypass"
        refreshed = self._find_chain(ssh, server, self._chain_token(chain))
        if refreshed is None or self._rule_by_handle(refreshed, handle) is not None:
            return False, "Удаление nftables bypass не подтверждено"
        return True, ""

    @classmethod
    def _exact_rules(cls, chain: Optional[dict[str, Any]]) -> list[FirewallRule]:
        if chain is None:
            return []
        source_label = cls._chain_label(chain)
        result: list[FirewallRule] = []
        for rule in chain["rules"]:
            parsed = cls._exact_allow(rule)
            if parsed is None:
                continue
            protocol, port, rule_source = parsed
            handle = rule.get("handle")
            result.append(FirewallRule(
                port=str(port),
                protocol=protocol,
                raw=cls._rule_description(rule),
                handle=str(handle) if isinstance(handle, int) else None,
                # Ограниченные правила несут канонический IP/CIDR,
                # неограниченные — служебную метку цепочки.
                source=rule_source or source_label,
            ))
        return result

    @staticmethod
    def _saddr_value(right: Any) -> Optional[str]:
        """Канонизировать правую часть ip/ip6 saddr match."""
        if isinstance(right, str):
            return normalize_source(right) or None
        if isinstance(right, dict):
            prefix = right.get("prefix")
            if (
                isinstance(prefix, dict)
                and isinstance(prefix.get("addr"), str)
                and isinstance(prefix.get("len"), int)
            ):
                return normalize_source(f"{prefix['addr']}/{prefix['len']}") or None
        return None

    @staticmethod
    def _exact_allow(rule: Optional[dict[str, Any]]) -> Optional[tuple[str, int, str]]:
        if not isinstance(rule, dict) or not isinstance(rule.get("expr"), list):
            return None
        match_value: Optional[tuple[str, int]] = None
        source_value: Optional[str] = None
        any_gate = False
        accepted = False
        for expression in rule["expr"]:
            if not isinstance(expression, dict):
                return None
            if "counter" in expression or "comment" in expression:
                continue
            if "accept" in expression:
                if accepted:
                    return None
                accepted = True
                continue
            match = expression.get("match")
            if not isinstance(match, dict) or match.get("op") not in {"==", None}:
                return None
            left = match.get("left")
            right = match.get("right")
            meta = left.get("meta") if isinstance(left, dict) else None
            if isinstance(meta, dict) and str(meta.get("key") or "").lower() == "l4proto":
                # Явный gate ANY-правила: meta l4proto { tcp, udp }.
                if match_value is not None or any_gate:
                    return None
                if not NftablesBackend._l4proto_tcp_udp(right):
                    return None
                any_gate = True
                continue
            payload = left.get("payload") if isinstance(left, dict) else None
            if not isinstance(payload, dict):
                return None
            protocol = str(payload.get("protocol") or "").lower()
            field = str(payload.get("field") or "").lower()
            if protocol in {"ip", "ip6"} and field == "saddr":
                # Ограничение источника: ip/ip6 saddr <адрес или CIDR>.
                if match_value is not None or source_value is not None:
                    return None
                candidate = NftablesBackend._saddr_value(right)
                if candidate is None:
                    return None
                source_value = candidate
                continue
            if protocol not in {"tcp", "udp", "th"} or field != "dport":
                return None
            try:
                port = int(right)
            except (TypeError, ValueError):
                return None
            if not 1 <= port <= 65535 or match_value is not None:
                return None
            # th dport — transport-header dport без привязки к одному протоколу.
            match_value = ("any", port) if protocol == "th" else (protocol, port)
        if match_value is None or not accepted:
            return None
        if any_gate and match_value[0] != "any":
            return None
        return match_value[0], match_value[1], source_value or ""

    @staticmethod
    def _l4proto_tcp_udp(value: Any) -> bool:
        """Проверить, что значение meta l4proto — это ровно множество tcp+udp."""
        if not isinstance(value, dict) or not isinstance(value.get("set"), list):
            return False
        names: set[str] = set()
        for item in value["set"]:
            if item in ("tcp", 6):
                names.add("tcp")
            elif item in ("udp", 17):
                names.add("udp")
            else:
                return False
        return names == {"tcp", "udp"}

    @staticmethod
    def _unconditional_accept(rule: dict[str, Any]) -> bool:
        expressions = rule.get("expr")
        if not isinstance(expressions, list):
            return False
        accepted = False
        for expression in expressions:
            if not isinstance(expression, dict):
                return False
            if "counter" in expression or "comment" in expression:
                continue
            if "accept" in expression and not accepted:
                accepted = True
                continue
            return False
        return accepted

    @classmethod
    def _bypass_rule(cls, rule: dict[str, Any]) -> bool:
        comment = rule.get("comment")
        if comment is None:
            for expression in rule.get("expr") or []:
                if isinstance(expression, dict) and "comment" in expression:
                    comment = expression.get("comment")
                    break
        return comment == _BYPASS_COMMENT and cls._unconditional_accept(rule)

    @classmethod
    def _bypass_handles(cls, chain: dict[str, Any]) -> list[int]:
        return [
            int(rule["handle"])
            for rule in chain["rules"]
            if isinstance(rule.get("handle"), int) and cls._bypass_rule(rule)
        ]

    @classmethod
    def _boilerplate_rule(cls, rule: Any) -> bool:
        """Служебные правила (ct established/related, loopback) вне модели переноса."""
        if not isinstance(rule, dict) or not isinstance(rule.get("expr"), list):
            return False
        accepted = False
        state_match = False
        loopback_match = False
        for expression in rule["expr"]:
            if not isinstance(expression, dict):
                return False
            if "counter" in expression or "comment" in expression:
                continue
            if "accept" in expression:
                if accepted:
                    return False
                accepted = True
                continue
            match = expression.get("match")
            if not isinstance(match, dict) or not isinstance(match.get("left"), dict):
                return False
            left = match["left"]
            right = match.get("right")
            ct = left.get("ct")
            if isinstance(ct, dict) and str(ct.get("key") or "").lower() == "state":
                states = cls._state_values(right)
                if states is not None and states <= {"established", "related"}:
                    state_match = True
                    continue
                return False
            meta = left.get("meta")
            if (
                isinstance(meta, dict)
                and str(meta.get("key") or "").lower() in {"iifname", "iif"}
                and right == "lo"
            ):
                loopback_match = True
                continue
            return False
        return accepted and (state_match or loopback_match)

    @staticmethod
    def _state_values(value: Any) -> Optional[set[str]]:
        if isinstance(value, str):
            items = [value]
        elif isinstance(value, dict) and isinstance(value.get("set"), list):
            items = value["set"]
        elif isinstance(value, list):
            items = value
        else:
            return None
        states = {str(item).lower() for item in items}
        return states or None

    @classmethod
    def _standard_direct_rule(cls, line: str) -> Optional[tuple[str, int, str]]:
        expression = re.sub(r"\s+#\s+handle\s+\d+\s*$", "", line.strip(), flags=re.I)
        expression = re.sub(r'\s+comment\s+"(?:[^"\\]|\\.)*"', "", expression)
        expression = re.sub(
            r"\bcounter(?:\s+packets\s+\d+\s+bytes\s+\d+)?\b",
            "",
            expression,
            flags=re.I,
        )
        expression = " ".join(expression.split())
        match = re.fullmatch(
            r"(?:(ip|ip6)\s+saddr\s+(\S+)\s+)?"
            r"(?:meta\s+l4proto\s+\{\s*tcp\s*,\s*udp\s*\}\s+)?"
            r"(?:(tcp|udp)|th)\s+dport\s+(\d+)\s+accept",
            expression,
            re.I,
        )
        if not match:
            return None
        source = ""
        if match.group(1):
            source = normalize_source(match.group(2)) or ""
            if not source:
                return None
        protocol = "any" if match.group(3) is None else match.group(3).lower()
        return protocol, int(match.group(4)), source

    @classmethod
    def _covering_shared_rules(
        cls,
        text: str,
        port: int,
        protocol: str,
        source: str = "",
    ) -> list[str]:
        ambiguous: list[str] = []
        # ANY-запрос покрывается правилами по tcp И по udp.
        checked = ("tcp", "udp") if protocol == "any" else (protocol,)
        for raw in text.splitlines():
            line = re.sub(r"\s+#\s+handle\s+\d+\s*$", "", raw.strip(), flags=re.I).lower()
            if "accept" not in line:
                continue
            if (
                re.match(r"^type\s+\S+\s+hook\s+\S+\s+priority\b", line)
                and re.search(r";\s*policy\s+\S+\s*;\s*$", line)
            ):
                continue
            if "ct state" in line and "established" in line:
                continue
            if re.search(r"\biif(?:name)?\s+(?:\"?lo\"?)\s+accept\b", line):
                continue
            direct_parsed = cls._standard_direct_rule(raw)
            if direct_parsed is not None:
                rule_protocol, rule_port, rule_source = direct_parsed
                if rule_port == port and rule_protocol in {protocol, "any"}:
                    # Само exact-правило запроса пропускаем; прочие правила
                    # на этом порту не должны оставлять доступ к источнику.
                    exact_self = (
                        rule_protocol == protocol and rule_source == (source or "")
                    )
                    if not exact_self and source_keeps_access(rule_source, source):
                        ambiguous.append(raw.strip())
                continue
            if source:
                saddr_match = re.search(r"\b(?:ip|ip6)\s+saddr\s+(\S+)", line)
                if saddr_match:
                    token = normalize_source(saddr_match.group(1))
                    # Правило с чужим источником не затрагивает закрываемый
                    # source; неканонический токен консервативно считаем покрывающим.
                    if token and not source_keeps_access(token, source):
                        continue
            mentioned = {
                name
                for name in ("tcp", "udp", "icmp", "icmpv6")
                if re.search(rf"\b{name}\b", line)
            }
            if mentioned and mentioned.isdisjoint(checked):
                continue
            handled = False
            for name in checked:
                range_match = re.search(
                    rf"\b{name}\s+dport\s+(\d+)\s*[-:]\s*(\d+)\b",
                    line,
                )
                if not range_match:
                    continue
                handled = True
                start, end = int(range_match.group(1)), int(range_match.group(2))
                if min(start, end) <= port <= max(start, end):
                    ambiguous.append(raw.strip())
                break
            if handled:
                continue
            for name in checked:
                set_match = re.search(
                    rf"\b{name}\s+dport\s*\{{([^}}]+)\}}",
                    line,
                )
                if not set_match:
                    continue
                handled = True
                covered = False
                unknown = False
                for token in set_match.group(1).split(","):
                    token = token.strip()
                    if token.isdigit() and int(token) == port:
                        covered = True
                    elif re.fullmatch(r"\d+\s*[-:]\s*\d+", token):
                        left, right = (int(value) for value in re.split(r"[-:]", token))
                        covered = covered or min(left, right) <= port <= max(left, right)
                    elif not token.isdigit():
                        unknown = True
                if covered or unknown:
                    ambiguous.append(raw.strip())
                break
            if handled:
                continue
            direct = re.search(r"\b(tcp|udp)\s+dport\s+(\d+)\b", line)
            if direct:
                if direct.group(1) in checked and int(direct.group(2)) == port:
                    ambiguous.append(raw.strip())
                continue
            ambiguous.append(raw.strip())
        return ambiguous

    @staticmethod
    def _matching(
        rules: list[FirewallRule],
        port: int,
        protocol: str,
        source: str = "",
    ) -> list[FirewallRule]:
        result = []
        for rule in rules:
            if rule.port != str(port) or rule.protocol != protocol:
                continue
            # Identity новых правил — (port, protocol, source): ограниченные
            # правила несут канонический IP/CIDR, неограниченные — метку цепочки.
            if source:
                if rule.source != source:
                    continue
            elif is_ip_source(rule.source):
                continue
            result.append(rule)
        return result

    @staticmethod
    def _object_key(value: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(value.get("family") or ""),
            str(value.get("table") or ""),
            str(value.get("name") or value.get("chain") or ""),
        )

    @staticmethod
    def _chain_token(chain: dict[str, Any]) -> dict[str, str]:
        return {
            "family": str(chain.get("family") or ""),
            "table": str(chain.get("table") or ""),
            "chain": str(chain.get("name") or ""),
        }

    @staticmethod
    def _valid_chain_token(value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        return all(
            isinstance(value.get(key), str)
            and bool(value[key])
            and len(value[key]) <= 128
            and "\x00" not in value[key]
            for key in ("family", "table", "chain")
        )

    @classmethod
    def _chain_args(cls, chain: dict[str, Any]) -> str:
        token = cls._chain_token(chain)
        return cls._quote_parts(token["family"], token["table"], token["chain"])

    @staticmethod
    def _quote_parts(*parts: str) -> str:
        return " ".join(shlex.quote(str(part)) for part in parts)

    @staticmethod
    def _chain_label(chain: dict[str, Any]) -> str:
        return "/".join(
            str(value)
            for value in (
                chain.get("family") or "?",
                chain.get("table") or "?",
                chain.get("name") or "?",
            )
        )[:400]

    @staticmethod
    def _rule_by_handle(
        chain: Optional[dict[str, Any]],
        handle: int,
    ) -> Optional[dict[str, Any]]:
        if chain is None:
            return None
        return next(
            (
                rule
                for rule in chain["rules"]
                if isinstance(rule.get("handle"), int) and int(rule["handle"]) == handle
            ),
            None,
        )

    @staticmethod
    def _rule_description(rule: dict[str, Any]) -> str:
        expression = json.dumps(
            rule.get("expr") or [],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        handle = rule.get("handle")
        suffix = f" # handle {handle}" if isinstance(handle, int) else ""
        return f"{expression}{suffix}"[:500]
