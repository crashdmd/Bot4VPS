# -*- coding: utf-8 -*-
"""Оркестратор Quick Setup: обзор и операции без Task Manager."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Optional

from core.storage import (
    ConnectionStateConflictError,
    clear_nftables_input_chain,
    compare_and_set_nftables_input_chain,
    find_server,
    server_connection_snapshot,
)

from . import diagnostics as diag_mod
from . import fail2ban as fail2ban_mod
from . import firewall as firewall_mod
from . import packages as packages_mod
from . import ssh_access as ssh_access_mod
from . import system as system_mod
from .models import (
    Fail2banStatus,
    LocalSettingsStatus,
    OpResult,
    PackagesStatus,
    QuickSetupOverview,
    QuickSetupServerNotFoundError,
    SshAccessStatus,
    SystemStatus,
)


def _require_server(server_id: str) -> dict:
    server = find_server(server_id)
    if not server:
        raise QuickSetupServerNotFoundError(f"Сервер не найден: {server_id}")
    return server


def _local_settings(server: dict) -> LocalSettingsStatus:
    """Имя/группа/SSL — локальные поля servers.json, SSH не нужны."""
    groups: list[str] = []
    try:
        from core.storage import load_groups

        for g in load_groups():
            name = g if isinstance(g, str) else g.get("name")
            if name:
                groups.append(name)
    except Exception:
        pass
    current = server.get("group") or ""
    if current and current not in groups:
        groups.insert(0, current)
    return LocalSettingsStatus(
        name=server.get("name") or "",
        group=current,
        groups=groups,
        ssl_enabled=bool(server.get("certificate_check")),
        ssl_host=server.get("ssl_host") or "",
    )


def get_overview(server_id: str, *, check_updates: bool = True) -> QuickSetupOverview:
    """Собрать снимок для страницы «Базовые настройки».

    Модули (ssh_access, firewall, fail2ban, packages) не зависят друг от
    друга — каждый открывает собственное SSH-подключение и глотает ошибки
    в свой status. Запускаем их параллельно: wall-clock = самому
    медленному модулю (было ~сумма всех ~5 с на каждый запрос страницы).
    diagnostics идёт первым: по его ssh_ok остальные решают, делать ли
    работу, и fallback-статусы заполняются как раньше.
    """
    server = _require_server(server_id)
    overview = QuickSetupOverview(
        server_id=server["id"],
        server_name=server.get("name") or server["id"],
        host=server.get("host") or "—",
    )
    # Локальные поля всегда доступны — не зависят от SSH
    overview.local_settings = _local_settings(server)

    overview.diagnostics = diag_mod.collect(server)

    if overview.diagnostics.ssh_ok:
        with ThreadPoolExecutor(max_workers=5) as pool:
            ssh_status = pool.submit(ssh_access_mod.get_status, server)
            fw_info = pool.submit(firewall_mod.detect, server)
            f2b_status = pool.submit(fail2ban_mod.get_status, server)
            pkg_status = pool.submit(packages_mod.list_packages, server)
            sys_status = (
                pool.submit(system_mod.check_updates, server)
                if check_updates
                else None
            )

            overview.ssh_access = ssh_status.result()
            info = fw_info.result()
            overview.firewall = firewall_mod.to_status(info)
            overview.fail2ban = f2b_status.result()
            overview.packages = pkg_status.result()
            overview.system = (
                sys_status.result()
                if sys_status is not None
                else SystemStatus(updates_summary="—")
            )

            if info.label:
                overview.diagnostics.firewall = info.label
            if overview.fail2ban.label:
                overview.diagnostics.fail2ban = overview.fail2ban.label
    else:
        overview.ssh_access = SshAccessStatus(
            user=server.get("user") or "—",
            port=int(server.get("port") or 22),
            key_configured=bool(server.get("key_path")),
            auth_type="key" if server.get("auth_type") == "key" else "password",
            error=overview.diagnostics.ssh_error,
        )

        from .firewall.base import FirewallInfo

        overview.firewall = firewall_mod.to_status(
            FirewallInfo(
                backend=None,
                active=None,
                label="—",
                error=overview.diagnostics.ssh_error,
            )
        )

        overview.fail2ban = Fail2banStatus(
            label="—", error=overview.diagnostics.ssh_error
        )

        overview.packages = PackagesStatus(error=overview.diagnostics.ssh_error)

        overview.system = SystemStatus(
            updates_summary="SSH недоступен",
            error=overview.diagnostics.ssh_error,
        )

    return overview


def system_check_updates(server_id: str) -> SystemStatus:
    return system_mod.check_updates(_require_server(server_id))


def system_upgrade(server_id: str) -> OpResult:
    return system_mod.upgrade_system(_require_server(server_id))


def system_reboot(server_id: str) -> OpResult:
    return system_mod.reboot_and_wait(_require_server(server_id))


def refresh_diagnostics(server_id: str) -> dict:
    return asdict(diag_mod.collect(_require_server(server_id)))


# ---- Packages ----

def packages_list(server_id: str) -> PackagesStatus:
    return packages_mod.list_packages(_require_server(server_id))


def packages_install(server_id: str, names: list[str]) -> OpResult:
    return packages_mod.install_packages(_require_server(server_id), names)


# ---- Firewall ----

def firewall_status(server_id: str) -> dict:
    info = firewall_mod.detect(_require_server(server_id))
    st = firewall_mod.to_status(info)
    return {
        **asdict(st),
        "rules": [
            {
                "port": str(r.port)[:32],
                "protocol": str(r.protocol)[:16],
                "action": str(r.action)[:32],
                "raw": str(r.raw or "")[:500],
            }
            for r in list(info.rules or [])[:200]
        ],
    }


def firewall_install(
    server_id: str,
    backend: str,
    *,
    confirm_switch: bool = False,
    continuation: Optional[dict] = None,
) -> OpResult:
    return firewall_mod.install_backend(
        _require_server(server_id),
        backend,
        confirm_switch=confirm_switch,
        continuation=continuation,
    )


def firewall_select_nftables_chain(
    server_id: str,
    family: str,
    table: str,
    chain: str,
) -> OpResult:
    server = _require_server(server_id)
    expected_connection = server_connection_snapshot(server)
    token = {"family": family, "table": table, "chain": chain}
    try:
        validated = firewall_mod.validate_nftables_input_chain(server, token)
    except (ValueError, RuntimeError):
        return OpResult(
            ok=False,
            message=(
                "Выбранная nftables chain не подтверждена на сервере; "
                "обновите список и повторите"
            ),
            error="nftables_chain_not_selectable",
        )
    except Exception:
        return OpResult(
            ok=False,
            message="Не удалось проверить nftables chain на сервере",
            error="nftables_chain_validation_failed",
        )

    try:
        saved = compare_and_set_nftables_input_chain(
            server_id,
            validated,
            expected_connection=expected_connection,
        )
    except ConnectionStateConflictError:
        return OpResult(
            ok=False,
            message=(
                "SSH-настройки сервера изменились во время проверки; "
                "обновите данные и повторите"
            ),
            error="server_connection_changed",
        )
    except Exception:
        return OpResult(
            ok=False,
            message="Проверенная nftables chain не сохранена",
            error="nftables_chain_persistence_failed",
        )

    return OpResult(
        ok=True,
        message="nftables input chain проверена и сохранена",
        data={"chain": saved},
    )


def firewall_switch(
    server_id: str,
    target: str,
    *,
    confirm: bool,
    continuation: Optional[dict] = None,
    selected_rules: Optional[list] = None,
) -> OpResult:
    return firewall_mod.switch_backend(
        _require_server(server_id),
        target,
        confirm=confirm,
        continuation=continuation,
        selected_rules=selected_rules,
    )


def firewall_migrate(
    server_id: str,
    target: str,
    *,
    confirm: bool,
    continuation: Optional[dict] = None,
) -> OpResult:
    return firewall_mod.migrate(
        _require_server(server_id),
        target,
        confirm=confirm,
        continuation=continuation,
    )


def firewall_open_port(
    server_id: str,
    port: int,
    protocol: str = "tcp",
    source: str = "",
    *,
    acknowledge_firewall_conflict: bool = False,
) -> OpResult:
    return firewall_mod.open_port(
        _require_server(server_id),
        port,
        protocol,
        source,
        acknowledge_firewall_conflict=acknowledge_firewall_conflict,
    )


def firewall_close_port(
    server_id: str,
    port: int,
    protocol: str = "tcp",
    source: str = "",
    *,
    acknowledge_firewall_conflict: bool = False,
) -> OpResult:
    return firewall_mod.close_port(
        _require_server(server_id),
        port,
        protocol,
        source,
        acknowledge_firewall_conflict=acknowledge_firewall_conflict,
    )


def firewall_disable(server_id: str) -> OpResult:
    """Отключить единственный активный firewall (правила сохраняются)."""
    return firewall_mod.disable(_require_server(server_id))


def firewall_enable(server_id: str, backend: str) -> OpResult:
    """Включить установленный неактивный firewall (без миграции правил)."""
    return firewall_mod.enable(_require_server(server_id), backend)


def firewall_remove(server_id: str, backend: str) -> OpResult:
    """Удалить firewall (пакет, без purge); для nftables сбросить выбор chain.

    Сохранённый выбор nftables input chain относится к конкретной
    установке и не должен переживать uninstall — сбрасываем его после
    успешного удаления (best-effort: сброс предпочтения не критичен
    для результата самой операции).
    """
    result = firewall_mod.remove(_require_server(server_id), backend)
    if result.ok and str(backend or "").strip().lower() == "nftables":
        try:
            result.data["chain_selection_cleared"] = clear_nftables_input_chain(
                server_id
            )
        except Exception:
            pass
    return result


def firewall_list_rules(server_id: str) -> OpResult:
    return firewall_mod.list_rules(_require_server(server_id))


# ---- Fail2ban ----

def fail2ban_status(server_id: str) -> Fail2banStatus:
    return fail2ban_mod.get_status(_require_server(server_id))


def fail2ban_install(server_id: str) -> OpResult:
    return fail2ban_mod.install(_require_server(server_id))


def fail2ban_apply(
    server_id: str,
    *,
    ssh_jail_enabled=None,
    ban_time=None,
    find_time=None,
    max_retry=None,
) -> OpResult:
    return fail2ban_mod.apply_settings(
        _require_server(server_id),
        ssh_jail_enabled=ssh_jail_enabled,
        ban_time=ban_time,
        find_time=find_time,
        max_retry=max_retry,
    )


def fail2ban_banned(server_id: str) -> OpResult:
    return fail2ban_mod.list_banned(_require_server(server_id))


def fail2ban_restart(server_id: str) -> OpResult:
    return fail2ban_mod.restart(_require_server(server_id))


def fail2ban_start(server_id: str) -> OpResult:
    return fail2ban_mod.start(_require_server(server_id))


def fail2ban_stop(server_id: str) -> OpResult:
    return fail2ban_mod.stop(_require_server(server_id))


def fail2ban_uninstall(server_id: str, *, remove_config: bool = False) -> OpResult:
    return fail2ban_mod.uninstall(_require_server(server_id), remove_config=remove_config)


def fail2ban_jails(server_id: str) -> OpResult:
    return fail2ban_mod.list_jails(_require_server(server_id))


def fail2ban_set_jail_enabled(server_id: str, jail: str, *, enabled: bool) -> OpResult:
    return fail2ban_mod.set_jail_enabled(_require_server(server_id), jail, enabled=enabled)


def fail2ban_unban(server_id: str, jail: str, ip: str) -> OpResult:
    return fail2ban_mod.unban(_require_server(server_id), jail, ip)


def fail2ban_whitelist(server_id: str) -> OpResult:
    return fail2ban_mod.list_whitelist(_require_server(server_id))


def fail2ban_add_whitelist(server_id: str, ip: str) -> OpResult:
    return fail2ban_mod.add_whitelist(_require_server(server_id), ip)


def fail2ban_remove_whitelist(server_id: str, ip: str) -> OpResult:
    return fail2ban_mod.remove_whitelist(_require_server(server_id), ip)


def fail2ban_filters(server_id: str) -> OpResult:
    return fail2ban_mod.list_filters(_require_server(server_id))


def fail2ban_configuration(server_id: str) -> OpResult:
    return fail2ban_mod.list_configuration(_require_server(server_id))


def fail2ban_read_configuration(server_id: str, kind: str, filename: str) -> OpResult:
    return fail2ban_mod.read_configuration(_require_server(server_id), kind, filename)


def fail2ban_write_configuration(
    server_id: str,
    kind: str,
    filename: str,
    content: str,
    *,
    create_only: bool = False,
) -> OpResult:
    return fail2ban_mod.write_configuration(
        _require_server(server_id),
        kind,
        filename,
        content,
        create_only=create_only,
    )


def fail2ban_delete_configuration(server_id: str, kind: str, filename: str) -> OpResult:
    return fail2ban_mod.delete_configuration(_require_server(server_id), kind, filename)


# ---- SSH access ----

def ssh_status(server_id: str) -> SshAccessStatus:
    return ssh_access_mod.get_status(_require_server(server_id))


def ssh_change_port(
    server_id: str,
    port: int,
    *,
    acknowledge_firewall_conflict: bool = False,
) -> OpResult:
    return ssh_access_mod.change_port(
        _require_server(server_id),
        port,
        acknowledge_firewall_conflict=acknowledge_firewall_conflict,
    )


def ssh_change_password(server_id: str, password: str) -> OpResult:
    return ssh_access_mod.change_password(_require_server(server_id), password)


def ssh_set_root_login(server_id: str, enabled: bool) -> OpResult:
    return ssh_access_mod.set_root_login(_require_server(server_id), enabled)


def ssh_set_password_auth(server_id: str, enabled: bool) -> OpResult:
    return ssh_access_mod.set_password_auth(_require_server(server_id), enabled)


def ssh_install_key(
    server_id: str,
    public_key: str,
    *,
    switch_to_key: bool = False,
    key_path: str | None = None,
) -> OpResult:
    return ssh_access_mod.install_pubkey(
        _require_server(server_id),
        public_key,
        switch_to_key=switch_to_key,
        key_path=key_path,
    )


def ssh_create_user(
    server_id: str,
    username: str,
    *,
    password: str | None = None,
    sudo: bool = True,
) -> OpResult:
    return ssh_access_mod.create_user(
        _require_server(server_id),
        username,
        password=password,
        sudo=sudo,
        switch_to_user=False,
    )


def ssh_list_users(server_id: str) -> OpResult:
    return ssh_access_mod.list_users(_require_server(server_id))


def ssh_switch_user(
    server_id: str,
    username: str,
    *,
    password: str | None = None,
    key_path: str | None = None,
    allow_without_sudo: bool = False,
) -> OpResult:
    return ssh_access_mod.switch_user(
        _require_server(server_id),
        username,
        password=password,
        key_path=key_path,
        allow_without_sudo=allow_without_sudo,
    )


def ssh_delete_user(
    server_id: str,
    username: str,
    *,
    remove_home: bool = False,
) -> OpResult:
    return ssh_access_mod.delete_user(
        _require_server(server_id),
        username,
        remove_home=remove_home,
    )


def ssh_grant_sudo(server_id: str, username: str) -> OpResult:
    return ssh_access_mod.grant_sudo(_require_server(server_id), username)


def ssh_revoke_sudo(server_id: str, username: str) -> OpResult:
    return ssh_access_mod.revoke_sudo(_require_server(server_id), username)


def ssh_list_user_keys(server_id: str, username: str) -> OpResult:
    return ssh_access_mod.list_user_keys(_require_server(server_id), username)


def ssh_list_local_free_keys(server_id: str, *, scope: str = "free") -> OpResult:
    """Локальные ключи Bot4VPS с публичной частью.

    scope=free (модалка «Добавить готовый ключ на сервер»): «свободный» =
    не используется нигде — не записан key_path ни в один сервер (маршруты
    Bot4VPS) и fingerprint отсутствует в authorized_keys всех пользователей
    ЭТОГО сервера (один ключ — один пользователь).

    scope=switch (селект в блоке «Переключить пользователя»): все ключи с
    приватной частью — в т.ч. используемые (ключ crashdmd подходит для
    переключения на crashdmd); пометка in_use позволяет их подписать."""
    server = _require_server(server_id)
    if scope == "switch":
        keys = ssh_access_mod.list_local_keys()
        return OpResult(
            ok=True,
            message=f"Локальных ключей: {len(keys)}",
            data={"keys": keys},
        )
    keys = ssh_access_mod.list_local_keys_with_public(server)
    return OpResult(
        ok=True,
        message=f"Свободных локальных ключей: {len(keys)}",
        data={"keys": keys},
    )


def ssh_add_user_key(
    server_id: str,
    username: str,
    *,
    root_password: Optional[str] = None,
) -> OpResult:
    return ssh_access_mod.add_key_to_user(
        _require_server(server_id),
        username,
        root_password=root_password,
    )


def ssh_remove_user_key(
    server_id: str,
    username: str,
    fingerprint: str,
    *,
    root_password: Optional[str] = None,
) -> OpResult:
    return ssh_access_mod.remove_key_from_user(
        _require_server(server_id),
        username,
        fingerprint,
        root_password=root_password,
    )


def ssh_select_user_key(server_id: str, username: str, fingerprint: str) -> OpResult:
    return ssh_access_mod.select_user_key(
        _require_server(server_id),
        username,
        fingerprint,
    )


def ssh_set_user_password(
    server_id: str,
    username: str,
    password: str,
    *,
    old_password: Optional[str] = None,
) -> OpResult:
    return ssh_access_mod.set_user_password(
        _require_server(server_id),
        username,
        password,
        old_password=old_password,
    )
