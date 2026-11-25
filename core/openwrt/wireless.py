"""Scoped wireless edits and on-demand iwinfo scans, without publishing keys."""
from __future__ import annotations

import asyncio
import re
import time

from core.openwrt.operations import _check
from core.openwrt.rpc import RpcClient, RpcError

ID = re.compile(r'[A-Za-z0-9_]{1,64}')
RADIO = {'disabled', 'channel', 'country', 'txpower', 'htmode'}
INTERFACE = {'disabled', 'ssid', 'encryption', 'key', 'hidden', 'isolate', 'network'}
ENCRYPTION = {'none', 'psk2', 'psk2+ccmp', 'psk-mixed', 'sae', 'sae-mixed', 'sae+ccmp', 'sae-mixed+ccmp'}
_scan_locks: dict[str, asyncio.Lock] = {}


def fields(values, allowed):
    if not isinstance(values, dict) or values.keys() - allowed:
        raise ValueError('Неподдерживаемые параметры Wi-Fi')
    result = {}
    for key, value in values.items():
        if value is None:
            if key not in {'country', 'txpower', 'key'}:
                raise ValueError('Параметр Wi-Fi нельзя сбросить: ' + key)
            result[key] = None
            continue
        items = value if isinstance(value, list) else [value]
        if isinstance(value, list) and key != 'network':
            raise ValueError('Параметр Wi-Fi требует одного значения')
        if len(items) > 32 or any(not isinstance(item, str) or len(item) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in item) for item in items):
            raise ValueError('Некорректное значение Wi-Fi')
        for item in items:
            if key in {'disabled', 'hidden', 'isolate'} and item not in {'0', '1'}:
                raise ValueError('Некорректный переключатель Wi-Fi')
            if key == 'ssid' and not 1 <= len(item.encode('utf-8')) <= 32:
                raise ValueError('Имя сети Wi-Fi должно занимать от 1 до 32 байт')
            if key == 'channel' and item != 'auto' and (not item.isdigit() or not 1 <= int(item) <= 233):
                raise ValueError('Некорректный канал Wi-Fi')
            if key == 'country' and not re.fullmatch(r'[A-Z]{2}|00', item):
                raise ValueError('Страна Wi-Fi: двухбуквенный код или 00')
            if key == 'txpower' and (not item.isdigit() or not 0 <= int(item) <= 40):
                raise ValueError('Мощность Wi-Fi должна быть от 0 до 40 dBm')
            if key == 'htmode' and not re.fullmatch(r'NOHT|(?:HT|VHT|HE|EHT)(?:20|40|80|160|320)', item):
                raise ValueError('Некорректный режим ширины канала')
            if key == 'encryption' and item not in ENCRYPTION:
                raise ValueError('Выберите поддерживаемую защиту Wi-Fi')
            if key == 'key' and not (8 <= len(item.encode('utf-8')) <= 63 or re.fullmatch(r'[a-fA-F0-9]{64}', item)):
                raise ValueError('Пароль Wi-Fi: 8–63 байта или 64 шестнадцатеричных символа')
            if key == 'network' and not ID.fullmatch(item):
                raise ValueError('Некорректная сеть для Wi-Fi')
        result[key] = value
    if 'key' in result and result['key'] is None and result.get('encryption') != 'none':
        raise ValueError('Для сохранения пароля не передавайте поле key')
    if result.get('encryption') == 'none':
        result['key'] = None
    if result.get('encryption', '').startswith('sae') and result.get('key') and len(result['key'].encode('utf-8')) > 63:
        raise ValueError('Для WPA3 пароль должен занимать не более 63 байт')
    return result


def normalise(data):
    if not isinstance(data, dict) or data.keys() - {'config_hash', 'radio', 'settings', 'interfaces'}:
        raise ValueError('Некорректный запрос Wi-Fi')
    if not isinstance(data.get('config_hash'), str) or not re.fullmatch(r'[a-f0-9]{64}', data['config_hash']):
        raise ValueError('Обновите Wi-Fi перед изменением')
    if not isinstance(data.get('radio'), str) or not ID.fullmatch(data['radio']):
        raise ValueError('Некорректный радиомодуль')
    rows = data.get('interfaces', [])
    if not isinstance(rows, list) or len(rows) > 32:
        raise ValueError('Некорректные сети Wi-Fi')
    result = {'config_hash': data['config_hash'], 'radio': data['radio'], 'settings': fields(data.get('settings', {}), RADIO), 'interfaces': []}
    for row in rows:
        if not isinstance(row, dict) or row.keys() - {'id', 'settings'} or not isinstance(row.get('id'), str) or not ID.fullmatch(row['id']):
            raise ValueError('Некорректный интерфейс Wi-Fi')
        result['interfaces'].append({'id': row['id'], 'settings': fields(row.get('settings'), INTERFACE)})
    ids = [row['id'] for row in result['interfaces']]
    if len(ids) != len(set(ids)):
        raise ValueError('Сеть Wi-Fi указана несколько раз')
    if not result['settings'] and not any(row['settings'] for row in result['interfaces']):
        raise ValueError('Настройки Wi-Fi не изменены')
    return result


async def _compatible(rpc):
    # Authentication failures must remain authentication failures. Only a
    # missing/forbidden feature on an authenticated session indicates old ACLs.
    await rpc.login()
    try:
        reply = _check(await rpc.call('bot4vps', 'wireless_capabilities'))
    except RpcError as exc:
        if exc.code not in ('unsupported', 'permission'):
            raise
        reply = {}
    if reply.get('version') != 1:
        raise RpcError('Обновите интеграцию Bot4VPS на роутере: установленный обработчик Wi-Fi может блокировать API.', 'contract')


