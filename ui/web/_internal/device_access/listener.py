"""Optional HTTPS socket exposing the existing API only to paired phones."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager, suppress
import ipaddress
import inspect
import json
import math
import socket
import ssl
import time

import uvicorn

from .access import ACCESS_HEADER, AccessDenied, MobileAccess
from .preview import MANAGEMENT_PREFIX
from .principal import VerifiedMobileDevice

_PROTOCOL = {"/api/mobile/pair", "/api/mobile/challenge", "/api/mobile/handshake"}
_WEB_ONLY = (MANAGEMENT_PREFIX, "/api/mobile-app", "/api/auth", "/api/login", "/api/logout", "/api/setup")


class _SessionEnded(Exception):
    pass


async def _json(send, status: int, data: dict, error: str | None = None):
    headers = [(b"content-type", b"application/json"), (b"cache-control", b"no-store"),
               (b"x-bot4vps-mobile", b"required")]
    if error:
        headers.append((b"x-bot4vps-mobile-error", error.encode("ascii")))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": json.dumps(data, ensure_ascii=False).encode()})


class ApiOnlyApp:
    def __init__(self, app, access: MobileAccess):
        self.app, self.access = app, access

    async def __call__(self, scope, receive, send):
        kind, path = scope["type"], scope.get("path", "")
        if kind not in ("http", "websocket"):
            raise RuntimeError("Mobile API shares its parent's lifespan; run it with lifespan=off")
        if not path.startswith("/api/") or any(path == prefix or path.startswith(prefix + "/") for prefix in _WEB_ONLY):
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 4404})
            else:
                await _json(send, 404, {"detail": "Не найдено"})
            return
        if scope.get("scheme") not in ("https", "wss"):
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 4403})
            else:
                await _json(send, 400, {"detail": "Для мобильного API требуется HTTPS"})
            return
        if kind == "http" and path in _PROTOCOL:
            await self._protocol(scope, receive, send)
            return
        token = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k.lower() == ACCESS_HEADER), None)
        lease = await asyncio.to_thread(self.access.session_details, token)
        if lease is None:
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 4401})
            else:
                await _json(send, 401 if token else 428,
                    {"detail": "Привяжите телефон с помощью одноразового кода в Web-панели", "mobile_pairing_required": True},
                    "session" if token else "pairing")
            return
        device_id = lease.device_id
        # Capture the authenticated lifetime of this connection. An HTTP
        # handshake rotates the device's token, but may not silently prolong
        # an existing socket: it must present the new token on that socket.
        deadline = time.monotonic() + max(0, lease.expires - self.access.clock())
        scope.setdefault("state", {})["mobile_device_id"] = device_id
        scope["state"]["mobile_identity"] = VerifiedMobileDevice(device_id)
        scope["state"]["mobile_access"] = self.access
        started = finished = False

        def remaining():
            return min(lease.expires - self.access.clock(), deadline - time.monotonic())

        async def close_socket(reason):
            nonlocal finished
            if not finished:
                finished = True
                await send({"type": "websocket.close", "code": 4401, "reason": reason})

        async def forward(message):
            nonlocal started, finished
            if kind == "websocket":
                if finished:
                    return
                if remaining() <= 0:
                    await close_socket("mobile_session_expired")
                    raise _SessionEnded()
            if message["type"] == "http.response.start":
                started = True
                headers = list(message.get("headers", []))
                # The private Web socket may be HTTP. This public socket is
                # always TLS, so its session cookies must carry Secure.
                headers = [(k, v + b"; Secure" if k.lower() == b"set-cookie" and b"secure" not in {p.strip() for p in v.lower().split(b";")} else v)
                           for k, v in headers]
                message = {**message, "headers": headers}
            elif message["type"] == "websocket.accept":
                started = True
                message = {**message, "headers": list(message.get("headers", [])) + [
                    (b"x-bot4vps-mobile-session-renewal", b"1"),
                    (b"x-bot4vps-mobile-session-ttl", str(max(0, math.ceil(remaining()))).encode())]}
            if message["type"] == "http.response.body" and not message.get("more_body") or message["type"] == "websocket.close":
                finished = True
            await send(message)

        async def receive_verified():
            nonlocal lease, deadline
            while True:
                message = await receive()
                if kind != "websocket" or message["type"] != "websocket.receive":
                    return message
                if finished or remaining() <= 0:
                    await close_socket("mobile_session_expired")
                    raise _SessionEnded()
                text = message.get("text")
                try:
                    data = json.loads(text) if isinstance(text, str) and len(text) <= 8192 else None
                except (ValueError, RecursionError):
                    data = None
                if not isinstance(data, dict) or data.get("type") != "mobile_session":
                    return message
                renewed = await asyncio.to_thread(self.access.session_details, data.get("session"))
                if (remaining() <= 0 or renewed is None or renewed.device_id != device_id
                        or renewed.expires < lease.expires):
                    await close_socket("mobile_session_invalid")
                    raise _SessionEnded()
                if renewed.expires > lease.expires:
                    lease = renewed
                    deadline = time.monotonic() + max(0, lease.expires - self.access.clock())
                await forward({"type": "websocket.send", "text": json.dumps({
                    "type": "mobile_session", "status": "renewed", "expires_in": max(0, math.ceil(remaining()))})})

        async def watch_revocation():
            while True:
                if kind == "websocket" and remaining() <= 0:
                    return "mobile_session_expired"
                if not await asyncio.to_thread(self.access.device_exists, device_id):
                    return "mobile_device_revoked"
                await asyncio.sleep(min(2, max(.001, remaining())) if kind == "websocket" else 2)
        request = asyncio.create_task(self.app(scope, receive_verified, forward))
        watcher = asyncio.create_task(watch_revocation())
        try:
            done, _ = await asyncio.wait((request, watcher), return_when=asyncio.FIRST_COMPLETED)
            if request in done:
                with suppress(_SessionEnded):
                    await request
            else:
                reason = await watcher
                if kind == "websocket":
                    await close_socket(reason)
                request.cancel()
                with suppress(asyncio.CancelledError, _SessionEnded):
                    await request
                if not finished:
                    if started:
                        await send({"type": "http.response.body", "body": b"", "more_body": False})
                    else:
                        await _json(send, 403, {"detail": "Доступ телефона отозван"})
        finally:
            watcher.cancel()
            request.cancel()
            await asyncio.gather(watcher, request, return_exceptions=True)

    async def _protocol(self, scope, receive, send):
        if scope.get("method") != "POST":
            await _json(send, 405, {"detail": "Требуется POST"})
            return
        async def read():
            raw = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    raise AccessDenied(400, "Подключение прервано")
                raw.extend(message.get("body", b""))
                if len(raw) > 8192:
                    raise AccessDenied(413, "Слишком большой запрос")
                if not message.get("more_body"):
                    break
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise AccessDenied(400, "Неверный запрос привязки")
            return data
        try:
            await asyncio.to_thread(self.access.rate_limit, str((scope.get("client") or ("unknown",))[0]))
            body = await asyncio.wait_for(read(), timeout=5)
            path = scope["path"]
            if path.endswith("/pair"):
                result = await asyncio.to_thread(self.access.pair, body.get("code"), body.get("public_key"), body.get("masterkey_device_public_key"))
                from core import audit
                from core.actor import Actor
                await asyncio.to_thread(audit.record, audit.AuditAction.MOBILE_DEVICE_PAIR, result=audit.AuditResult.OK,
                    actor=Actor.phone(device_id=result["device_id"], ip=str((scope.get("client") or ("unknown",))[0])),
                    params={"device_id": result["device_id"], "name": result.get("name")})
            elif path.endswith("/challenge"):
                result = await asyncio.to_thread(self.access.challenge, body.get("device_id"))
            else:
                result = await asyncio.to_thread(self.access.handshake, body.get("device_id"), body.get("challenge_id"), body.get("signature"))
            await _json(send, 200, result)
        except AccessDenied as exc:
            await _json(send, exc.status, {"detail": str(exc)}, "pairing")
        except (ValueError, TypeError, asyncio.TimeoutError):
            await _json(send, 400, {"detail": "Неверный запрос привязки"})


class _ApiServer(uvicorn.Server):
    # The primary uvicorn instance alone owns process signals (old and new uvicorn).
    def install_signal_handlers(self):
        pass

    @contextmanager
    def capture_signals(self):
        yield


class ApiListener:
    def __init__(self, server, sock, task, config, identity):
        self.server, self.sock, self.task = server, sock, task
        self.config, self.identity = dict(config), dict(identity)

    async def stop(self):
        self.server.should_exit = True
        try:
            await asyncio.wait_for(asyncio.shield(self.task), 5)
        except asyncio.TimeoutError:
            self.server.force_exit = True
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        finally:
            self.sock.close()


async def start_api_listener(app, web: dict):
    config = web.get("mobile_api") or {}
    if not config.get("enabled"):
        return None
    host = str(config.get("host", "0.0.0.0"))
    address = ipaddress.ip_address(host)
    port = config.get("port", 8444)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Мобильный API: порт должен быть от 1 до 65535")
    from core.web_port import current_port_from_unit
    if port == current_port_from_unit():
        raise ValueError("Мобильный API: выберите порт, отличный от порта Web")
    from .identity import configured_identity
    identity = await asyncio.to_thread(configured_identity, config)
    cert, key = identity["cert_path"], identity["key_path"]
    api = ApiOnlyApp(app, MobileAccess())
    graceful = {"timeout_graceful_shutdown": 3} if "timeout_graceful_shutdown" in inspect.signature(uvicorn.Config).parameters else {}
    settings = uvicorn.Config(api, host=host, port=port, lifespan="off", proxy_headers=False,
        access_log=False, ssl_certfile=cert, ssl_keyfile=key, **graceful)
    await asyncio.to_thread(settings.load)
    settings.ssl.minimum_version = ssl.TLSVersion.TLSv1_2
    sock = socket.socket(socket.AF_INET6 if address.version == 6 else socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(2048)
        sock.setblocking(False)
        server = _ApiServer(settings)
        task = asyncio.create_task(server.serve(sockets=[sock]))
        listener = ApiListener(server, sock, task, config, identity)
        try:
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError("Мобильный API не запустился")
                await asyncio.sleep(.01)
            return listener
        except BaseException:
            await listener.stop()
            raise
    except BaseException:
        sock.close()
        raise
