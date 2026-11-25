"""Verified installation bundles, keyed by router platform and kernel ABI."""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import tarfile
import time
import threading
from contextlib import contextmanager, asynccontextmanager
from urllib.parse import urlsplit

import httpx

from core.install_paths import get_install_path
from core.json_store import JsonDocumentStore, atomic_write_json, locked
from core.service_projects import PROJECTS

ROOT = get_install_path() / 'data/gateway-bundles'
REPOS = {name: PROJECTS[name]['repository'] for name in ('podkop', 'ssclash', 'adguardhome')}
_locks = {}
_store_lock = threading.RLock()
_preparing = set()
SETTINGS = JsonDocumentStore(ROOT / 'settings.json', name='OPENWRT BUNDLES')


def settings():
    rows = SETTINGS.read()
    return rows[0] if rows else {'enabled': False, 'keep': 3}


def configure(enabled, keep):
    if keep not in (2, 3):
        raise ValueError('Можно хранить 2 или 3 версии')
    SETTINGS.write([{'enabled': bool(enabled), 'keep': keep}])
    collect()
    return settings()


@contextmanager
def cache_lock():
    ROOT.mkdir(parents=True, exist_ok=True)
    with locked(ROOT / '.cache.lock', _store_lock):
        yield


def pin(bundle_id, token, expires):
    with cache_lock():
        directory = ROOT / 'pins'
        directory.mkdir(parents=True, exist_ok=True)
        atomic_write_json(directory / token, {'bundle_id': bundle_id, 'expires': expires})


def unpin(token):
    with cache_lock():
        (ROOT / 'pins' / token).unlink(missing_ok=True)


def collect():
    """Retain explicitly reserved versions and active operation bundles."""
    with cache_lock():
        now = time.time(); pinned = set()
        for path in (ROOT / 'pins').glob('*'):
            try:
                record = json.loads(path.read_text())
                if record['expires'] > now: pinned.add(record['bundle_id'])
                else: path.unlink()
            except (OSError, ValueError, KeyError):
                path.unlink(missing_ok=True)
        options = settings(); referenced = set()
        for directory in (ROOT / 'manifests').glob('*/*'):
            entries = []
            for path in directory.glob('*.json'):
                try:
                    entries.append((path, json.loads(path.read_text())))
                except (OSError, ValueError):
                    continue
            entries.sort(key=lambda item: _version(item[1]['version']) or (0, 0, 0), reverse=True)
            for index, (path, row) in enumerate(entries):
                reserved = options['enabled'] or row.get('reserved')
                keep = row['id'] in pinned or (reserved and index < options['keep']) or (not reserved and now - row.get('created_at', 0) < 3600)
                if not keep: path.unlink(missing_ok=True)
                else: referenced.update(f['sha256'] for f in row['files'])
        # Downloads have no manifest until fully verified. Never sweep them.
        if not _preparing:
            for path in (ROOT / 'objects').glob('*'):
                if path.name not in referenced and now - path.stat().st_mtime > 3600:
                    path.unlink(missing_ok=True)
            for path in (ROOT / 'incoming').glob('*'):
                if now - path.stat().st_mtime > 3600: path.unlink(missing_ok=True)


def compare_versions(left, right):
    """opkg/Debian ordering, including epoch, tilde and revision."""
    def split(value):
        epoch, sep, tail = value.partition(':')
        return (int(epoch), tail) if sep and epoch.isdigit() else (0, value)
    le, left = split(left); re_, right = split(right)
    if le != re_: return 1 if le > re_ else -1
    def order(char):
        return -1 if char == '~' else 0 if not char else ord(char) if char.isalpha() else ord(char) + 256
    while left or right:
        while (left and not left[0].isdigit()) or (right and not right[0].isdigit()):
            a = left[0] if left and not left[0].isdigit() else ''
            b = right[0] if right and not right[0].isdigit() else ''
            if order(a) != order(b): return 1 if order(a) > order(b) else -1
            if a: left = left[1:]
            if b: right = right[1:]
        a = re.match(r'\d*', left).group(); b = re.match(r'\d*', right).group()
        av, bv = int(a or '0'), int(b or '0')
        if av != bv: return 1 if av > bv else -1
        left = left[len(a):]; right = right[len(b):]
    return 0


