"""Portable APK metadata/signature reader. It never installs host packages."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import re
import subprocess
import tarfile
import tempfile
import threading
from pathlib import Path

from core.install_paths import get_install_path
from core.json_store import atomic_write_json

ROOT = get_install_path() / 'data/gateway-bundles/tools'
VERSION = '3.0.9-r0'
PINS = {
    'x86_64': 'ea77b2533566e70c9566c03748199b79348010c3199ba02d97e0634cf0fa9ef7',
    'aarch64': '5297264f149a36560c404ac6d4428508c37ca2629140de91b2f832cfc2c98e21',
}
_lock = asyncio.Lock()
_resolver_locks = {}


def tool_path():
    machine = platform.machine()
    if machine not in PINS: raise ValueError('Обработка APK ещё не проверена для архитектуры этой панели')
    directory = ROOT / machine / VERSION
    path = directory / 'apk.static'
    if not path.is_file() or path.is_symlink(): raise ValueError('Обработчик APK не подготовлен')
    record = json.loads((directory / 'identity.json').read_text())
    if record.get('archive_sha256') != PINS[machine] or hashlib.sha256(path.read_bytes()).hexdigest() != record['binary_sha256']:
        raise ValueError('Контрольная сумма обработчика APK не совпала')
    return path


async def ensure(http, progress):
    from core.openwrt import bundles
    async with _lock:
        try: return await asyncio.to_thread(tool_path)
        except (OSError, ValueError, KeyError): pass
        machine = platform.machine()
        if machine not in PINS: raise ValueError('Архитектура панели не поддерживает обработчик APK')
        await progress('Подготавливаю обработку пакетов APK на панели; пакеты роутера не меняются…')
        url = f'https://dl-cdn.alpinelinux.org/alpine/v3.23/main/{machine}/apk-tools-static-{VERSION}.apk'
        archive = await bundles._fetch(http, url, PINS[machine], limit=16 * 1024 * 1024)
        directory = ROOT / machine / VERSION; directory.mkdir(parents=True, exist_ok=True)
        with tarfile.open(bundles.object_path(archive['sha256']), ignore_zeros=True) as package:
            entry = next(item for item in package.getmembers() if item.name.lstrip('./') == 'sbin/apk.static')
            if entry.size > 16 * 1024 * 1024 or not entry.isfile(): raise ValueError('Некорректный обработчик APK')
            binary = package.extractfile(entry).read()
        temporary = directory / 'apk.static.new'; temporary.write_bytes(binary); temporary.chmod(0o755)
        os.replace(temporary, directory / 'apk.static')
        atomic_write_json(directory / 'identity.json', {'archive_sha256': archive['sha256'], 'binary_sha256': hashlib.sha256(binary).hexdigest(), 'license': 'GPL-2.0-only', 'source': url})
        return tool_path()


def dump(path):
    result = subprocess.run([str(tool_path()), 'adbdump', '--format', 'json', str(path)], capture_output=True, timeout=30)
    if result.returncode or len(result.stdout) > 128 * 1024 * 1024:
        raise ValueError('Не удалось прочитать метаданные APK')
    value = json.loads(result.stdout)
    if not isinstance(value, dict): raise ValueError('Некорректные метаданные APK')
    return value


def key_directory(platform_info, platform_key):
    directory = ROOT / 'keys' / platform_key
    directory.mkdir(parents=True, exist_ok=True)
    keys = platform_info.get('apk_keys', [])
    if not keys: raise ValueError('API не предоставил публичные ключи проверки пакетов OpenWrt')
    for item in keys:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+\.(pub|pem)', item.get('name', '')) or len(item.get('data') or '') > 16384 or 'PRIVATE KEY' in (item.get('data') or ''):
            raise ValueError('Некорректный публичный ключ APK')
        filename = item['name'] if item['name'].endswith('.pub') else item['name'] + '.pub'
        temporary = directory / (filename + '.new')
        temporary.write_text(item['data']); os.replace(temporary, directory / filename)
    return directory


def repository_indexes(platform_info):
    """Normalize official repository directories and index URLs for both readers."""
    from core.openwrt import bundles
    from urllib.parse import urlsplit, urlunsplit
    indexes = []
    for raw in platform_info.get('feeds') or []:
        if not isinstance(raw, str): raise ValueError('Некорректный адрес репозитория APK')
        feed = raw.split('#', 1)[0].strip()
        if not feed: continue
        fields = feed.split()
        if len(fields) == 2 and fields[0].startswith('@'): feed = fields[1]
        parsed = urlsplit(feed)
        if parsed.scheme == 'http' and parsed.hostname == 'downloads.openwrt.org':
            feed = urlunsplit(parsed._replace(scheme='https'))
            parsed = urlsplit(feed)
        bundles._allowed_url(feed)
        if parsed.hostname != 'downloads.openwrt.org': continue
        path = parsed.path.rstrip('/')
        if not path.endswith('.adb'):
            path += '/packages.adb'
        feed = urlunsplit(parsed._replace(path=path, fragment=''))
        if feed not in indexes: indexes.append(feed)
    if not indexes:
        raise ValueError('API не предоставил официальные источники APK OpenWrt. Проверьте источники пакетов в LuCI и синхронизацию интеграции Bot4VPS.')
    return indexes


def package_architecture(platform_info):
    architecture = platform_info.get('package_architecture') or platform_info.get('architecture')
    if not isinstance(architecture, str) or not re.fullmatch(r'[A-Za-z0-9_+-]+', architecture):
        raise ValueError('Архитектура пакетов APK не определена')
    return architecture


async def resolve_repositories(platform_info, board, http, progress):
    """Resolve OpenWrt's package ABI separately from apk's compiled CPU name."""
    feeds = platform_info.get('feeds')
    feed_architectures = set()
    if feeds:
        from urllib.parse import urlsplit
        for feed in repository_indexes(platform_info):
            match = re.fullmatch(r'/releases/[^/]+/packages/([^/]+)/[^/]+/packages\.adb', urlsplit(feed).path)
            if match: feed_architectures.add(match[1])
        if not feed_architectures or feed_architectures == {package_architecture(platform_info)}:
            return
    from core.openwrt import bundles
    release = board.get('release') or {}
    version, target = release.get('version'), release.get('target')
    if not isinstance(version,str) or not re.fullmatch(r'[0-9]{2}\.[0-9]{2}\.[0-9]+',version) or not isinstance(target,str) or not re.fullmatch(r'[a-z0-9_+-]+/[a-z0-9_+-]+',target):
        raise ValueError('API не передал источники APK, а официальная версия или платформа OpenWrt не определена')
    kernel = str(platform_info.get('kernel') or '')
    if not feeds:
        match = re.fullmatch(r'([0-9]+\.[0-9]+\.[0-9]+)~([a-f0-9]{32})-r([0-9]+)',kernel)
        if match: kernel_directory = match[1]+'-'+match[3]+'-'+match[2]
        elif re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+-[0-9]+-[a-f0-9]{32}',kernel): kernel_directory = kernel
        else: raise ValueError('API не передал точную версию и ABI ядра для подбора официальных APK-зависимостей')
    root = 'https://downloads.openwrt.org/releases/'+version
    target_root = root+'/targets/'+target
    await progress(('Уточняю архитектуру пакетов APK. ' if feeds else 'API не передал источники APK. ') + 'Получаю официальные метаданные OpenWrt '+version+' · '+target+'…')
    metadata = await bundles._fetch(http,target_root+'/profiles.json',limit=8*1024*1024)
    try: description = json.loads(bundles.object_path(metadata['sha256']).read_text())
    except (OSError, ValueError): raise ValueError('Не удалось прочитать официальные метаданные платформы OpenWrt') from None
    if not isinstance(description,dict): raise ValueError('Официальные метаданные платформы OpenWrt имеют некорректный формат')
    architecture = description.get('arch_packages')
    if description.get('version_number')!=version or description.get('target')!=target or not isinstance(architecture,str) or not re.fullmatch(r'[A-Za-z0-9_+-]+',architecture):
        raise ValueError('Официальные метаданные не совпадают с версией или платформой этого шлюза')
    cpu_architecture = platform_info.get('architecture')
    if architecture != cpu_architecture and not (cpu_architecture == 'aarch64' and architecture.startswith('aarch64_')):
        raise ValueError('Архитектура официальных пакетов не совпадает с архитектурой шлюза')
    if feed_architectures and feed_architectures != {architecture}:
        raise ValueError('Архитектура источников APK не совпадает с официальной платформой шлюза')
    platform_info['package_architecture'] = architecture
    await progress('Архитектура APK: ' + architecture + ' (API роутера: ' + str(cpu_architecture) + ')')
    if feeds: return
    platform_info['feeds'] = [target_root+'/packages/packages.adb',target_root+'/kmods/'+kernel_directory+'/packages.adb',
        *[root+'/packages/'+architecture+'/'+feed+'/packages.adb' for feed in ('base','luci','packages','routing')]]
    await progress('Подобраны официальные источники APK для '+architecture+' и ABI ядра '+kernel)


def fetch_official(row, platform_info, platform_key, keys):
    """apk authenticates unsigned packages using their signed repository index."""
    from core.openwrt import bundles
    with _resolver_locks.setdefault(platform_key, threading.RLock()):
        root = ROOT / 'resolvers' / platform_key
        configuration = root / 'etc/apk'; configuration.mkdir(parents=True, exist_ok=True)
        trust = configuration / 'keys'; trust.mkdir(exist_ok=True)
        for key in keys.glob('*.pub'):
            (trust / key.name).write_bytes(key.read_bytes())
        (configuration / 'repositories').write_text('\n'.join(repository_indexes(platform_info)) + '\n')
        (root / 'var/cache/apk').mkdir(parents=True, exist_ok=True)
        tool = str(tool_path())
        architecture = package_architecture(platform_info)
        if not (root / 'lib/apk/db/installed').exists():
            initialize = [tool, '--root', str(root), '--arch', architecture, '--no-network', 'add', '--initdb', '--no-scripts']
            if os.geteuid() != 0: initialize.append('--usermode')
            result = subprocess.run(initialize, capture_output=True, timeout=120)
            if result.returncode: raise ValueError('Не удалось подготовить проверку репозиториев APK на панели')
        incoming = bundles.ROOT / 'incoming'; incoming.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=incoming) as directory:
            arguments = [tool, '--root', str(root), '--arch', architecture, '--no-progress', '--cache-max-age', '240', 'fetch', '--output', directory, row['name']]
            # fetch's package selector is a name pattern, not a version constraint.
            # Verify the exact version against the reviewed index after fetching.
            result = subprocess.run(arguments, capture_output=True, timeout=120)
            if result.returncode: raise ValueError('Зависимость APK не загружена из проверенного индекса: ' + row['name'])
            paths = list(Path(directory).glob('*.apk'))
            if len(paths) != 1 or paths[0].is_symlink() or paths[0].stat().st_size > 128 * 1024 * 1024:
                raise ValueError('Проверенный источник вернул некорректный комплект APK')
            digest = hashlib.sha256(paths[0].read_bytes()).hexdigest()
            size = paths[0].stat().st_size
            objects = bundles.ROOT / 'objects'; objects.mkdir(exist_ok=True)
            os.replace(paths[0], objects / digest)
            return {'sha256': digest, 'size': size, 'source': row['feed'] + '/' + row['name'] + '-' + row['version'] + '.apk'}


def verify(path, keys, *, project=False):
    arguments = [str(tool_path()), '--keys-dir', str(keys)]
    if project: arguments.append('--allow-untrusted')
    arguments.extend(['verify', str(path)])
    result = subprocess.run(arguments, capture_output=True, timeout=30)
    if result.returncode: raise ValueError('Подпись или целостность APK не подтверждена')


def dependencies(values):
    for value in values or []:
        match = re.fullmatch(r'(!?[A-Za-z0-9_.:+-]+)(?:(>=|<=|=|>|<|~)(\S+))?', value)
        if not match: raise ValueError('Неподдерживаемая зависимость APK: ' + value)
        yield match[1], (match[2] or '') + (match[3] or '')


def satisfies(version, requirement):
    if not requirement: return True
    match = re.fullmatch(r'(>=|<=|=|>|<|~)(\S+)', requirement)
    if not match: raise ValueError('Неподдерживаемое условие версии APK')
    if match[1] == '~': return version == match[2] or version.startswith(match[2] + '.') or version.startswith(match[2] + '-r')
    result = subprocess.run([str(tool_path()), 'version', '-t', version, match[2]], capture_output=True, text=True, timeout=5)
    if result.returncode: raise ValueError('Не удалось сравнить версии APK')
    relation = result.stdout.strip()
    return relation in {'>=': ('>', '='), '<=': ('<', '='), '=': ('=',), '>': ('>',), '<': ('<',)}[match[1]]


def install_files(bundle, installed):
    projects = {'podkop', 'luci-app-podkop', 'luci-i18n-podkop-ru'}
    files = [item for item in bundle['files'] if item['role'] != 'package' or item.get('package') in projects or item.get('package') not in installed]
    versions = {**installed, **{f['package']: f['version'] for f in files if f.get('package')}}
    for item in bundle['files']:
        if item.get('package') not in versions: continue
        for name, requirement in dependencies(item.get('provides')):
            if not name.startswith('!'): versions.setdefault(name, versions[item['package']])
    for item in files:
        for name, requirement in dependencies(item.get('dependencies')):
            if name.startswith('!'):
                if name[1:] in versions: raise ValueError('Конфликт пакетов APK: ' + name[1:])
            elif name not in versions or not satisfies(versions[name], requirement):
                raise ValueError('Несовместимая зависимость APK: ' + name + ' ' + requirement + '. Автоматическая замена установленных пакетов отключена.')
    return files


async def prepare_files(platform_info, platform_key, profile, release, http, progress):
    from core.openwrt import bundles
    feeds = repository_indexes(platform_info)
    architecture = package_architecture(platform_info)
    accepted_architectures = {'noarch', architecture, platform_info['architecture']}
    await ensure(http, progress)
    keys = await asyncio.to_thread(key_directory, platform_info, platform_key)
    files = []; queue = []
    async def add(name, url, role, *, project=False, metadata=None, expected=None):
        await progress('Получаю ' + name + '…')
        item = await asyncio.to_thread(fetch_official, metadata, platform_info, platform_key, keys) if metadata else await bundles._fetch(http, url, expected)
        item.update(name=name, role=role)
        if role == 'package':
            path = bundles.object_path(item['sha256'])
            if project: await asyncio.to_thread(verify, path, keys, project=True)
            info = (await asyncio.to_thread(dump, path)).get('info', {})
            if info.get('arch') not in accepted_architectures: raise ValueError('Архитектура APK не совпадает с роутером')
            if metadata and any(info.get(key, []) != metadata.get(key, []) for key in ('name', 'version', 'arch', 'depends', 'provides')):
                raise ValueError('Метаданные APK не совпадают с проверенным индексом')
            if not re.fullmatch(r'[A-Za-z0-9_.+-]+', info.get('name', '')): raise ValueError('Некорректное имя пакета APK')
            item.update(package=info['name'], version=info['version'], dependencies=info.get('depends', []), provides=info.get('provides', []))
            queue.extend(dependencies(info.get('depends', [])))
        files.append(item)
        await progress('Получен ' + name + '; целостность проверена')
        return item
    assets = {item['name']: item for item in release['assets']}
    if profile == 'podkop':
        for name, asset in assets.items():
            if name.endswith('.apk') and name.startswith(('podkop-', 'luci-app-podkop-', 'luci-i18n-podkop-ru')):
                await add(name, asset['browser_download_url'], 'package', project=True)
    else:
        arch = platform_info['architecture']
        binary_arch = 'amd64' if arch == 'x86_64' else 'arm64' if arch.startswith('aarch64_') or arch == 'aarch64' else None
        if not binary_arch: raise ValueError('Архитектура SSClash/Mihomo ещё не проверена для этого роутера')
        checksums = await bundles._fetch(http, assets['sha256sums.txt']['browser_download_url'], limit=65536)
        sums = {line.split()[-1].lstrip('*'): line.split()[0] for line in bundles.object_path(checksums['sha256']).read_text().splitlines() if len(line.split()) == 2}
        name = 'ssclash-linux-' + binary_arch
        if name not in sums: raise ValueError('Нет контрольной суммы SSClash')
        await add(name, assets[name]['browser_download_url'], 'ssclash', expected=sums[name])
        response = await http.get('https://api.github.com/repos/MetaCubeX/mihomo/releases/latest'); response.raise_for_status()
        mihomo = response.json()
        prefix = 'mihomo-linux-amd64-compatible-' if binary_arch == 'amd64' else 'mihomo-linux-arm64-'
        choices = [a for a in mihomo['assets'] if a['name'].startswith(prefix) and a['name'].endswith('.gz') and mihomo['tag_name'] in a['name']]
        if not choices: raise ValueError('Совместимое ядро Mihomo не найдено')
        await add(choices[0]['name'], choices[0]['browser_download_url'], 'mihomo')
        queue = [('kmod-tun', ''), ('kmod-nft-tproxy', '')]
    if not files: raise ValueError('Релиз не содержит подходящих установочных файлов APK')
    await progress('Проверяю подписи индексов и разрешаю все зависимости APK…')
    index = {}; providers = {}
    for feed in feeds:
        await progress('Индекс APK: ' + feed)
        item = await bundles._fetch(http, feed, limit=32 * 1024 * 1024)
        path = bundles.object_path(item['sha256'])
        await asyncio.to_thread(verify, path, keys)
        rows = (await asyncio.to_thread(dump, path)).get('packages', [])
        matched = 0
        for row in rows:
            if row.get('arch') not in accepted_architectures: continue
            matched += 1
            row['feed'] = feed.rsplit('/', 1)[0]
            index.setdefault(row['name'], row)
            for provided, _ in dependencies(row.get('provides', [])):
                providers.setdefault(provided, row)
        await progress('Проверен индекс APK: ' + str(matched) + ' пакетов для ' + architecture)
    if not index:
        raise ValueError('В проверенных индексах APK нет пакетов для архитектуры ' + architecture)
    installed = dict(line.split(' - ', 1) for line in platform_info['output'].splitlines() if ' - ' in line)
    resolved = {item['package'] for item in files if item.get('package')}
    for item in files:
        resolved.update(name for name, _ in dependencies(item.get('provides', [])))
    while queue:
        name, requirement = queue.pop(0)
        if name.startswith('!'): continue
        if name in resolved: continue
        if name in ('kernel', 'libc', 'libgcc'):
            if name not in installed or not await asyncio.to_thread(satisfies, installed[name], requirement):
                raise ValueError('Базовая зависимость или ABI ядра не совпадает: ' + name)
            resolved.add(name); continue
        row = index.get(name) or providers.get(name)
        if not row: raise ValueError('Не удалось найти зависимость APK: ' + name + ' (проверено индексов: ' + str(len(feeds)) + ')')
        if row['name'] in resolved: resolved.add(name); continue
        if requirement and not await asyncio.to_thread(satisfies, row['version'], requirement):
            raise ValueError('Нет совместимой версии зависимости APK: ' + name + ' ' + requirement)
        filename = row['name'] + '-' + row['version'] + '.apk'
        await add(filename, row['feed'] + '/' + filename, 'package', metadata=row)
        resolved.add(name); resolved.add(row['name'])
        resolved.update(provided for provided, _ in dependencies(row.get('provides', [])))
    return files
