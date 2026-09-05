# -*- coding: utf-8 -*-
"""API «Базовые настройки» (Quick Setup). Без Task Manager."""
from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.quick_setup.models import QuickSetupServerNotFoundError


router = APIRouter(tags=["quick-setup"])


def _qs():
    from core import quick_setup
    return quick_setup


def _internal_error(_: Exception) -> JSONResponse:
    """Не возвращать клиенту текст unexpected exception с возможными секретами."""
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "message": "Операция не выполнена",
            "output": "",
            "error": "Внутренняя ошибка",
        },
    )


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


_CONTINUATION_MAX_BYTES = 32 * 1024
_CONTINUATION_MAX_DEPTH = 8
_CONTINUATION_MAX_ITEMS = 256
_CONTINUATION_MAX_NODES = 2048
_CONTINUATION_MAX_STRING_BYTES = 4096


def _bounded_continuation(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("continuation должен быть JSON-объектом")

    remaining = _CONTINUATION_MAX_NODES

    def walk(item: Any, depth: int) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining < 0:
            raise ValueError("continuation содержит слишком много элементов")
        if depth > _CONTINUATION_MAX_DEPTH:
            raise ValueError("continuation имеет слишком большую вложенность")
        if isinstance(item, dict):
            if len(item) > _CONTINUATION_MAX_ITEMS:
                raise ValueError("continuation содержит слишком много полей")
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError("ключи continuation должны быть строками")
                if len(key.encode("utf-8")) > _CONTINUATION_MAX_STRING_BYTES:
                    raise ValueError("ключ continuation слишком длинный")
                walk(child, depth + 1)
            return
        if isinstance(item, list):
            if len(item) > _CONTINUATION_MAX_ITEMS:
                raise ValueError("continuation содержит слишком длинный список")
            for child in item:
                walk(child, depth + 1)
            return
        if isinstance(item, str):
            if len(item.encode("utf-8")) > _CONTINUATION_MAX_STRING_BYTES:
                raise ValueError("строка continuation слишком длинная")
            return
        if item is None or isinstance(item, (bool, int, float)):
            return
        raise ValueError("continuation содержит недопустимое JSON-значение")

    walk(value, 0)
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("continuation содержит недопустимое JSON-значение") from exc
    if len(encoded) > _CONTINUATION_MAX_BYTES:
        raise ValueError("continuation превышает допустимый размер")
    return value


class FirewallContinuationBody(StrictBody):
    continuation: Optional[dict[str, Any]] = None

    @field_validator("continuation", mode="before")
    @classmethod
    def validate_continuation(cls, value: Any) -> Any:
        return _bounded_continuation(value)


PackageName = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}$"),
]


class PackagesInstallBody(StrictBody):
    packages: List[PackageName] = Field(default_factory=list, max_length=32)


class FirewallInstallBody(FirewallContinuationBody):
    backend: Literal["ufw", "firewalld", "nftables"]
    confirm_switch: bool = False


class FirewallSelectedRuleBody(StrictBody):
    port: int = Field(..., ge=1, le=65535)
    protocol: Literal["tcp", "udp", "any"]
    source: str = Field("", max_length=64)

    @field_validator("source", mode="before")
    @classmethod
    def _validate_source(cls, value):
        from core.quick_setup.firewall.base import normalize_source

        if not value:
            return ""
        normalized = normalize_source(value)
        if not normalized or normalized != value:
            raise ValueError("source должен быть каноническим IP-адресом или CIDR")
        return normalized


class FirewallSwitchBody(FirewallContinuationBody):
    target: Literal["ufw", "firewalld", "nftables"]
    confirm: bool
    selected_rules: Optional[List[FirewallSelectedRuleBody]] = Field(
        default=None, max_length=200
    )


NftablesChainPart = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[^\x00]+$"),
]


class NftablesChainBody(StrictBody):
    family: NftablesChainPart
    table: NftablesChainPart
    chain: NftablesChainPart


class FirewallMigrationBody(FirewallContinuationBody):
    target: Literal["ufw", "firewalld", "nftables"]
    confirm: bool