def satisfies(version, requirement):
    if not requirement: return True
    found = re.fullmatch(r'\s*(>=|<=|=|==|>>|<<|>|<)\s*(\S+)\s*', requirement)
    if not found: raise ValueError('Неподдерживаемое условие версии: ' + requirement)
    relation = compare_versions(version, found[2])
    return {'>=': relation >= 0, '<=': relation <= 0, '=': relation == 0, '==': relation == 0,
            '>>': relation > 0, '<<': relation < 0, '>': relation > 0, '<': relation < 0}[found[1]]


def install_files(bundle, installed):
    if bundle.get('profile') == 'adguardhome': return bundle['files']
    if bundle['platform']['manager'] == 'apk':
        from core.openwrt.apk import install_files as apk_install_files
        return apk_install_files(bundle, installed)
    projects = {'podkop', 'luci-app-podkop', 'luci-i18n-podkop-ru'}
    files = [item for item in bundle['files'] if item['role'] != 'package' or item.get('package') in projects or item.get('package') not in installed]
    versions = {**installed, **{f['package']: f['version'] for f in files if f.get('package')}}
    for item in files:
        if item['role'] != 'package': continue
        control = _ipk_control(object_path(item['sha256']))
        for dependency, requirement in _deps(control.get('Depends', '')):
            if dependency not in versions or not satisfies(versions[dependency], requirement):
                raise ValueError('Несовместимая зависимость ' + dependency + ' ' + requirement + '. Автоматическая замена установленных пакетов отключена; выберите совместимый комплект.')
    return files


def _version(tag):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', tag)
    return tuple(map(int, match.groups())) if match else None


def compatible(release_version, profile, tag):
    return not (profile == 'podkop' and str(release_version).startswith('23.') and (_version(tag) or (999, 0, 0)) >= (0, 5, 0))


def release_compatible(release_version, profile, release, platform):
    if not compatible(release_version,profile,release['tag_name']): return False
    if profile == 'adguardhome': return True
    names = {asset['name'] for asset in release.get('assets', [])}
    if profile == 'podkop':
        extension = '.apk' if platform.get('manager') == 'apk' else '.ipk'
        return any(name.endswith(extension) and name.startswith(('podkop-','podkop_')) for name in names)
    from core.openwrt.service_versions import ssclash_architecture
    binary = ssclash_architecture(platform)
    return bool(binary and 'ssclash-linux-'+binary in names and 'sha256sums.txt' in names)


async def releases(profile):
    repo = REPOS.get(profile)
    if not repo:
        raise ValueError('Неизвестный проект')
    from core.openwrt import release_catalog
    rows = await release_catalog.get(ROOT, profile, repo)
    return [r for r in rows if not r.get('prerelease') and not r.get('draft') and _version(r.get('tag_name') or '')]


def _allowed_url(url):
    value = urlsplit(url)
    if value.scheme == 'https' and value.hostname == 'dl-cdn.alpinelinux.org' and not value.username and not value.password and re.fullmatch(r'/alpine/v3\.23/main/(x86_64|aarch64)/apk-tools-static-3\.0\.9-r0\.apk', value.path):
        return
    if value.scheme != 'https' or value.username or value.password or value.hostname not in {
        'github.com', 'api.github.com', 'raw.githubusercontent.com', 'objects.githubusercontent.com',
        'release-assets.githubusercontent.com', 'downloads.openwrt.org'}:
        raise ValueError('Источник установочного файла не разрешён')


