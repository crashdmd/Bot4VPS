"""Validation for scoped DHCP, resolver and firewall changes."""
from __future__ import annotations

import ipaddress
import re

ID = re.compile(r'[A-Za-z0-9_]{1,64}')
ZONE_NAME = re.compile(r'[A-Za-z0-9_-]{1,64}')
DHCP = {'ignore', 'start', 'limit', 'leasetime', 'dns'}
DNS = {'port', 'server', 'noresolv', 'cachesize', 'domain', 'local', 'rebind_protection', 'domainneeded', 'boguspriv'}
DEFAULTS = {'input', 'output', 'forward', 'synflood_protect'}
ZONE = {'id', 'input', 'output', 'forward', 'masq', 'mtu_fix'}
RULE = {'id', 'name', 'src', 'dest', 'src_ip', 'dest_ip', 'proto', 'dest_port', 'target', 'enabled'}
REDIRECT = {'id', 'name', 'src', 'dest', 'src_ip', 'dest_ip', 'proto', 'src_dport', 'dest_port', 'enabled', 'reflection'}


def fields(values, allowed):
    if not isinstance(values, dict) or values.keys() - allowed:
        raise ValueError('Неподдерживаемые параметры конфигурации')
    result = {}
    for key, value in values.items():
        if value in (None, '', []):
            result[key] = None
            continue
        if isinstance(value, list) and key not in {'dns', 'server', 'proto', 'src_ip', 'dest_ip'}:
            raise ValueError('Параметр требует одного значения: ' + key)
        items = value if isinstance(value, list) else [value]
        if len(items) > 32 or any(not isinstance(item, str) or len(item) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in item) for item in items):
            raise ValueError('Некорректное значение конфигурации')
        for item in items:
            if key in {'ignore', 'noresolv', 'rebind_protection', 'domainneeded', 'boguspriv', 'synflood_protect', 'masq', 'mtu_fix', 'enabled', 'reflection'}:
                if item not in ('0', '1'): raise ValueError('Некорректный переключатель')
            elif key in {'input', 'output', 'forward'}:
                if item not in ('ACCEPT', 'REJECT', 'DROP'): raise ValueError('Некорректная политика firewall')
            elif key == 'target':
                if item not in ('ACCEPT', 'REJECT', 'DROP'): raise ValueError('В этой форме доступны ACCEPT, REJECT и DROP')
            elif key in {'port', 'start', 'limit', 'cachesize'}:
                high = 65535 if key == 'port' else 1048576
                if not item.isdigit() or not 0 <= int(item) <= high: raise ValueError('Некорректное число: ' + key)
            elif key in {'dns', 'src_ip', 'dest_ip'}:
                if key == 'dns': ipaddress.ip_address(item)
                else: ipaddress.ip_network(item, strict=False)
            elif key == 'server':
                # dnsmasq supports /domain/address#port, address#port and #.
                if not re.fullmatch(r'[A-Za-z0-9_.:/#@\[\]-]+', item): raise ValueError('Некорректный DNS upstream')
            elif key == 'id':
                if item != '*' and not ID.fullmatch(item): raise ValueError('Некорректный идентификатор')
            elif key in {'src', 'dest'}:
                if item != '*' and not ZONE_NAME.fullmatch(item): raise ValueError('Некорректное имя зоны firewall')
            elif key == 'leasetime':
                if item != 'infinite' and not re.fullmatch(r'[1-9][0-9]{0,6}[smhdw]?', item): raise ValueError('Время аренды: например 12h или 1d')
            elif key in {'dest_port', 'src_dport'}:
                for port in item.split():
                    ends = re.split('[:-]', port)
                    if len(ends) > 2 or any(not p.isdigit() or not 1 <= int(p) <= 65535 for p in ends) or int(ends[0]) > int(ends[-1]):
                        raise ValueError('Некорректный порт firewall')
            elif key == 'proto':
                if item not in ('tcp', 'udp', 'icmp', 'icmpv6', 'all'): raise ValueError('Некорректный протокол')
            elif key in {'domain', 'local'}:
                if not re.fullmatch(r'[A-Za-z0-9_./-]+', item): raise ValueError('Некорректный локальный домен')
        result[key] = value
    return result


