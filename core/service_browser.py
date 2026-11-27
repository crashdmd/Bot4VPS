"""Fixed service destinations and bounded SSH forwarding for the mobile browser.

Only a server-side service definition selects a destination. The phone never
supplies a hostname, port, URL, SSH command, or service credentials.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import json
import ssl
from contextlib import suppress
from dataclasses import dataclass
from urllib.parse import urlsplit


class ServiceRequestGuard:
    """Validate every HTTP request before forwarding to the fixed service.

    Native requests have a known body length. A verified WebSocket handshake
    switches this connection to service frames, never to a generic proxy.
    """
    def __init__(self, target):
        self.target = target
        self.header = b''
        self.body_left = 0
        self.upgrade_key = None
        self.response_header = b''
        self.websocket = False

    @staticmethod
    def host(value):
        if ':' in value:
            return ipaddress.ip_address(value).compressed.lower()
        return value.encode('idna').decode('ascii').lower()

    def validate(self, head):
        lines = head.decode('iso-8859-1').split('\r\n')
        parts = lines[0].split(' ')
        if len(parts) != 3 or parts[0] not in ('GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS') or parts[2] not in ('HTTP/1.0','HTTP/1.1'):
            raise ValueError('Метод туннеля не поддерживается')
        if not parts[1].startswith('/') or parts[1].startswith('//') or '\\' in parts[1]:
            raise ValueError('Туннель не поддерживает произвольные URL')
        headers = {}
        for line in lines[1:]:
            if not line: continue
            if ':' not in line or line[0] in ' \t': raise ValueError('Неверные заголовки сервиса')
            name, value = line.split(':', 1); name = name.lower(); value = value.strip()
            if name.startswith(('x-forwarded-', 'x-bot4vps-')) or name in ('forwarded','proxy-authorization','proxy-connection','transfer-encoding'):
                raise ValueError('Заголовок прокси не поддерживается')
            headers.setdefault(name, []).append(value)
        hosts = headers.get('host', [])
        if len(hosts) != 1: raise ValueError('Укажите Host выбранного сервиса')
        requested = urlsplit(('https' if self.target.tls else 'http') + '://' + hosts[0])
        selected = urlsplit(self.target.origin)
        if requested.username or requested.password or requested.path or requested.query or requested.fragment or not requested.hostname:
            raise ValueError('Неверный Host сервиса')
        port = requested.port or (443 if self.target.tls else 80)
        if self.host(requested.hostname) != self.host(selected.hostname) or port != self.target.port:
            raise ValueError('Назначение туннеля менять нельзя')
        sizes = headers.get('content-length', [])
        if len(sizes) > 1 or sizes and (not sizes[0].isascii() or not sizes[0].isdigit()):
            raise ValueError('Неверная длина запроса')
        self.body_left = int(sizes[0]) if sizes else 0
        if not 0 <= self.body_left <= 32 * 1024 * 1024: raise ValueError('Слишком большой запрос сервиса')
        upgrades = headers.get('upgrade', [])
        if upgrades:
            keys = headers.get('sec-websocket-key', [])
            if len(upgrades) != 1 or upgrades[0].lower() != 'websocket' or parts[0] != 'GET' or self.body_left or len(keys) != 1:
                raise ValueError('Поддерживается только WebSocket выбранного сервиса')
            try: key = base64.b64decode(keys[0], validate=True)
            except ValueError: raise ValueError('Неверный ключ WebSocket') from None
            if len(key) != 16: raise ValueError('Неверный ключ WebSocket')
            self.upgrade_key = keys[0]

    def feed(self, data):
        incoming = self.header + data
        self.header = b''
        accepted = []
        while incoming:
            if self.websocket: accepted.append(incoming); break
            if self.upgrade_key: raise ValueError('Дождитесь подтверждения WebSocket')
            if self.body_left:
                count = min(self.body_left, len(incoming))
                accepted.append(incoming[:count]); incoming = incoming[count:]; self.body_left -= count
                continue
            end = incoming.find(b'\r\n\r\n')
            if end < 0:
                if len(incoming) > 65536: raise ValueError('Слишком большие заголовки сервиса')
                self.header = incoming; break
            if end + 4 > 65536: raise ValueError('Слишком большие заголовки сервиса')
            head, incoming = incoming[:end+4], incoming[end+4:]
            self.validate(head); accepted.append(head)
        return b''.join(accepted)

    def response(self, data):
        if not self.upgrade_key: return
        self.response_header += data
        end = self.response_header.find(b'\r\n\r\n')
        if end < 0:
            if len(self.response_header) > 65536: raise ValueError('Слишком большие заголовки WebSocket')
            return
        if end + 4 > 65536: raise ValueError('Слишком большие заголовки WebSocket')
        lines = self.response_header[:end].decode('iso-8859-1').split('\r\n')
        values = {line.split(':',1)[0].lower():line.split(':',1)[1].strip() for line in lines[1:] if ':' in line}
        expected = base64.b64encode(hashlib.sha1((self.upgrade_key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        self.websocket = (lines[0].split(' ')[1] == '101' and values.get('upgrade','').lower() == 'websocket'
            and 'upgrade' in [token.strip() for token in values.get('connection','').lower().split(',')] and values.get('sec-websocket-accept') == expected)
        self.upgrade_key = None; self.response_header = b''


@dataclass(frozen=True)
class Destination:
    node_id: str
    service: str
    origin: str
    path: str
    host: str
    port: int
    tls: bool
    ssh: dict | None
    certificate: str | None = None
    certificate_pin: str | None = None
    local_addresses: tuple[str, ...] = ()


def identity(node):
    # Changing access, deleting the node, or moving its service invalidates the
    # browser session. Secrets participate in the hash but are never returned.
    return hashlib.sha256(json.dumps(node, sort_keys=True, default=str).encode()).hexdigest()


def destination(node, service, url, local_addresses=()):
    parsed = urlsplit(url)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('У сервиса нет корректного адреса веб-интерфейса')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    if not 1 <= port <= 65535:
        raise ValueError('Некорректный порт веб-интерфейса')
    config = node.get('openwrt', {})
    ssh = None
    if node.get('node_type') == 'openwrt':
        if config.get('ssh', {}).get('host_key'):
            from core.openwrt.console import target
            ssh = target(node)
        elif service == '3x-ui':
            raise ValueError('Этот сервис не относится к шлюзу')
    elif service == '3x-ui':
        if not node.get('host_key'):
            raise ValueError('Сначала проверьте SSH-ключ сервера')
        ssh = node.copy()
    else:
        raise ValueError('Веб-интерфейс этого сервиса не поддерживается')
    # An SSH channel terminates on loopback or an assigned IP of the registered machine, never
    # on a host read from a remote service's URL.
    host = '127.0.0.1' if ssh else parsed.hostname
    pem = config.get('tls_certificate') if service in ('podkop', 'luci') else None
    pin = config.get('tls_sha256') if pem else None
    return Destination(node['id'], service, f'{parsed.scheme}://{parsed.netloc}',
                       parsed.path or '/', host, port, parsed.scheme == 'https', ssh, pem, pin, tuple(local_addresses))


async def resolve(node, service):
    local_addresses = []
    if node.get('node_type') == 'openwrt':
        if service not in ('podkop', 'ssclash', 'adguardhome', 'luci'):
            raise ValueError('Веб-интерфейс этого сервиса не поддерживается')
        from core.openwrt.rpc import RpcClient
        rpc = RpcClient(node['openwrt'])
        try:
            status = await rpc.call('bot4vps', 'status')
            if node['openwrt'].get('ssh', {}).get('host_key'):
                interfaces = await rpc.call('network.interface', 'dump')
                # Fall back only to IP addresses assigned to this router's own
                # interfaces. LAN-only services often do not bind loopback.
                for interface in interfaces.get('interface', []):
                    for entry in interface.get('ipv4-address', []) + interface.get('ipv6-address', []):
                        try: address = ipaddress.ip_address(entry.get('address', ''))
                        except ValueError: continue
                        if not address.is_unspecified and not address.is_multicast and not address.is_link_local:
                            local_addresses.append(str(address))
        finally:
            await rpc.close()
        info = status.get('services', {}).get(service, {})
        if service != 'luci' and not info.get('installed'):
            raise ValueError('Сервис не установлен')
        if service in ('ssclash', 'adguardhome'):
            port = info.get('web_port')
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                raise ValueError('Роутер не сообщил порт веб-интерфейса сервиса')
            host = node['host']
            if ':' in host: host = '[' + host + ']'
            url = f'{"https" if info.get("web_https") else "http"}://{host}:{port}/'
        else:
            root = node['openwrt']['url'].removesuffix('/ubus').rstrip('/')
            url = root + ('/cgi-bin/luci/admin/services/podkop' if service == 'podkop' else '/cgi-bin/luci/')
    elif service == '3x-ui':
        from core import integrator
        state = await integrator.call(service, node['id'], 'get_state')
        url = state.get('panel_url')
        if not state.get('installed') or not isinstance(url, str):
            raise ValueError('Панель 3x-ui не установлена или её адрес неизвестен')
    else:
        raise ValueError('Веб-интерфейс этого сервиса не поддерживается')
    return destination(node, service, url, local_addresses)


class ServiceConnection:
    """One stream; SSH blocking calls stay in worker threads, including close."""
    def __init__(self, target, ssh_client=None):
        self.target = target
        self.shared_ssh = ssh_client
        self.reader = self.writer = self.ssh = self.channel = self.listener = None
        self.bridge_tasks = set()
        self.bridge_diagnostic = None

    async def open(self):
        target = self.target
        host, port = target.host, target.port
        try:
            if target.ssh:
                from core.ssh import create_ssh_client
                self.ssh = self.shared_ssh or await asyncio.to_thread(create_ssh_client, target.ssh)
                last_error = None
                for address in dict.fromkeys((host,) + target.local_addresses):
                    try:
                        self.channel = await asyncio.to_thread(self.ssh.get_transport().open_channel,
                            'direct-tcpip', (address, port), ('127.0.0.1', 0), timeout=8)
                        break
                    except Exception as exc: last_error = exc
                if self.channel is None: raise ValueError('SSH не смог подключиться к веб-интерфейсу сервиса') from last_error
                self.listener = await asyncio.start_server(self._bridge, '127.0.0.1', 0)
                host, port = self.listener.sockets[0].getsockname()[:2]
            context = None
            if target.tls:
                if target.ssh:
                    # The registered router's own address is inside an authenticated SSH channel.
                    # TLS adds framing here; SSH supplies endpoint identity.
                    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                else:
                    context = ssl.create_default_context(cadata=target.certificate)
                    if target.certificate:
                        der = ssl.PEM_cert_to_DER_cert(target.certificate)
                        if not target.certificate_pin or hashlib.sha256(der).hexdigest() != target.certificate_pin:
                            raise ValueError('Некорректный сохранённый TLS-отпечаток')
                        context.check_hostname = False
            self.reader, self.writer = await asyncio.wait_for(asyncio.open_connection(host, port,
                ssl=context, server_hostname=urlsplit(target.origin).hostname if context else None), 12)
            if context and target.certificate_pin and not target.ssh:
                peer = self.writer.get_extra_info('ssl_object').getpeercert(binary_form=True)
                if hashlib.sha256(peer).hexdigest() != target.certificate_pin:
                    raise ValueError('Сертификат веб-интерфейса изменился')
            if self.listener:
                # Python 3.13 wait_closed() also waits for accepted streams.
                # Keep this stream alive until the browser has sent its request.
                self.listener.close()
        except BaseException:
            await self.close()
            raise

    async def _bridge(self, reader, writer):
        task = asyncio.current_task()
        self.bridge_tasks.add(task)
        channel = self.channel
        async def outgoing():
            while data := await reader.read(32768):
                await asyncio.to_thread(channel.sendall, data)
        async def incoming():
            loop = asyncio.get_running_loop()
            fd = channel.fileno()
            while True:
                # Paramiko signals data and EOF on this descriptor. Idle HTTP
                # keep-alives must leave the executor free for other requests.
                ready = loop.create_future()

                def readable():
                    if not ready.done():
                        ready.set_result(None)

                loop.add_reader(fd, readable)
                try:
                    await ready
                finally:
                    loop.remove_reader(fd)
                data = await asyncio.to_thread(channel.recv, 32768)
                if not data:
                    return
                writer.write(data)
                await writer.drain()
        jobs = [asyncio.create_task(outgoing()), asyncio.create_task(incoming())]
        try:
            done, _ = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
            self.bridge_diagnostic = [{"direction": "outgoing" if job is jobs[0] else "incoming", "error": type(job.exception()).__name__ if job.exception() else None} for job in done]
        finally:
            for job in jobs: job.cancel()
            try:
                await asyncio.gather(*jobs, return_exceptions=True)
                await self._close_channel()
            finally:
                writer.close()
                self.bridge_tasks.discard(task)
                with suppress(Exception): await writer.wait_closed()

    async def _close_channel(self):
        channel, self.channel = self.channel, None
        if channel:
            await asyncio.to_thread(channel.close)

    async def close(self):
        if self.listener:
            self.listener.close()
        if self.writer:
            self.writer.close()
        for task in list(self.bridge_tasks): task.cancel()
        await asyncio.gather(*self.bridge_tasks, return_exceptions=True)
        await self._close_channel()
        if self.ssh and not self.shared_ssh: await asyncio.to_thread(self.ssh.close)
        if self.listener:
            with suppress(Exception): await self.listener.wait_closed()
        if self.writer:
            with suppress(Exception): await self.writer.wait_closed()
