"""Inventory and removal of local installation artifacts; never remote services."""
from contextlib import contextmanager
import fcntl
import hashlib
import importlib
import json
from pathlib import Path
import re
import threading
import time

from core.openwrt import bundles

NAMES = {'3x-ui': '3x-ui', 'ssclash': 'SSClash-Go', 'adguardhome': 'AdGuard Home', 'podkop': 'Podkop'}
_locks = {}
_held = threading.local()


class ArchiveBusy(ValueError):
    pass


@contextmanager
def archive_access(root, *, blocking=True):
    root = Path(root).resolve()
    lock = _locks.setdefault(str(root), threading.RLock())
    if not lock.acquire(blocking=blocking):
        raise ArchiveBusy('Установочные файлы используются. Дождитесь завершения операции.')
    depth = getattr(_held, 'paths', {})
    _held.paths = depth
    handle = None
    try:
        if str(root) not in depth:
            root.mkdir(parents=True, exist_ok=True)
            handle = (root / '.archives.lock').open('a')
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError:
                raise ArchiveBusy('Установочные файлы используются. Дождитесь завершения операции.') from None
        depth[str(root)] = depth.get(str(root), 0) + 1
        try:
            yield
        finally:
            depth[str(root)] -= 1
            if not depth[str(root)]: del depth[str(root)]
    finally:
        if handle is not None: handle.close()
        lock.release()


def _local(path, root):
    return not path.is_symlink() and path.resolve().is_relative_to(root.resolve())


def _children(path):
    try: return list(path.iterdir())
    except OSError: return []


def _xui():
    cache = importlib.import_module('services.3x-ui.impl.release_cache')
    root = cache.cache_root()
    if not root.is_dir(): return []
    from core.task_manager import task_manager
    tasks = list(task_manager._running.values())
    for queue in list(task_manager._queues.values()): tasks.extend(list(queue))
    busy = any(not task.is_done and task.payload.get('service') == '3x-ui' and
               task.payload.get('action') in ('install', 'update', 'reinstall', 'release_download') for task in tasks)
    try:
        with archive_access(root, blocking=False): pass
    except ArchiveBusy:
        busy = True
    result = []
    for tag in cache.list_cached_versions():
        version = root / tag
        if not _local(version, root): continue
        for archive in _children(version):
            match = re.fullmatch(r'x-ui-linux-([A-Za-z0-9_-]+)\.tar\.gz', archive.name)
            if not match: continue
            arch = match[1]
            tarball = cache.tarball_path(tag, arch)
            paths = [tarball, tarball.with_name(tarball.name + '.sha256')]
            if not all(path.is_file() and _local(path, root) for path in paths): continue
            try: sizes = [path.stat().st_size for path in paths]
            except OSError: continue
            if not sizes[0]: continue
            result.append({'id': hashlib.sha256(f'3x-ui:{tag}:{arch}'.encode()).hexdigest(), 'service': '3x-ui',
                'name': NAMES['3x-ui'], 'version': tag, 'destination': 'VPS / Linux · ' + arch,
                'size': sum(sizes), 'busy': busy, 'reserved': False, 'complete': True,
                'files': [{'name': path.name, 'size': size, 'available': True} for path, size in zip(paths, sizes)],
                '_paths': paths, '_root': root})
    return result


def _pins():
    active = set()
    for path in (bundles.ROOT / 'pins').glob('*'):
        try:
            record = json.loads(path.read_text())
            if record.get('expires', 0) > time.time(): active.add(record['bundle_id'])
        except (OSError, ValueError, KeyError):
            active.add('*')  # An unreadable pin cannot safely be ignored.
    return active


