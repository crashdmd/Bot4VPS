"""Compatible service updates from verified panel bundles, with rollback files."""
import asyncio
import hashlib
import json
import re
import time

from core.openwrt import bundles
from core.openwrt.rpc import RpcClient
from core.task_manager import TaskResult, register_executor, task_manager

_update_locks = {}


def update_lock(node_id, profile):
    return _update_locks.setdefault((node_id, profile), asyncio.Lock())


def active_tasks(node_id):
    tasks = [task_manager.get_running(node_id), *task_manager.get_queue(node_id)]
    return [task for task in tasks if task and not task.is_done and
            (task.kind == 'openwrt-update-bundle' or task.kind == 'openwrt-operation' and task.payload.get('action') == 'update')]


def active_task(node_id, profile):
    return next((task for task in active_tasks(node_id) if task.payload.get('profile', task.payload.get('service')) == profile), None)


def task_states(node_id):
    return [{'service': task.payload.get('profile', task.payload.get('service')), 'task_id': task.id,
             'stage': 'prepare' if task.kind == 'openwrt-update-bundle' else 'apply'} for task in active_tasks(node_id)]


def pending_review(node_id, profile):
    from core.openwrt import operations
    with operations._plan_lock:
        for path in operations.PLANS.glob('*.json'):
            try: record = json.loads(path.read_text())
            except (OSError, ValueError): continue
            if not isinstance(record,dict) or not isinstance(record.get('expires',0),(int,float)):continue
            if record.get('node_id') == node_id and record.get('service') == profile and record.get('action') == 'update' and not record.get('started') and not record.get('closed') and record.get('expires', 0) > time.time():
                return record
    return None


async def enqueue_update(node, profile, owner=None):
    if node.get('node_type') != 'openwrt' or profile not in bundles.REPOS:
        raise ValueError('Сервис или шлюз не найден')
    async with update_lock(node['id'], profile):
        existing = active_task(node['id'], profile)
        if existing: return existing
        if await asyncio.to_thread(pending_review, node['id'], profile):
            raise ValueError('Для сервиса уже подготовлен план обновления. Подтвердите его или отмените.')
        return await task_manager.enqueue(name='Подготовка обновления ' + profile,
            server_id=node['id'], server_name=node['name'], kind='openwrt-update-bundle',
            payload={'profile': profile, 'owner_hash': hashlib.sha256(owner.encode()).hexdigest() if owner else None}, live_reported=True)


def base_version(value):
    found = re.match(r'v?(\d+\.\d+\.\d+)', str(value or ''))
    return found[1] if found else None


async def available(node, owner=None):
    from core.openwrt.contract import check
    from core.openwrt.operations import namespace
    rpc = RpcClient(node['openwrt'])
    try:
        await check(rpc, namespace(node))
        info = await rpc.call('bot4vps', 'service_versions')
        platform = await rpc.call('bot4vps', 'packages')
        board = await rpc.call('system', 'board')
        installed = dict(line.split(' - ', 1) for line in platform.get('output', '').splitlines() if ' - ' in line)
        cached = bundles.cached(); result = {}
        for profile in bundles.REPOS:
            state = info.get(profile) or {}
            current = base_version(installed.get('podkop')) if profile == 'podkop' else base_version(state.get('version'))
            if not current and state.get('binary_sha256'):
                from core.openwrt.service_inventory import known
                current = known(node['id'], profile, state['binary_sha256'])
            if not current and state.get('binary_sha256'):
                for manifest in (bundles.ROOT / 'manifests').glob('*/' + profile + '/*.json'):
                    try:
                        row = json.loads(manifest.read_text())
                        if any(item.get('role') == profile and item.get('sha256') == state['binary_sha256'] for item in row['files']):
                            current = base_version(row['version']); break
                    except (OSError, ValueError, KeyError): continue
            warning = None
            releases = []
            # Local complete bundles participate even when GitHub is unavailable.
            # Preserve the exact release tag so prepare() finds the saved bundle.
            versions = [row['version'] for row in cached if row['profile'] == profile and row.get('complete') and
                row['platform'].get('architecture') == platform.get('architecture') and row['platform'].get('manager') == platform.get('manager') and
                row['platform'].get('kernel') == platform.get('kernel') and row['platform'].get('release',{}).get('version') == board.get('release',{}).get('version')]
            try:
                releases = await bundles.releases(profile)
                from core.openwrt.release_catalog import status
                if status(profile).get('offline'):
                    warning = 'Лимит GitHub исчерпан. Используются сохранённые на панели версии и данные релизов.'
                versions.extend(row['tag_name'] for row in releases if bundles.release_compatible(board.get('release', {}).get('version'),profile,row,platform))
            except Exception:
                warning = 'Онлайн-проверка недоступна. Сохранённые совместимые версии доступны для обновления.' if versions else 'Онлайн-проверка недоступна; совместимых установочных комплектов на панели нет.'
            if profile == 'ssclash' and state.get('installed') and not current:
                from core.openwrt.service_versions import identify_ssclash, checksum_releases
                # A cached ARM bundle can identify the release's x86 binary via
                # the official checksums, even after the old x86 bundle was pruned.
                candidates = releases + checksum_releases(row['version'] for row in cached if row['profile'] == profile)
                try:
                    current = base_version(await identify_ssclash(state.get('binary_sha256'), candidates, platform))
                except Exception:
                    warning = 'Не удалось сверить установленный SSClash с официальными контрольными суммами. Повторите проверку обновлений.'
            if state.get('installed') and not current and not warning:
                warning = 'Установленная версия не определена. Обновление станет доступно после её распознавания.'
            versions = [tag for tag in versions if bundles.compatible(board.get('release', {}).get('version'), profile, tag)]
            versions.sort(key=lambda tag: bundles._version(tag) or (0,0,0), reverse=True)
            latest = versions[0] if versions else None
            if state.get('installed') and current and not latest and not warning:
                warning = 'Не найден совместимый релиз для архитектуры и версии OpenWrt этого шлюза.'
            can_update = state.get('installed') and current and latest and bundles._version(latest) > bundles._version(current)
            if profile == 'adguardhome' and not state.get('managed'):
                can_update = False
                if state.get('installed'):
                    warning = warning or 'AdGuard Home установлен вне Bot4VPS. Обновление через панель доступно для управляемых установок.'
            pending = active_task(node['id'], profile)
            review = await asyncio.to_thread(pending_review, node['id'], profile)
            plan = None
            if review and owner and review['owner_hash'] == hashlib.sha256(owner.encode()).hexdigest():
                from core.openwrt.operations import public_plan
                plan = public_plan(review)
            result[profile] = {'installed_version': installed.get('podkop') if profile == 'podkop' else current, 'current': current, 'latest': latest, 'available': bool(can_update), 'fingerprint': state.get('binary_sha256'),
                'task_id': pending.id if pending else None,
                'stage': 'prepare' if pending and pending.kind == 'openwrt-update-bundle' else 'apply' if pending else 'review' if review else None,
                'plan': plan, 'warning': warning,
                'status': 'update' if can_update else 'current_cached' if warning and current and latest and bundles._version(current) >= bundles._version(latest) else 'unverified' if warning else 'current' if current and latest and bundles._version(current) == bundles._version(latest) else 'newer' if current and latest else 'not_installed' if not state.get('installed') else 'unverified'}
        for service, packages in {'dnsmasq': ('dnsmasq-full', 'dnsmasq'), 'firewall': ('firewall4', 'firewall')}.items():
            current = next((installed[name] for name in packages if installed.get(name)), None)
            result[service] = {'current': current, 'latest': None, 'available': False, 'status': 'system', 'warning': None}
        return result
    finally: await rpc.close()


