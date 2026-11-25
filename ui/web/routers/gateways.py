"""OpenWrt gateway API; all routes share the existing authentication gate."""
from __future__ import annotations

import time

import asyncio
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Depends, UploadFile, File
from pydantic import BaseModel, Field

from core.openwrt import bootstrap
from core.openwrt import service_updates as service_update_jobs
from core.openwrt import integration_updates
from core.openwrt import backups as gateway_backups
from core.openwrt.monitor import refresh, snapshot
from core.node_types import load_gateways
from ..deps import task_brief

def feature_gate(request: Request):
    from core.openwrt.feature import enabled
    if request.url.path.rstrip('/') != '/api/gateways' and not enabled():
        raise HTTPException(409,'Управление OpenWrt выключено в Настройки → Параметры')

router = APIRouter(prefix="/api/gateways", tags=["gateways"], dependencies=[Depends(feature_gate)])


class ProbeBody(BaseModel):
    name: str = Field(default='', max_length=100)
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=22, ge=1, le=65535)
    user: str = Field(default="root", min_length=1, max_length=64)
    auth_type: Literal["password", "key"] = "password"
    password: str | None = Field(default=None, repr=False)
    key_path: str | None = None
    group: str = ""


class DecisionBody(BaseModel):
    decision: Literal["automatic", "manual", "no"]


class ManualBody(BaseModel):
    name: str = Field(default='', max_length=100)
    url: str = Field(min_length=1, max_length=512)
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=512, repr=False)
    tls_sha256: str | None = None
    tls_pin_confirmed: bool = False
    group: str = ""


class DeleteBody(BaseModel):
    confirmed: bool = False
    plan_token: str


class SSHBody(BaseModel):
    user: str = Field(default='root', min_length=1, max_length=64)
    port: int = Field(default=22, ge=1, le=65535)
    auth_type: Literal['password', 'key'] = 'password'
    password: str | None = Field(default=None, max_length=512, repr=False)
    key_path: str | None = None


class ReserveBody(BaseModel):
    enabled: bool
    keep: Literal[2, 3] = 3


class BundleBody(BaseModel):
    profile: Literal['podkop', 'ssclash', 'adguardhome']
    version: str = Field(min_length=1, max_length=32)


class OperationBody(BaseModel):
    action: Literal['start', 'stop', 'restart', 'remove', 'install', 'update', 'web_access']
    web_scope: Literal['lan', 'wan'] | None = None
    keep_backup: bool = True
    bundle_id: str | None = None
    rollback_bundle_id: str | None = None


class ApplyBody(BaseModel):
    plan_token: str
    confirmed: bool = False


class NetworkBody(BaseModel):
    action: Literal['edit', 'delete', 'routes', 'up', 'down', 'reconnect', 'dhcp', 'dns', 'firewall', 'firewall_restart', 'wireless']
    data: dict = Field(repr=False)


class PackageBody(BaseModel):
    action: Literal['refresh', 'install']
    package: str = Field(default='', max_length=100)


class BackupPlanBody(BaseModel):
    action: Literal['restore', 'reboot'] = 'restore'
    archive_id: str | None = None


def owner(request):
    from ..security import verified_mobile_device_id
    device = verified_mobile_device_id(request)
    if device:
        return "phone:" + device
    from .._internal.auth_flows import browser_id
    return "web:" + browser_id(request)


def public(node):
    config = node.get("openwrt") or {}
    ssh = config.get('ssh') or {}
    return {"id": node["id"], "name": node["name"], "host": node["host"], "group": node.get("group", ""),
        "api_url": config.get("url"), "api_username": config.get("username"), "tls_sha256": config.get("tls_sha256"),
        "luci_url": config.get("url", "").removesuffix("/ubus") + "/cgi-bin/luci/",
        "access_url": config.get("url", "").removesuffix("/ubus") + config.get("luci_path", "/cgi-bin/luci/admin/services/bot4vps").replace('/admin/system/bot4vps', '/admin/services/bot4vps'),
        "ssh_configured": bool(ssh), "ssh_user": ssh.get('user'), "ssh_port": ssh.get('port', 22), "ssh_auth_type": ssh.get('auth_type', 'password'),
        "managed": bool(config.get("managed")), "bootstrap_state": node.get("bootstrap_state", "ready"), "deletion_pending": bool(node.get("deletion_pending")), "monitor": snapshot(node["id"]),
        "service_update_tasks": service_update_jobs.task_states(node['id'])}


