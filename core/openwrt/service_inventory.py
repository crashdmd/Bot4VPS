"""Versions explicitly confirmed for existing service binaries on a gateway."""
import asyncio
import hashlib
import json
import re
import threading
import time

from core.json_store import atomic_write_json, locked
from core.openwrt import bundles
from core.openwrt.rpc import RpcClient

_lock = threading.RLock()


def path_for(node_id, profile):
    if profile not in bundles.REPOS: raise ValueError('Сервис не поддерживается')
    key = hashlib.sha256(str(node_id).encode()).hexdigest()
    return bundles.ROOT / 'service-versions' / key / (profile + '.json')


def known(node_id, profile, fingerprint):
    if not re.fullmatch(r'[a-f0-9]{64}', fingerprint or ''): return None
    try:
        value = json.loads(path_for(node_id, profile).read_text())
        if isinstance(value, dict) and value.get('binary_sha256') == fingerprint and bundles._version(value.get('version', '')): return value['version']
    except (OSError, ValueError, TypeError): pass
    return None


def remember(node_id, profile, version, fingerprint):
    if not bundles._version(version): raise ValueError('Укажите установленную версию в формате 7.7.4')
    if not re.fullmatch(r'[a-f0-9]{64}', fingerprint or ''): raise ValueError('Установленный бинарный файл не определён')
    path = path_for(node_id, profile)
    with locked(path.with_suffix('.lock'), _lock):
        atomic_write_json(path, {'version': version.removeprefix('v'), 'binary_sha256': fingerprint,
                                'source': 'owner_confirmation', 'confirmed_at': int(time.time())})


async def confirm(node, profile, version, fingerprint):
    from core.openwrt.contract import check
    from core.openwrt.operations import namespace
    from core.openwrt.service_updates import active_task, update_lock
    if profile not in ('ssclash', 'adguardhome'): raise ValueError('Версия этого сервиса определяется пакетным менеджером')
    async with update_lock(node['id'], profile):
        if active_task(node['id'], profile): raise ValueError('Дождитесь завершения обновления сервиса')
        rpc = RpcClient(node['openwrt'])
        try:
            await check(rpc, namespace(node))
            info = await rpc.call('bot4vps', 'service_versions')
            state = info.get(profile) or {}
            if not state.get('installed'): raise ValueError('Сервис не установлен')
            if state.get('binary_sha256') != fingerprint: raise ValueError('Сервис изменился. Проверьте установленную версию заново.')
            if state.get('version') and bundles._version(state['version']) != bundles._version(version):
                raise ValueError('Шлюз уже определил другую установленную версию: ' + str(state['version']))
            await asyncio.to_thread(remember, node['id'], profile, version, fingerprint)
            return {'version': version.removeprefix('v')}
        finally: await rpc.close()
