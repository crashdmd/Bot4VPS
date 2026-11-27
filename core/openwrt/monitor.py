"""Shared OpenWrt snapshots. A UI request never creates another polling loop."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
import math
from core import state_db
from core.openwrt.rpc import RpcClient, RpcError

_clock = time.monotonic
_clients = {}
_samples = {}
_locks = {}
_previous = {}
_retry_at = {}
_removed = set()
TRAFFIC_PERIODS = (900, 3600, 21600, 43200, 86400)


async def _availability(node, online, error='', system=None):
    from core.openwrt.feature import enabled
    if not enabled(): return
    if node['id'] in _removed: return
    from core.monitor import update_server_availability, record_online_anchor, record_offline_anchor
    event = await asyncio.to_thread(update_server_availability, node, online=online, error=error, system=system)
    if not isinstance(event, dict):
        return
    # Linux online anchors perform another SSH information probe. Gateways already
    # supplied their native system snapshot and must not enter that Linux path.
    if not online: await asyncio.to_thread(record_offline_anchor, node, event)
    from core.event_service import notify_event
    from core.event_types import EventType, EventLevel, EventReason
    await notify_event(EventType.SERVER, EventLevel.INFO if online else EventLevel.CRITICAL,
        'API шлюза снова доступен' if online else 'API шлюза недоступен',
        f'Шлюз «{node["name"]}»: ' + ('подключение восстановлено.' if online else error),
        {**event, 'node_type': 'openwrt', 'reason': (EventReason.SERVER_ONLINE if online else EventReason.SERVER_OFFLINE).value})


async def client_for(node):
    if node['id'] in _removed:
        from core.storage import find_server
        if not await asyncio.to_thread(find_server, node['id']):
            raise RpcError('Шлюз удалён', 'configuration')
        _removed.discard(node['id'])
    config = node.get("openwrt") or {}
    version = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    cached = _clients.get(node["id"])
    if cached and cached[0] == version:
        return cached[1]
    if cached:
        await cached[1].close()
    client = RpcClient(config)
    _clients[node["id"]] = (version, client)
    _previous.pop(node["id"], None)
    return client


def snapshot(node_id):
    data = dict(_samples.get(node_id) or {"ok": False, "error": "Ожидание первого сбора", "error_code": "pending"})
    data["stale"] = not data.get("checked_at") or time.time() - data["checked_at"] > 75
    return data


def traffic_series(node_id, seconds=3600, limit=240, *, now=None):
    """Return a bounded series for the requested window without router calls."""
    if seconds not in TRAFFIC_PERIODS:
        raise ValueError('Выберите период трафика: 15 минут, час, 6 часов, 12 часов или сутки')
    end = int(time.time() if now is None else now)
    start = end - seconds
    history = state_db.iter_gateway_traffic(node_id, start, end)
    step = max(1, seconds / limit); groups = {}
    for point in history:
        key = min(limit - 1, int((point['at'] - start) / step))
        groups.setdefault(key, []).append(point)
    result = []
    for rows in groups.values():
        point = {'at': rows[-1]['at']}
        for role in ('lan', 'wan'):
            point[role] = dict(rows[-1].get(role) or {})
            for field in ('rx_bps', 'tx_bps'):
                values = [row.get(role, {}).get(field) for row in rows]
                values = [value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)]
                point[role][field] = sum(values) / len(values) if values else None
        result.append(point)
    return result


def _record_traffic(node_id, ts, totals):
    state_db.record_gateway_traffic(node_id, ts, totals)
    return traffic_series(node_id, now=ts)


def _object(value):
    return value if isinstance(value, dict) else {}


def _rows(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _number(value, fallback=0):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else fallback


def _cpu(text):
    if not isinstance(text, str): return None
    fields = next((line.split()[1:] for line in text.splitlines() if line.startswith("cpu ")), None)
    if not fields or len(fields) < 4:
        return None
    try: values = [int(n) for n in fields[:8]]  # guest times are already in user/nice.
    except (ValueError, TypeError): return None
    return (sum(values), values[3] + (values[4] if len(values) > 4 else 0))


def _wireguard(value):
    result = {}
    for name, iface in _object(value).items():
        if not isinstance(iface, dict): continue
        result[name] = {'name': name, 'listen_port': _number(iface.get('listen_port'), None),
            'peers': [{key: peer.get(key) for key in ('endpoint','allowed_ips','last_handshake','recent_handshake','rx_bytes','tx_bytes')}
                for peer in _rows(iface.get('peers'))]}
    return result


def _wifi(devices):
    if not isinstance(devices,dict): return None
    result = []
    # LuCI wireless replies also contain configuration, including Wi-Fi keys.
    # Publish only operational radio/interface fields.
    for name, radio in devices.items():
        if not isinstance(radio, dict): continue
        interfaces = []
        items = radio.get('interfaces') or []
        if not isinstance(items,list): items=[]
        for item in items:
            if not isinstance(item,dict): continue
            info = item.get('iwinfo') or {}
            if not isinstance(info,dict): info = {}
            interfaces.append({'device': item.get('ifname'), **{key: info.get(key) for key in ('ssid', 'mode', 'channel', 'frequency', 'signal', 'quality', 'quality_max', 'bitrate')}})
        result.append({'name': name, 'up': bool(radio.get('up')), 'disabled': bool(radio.get('disabled')), 'interfaces': interfaces})
    return result


async def refresh(node, *, force=False):
    from core.openwrt.feature import enabled
    if not enabled(): return {'ok':False,'error':'Управление OpenWrt выключено','error_code':'disabled'}
    sid = node["id"]
    async with _locks.setdefault(sid, asyncio.Lock()):
        old = _samples.get(sid) or {}
        if not force and (time.time() - old.get("checked_at", 0) < 20 or _retry_at.get(sid, 0) > _clock()):
            return snapshot(sid)
        try:
            rpc = await client_for(node)
            board = await rpc.call("system", "board")
            if not isinstance(board, dict): raise RpcError("Некорректное описание роутера", "response")
            if str(_object(board.get("release")).get("distribution", "")).lower() != "openwrt":
                raise RpcError("API не подтвердил OpenWrt", "response")
            info = await rpc.call("system", "info")
            interfaces = await rpc.call("network.interface", "dump")
            if not isinstance(info, dict) or not isinstance(interfaces, dict): raise RpcError("Некорректный системный ответ API", "response")
        except (RpcError, ValueError, KeyError) as exc:
            if sid in _removed: return {'ok': False, 'error': 'Шлюз удалён', 'error_code': 'removed'}
            _retry_at[sid] = _clock() + 60
            _samples[sid] = {**old, "ok": False, "error": str(exc), "error_code": getattr(exc, "code", "configuration"), "attempted_at": int(time.time())}
            await _availability(node, False, str(exc))
            return snapshot(sid)
        _retry_at.pop(sid, None)
        capabilities = {}
        async def optional(name, obj, method, args=None):
            try:
                result = await rpc.call(obj, method, args)
                if not isinstance(result,dict): raise RpcError('Некорректный необязательный ответ API','response')
                capabilities[name] = {"available": True}
                return result
            except RpcError as exc:
                capabilities[name] = {"available": False, "reason": exc.code}
                return None
        devices = await optional("traffic", "network.device", "status")
        devices = devices or {}
        for iface in _rows(interfaces.get('interface')):
            if not isinstance(iface,dict): continue
            device = iface.get('l3_device') or iface.get('device')
            known = devices.get(device)
            if device and (not isinstance(known,dict) or not isinstance(known.get('statistics'),dict)):
                value = await optional('traffic_' + device,'network.device','status',{'name':device})
                if value: devices[device] = value
        cpu = await optional("cpu", "file", "read", {"path": "/proc/stat"})
        health = await optional("services", "bot4vps", "status")
        if node.get('openwrt', {}).get('signing_private_key'):
            await optional('controls', 'bot4vps-key-' + node['openwrt']['username'].removeprefix('bot4vps_'), 'capabilities')
        leases = await optional("clients", "luci-rpc", "getDHCPLeases", {"family": 4})
        wifi = await optional("wifi", "luci-rpc", "getWirelessDevices")
        now = _clock()
        boot = int(_number(info.get("uptime")))
        previous = _previous.get(sid) or {}
        rebooted = boot < previous.get("uptime", 0)
        cpu_pair = _cpu((cpu or {}).get("data", ""))
        cpu_pct = None
        if cpu_pair and previous.get("cpu") and not rebooted:
            total = cpu_pair[0] - previous["cpu"][0]
            idle = cpu_pair[1] - previous["cpu"][1]
            if total > 0 and 0 <= idle <= total:
                cpu_pct = round(100 * (1 - idle / total), 1)
        network = []
        counters = {}
        for iface in _rows(interfaces.get("interface")):
            if not isinstance(iface,dict): continue
            device = iface.get("l3_device") or iface.get("device")
            dev = _object(devices.get(device))
            statistics = _object(dev.get("statistics"))
            rx, tx = _number(statistics.get("rx_bytes"), None), _number(statistics.get("tx_bytes"), None)
            rates = {"rx_bps": None, "tx_bps": None}
            before = previous.get("counters", {}).get(device)
            if before and now > previous.get("time", now) and not rebooted:
                for field, index, current in (("rx_bps", 0, rx), ("tx_bps", 1, tx)):
                    if isinstance(current, int) and isinstance(before[index], int) and current >= before[index]:
                        rates[field] = round((current - before[index]) / (now - previous["time"]))
            counters[device] = (rx, tx)
            network.append({"name": iface.get("interface"), "device": device, "up": bool(iface.get("up")),
                "role": _object((health or {}).get('network_roles')).get(iface.get('interface')) or ('lan' if str(iface.get('interface','')).startswith('lan') else 'wan' if str(iface.get('interface','')).startswith('wan') else 'other'),
                "protocol": iface.get("proto"), "addresses": [item["address"] for item in _rows(iface.get("ipv4-address")) if isinstance(item.get("address"), str)],
                "link": dev.get("link"), "rx_bytes": rx, "tx_bytes": tx, **rates})
        _previous[sid] = {"cpu": cpu_pair, "counters": counters, "time": now, "uptime": boot}
        memory = info.get("memory") or {}
        root = info.get("root") or {}
        if not isinstance(memory,dict): memory={}
        if not isinstance(root,dict): root={}
        total = _number(memory.get("total"))
        available = min(total, _number(memory.get("available", memory.get("free"))))
        services = []
        states = (health or {}).get('services') or {}
        if not isinstance(states,dict): states={}
        for name, state in states.items():
            if isinstance(state,dict) and state.get("installed"):
                services.append({"id": name, "name": {"podkop": "Podkop", "ssclash": "SSClash-Go", "adguardhome": "AdGuard Home", "dnsmasq": "dnsmasq", "firewall": "Firewall"}.get(name, name), **state})
        result = {"ok": True, "checked_at": int(time.time()), "error": None, "board": board,
            "boot_id": (health or {}).get('boot_id') if isinstance((health or {}).get('boot_id'), str) else None,
            "cpu_pct": cpu_pct, "load": [value / 65536 for value in (info.get("load") if isinstance(info.get("load"),list) else []) if _number(value,None) is not None],
            "uptime": boot, "ram_total": total, "ram_used": max(0, total - available),
            "ram_pct": round(100 * (total - available) / total, 1) if total else None,
            "storage_total": _number(root.get("total")) * 1024, "storage_free": _number(root.get("avail", root.get("free"))) * 1024,
            "temperature": _number((health or {}).get("temperature"), None), "temperature_support": _object((health or {}).get('temperature_support')), "interfaces": network, "services": services,
            "active_sessions_version": (health or {}).get("active_sessions_version"),
            "clients": _rows((leases or {}).get("dhcp_leases")), "wifi": _wifi(wifi),
            "wireguard": _wireguard((health or {}).get('wireguard')), "capabilities": capabilities}
        if sid in _removed: return {'ok': False, 'error': 'Шлюз удалён', 'error_code': 'removed'}
        totals = {}
        for role in ('lan','wan'):
            seen = set(); members=[]
            for iface in network:
                if iface['role']==role and iface['device'] not in seen:
                    seen.add(iface['device']); members.append(iface)
            totals[role] = {key: sum(values) if values else None for key in ('rx_bps','tx_bps','rx_bytes','tx_bytes')
                for values in [[item[key] for item in members if isinstance(item.get(key),(int,float))]]}
            totals[role]['up'] = any(item['up'] for item in members)
        result['traffic'] = totals
        result['traffic_history'] = await asyncio.to_thread(_record_traffic, sid, result['checked_at'], totals)
        if sid in _removed:
            return {'ok': False, 'error': 'Шлюз удалён', 'error_code': 'removed'}
        _samples[sid] = result
        # Persist the existing native probe for Monitoring; no extra router calls.
        from core.metrics import record_sample
        loads = result['load']
        mounts = []
        if result['storage_total'] > 0:
            used = max(0, result['storage_total'] - result['storage_free'])
            mounts.append({'mount': '/', 'fs': None, 'used_kb': used // 1024,
                'total_kb': result['storage_total'] // 1024,
                'used_pct': 100 * used / result['storage_total']})
        cpu_text = (cpu or {}).get('data', '')
        if not isinstance(cpu_text, str): cpu_text = ''
        cpu_count = sum(1 for line in cpu_text.splitlines()
                        if line.split() and line.split()[0].startswith('cpu') and line.split()[0][3:].isdigit())
        sample = {'metrics_ok': bool(loads) and total > 0, 'uptime_seconds': boot,
            'metrics': {**{key: loads[index] if index < len(loads) else None
                          for index, key in enumerate(('load1', 'load5', 'load15'))},
                'cpu_count': cpu_count or None, 'ram_used_kb': result['ram_used'] // 1024,
                'ram_total_kb': total // 1024, 'mounts': mounts}}
        try:
            await asyncio.to_thread(record_sample, node, sample, now=result['checked_at'])
        except Exception as exc:
            print(f"[OPENWRT] metrics {sid}: {type(exc).__name__}", flush=True)
        await _availability(node, True, system={
            "hostname": board.get("hostname"), "os": "openwrt", "os_version": board.get("release", {}).get("version"),
            "kernel": board.get("kernel"), "arch": board.get("release", {}).get("target"), "uptime_seconds": boot})
        return snapshot(sid)


async def polling_job(_context=None):
    from core.openwrt.bootstrap import prune_drafts
    await asyncio.to_thread(prune_drafts)
    from core.openwrt.feature import enabled
    if not enabled(): return
    from core.node_types import load_gateways
    semaphore = asyncio.Semaphore(3)
    async def one(node):
        async with semaphore:
            try:
                await refresh(node)
            except Exception as exc:
                print(f"[OPENWRT] {node.get('id')}: {type(exc).__name__}", flush=True)
    await asyncio.gather(*(one(node) for node in load_gateways()))


async def close_clients():
    from core.openwrt.active_sessions import clear
    clear()
    for _, client in list(_clients.values()):
        await client.close()
    _clients.clear()


async def forget(node_id):
    from core.openwrt.active_sessions import forget as forget_sessions
    forget_sessions(node_id)
    _removed.add(node_id)
    previous = _clients.pop(node_id, None)
    if previous:
        await previous[1].close()
    for data in (_samples, _previous, _retry_at):
        data.pop(node_id, None)