def gateway(node_id):
    from core.storage import find_server
    node = find_server(node_id)
    if not node or node.get("node_type") != "openwrt":
        raise HTTPException(404, "Шлюз не найден")
    return node


def editing_allowed(node_id):
    from core.task_manager import task_manager
    tasks = [task_manager.get_running(node_id), *task_manager.get_queue(node_id)]
    if any(task and task.kind in ('openwrt-disconnect', 'openwrt-router-operation', 'openwrt-operation', 'openwrt-integration-update', 'openwrt-backup') and not task.is_done for task in tasks):
        raise HTTPException(409, 'Выполняется операция шлюза. Дождитесь завершения перед изменением доступа.')


@router.get('/{node_id}/backups')
async def gateway_backup_list(node_id: str):
    from core.openwrt.backup_store import inventory
    node = gateway(node_id)
    task = gateway_backups.active_task(node_id)
    return {'items': await asyncio.to_thread(inventory),
            'available': bool(node['openwrt'].get('signing_private_key')),
            'reboot_required': await asyncio.to_thread(gateway_backups.reboot_required, node_id),
            'task': task_brief(task) if task else None}


@router.post('/{node_id}/backups/create', status_code=202)
async def create_gateway_backup(node_id: str):
    try:
        task = await gateway_backups.enqueue_create(gateway(node_id))
        return {'task_id': task.id, 'task': task_brief(task)}
    except ValueError as exc: raise HTTPException(400, str(exc)) from None


@router.post('/{node_id}/backups/upload')
async def upload_gateway_backup(node_id: str, file: UploadFile = File(...)):
    import tempfile
    from pathlib import Path
    from core.openwrt import backup_store, backup_archive
    gateway(node_id)  # Archive remains shared after upload from this gateway's UI.
    incoming = backup_store.ROOT / 'incoming'; incoming.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=incoming); written = 0
    import os
    try:
        with os.fdopen(fd, 'wb') as output:
            while chunk := await file.read(65536):
                written += len(chunk)
                if written > backup_store.MAX_ARCHIVE_BYTES: raise ValueError('Архив настроек должен быть не больше 32 МБ')
                output.write(chunk)
            output.flush(); os.fsync(output.fileno())
        await asyncio.to_thread(backup_archive.inspect, Path(name))
        record = await asyncio.to_thread(backup_store.save, Path(name), filename=file.filename, origin='upload')
        return {'archive': record}
    except ValueError as exc: raise HTTPException(400, str(exc)) from None
    finally:
        await file.close(); Path(name).unlink(missing_ok=True)


@router.post('/{node_id}/backups/plan')
async def gateway_backup_plan(node_id: str, body: BackupPlanBody, request: Request):
    try: return await gateway_backups.prepare(gateway(node_id), owner(request), body.action, body.archive_id)
    except FileNotFoundError as exc: raise HTTPException(404, str(exc)) from None
    except ValueError as exc: raise HTTPException(400, str(exc)) from None


@router.delete('/{node_id}/backups/plans/{token}')
async def cancel_gateway_backup_plan(node_id: str, token: str, request: Request):
    try:
        await gateway_backups.cancel_plan(gateway(node_id), token, owner(request))
        return {'ok': True}
    except ValueError as exc: raise HTTPException(400, str(exc)) from None


