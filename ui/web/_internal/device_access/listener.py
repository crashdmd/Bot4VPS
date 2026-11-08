"""Optional HTTPS socket exposing the existing API only to paired phones."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager, suppress
import ipaddress
import inspect
import json
import socket
import ssl

import uvicorn

from .access import ACCESS_HEADER, AccessDenied, MobileAccess
from .preview import MANAGEMENT_PREFIX, preview_enabled

_PROTOCOL = {"/api/mobile/pair", "/api/mobile/challenge", "/api/mobile/handshake"}


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
        if not path.startswith("/api/") or path == MANAGEMENT_PREFIX or path.startswith(MANAGEMENT_PREFIX + "/"):
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
        device_id = await asyncio.to_thread(self.access.authorize, token)
        if device_id is None:
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 4401})
            else:
                await _json(send, 401 if token else 428,
                    {"detail": "Привяжите телефон с помощью одноразового кода на LXC", "mobile_pairing_required": True},
                    "session" if token else "pairing")
            return
        scope.setdefault("state", {})["mobile_device_id"] = device_id
        started = finished = False
        async def forward(message):
            nonlocal started, finished
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
            if message["type"] == "http.response.body" and not message.get("more_body") or message["type"] == "websocket.close":
                finished = True
            await send(message)
        async def watch_revocation():
            while await asyncio.to_thread(self.access.device_exists, device_id):
                await asyncio.sleep(2)
        request = asyncio.create_task(self.app(scope, receive, forward))
        watcher = asyncio.create_task(watch_revocation())
        try:
            done, _ = await asyncio.wait((request, watcher), return_when=asyncio.FIRST_COMPLETED)
            if request in done:
                await request
            else:
                request.cancel()
                with suppress(asyncio.CancelledError):
                    await request
                if not finished:
                    if kind == "websocket":
                        await send({"type": "websocket.close", "code": 4401})
                    elif started:
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
                result = await asyncio.to_thread(self.access.pair, body.get("code"), body.get("public_key"))
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
    if not preview_enabled():
        return None
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
