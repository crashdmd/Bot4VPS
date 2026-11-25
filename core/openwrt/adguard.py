"""Official GitHub binaries and non-destructive OpenWrt setup guidance."""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import tarfile


def architecture(package_arch):
    known = {'x86_64': 'amd64', 'i386': '386', 'i686': '386', 'x86': '386',
             'aarch64': 'arm64', 'riscv64': 'riscv64', 'armv7': 'armv7', 'armhf': 'armv6'}
    if package_arch in known: return known[package_arch]
    if package_arch.startswith('aarch64_'): return 'arm64'
    if package_arch.startswith('arm_cortex-a') or package_arch.startswith('arm_armv7'): return 'armv7'
    if package_arch.startswith('arm_arm1176'): return 'armv6'
    if package_arch.startswith(('arm_arm926', 'arm_fa526', 'arm_xscale')): return 'armv5'
    if package_arch.startswith('mipsel_'): return 'mipsle_softfloat'
    if package_arch.startswith('mips_'): return 'mips_softfloat'
    if package_arch.startswith('mips64el_'): return 'mips64le_softfloat'
    if package_arch.startswith('mips64_'): return 'mips64_softfloat'
    raise ValueError('Для этой архитектуры пока нет проверенного соответствия AdGuard Home: ' + package_arch)


def extract_binary(archive):
    """Extract only the expected executable; no archive paths reach the filesystem."""
    from core.openwrt.bundles import ROOT
    with tarfile.open(archive, 'r:gz') as tar:
        candidates = [entry for entry in tar.getmembers() if entry.name.removeprefix('./') == 'AdGuardHome/AdGuardHome']
        if len(candidates) != 1 or not candidates[0].isfile() or not 0 < candidates[0].size <= 128 * 1024 * 1024:
            raise ValueError('В архиве нет допустимого исполняемого файла AdGuard Home')
        temp = ROOT / 'incoming' / os.urandom(16).hex()
        digest = hashlib.sha256(); size = 0
        try:
            with tar.extractfile(candidates[0]) as source, temp.open('wb') as target:
                while chunk := source.read(128 * 1024):
                    size += len(chunk)
                    if size > candidates[0].size: raise ValueError('Размер исполняемого файла изменился')
                    digest.update(chunk); target.write(chunk)
                target.flush(); os.fsync(target.fileno())
            if size != candidates[0].size: raise ValueError('Архив обрезан')
            target = ROOT / 'objects' / digest.hexdigest(); os.replace(temp, target)
            return {'name': 'AdGuardHome', 'role': 'adguardhome', 'sha256': digest.hexdigest(), 'size': size}
        finally: temp.unlink(missing_ok=True)


async def prepare_files(platform, release, http, progress):
    from core.openwrt.bundles import _fetch, object_path
    binary_arch = architecture(platform['architecture'])
    name = 'AdGuardHome_linux_' + binary_arch + '.tar.gz'
    assets = {entry['name']: entry for entry in release.get('assets', [])}
    if name not in assets or 'checksums.txt' not in assets:
        raise ValueError('В релизе нет бинарного файла или официальной контрольной суммы для роутера')
    await progress('Получаю официальные контрольные суммы AdGuard Home…')
    checksums = await _fetch(http, assets['checksums.txt']['browser_download_url'], limit=65536)
    sums = {line.split()[-1].lstrip('*').removeprefix('./'): line.split()[0] for line in object_path(checksums['sha256']).read_text().splitlines() if len(line.split()) == 2}
    if name not in sums: raise ValueError('Официальная контрольная сумма архива отсутствует')
    await progress('Получаю ' + name + ' для ' + platform['architecture'] + '…')
    archive = await _fetch(http, assets[name]['browser_download_url'], sums[name])
    binary = await asyncio.to_thread(extract_binary, object_path(archive['sha256']))
    binary.update(source=archive['source'], archive_sha256=archive['sha256'])
    await progress('SHA-256 архива проверен. Бинарный файл сохранён на панели; роутеру не потребуется доступ к GitHub.')
    return [binary]


GUIDE = [
    'Установка сохраняет бинарный файл и службу procd. DNS, DHCP и firewall остаются в прежнем состоянии; сервис не запускается автоматически.',
    'Перед первым запуском проверьте свободный TCP-порт 3000. Мастер AdGuard Home откроется по адресу роутера:3000 только на адресе управления.',
    'В мастере оставьте веб-интерфейс на адресе LAN, выберите свободный порт (например 3000 или 8080). Не выбирайте 80/443: они обычно заняты LuCI. Создайте отдельный пароль администратора.',
    'Для первого безопасного теста задайте DNS-порт 5353 и адрес LAN или loopback. Не включайте DHCP в AdGuard Home: его продолжает обслуживать OpenWrt. Не открывайте DNS и веб-интерфейс на WAN.',
    'Задайте upstream и bootstrap DNS в AdGuard Home, затем проверьте запрос: dig @АДРЕС_РОУТЕРА -p 5353 example.org (например dig @192.168.1.1 -p 5353 example.org). Если dig отсутствует, выполните проверку с компьютера с установленным dig; стандартный nslookup не умеет переносимо указывать этот порт. Проверьте фильтрацию и журнал запросов до переключения клиентов.',
    'Простой вариант: оставьте dnsmasq на 53, в «Сеть → DNS» укажите upstream АДРЕС_РОУТЕРА#5353 и включите «Использовать только указанные upstream». В AdGuard Home не направляйте обычные запросы обратно на dnsmasq: это создаст петлю. Настройки DHCP менять не нужно.',
    'Если Podkop/другой сервис использует nftset или ipset, сохраните обработку его доменов через dnsmasq. Полную замену DNS на порту 53 сначала настройте в LuCI по официальной инструкции: она переносит dnsmasq на 54 и задаёт локальные/PTR resolver в AdGuard Home.',
    'Панель покажет план перед изменением DNS. Если API станет недоступен, конфигурация откатится. Сохранение доступа к API само по себе не подтверждает работу DNS: отдельно проверьте интернет и имена с клиентского устройства.',
    'Перед удалением AdGuard Home верните рабочие upstream DNS и проверьте клиентов. Панель не удалит сервис, пока dnsmasq ссылается на его адрес и порт. Конфигурацию можно сохранить в резерв; общие пакеты и другие службы не удаляются.',
]


async def guide(node):
    from core.openwrt.rpc import RpcClient
    rpc = RpcClient(node['openwrt'])
    try:
        result = await rpc.call('bot4vps', 'adguard_info')
        if result.get('error'): raise ValueError(result['error'])
        return {**result, 'steps': GUIDE, 'sources': [
            {'name': 'OpenWrt: AdGuard Home', 'url': 'https://openwrt.org/docs/guide-user/services/dns/adguard-home'},
            {'name': 'AdGuard Home: Getting Started', 'url': 'https://github.com/AdguardTeam/AdGuardHome/wiki/Getting-Started'}]}
    finally: await rpc.close()
