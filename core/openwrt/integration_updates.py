"""Explicit, reviewed replacement of owned integration files over saved SSH."""
import asyncio
import hashlib
import json
import secrets
import time

from core.json_store import atomic_write_json, locked
from core.openwrt import components
from core.openwrt.operations import PLANS, _plan_lock, _load, namespace
from core.openwrt.router_operations import config_hash
from core.task_manager import TaskResult, register_executor, task_manager


def validate(node, state):
    account = node['openwrt']['username']
    if state.get('account_id') != account.removeprefix('bot4vps_'):
        raise ValueError('Принадлежность API-доступа Bot4VPS не подтверждена')
    accepted = components.accepted_hashes(node['openwrt'], state.get('journal'))
    wanted = components.hashes()
    for path, value in state['files'].items():
        if path in wanted and value is not None and (not isinstance(value, str) or value not in accepted[path]):
            raise ValueError('Компонент изменён вне известной установки: ' + path + '. Автоматическая замена отключена.')
    return wanted


def inspect(node):
    from core.openwrt.console import target
    from core.openwrt.bootstrap import _read
    from core.ssh import create_ssh_client
    account = node['openwrt']['username']
    if not node['openwrt'].get('managed') or not node['openwrt'].get('ssh'):
        raise ValueError('Для обновления интеграции нужен управляемый шлюз с сохранённым SSH-доступом')
    import re
    if not re.fullmatch(r'bot4vps_[a-f0-9]{16}', account): raise ValueError('Неизвестная учётная запись интеграции')
    script = "import {cursor} from 'uci'; import {lstat,readfile,popen} from 'fs'; let files={};\n"
    script += 'for (let path in ' + json.dumps(list(components.FILES)) + ") { let info=lstat(path); if(!info) files[path]=null; else if(info.type!='file') files[path]='__NOT_FILE__'; else { let p=popen('sha256sum '+path); files[path]=split(trim(p.read('all')),' ')[0]; p.close(); } }\n"
    script += 'let journal=readfile(' + json.dumps('/root/bot4vps-backup/'+account[8:]+'/transaction.json') + ');\n'
    script += 'printf("%J", {files,account_id:cursor().get("rpcd",'+json.dumps(account)+',"bot4vps_id"),journal:journal?json(journal):null});\n'
    ssh = create_ssh_client(target(node))
    try:
        import shlex
        return json.loads(_read(ssh, 'ucode -e '+shlex.quote(script)))
    finally: ssh.close()


async def prepare(node, owner):
    state = await asyncio.to_thread(inspect, node)
    if state.get('account_id') is None:
        from core.openwrt.access_recovery import prepare as prepare_recovery
        return await prepare_recovery(node, owner)
    wanted = validate(node, state)
    token = secrets.token_urlsafe(32)
    record = {'token':token,'owner_hash':hashlib.sha256(owner.encode()).hexdigest(),'node_id':node['id'],
        'service':'integration','action':'integration_update','config_hash':config_hash(node),
        'before':state['files'],'after':wanted,'expires':time.time()+900,'started':False}
    PLANS.mkdir(parents=True,exist_ok=True);atomic_write_json(PLANS/(token+'.json'),record)
    return {'plan_token':token,'files':[path for path in wanted if state['files'].get(path)!=wanted[path]],
        'warnings':['Обновляются общие RPC-компоненты и интерфейс LuCI Bot4VPS. Учётные записи, секреты и установленные сервисы сохраняются.']}


async def enqueue(node, token, owner):
    with locked(PLANS/'.claim.lock',_plan_lock):
        record = _load(token)
        if record.get('action') not in ('integration_update', 'access_recovery') or record['node_id']!=node['id'] or record['owner_hash']!=hashlib.sha256(owner.encode()).hexdigest() or record['expires']<time.time(): raise ValueError('План обновления истёк или принадлежит другому подключению')
        if record['started'] or record.get('closed'): raise ValueError('План уже запущен или отменён')
        record['started']=True;atomic_write_json(PLANS/(token+'.json'),record)
    try:
        return await task_manager.enqueue(name='Восстановление API через root SSH' if record['action']=='access_recovery' else 'Обновление интеграции Bot4VPS',server_id=node['id'],server_name=node['name'],
            kind='openwrt-integration-update',payload={'plan_token':token},live_reported=True)
    except BaseException:
        with locked(PLANS/'.claim.lock',_plan_lock):
            record = _load(token)
            record['started']=False;atomic_write_json(PLANS/(token+'.json'),record)
        raise


