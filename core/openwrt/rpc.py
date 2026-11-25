"""HTTPS ubus client with router-specific TLS trust and bounded sessions."""
from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import ssl
import time
from urllib.parse import urlsplit

import httpx


class RpcError(ValueError):
    def __init__(self, message: str, code: str = "rpc"):
        super().__init__(message)
        self.code = code


def endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Укажите HTTPS-адрес API без логина, пароля и параметров в URL")
    if parsed.path.rstrip("/") not in ("", "/ubus"):
        raise ValueError("API OpenWrt должен использовать путь /ubus")
    try:
        port = parsed.port or 443
    except ValueError:
        raise ValueError("Некорректный порт API") from None
    if not 1 <= port <= 65535:
        raise ValueError("Некорректный порт API")
    return value.rstrip("/") if parsed.path.rstrip("/") == "/ubus" else value.rstrip("/") + "/ubus"


def certificate_for_pin(url: str, expected: str) -> str:
    """Fetch public cert without credentials, verify pin before authentication."""
    parsed = urlsplit(endpoint(url))
    pin = expected.lower().replace(":", "")
    if len(pin) != 64 or any(c not in "0123456789abcdef" for c in pin):
        raise ValueError("Отпечаток TLS должен содержать 64 шестнадцатеричных символа SHA-256")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # Only public certificate discovery.
    with socket.create_connection((parsed.hostname, parsed.port or 443), timeout=8) as raw:
        with context.wrap_socket(raw, server_hostname=parsed.hostname) as tls:
            der = tls.getpeercert(binary_form=True)
    if hashlib.sha256(der).hexdigest() != pin:
        raise RpcError("Сертификат API не совпадает с указанным отпечатком", "tls")
    return ssl.DER_cert_to_PEM_cert(der)


class RpcClient:
    def __init__(self, config: dict):
        from core.openwrt.feature import require_enabled
        require_enabled()
        self.url = endpoint(config["url"])
        self.username = config["username"]
        self.password = config["password"]
        self.pin = config.get("tls_sha256")
        pem = config.get("tls_certificate")
        self.context = ssl.create_default_context(cadata=pem) if pem else ssl.create_default_context()
        if pem:
            der = ssl.PEM_cert_to_DER_cert(pem)
            if not self.pin or hashlib.sha256(der).hexdigest() != self.pin:
                raise RpcError("Некорректный сохранённый TLS-отпечаток", "tls")
            # The exact self-signed router certificate is the trust anchor.
            self.context.check_hostname = False
        self.http = httpx.AsyncClient(verify=self.context, trust_env=False, follow_redirects=False,
                                     timeout=httpx.Timeout(10, connect=5), limits=httpx.Limits(max_connections=4))
        self.sid = "0" * 32
        self.expires = 0.0
        self.login_lock = asyncio.Lock()
        self.sequence = 0
        from core.openwrt.feature import register_rpc
        register_rpc(self)

    async def close(self):
        await self.http.aclose()

    async def _request(self, object_name: str, method: str, arguments: dict, sid: str):
        from core.openwrt.feature import require_enabled
        require_enabled()
        self.sequence += 1
        try:
            async with self.http.stream('POST', self.url, headers={'Accept-Encoding':'identity'}, json={"jsonrpc": "2.0", "id": self.sequence,
                    "method": "call", "params": [sid, object_name, method, arguments]}) as response:
                response.raise_for_status()
                if self.pin:
                    stream = response.extensions.get("network_stream")
                    tls = stream.get_extra_info("ssl_object") if stream else None
                    if not tls or hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest() != self.pin:
                        raise RpcError("Сертификат API изменился", "tls")
                if response.headers.get('content-encoding', 'identity').lower() not in ('', 'identity'):
                    raise RpcError('API вернул неподдерживаемое сжатие ответа', 'response')
                content = bytearray()
                async for chunk in response.aiter_raw(chunk_size=65536):
                    if len(content) + len(chunk) > 2_000_000:
                        raise RpcError("Ответ API превышает допустимый размер", "response")
                    content.extend(chunk)
                data = json.loads(content)
        except RpcError:
            raise
        except httpx.HTTPStatusError as exc:
            raise RpcError(f"API ответил HTTP {exc.response.status_code}", "http") from None
        except httpx.TimeoutException:
            raise RpcError(f'Роутер не ответил вовремя на запрос {object_name}.{method}', 'connection') from None
        except (httpx.HTTPError, ssl.SSLError, OSError):
            raise RpcError("Не удалось соединиться с HTTPS API роутера", "connection") from None
        except (ValueError, TypeError):
            raise RpcError("API вернул некорректный JSON", "response") from None
        if not isinstance(data, dict):
            raise RpcError("Некорректный ответ API", "response")
        if data.get("error"):
            code = "permission" if (data["error"] if isinstance(data["error"], dict) else {}).get("code") == -32002 else "rpc"
            raise RpcError("API отказал в доступе" if code == "permission" else "Ошибка RPC роутера", code)
        result = data.get("result")
        if not isinstance(result, list) or not result:
            raise RpcError("Некорректный результат RPC", "response")
        if result[0] != 0:
            code = "permission" if result[0] == 6 else "unsupported" if result[0] in (3, 4) else "rpc"
            raise RpcError("Недостаточно прав API" if code == "permission" else "Метод API не найден" if code == "unsupported" else "Ошибка выполнения RPC (код " + str(result[0]) + ")", code)
        return result[1] if len(result) > 1 else {}

    async def login(self):
        async with self.login_lock:
            if self.expires > time.monotonic():
                return
            data = await self._request("session", "login", {"username": self.username,
                "password": self.password, "timeout": 300}, "0" * 32)
            sid = data.get("ubus_rpc_session")
            if not isinstance(sid, str) or len(sid) != 32:
                raise RpcError("Вход в API не подтверждён", "permission")
            self.sid = sid
            self.expires = time.monotonic() + max(1, min(int(data.get("timeout", 300)) - 20, 280))

    async def call(self, object_name: str, method: str, arguments: dict | None = None):
        await self.login()
        # No automatic repeat: mutating calls may have succeeded before a lost reply.
        try:
            return await self._request(object_name, method, arguments or {}, self.sid)
        except RpcError as exc:
            if exc.code == 'permission':
                self.expires = 0
            raise
