"""Shared OpenWrt configuration archives and explicitly reviewed restoration."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import tempfile
import time

from core.json_store import atomic_write_json, locked
from core.openwrt import backup_archive, backup_store
from core.openwrt.contract import check
from core.openwrt.operations import PLANS, _plan_lock, _load, _check, _upload, namespace
from core.openwrt.rpc import RpcClient, RpcError
from core.openwrt.router_operations import config_hash
from core.openwrt.signing import sign
from core.task_manager import TaskResult, register_executor, task_manager


def active_task(node_id):
    return next((task for task in [task_manager.get_running(node_id), *task_manager.get_queue(node_id)]
                 if task and not task.is_done and task.kind == 'openwrt-backup'), None)


def _status_path(node_id):
    return backup_store.ROOT / 'status' / (hashlib.sha256(node_id.encode()).hexdigest() + '.json')


def reboot_required(node_id):
    try: state = json.loads(_status_path(node_id).read_text())
    except (OSError, ValueError): return False
    if state.get('reboot_required') is not True: return False
    from core.openwrt.monitor import snapshot
    current = snapshot(node_id).get('boot_id')
    if current and state.get('boot_id') and current != state['boot_id']:
        set_reboot_required(node_id, False, current)
        return False
    return True


def set_reboot_required(node_id, value, boot_id=None):
    atomic_write_json(_status_path(node_id), {'reboot_required': value, 'boot_id': boot_id, 'at': time.time()})


async def enqueue_create(node):
    pending = active_task(node['id'])
    if pending:
        if pending.payload.get('action') == 'create': return pending
        raise ValueError('На шлюзе выполняется восстановление или перезагрузка')
    return await task_manager.enqueue(name='Резервная копия настроек OpenWrt', server_id=node['id'],
        server_name=node['name'], kind='openwrt-backup', payload={'action': 'create'}, live_reported=True)


async def prepare(node, owner, action, archive_id=None):
    if action not in ('restore', 'reboot'): raise ValueError('Действие не поддерживается')
    if active_task(node['id']): raise ValueError('Дождитесь завершения операции резервного копирования шлюза')
    token = secrets.token_urlsafe(32); nonce = secrets.token_hex(16)
    info = None; archive = None; pinned = False; remote_prepared = False
    rpc = RpcClient(node['openwrt'])
    try:
        data = {}
        if action == 'restore':
            path, archive = await asyncio.to_thread(backup_store.download, archive_id, verify=True)
            await asyncio.to_thread(backup_store.pin, archive_id, nonce, time.time() + 900)
            pinned = True
            info = await asyncio.to_thread(backup_archive.inspect, path)
            data = {'sha256': archive['sha256'], 'size': archive['size'],
                    'entries': info['entries'], 'unpacked_size': info['unpacked_size']}
        raw = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
        if len(raw.encode()) > 49152: raise ValueError('В архиве слишком много путей для одного плана восстановления')
        await check(rpc, namespace(node))
        remote = _check(await rpc.call(namespace(node), 'plan', {'kind': 'backup', 'action': action, 'nonce': nonce, 'data': raw}))
        remote_prepared = True
        record = {'token': token, 'owner_hash': hashlib.sha256(owner.encode()).hexdigest(), 'node_id': node['id'],
                  'nonce': nonce, 'service': 'backup', 'action': action, 'archive_id': archive_id,
                  'archive_sha256': archive['sha256'] if archive else None, 'remote': remote,
                  'expires': time.time() + 900, 'started': False, 'config_hash': config_hash(node)}
        PLANS.mkdir(parents=True, exist_ok=True); atomic_write_json(PLANS / (token + '.json'), record)
        warnings = ['Сеть, Wi-Fi и доступ после перезагрузки будут определяться настройками из архива. Адрес, секрет API и сертификат HTTPS могут измениться; может потребоваться повторное подключение шлюза.']
        if action == 'restore':
            warnings += ['Перед применением на панели будет сохранена штатная защитная копия текущих настроек.',
                         'Архивы общие для всех шлюзов. Проверьте соответствие интерфейсов и настроек выбранному роутеру.',
                         'Прошивка и установленные пакеты не восстанавливаются. После записи файлов перезагрузка подтверждается отдельно.']
        return {'plan_token': token, 'node_id': node['id'], 'action': action,
                'filename': archive['filename'] if archive else None, 'files': info['files'] if info else None,
                'warnings': warnings}
    except BaseException:
        if pinned: await asyncio.to_thread(backup_store.unpin, nonce)
        if remote_prepared:
            try: await rpc.call(namespace(node), 'cleanup', {'nonce': nonce})
            except Exception: pass
        raise
    finally: await rpc.close()


def cancel(node, token, owner):
    with locked(PLANS / '.claim.lock', _plan_lock):
        record = _load(token)
        if record.get('service') != 'backup' or record['node_id'] != node['id'] or record['owner_hash'] != hashlib.sha256(owner.encode()).hexdigest():
            raise ValueError('План принадлежит другому подключению')
        if record['started']: raise ValueError('Операция уже запущена')
        if record['archive_id']: backup_store.unpin(record['nonce'])
        (PLANS / (token + '.json')).unlink(missing_ok=True)
        return record


async def cancel_plan(node, token, owner):
    record = await asyncio.to_thread(cancel, node, token, owner)
    rpc = None
    try:
        rpc = RpcClient(node['openwrt'])
        await rpc.call(namespace(node), 'cleanup', {'nonce': record['nonce']})
    except Exception: pass  # Local cancellation is final; unreachable drafts expire remotely.
    finally:
        if rpc: await rpc.close()


def cancel_queued(task):
    if task.payload.get('action') == 'create': return
    record = _load(task.payload['plan_token'])
    if record.get('service') != 'backup' or record['node_id'] != task.server_id:
        raise ValueError('Неверный план отменяемой задачи')
    record['closed'] = True
    atomic_write_json(PLANS / (record['token'] + '.json'), record)
    if record.get('archive_id'): backup_store.unpin(record['nonce'])


async def enqueue(node, token, owner):
    with locked(PLANS / '.claim.lock', _plan_lock):
        record = _load(token)
        if record.get('service') != 'backup' or record['node_id'] != node['id'] or record['owner_hash'] != hashlib.sha256(owner.encode()).hexdigest():
            raise ValueError('План принадлежит другому подключению')
        if record['expires'] < time.time(): raise ValueError('План истёк. Проверьте восстановление заново.')
        if record['started'] or active_task(node['id']): raise ValueError('Операция уже выполняется')
        if config_hash(node) != record['config_hash']: raise ValueError('Доступ к шлюзу изменился. Подготовьте новый план.')
        record['started'] = True; atomic_write_json(PLANS / (token + '.json'), record)
        if record['archive_id']: backup_store.pin(record['archive_id'], record['nonce'], time.time() + 86400)
    try:
        return await task_manager.enqueue(name='Восстановление настроек OpenWrt' if record['action'] == 'restore' else 'Перезагрузка шлюза OpenWrt',
            server_id=node['id'], server_name=node['name'], kind='openwrt-backup',
            payload={'action': record['action'], 'plan_token': token}, live_reported=True)
    except BaseException:
        with locked(PLANS / '.claim.lock', _plan_lock):
            record['started'] = False; atomic_write_json(PLANS / (token + '.json'), record)
        raise


async def run_job(node, rpc, nonce, remote, progress, archive=None):
    message = {'username': node['openwrt']['username'], 'nonce': nonce, 'service': 'backup',
               'action': remote['action'], 'expected': remote['expected'], 'expires': remote['expires'], 'files': []}
    if archive:
        message['files'] = [{'name': 'restore.tar.gz', 'size': archive[1]['size'], 'sha256': archive[1]['sha256']}]
    raw = json.dumps(message, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    object_name = namespace(node)
    await _upload(rpc, object_name, nonce, 'manifest.json', raw, progress)
    await _upload(rpc, object_name, nonce, 'manifest.sig', sign(node['openwrt'], raw).encode(), progress)
    if archive: await _upload(rpc, object_name, nonce, 'restore.tar.gz', await asyncio.to_thread(archive[0].read_bytes), progress)
    try: _check(await rpc.call(object_name, 'apply', {'nonce': nonce}))
    except RpcError as exc:
        if exc.code != 'connection': raise
        await progress('Ответ потерян. Проверяю результат; операция повторно не запускается.')
    offset = 0; deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        state = _check(await rpc.call(object_name, 'job', {'nonce': nonce}))
        output = state.get('output', '')
        for line in output[offset:].splitlines(): await progress(line)
        offset = len(output)
        if state.get('phase') == 'success': return state
        if state.get('phase') == 'failed': raise ValueError(state.get('error') or 'Операция резервного копирования завершилась с ошибкой')
        await asyncio.sleep(1)
    raise ValueError('Роутер не подтвердил завершение операции. Проверьте его состояние перед повтором.')


async def create_archive(node, rpc, progress, *, origin='gateway'):
    nonce = secrets.token_hex(16); object_name = namespace(node)
    board = await rpc.call('system', 'board')
    remote = _check(await rpc.call(object_name, 'plan', {'kind': 'backup', 'action': 'create', 'nonce': nonce, 'data': '{}'}))
    temporary = None
    try:
        state = await run_job(node, rpc, nonce, remote, progress)
        info = state.get('archive') or {}; size = info.get('size', 0)
        if not isinstance(size, int) or not 0 < size <= backup_store.MAX_ARCHIVE_BYTES:
            raise ValueError('Роутер вернул недопустимый размер копии')
        incoming = backup_store.ROOT / 'incoming'; incoming.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(dir=incoming)
        digest = hashlib.sha256()
        with os.fdopen(fd, 'wb') as output:
            for offset in range(0, size, 65536):
                chunk = _check(await rpc.call(object_name, 'job', {'nonce': nonce, 'offset': offset, 'length': min(65536, size - offset)}))
                try: data = base64.b64decode(chunk.get('data', ''), validate=True)
                except ValueError: raise ValueError('Некорректный фрагмент копии шлюза') from None
                if len(data) != min(65536, size - offset): raise ValueError('Роутер вернул неполный фрагмент копии')
                output.write(data); digest.update(data)
            output.flush(); os.fsync(output.fileno())
        if digest.hexdigest() != info.get('sha256'): raise ValueError('Контрольная сумма полученной копии не совпала')
        from pathlib import Path
        path = Path(temporary); await asyncio.to_thread(backup_archive.inspect, path)
        release = board.get('release') or {}
        record = await asyncio.to_thread(backup_store.save, path, source_name=node['name'], model=board.get('model'),
                                         version=release.get('version'), target=release.get('target'), origin=origin)
        await progress('Копия сохранена на панели: ' + record['filename'])
        return record
    finally:
        if temporary:
            from pathlib import Path
            Path(temporary).unlink(missing_ok=True)
        try: await rpc.call(object_name, 'cleanup', {'nonce': nonce})
        except Exception: pass


async def execute(payload, task, progress):
    from core.storage import find_server
    record = None; rpc = None
    try:
        if payload['action'] != 'create':
            candidate = await asyncio.to_thread(_load, payload['plan_token'])
            if candidate.get('service') != 'backup' or candidate['node_id'] != task.server_id or candidate['action'] != payload['action']:
                raise ValueError('План не соответствует задаче шлюза')
            record = candidate
            if record.get('closed'): raise ValueError('План уже завершён. Подготовьте новый план восстановления.')
        node = await asyncio.to_thread(find_server, task.server_id)
        if not node or node.get('node_type') != 'openwrt': raise ValueError('Шлюз не найден')
        rpc = RpcClient(node['openwrt']); await check(rpc, namespace(node))
        if payload['action'] == 'create':
            archive = await create_archive(node, rpc, progress)
            return TaskResult(True, output='Копия настроек сохранена: ' + archive['filename'])
        if record['expires'] < time.time() or config_hash(node) != record['config_hash']:
            raise ValueError('План истёк или доступ изменился. Подготовьте новый план.')
        archive = None
        if record['action'] == 'restore':
            archive = await asyncio.to_thread(backup_store.download, record['archive_id'], verify=True)
            if archive[1]['sha256'] != record['archive_sha256']: raise ValueError('Копия изменилась после просмотра плана')
            await asyncio.to_thread(backup_archive.inspect, archive[0])
            await progress('Сохраняю защитную копию текущих настроек на панели…')
            await create_archive(node, rpc, progress, origin='protective')
        state = await run_job(node, rpc, record['nonce'], record['remote'], progress, archive)
        await asyncio.to_thread(set_reboot_required, node['id'], record['action'] == 'restore', state.get('boot_id'))
        return TaskResult(True, output='Настройки восстановлены. Перезагрузка подтверждается отдельно.' if record['action'] == 'restore' else 'Перезагрузка шлюза подтверждена')
    except Exception as exc:
        return TaskResult(False, error=str(exc))
    finally:
        if record:
            record['closed'] = True
            await asyncio.to_thread(atomic_write_json, PLANS / (record['token'] + '.json'), record)
            if record.get('archive_id'): await asyncio.to_thread(backup_store.unpin, record['nonce'])
            if rpc and record.get('action') != 'reboot':
                try: await rpc.call(namespace(node), 'cleanup', {'nonce': record['nonce']})
                except Exception: pass
        if rpc: await rpc.close()


register_executor('openwrt-backup', execute)