class FirewallBackendBody(StrictBody):
    backend: Literal["ufw", "firewalld", "nftables"]


class FirewallPortBody(StrictBody):
    port: int = Field(..., ge=1, le=65535)
    protocol: Literal["tcp", "udp", "any"] = "tcp"
    source: str = Field("", max_length=64)
    acknowledge_firewall_conflict: bool = False

    @field_validator("source", mode="before")
    @classmethod
    def _validate_source(cls, value):
        from core.quick_setup.firewall.base import normalize_source

        normalized = normalize_source(value)
        if normalized is None:
            raise ValueError("source должен быть IP-адресом или CIDR (IPv4/IPv6)")
        return normalized


@router.get("/api/servers/{server_id}/quick-setup")
async def api_overview(server_id: str, updates: bool = True):
    """Полный снимок страницы «Базовые настройки»."""
    try:
        overview = await asyncio.to_thread(
            _qs().get_overview, server_id, check_updates=updates
        )
        return overview.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.get("/api/servers/{server_id}/quick-setup/diagnostics")
async def api_diagnostics(server_id: str):
    try:
        data = await asyncio.to_thread(_qs().refresh_diagnostics, server_id)
        return {"ok": True, "diagnostics": data}
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/system/check-updates")
async def api_check_updates(server_id: str):
    try:
        from dataclasses import asdict

        st = await asyncio.to_thread(_qs().system_check_updates, server_id)
        return {"ok": True, "system": asdict(st)}
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/system/upgrade")
async def api_upgrade(server_id: str):
    try:
        result = await asyncio.to_thread(_qs().system_upgrade, server_id)
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/system/reboot")
async def api_qs_reboot(server_id: str):
    try:
        result = await asyncio.to_thread(_qs().system_reboot, server_id)
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


# ---- Packages ----

