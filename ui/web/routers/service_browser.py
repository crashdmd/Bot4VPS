"""Device-bound service tunnels with an explicit window lifetime and recovery grace."""
from __future__ import annotations
import asyncio
import json
import secrets
import time
from contextlib import suppress
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from fastapi import APIRouter, Body, HTTPException, Request, WebSocket
from core.service_browser import Destination, ServiceConnection, ServiceRequestGuard, identity, resolve
from ui.web.security import verified_mobile_device_id

router = APIRouter(tags=['service-browser'])
RECOVERY_SECONDS = 60
PROBE_SECONDS = 5

@dataclass
class BrowserSession:
    device_id: str
    node_id: str
    node_identity: str
    target: Destination
    expires: float
    streams: int = 0
    ssh_client: object = None
    ssh_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    idle_task: object = None
    control: object = None
    connections: set = field(default_factory=set)
    handlers: set = field(default_factory=set)
    closed: asyncio.Event = field(default_factory=asyncio.Event)
    last_reply: float = field(default_factory=time.monotonic)
    last_phone: float = field(default_factory=time.monotonic)
    gateway_available: bool = False

    async def ssh(self):
        if self.closed.is_set(): raise HTTPException(410, 'Сессия сервиса завершена')
        if not self.target.ssh: return None
        async with self.ssh_lock:
            if self.closed.is_set(): raise HTTPException(410, 'Сессия сервиса завершена')
            client = self.ssh_client
            if client is not None and not client.get_transport().is_active():
                self.ssh_client = None
                await asyncio.to_thread(client.close)
            if self.ssh_client is None:
                from core.ssh import create_ssh_client
                self.ssh_client = await asyncio.to_thread(create_ssh_client, self.target.ssh)
            return self.ssh_client

    async def release_ssh(self):
        async with self.ssh_lock:
            client, self.ssh_client = self.ssh_client, None
            if client: await asyncio.to_thread(client.close)

    async def close(self, reason='browser_session_ended'):
        if self.closed.is_set(): return
        self.closed.set()
        if self.idle_task and self.idle_task is not asyncio.current_task(): self.idle_task.cancel()
        self.idle_task = None
        control, self.control = self.control, None
        if control:
            with suppress(Exception): await control.close(4410, reason)
        jobs = [job for job in self.handlers if job is not asyncio.current_task()]
        for job in jobs: job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        await asyncio.gather(*(connection.close() for connection in tuple(self.connections)), return_exceptions=True)
        await self.release_ssh()

    def reply(self):
        self.last_reply = time.monotonic()
        self.gateway_available = True

_sessions: dict[str, BrowserSession] = {}
_streams = 0

def mobile(request):
    device = verified_mobile_device_id(request)
    if not device: raise HTTPException(403, 'Откройте сервис из привязанного мобильного приложения')
    return device

def session_for(key, device):
    session = _sessions.get(key)
    if session is None or session.device_id != device or session.expires <= time.monotonic() or session.closed.is_set():
        raise HTTPException(410, 'Сессия браузера завершена. Откройте сервис заново.')
    return session

async def discard(key, session, reason='browser_session_ended'):
    if _sessions.get(key) is session: _sessions.pop(key, None)
    await session.close(reason)

def expire_without_control(key, session):
    async def expire():
        await asyncio.sleep(max(0, RECOVERY_SECONDS - (time.monotonic() - session.last_phone)))
        if session.control is None: await discard(key, session)
    if session.idle_task: session.idle_task.cancel()
    session.idle_task = asyncio.create_task(expire())

