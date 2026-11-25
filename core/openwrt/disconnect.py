"""Removal completes only after router-side access revocation is confirmed."""
import asyncio
import hashlib
import json
import shlex
import secrets
import time
import threading
from core.install_paths import get_install_path
from core.json_store import atomic_write_json, locked
from core.task_manager import TaskResult, register_executor, task_manager
from core.openwrt.rpc import RpcClient, RpcError


def config_hash(node):
    return hashlib.sha256(json.dumps(node['openwrt'], sort_keys=True).encode()).hexdigest()


PLANS = get_install_path() / 'data/openwrt-deletion-plans'
_plan_lock = threading.RLock()


async def prepare(node, owner):
    from core.openwrt.uninstall import preflight
    expected = config_hash(node)
    inventory = await asyncio.to_thread(preflight, node) if node['openwrt'].get('managed') else None
    token = secrets.token_urlsafe(32)
    record = {'node_id': node['id'], 'config_hash': expected, 'cleanup_inventory': inventory,
              'owner_hash': hashlib.sha256(owner.encode()).hexdigest(), 'expires': time.time() + 900, 'started': False}
    PLANS.mkdir(parents=True, exist_ok=True)
    atomic_write_json(PLANS / (token + '.json'), record)
    return token


def revoke_over_ssh(node, inventory=None):
    from core.openwrt.console import target
    from core.openwrt.bootstrap import _read
    from core.ssh import create_ssh_client
    account = node['openwrt']['username']
    if not node['openwrt'].get('managed') or not account.startswith('bot4vps_'):
        raise ValueError('Через SSH можно отозвать только созданный панелью API-доступ')
    credentials = target(node)
    ssh = create_ssh_client(credentials)
    try:
        # Independent of installed components: cleanup retries may have already
        # removed the revoke helper before losing the SSH reply.
        code = "import { cursor } from 'uci'; import { unlink, lstat, popen } from 'fs'; import { connect } from 'ubus'; let c = cursor(); let name = " + json.dumps(account) + "; if (c.get('rpcd', name) && c.get('rpcd', name, 'bot4vps_id') != substr(name, 8)) exit(1); "
        if inventory is not None:
            from core.openwrt.components import FILES
            if set(inventory['files']) - set(FILES):
                raise ValueError('План содержит неизвестные файлы интеграции')
            code += 'let expected = ' + json.dumps(inventory['files']) + '; '
            code += "for (let path, digest in expected) { let info = lstat(path); if (digest == null) { if (info) die('Файлы изменились перед отзывом; API-доступ сохранён'); continue; } if (!info || info.type != 'file') die('Файлы изменились перед отзывом; API-доступ сохранён'); let p = popen('sha256sum ' + path); let actual = split(trim(p.read('all')), ' ')[0]; p.close(); if (actual != digest) die('Файлы изменились перед отзывом; API-доступ сохранён'); } "
            code += 'let expected_accounts = ' + json.dumps(inventory['accounts']) + '; '
            code += "let accounts = []; c.foreach('rpcd', 'login', s => { if (s['.name'] != name && (s.bot4vps_id || match(s.username || '', /^bot4vps_[a-f0-9]+$/))) push(accounts, s['.name']); }); if (length(accounts) != length(expected_accounts)) die('Подключения изменились перед отзывом; API-доступ сохранён'); for (let other in accounts) if (index(expected_accounts, other) < 0) die('Подключения изменились перед отзывом; API-доступ сохранён'); "
        code += "if (c.get('rpcd', name)) { c.delete('rpcd', name); if (!c.commit('rpcd')) exit(1); } unlink('/etc/bot4vps/keys/' + name + '.pub'); unlink('/usr/share/rpcd/acl.d/bot4vps-key-' + substr(name,8) + '.json'); let bus = connect(); let rows = bus.call('session', 'list', {}, true) || []; for (let row in rows) if (row.data?.username == name) bus.call('session', 'destroy', { ubus_rpc_session: row.ubus_rpc_session });"
        _read(ssh, 'ucode -e ' + shlex.quote(code) + ' && /etc/init.d/rpcd reload')
        script = "ucode -e 'import { cursor } from \"uci\"; import { access } from \"fs\"; import { connect } from \"ubus\"; let name = " + json.dumps(account) + "; if (cursor().get(\"rpcd\", name) || access(\"/etc/bot4vps/keys/\" + name + \".pub\") || access(\"/usr/share/rpcd/acl.d/bot4vps-key-\" + substr(name,8) + \".json\")) exit(1); let rows = connect().call(\"session\", \"list\", {}, true) || []; for (let row in rows) if (row.data?.username == name) exit(1);'"
        _read(ssh, script)
    finally:
        ssh.close()


