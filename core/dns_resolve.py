# -*- coding: utf-8 -*-
"""Резолв домена сервера в IP — минимальный DNS-клиент на stdlib.

Зачем не системный резолвер: у части пользователей на роутере стоит
AdGuard/Clash с FakeIP — любые домены резолвятся локально в фейковые
адреса, и карточка сервера показывает мусор. Поэтому домены серверов
резолвим ЯВНЫМИ UDP-запросами к публичным DNS, с резервом:

    9.9.9.9   — Quad9 (первичный)
    77.88.8.8 — Яндекс (резерв, если Quad9 недоступен/отфильтровал)

Правило честности: если публичные DNS ОТВЕТИЛИ «записи нет» — это
окончательный ответ, системный резолвер не спрашиваем (при FakeIP он
соврёт). Системный fallback только когда оба сервера недоступны по сети.

Пробы доступности (ping/SSH) продолжают ходить по домену через системный
резолвер — при Clash-роутинге это правильно: туннель сам маршрутизирует.
Через эту цепочку резолвится только ОТОБРАЖАЕМЫЙ IP (monitor.json →
карточка сервера и список «Серверы»).
"""
from __future__ import annotations

import random
import socket
import struct
from typing import List, Optional

# Цепочка DNS для резолва доменов серверов (порядок = приоритет).
RESOLVE_DNS_CHAIN: tuple = ("9.9.9.9", "77.88.8.8")

_QUERY_TIMEOUT = 2.0

# Типы DNS-записей.
_TYPE_A = 1
_TYPE_AAAA = 28


def is_ip_literal(host: str) -> bool:
    """host — уже IP-адрес (IPv4/IPv6), а не домен?"""
    import ipaddress

    try:
        ipaddress.ip_address((host or "").strip())
        return True
    except ValueError:
        return False


def _encode_name(name: str) -> bytes:
    """Домен → секция QNAME (метки с длинами, терминатор 0x00)."""
    parts = []
    for label in (name or "").rstrip(".").split("."):
        raw = label.encode("ascii", errors="strict")
        if not raw or len(raw) > 63:
            raise ValueError(f"некорректная метка домена: {label!r}")
        parts.append(bytes([len(raw)]) + raw)
    return b"".join(parts) + b"\x00"


def _skip_name(data: bytes, offset: int) -> int:
    """Пропустить имя в ответе (учитывая компрессионные указатели 0xC0)."""
    while True:
        if offset >= len(data):
            raise ValueError("усечённый DNS-ответ")
        length = data[offset]
        if length == 0:
            return offset + 1
        if (length & 0xC0) == 0xC0:
            # указатель — имя закончилось (на него уходит 2 байта)
            if offset + 1 >= len(data):
                raise ValueError("усечённый DNS-ответ")
            return offset + 2
        offset += 1 + length


def _query(dns_server: str, name: str, qtype: int,
           timeout: float = _QUERY_TIMEOUT) -> Optional[List[str]]:
    """Один UDP-запрос к DNS-серверу → список IP.

    None — сервер недоступен/ответ не распарсился (можно пробовать следующий);
    [] — сервер ответил, но записей этого типа нет (окончательный ответ
    для этого сервера).
    """
    transaction_id = random.randint(0, 0xFFFF)
    # RD=1 (рекурсия желательна), один вопрос.
    header = struct.pack(">HHHHHH", transaction_id, 0x0100, 1, 0, 0, 0)
    question = _encode_name(name) + struct.pack(">HH", qtype, 1)
    packet = header + question

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(packet, (dns_server, 53))
        data, _ = sock.recvfrom(4096)
    finally:
        try:
            sock.close()
        except OSError:
            pass

    if len(data) < 12:
        return None
    rid, flags, qdcount, ancount, _, _ = struct.unpack(">HHHHHH", data[:12])
    if rid != transaction_id:
        return None  # чужой/битый ответ — считаем сервер ненадёжным
    rcode = flags & 0x0F
    if rcode not in (0, 3):  # 0=NOERROR, 3=NXDOMAIN; остальное — сервер ошибся
        return None

    offset = 12
    for _ in range(qdcount):
        offset = _skip_name(data, offset)
        offset += 4  # QTYPE + QCLASS

    ips: List[str] = []
    for _ in range(ancount):
        offset = _skip_name(data, offset)
        if offset + 10 > len(data):
            return None
        atype, _, _, rdlength = struct.unpack(">HHIH", data[offset:offset + 10])
        offset += 10
        rdata = data[offset:offset + rdlength]
        offset += rdlength
        if atype == _TYPE_A and rdlength == 4:
            ips.append(socket.inet_ntoa(rdata))
        elif atype == _TYPE_AAAA and rdlength == 16:
            ips.append(socket.inet_ntop(socket.AF_INET6, rdata))
        # CNAME и прочее пропускаем — ищем только адреса
    return ips


def resolve_host(host: str, timeout: float = _QUERY_TIMEOUT) -> Optional[str]:
    """Домен → IP через цепочку публичных DNS; IP-литерал проходит как есть.

    Возвращает None, если резолвить нечего/нечем: домена нет в DNS
    (авторитетный ответ) или вся цепочка недоступна и системный резерв
    тоже молчит. Вызывающий код НЕ должен затирать прежнее значение None-ом.
    """
    host = (host or "").strip()
    if not host:
        return None
    if is_ip_literal(host):
        return host

    # «www.example.com. » с точкой на конце — валидный FQDN, нормализуем.
    name = host.rstrip(".")

    chain_unreachable = True
    for dns_server in RESOLVE_DNS_CHAIN:
        try:
            ips = _query(dns_server, name, _TYPE_A, timeout)
            if ips:
                return ips[0]
            if ips is not None:
                # Сервер ответил: A-записи нет. Проверим AAAA — вдруг адрес
                # только IPv6. Пустой ответ этого сервера не «недоступность».
                ips6 = _query(dns_server, name, _TYPE_AAAA, timeout)
                if ips6:
                    return ips6[0]
                chain_unreachable = False
                continue
        except (OSError, ValueError):
            continue  # таймаут/сеть — пробуем следующий DNS цепочки

    if chain_unreachable:
        # Оба публичных DNS недоступны (UDP 53 закрыт?). Последний резерв —
        # системный резолвер: у большинства пользователей он честный.
        try:
            return socket.gethostbyname(name)
        except OSError:
            return None
    return None
