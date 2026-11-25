"""Validated network forms; all writes use signed plans and router-side rollback."""
from __future__ import annotations

import base64
import ipaddress
import re
import socket
import asyncio
from urllib.parse import urlsplit

from core.openwrt.rpc import RpcClient
from core.openwrt.operations import _check

NAME = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,30}')
FIELDS = {'proto', 'device', 'ipaddr', 'netmask', 'gateway', 'dns', 'metric', 'mtu',
    'defaultroute', 'peerdns', 'auto', 'username', 'password', 'addresses', 'listen_port',
    'private_key', 'ip6addr', 'ip6gw'}
ROUTE_FIELDS = {'interface', 'target', 'netmask', 'gateway', 'metric', 'table', 'onlink'}
PEER_FIELDS = {'id', 'public_key', 'preshared_key', 'endpoint_host', 'endpoint_port',
    'allowed_ips', 'persistent_keepalive', 'route_allowed_ips', 'description'}


def _values(value):
    return value if isinstance(value, list) else [value]


def _text(value):
    if not isinstance(value, str) or len(value) > 256 or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError('Недопустимое значение сетевого поля')
    return value


def _fields(values, allowed):
    if not isinstance(values, dict) or values.keys() - allowed:
        raise ValueError('Сетевые поля не поддерживаются')
    result = {}
    for name, value in values.items():
        if value is None or value == '' or value == []:
            result[name] = None
            continue
        items = _values(value)
        if isinstance(value, list) and name not in ('dns', 'addresses', 'allowed_ips', 'ip6addr'):
            raise ValueError('Для поля ' + name + ' требуется одно значение')
        if len(items) > 32: raise ValueError('Слишком много значений сетевого поля')
        for item in items: _text(item)
        if name in ('ipaddr', 'gateway', 'target', 'ip6gw'):
            for item in items: ipaddress.ip_address(item)
        elif name == 'netmask':
            ipaddress.IPv4Network('0.0.0.0/' + value)
        elif name in ('ip6addr', 'addresses', 'allowed_ips'):
            for item in items: ipaddress.ip_interface(item)
        elif name == 'dns':
            for item in items: ipaddress.ip_address(item)
        elif name in ('metric', 'mtu', 'listen_port', 'endpoint_port', 'persistent_keepalive', 'table'):
            limits = {'mtu': (576, 65535), 'listen_port': (1, 65535), 'endpoint_port': (1, 65535),
                'persistent_keepalive': (0, 65535)}
            low, high = limits.get(name, (0, 4294967295))
            if not value.isdigit() or not low <= int(value) <= high: raise ValueError('Некорректное числовое поле: ' + name)
        elif name in ('defaultroute', 'peerdns', 'auto', 'route_allowed_ips', 'onlink'):
            if value not in ('0', '1'): raise ValueError('Некорректный переключатель: ' + name)
        elif name in ('private_key', 'public_key', 'preshared_key'):
            try:
                if len(base64.b64decode(value, validate=True)) != 32: raise ValueError()
            except (ValueError, TypeError): raise ValueError('Некорректный ключ WireGuard') from None
        elif name == 'device':
            if not re.fullmatch(r'[A-Za-z0-9_.:@-]{1,64}', value): raise ValueError('Некорректное устройство сети')
        elif name in ('interface', 'id'):
            if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', value): raise ValueError('Некорректный идентификатор сети')
        elif name == 'proto':
            if value not in ('static', 'dhcp', 'pppoe', 'wireguard', 'none'): raise ValueError('Протокол не поддерживается')
        elif name == 'endpoint_host':
            if not re.fullmatch(r'[A-Za-z0-9_.:\[\]-]{1,253}', value): raise ValueError('Некорректный адрес пира')
        result[name] = value
    return result


def normalise(action, data):
    if action == 'wireless':
        from core.openwrt.wireless import normalise as wireless_normalise
        return wireless_normalise(data)
    if action in ('dhcp', 'dns', 'firewall', 'firewall_restart'):
        from core.openwrt.configuration import normalise as settings_normalise
        return settings_normalise(action, data)
    if action not in ('edit', 'delete', 'routes', 'up', 'down', 'reconnect'):
        raise ValueError('Сетевое действие не поддерживается')
    if not isinstance(data, dict) or data.keys() - {'interface', 'settings', 'peers', 'routes', 'config_hash'}:
        raise ValueError('Некорректный сетевой запрос')
    result = {}
    if not isinstance(data.get('config_hash'), str) or not re.fullmatch(r'[a-f0-9]{64}', data['config_hash']):
        raise ValueError('Обновите состояние сети перед изменением')
    result['config_hash'] = data['config_hash']
    if action != 'routes':
        name = data.get('interface')
        if not isinstance(name, str) or not NAME.fullmatch(name) or name == 'loopback':
            raise ValueError('Некорректное имя интерфейса')
        result['interface'] = name
    if action == 'edit':
        settings = _fields(data.get('settings'), FIELDS)
        if settings.get('proto') == 'static':
            if not settings.get('ipaddr') or not settings.get('netmask'):
                raise ValueError('Для статического IPv4 укажите адрес и маску')
            ipaddress.IPv4Address(settings['ipaddr'])
            if settings.get('gateway'): ipaddress.IPv4Address(settings['gateway'])
        result['settings'] = settings
        if 'peers' in data:
            if not isinstance(data['peers'], list) or len(data['peers']) > 32: raise ValueError('Некорректные пиры WireGuard')
            result['peers'] = [_fields(peer, PEER_FIELDS) for peer in data['peers']]
            if any(not peer.get('public_key') for peer in result['peers']): raise ValueError('Укажите публичный ключ каждого пира')
    if action == 'routes':
        if not isinstance(data.get('routes'), list) or len(data['routes']) > 64: raise ValueError('Некорректный список маршрутов')
        routes = []
        for route in data['routes']:
            if not isinstance(route, dict): raise ValueError('Некорректный маршрут')
            route = dict(route)
            if isinstance(route.get('target'), str) and '/' in route['target']:
                subnet = ipaddress.IPv4Network(route['target'], strict=False)
                route['target'], route['netmask'] = str(subnet.network_address), str(subnet.netmask)
            routes.append(_fields(route, ROUTE_FIELDS))
        result['routes'] = routes
        for route in result['routes']:
            if not route.get('interface') or not route.get('target'): raise ValueError('Для маршрута укажите сеть и интерфейс')
            ipaddress.IPv4Network(route['target'] + '/' + (route.get('netmask') or '255.255.255.255'), strict=False)
    return result


async def configuration(node):
    rpc = RpcClient(node['openwrt'])
    try:
        return _check(await rpc.call('bot4vps', 'network'))
    finally: await rpc.close()


async def prepare(node, owner, action, data):
    from core.openwrt.feature import require_enabled
    require_enabled()
    from core.openwrt.router_operations import prepare as prepare_operation
    clean = normalise(action, data)
    clean['api_host'] = urlsplit(node['openwrt']['url']).hostname
    try:
        rows = await asyncio.to_thread(socket.getaddrinfo,clean['api_host'],None)
        clean['api_addresses'] = list({row[4][0] for row in rows})[:32]
    except OSError: clean['api_addresses'] = [clean['api_host']]
    return await prepare_operation(node, owner, 'network', action, clean)