async def execute(payload, task, progress):
    from core.storage import find_server, delete_server, commit_server, data_lock
    from core.openwrt import monitor
    node = find_server(task.server_id)
    if not node or node.get('node_type') != 'openwrt':
        return TaskResult(False, error='Шлюз не найден')
    rpc = None
    revoked = False
    expected = payload.get('config_hash', config_hash(node))
    root_ssh = node['openwrt'].get('managed') and (node['openwrt'].get('ssh') or {}).get('user') == 'root'
    if config_hash(node) != expected:
        return TaskResult(False, error='API-доступ изменился после подтверждения удаления. Подготовьте новый план.')
    if node['openwrt'].get('managed'):
        from core.openwrt.uninstall import preflight
        try:
            await progress('Проверяю SSH, файлы интеграции и возможность очистки до отзыва API-доступа…')
            inventory = await asyncio.to_thread(preflight, node)
            if payload.get('cleanup_inventory') is not None and inventory != payload['cleanup_inventory']:
                raise ValueError('Файлы интеграции или другие подключения изменились после просмотра плана. Подготовьте новый план удаления.')
            current = find_server(node['id'])
            if not current or config_hash(current) != expected:
                raise ValueError('API-доступ изменился во время предварительной проверки. Подготовьте новый план удаления.')
        except Exception as exc:
            return TaskResult(False, error='Удаление остановлено до изменения API-доступа: ' + str(exc))
    try:
        if root_ssh:
            await progress('Отзываю собственную учётную запись Bot4VPS и её сеансы через сохранённый root SSH, с повторной проверкой файлов перед отзывом…')
            try:
                await asyncio.to_thread(revoke_over_ssh, node, inventory)
            except Exception as exc:
                raise ValueError('Отзыв через root SSH не подтверждён: ' + str(exc)) from None
            revoked = True
            with data_lock():
                current = find_server(node['id'])
                if not current or config_hash(current) != expected:
                    raise ValueError('API-доступ изменился во время удаления. Новая запись сохранена.')
                current['revocation_requested'] = expected
                commit_server(current)
            await cleanup_integration(node, progress)
            with data_lock():
                current = find_server(node['id'])
                if not current or config_hash(current) != expected:
                    raise ValueError('API-доступ изменился во время удаления. Новая запись сохранена.')
                delete_server(node['id'], gateway_revoked=True)
            await monitor.forget(node['id'])
            await progress('Через root SSH проверены отзыв доступа и очистка интеграции. Запись шлюза удалена; службы и настройки роутера сохранены.')
            return TaskResult(True, output='Собственный API-доступ отозван и проверен через root SSH. Интеграция удалена, сервисы и настройки сохранены.')
        await progress('Подключаюсь к API шлюза…')
        rpc = RpcClient(node['openwrt'])
        already_revoked = False
        try:
            await rpc.login()
        except RpcError as exc:
            if exc.code == 'permission' and node.get('revocation_requested') == expected:
                already_revoked = True
            else:
                raise
        await progress('Отзываю отдельную учётную запись Bot4VPS и её активные сеансы…')
        try:
            username = node['openwrt']['username']
            if not username.startswith('bot4vps_'):
                raise ValueError('Отзовите эту вручную настроенную учётную запись в LuCI')
            result = {'revoked': True} if already_revoked else await rpc.call('bot4vps-key-' + username.removeprefix('bot4vps_'), 'disconnect')
            if not result.get('revoked'):
                raise ValueError('Отзыв не подтверждён. Для ручного API отключите его учётную запись в LuCI.')
        except RpcError as exc:
            if exc.code != 'connection':
                raise
            # Revoking the current session can close its HTTP reply. Do not
            # repeat a mutation; confirm the old credential independently.
            await progress('Соединение завершилось при отзыве. Проверяю результат отдельным подключением…')
            await asyncio.sleep(2)
        with data_lock():
            current = find_server(node['id'])
            if not current or config_hash(current) != expected:
                raise ValueError('API-доступ изменился во время удаления. Новая запись сохранена.')
            current['revocation_requested'] = expected
            commit_server(current)
        await asyncio.sleep(2)
        await rpc.close(); rpc = None
        await progress('Проверяю, что прежний секрет больше не позволяет подключиться…')
        verification = RpcClient(node['openwrt'])
        try:
            try:
                await verification.login()
            except RpcError as exc:
                if exc.code != 'permission':
                    raise ValueError('Отзыв выполнен, но результат не удалось проверить. Запись шлюза сохранена.') from None
            else:
                raise ValueError('Прежний секрет всё ещё работает. Запись шлюза не удалена.')
        finally:
            await verification.close()
        revoked = True
        await cleanup_integration(node, progress)
        await progress('Доступ отозван. Удаляю запись и сохранённый секрет из панели…')
        with data_lock():
            current = find_server(node['id'])
            if not current or config_hash(current) != expected:
                raise ValueError('API-доступ изменился во время проверки. Новая запись сохранена.')
            delete_server(node['id'], gateway_revoked=True)
        await monitor.forget(node['id'])
        await progress('Шлюз удалён. Службы, LAN, WAN и настройки самого роутера сохранены.')
        return TaskResult(True, output='API-доступ Bot4VPS отозван и проверен. Очистка интеграции завершена. Запись шлюза удалена.')
    except (RpcError, ValueError) as exc:
        current = find_server(node['id'])
        if not root_ssh and not revoked and current and config_hash(current) == expected and node['openwrt'].get('managed') and node['openwrt'].get('ssh'):
            await progress('Отзыв через API не подтверждён. Использую сохранённый SSH-доступ для удаления только своей учётной записи…')
            try:
                await asyncio.to_thread(revoke_over_ssh, node)
                with data_lock():
                    current = find_server(node['id'])
                    if not current or config_hash(current) != expected:
                        raise ValueError('Данные доступа изменились во время отзыва')
                    current['revocation_requested'] = expected
                    commit_server(current)
                await cleanup_integration(node, progress)
                with data_lock():
                    current = find_server(node['id'])
                    if not current or config_hash(current) != expected: raise ValueError('Данные доступа изменились во время отзыва')
                    delete_server(node['id'], gateway_revoked=True)
                await monitor.forget(node['id'])
                await progress('Через SSH проверены отзыв доступа и очистка интеграции. Запись шлюза удалена.')
                return TaskResult(True, output='API-доступ отозван и проверен через SSH. Очистка интеграции завершена. SSH-вход и службы роутера сохранены.')
            except Exception as fallback_error:
                exc = fallback_error
                await progress('Отзыв или очистка через SSH не завершены: ' + str(fallback_error))
        with data_lock():
            current = find_server(node['id'])
            if current and config_hash(current) == expected:
                current['deletion_pending'] = True
                commit_server(current)
        return TaskResult(False, error=str(exc) + ' Отзыв доступа или очистка интеграции не завершены. Запись сохранена для повторного удаления.')
    finally:
        if rpc:
            await rpc.close()


