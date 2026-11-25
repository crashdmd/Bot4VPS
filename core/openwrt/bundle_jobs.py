"""Preparation downloads only to the panel, never changes a router."""
import asyncio
import logging

from core.task_manager import TaskResult, task_manager, register_executor
from core.openwrt import bundles


async def execute(payload, task, progress):
    from core.storage import find_server
    node = find_server(task.server_id)
    if not node or node.get('node_type') != 'openwrt':
        return TaskResult(False, error='Шлюз не найден')
    try:
        bundle = await bundles.prepare(node, payload['profile'], payload['version'], progress)
        return TaskResult(True, output='Комплект готов: ' + bundle['id'])
    except Exception as exc:
        return TaskResult(False, error=str(exc))


async def enqueue(node, profile, version):
    return await task_manager.enqueue(name='Подготовка резервного комплекта ' + profile,
        server_id=node['id'], server_name=node['name'], kind='openwrt-bundle',
        payload={'profile': profile, 'version': version}, live_reported=True)


async def enqueue_reserve(node, *, automatic=False):
    if automatic and not bundles.settings()['enabled']: return None
    tasks = [task_manager.get_running(node['id']), *task_manager.get_queue(node['id'])]
    existing = next((task for task in tasks if task and not task.is_done and task.kind == 'openwrt-reserve'), None)
    if existing: return existing
    return await task_manager.enqueue(name='Проверка установочных комплектов OpenWrt',
        server_id=node['id'], server_name=node['name'], kind='openwrt-reserve',
        payload={'automatic': automatic}, live_reported=True)


async def execute_reserve(payload, task, progress):
    from core.storage import find_server
    from core.openwrt.monitor import client_for
    node = await asyncio.to_thread(find_server, task.server_id)
    if not node or node.get('node_type') != 'openwrt': return TaskResult(False, error='Шлюз не найден')
    options = bundles.settings()
    if payload.get('automatic') and not options['enabled']: return TaskResult(True, output='Автоматическое резервирование выключено')
    failures = []
    try:
        rpc = await client_for(node)
        board = await rpc.call('system', 'board')
        platform = await rpc.call('bot4vps', 'packages')
        await progress('OpenWrt ' + str(board.get('release', {}).get('version')) + ' · ' + str(platform.get('architecture')))
        for profile in bundles.REPOS:
            try:
                versions = [release for release in await bundles.releases(profile)
                            if bundles.release_compatible(board.get('release', {}).get('version'), profile, release, platform)]
                versions.sort(key=lambda release: bundles._version(release['tag_name']) or (0, 0, 0), reverse=True)
            except Exception as exc:
                failures.append(profile + ': ' + str(exc))
                await progress('Не удалось подготовить ' + failures[-1])
                continue
            for release in versions[:options['keep']]:
                label = profile + ' ' + release['tag_name']
                try:
                    await progress(profile + ': ' + release['tag_name'])
                    await bundles.prepare(node, profile, release['tag_name'], progress, platform=platform, board=board, reserve=True)
                except Exception as exc:
                    failures.append(label + ': ' + str(exc))
                    await progress('Не удалось подготовить ' + failures[-1])
            if not versions: await progress('Для '+profile+' нет совместимых установочных релизов на этой платформе')
        await asyncio.to_thread(bundles.collect)
        return TaskResult(not failures, error='; '.join(failures) or None,
                          output='Проверка установочных комплектов завершена' + (' с ошибками: ' + '; '.join(failures) if failures else ''))
    except Exception as exc:
        return TaskResult(False, error=str(exc))


async def reserve_job(_context=None):
    from core.openwrt.feature import enabled
    if not enabled() or not bundles.settings()['enabled']: return
    await asyncio.to_thread(bundles.collect)
    from core.node_types import load_gateways
    for node in await asyncio.to_thread(load_gateways):
        try:
            await enqueue_reserve(node, automatic=True)
        except Exception:
            logging.getLogger(__name__).exception('Не удалось поставить резервирование шлюза %s в очередь', node['id'])


register_executor('openwrt-bundle', execute)

register_executor('openwrt-reserve', execute_reserve)
