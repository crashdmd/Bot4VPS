"""Explicit SSH console access, separate from the constrained OpenWrt RPC account."""
from __future__ import annotations


def target(node):
    from core.openwrt.feature import require_enabled
    require_enabled()
    if node.get('node_type') != 'openwrt': raise ValueError('Шлюз не найден')
    config = node.get('openwrt', {}).get('ssh')
    if not config: raise ValueError('Укажите SSH-доступ во вкладке «Доступ», чтобы открыть консоль шлюза')
    if not config.get('host_key'): raise ValueError('Сначала проверьте SSH-доступ во вкладке «Доступ»')
    return {**{key: config[key] for key in ('user', 'port', 'auth_type', 'password', 'key_path', 'host_key') if key in config}, 'id': node['id'], 'name': node['name'], 'host': node['host'], '_gateway_node_id':node['id']}
