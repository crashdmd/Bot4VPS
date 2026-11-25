"""Signed, reviewed operations with live output and router-side recovery."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import time
import threading

from core.install_paths import get_install_path
from core.json_store import atomic_write_json, locked
from core.task_manager import TaskResult, register_executor, task_manager
from core.openwrt.rpc import RpcClient, RpcError
from core.openwrt import bundles
from core.openwrt.signing import sign

PLANS = get_install_path() / 'data/openwrt-operation-plans'
_plan_lock = threading.RLock()


def namespace(node):
    username = node['openwrt']['username']
    if not username.startswith('bot4vps_') or not node['openwrt'].get('signing_private_key'):
        raise ValueError('Для управления требуется настроить отдельный доступ Bot4VPS через мастер подключения')
    return 'bot4vps-key-' + username[8:]


def _check(result):
    if not isinstance(result, dict): raise RpcError('Некорректная структура ответа API', 'response')
    if result.get('error'):
        raise ValueError(result['error'])
    return result


async def prepare(node, owner, service, action, *, keep_backup=True, bundle_id=None, rollback_bundle_id=None, web_scope=None):
    if action == 'update':
        from core.openwrt.service_updates import update_lock, active_task, pending_review
        async with update_lock(node['id'], service):
            if active_task(node['id'], service) or await asyncio.to_thread(pending_review, node['id'], service):
                raise ValueError('Обновление этого сервиса уже выполняется или ожидает подтверждения')
            return await _prepare(node, owner, service, action, keep_backup=keep_backup, bundle_id=bundle_id, rollback_bundle_id=rollback_bundle_id, web_scope=web_scope)
    return await _prepare(node, owner, service, action, keep_backup=keep_backup, bundle_id=bundle_id, rollback_bundle_id=rollback_bundle_id, web_scope=web_scope)


async def _prepare(node, owner, service, action, *, keep_backup=True, bundle_id=None, rollback_bundle_id=None, web_scope=None, owner_hash=None, expected_binary_hash=None, preparation_task_id=None):
    if service not in ('podkop', 'ssclash', 'dnsmasq', 'adguardhome') or action not in ('start', 'stop', 'restart', 'remove', 'install', 'update', 'web_access'):
        raise ValueError('Операция не разрешена')
    if action == 'web_access' and (service != 'ssclash' or web_scope not in ('lan', 'wan')):
        raise ValueError('Выберите LAN или WAN для управляемого SSClash')
    if service == 'dnsmasq' and action in ('remove', 'install', 'update'):
        raise ValueError('Удаление системного dnsmasq не поддерживается')
    rpc = RpcClient(node['openwrt'])
    nonce = secrets.token_hex(16)
    token = secrets.token_urlsafe(32)
    prepared = False
    remote_prepared = False
    try:
        from core.openwrt.contract import check
        await check(rpc, namespace(node))
        arguments = {'service': service, 'action': action, 'nonce': nonce, 'api_host': __import__('urllib.parse', fromlist=['urlsplit']).urlsplit(node['openwrt']['url']).hostname}
        if action == 'web_access': arguments['web_scope'] = web_scope
        remote = _check(await rpc.call(namespace(node), 'plan', arguments))
        remote_prepared = True
        if expected_binary_hash and remote.get('binary_hash') != expected_binary_hash:
            raise ValueError('Служба изменилась во время подготовки обновления. Проверьте её версию и подготовьте новый план.')
        files = []; changes = []; rollback_files = []; version = None
        if action in ('install', 'update'):
            await asyncio.to_thread(bundles.pin, bundle_id, token, time.time() + 3600)
            bundle = await asyncio.to_thread(bundles.lookup, bundle_id)
            if bundle['profile'] != service or bundle['platform']['architecture'] != remote['architecture'] or bundle['platform']['kernel'] != remote['kernel']:
                raise ValueError('Комплект не совпадает с архитектурой и ABI ядра роутера')
            if remote.get('manager') and bundle['platform']['manager'] != remote['manager']:
                raise ValueError('Пакетный менеджер комплекта не совпадает с роутером')
            version = bundle['version']
            inventory = await rpc.call('bot4vps', 'packages')
            installed = dict(line.split(' - ', 1) for line in inventory.get('output', '').splitlines() if ' - ' in line)
            files = await asyncio.to_thread(bundles.install_files, bundle, installed)
            changes = [{'package': f['package'], 'before': installed.get(f['package']), 'after': f['version']}
                       for f in files if f.get('package') and installed.get(f['package']) != f['version']]
            if action == 'update' and service == 'podkop':
                await asyncio.to_thread(bundles.pin, rollback_bundle_id, token+'-rollback', time.time()+3600)
                old = await asyncio.to_thread(bundles.lookup, rollback_bundle_id)
                if old['profile'] != service or old['platform'] != bundle['platform']:
                    raise ValueError('Резерв отката не соответствует платформе обновления')
                rollback_files = [item for item in old['files'] if item.get('role') == 'package' and
                                  installed.get(item.get('package')) == item.get('version')]
                if not any(item.get('package') == 'podkop' and item.get('version') == installed.get('podkop') for item in rollback_files):
                    raise ValueError('Комплект отката не совпадает с установленной версией Podkop')
                for item in files:
                    name = item.get('package')
                    if name and installed.get(name) and not any(old_item.get('package') == name and old_item.get('version') == installed[name] for old_item in rollback_files):
                        raise ValueError('В комплекте отката нет установленной версии пакета ' + name)

        config_hash = hashlib.sha256(json.dumps(node['openwrt'], sort_keys=True).encode()).hexdigest()
        record = {'token': token, 'owner_hash': owner_hash or hashlib.sha256(owner.encode()).hexdigest(), 'node_id': node['id'],
            'nonce': nonce, 'remote': remote, 'config_hash': config_hash, 'service': service, 'action': action,
            'keep_backup': keep_backup, 'bundle_id': bundle_id, 'files': files, 'changes': changes,
            'version': version, 'rollback_files': rollback_files, 'preparation_task_id': preparation_task_id,
            'expires': time.time() + 900, 'started': False}
        PLANS.mkdir(parents=True, exist_ok=True); atomic_write_json(PLANS / (token + '.json'), record)
        prepared = True
        if action == 'update':
            await asyncio.to_thread(bundles.unpin, 'update-'+node['id']+'-'+service)
            await asyncio.to_thread(bundles.unpin, 'update-'+node['id']+'-'+service+'-new')
        return public_plan(record)
    finally:
        if not prepared and remote_prepared:
            try: await rpc.call(namespace(node), 'cleanup', {'nonce': nonce})
            except Exception: pass  # A lost reply leaves only an expiring prepared job.
        await rpc.close()
        if not prepared:
            await asyncio.to_thread(bundles.unpin, token)
            await asyncio.to_thread(bundles.unpin, token+'-rollback')
            if action == 'update': await asyncio.to_thread(bundles.unpin, 'update-'+node['id']+'-'+service)
            if action == 'update': await asyncio.to_thread(bundles.unpin, 'update-'+node['id']+'-'+service+'-new')


def public_plan(record):
    return {'plan_token': record['token'], 'node_id': record['node_id'], 'service': record['service'], 'action': record['action'],
        'root': record['remote']['root'], 'removed': record['remote']['removed'],
        'preserved': record['remote']['preserved'], 'keep_backup': record['keep_backup'],
        'changes': record['changes'], 'files': [{'name': f['name'], 'size': f['size']} for f in record['files']],
        'version': record.get('version'), 'preparation_task_id': record.get('preparation_task_id'), 'web_scope': record['remote'].get('web_scope'), 'warnings': record['remote'].get('warnings', []),
        'network_check': record['action'] in ('start', 'stop', 'restart', 'remove', 'update', 'web_access')}


def _load(token):
    if not isinstance(token, str) or len(token) != 43 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in token):
        raise ValueError('Некорректный план')
    path = PLANS / (token + '.json')
    if not path.is_file(): raise ValueError('План не найден')
    return json.loads(path.read_text())


async def enqueue(node, token, owner):
    record = await asyncio.to_thread(_load, token)
    if record.get('action') == 'update':
        from core.openwrt.service_updates import update_lock
        async with update_lock(node['id'], record['service']):
            return await _enqueue(node, token, owner)
    return await _enqueue(node, token, owner)


async def _enqueue(node, token, owner):
    with locked(PLANS / '.claim.lock', _plan_lock):
        record = _load(token)
        if record['node_id'] != node['id'] or record['owner_hash'] != hashlib.sha256(owner.encode()).hexdigest() or record['expires'] < time.time():
            raise ValueError('План истёк или принадлежит другому подключению')
        if record['started'] or record.get('closed'): raise ValueError('Операция уже запущена или план отменён')
        record['started'] = True; atomic_write_json(PLANS / (token + '.json'), record)
    try:
        return await task_manager.enqueue(name={'install': 'Установка', 'update': 'Обновление', 'web_access': 'Доступ веб-панели', 'remove': 'Удаление', 'start': 'Запуск', 'stop': 'Остановка', 'restart': 'Перезапуск'}[record['action']] + ' ' + record['service'],
            server_id=node['id'], server_name=node['name'], kind='openwrt-operation', payload={'plan_token': token, 'service': record['service'], 'action': record['action']}, live_reported=True)
    except BaseException:
        with locked(PLANS / '.claim.lock', _plan_lock):
            record = _load(token)
            record['started'] = False; atomic_write_json(PLANS / (token + '.json'), record)
        raise


async def cancel(node, token, owner):
    with locked(PLANS / '.claim.lock', _plan_lock):
        record = _load(token)
        if record['node_id'] != node['id'] or record['owner_hash'] != hashlib.sha256(owner.encode()).hexdigest():
            raise ValueError('План принадлежит другому подключению')
        if record['started']: raise ValueError('Операция уже выполняется')
        record['closed'] = True
        atomic_write_json(PLANS / (token + '.json'), record)
    rpc = RpcClient(node['openwrt'])
    try:
        _check(await rpc.call(namespace(node), 'cleanup', {'nonce':record['nonce']}))
        (PLANS / (token + '.json')).unlink(missing_ok=True)
        await asyncio.to_thread(bundles.unpin, token)
        await asyncio.to_thread(bundles.unpin, token+'-rollback')
    finally: await rpc.close()


_UPLOAD_CHUNK_BYTES = 40 * 1024


async def _upload(rpc, object_name, nonce, name, data, progress):
    async def send(chunk, append):
        _check(await rpc.call(object_name, 'upload', {'nonce': nonce, 'name': name,
            'data': base64.b64encode(chunk).decode(), 'append': append}))
    if isinstance(data, bytes):
        for offset in range(0, len(data), _UPLOAD_CHUNK_BYTES):
            await send(data[offset:offset + _UPLOAD_CHUNK_BYTES], offset > 0)
        return
    path = data
    done = 0; next_report = 2 * 1024 * 1024
    started = time.monotonic(); last_report = started
    total = path.stat().st_size
    with path.open('rb') as source:
        # 40 KiB becomes 53.4 KiB in base64, leaving room for JSON within
        # the common 64 KiB ubus frame limit. Await each append in order.
        while chunk := source.read(_UPLOAD_CHUNK_BYTES):
            await send(chunk, done > 0); done += len(chunk)
            now = time.monotonic()
            if done >= next_report or now-last_report >= 2 or done == total:
                speed = done / (1024 * 1024) / max(now-started, .001)
                await progress(f'Передаю {name}: {done / (1024 * 1024):.1f} / {total / (1024 * 1024):.1f} МБ · {speed:.1f} МБ/с')
                next_report = done + 2 * 1024 * 1024
                last_report = now


async def _upload_payloads(node, rpc, object_name, nonce, payloads, progress):
    from core.openwrt import ssh_transfer
    ssh = await asyncio.to_thread(ssh_transfer.connect_root, node)
    await progress('Передача файлов: root SSH.' if ssh else 'Root SSH недоступен. Передаю файлы через API.')
    try:
        for name, data in payloads:
            if ssh is not None:
                try:
                    await ssh_transfer.upload_async(ssh, node['openwrt']['username'], nonce, name, data, progress)
                    continue
                except ssh_transfer.SshUnavailable:
                    await asyncio.to_thread(ssh.close)
                    ssh = None
                    # The signed operation is still prepared. API starts this
                    # file with append=false. SSH writes a separate temporary
                    # file and can publish it only after verifying its hash
                    # while the operation is still prepared.
                    await progress('Root SSH прервался. Продолжаю передачу файлов через API.')
            try:
                await _upload(rpc, object_name, nonce, name, data, progress)
            except RpcError as exc:
                raise RpcError('Root SSH недоступен; передача через API не удалась: ' + str(exc), exc.code) from exc
    finally:
        if ssh is not None:
            await asyncio.to_thread(ssh.close)


async def execute(payload, task, progress):
    from core.storage import find_server
    node = find_server(task.server_id)
    if not node or node.get('node_type') != 'openwrt': return TaskResult(False, error='Шлюз не найден')
    rpc = None
    try:
        record = _load(payload['plan_token'])
        actual_hash = hashlib.sha256(json.dumps(node['openwrt'], sort_keys=True).encode()).hexdigest()
        if actual_hash != record['config_hash']: raise ValueError('Настройки API изменились. Подготовьте новый план операции.')
        rpc = RpcClient(node['openwrt']); object_name = namespace(node); nonce = record['nonce']
        previous = _check(await rpc.call(object_name, 'job', {'nonce': nonce}))
        if previous.get('phase') == 'prepared':
            message = {'username': node['openwrt']['username'], 'nonce': nonce, 'service': record['service'],
                'action': record['action'], 'expected': record['remote']['expected'], 'keep_backup': record['keep_backup'],
                'files': record['files'], 'rollback_files': record.get('rollback_files', []),
                'version': record.get('version'), 'web_scope': record['remote'].get('web_scope'), 'was_running': record['remote'].get('running', False), 'expires': record['expires']}
            raw = json.dumps(message, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
            await progress('Передаю подписанный план операции…')
            payloads = [('manifest.json', raw), ('manifest.sig', sign(node['openwrt'], raw).encode())]
            payloads += [(item['name'], bundles.object_path(item['sha256']))
                         for item in record['files'] + record.get('rollback_files', [])]
            await _upload_payloads(node, rpc, object_name, nonce, payloads, progress)
            await progress('Запускаю проверку подписи и выполнение на роутере…')
            try:
                _check(await rpc.call(object_name, 'apply', {'nonce': nonce}))
            except RpcError as exc:
                if exc.code != 'connection': raise
                await progress('Ответ потерян. Проверяю уже запущенную операцию; повтор не выполняется…')
        offset = 0; confirmed = False; verification_failed = False; deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            try:
                state = await rpc.call(object_name, 'job', {'nonce': nonce})
                if not state.get('phase'):
                    _check(state)
            except RpcError as exc:
                if exc.code == 'connection':
                    await asyncio.sleep(2); continue
                raise
            output = state.get('output', '')
            for line in output[offset:].splitlines(): await progress(line)
            offset = len(output)
            phase = state.get('phase')
            if phase == 'verify' and not confirmed and not verification_failed:
                await progress('Проверяю результат новым HTTPS-подключением…')
                verification = RpcClient(node['openwrt'])
                try:
                    health = await verification.call('bot4vps', 'status')
                    running = health.get('services', {}).get(record['service'], {}).get('running')
                    wanted = record['remote'].get('running', False) if record['action'] in ('update', 'web_access') else record['action'] in ('start', 'restart')
                    scope_matches = record['action'] != 'web_access' or health.get('services', {}).get('ssclash', {}).get('web_scope') == record['remote'].get('web_scope')
                    if bool(running) != wanted or not scope_matches:
                        verification_failed = True
                        await progress('Состояние службы не подтверждено. Ожидаю восстановления на роутере…')
                    else:
                        _check(await verification.call(object_name, 'confirm', {'nonce': nonce})); confirmed = True
                        await progress('API доступен, результат проверен.')
                except RpcError as exc:
                    if exc.code != 'connection': raise
                    await progress('Ответ подтверждения потерян. Сверяю конечное состояние операции…')
                finally: await verification.close()
            if phase == 'success':
                if record['action'] != 'install':
                    verification = RpcClient(node['openwrt'])
                    try:
                        health = await verification.call('bot4vps','status')
                        wanted = record['remote'].get('running', False) if record['action'] == 'update' else record['action'] in ('start','restart')
                        if bool(health.get('services',{}).get(record['service'],{}).get('running')) != wanted:
                            raise ValueError('Конечное состояние службы не совпадает с планом. Проверьте журнал.')
                    finally: await verification.close()
                from core.openwrt.monitor import refresh
                await refresh(node, force=True)
                try:
                    _check(await rpc.call(object_name, 'cleanup', {'nonce': nonce}))
                except RpcError:
                    await progress('Временные файлы операции будут очищены при следующем подключении.')
                await asyncio.to_thread(bundles.unpin, record['token'])
                await asyncio.to_thread(bundles.unpin, record['token']+'-rollback')
                return TaskResult(True, output=output)
            if phase in ('failed', 'rolled_back'):
                try:
                    await rpc.call(object_name, 'cleanup', {'nonce': nonce})
                except RpcError:
                    pass
                await asyncio.to_thread(bundles.unpin, record['token'])
                await asyncio.to_thread(bundles.unpin, record['token']+'-rollback')
                return TaskResult(False, output=output, error=state.get('error') or 'Операция не завершена')
            await asyncio.sleep(1)
        return TaskResult(False, error='Результат не подтверждён. Проверьте состояние операции и журнал; автоматический повтор отключён.')
    except Exception as exc:
        return TaskResult(False, error=str(exc))
    finally:
        if rpc: await rpc.close()


register_executor('openwrt-operation', execute)
