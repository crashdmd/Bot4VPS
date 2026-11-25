"""Reviewed recovery of a revoked managed API through saved root SSH."""
import asyncio
from copy import deepcopy
import hashlib
import json
import secrets
import shlex
import time

from core.openwrt import components
from core.openwrt.router_operations import config_hash
from core.openwrt.operations import PLANS
from core.json_store import atomic_write_json


def inspect(node):
    from core.openwrt.uninstall import _config, _inventory
    from core.openwrt.console import target
    from core.ssh import create_ssh_client
    config = _config(node)
    if config['ssh'].get('user') != 'root':
        raise ValueError('Для восстановления отозванного API сохраните и проверьте root SSH-доступ')
    ssh = create_ssh_client(target(node))
    try:
        state = _inventory(ssh, config, require_revoked=False)
        if state.get('account_present'):
            raise ValueError('API-учётная запись существует. Для смены её секрета используйте раздел доступа; восстановление отозванной записи не запускалось.')
        if state['accounts']:
            raise ValueError('На роутере есть другие подключения Bot4VPS. Общие компоненты нельзя заменять при восстановлении отозванной записи.')
        for path, digest in state['files'].items():
            if digest is not None and (not isinstance(digest, str) or len(digest) != 64 or any(char not in '0123456789abcdef' for char in digest)):
                raise ValueError('Компонент не является обычным проверяемым файлом: ' + path)
        return {'files': state['files'], 'accounts': state['accounts'], 'account_present': False}
    finally:
        ssh.close()


async def prepare(node, owner):
    expected = config_hash(node)
    before = await asyncio.to_thread(inspect, node)
    token = secrets.token_urlsafe(32)
    record = {'token': token, 'owner_hash': hashlib.sha256(owner.encode()).hexdigest(), 'node_id': node['id'],
              'service': 'integration', 'action': 'access_recovery', 'config_hash': expected,
              'before': before, 'after': components.hashes(), 'expires': time.time() + 900, 'started': False}
    PLANS.mkdir(parents=True, exist_ok=True); atomic_write_json(PLANS / (token + '.json'), record)
    return {'plan_token': token, 'access_recovery': True, 'title': 'Восстановить API-доступ через root SSH?',
            'files': list(components.FILES), 'warnings': [
                'Отозванная собственная API-учётная запись Bot4VPS будет создана заново с новым секретом и новым ключом подписи. Прежний секрет не возобновляется.',
                'Перед заменой файлов интеграции их текущее содержимое сохраняется на роутере. В том числе заменяются старые или изменённые обычные файлы, перечисленные в плане.',
                'SSH-доступ, установленные сервисы, LAN, WAN, Wi-Fi и параметры HTTPS сохраняются.',
                'Сохраняется существующая запись шлюза. При ошибке до сохранения нового доступа созданная учётная запись отзывается, файлы возвращаются по резервному журналу.']}


def apply(node, record, emit):
    from core.openwrt.bootstrap import _read, _write
    from core.openwrt.bootstrap_transaction import Transaction, drain
    from core.openwrt.console import target
    from core.openwrt.signing import create
    from core.ssh import create_ssh_client
    before = inspect(node)
    if before != record['before'] or components.hashes() != record['after']:
        raise ValueError('Состояние интеграции изменилось после просмотра плана. Подготовьте восстановление заново.')
    config = node['openwrt']; account = config['username']; account_id = account.removeprefix('bot4vps_')
    ssh = create_ssh_client(target(node)); transaction = Transaction(ssh, account_id, emit)
    transaction.account = account
    recovered = deepcopy(node); secret = secrets.token_hex(32); signing, public_key = create()
    transaction.recovery_nonce = secrets.token_hex(16)
    transaction.recovery_password_hash = None
    modified = False
    try:
        # Preserve any previous journal before publishing the recovery journal.
        backup = transaction.path + '.before-recovery-' + secrets.token_hex(8)
        _read(ssh, 'if [ -f ' + shlex.quote(transaction.path) + ' ]; then cp -p ' + shlex.quote(transaction.path) + ' ' + shlex.quote(backup) + '; fi')
        transaction.snapshot('/etc/config/rpcd')
        for path in components.FILES:
            transaction.snapshot(path)
        transaction.snapshot('/etc/bot4vps/keys/' + account + '.pub')
        namespace = 'bot4vps-key-' + account_id
        acl_path = '/usr/share/rpcd/acl.d/' + namespace + '.json'
        transaction.snapshot(acl_path)
        # Recheck on the same SSH connection before the first replacement.
        from core.openwrt.uninstall import _inventory
        current = _inventory(ssh, config, require_revoked=False)
        if current.get('account_present') or current['accounts'] or current['files'] != before['files']:
            raise ValueError('Доступ или файлы изменились перед восстановлением. Изменения не применены.')
        emit('Сохраняю прежние файлы интеграции и устанавливаю компоненты текущей панели…')
        modified = True
        for path, source in components.FILES.items():
            transaction.write(path, (components.ASSETS / source).read_text(), '755' if path.startswith('/usr/libexec/') else '644')
        transaction.write('/etc/bot4vps/keys/' + account + '.pub', public_key, '644')
        transaction.write(acl_path, json.dumps({namespace: {'description': 'Собственные операции Bot4VPS', 'write': {'ubus': {namespace: ['disconnect', 'capabilities', 'plan', 'upload', 'apply', 'job', 'confirm', 'cleanup']}}}}, ensure_ascii=False), '644')
        emit('Создаю собственную API-учётную запись с новым секретом; root-пароль в API не передаётся…')
        code = "import { cursor } from 'uci'; import { popen } from 'fs'; let c = cursor();\n"
        code += 'let account = ' + json.dumps(account) + '; let secret = ' + json.dumps(secret) + ';\n'
        code += "if (c.get('rpcd', account)) exit(1); let p = popen('/usr/sbin/uhttpd -m ' + secret); let hash = trim(p.read('all')); p.close(); if (!hash) exit(1); c.set('rpcd', account, 'login');\n"
        for key, value in {'username': account, 'password': None, 'bot4vps_id': account_id, 'bot4vps_label': node['name'], 'bot4vps_recovery_nonce': transaction.recovery_nonce, 'read': ['bot4vps-reader'], 'write': [namespace]}.items():
            code += 'c.set("rpcd", account, ' + json.dumps(key) + ', ' + ('hash' if value is None else json.dumps(value)) + ');\n'
        code += 'if (!c.commit("rpcd")) exit(1); printf("%J", {password_hash: hash});\n'
        stdin, stdout, stderr = ssh.exec_command('ucode -', timeout=20)
        stdin.write(code); stdin.flush(); stdin.channel.shutdown_write()
        output, _, status = drain(stdout, stderr)
        if status: raise ValueError('Не удалось создать собственную API-учётную запись')
        transaction.recovery_password_hash = json.loads(output)['password_hash']
        _read(ssh, '/etc/init.d/rpcd reload')
        recovered['openwrt'].update(password=secret, **signing, installed_components=record['after'])
        recovered['deletion_pending'] = False; recovered.pop('revocation_requested', None)
        recovered['bootstrap_state'] = 'commit_pending'
        return transaction, recovered
    except Exception:
        if modified:
            rollback(transaction)
        raise
    finally:
        ssh.close()


