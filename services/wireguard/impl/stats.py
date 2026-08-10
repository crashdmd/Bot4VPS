# -*- coding: utf-8 -*-
"""Чистый парсинг и нормализация статистики WireGuard (без SSH, без состояния).

Весь «живой» сбор данных (SSH, ``wg show wg0 dump``) живёт в сервисе
(``service._read_live``); здесь — только детерминированная трансформация текста в
нормализованные dict'ы. Так парсер можно тестировать изолированно, а оба UI
(Telegram и Web) получают один и тот же источник статистики (ТЗ §19/§20).

Контракт — нормализованный профиль (service обогащает им кэш и live-ответ):

    {
      "name": str, "enabled": bool, "managed": bool,
      "public_key": str | None,
      "allowed_ips": [str, ...],          # ВСЕ allowed-ips пира (ТЗ §7)
      "connected": bool,                   # по последнему handshake (ТЗ §7)
      "last_handshake_ts": int | None,     # сырая epoch-метка
      "last_handshake": str,               # ru-гуманизация
      "rx_bytes": int, "tx_bytes": int,    # СЫРЫЕ байты; UI форматирует (ТЗ §19)
    }
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Порог «подключён»: handshake в течение последних N секунд.
# WireGuard-клиенты с PersistentKeepalive стучатся регулярно (по умолчанию 25с),
# 180с — принятая в экосистеме граница «жив» пира.
CONNECTED_THRESHOLD_S = 180


def parse_dump(text: str) -> Dict[str, Dict[str, Any]]:
    """Разобрать ``wg show wg0 dump`` → ``{pubkey: {allowed_ips, last_handshake_ts,
    rx_bytes, tx_bytes, endpoint}}``.

    Формат dump: первая строка — interface (пропускаем), далее по строке на пир
    (8 таб-полей): ``pubkey \\t psk \\t endpoint \\t allowed-ips \\t
    latest-handshake \\t transfer-rx \\t transfer-tx \\t keepalive``.
    ``latest-handshake == 0`` → ``None`` (никогда). ``allowed-ips == "(none)"`` → ``[]``.
    """
    out: Dict[str, Dict[str, Any]] = {}
    if not text:
        return out
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for idx, line in enumerate(lines):
        if idx == 0:
            continue  # строка интерфейса
        parts = line.split("\t")
        if len(parts) < 8:
            continue  # недостаточно полей — не пир
        pubkey = parts[0].strip()
        if not pubkey:
            continue
        endpoint = parts[2].strip()
        aip_raw = parts[3].strip()
        allowed_ips = [a.strip() for a in aip_raw.split(",") if a.strip() and a.strip() != "(none)"]
        try:
            hs = int(parts[4].strip() or "0")
        except ValueError:
            hs = 0
        try:
            rx = int(parts[5].strip() or "0")
        except ValueError:
            rx = 0
        try:
            tx = int(parts[6].strip() or "0")
        except ValueError:
            tx = 0
        out[pubkey] = {
            "allowed_ips": allowed_ips,
            "last_handshake_ts": hs if hs > 0 else None,
            "rx_bytes": rx,
            "tx_bytes": tx,
            "endpoint": endpoint or None,
        }
    return out


def humanize_handshake(ts: Optional[int], now_ts: int) -> str:
    """ru-гуманизация времени последнего handshake: «никогда»/«N сек назад»/
    «N мин назад»/«N ч назад»/«N дн. назад»."""
    if not ts:
        return "никогда"
    delta = now_ts - ts
    if delta < 0:
        return "только что"
    if delta < 60:
        return f"{delta} сек назад"
    if delta < 3600:
        return f"{delta // 60} мин назад"
    if delta < 86400:
        return f"{delta // 3600} ч назад"
    return f"{delta // 86400} дн. назад"


def build_profile_stats(
    profiles_raw: List[Dict[str, Any]],
    name_to_pubkey: Dict[str, str],
    dump_map: Dict[str, Dict[str, Any]],
    now_ts: int,
) -> List[Dict[str, Any]]:
    """Соединить профили ``[{name,enabled,managed}]`` со статистикой из dump
    (по pubkey) → обогащённые dict'ы. Пир без pubkey/dump-данных получает нули и
    ``connected=False`` (не роняем весь read)."""
    enriched: List[Dict[str, Any]] = []
    for p in profiles_raw:
        name = p.get("name")
        pubkey = name_to_pubkey.get(name) if name else None
        entry = dump_map.get(pubkey) if pubkey else None
        ts = entry.get("last_handshake_ts") if entry else None
        rx = entry.get("rx_bytes", 0) if entry else 0
        tx = entry.get("tx_bytes", 0) if entry else 0
        allowed_ips = entry.get("allowed_ips", []) if entry else []
        connected = bool(ts and (now_ts - ts) <= CONNECTED_THRESHOLD_S)
        enriched.append({
            "name": name,
            "enabled": bool(p.get("enabled")),
            "managed": bool(p.get("managed")),
            "public_key": pubkey,
            "allowed_ips": allowed_ips,
            "connected": connected,
            "last_handshake_ts": ts,
            "last_handshake": humanize_handshake(ts, now_ts),
            "rx_bytes": int(rx or 0),
            "tx_bytes": int(tx or 0),
        })
    return enriched