async def _fetch(http, url, expected=None, limit=128 * 1024 * 1024):
    _allowed_url(url)
    temp_dir = ROOT / 'incoming'; temp_dir.mkdir(parents=True, exist_ok=True)
    temp = temp_dir / os.urandom(16).hex()
    digest = hashlib.sha256(); count = 0
    try:
        async with http.stream('GET', url) as response:
            response.raise_for_status(); _allowed_url(str(response.url))
            with temp.open('wb') as output:
                async for chunk in response.aiter_bytes(128 * 1024):
                    count += len(chunk)
                    if count > limit: raise ValueError('Файл установки превышает допустимый размер')
                    digest.update(chunk); output.write(chunk)
                output.flush(); os.fsync(output.fileno())
        actual = digest.hexdigest()
        if expected and actual != expected.lower(): raise ValueError('Контрольная сумма файла не совпала')
        object_dir = ROOT / 'objects'; object_dir.mkdir(parents=True, exist_ok=True)
        target = object_dir / actual
        os.replace(temp, target)
        return {'sha256': actual, 'size': count, 'source': url}
    finally:
        temp.unlink(missing_ok=True)


def object_path(digest):
    if not re.fullmatch(r'[a-f0-9]{64}', digest or ''): raise ValueError('Некорректная контрольная сумма')
    path = ROOT / 'objects' / digest
    if not path.is_file() or path.is_symlink(): raise ValueError('Файл комплекта отсутствует')
    return path


def _ipk_control(path):
    # OpenWrt release ipk files use gzip tar containing control/data archives.
    with tarfile.open(path) as package:
        member = next(m for m in package.getmembers() if Path(m.name).name == 'control.tar.gz')
        stream = package.extractfile(member)
        with tarfile.open(fileobj=stream) as control:
            entry = next(m for m in control.getmembers() if Path(m.name).name == 'control')
            return _paragraphs(control.extractfile(entry).read().decode())[0]


def _paragraphs(text):
    rows = []
    for paragraph in text.split('\n\n'):
        fields = {}
        for line in paragraph.splitlines():
            if ': ' in line and not line.startswith(' '):
                key, value = line.split(': ', 1); fields[key] = value
        if fields: rows.append(fields)
    return rows


def _deps(value):
    for field in value.split(','):
        alternatives = field.strip().split('|')
        match = re.match(r'([A-Za-z0-9+_.-]+)(?:\s*\(([^)]+)\))?', alternatives[0].strip())
        if match: yield match[1], match[2] or ''


@asynccontextmanager
async def preparing(key):
    async with _locks.setdefault(key, asyncio.Lock()):
        with cache_lock(): _preparing.add(key)
        try: yield
        finally:
            with cache_lock(): _preparing.discard(key)


