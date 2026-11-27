"""Short-lived summaries of Internet flows. Raw samples and log lines stay in memory."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import blake2s
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
import re
from time import monotonic

from core.openwrt.rpc import RpcError


SAMPLE_INTERVAL = 3
IDLE_TTL = 25
MAX_ROWS = 80
MAX_DESTINATIONS = 60
_FAKE_NETWORKS = (ip_network('198.18.0.0/15'), ip_network('fdfe:dcba:9876::/48'))
_FIELDS = re.compile(r'\b(src|dst|sport|dport|bytes|type|code|id)=([^\s]+)')
_PROTOCOL = re.compile(r'^(?:ipv[46]\s+\d+\s+)?([a-z0-9_-]+)\s+\d+\s+\d+\s')
_MAC = re.compile(r'[\da-f]{2}(?::[\da-f]{2}){5}', re.I)
_DOMAIN = re.compile(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}', re.I)
_SERVICES = {
    'YouTube': ('youtube.com', 'googlevideo.com', 'ytimg.com', 'youtu.be'),
    'Instagram': ('instagram.com', 'cdninstagram.com'),
    'Netflix': ('netflix.com', 'nflxvideo.net', 'nflximg.net'),
    'Telegram': ('telegram.org', 't.me', 'telegra.ph'),
    'Steam': ('steampowered.com', 'steamcontent.com', 'steamstatic.com'),
}


def _ip(value):
    try:
        return ip_address(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _domain(value):
    value = value.lower().rstrip('.')
    return value if _DOMAIN.fullmatch(value) else None


def _port(value):
    return int(value) if value and value.isascii() and value.isdigit() and len(value) <= 5 and int(value) <= 65535 else None


def _counter(value):
    return int(value) if value and value.isascii() and value.isdigit() and len(value) <= 20 else None


@dataclass(frozen=True)
class Flow:
    protocol: str
    source: IPv4Address | IPv6Address
    destination: IPv4Address | IPv6Address
    reply_source: IPv4Address | IPv6Address
    source_port: int | None
    destination_port: int | None
    tx: int
    rx: int


def _flows(text):
    records = {}
    offloaded = False
    for line in text.splitlines():
        protocol = _PROTOCOL.match(line)
        if not protocol:
            continue
        pairs = _FIELDS.findall(line)
        replies = [index for index, (name, _) in enumerate(pairs) if name == 'src']
        if len(replies) != 2:
            continue
        original = dict(pairs[:replies[1]])
        reply = dict(pairs[replies[1]:])
        source, destination, reply_source = (_ip(value) for value in (
            original.get('src'), original.get('dst'), reply.get('src')))
        tx, rx = _counter(original.get('bytes')), _counter(reply.get('bytes'))
        if None in (source, destination, reply_source) or tx is None or rx is None:
            continue
        key = (protocol[1], *(tuple(entry.get(field) for field in ('src', 'dst', 'sport', 'dport', 'type', 'code', 'id'))
                              for entry in (original, reply)))
        records[key] = Flow(protocol[1], source, destination, reply_source, _port(original.get('sport')),
                            _port(original.get('dport')), tx, rx)
        offloaded |= '[OFFLOAD]' in line or '[HW_OFFLOAD]' in line
    return records, offloaded


def _endpoint(text):
    addr, sep, port = text.rpartition(':')
    return (_ip(addr.strip('[]')), _port(port)) if sep else (None, None)


def _recent_log(line, captured_at):
    try:
        stamp = datetime.strptime(line[:24], '%a %b %d %H:%M:%S %Y').replace(tzinfo=timezone.utc).timestamp()
    except (ValueError, OverflowError):
        return False
    return -5 <= captured_at - stamp <= 180


def _hints(text, captured_at):
    """Collect client-specific names and recent DNS answers for synthetic addresses."""
    dns = defaultdict(set)
    fake_dns = defaultdict(set)
    queries = defaultdict(set)
    sessions = defaultdict(set)
    addresses = defaultdict(set)
    inbound = {}
    requested = defaultdict(set)
    if not isinstance(captured_at, int):
        return dns, sessions, fake_dns, addresses

    def record(key, host, direct):
        if name := _domain(host):
            sessions[key].add(name)
        elif direct and (address := _ip(host)) and address.is_global and not _is_fake(address):
            addresses[key].add(address)
    for line in text.splitlines():
        if not _recent_log(line, captured_at):
            continue
        entry = re.search(r'\bdnsmasq\[\d+\]:\s*(?:\d+\s+\S+\s+)?(.*)', line)
        if entry:
            query = re.match(r'query\[(?:A|AAAA)\] (\S+) from (\S+)', entry[1])
            result = re.match(r'(?:reply|cached) (\S+) is (\S+)', entry[1])
            if query and (host := _domain(query[1])) and (client := _ip(query[2])):
                queries[host].add(client)
            if result and (host := _domain(result[1])) and (address := _ip(result[2])):
                for client in queries.get(host, ()):
                    dns[client, address].add(host)
                if _is_fake(address):
                    fake_dns[address].add(host)
            continue
        if not re.search(r'\b(?:sing-box|mihomo|ssclash|podkop)\b', line, re.I):
            continue
        answer = re.search(r'\bdns: exchanged (A|AAAA) (\S+)\s+\d+\s+IN\s+\1\s+(\S+)', line)
        if answer and (name := _domain(answer[2])) and (address := _ip(answer[3])) and _is_fake(address):
            fake_dns[address].add(name)
        clash = re.search(r'\[(TCP|UDP)\]\s+(\S+)\s+-->\s+(\S+)', line)
        if clash:
            client, source_port = _endpoint(clash[2])
            host, sep, port = clash[3].rpartition(':')
            if client is not None and source_port and sep and (destination_port := _port(port)):
                record((clash[1].lower(), client, source_port, destination_port), host.strip('[]'), True)
            continue
        box = re.search(r'\[(\d+)\s+[^\]]+\].*?\b(inbound|outbound) (packet )?connection (from|to)\s+(\S+)', line)
        if not box:
            continue
        identity = (box[1], 'udp' if box[3] else 'tcp')
        if box[2] == 'inbound' and box[4] == 'from':
            inbound[identity] = _endpoint(box[5])
        elif box[4] == 'to':
            name, sep, port = box[5].rpartition(':')
            if sep and (destination_port := _port(port)):
                direct = bool(re.search(r'\boutbound/direct(?:\[[^\]]*\])?:', line))
                requested[identity].add((name.strip('[]'), destination_port, direct))
    for identity, destinations in requested.items():
        client, source_port = inbound.get(identity, (None, None))
        if client is not None and source_port:
            for name, port, direct in destinations:
                record((identity[1], client, source_port, port), name, direct)
    return dns, sessions, fake_dns, addresses


def _list(value):
    return value if isinstance(value, list) else []


def _proxy_key(flow):
    return flow.protocol, flow.source, flow.source_port, flow.destination_port


def _controller_hints(rows):
    result = defaultdict(set)
    for row in _list(rows):
        if not isinstance(row, dict) or row.get('network') not in ('tcp', 'udp'):
            continue
        client = _ip(row.get('sourceIP'))
        source_port, destination_port = (_port(str(row.get(key))) for key in ('sourcePort', 'destinationPort'))
        if client is None or not source_port or not destination_port:
            continue
        if isinstance(client, IPv6Address) and client.ipv4_mapped:
            client = client.ipv4_mapped
        host = row.get('host') or row.get('sniffHost')
        name = _domain(host) if isinstance(host, str) else None
        address = _ip(row.get('destinationIP'))
        if address is not None or name:
            result[row['network'], client, source_port, destination_port].add((name, address))
    return result


def _networks(data):
    networks = []
    for item in _list(data):
        try:
            network = ip_network(item, strict=False) if isinstance(item, str) else None
        except ValueError:
            continue
        if network and network.prefixlen:
            networks.append(network)
    return networks


def _local(address, networks):
    return (address.is_unspecified or address.is_loopback or address.is_multicast or address.is_link_local
            or any(address in network for network in networks))


def _is_fake(address):
    return any(address in network for network in _FAKE_NETWORKS)


def _device_map(sample, leases):
    macs, names = {}, {}
    for line in str(sample.get('neighbours') or '').splitlines():
        pair = re.match(r'^(\S+) dev \S+ lladdr (\S+)', line)
        if pair and (address := _ip(pair[1])) and _MAC.fullmatch(pair[2]):
            macs[address] = pair[2].lower()
    for lease in leases:
        if not isinstance(lease, dict) or not (address := _ip(lease.get('ipaddr'))):
            continue
        mac, hostname = lease.get('macaddr'), lease.get('hostname')
        if isinstance(mac, str) and _MAC.fullmatch(mac):
            macs.setdefault(address, mac.lower())
        if isinstance(hostname, str) and hostname.strip():
            names.setdefault(macs.get(address, address), hostname.strip()[:128])
    wifi, ethernet = ({mac.lower() for mac in _list(sample.get(key)) if isinstance(mac, str) and _MAC.fullmatch(mac)}
                      for key in ('wifi', 'ethernet'))
    return macs, names, wifi, ethernet


def _destination(flow, dns, proxy, fake_dns, previous=None, controller_names=()):
    fake_ip = _is_fake(flow.destination)
    direct = dns.get((flow.source, flow.destination), ())
    matched = proxy.get((flow.protocol, flow.source, flow.source_port, flow.destination_port), ()) if fake_ip else ()
    names = controller_names or matched or direct
    if fake_ip and not names:
        names = fake_dns.get(flow.destination, ())
        if previous and len(names) == 1 and previous[2] not in names:
            names = set(names) | {previous[2]}
    if len(names) == 1:
        name = next(iter(names))
        service = next((label for label, suffixes in _SERVICES.items()
                        if any(name == suffix or name.endswith('.' + suffix) for suffix in suffixes)), None)
        return service or name, 'service' if service else 'domain', name
    if not names and previous:
        return previous
    addr = str(flow.destination)
    if flow.destination_port is not None:
        addr = f'[{addr}]:{flow.destination_port}' if flow.destination.version == 6 else f'{addr}:{flow.destination_port}'
    return addr, 'fake-ip' if fake_ip else 'ip', None


def _activity(previous, current, sample, leases, elapsed, *, complete, known=None, flow_starts=None):
    networks = _networks(sample.get('networks'))
    own_addresses = {_ip(value) for value in _list(sample.get('addresses'))}
    macs, names, wifi, ethernet = _device_map(sample, leases)
    logs = sample.get('logs')
    dns, proxy, fake_dns, proxy_ips = _hints(logs if isinstance(logs, str) else '', sample.get('captured_at'))
    controllers = _controller_hints(sample.get('proxy_sessions'))
    observed = defaultdict(set)
    for flow in current.values():
        if (key := _proxy_key(flow)) in controllers:
            observed[key].add(flow.destination)
    devices = {}
    connections = []
    known = known or {}
    retained = {}
    for key, flow in current.items():
        if (not any(flow.source in network for network in networks) or flow.source in own_addresses
                or flow.destination in own_addresses or _local(flow.destination, networks)):
            continue
        if not _is_fake(flow.destination) and (flow.reply_source in own_addresses or _local(flow.reply_source, networks)):
            continue
        before = previous.get(key)
        if before is None and not complete:
            continue
        rx = flow.rx - (before.rx if before else 0)
        tx = flow.tx - (before.tx if before else 0)
        if min(rx, tx) < 0:
            continue
        saved = known.get(key) if before else None
        fake = _is_fake(flow.destination)
        proxy_key = _proxy_key(flow)
        controller_rows = controllers.get(proxy_key, ())
        matched = [(name, address) for name, address in controller_rows
                   if address == flow.destination or (len(observed[proxy_key]) == 1 and (fake or address is None))]
        names_from_controller = {name for name, _ in matched if name}
        label, kind, domain = _destination(flow, dns, proxy, fake_dns, saved[:3] if saved and saved[2] else None,
                                           names_from_controller)
        destination_ip = flow.destination
        if fake:
            destination_ip = flow.reply_source if (
                flow.reply_source.is_global and flow.reply_source not in own_addresses
                and not _is_fake(flow.reply_source) and not _local(flow.reply_source, networks)
            ) else None
            if destination_ip is None:
                candidates = {address for _, address in matched if address is not None and address.is_global
                              and not _is_fake(address)}
                candidates = candidates or proxy_ips.get(proxy_key, ())
                if len(candidates) == 1:
                    candidate = next(iter(candidates))
                    if candidate not in own_addresses and not _local(candidate, networks):
                        destination_ip = candidate
                elif not candidates and saved and saved[2] == domain:
                    destination_ip = saved[3]
        if domain or (fake and destination_ip):
            retained[key] = (label, kind, domain, destination_ip)
        if not (rx or tx):
            continue
        identity = macs.get(flow.source, flow.source)
        connections.append({
            'id': blake2s(repr((key, flow_starts.get(key) if flow_starts else None)).encode(), digest_size=12).hexdigest(),
            'device_name': names.get(identity), 'device_ip': str(flow.source),
            'name': label if domain else None, 'domain': domain,
            'destination_ip': str(destination_ip) if destination_ip else None,
            'observed_ip': str(flow.destination), 'via_fake_ip': fake,
            'rx_bps': round(rx * 8 / elapsed), 'tx_bps': round(tx * 8 / elapsed),
        })
        device = devices.setdefault(identity, {'addresses': set(), 'rx': 0, 'tx': 0, 'connections': 0, 'destinations': {}})
        device['addresses'].add(flow.source)
        entry = device['destinations'].setdefault((kind, label),
            {'name': label, 'kind': kind, 'domain': domain, 'rx': 0, 'tx': 0, 'connections': 0})
        if entry['domain'] != domain:
            entry['domain'] = None
        for item in (entry, device):
            item['rx'] += rx
            item['tx'] += tx
            item['connections'] += 1

    def rates(row):
        return {'connections': row['connections'], 'rx_bps': round(row['rx'] * 8 / elapsed),
                'tx_bps': round(row['tx'] * 8 / elapsed)}

    rows = []
    total = {'rx': 0, 'tx': 0, 'connections': 0}
    for identity, device in sorted(devices.items(), key=lambda pair: -(pair[1]['rx'] + pair[1]['tx'])):
        for key in total:
            total[key] += device[key]
        if len(rows) >= MAX_ROWS:
            continue
        addresses = list(map(str, sorted(device['addresses'], key=lambda addr: (addr.version, int(addr)))))
        destinations = sorted(device['destinations'].values(), key=lambda item: -(item['rx'] + item['tx']))
        rows.append({'id': str(identity), 'ip': addresses[0], 'addresses': addresses, 'name': names.get(identity),
                     'connection_type': 'wifi' if identity in wifi else 'ethernet' if identity in ethernet else None,
                     'destinations': [{**rates(item), **{key: item[key] for key in ('name', 'kind', 'domain')}}
                                      for item in destinations[:MAX_DESTINATIONS]],
                     'destination_count': len(destinations), **rates(device)})
    return {'devices': rows, 'device_count': len(devices), 'connections': connections, 'total': rates(total)}, retained


def session_view(result, view):
    if view == 'devices':
        return {key: value for key, value in result.items() if key != 'connections'}
    data = {key: value for key, value in result.items() if key not in ('devices', 'device_count', 'connections')}
    if view == 'connections':
        data['connections'] = result.get('connections', [])
    return data


def _wan_counters(value):
    if not isinstance(value, dict):
        return {}
    return {name: pair for name, pair in value.items() if isinstance(pair, list) and len(pair) == 2
            and all(type(counter) is int and counter >= 0 for counter in pair)}


def _wan_rates(before, after, elapsed):
    if not before or before.keys() != after.keys():
        return None
    rates = [0, 0]
    for name, counters in after.items():
        for i, counter in enumerate(counters):
            difference = counter - before[name][i]
            if difference < 0:
                return None
            rates[i] += difference
    return {key: round(value * 8 / elapsed) for key, value in zip(('rx_bps', 'tx_bps'), rates)}


@dataclass
class _State:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    sampled: float = 0
    last_ok: float = 0
    boot: str = ''
    client: object = None
    flows: dict = field(default_factory=dict)
    flow_starts: dict = field(default_factory=dict)
    names: dict = field(default_factory=dict)
    wan: dict = field(default_factory=dict)
    complete: bool = False
    reply: dict = field(default_factory=dict)
    expiry: asyncio.TimerHandle | None = None


_states = {}


def forget(node_id):
    state = _states.pop(node_id, None)
    if state and state.expiry:
        state.expiry.cancel()


def clear():
    for sid in tuple(_states):
        forget(sid)


async def sample(node):
    from core.openwrt.monitor import client_for, snapshot

    sid = node['id']
    state = _states.setdefault(sid, _State())
    async with state.lock:
        now = monotonic()
        if _states.get(sid) is not state:
            return {'status': 'unavailable', 'devices': []}
        if state.expiry:
            state.expiry.cancel()
        state.expiry = asyncio.get_running_loop().call_later(IDLE_TTL, forget, sid)
        monitor = snapshot(sid)
        if not monitor.get('ok') or monitor.get('stale'):
            return {'status': 'unavailable', 'devices': []}
        # Older collectors can block rpcd by calling iwinfo synchronously
        # from inside rpcd. Only a recent status reply opts in to sampling.
        if monitor.get('active_sessions_version') != 2:
            return {'status': 'integration', 'devices': []}
        rpc = None
        try:
            rpc = await client_for(node)
            if state.client is rpc and now - state.sampled < SAMPLE_INTERVAL:
                return state.reply
            raw = await rpc.call('bot4vps', 'active_sessions_v2')
        except (RpcError, ValueError, KeyError) as exc:
            state.client, state.sampled, state.last_ok = rpc, monotonic(), 0
            state.reply = {'status': 'integration' if getattr(exc, 'code', '') in ('unsupported', 'permission') else 'unavailable', 'devices': []}
            return state.reply
        now = monotonic()
        same_client = state.client is rpc
        state.client = rpc
        state.sampled = now
        if not isinstance(raw, dict) or raw.get('available') is not True:
            state.last_ok = 0
            state.reply = {'status': 'unavailable', 'devices': []}
            return state.reply
        if not raw.get('accounting'):
            state.last_ok = 0
            state.reply = {'status': 'accounting', 'devices': []}
            return state.reply
        current, offloaded = await asyncio.to_thread(_flows, raw['flows'] if isinstance(raw.get('flows'), str) else '')
        complete = not bool(raw.get('truncated'))
        wan = _wan_counters(raw.get('wan_counters'))
        elapsed = now - state.last_ok
        boot = raw.get('boot_id')
        warming = not same_client or not state.last_ok or elapsed > IDLE_TTL or boot != state.boot
        if not _networks(raw.get('networks')):
            state.last_ok = 0
            state.reply = {'status': 'networks', 'devices': []}
            return state.reply
        reply = {'status': 'warming' if warming else 'ready', 'devices': [], 'sample_seconds': SAMPLE_INTERVAL,
                 'truncated': not complete, 'offloaded': offloaded or bool(raw.get('offloaded'))}
        if warming:
            state.names = {}
            state.flow_starts = dict.fromkeys(current, now)
        else:
            starts = state.flow_starts
            state.flow_starts = {
                key: starts.get(key, now) if (before := state.flows.get(key)) is None
                or (flow.rx >= before.rx and flow.tx >= before.tx) else now
                for key, flow in current.items()
            }
            if not complete:
                state.flow_starts.update((key, starts[key]) for key in state.flows if key not in current)
            result, state.names = await asyncio.to_thread(_activity, state.flows, current, raw,
                _list(monitor.get('clients')), elapsed, complete=state.complete and complete, known=state.names,
                flow_starts=state.flow_starts)
            reply.update(result)
            reply['wan'] = _wan_rates(state.wan, wan, elapsed)
        state.flows, state.boot, state.last_ok, state.complete = current, boot, now, complete
        state.wan = wan
        state.reply = reply
        return reply