@router.post('/{node_id}/backups/apply', status_code=202)
async def apply_gateway_backup_plan(node_id: str, body: ApplyBody, request: Request):
    if not body.confirmed: raise HTTPException(400, 'Подтвердите показанный план восстановления или перезагрузки')
    try:
        task = await gateway_backups.enqueue(gateway(node_id), body.plan_token, owner(request))
        return {'task_id': task.id, 'task': task_brief(task)}
    except ValueError as exc: raise HTTPException(400, str(exc)) from None


@router.get("")
async def list_gateways(compact: bool = False):
    from core.openwrt.feature import enabled
    active = enabled()
    rows = [public(node) for node in load_gateways()] if active else []
    if compact:
        for row in rows: row['monitor'].pop('traffic_history',None)
    return {"enabled":active,"gateways":rows}


@router.post("/probe")
async def probe(body: ProbeBody, request: Request):
    if body.auth_type == "password" and not body.password:
        raise HTTPException(400, "Введите SSH-пароль")
    if any(node["host"] == body.host for node in load_gateways()):
        raise HTTPException(409, "Этот шлюз уже добавлен")
    try:
        result = await bootstrap.prepare(body.model_dump(), owner(request))
        return result or {"node_type": "linux"}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/bootstrap/{token}")
async def decide(token: str, body: DecisionBody, request: Request):
    try:
        draft = bootstrap.get_draft(token, owner(request))
        if body.decision == "manual":
            return {"manual": bootstrap.manual_instructions(draft)}
        if body.decision == "no":
            if draft.started:
                raise ValueError("Настройка уже выполняется")
            await asyncio.to_thread(bootstrap.discard_draft, token, draft)
            return {"ok": True, "cancelled": True}
        task = await bootstrap.start(token, owner(request))
        return {"task_id": task.id, "task": task_brief(task)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


async def manual_config(body):
    if body.username == "root":
        raise ValueError("Для API укажите отдельную учётную запись Bot4VPS. Root используется только для первоначальной настройки через SSH.")
    from core.openwrt.rpc import RpcClient, endpoint, certificate_for_pin
    config = {"url": endpoint(body.url), "username": body.username, "password": body.password, "managed": False}
    if body.tls_sha256:
        config["tls_certificate"] = await asyncio.to_thread(certificate_for_pin, body.url, body.tls_sha256)
        config["tls_sha256"] = body.tls_sha256.lower().replace(":", "")
    rpc = RpcClient(config)
    try:
        board = await rpc.call("system", "board")
        if board.get("release", {}).get("distribution", "").lower() != "openwrt":
            raise ValueError("API не подтвердил OpenWrt")
        config["board"] = board
    finally:
        await rpc.close()
    return config


@router.post("/manual")
async def add_manual(body: ManualBody):
    import secrets
    from core.storage import add_server, data_lock
    try:
        config = await manual_config(body)
        host = urlsplit(config["url"]).hostname
        node = {"id": secrets.token_hex(8), "node_type": "openwrt", "name": bootstrap.gateway_name(body.name, config['board'], host),
                "host": host, "group": body.group, "openwrt": config}
        with data_lock():
            if any(item["host"] == host for item in load_gateways()):
                raise ValueError("Этот шлюз уже добавлен")
            add_server(node)
        try: await refresh(node, force=True)
        except Exception: pass  # Saving the verified connection is already complete.
        from core.openwrt.bundle_jobs import enqueue_reserve
        try: await enqueue_reserve(node, automatic=True)
        except Exception: pass  # A queue failure cannot undo a stored connection.
        return public(node)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get('/reserve')
async def reserve_settings():
    from core.openwrt import bundles
    return {'settings': bundles.settings(), 'bundles': bundles.cached()}


@router.put('/reserve')
async def set_reserve(body: ReserveBody):
    from core.openwrt import bundles
    return {'settings': bundles.configure(body.enabled, body.keep)}




@router.post('/{node_id}/bootstrap/finalize')
async def finalize_bootstrap(node_id: str):
    from core.task_manager import task_manager
    node = gateway(node_id)
    if node.get('bootstrap_state') != 'commit_pending':
        raise HTTPException(400, 'Фиксация подключения уже завершена')
    task = await task_manager.enqueue(name='Фиксация подключения шлюза', server_id=node['id'],
        server_name=node['name'], kind='openwrt-bootstrap-finalize', payload={}, live_reported=True)
    return {'task_id': task.id, 'task': task_brief(task)}


@router.get('/catalog/{profile}')
async def catalog(profile: Literal['podkop', 'ssclash', 'adguardhome'], node_id: str | None = None):
    from core.openwrt import bundles
    release_version = None
    if node_id:
        node = gateway(node_id)
        board = snapshot(node_id).get('board') or node['openwrt'].get('board') or {}
        release_version = board.get('release', {}).get('version')
    try:
        rows = [row for row in await bundles.releases(profile) if bundles.compatible(release_version, profile, row['tag_name'])]
        return {'versions': [row['tag_name'] for row in rows], 'project': bundles.REPOS[profile]}
    except Exception:
        return {'versions': sorted({row['version'] for row in bundles.cached() if row['profile'] == profile and bundles.compatible(release_version, profile, row['version'])}, reverse=True),
                'project': bundles.REPOS[profile], 'offline': True}


@router.post('/{node_id}/bundles')
async def prepare_bundle(node_id: str, body: BundleBody):
    from core.openwrt.bundle_jobs import enqueue
    task = await enqueue(gateway(node_id), body.profile, body.version)
    return {'task_id': task.id, 'task': task_brief(task)}


class ServiceVersionBody(BaseModel):
    version: str = Field(min_length=1, max_length=32, pattern=r'^v?\d+\.\d+\.\d+$')
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    confirmed: bool = False


@router.post('/{node_id}/services/{service}/version')
async def confirm_service_version(node_id: str, service: Literal['ssclash', 'adguardhome'], body: ServiceVersionBody):
    editing_allowed(node_id)
    if not body.confirmed: raise HTTPException(400, 'Подтвердите фактически установленную версию сервиса')
    from core.openwrt.service_inventory import confirm
    try: return await confirm(gateway(node_id), service, body.version, body.fingerprint)
    except ValueError as exc: raise HTTPException(400, str(exc)) from None


@router.get('/{node_id}/service-updates')
async def service_updates(node_id: str, request: Request):
    try:
        result = await service_update_jobs.available(gateway(node_id), owner(request))
        return {'services': result, 'checked_at': int(time.time())}
    except ValueError as exc: raise HTTPException(400, str(exc)) from None


@router.post('/{node_id}/integration/plan')
async def integration_plan(node_id: str, request: Request):
    editing_allowed(node_id)
    try:return await integration_updates.prepare(gateway(node_id),owner(request))
    except ValueError as exc:raise HTTPException(400,str(exc)) from None


@router.post('/{node_id}/integration')
async def apply_integration(node_id: str, body: ApplyBody, request: Request):
    if not body.confirmed:raise HTTPException(400,'Подтвердите показанный план обновления интеграции')
    try:
        task=await integration_updates.enqueue(gateway(node_id),body.plan_token,owner(request))
        return {'task_id':task.id,'task':task_brief(task)}
    except ValueError as exc:raise HTTPException(400,str(exc)) from None


@router.delete('/{node_id}/integration/plans/{token}')
async def cancel_integration(node_id: str, token: str, request: Request):
    try:await asyncio.to_thread(integration_updates.cancel,gateway(node_id),token,owner(request));return {'ok':True}
    except ValueError as exc:raise HTTPException(400,str(exc)) from None


@router.post('/{node_id}/services/{service}/update-bundle')
async def prepare_service_update(node_id: str, service: Literal['podkop', 'ssclash', 'adguardhome'], request: Request):
    node = gateway(node_id)
    try: task = await service_update_jobs.enqueue_update(node, service, owner(request))
    except ValueError as exc: raise HTTPException(409, str(exc)) from None
    return {'task_id':task.id,'task':task_brief(task)}


@router.get('/{node_id}/services/{service}/update-plan')
async def prepared_update_plan(node_id: str, service: Literal['podkop', 'ssclash', 'adguardhome'], request: Request, task_id: str | None = None):
    import hashlib
    from core.openwrt.operations import public_plan
    gateway(node_id)
    plan = await asyncio.to_thread(service_update_jobs.pending_review,node_id,service)
    if not plan:raise HTTPException(404,'Подготовленный план обновления не найден')
    if task_id and plan.get('preparation_task_id')!=task_id:raise HTTPException(404,'План относится к другой задаче подготовки обновления')
    if plan['owner_hash']!=hashlib.sha256(owner(request).encode()).hexdigest():raise HTTPException(403,'План обновления подготовлен в другом окне или на другом устройстве')
    return public_plan(plan)


@router.post('/{node_id}/services/{service}/plan')
async def operation_plan(node_id: str, service: Literal['dnsmasq', 'podkop', 'ssclash', 'adguardhome'], body: OperationBody, request: Request):
    from core.openwrt.operations import prepare
    try:
        return await prepare(gateway(node_id), owner(request), service, body.action,
            keep_backup=body.keep_backup, bundle_id=body.bundle_id, rollback_bundle_id=body.rollback_bundle_id, web_scope=body.web_scope)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post('/{node_id}/operations')
async def apply_operation(node_id: str, body: ApplyBody, request: Request):
    if not body.confirmed: raise HTTPException(400, 'Подтвердите показанный план операции')
    from core.openwrt.operations import enqueue
    try:
        task = await enqueue(gateway(node_id), body.plan_token, owner(request))
        return {'task_id': task.id, 'task': task_brief(task)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get('/status')
async def gateway_status():
    from core.openwrt.feature import stored_gateways
    nodes = await asyncio.to_thread(stored_gateways)
    return {'gateways': [{'id': node['id'], 'monitor': {key:value for key,value in snapshot(node['id']).items() if key != 'traffic_history'}, 'service_update_tasks': service_update_jobs.task_states(node['id'])} for node in nodes]}


@router.get("/{node_id}")
async def get_gateway(node_id: str):
    return public(gateway(node_id))


@router.get('/{node_id}/traffic')
async def gateway_traffic(node_id: str, seconds: int = 3600):
    from core.openwrt.monitor import traffic_series
    gateway(node_id)
    try: return {'seconds': seconds, 'traffic_history': traffic_series(node_id, seconds)}
    except ValueError as exc: raise HTTPException(400, str(exc)) from None


@router.get('/{node_id}/network')
async def network_configuration(node_id: str):
    from core.openwrt.network import configuration
    try: return await configuration(gateway(node_id))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get('/{node_id}/wireless')
async def wireless_configuration(node_id: str):
    from core.openwrt.wireless import configuration
    try: return await configuration(gateway(node_id))
    except ValueError as exc: raise HTTPException(400, str(exc)) from None


@router.post('/{node_id}/wireless/{radio}/scan')
async def wireless_scan(node_id: str, radio: str):
    from core.openwrt.wireless import scan
    try: return await scan(gateway(node_id), radio)
    except ValueError as exc: raise HTTPException(400, str(exc)) from None


@router.post('/{node_id}/network/plan')
async def network_plan(node_id: str, body: NetworkBody, request: Request):
    from core.openwrt.network import prepare
    try: return await prepare(gateway(node_id), owner(request), body.action, body.data)
    except ValueError as exc: raise HTTPException(400, str(exc)) from None


@router.get('/{node_id}/packages')
async def package_catalog(node_id: str, query: str = '', installed: bool = False, offset: int = 0):
    from core.openwrt.rpc import RpcClient
    from core.openwrt.operations import _check
    if len(query) > 100 or not 0 <= offset <= 100000: raise HTTPException(400, 'Некорректный поиск')
    rpc = RpcClient(gateway(node_id)['openwrt'])
    try: return _check(await rpc.call('bot4vps', 'package_catalog', {'query':query, 'installed':installed, 'offset':offset}))
    except ValueError as exc: raise HTTPException(400, str(exc)) from None
    finally: await rpc.close()


@router.post('/{node_id}/packages/plan')
async def package_plan(node_id: str, body: PackageBody, request: Request):
    import re
    from core.openwrt.router_operations import prepare
    if body.action == 'install' and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+~-]{0,99}', body.package):
        raise HTTPException(400, 'Некорректное имя пакета')
    try: return await prepare(gateway(node_id), owner(request), 'packages', body.action, {'package':body.package})
    except ValueError as exc: raise HTTPException(400, str(exc)) from None


@router.post('/{node_id}/router-operations')
async def apply_router_operation(node_id: str, body: ApplyBody, request: Request):
    if not body.confirmed: raise HTTPException(400, 'Подтвердите просмотренный план')
    from core.openwrt.router_operations import enqueue
    try:
        task = await enqueue(gateway(node_id), body.plan_token, owner(request))
        return {'task_id':task.id, 'task':task_brief(task)}
    except ValueError as exc: raise HTTPException(400, str(exc)) from None


@router.delete('/{node_id}/operation-plans/{token}')
async def cancel_operation_plan(node_id: str, token: str, request: Request):
    from core.openwrt.operations import cancel
    try:
        await cancel(gateway(node_id), token, owner(request))
        return {'ok':True}
    except ValueError as exc: raise HTTPException(400, str(exc)) from None


@router.get("/{node_id}/deletion-plan")
async def deletion_plan(node_id: str, request: Request):
    node = gateway(node_id)
    from core.openwrt.disconnect import prepare
    try:
        token = await prepare(node, owner(request))
    except ValueError as exc:
        raise HTTPException(409, 'Удаление остановлено на предварительной проверке; этап отзыва API не запускался. ' + str(exc)) from None
    steps = ['Проверить SSH-доступ, контрольные суммы файлов интеграции и оставшиеся подключения до отзыва API'] if node['openwrt'].get('managed') else []
    steps.append('Отозвать API-доступ Bot4VPS на роутере')
    if node['openwrt'].get('managed') and node['openwrt'].get('ssh'):
        steps.append('Если API недоступен, отозвать свой доступ через сохранённый SSH; вход пользователя по SSH сохраняется')
    steps.append('Проверить отзыв доступа')
    if node['openwrt'].get('managed'):
        steps.append('Через SSH удалить файлы интеграции и пункт LuCI Bot4VPS, если на роутере больше нет подключений Bot4VPS')
    steps.append('Удалить запись и сохранённые секреты из панели')
    return {"name": node['name'], "plan_token": token, "steps": steps,
        "preserved": ['Установленные службы', 'LAN, WAN и конфигурация роутера'],
        "manual": not node['openwrt'].get('managed', False)}


@router.delete("/{node_id}")
async def delete_gateway(node_id: str, body: DeleteBody, request: Request):
    node = gateway(node_id)
    if not body.confirmed:
        raise HTTPException(400, 'Подтвердите план отзыва API и удаления шлюза')
    from core.openwrt.disconnect import enqueue
    try:
        task = await enqueue(node, body.plan_token, owner(request))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {'task_id': task.id, 'task': task_brief(task)}


@router.post('/reserve/refresh')
async def refresh_reserve():
    from core.openwrt.bundle_jobs import enqueue_reserve
    nodes = await asyncio.to_thread(load_gateways)
    tasks, errors = [], []
    for node in nodes:
        try:
            tasks.append(await enqueue_reserve(node))
        except Exception as exc:
            errors.append({'gateway_id': node['id'], 'gateway_name': node['name'], 'error': str(exc)})
    return {'tasks': [task_brief(task) for task in tasks], 'gateways': len(nodes), 'errors': errors}


@router.post("/{node_id}/refresh")
async def refresh_gateway(node_id: str):
    node = gateway(node_id)
    await refresh(node)
    return public(node)


@router.put("/{node_id}/credentials")
async def replace_credentials(node_id: str, body: ManualBody):
    from core.storage import commit_server
    node = gateway(node_id)
    editing_allowed(node_id)
    try:
        previous_pin = node['openwrt'].get('tls_sha256')
        if previous_pin and body.tls_sha256 != previous_pin and not body.tls_pin_confirmed:
            raise ValueError('Сохранённый TLS-отпечаток изменяется. Явно подтвердите принятие нового сертификата или смену режима доверия.')
        if node['openwrt'].get('managed') and (urlsplit(body.url).hostname != node['host'] or body.username != node['openwrt']['username']):
            raise ValueError('Для другого роутера или учётной записи добавьте отдельный шлюз. Здесь обновляется секрет текущего доступа.')
        config = await manual_config(body)
        # Rotation through LuCI does not change ownership of the managed entry.
        config["managed"] = node["openwrt"].get("managed", False)
        for name in ("signing_private_key", "signing_key_id", "installed_components"):
            if node["openwrt"].get(name): config[name] = node["openwrt"][name]
        if node['openwrt'].get('ssh'): config['ssh'] = node['openwrt']['ssh']
        config["luci_path"] = node["openwrt"].get("luci_path", "/cgi-bin/luci/admin/services/bot4vps")
        editing_allowed(node_id)
        host = urlsplit(config['url']).hostname
        node.update(name=bootstrap.gateway_name(body.name, config['board'], host), host=host, openwrt=config, deletion_pending=False)
        if 'group' in body.model_fields_set: node['group'] = body.group
        node.pop('revocation_requested', None)
        commit_server(node)
        await refresh(node, force=True)
        return public(node)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("/{node_id}/logs")
async def logs(node_id: str):
    from core.openwrt.monitor import client_for
    from core.audit import mask_text
    try:
        rpc = await client_for(gateway(node_id))
        result = await rpc.call("bot4vps", "logs", {"lines": 100})
        return {"output": mask_text(result.get("output", ""))}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.put('/{node_id}/ssh')
async def save_ssh(node_id: str, body: SSHBody):
    from core.storage import commit_server, data_lock
    from core.install_paths import get_install_path
    node = gateway(node_id)
    editing_allowed(node_id)
    previous = node['openwrt'].get('ssh') or {}
    credentials = {'id': node['id'], 'name': node['name'], 'host': node['host'], 'user': body.user, 'port': body.port, 'auth_type': body.auth_type}
    if previous.get('host_key'): credentials['host_key'] = previous['host_key']
    if body.auth_type == 'password':
        credentials['password'] = body.password or (previous.get('password') if previous.get('auth_type') == 'password' else None)
        if not credentials['password']: raise HTTPException(400, 'Введите SSH-пароль')
    else:
        from pathlib import Path
        path = Path(body.key_path or previous.get('key_path') or '')
        keys = (get_install_path() / 'keys').resolve()
        if not path.is_absolute(): path = keys / path.name
        path = path.resolve()
        if not path.is_file() or path.parent != keys or path.name == 'secret.key' or path.name.startswith('registry.'):
            raise HTTPException(400, 'Выберите SSH-ключ из хранилища ключей панели')
        credentials['key_path'] = str(path)
    try:
        inspected = await asyncio.to_thread(bootstrap.inspect_target, credentials)
        if not inspected: raise ValueError('SSH не подтвердил OpenWrt')
        with data_lock():
            editing_allowed(node_id)
            current = gateway(node_id)
            if current['host'] != node['host']: raise ValueError('Адрес шлюза изменился; повторите проверку SSH')
            current['openwrt']['ssh'] = {key: credentials[key] for key in ('port', 'user', 'auth_type', 'password', 'key_path', 'host_key') if key in credentials}
            commit_server(current)
        return public(current)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from None


@router.get('/{node_id}/adguard')
async def adguard_guide(node_id: str):
    from core.openwrt.adguard import guide
    try: return await guide(gateway(node_id))
    except (ValueError, RpcError) as exc: raise HTTPException(400, str(exc)) from exc