def rollback(transaction):
    """Revoke only the account created by this operation; preserve replacement access."""
    from core.openwrt.bootstrap import _read
    account = transaction.account
    code = "import { cursor } from 'uci'; import { connect } from 'ubus'; let c = cursor(); "
    code += 'let account = ' + json.dumps(account) + '; let nonce = ' + json.dumps(transaction.recovery_nonce) + '; '
    code += 'let expected_hash = ' + json.dumps(transaction.recovery_password_hash) + '; '
    code += "if (c.get('rpcd', account)) { if (c.get('rpcd', account, 'bot4vps_id') != substr(account, 8) || c.get('rpcd', account, 'bot4vps_recovery_nonce') != nonce || (expected_hash && c.get('rpcd', account, 'password') != expected_hash)) die('API-доступ изменён другим действием; откат не перезаписывает его'); c.delete('rpcd', account); if (!c.commit('rpcd')) exit(1); let bus = connect(); let sessions = bus.call('session', 'list', {}, true) || []; for (let row in sessions) if (row.data?.username == account) bus.call('session', 'destroy', {ubus_rpc_session: row.ubus_rpc_session}); }"
    _read(transaction.ssh, 'ucode -e ' + shlex.quote(code))
    return transaction.rollback(revoke_account=False)


async def execute(node, record, progress):
    from core.openwrt import integration_updates
    from core.openwrt.rpc import RpcClient
    from core.openwrt.contract import check
    from core.openwrt.operations import namespace
    from core.storage import find_server, commit_server, data_lock
    from core.openwrt.monitor import refresh
    from core.task_manager import TaskResult
    loop = asyncio.get_running_loop(); transaction = None; rpc = None; stored = False
    def emit(line): asyncio.run_coroutine_threadsafe(progress(line), loop).result(timeout=15)
    try:
        if config_hash(node) != record['config_hash'] or record['expires'] < time.time():
            raise ValueError('Доступ изменился или план восстановления истёк')
        transaction, recovered = await asyncio.to_thread(apply, node, record, emit)
        await progress('Проверяю восстановленный HTTPS API и подпись компонентов…')
        rpc = RpcClient(recovered['openwrt']); await rpc.call('system', 'board'); await check(rpc, namespace(recovered))
        def store():
            with data_lock():
                current = find_server(node['id'])
                if not current or config_hash(current) != record['config_hash']:
                    raise ValueError('Запись шлюза изменилась во время восстановления')
                commit_server(recovered)
        await asyncio.to_thread(store); stored = True
        warnings = False
        try:
            await asyncio.to_thread(integration_updates.finish, node, transaction)
            from core.openwrt.bootstrap import set_bootstrap_state
            await asyncio.to_thread(set_bootstrap_state, node['id'], 'ready')
        except Exception:
            warnings = True; await progress('API восстановлен и сохранён. Фиксацию резервного журнала можно повторить во вкладке «Доступ».')
        try: await refresh(recovered, force=True)
        except Exception: warnings = True
        await progress('API-доступ восстановлен через root SSH. Сервисы и сетевые настройки сохранены.')
        return TaskResult(True, warnings=warnings, output='Доступ шлюза восстановлен; существующая запись и сервисы сохранены.')
    except Exception as exc:
        if transaction is not None and not stored:
            try:
                from core.openwrt.console import target
                from core.ssh import create_ssh_client
                def perform_rollback():
                    ssh = create_ssh_client(target(node)); transaction.ssh = ssh
                    try: rollback(transaction)
                    finally: ssh.close()
                await asyncio.to_thread(perform_rollback)
            except Exception: await progress('Откат требует проверки по сохранённому резервному журналу на роутере.')
        return TaskResult(False, error=str(exc))
    finally:
        if rpc: await rpc.close()
        (PLANS / (record['token'] + '.json')).unlink(missing_ok=True)