def _device(radio):
    return next((iface['ifname'] for iface in radio.get('interfaces', []) if iface.get('ifname')), radio['name'])


async def _configuration(rpc):
    await _compatible(rpc)
    result = _check(await rpc.call('bot4vps', 'wireless'))
    for radio in result.get('radios', []):
        radio.setdefault('htmodes', [])
        radio.setdefault('frequencies', [])
        device = _device(radio)
        # These calls originate in the panel, so rpcd can service iwinfo.
        try:
            info = _check(await rpc.call('iwinfo', 'info', {'device': device}))
            radio.update({key: info.get(value) for key, value in
                          (('frequency', 'frequency'), ('runtime_channel', 'channel'), ('noise', 'noise'))})
            radio['htmodes'] = info.get('htmodes') or []
            frequencies = _check(await rpc.call('iwinfo', 'freqlist', {'device': device}))
            radio['frequencies'] = frequencies.get('results') or []
        except RpcError as exc:
            if exc.code not in ('unsupported', 'permission', 'rpc'):
                raise
            radio['iwinfo_error'] = str(exc)
        for method, field in (('countrylist', 'countries'), ('txpowerlist', 'txpowers')):
            radio[field] = []
            try:
                response = _check(await rpc.call('iwinfo', method, {'device': device}))
                rows = response.get('results')
                if not isinstance(rows, list): rows = []
                if field == 'countries':
                    choices = {}
                    for row in rows:
                        if not isinstance(row, dict): continue
                        code = row.get('iso3166') or row.get('code')
                        if isinstance(code, str) and re.fullmatch(r'[A-Z]{2}', code):
                            choices[code] = {**row, 'code': code}
                    radio[field] = list(choices.values())
                else:
                    choices = {}
                    for row in rows:
                        if not isinstance(row, dict): continue
                        dbm = row.get('dbm')
                        if isinstance(dbm, int) and not isinstance(dbm, bool) and 0 <= dbm <= 40:
                            choices[dbm] = row
                    radio[field] = sorted(choices.values(), key=lambda row: row['dbm'])
            except RpcError as exc:
                if exc.code not in ('unsupported', 'permission', 'rpc'): raise
    return result


async def validate_hardware(rpc, data):
    config = await _configuration(rpc)
    radio = next((row for row in config.get('radios', []) if row.get('name') == data['radio']), None)
    if not radio:
        raise ValueError('Радиомодуль не найден')
    channel, mode = data.get('settings', {}).get('channel'), data.get('settings', {}).get('htmode')
    if channel and channel != 'auto' and radio['frequencies'] and not any(str(row.get('channel')) == channel and not row.get('restricted') for row in radio['frequencies']):
        raise ValueError('Канал недоступен для этого радиомодуля и страны')
    if mode and radio['htmodes'] and mode not in radio['htmodes']:
        raise ValueError('Режим ширины канала не поддерживается радиомодулем')
    power = data.get('settings', {}).get('txpower')
    if power is not None and not any(str(row.get('dbm')) == power for row in radio.get('txpowers', [])):
        raise ValueError('Мощность не входит в список допустимых значений радиомодуля')
    country = data.get('settings', {}).get('country')
    if country and country != '00' and not any(row.get('code') == country for row in radio.get('countries', [])):
        raise ValueError('Страна не поддерживается регуляторной базой радиомодуля')


async def configuration(node):
    rpc = RpcClient(node['openwrt'])
    try:
        return await _configuration(rpc)
    finally:
        await rpc.close()


async def scan(node, radio):
    if not isinstance(radio, str) or not ID.fullmatch(radio):
        raise ValueError('Некорректный радиомодуль')
    lock = _scan_locks.setdefault(node['id'], asyncio.Lock())
    if lock.locked():
        raise ValueError('Сканирование уже выполняется. Дождитесь результата.')
    async with lock:
        import httpx
        rpc = RpcClient(node['openwrt'])
        rpc.http.timeout = httpx.Timeout(30, connect=5)
        try:
            config = await _configuration(rpc)
            selected = next((row for row in config.get('radios', []) if row.get('name') == radio), None)
            if not selected:
                raise ValueError('Радиомодуль не найден')
            if not selected.get('up'):
                raise ValueError('Для сканирования включите радиомодуль Wi-Fi')
            async def measure():
                reply = _check(await rpc.call('bot4vps', 'wireless_survey', {'radio': radio}))
                return reply.get('survey') or []
            before = await measure()
            reply = await rpc.call('iwinfo', 'scan', {'device': _device(selected)})
            if not isinstance(reply.get('results'), list):
                raise ValueError('Драйвер не вернул результаты сканирования Wi-Fi. Проверьте поддержку iwinfo.')
            await asyncio.sleep(1)
            after = await measure()
            survey = []
            for row in after:
                old = next((item for item in before if item.get('frequency') == row.get('frequency')), {})
                def delta(key):
                    a, b = row.get(key), old.get(key)
                    return a - b if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None
                active, busy = delta('active_ms'), delta('busy_ms')
                survey.append({**{key: row.get(key) for key in ('frequency', 'noise', 'in_use')},
                               'busy_pct': round(100 * busy / active, 1) if active is not None and active > 0 and busy is not None and 0 <= busy <= active else None})
            keys = ('ssid', 'bssid', 'channel', 'frequency', 'mhz', 'band', 'signal', 'quality', 'quality_max', 'encryption',
                    'ht_operation', 'vht_operation', 'he_operation', 'eht_operation')
            return {'radio': radio, 'scanned_at': int(time.time()),
                    'networks': [{key: row[key] for key in keys if key in row} for row in reply['results'] if isinstance(row, dict)],
                    'survey': survey, 'frequencies': selected.get('frequencies') or []}
        finally:
            await rpc.close()
