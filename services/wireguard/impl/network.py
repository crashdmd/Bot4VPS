# -*- coding: utf-8 -*-
"""Выделение IP-адресов клиентам в подсети сервера."""
from __future__ import annotations

import ipaddress
from typing import Set

from core.integrator import StepError


def next_client_ip(server_addr: str, used_peers: str) -> str:
    """Первый свободный IP в подсети сервера.
    
    used_peers: многострочная строка с IP-адресами (например, "10.8.0.2/32\n10.8.0.3/32")
    """
    try:
        net = ipaddress.ip_network(server_addr, strict=False)
    except ValueError:
        raise StepError("allocate_client_ip", -1, title="Выделение IP клиенту",
                         detail=f"некорректная подсеть сервера: {server_addr!r}")
    
    server_ip = server_addr.split("/", 1)[0]
    used: Set[ipaddress.IPv4Address] = set()
    
    for line in used_peers.splitlines():
        token = line.strip()
        if not token:
            continue
        try:
            ip = ipaddress.ip_address(token.split("/", 1)[0])
            if ip in used:
                raise StepError("allocate_client_ip", -1, title="Выделение IP клиенту",
                                detail=f"обнаружены дублирующиеся адреса в конфигах: {ip}")
            used.add(ip)
        except ValueError:
            pass

    # .hosts() для IPv4 автоматически исключает сетевой адрес (например, .0) 
    # и broadcast-адрес (.255).
    for ip in net.hosts():
        if str(ip) == server_ip:
            continue
        if ip == net.network_address or ip == net.broadcast_address:
            continue
        if ip not in used:
            return str(ip)
            
    raise StepError("allocate_client_ip", -1, title="Выделение IP клиенту",
                     detail="нет свободных адресов в подсети")