def status(session):
    remaining = max(0, int((RECOVERY_SECONDS - (time.monotonic() - session.last_reply)) * 1000))
    return {'type': 'browser_status', 'gateway_available': session.gateway_available,
            'retry_millis': remaining, 'retry_seconds': (remaining + 999) // 1000}

@router.post('/api/service-browser/{node_id}/{service}/open')
async def open_browser(node_id: str, service: str, request: Request, payload: dict | None = Body(default=None)):
    device = mobile(request)
    if payload is None or payload.get('protocol') != 2:
        raise HTTPException(409, 'Обновите Mobile до актуальной сборки 2.0.0 для открытия сервисов')
    if payload.keys() - {'protocol'}:
        raise HTTPException(400, 'Адрес сервиса выбирает панель; произвольное назначение не поддерживается')
    from core.storage import find_server
    node = await asyncio.to_thread(find_server, node_id)
    if not node: raise HTTPException(404, 'Узел не найден')
    for key, value in list(_sessions.items()):
        if value.expires <= time.monotonic(): await discard(key, value)
    if len(_sessions) >= 64 or sum(s.device_id == device for s in _sessions.values()) >= 4:
        raise HTTPException(429, 'Закройте предыдущие окна сервисов')
    try: target = await resolve(node, service)
    except ValueError as exc: raise HTTPException(400, str(exc)) from None
    key = secrets.token_urlsafe(32)
    session = BrowserSession(device, node_id, identity(node), target, time.monotonic() + 3600)
    _sessions[key] = session
    expire_without_control(key, session)
    return {'session_id': key, 'origin': target.origin, 'entry_path': target.path, 'protocol': 2,
            'socket_path': '/api/service-browser/' + key + '/stream',
            'control_path': '/api/service-browser/' + key + '/control', 'recovery_seconds': RECOVERY_SECONDS}

@router.delete('/api/service-browser/{session_id}')
async def close_browser(session_id: str, request: Request):
    session = session_for(session_id, mobile(request))
    await discard(session_id, session)
    return {'ok': True}

async def probe(session):
    connection = None
    try:
        connection = ServiceConnection(session.target, await session.ssh())
        await connection.open()
        host = urlsplit(session.target.origin).netloc
        connection.writer.write(f'HEAD {session.target.path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n'.encode())
        await connection.writer.drain()
        line = await asyncio.wait_for(connection.reader.readline(), 5)
        if not line.startswith(b'HTTP/'): raise ValueError('Нет ответа веб-интерфейса')
        session.reply()
    except asyncio.CancelledError: raise
    except Exception:
        session.gateway_available = False
        await session.release_ssh()
    finally:
        if connection:
            with suppress(Exception): await asyncio.wait_for(connection.close(), 3)

@router.websocket('/api/service-browser/{session_id}/control')
async def browser_control(websocket: WebSocket, session_id: str):
    session = None
    jobs = []
    intentional = False
    try:
        session = session_for(session_id, mobile(websocket))
        if session.control is not None: raise HTTPException(409, 'Окно сервиса уже подключено')
        if time.monotonic() - session.last_phone >= RECOVERY_SECONDS:
            await discard(session_id, session); raise HTTPException(410, 'Время восстановления соединения истекло')
        session.control = websocket
        session.last_phone = time.monotonic()
        if session.idle_task: session.idle_task.cancel(); session.idle_task = None
        await websocket.accept()
        async def receive():
            nonlocal intentional
            while True:
                message = await asyncio.wait_for(websocket.receive(), 20)
                if message['type'] == 'websocket.disconnect':
                    intentional = message.get('code') == 1000
                    return
                text = message.get('text')
                if not isinstance(text, str) or len(text) > 1024: intentional = True; return
                try: value = json.loads(text)
                except (ValueError, RecursionError): intentional = True; return
                if value == {'type': 'browser_close'}: intentional = True; return
                if value != {'type': 'browser_ping'}: intentional = True; return
                session.last_phone = time.monotonic()
                await websocket.send_json(status(session))
        async def watch_authority():
            from core.storage import find_server
            while not session.closed.is_set():
                node = await asyncio.to_thread(find_server, session.node_id)
                if not node or identity(node) != session.node_identity or session.expires <= time.monotonic():
                    await discard(session_id, session); return
                if node.get('node_type') == 'openwrt':
                    from core.openwrt.feature import require_enabled
                    try: require_enabled()
                    except Exception:
                        await discard(session_id, session); return
                await asyncio.sleep(2)
        async def watch_deadline():
            while not session.closed.is_set():
                remaining = RECOVERY_SECONDS - (time.monotonic() - session.last_reply)
                if remaining <= 0:
                    await discard(session_id, session, 'gateway_unavailable_60'); return
                await asyncio.sleep(remaining)
        async def watch_gateway():
            while not session.closed.is_set():
                await probe(session)
                await websocket.send_json(status(session))
                await asyncio.sleep(PROBE_SECONDS)
        jobs = [asyncio.create_task(fn()) for fn in (receive, watch_authority, watch_deadline, watch_gateway)]
        done, _ = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
        for job in done: await job
    except asyncio.CancelledError: raise
    except Exception: pass
    finally:
        for job in jobs: job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        if session and session.control is websocket:
            session.control = None
            session.gateway_available = False
            access = websocket.scope.get('state', {}).get('mobile_access')
            revoked = access is not None and not await asyncio.to_thread(access.device_exists, session.device_id)
            if intentional or revoked: await discard(session_id, session)
            elif not session.closed.is_set(): expire_without_control(session_id, session)
        with suppress(Exception): await websocket.close()

@router.websocket('/api/service-browser/{session_id}/stream')
async def browser_stream(websocket: WebSocket, session_id: str):
    global _streams
    session = connection = None
    jobs = []
    acquired = False
    handler = asyncio.current_task()
    try:
        session = session_for(session_id, mobile(websocket))
        if session.control is None: raise HTTPException(410, 'Контрольный канал окна не подключён')
        from core.storage import find_server
        node = await asyncio.to_thread(find_server, session.node_id)
        if not node or identity(node) != session.node_identity:
            await discard(session_id, session); raise HTTPException(410, 'Доступ к шлюзу изменён')
        if _streams >= 48 or session.streams >= 12: raise HTTPException(429, 'Слишком много подключений к сервису')
        _streams += 1; session.streams += 1; acquired = True
        session.handlers.add(handler)
        await websocket.accept()
        connection = ServiceConnection(session.target, await session.ssh())
        session.connections.add(connection)
        await connection.open()
        if session.closed.is_set(): return
        guard = ServiceRequestGuard(session.target)
        async def from_phone():
            while True:
                message = await asyncio.wait_for(websocket.receive(), 300)
                if message['type'] == 'websocket.disconnect': return
                data = message.get('bytes')
                if data is None or len(data) > 65536:
                    await websocket.close(4400, 'Неверный пакет браузера'); return
                accepted = guard.feed(data)
                if accepted:
                    connection.writer.write(accepted)
                    await connection.writer.drain()
        async def to_phone():
            while data := await asyncio.wait_for(connection.reader.read(32768), 300):
                guard.response(data)
                session.reply()
                await websocket.send_bytes(data)
        jobs = [asyncio.create_task(fn()) for fn in (from_phone, to_phone, session.closed.wait)]
        done, _ = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
        for job in done: await job
    except asyncio.CancelledError: raise
    except ValueError:
        with suppress(Exception): await websocket.close(4400, 'service_destination_rejected')
    except Exception:
        with suppress(Exception): await websocket.close(4411, 'gateway_temporarily_unavailable')
    finally:
        for job in jobs: job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        if connection:
            with suppress(Exception): await connection.close()
        if acquired:
            _streams -= 1; session.streams -= 1
            session.handlers.discard(handler); session.connections.discard(connection)
        with suppress(Exception): await websocket.close()