@router.get("/api/servers/{server_id}/quick-setup/packages")
async def api_packages_list(server_id: str):
    try:
        from dataclasses import asdict

        st = await asyncio.to_thread(_qs().packages_list, server_id)
        return {"ok": True, "packages": asdict(st)}
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/packages/install")
async def api_packages_install(server_id: str, body: PackagesInstallBody):
    try:
        result = await asyncio.to_thread(
            _qs().packages_install, server_id, body.packages
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


# ---- Firewall ----

@router.get("/api/servers/{server_id}/quick-setup/firewall")
async def api_firewall_status(server_id: str):
    try:
        data = await asyncio.to_thread(_qs().firewall_status, server_id)
        return {"ok": True, "firewall": data}
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/firewall/install")
async def api_firewall_install(server_id: str, body: FirewallInstallBody):
    try:
        result = await asyncio.to_thread(
            _qs().firewall_install,
            server_id,
            body.backend,
            confirm_switch=body.confirm_switch,
            continuation=body.continuation,
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post(
    "/api/servers/{server_id}/quick-setup/firewall/nftables/chain"
)
async def api_firewall_select_nftables_chain(
    server_id: str,
    body: NftablesChainBody,
):
    try:
        result = await asyncio.to_thread(
            _qs().firewall_select_nftables_chain,
            server_id,
            body.family,
            body.table,
            body.chain,
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/firewall/switch")
async def api_firewall_switch(
    server_id: str, body: FirewallSwitchBody
):
    try:
        result = await asyncio.to_thread(
            _qs().firewall_switch,
            server_id,
            body.target,
            confirm=body.confirm,
            continuation=body.continuation,
            selected_rules=(
                [rule.model_dump() for rule in body.selected_rules]
                if body.selected_rules is not None
                else None
            ),
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/firewall/migration")
async def api_firewall_migration(
    server_id: str, body: FirewallMigrationBody
):
    try:
        result = await asyncio.to_thread(
            _qs().firewall_migrate,
            server_id,
            body.target,
            confirm=body.confirm,
            continuation=body.continuation,
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/firewall/open")
async def api_firewall_open(server_id: str, body: FirewallPortBody):
    try:
        result = await asyncio.to_thread(
            _qs().firewall_open_port,
            server_id,
            body.port,
            body.protocol,
            body.source,
            acknowledge_firewall_conflict=body.acknowledge_firewall_conflict,
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/firewall/close")
async def api_firewall_close(server_id: str, body: FirewallPortBody):
    try:
        result = await asyncio.to_thread(
            _qs().firewall_close_port,
            server_id,
            body.port,
            body.protocol,
            body.source,
            acknowledge_firewall_conflict=body.acknowledge_firewall_conflict,
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/firewall/disable")
async def api_firewall_disable(server_id: str):
    try:
        result = await asyncio.to_thread(_qs().firewall_disable, server_id)
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/firewall/enable")
async def api_firewall_enable(server_id: str, body: FirewallBackendBody):
    try:
        result = await asyncio.to_thread(
            _qs().firewall_enable, server_id, body.backend
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/firewall/remove")
async def api_firewall_remove(server_id: str, body: FirewallBackendBody):
    try:
        result = await asyncio.to_thread(
            _qs().firewall_remove, server_id, body.backend
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.get("/api/servers/{server_id}/quick-setup/firewall/rules")
async def api_firewall_rules(server_id: str):
    try:
        result = await asyncio.to_thread(_qs().firewall_list_rules, server_id)
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


# ---- Fail2ban ----

class Fail2banSettingsBody(StrictBody):
    model_config = ConfigDict(extra="forbid")
    ssh_jail_enabled: Optional[bool] = None
    ban_time: Optional[str] = Field(default=None, max_length=16)
    find_time: Optional[str] = Field(default=None, max_length=16)
    max_retry: Optional[int] = Field(default=None, ge=1, le=100)


class Fail2banUninstallBody(StrictBody):
    model_config = ConfigDict(extra="forbid")
    remove_config: bool = False


class Fail2banUnbanBody(StrictBody):
    model_config = ConfigDict(extra="forbid")
    jail: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    ip: str = Field(..., min_length=1, max_length=64)


class Fail2banWhitelistBody(StrictBody):
    model_config = ConfigDict(extra="forbid")
    ip: str = Field(..., min_length=1, max_length=64)


class Fail2banConfigRef(StrictBody):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(..., min_length=1, max_length=16, pattern=r"^(?:jail|filter)$")
    filename: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.(?:conf|local)$")


class Fail2banConfigWriteBody(Fail2banConfigRef):
    content: str = Field(..., max_length=512 * 1024)
    create_only: bool = False


@router.get("/api/servers/{server_id}/quick-setup/fail2ban")
async def api_fail2ban_status(server_id: str):
    try:
        from dataclasses import asdict

        st = await asyncio.to_thread(_qs().fail2ban_status, server_id)
        return {"ok": True, "fail2ban": asdict(st)}
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/fail2ban/install")
async def api_fail2ban_install(server_id: str):
    try:
        result = await asyncio.to_thread(_qs().fail2ban_install, server_id)
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/fail2ban/settings")
async def api_fail2ban_settings(server_id: str, body: Fail2banSettingsBody):
    try:
        result = await asyncio.to_thread(
            lambda: _qs().fail2ban_apply(
                server_id,
                ssh_jail_enabled=body.ssh_jail_enabled,
                ban_time=body.ban_time,
                find_time=body.find_time,
                max_retry=body.max_retry,
            )
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.get("/api/servers/{server_id}/quick-setup/fail2ban/banned")
async def api_fail2ban_banned(server_id: str):
    try:
        result = await asyncio.to_thread(_qs().fail2ban_banned, server_id)
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/fail2ban/restart")
async def api_fail2ban_restart(server_id: str):
    try:
        result = await asyncio.to_thread(_qs().fail2ban_restart, server_id)
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/fail2ban/start")
async def api_fail2ban_start(server_id: str):
    try:
        result = await asyncio.to_thread(_qs().fail2ban_start, server_id)
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/fail2ban/stop")
async def api_fail2ban_stop(server_id: str):
    try:
        result = await asyncio.to_thread(_qs().fail2ban_stop, server_id)
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/fail2ban/uninstall")
async def api_fail2ban_uninstall(server_id: str, body: Fail2banUninstallBody):
    try:
        result = await asyncio.to_thread(
            lambda: _qs().fail2ban_uninstall(server_id, remove_config=body.remove_config)
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.get("/api/servers/{server_id}/quick-setup/fail2ban/jails")
async def api_fail2ban_jails(server_id: str):
    try:
        result = await asyncio.to_thread(_qs().fail2ban_jails, server_id)
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


class Fail2banJailEnabledBody(StrictBody):
    enabled: bool


@router.post(
    "/api/servers/{server_id}/quick-setup/fail2ban/jails/{jail}/enabled"
)
async def api_fail2ban_jail_enabled(
    server_id: str,
    jail: Annotated[
        str,
        Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"),
    ],
    body: Fail2banJailEnabledBody,
):
    try:
        result = await asyncio.to_thread(
            lambda: _qs().fail2ban_set_jail_enabled(server_id, jail, enabled=body.enabled)
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/fail2ban/unban")
async def api_fail2ban_unban(server_id: str, body: Fail2banUnbanBody):
    try:
        result = await asyncio.to_thread(
            lambda: _qs().fail2ban_unban(server_id, body.jail, body.ip)
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.get("/api/servers/{server_id}/quick-setup/fail2ban/whitelist")
async def api_fail2ban_whitelist(server_id: str):
    try:
        result = await asyncio.to_thread(_qs().fail2ban_whitelist, server_id)
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/fail2ban/whitelist")
async def api_fail2ban_add_whitelist(server_id: str, body: Fail2banWhitelistBody):
    try:
        result = await asyncio.to_thread(
            lambda: _qs().fail2ban_add_whitelist(server_id, body.ip)
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.delete("/api/servers/{server_id}/quick-setup/fail2ban/whitelist")
async def api_fail2ban_remove_whitelist(server_id: str, body: Fail2banWhitelistBody):
    try:
        result = await asyncio.to_thread(
            lambda: _qs().fail2ban_remove_whitelist(server_id, body.ip)
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.get("/api/servers/{server_id}/quick-setup/fail2ban/filters")
async def api_fail2ban_filters(server_id: str):
    try:
        result = await asyncio.to_thread(_qs().fail2ban_filters, server_id)
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.get("/api/servers/{server_id}/quick-setup/fail2ban/configuration")
async def api_fail2ban_configuration(server_id: str):
    try:
        result = await asyncio.to_thread(_qs().fail2ban_configuration, server_id)
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.get("/api/servers/{server_id}/quick-setup/fail2ban/configuration/content")
async def api_fail2ban_read_configuration(
    server_id: str,
    kind: Literal["jail", "filter"] = Query(...),
    filename: str = Query(
        ...,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.(?:conf|local)$",
    ),
):
    try:
        result = await asyncio.to_thread(
            _qs().fail2ban_read_configuration, server_id, kind, filename
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.put("/api/servers/{server_id}/quick-setup/fail2ban/configuration/content")
async def api_fail2ban_write_configuration(
    server_id: str, body: Fail2banConfigWriteBody
):
    try:
        result = await asyncio.to_thread(
            lambda: _qs().fail2ban_write_configuration(
                server_id,
                body.kind,
                body.filename,
                body.content,
                create_only=body.create_only,
            )
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.delete("/api/servers/{server_id}/quick-setup/fail2ban/configuration/content")
async def api_fail2ban_delete_configuration(
    server_id: str, ref: Fail2banConfigRef
):
    try:
        result = await asyncio.to_thread(
            _qs().fail2ban_delete_configuration, server_id, ref.kind, ref.filename
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


# ---- SSH / Access ----

class SshPortBody(StrictBody):
    port: int = Field(..., ge=1, le=65535)
    acknowledge_firewall_conflict: bool = False


class SshPasswordBody(StrictBody):
    password: str = Field(..., min_length=6, max_length=256)


class SshBoolBody(StrictBody):
    enabled: bool


class SshKeyBody(StrictBody):
    public_key: str = Field(..., min_length=20, max_length=8192)
    switch_to_key: bool = False
    key_path: Optional[str] = Field(default=None, max_length=512)


class SshUserBody(StrictBody):
    username: str = Field(
        ...,
        min_length=1,
        max_length=32,
        pattern=r"^[a-z_][a-z0-9_-]{0,31}$",
    )
    password: Optional[str] = Field(default=None, min_length=6, max_length=256)
    sudo: bool = True


class SshSwitchUserBody(StrictBody):
    username: str = Field(
        ...,
        min_length=1,
        max_length=32,
        pattern=r"^[a-z_][a-z0-9_-]{0,31}$",
    )
    password: Optional[str] = Field(default=None, min_length=1, max_length=256)
    key_path: Optional[str] = Field(default=None, max_length=512)
    allow_without_sudo: bool = False


class SshDeleteUserBody(StrictBody):
    remove_home: bool = False


class SshUserKeyDeleteBody(StrictBody):
    fingerprint: str = Field(..., min_length=10, max_length=100)
    root_password: Optional[str] = Field(default=None, max_length=256)


class SshUserKeyCreateBody(StrictBody):
    root_password: Optional[str] = Field(default=None, max_length=256)


class SshUserKeySelectBody(StrictBody):
    fingerprint: str = Field(..., min_length=10, max_length=100)


class SshUserPasswordBody(StrictBody):
    password: str = Field(..., min_length=6, max_length=256)
    old_password: Optional[str] = Field(default=None, max_length=256)


@router.get("/api/servers/{server_id}/quick-setup/ssh")
async def api_ssh_status(server_id: str):
    try:
        from dataclasses import asdict
        st = await asyncio.to_thread(_qs().ssh_status, server_id)
        return {"ok": True, "ssh_access": asdict(st)}
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/ssh/port")
async def api_ssh_port(server_id: str, body: SshPortBody):
    try:
        result = await asyncio.to_thread(
            _qs().ssh_change_port,
            server_id,
            body.port,
            acknowledge_firewall_conflict=body.acknowledge_firewall_conflict,
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/ssh/password")
async def api_ssh_password(server_id: str, body: SshPasswordBody):
    try:
        result = await asyncio.to_thread(_qs().ssh_change_password, server_id, body.password)
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/ssh/root-login")
async def api_ssh_root(server_id: str, body: SshBoolBody):
    try:
        result = await asyncio.to_thread(_qs().ssh_set_root_login, server_id, body.enabled)
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/ssh/password-auth")
async def api_ssh_pwd_auth(server_id: str, body: SshBoolBody):
    try:
        result = await asyncio.to_thread(_qs().ssh_set_password_auth, server_id, body.enabled)
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/ssh/key")
async def api_ssh_key(server_id: str, body: SshKeyBody):
    try:
        result = await asyncio.to_thread(
            lambda: _qs().ssh_install_key(
                server_id,
                body.public_key,
                switch_to_key=body.switch_to_key,
                key_path=body.key_path,
            )
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.get("/api/servers/{server_id}/quick-setup/ssh/users")
async def api_ssh_users(server_id: str):
    try:
        result = await asyncio.to_thread(_qs().ssh_list_users, server_id)
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/ssh/users")
async def api_ssh_create_user(server_id: str, body: SshUserBody):
    try:
        result = await asyncio.to_thread(
            lambda: _qs().ssh_create_user(
                server_id,
                body.username,
                password=body.password,
                sudo=body.sudo,
            )
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/ssh/users/switch")
async def api_ssh_switch_user(server_id: str, body: SshSwitchUserBody):
    try:
        result = await asyncio.to_thread(
            lambda: _qs().ssh_switch_user(
                server_id,
                body.username,
                password=body.password,
                key_path=body.key_path,
                allow_without_sudo=body.allow_without_sudo,
            )
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.delete("/api/servers/{server_id}/quick-setup/ssh/users/{username}")
async def api_ssh_delete_user(
    server_id: str,
    body: SshDeleteUserBody,
    username: str = Path(
        ...,
        min_length=1,
        max_length=32,
        pattern=r"^[a-z_][a-z0-9_-]{0,31}$",
    ),
):
    try:
        result = await asyncio.to_thread(
            lambda: _qs().ssh_delete_user(
                server_id,
                username,
                remove_home=body.remove_home,
            )
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/ssh/users/{username}/sudo")
async def api_ssh_grant_sudo(
    server_id: str,
    username: str = Path(
        ...,
        min_length=1,
        max_length=32,
        pattern=r"^[a-z_][a-z0-9_-]{0,31}$",
    ),
):
    try:
        result = await asyncio.to_thread(
            lambda: _qs().ssh_grant_sudo(server_id, username)
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.delete("/api/servers/{server_id}/quick-setup/ssh/users/{username}/sudo")
async def api_ssh_revoke_sudo(
    server_id: str,
    username: str = Path(
        ...,
        min_length=1,
        max_length=32,
        pattern=r"^[a-z_][a-z0-9_-]{0,31}$",
    ),
):
    try:
        result = await asyncio.to_thread(
            lambda: _qs().ssh_revoke_sudo(server_id, username)
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.get("/api/servers/{server_id}/quick-setup/ssh/local-keys")
async def api_ssh_local_free_keys(server_id: str, scope: str = "free"):
    try:
        result = await asyncio.to_thread(
            lambda: _qs().ssh_list_local_free_keys(server_id, scope=scope)
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.get("/api/servers/{server_id}/quick-setup/ssh/users/{username}/keys")
async def api_ssh_user_keys(
    server_id: str,
    username: str = Path(
        ...,
        min_length=1,
        max_length=32,
        pattern=r"^[a-z_][a-z0-9_-]{0,31}$",
    ),
):
    try:
        result = await asyncio.to_thread(
            lambda: _qs().ssh_list_user_keys(server_id, username)
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/ssh/users/{username}/keys")
async def api_ssh_user_key_create(
    server_id: str,
    body: SshUserKeyCreateBody,
    username: str = Path(
        ...,
        min_length=1,
        max_length=32,
        pattern=r"^[a-z_][a-z0-9_-]{0,31}$",
    ),
):
    try:
        result = await asyncio.to_thread(
            lambda: _qs().ssh_add_user_key(
                server_id,
                username,
                root_password=body.root_password,
            )
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.delete("/api/servers/{server_id}/quick-setup/ssh/users/{username}/keys")
async def api_ssh_user_key_delete(
    server_id: str,
    body: SshUserKeyDeleteBody,
    username: str = Path(
        ...,
        min_length=1,
        max_length=32,
        pattern=r"^[a-z_][a-z0-9_-]{0,31}$",
    ),
):
    try:
        result = await asyncio.to_thread(
            lambda: _qs().ssh_remove_user_key(
                server_id,
                username,
                body.fingerprint,
                root_password=body.root_password,
            )
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/ssh/users/{username}/keys/select")
async def api_ssh_user_key_select(
    server_id: str,
    body: SshUserKeySelectBody,
    username: str = Path(
        ...,
        min_length=1,
        max_length=32,
        pattern=r"^[a-z_][a-z0-9_-]{0,31}$",
    ),
):
    try:
        result = await asyncio.to_thread(
            lambda: _qs().ssh_select_user_key(server_id, username, body.fingerprint)
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)


@router.post("/api/servers/{server_id}/quick-setup/ssh/users/{username}/password")
async def api_ssh_user_password(
    server_id: str,
    body: SshUserPasswordBody,
    username: str = Path(
        ...,
        min_length=1,
        max_length=32,
        pattern=r"^[a-z_][a-z0-9_-]{0,31}$",
    ),
):
    try:
        result = await asyncio.to_thread(
            lambda: _qs().ssh_set_user_password(
                server_id,
                username,
                body.password,
                old_password=body.old_password,
            )
        )
        return result.to_dict()
    except QuickSetupServerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return _internal_error(e)
