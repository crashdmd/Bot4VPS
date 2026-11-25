"""Reviewed network/package jobs sharing the signed OpenWrt task transport."""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
from urllib.parse import urlsplit, urlunsplit

from core.json_store import atomic_write_json, locked
from core.openwrt.operations import PLANS, _plan_lock, _load, _check, _upload, namespace
from core.openwrt.rpc import RpcClient, RpcError
from core.openwrt.signing import sign
from core.task_manager import TaskResult, register_executor, task_manager

LABELS = {'wireless': 'Настройка Wi-Fi', 'dhcp': 'Настройка DHCP', 'dns': 'Настройка DNS', 'firewall': 'Настройка firewall', 'firewall_restart': 'Перезапуск firewall', 'edit': 'Настройка интерфейса', 'delete': 'Удаление интерфейса', 'routes': 'Настройка маршрутов',
    'up': 'Подключение', 'down': 'Отключение', 'reconnect': 'Переподключение',
    'refresh': 'Обновление списка пакетов', 'install': 'Установка пакета'}


def config_hash(node):
    return hashlib.sha256(json.dumps(node['openwrt'], sort_keys=True).encode()).hexdigest()


def new_endpoint(node, remote):
    before, after = remote.get('api_host'), remote.get('new_api_host')
    if not after or before == after: return node['openwrt']['url']
    address = urlsplit(node['openwrt']['url'])
    authority = '[' + after + ']' if ':' in after else after
    if address.port: authority += ':' + str(address.port)
    return urlunsplit((address.scheme, authority, address.path, '', ''))


async def prepare(node, owner, kind, action, data):
    if kind not in ('network', 'packages') or action not in LABELS: raise ValueError('Операция не поддерживается')
    rpc = RpcClient(node['openwrt']); nonce = secrets.token_hex(16); token = secrets.token_urlsafe(32)
    try:
        from core.openwrt.contract import check
        await check(rpc,namespace(node))
        if kind == 'network' and action == 'firewall' and ('redirects' in data or 'deleted_redirects' in data):
            configuration = _check(await rpc.call('bot4vps', 'network'))
            if not isinstance(configuration.get('firewall', {}).get('redirects'), list):
                raise ValueError('Обновите интеграцию Bot4VPS на шлюзе для управления перенаправлениями портов')
        if kind == 'network' and action == 'wireless':
            from core.openwrt.wireless import validate_hardware
            await validate_hardware(rpc, data)
        remote = _check(await rpc.call(namespace(node), 'plan', {'kind': kind, 'action': action,
            'nonce': nonce, 'data': json.dumps(data, ensure_ascii=False, separators=(',', ':'))}))
        record = {'token': token, 'owner_hash': hashlib.sha256(owner.encode()).hexdigest(), 'node_id': node['id'],
            'nonce': nonce, 'remote': remote, 'config_hash': config_hash(node), 'service': kind,
            'action': action, 'expires': time.time() + 900, 'started': False}
        # Native replies contain fingerprints and redacted summaries, never UCI secrets.
        PLANS.mkdir(parents=True, exist_ok=True); atomic_write_json(PLANS / (token + '.json'), record)
        return {'plan_token': token, 'kind': kind, 'action': action, 'title': LABELS[action],
            'summary': remote.get('summary', []), 'warnings': remote.get('warnings', []), 'interface': remote.get('interface'),
            'package': remote.get('package'), 'new_api_host': remote.get('new_api_host'),
            'address_changes': remote.get('api_host') != remote.get('new_api_host') if kind == 'network' else False,
            'rollback_seconds': 120 if kind == 'network' else None,
            'package_scripts': kind == 'packages' and action == 'install'}
    finally: await rpc.close()


async def enqueue(node, token, owner):
    with locked(PLANS / '.claim.lock', _plan_lock):
        record = _load(token)
        if record.get('service') not in ('network', 'packages'): raise ValueError('Неверный тип плана')
        if record['node_id'] != node['id'] or record['owner_hash'] != hashlib.sha256(owner.encode()).hexdigest():
            raise ValueError('План принадлежит другому подключению')
        if record['expires'] < time.time(): raise ValueError('План истёк. Проверьте изменения заново.')
        if record['started'] or record.get('closed'): raise ValueError('Операция уже запущена или план отменён')
        if config_hash(node) != record['config_hash']: raise ValueError('Доступ изменился. Подготовьте новый план.')
        record['started'] = True; atomic_write_json(PLANS / (token + '.json'), record)
    try:
        return await task_manager.enqueue(name=LABELS[record['action']] + ' ' + (record['remote'].get('interface') or record['remote'].get('package') or ''),
            server_id=node['id'], server_name=node['name'], kind='openwrt-router-operation', payload={'plan_token': token}, live_reported=True)
    except BaseException:
        with locked(PLANS / '.claim.lock', _plan_lock):
            record = _load(token)
            record['started'] = False; atomic_write_json(PLANS / (token + '.json'), record)
        raise