async def cleanup_integration(node, progress):
    if not node['openwrt'].get('managed'):
        return
    from core.openwrt.uninstall import cleanup
    await progress('Проверяю оставшиеся подключения и удаляю файлы интеграции Bot4VPS через SSH…')
    if await asyncio.to_thread(cleanup, node):
        await progress('Файлы интеграции и пункт LuCI Bot4VPS удалены. LuCI, SSH и установленные службы сохранены.')
    else:
        await progress('На роутере есть другие подключения Bot4VPS. Общие файлы и пункт LuCI сохранены для них.')


async def enqueue(node, token, owner):
    if not isinstance(token, str) or len(token) != 43 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in token):
        raise ValueError('Сначала просмотрите план удаления шлюза')
    with locked(PLANS / '.claim.lock', _plan_lock):
        path = PLANS / (token + '.json')
        if not path.exists(): raise ValueError('План удаления не найден')
        record = json.loads(path.read_text())
        if record['node_id'] != node['id'] or record['owner_hash'] != hashlib.sha256(owner.encode()).hexdigest() or record['expires'] < time.time():
            raise ValueError('План удаления истёк или принадлежит другому подключению')
        if record['config_hash'] != config_hash(node):
            raise ValueError('API-доступ изменился после просмотра плана. Проверьте новый план удаления.')
        if node['openwrt'].get('managed') and not isinstance(record.get('cleanup_inventory'), dict):
            raise ValueError('План удаления не содержит предварительной проверки файлов. Подготовьте новый план удаления.')
        if record['started']: raise ValueError('Удаление по этому плану уже запущено')
        record['started'] = True; atomic_write_json(path, record)
    try:
        return await task_manager.enqueue(name='Удаление шлюза и отзыв API', server_id=node['id'],
            server_name=node['name'], kind='openwrt-disconnect', payload={'config_hash': record['config_hash'], 'cleanup_inventory': record.get('cleanup_inventory')}, live_reported=True)
    except BaseException:
        with locked(PLANS / '.claim.lock', _plan_lock):
            record = json.loads(path.read_text())
            record['started'] = False; atomic_write_json(path, record)
        raise


register_executor('openwrt-disconnect', execute)