def normalise(action, data):
    if not isinstance(data, dict) or data.keys() - {'config_hash', 'section', 'interface', 'settings', 'zones', 'rules', 'deleted_rules', 'redirects', 'deleted_redirects'}:
        raise ValueError('Некорректный запрос конфигурации')
    if not isinstance(data.get('config_hash'), str) or not re.fullmatch(r'[a-f0-9]{64}', data['config_hash']):
        raise ValueError('Обновите конфигурацию перед изменением')
    if action != 'firewall' and ('redirects' in data or 'deleted_redirects' in data):
        raise ValueError('Перенаправления доступны только в настройках firewall')
    result = {'config_hash': data['config_hash']}
    if action == 'dhcp':
        name = data.get('interface')
        if not isinstance(name, str) or not ID.fullmatch(name) or name == 'loopback': raise ValueError('Некорректный интерфейс DHCP')
        result['interface'] = name
        result['settings'] = fields(data.get('settings'), DHCP)
    elif action == 'dns':
        name = data.get('section')
        if not isinstance(name, str) or not ID.fullmatch(name): raise ValueError('Выберите экземпляр dnsmasq')
        result['section'] = name
        result['settings'] = fields(data.get('settings'), DNS)
    elif action == 'firewall':
        result['settings'] = fields(data.get('settings'), DEFAULTS)
        for name, allowed in (('zones', ZONE), ('rules', RULE)):
            rows = data.get(name, [])
            if not isinstance(rows, list) or len(rows) > 128: raise ValueError('Слишком много правил firewall')
            result[name] = [fields(row, allowed) for row in rows]
            ids = [row['id'] for row in result[name] if row.get('id')]
            if len(ids) != len(set(ids)): raise ValueError('Идентификаторы firewall повторяются')
        deleted = data.get('deleted_rules', [])
        if not isinstance(deleted, list) or len(deleted) > 128 or any(not isinstance(x, str) or not ID.fullmatch(x) for x in deleted): raise ValueError('Некорректные удаляемые правила')
        if set(deleted) & set(row.get('id') for row in result['rules']): raise ValueError('Правило нельзя одновременно изменить и удалить')
        result['deleted_rules'] = deleted
        if 'redirects' in data or 'deleted_redirects' in data:
            rows = data.get('redirects', [])
            if not isinstance(rows, list) or len(rows) > 128: raise ValueError('Слишком много перенаправлений портов')
            redirects = [fields(row, REDIRECT) for row in rows]
            for row in redirects:
                if not row.get('id') and not all(row.get(key) for key in ('src', 'dest', 'src_dport', 'dest_ip')):
                    raise ValueError('Укажите зоны, внешний порт и IP устройства назначения')
                for key in ('src', 'dest'):
                    if key in row and (not row[key] or row[key] == '*'): raise ValueError('Выберите зону перенаправления')
                if row.get('dest_ip'):
                    if not isinstance(row['dest_ip'], str): raise ValueError('Укажите один IP устройства назначения')
                    ipaddress.ip_address(row['dest_ip'])
                if isinstance(row.get('src_ip'), list): raise ValueError('Укажите один IP или подсеть источника')
                protocols = row.get('proto') or ['tcp', 'udp']
                protocols = protocols if isinstance(protocols, list) else [protocols]
                if any(value not in ('tcp', 'udp') for value in protocols): raise ValueError('Перенаправление портов поддерживает TCP и UDP')
                for key in ('src_dport', 'dest_port'):
                    if row.get(key) and len(row[key].split()) != 1: raise ValueError('Укажите один порт или диапазон')
                if 'src_dport' in row and not row['src_dport']:
                    raise ValueError('Укажите внешний порт перенаправления')
            ids = [row['id'] for row in redirects if row.get('id')]
            deleted = data.get('deleted_redirects', [])
            if len(ids) != len(set(ids)): raise ValueError('Идентификаторы перенаправлений повторяются')
            if not isinstance(deleted, list) or len(deleted) > 128 or any(not isinstance(x, str) or not ID.fullmatch(x) for x in deleted) or len(deleted) != len(set(deleted)):
                raise ValueError('Некорректные удаляемые перенаправления')
            if set(deleted) & set(ids): raise ValueError('Перенаправление нельзя одновременно изменить и удалить')
            if set(ids + deleted) & set(row.get('id') for row in result['rules']): raise ValueError('Секция firewall указана в разных типах правил')
            result.update(redirects=redirects, deleted_redirects=deleted)
    elif action != 'firewall_restart':
        raise ValueError('Действие не поддерживается')
    return result