async def _verify_network(node, record, rpc):
    remote = record['remote']
    if new_endpoint(node, remote) != node['openwrt']['url'] and rpc.url != new_endpoint(node, remote):
        return False
    state = _check(await rpc.call('bot4vps', 'network'))
    if remote.get('configs'):
        if remote.get('reload') == 'dnsmasq':
            health = _check(await rpc.call('bot4vps', 'status'))
            if not health.get('services', {}).get('dnsmasq', {}).get('running'): return False
        if remote.get('reload') == 'wireless':
            wireless = _check(await rpc.call('bot4vps', 'wireless'))
            radio = next((r for r in wireless.get('radios', []) if r.get('name') == remote.get('radio')), None)
            if not radio or radio.get('pending'): return False
            expected_up = radio.get('disabled') != '1' and any(i.get('disabled') != '1' for i in radio.get('interfaces', []))
            if bool(radio.get('up')) != expected_up: return False
            if expected_up and any(i.get('disabled') != '1' and not i.get('ifname') for i in radio.get('interfaces', [])): return False
        fingerprints = state.get('config_hashes', {})
        if any(fingerprints.get(item['name']) != item['after'] for item in remote['configs']): return False
    if remote.get('after_hash') and state.get('config_hash') != remote['after_hash']: return False
    if record['action'] in ('up', 'down', 'reconnect'):
        interface = next((item for item in state.get('interfaces', []) if item['name'] == remote['interface']), None)
        if not interface or bool(interface.get('up')) != (record['action'] != 'down'): return False
    from core.storage import find_server
    current = find_server(node['id'])
    if not current or config_hash(current) != record['config_hash']:
        raise ValueError('Доступ к шлюзу изменился. Сетевая операция будет восстановлена роутером.')
    from core.node_types import load_gateways
    destination = urlsplit(new_endpoint(node, remote)).hostname
    if any(item['id'] != node['id'] and item['host'] == destination for item in load_gateways()):
        raise ValueError('Новый адрес уже занят другой записью. Роутер восстановит прежнюю сеть.')
    return True


def _commit_new_address(node, record):
    new_url = new_endpoint(node, record['remote'])
    if new_url == node['openwrt']['url']: return node
    from core.storage import data_lock, find_server, commit_server
    from core.node_types import load_gateways
    with data_lock():
        current = find_server(node['id'])
        if not current or config_hash(current) != record['config_hash']:
            raise ValueError('Сеть применена, но доступ в панели изменён параллельно. Проверьте адрес шлюза.')
        host = urlsplit(new_url).hostname
        if any(item['id'] != node['id'] and item['host'] == host for item in load_gateways()):
            raise ValueError('Сеть применена, но новый адрес уже занят другой записью шлюза.')
        current['host'] = host; current['openwrt']['url'] = new_url
        commit_server(current)
        return current


async def execute(payload, task, progress):
    from core.storage import find_server
    node = find_server(task.server_id)
    if not node or node.get('node_type') != 'openwrt': return TaskResult(False, error='Шлюз не найден')
    clients = []
    try:
        record = _load(payload['plan_token'])
        if config_hash(node) != record['config_hash']: raise ValueError('Доступ изменился. Подготовьте новый план.')
        object_name = namespace(node); nonce = record['nonce']
        original = RpcClient(node['openwrt']); clients.append(original)
        urls = list(dict.fromkeys([new_endpoint(node, record['remote']), node['openwrt']['url']]))
        candidates = []
        for url in urls:
            candidate = RpcClient({**node['openwrt'], 'url': url}); clients.append(candidate); candidates.append(candidate)
        message = {'username': node['openwrt']['username'], 'nonce': nonce, 'service': record['service'],
            'action': record['action'], 'expected': record['remote']['expected'], 'expires': record['expires']}
        raw = json.dumps(message, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
        await progress('Передаю подтверждённый подписанный план…')
        await _upload(original, object_name, nonce, 'manifest.json', raw, progress)
        await _upload(original, object_name, nonce, 'manifest.sig', sign(node['openwrt'], raw).encode(), progress)
        try: _check(await original.call(object_name, 'apply', {'nonce': nonce}))
        except RpcError as exc:
            if exc.code != 'connection': raise
            await progress('Ответ потерян. Проверяю запущенную операцию; повтор не выполняется.')
        offset = 0; confirmed = False; deadline = time.monotonic() + 360
        while time.monotonic() < deadline:
            state = None; reachable = None
            for candidate in candidates:
                try:
                    state = _check(await candidate.call(object_name, 'job', {'nonce': nonce})); reachable = candidate; break
                except RpcError as exc:
                    if exc.code not in ('connection', 'response'): raise
            if state is None:
                await asyncio.sleep(2); continue
            output = state.get('output', '')
            for line in output[offset:].splitlines(): await progress(line)
            offset = len(output)
            if state.get('phase') == 'verify' and not confirmed:
                for candidate in candidates:
                    try:
                        if await _verify_network(node, record, candidate):
                            _check(await candidate.call(object_name, 'confirm', {'nonce': nonce})); confirmed = True
                            await progress('Конфигурация UCI и доступность API проверены. Подтверждение отправлено роутеру.')
                            break
                    except RpcError: continue
            if state.get('phase') == 'success':
                if record['service'] == 'network':
                    # A confirm may reach the router while its response is lost.
                    # Success must be reconciled with a fresh read at the new URL.
                    verified = False
                    for candidate in candidates:
                        try:
                            if await _verify_network(node, record, candidate): verified = True; break
                        except RpcError: continue
                    if not verified: raise ValueError('Результат сети не прошёл конечную сверку. Проверьте журнал и адрес подключения.')
                    node = _commit_new_address(node, record)
                from core.openwrt.monitor import refresh
                await refresh(node, force=True)
                try: _check(await reachable.call(object_name, 'cleanup', {'nonce': nonce}))
                except RpcError: await progress('Временные файлы будут очищены позже.')
                return TaskResult(True, output=output)
            if state.get('phase') in ('failed', 'rolled_back'):
                try: await reachable.call(object_name, 'cleanup', {'nonce':nonce})
                except RpcError: pass
                return TaskResult(False, output=output, error=state.get('error') or 'Изменение не подтверждено')
            await asyncio.sleep(1)
        return TaskResult(False, error='Результат не подтверждён. Повторное выполнение отключено; проверьте журнал и доступность роутера.')
    except Exception as exc:
        return TaskResult(False, error=str(exc))
    finally:
        for client in clients: await client.close()


register_executor('openwrt-router-operation', execute)