def _gateway_entries():
    result = []
    pinned = _pins()
    for path in (bundles.ROOT / 'manifests').glob('*/*/*.json'):
        if not _local(path, bundles.ROOT): continue
        try:
            row = json.loads(path.read_text())
            sid, bundle_id = row['profile'], row['id']
            if sid not in NAMES or sid == '3x-ui' or path.parent.name != sid or not re.fullmatch(r'[a-f0-9]{64}', bundle_id): continue
            files, paths = [], []
            for entry in row['files']:
                artifact = bundles.object_path(entry['sha256'])
                exists = artifact.is_file() and _local(artifact, bundles.ROOT)
                files.append({'name': entry['name'], 'size': artifact.stat().st_size if exists else entry.get('size', 0), 'available': exists})
                paths.append(artifact if exists else None)
            if not any(paths): continue
            platform = row.get('platform') or {}; release = platform.get('release') or {}
            target = 'Шлюзы OpenWrt ' + str(release.get('version') or '—')
            target += ' · ' + str(platform.get('architecture') or release.get('target') or 'архитектура не указана')
            if release.get('target'): target += ' · ' + str(release['target'])
            key = str(row.get('platform_key', path.parent.parent.name)) + sid + str(row['version'])
            result.append({'id': bundle_id, 'service': sid, 'name': NAMES[sid], 'version': row['version'],
                'destination': target, 'openwrt_version': str(release.get('version') or ''),
                'openwrt_major': str(release.get('version') or '').split('.')[0],
                'size': sum(file['size'] for file in files if file['available']),
                'complete': bool(row.get('complete')) and all(paths), 'reserved': bool(row.get('reserved')),
                'auto_reserve': bool(bundles.settings().get('enabled')),
                'busy': '*' in pinned or bundle_id in pinned or key in bundles._preparing,
                'files': files, '_paths': paths, '_manifest': path, '_root': bundles.ROOT})
        except (OSError, ValueError, KeyError, TypeError): continue
    return result


def inventory():
    rows = _xui() + _gateway_entries()
    return [{key: value for key, value in row.items() if not key.startswith('_')} for row in rows]


def _find(archive_id):
    if not re.fullmatch(r'[a-f0-9]{64}', archive_id or ''): raise ValueError('Некорректная установочная копия')
    row = next((row for row in _xui() + _gateway_entries() if row['id'] == archive_id), None)
    if not row: raise FileNotFoundError('Установочные файлы не найдены')
    return row


def download_path(archive_id, index):
    row = _find(archive_id)
    if index < 0 or index >= len(row['_paths']) or row['_paths'][index] is None:
        raise FileNotFoundError('Файл не найден')
    return row['_paths'][index], row['files'][index]['name']


def delete(archive_id):
    row = _find(archive_id)
    if row['service'] == '3x-ui':
        with archive_access(row['_root'], blocking=False):
            row = _find(archive_id)
            if row['busy']: raise ArchiveBusy('Копия используется задачей 3x-ui. Дождитесь завершения операции.')
            for path in row['_paths']: path.unlink(missing_ok=True)
            parent = row['_paths'][0].parent
            try: parent.rmdir()
            except OSError: pass
    else:
        with bundles.cache_lock():
            row = _find(archive_id)
            if row['busy']: raise ArchiveBusy('Комплект используется установкой или подтверждённым планом. Завершите или отмените операцию.')
            row['_manifest'].unlink()
            referenced = set(); readable = True
            for manifest in (bundles.ROOT / 'manifests').glob('*/*/*.json'):
                try: referenced.update(entry['sha256'] for entry in json.loads(manifest.read_text())['files'])
                except (OSError, ValueError, KeyError, TypeError): readable = False
            if readable and not bundles._preparing:
                for path in row['_paths']:
                    if path is not None and path.name not in referenced: path.unlink(missing_ok=True)
    return {'ok': True}


def delete_group(service, major):
    if service == '3x-ui' and major == 'linux':
        cache = importlib.import_module('services.3x-ui.impl.release_cache')
        with archive_access(cache.cache_root(), blocking=False):
            rows = _xui()
            if not rows: raise FileNotFoundError('Группа установочных файлов не найдена')
            if any(row['busy'] for row in rows):
                raise ArchiveBusy('Копии используются задачей 3x-ui. Дождитесь завершения операции.')
            for row in rows: delete(row['id'])
        return {'ok': True, 'deleted': len(rows)}
    if service not in ('podkop', 'ssclash', 'adguardhome') or not re.fullmatch(r'\d{2}|SNAPSHOT', major or ''):
        raise ValueError('Некорректная группа установочных файлов')
    with bundles.cache_lock():
        rows = [row for row in _gateway_entries() if row['service'] == service and row['openwrt_major'] == major]
        if not rows: raise FileNotFoundError('Группа установочных файлов не найдена')
        if any(row['busy'] for row in rows):
            raise ArchiveBusy('Часть группы используется установкой или планом. Дождитесь завершения операции.')
        for row in rows: delete(row['id'])
    return {'ok': True, 'deleted': len(rows)}