async def prepare_update(payload, task, progress):
    from core.storage import find_server
    from core.openwrt.monitor import client_for
    node = await asyncio.to_thread(find_server, task.server_id)
    if not node or node.get('node_type') != 'openwrt': return TaskResult(False, error='Шлюз не найден')
    completed = False
    profile = payload.get('profile')
    try:
        profile = payload['profile']; update = (await available(node))[profile]
        if not update['available']: raise ValueError('Совместимого обновления не найдено')
        rpc = await client_for(node)
        board = await rpc.call('system','board'); platform = await rpc.call('bot4vps','packages')
        old_bundle = None
        if profile == 'podkop':
            releases = await bundles.releases(profile)
            tag = next((row['tag_name'] for row in releases if base_version(row['tag_name']) == update['current']), None)
            if not tag: raise ValueError('Исходная версия Podkop не найдена: невозможно подготовить безопасный откат')
            identity = {'release':board.get('release'),'kernel':platform.get('kernel'),'architecture':platform.get('architecture'),'manager':platform['manager']}
            key = hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
            old_id = hashlib.sha256((key+profile+tag).encode()).hexdigest()
            # Keep rollback artifacts across preparation and the subsequent review.
            await asyncio.to_thread(bundles.pin, old_id, 'update-'+node['id']+'-'+profile, time.time()+3600)
            old_bundle = await bundles.prepare(node,profile,tag,progress,platform=platform,board=board)
        bundle = await bundles.prepare(node,profile,update['latest'],progress,platform=platform,board=board)
        await asyncio.to_thread(bundles.pin, bundle['id'], 'update-'+node['id']+'-'+profile+'-new', time.time()+3600)
        review_prepared = False
        if payload.get('owner_hash'):
            if not re.fullmatch(r'[a-f0-9]{64}',payload['owner_hash']):raise ValueError('Некорректный контекст подтверждения обновления')
            from core.openwrt.operations import _prepare
            await _prepare(node,'',profile,'update',bundle_id=bundle['id'],rollback_bundle_id=old_bundle['id'] if old_bundle else None,
                owner_hash=payload['owner_hash'],expected_binary_hash=update.get('fingerprint'),preparation_task_id=task.id)
            review_prepared = True
        completed = True
        return TaskResult(True,output=json.dumps({'bundle_id':bundle['id'],'rollback_bundle_id':old_bundle['id'] if old_bundle else None,'review_prepared':review_prepared}))
    except Exception as exc: return TaskResult(False,error=str(exc))
    finally:
        if not completed:
            await asyncio.to_thread(bundles.unpin, 'update-'+node['id']+'-'+str(profile))
            await asyncio.to_thread(bundles.unpin, 'update-'+node['id']+'-'+str(profile)+'-new')


register_executor('openwrt-update-bundle', prepare_update)
