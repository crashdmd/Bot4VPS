"""Optional OpenWrt management, including transport shutdown when disabled."""
from __future__ import annotations

import asyncio
import weakref

_rpc_clients = weakref.WeakSet()
_ssh_clients = weakref.WeakSet()


def stored_gateways():
    from core.storage import load_data
    return [node for node in load_data(decrypt_passwords=False).get('servers', [])
        if isinstance(node, dict) and node.get('node_type') == 'openwrt']


def enabled():
    from core.config import _read_config_raw
    try:
        raw = _read_config_raw()
        if 'openwrt_enabled' in raw: return raw['openwrt_enabled'] is True
        # Existing installations keep their connected gateways. New ones opt in.
        return bool(stored_gateways())
    except Exception:
        return False


def require_enabled():
    if not enabled():
        from core.openwrt.rpc import RpcError
        raise RpcError('Управление OpenWrt выключено в Настройки → Параметры', 'disabled')


def gateway_profile(connection):
    if connection.get('_gateway_node_id'): return True
    for node in stored_gateways():
        if connection.get('id') == node.get('id'): return True
        ssh = node.get('openwrt',{}).get('ssh') or {}
        if connection.get('host') == node.get('host') and int(connection.get('port') or 22) == int(ssh.get('port') or 22): return True
    return False


def register_rpc(client):
    require_enabled(); _rpc_clients.add(client)


def register_ssh(client):
    require_enabled(); _ssh_clients.add(client)


def state():
    nodes = stored_gateways()
    return {'enabled':enabled(), 'gateways':len(nodes),
        'names':[node.get('name','Шлюз') for node in nodes], 'ssh_connections':len(_ssh_clients)}


async def set_enabled(value, confirmed=False):
    from core.config import _patch_config_keys
    from core.task_manager import task_manager
    from core.audit import record, AuditAction, AuditResult
    nodes = stored_gateways()
    if not value and nodes and not confirmed:
        raise ValueError('Подтвердите остановку запросов и подключений ко всем добавленным шлюзам')
    # Bootstrap owns account creation/cleanup; interrupting it could leave an orphan.
    if not value:
        running = [task for task in task_manager._running.values()
            if not task.is_done and task.kind in ('openwrt-bootstrap','openwrt-bootstrap-finalize','openwrt-router-operation','openwrt-operation','openwrt-disconnect','openwrt-integration-update','openwrt-backup')]
        if running: raise ValueError('Дождитесь завершения текущей операции подключения, сети, служб или удаления шлюза перед выключением управления')
    _patch_config_keys({'openwrt_enabled':bool(value)})
    if not value:
        for node in nodes:
            tasks = [task_manager.get_running(node['id']), *task_manager.get_queue(node['id'])]
            for task in tasks:
                if task and not task.is_done:
                    await task_manager.cancel(task.id)
                    if task.kind == 'openwrt-backup':
                        from core.openwrt.backups import cancel_queued
                        try: await asyncio.to_thread(cancel_queued, task)
                        except ValueError: pass  # Missing/corrupt drafts must not prevent transport shutdown.
        from core.openwrt.monitor import close_clients
        await close_clients()
        for client in list(_rpc_clients): await client.close()
        for client in list(_ssh_clients): await asyncio.to_thread(client.close)
        _ssh_clients.clear(); _rpc_clients.clear()
    record(AuditAction.SETTINGS_UPDATE,result=AuditResult.OK,
        params={'openwrt_enabled':bool(value),'gateways':len(nodes)})
    return state()