async def prepare(node, profile, tag, progress, *, platform=None, board=None, reserve=False):
    if profile not in REPOS or not _version(tag): raise ValueError('Некорректный проект или версия')
    from core.openwrt.monitor import client_for
    rpc = await client_for(node)
    if platform is None: platform = await rpc.call('bot4vps', 'packages')
    if board is None: board = await rpc.call('system', 'board')
    if not compatible(board.get('release', {}).get('version'), profile, tag):
        raise ValueError('Эта версия Podkop не поддерживает OpenWrt 23.05. Выберите совместимую версию; обновление роутера не требуется.')
    identity = {'release': board.get('release'), 'kernel': platform.get('kernel'), 'architecture': platform.get('architecture'), 'manager': platform['manager']}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    async with preparing(key + profile + tag):
        directory = ROOT / 'manifests' / key / profile
        target = directory / (tag + '.json')
        if target.exists():
            bundle = json.loads(target.read_text()); await asyncio.to_thread(verify, bundle)
            if (settings()['enabled'] or reserve) and not bundle.get('reserved'):
                bundle['reserved'] = True; atomic_write_json(target, bundle)
            return bundle
        if profile == 'adguardhome':
            from core.openwrt.adguard import prepare_files
            actual = next((release for release in await releases(profile) if release['tag_name'] == tag), None)
            if not actual: raise ValueError('Релиз не найден')
            async with httpx.AsyncClient(trust_env=False, follow_redirects=True, timeout=httpx.Timeout(120, connect=10), headers={'User-Agent': 'Bot4VPS-OpenWrt'}) as http:
                files = await prepare_files(platform, actual, http, progress)
            bundle = {'id': hashlib.sha256((key + profile + tag).encode()).hexdigest(), 'platform_key': key, 'platform': identity, 'profile': profile, 'version': tag, 'files': files, 'changes': [], 'created_at': int(time.time()), 'complete': True, 'reserved': bool(settings()['enabled'] or reserve), 'size': sum(f['size'] for f in files)}
            directory.mkdir(parents=True, exist_ok=True); atomic_write_json(target, bundle); collect()
            return bundle
        if platform['manager'] == 'apk':
            from core.openwrt.apk import prepare_files, resolve_repositories
            actual = next((release for release in await releases(profile) if release['tag_name'] == tag), None)
            if not actual: raise ValueError('Релиз не найден')
            async with httpx.AsyncClient(trust_env=False, follow_redirects=True, timeout=httpx.Timeout(120, connect=10), headers={'User-Agent': 'Bot4VPS-OpenWrt'}) as http:
                await resolve_repositories(platform,board,http,progress)
                files = await prepare_files(platform, key, profile, actual, http, progress)
            bundle = {'id': hashlib.sha256((key + profile + tag).encode()).hexdigest(), 'platform_key': key,
                'platform': identity, 'profile': profile, 'version': tag, 'files': files, 'changes': [],
                'created_at': int(time.time()), 'complete': True, 'reserved': bool(settings()['enabled'] or reserve), 'size': sum(file['size'] for file in files)}
            directory.mkdir(parents=True, exist_ok=True); atomic_write_json(target, bundle); collect()
            await progress('Комплект APK готов: все файлы и зависимости сохранены на панели.')
            return bundle
        if platform['manager'] != 'opkg':
            raise ValueError('Пакетный менеджер роутера не поддерживается')
        installed = dict(line.split(' - ', 1) for line in platform['output'].splitlines() if ' - ' in line)
        actual = next((r for r in await releases(profile) if r['tag_name'] == tag), None)
        if not actual: raise ValueError('Релиз не найден')
        assets = {a['name']: a for a in actual['assets']}
        files = []; dependencies = []
        async with httpx.AsyncClient(trust_env=False, follow_redirects=True, timeout=httpx.Timeout(120, connect=10), headers={'User-Agent': 'Bot4VPS-OpenWrt'}) as http:
            async def add(name, url, role, expected=None):
                await progress('Получаю ' + name + '…')
                info = await _fetch(http, url, expected)
                info.update(name=name, role=role); files.append(info)
                await progress('Получен ' + name + '; SHA-256 проверен' if expected else 'Получен ' + name + '; SHA-256 сохранён')
                return info
            if profile == 'podkop':
                if str(board['release']['version']).startswith('23.') and _version(tag) >= (0, 5, 0):
                    raise ValueError('Эта версия Podkop не поддерживает OpenWrt 23.05. Выберите совместимую версию; обновление роутера не требуется.')
                for name, asset in assets.items():
                    if name.endswith('.ipk') and (name.startswith(('podkop-', 'podkop_')) or name.startswith(('luci-app-podkop-', 'luci-app-podkop_')) or name.startswith('luci-i18n-podkop-ru')):
                        item = await add(name, asset['browser_download_url'], 'package')
                        control = _ipk_control(object_path(item['sha256']))
                        item['package'] = control['Package']; item['version'] = control['Version']
                        dependencies.extend(_deps(control.get('Depends', '')))
            else:
                from core.openwrt.service_versions import ssclash_architecture
                binary_arch = ssclash_architecture(platform)
                if not binary_arch:
                    raise ValueError('Соответствие архитектуры SSClash/Mihomo ещё не проверено для этого роутера')
                checksums = await _fetch(http, assets['sha256sums.txt']['browser_download_url'], limit=65536)
                sums = {line.split()[-1].lstrip('*'): line.split()[0] for line in object_path(checksums['sha256']).read_text().splitlines() if len(line.split()) == 2}
                name = 'ssclash-linux-' + binary_arch
                await add(name, assets[name]['browser_download_url'], 'ssclash', sums.get(name))
                response = await http.get('https://api.github.com/repos/MetaCubeX/mihomo/releases/latest'); response.raise_for_status()
                mihomo = response.json(); desired = 'mihomo-linux-' + binary_arch + '-' + mihomo['tag_name'] + '.gz'
                # amd64 builds can require x86-64-v3. Prefer a compatible build.
                if binary_arch == 'amd64':
                    choices = [a for a in mihomo['assets'] if a['name'].startswith('mihomo-linux-amd64-compatible-') and a['name'].endswith('.gz')]
                    if not choices: raise ValueError('Не найден проверенный совместимый Mihomo для amd64')
                else: choices = [a for a in mihomo['assets'] if a['name'] == desired]
                if not choices: raise ValueError('Ядро Mihomo для архитектуры не найдено')
                await add(choices[0]['name'], choices[0]['browser_download_url'], 'mihomo')
                dependencies = [('kmod-tun', ''), ('kmod-nft-tproxy', '')]
            if not files: raise ValueError('В релизе нет подходящих файлов')
            await progress('Разрешаю все зависимости для версии OpenWrt и ABI ядра…')
            index = {}
            for feed in platform.get('feeds', []):
                if urlsplit(feed).hostname != 'downloads.openwrt.org': continue
                data = await _fetch(http, feed.rstrip('/') + '/Packages.gz', limit=32 * 1024 * 1024)
                text = gzip.decompress(object_path(data['sha256']).read_bytes()).decode()
                for row in _paragraphs(text):
                    row['feed'] = feed; index.setdefault(row.get('Package'), row)
            queue = list(dependencies); resolved = set(i.get('package') for i in files)
            while queue:
                name, requirement = queue.pop(0)
                if name in resolved: continue
                resolved.add(name)
                if name in ('kernel', 'libc', 'libgcc'):
                    if name not in installed: raise ValueError('Базовая зависимость отсутствует: ' + name)
                    if requirement and not satisfies(installed[name], requirement):
                        raise ValueError('Kernel ABI зависимостей не совпадает с роутером')
                    continue
                row = index.get(name)
                if not row: raise ValueError('Не удалось получить зависимость: ' + name)
                if requirement and not satisfies(row['Version'], requirement):
                    raise ValueError('В источнике нет совместимой версии зависимости: ' + name + ' ' + requirement)
                expected = row.get('SHA256sum')
                if not expected: raise ValueError('Нет SHA-256 зависимости: ' + name)
                item = await add(Path(row['Filename']).name, row['feed'].rstrip('/') + '/' + row['Filename'], 'package', expected)
                item['package'] = name; item['version'] = row['Version']
                queue.extend(_deps(row.get('Depends', '')))
        changes = [{'package': f['package'], 'before': installed.get(f['package']), 'after': f['version']}
                   for f in files if f.get('package') and installed.get(f['package']) != f['version']]
        bundle = {'id': hashlib.sha256((key + profile + tag).encode()).hexdigest(), 'platform_key': key,
            'platform': identity, 'profile': profile, 'version': tag, 'files': files, 'changes': changes,
            'created_at': int(time.time()), 'complete': True, 'reserved': bool(settings()['enabled'] or reserve), 'size': sum(f['size'] for f in files)}
        directory.mkdir(parents=True, exist_ok=True); atomic_write_json(target, bundle)
        collect()
        await progress('Комплект готов: все файлы и зависимости сохранены на панели.')
        return bundle


def verify(bundle):
    if not bundle.get('complete'): raise ValueError('Комплект неполный')
    for entry in bundle['files']:
        path = object_path(entry['sha256'])
        with path.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        if digest != entry['sha256'] or path.stat().st_size != entry['size']:
            raise ValueError('Файл резервного комплекта повреждён')


def cached():
    result = []
    for path in (ROOT / 'manifests').glob('*/*/*.json'):
        try:
            row = json.loads(path.read_text())
            result.append({k: row[k] for k in ('id', 'profile', 'version', 'platform', 'complete', 'size', 'created_at')})
        except (OSError, ValueError, KeyError): pass
    return result


def lookup(bundle_id):
    if not re.fullmatch(r'[a-f0-9]{64}', bundle_id or ''): raise ValueError('Некорректный комплект')
    for path in (ROOT / 'manifests').glob('*/*/*.json'):
        row = json.loads(path.read_text())
        if row.get('id') == bundle_id: verify(row); return row
    raise ValueError('Резервный комплект не найден')