def cancel(node, token, owner):
    with locked(PLANS/'.claim.lock',_plan_lock):
        record=_load(token)
        if record.get('action') not in ('integration_update', 'access_recovery') or record['node_id']!=node['id'] or record['owner_hash']!=hashlib.sha256(owner.encode()).hexdigest():raise ValueError('План принадлежит другому подключению')
        if record['started']:raise ValueError('Обновление уже запущено')
        (PLANS/(token+'.json')).unlink(missing_ok=True)


def apply(node, record, emit):
    from core.openwrt.bootstrap_transaction import Transaction
    from core.openwrt.bootstrap import _read
    from core.openwrt.console import target
    from core.ssh import create_ssh_client
    state = inspect(node);validate(node,state)
    if state['files']!=record['before'] or components.hashes()!=record['after']: raise ValueError('Компоненты изменились после просмотра плана. Проверьте изменения заново.')
    ssh=create_ssh_client(target(node));transaction=Transaction(ssh,secrets.token_hex(16),emit)
    transaction.account=node['openwrt']['username']
    try:
        for path, source in components.FILES.items():
            if record['before'].get(path)==record['after'][path]: continue
            emit('Обновляю '+path)
            mode='755' if path.startswith('/usr/libexec/') else '644'
            transaction.write(path,(components.ASSETS/source).read_text(),mode)
        _read(ssh,'/etc/init.d/rpcd reload')
        return transaction
    except Exception:
        transaction.rollback(revoke_account=False)
        raise
    finally: ssh.close()


def finish(node, transaction, *, rollback=False):
    from core.openwrt.console import target
    from core.ssh import create_ssh_client
    ssh=create_ssh_client(target(node));transaction.ssh=ssh
    try:
        if rollback: return transaction.rollback(revoke_account=False)
        transaction.commit();return True
    finally:ssh.close()


async def execute(payload, task, progress):
    from core.storage import find_server,commit_server,data_lock
    from core.openwrt.rpc import RpcClient
    from core.openwrt.contract import check
    node=await asyncio.to_thread(find_server,task.server_id);transaction=None;rpc=None
    if not node or node.get('node_type')!='openwrt':return TaskResult(False,error='Шлюз не найден')
    record=_load(payload['plan_token']);loop=asyncio.get_running_loop()
    if record.get('action') == 'access_recovery':
        from core.openwrt.access_recovery import execute as execute_recovery
        return await execute_recovery(node, record, progress)
    def emit(line):asyncio.run_coroutine_threadsafe(progress(line),loop).result(timeout=15)
    try:
        if record['expires']<time.time():raise ValueError('План обновления истёк. Проверьте компоненты заново.')
        if config_hash(node)!=record['config_hash']:raise ValueError('Доступ изменился после просмотра плана')
        transaction=await asyncio.to_thread(apply,node,record,emit)
        rpc=RpcClient(node['openwrt']);await check(rpc,namespace(node))
        await asyncio.to_thread(finish,node,transaction)
        def store():
            with data_lock():
                current=find_server(node['id'])
                if not current or config_hash(current)!=record['config_hash']:raise ValueError('Доступ изменился во время обновления')
                current['openwrt']['installed_components']=record['after'];commit_server(current)
        await asyncio.to_thread(store)
        await progress('Интеграция обновлена и проверена. Доступ и сервисы сохранены.')
        return TaskResult(True,output='Компоненты Bot4VPS синхронизированы с панелью')
    except Exception as exc:
        if transaction:
            try:await asyncio.to_thread(finish,node,transaction,rollback=True)
            except Exception as failure:await progress('Откат компонентов требует проверки: '+str(failure))
        return TaskResult(False,error=str(exc))
    finally:
        if rpc:await rpc.close()
        (PLANS/(record['token']+'.json')).unlink(missing_ok=True)


register_executor('openwrt-integration-update',execute)
