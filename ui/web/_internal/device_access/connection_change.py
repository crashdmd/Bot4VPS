"""Two-minute, device-signed migration with the old endpoint kept available."""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import io
import json
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

from .access import AccessDenied, _decode, _public_key
from . import runtime

TTL = 120
clock = time.monotonic
STAGING_LEDGER = Path("data/mobile-api-staging-firewall.json")
STAGING_INTENT = Path("data/mobile-api-staging-intent.json")


def staged_firewall_pending():
    return STAGING_LEDGER.exists() or STAGING_INTENT.exists()


async def stage_firewall(port):
    def sync():
        from core.local_privileges import separated, request
        if separated():
            from core.json_store import atomic_write_json
            if port is not None:
                # Persist intent before calling the helper: a lost reply may
                # still mean it opened the rule in its root-owned ledger.
                atomic_write_json(STAGING_INTENT, {"port": port})
            elif not STAGING_INTENT.exists():
                return ""
            result = request("firewall.stage", port=port)
            if port is None:
                STAGING_INTENT.unlink(missing_ok=True)
            return result
        from core._internal.device_access.firewall import LocalApiFirewall
        return LocalApiFirewall(STAGING_LEDGER).sync(port)
    return await asyncio.to_thread(sync)


def proof_message(change_id, nonce, device_id, url):
    return f"bot4vps-mobile-connection-v1\n{change_id}\n{nonce}\n{device_id}\n{url}".encode("ascii")


def authority(url):
    parsed = urlsplit(url)
    return parsed.hostname.lower().encode('idna').decode(), parsed.port or 443


@dataclass
class Change:
    id: str
    nonce: str
    owner: str
    version: str
    previous: dict
    proposed: dict
    access: object
    devices: set
    old: object
    deadline: float = 0
    expires: float = 0
    candidate: object = None
    state: str = "pending"
    message: str = "Ожидаем подключение телефона по новым данным"
    device_id: str | None = None
    qr: str = ""
    code: str = ""
    timer: object = None
    original_cert: bytes | None = None

    def status(self, *, include_qr=False):
        result = {"id": self.id, "state": self.state, "message": self.message,
                  "expires": self.expires, "remaining": max(0, self.deadline - clock()),
                  "old_url": self.previous.get("public_url", ""), "public_url": self.proposed["public_url"]}
        if include_qr and self.state == "pending":
            result.update(qr=self.qr, code=self.code)
        return result


def active(app):
    change = getattr(app.state, "mobile_connection_change", None)
    return change if change and change.state == "pending" else None


async def begin(app, cfg, owner, access):
    from core.config import get_web_config
    from ...security import auth_version
    async with runtime._lock(app):
        if active(app):
            raise HTTPException(409, "Смена подключения уже ожидает подтверждения телефона")
        previous = dict((await asyncio.to_thread(get_web_config)).get("mobile_api") or {})
        primary = await asyncio.to_thread(access.primary_device_id)
        devices = {primary} if primary else set()
        if not devices or not cfg["enabled"]:
            raise HTTPException(409, "Подтверждение доступно только при включённом API и привязанном телефоне")
        old = getattr(app.state, "mobile_api_listener", None)
        if old is None or getattr(getattr(old, "task", None), "done", lambda: False)():
            raise HTTPException(409, "Сначала восстановите работу текущего API")
        if cfg["host"] != previous.get("host", "0.0.0.0"):
            raise HTTPException(409, "Интерфейс API нельзя менять при привязанных телефонах; измените адрес или порт приложения")
        change = Change(secrets.token_urlsafe(24), secrets.token_urlsafe(32), owner,
                        auth_version(await asyncio.to_thread(get_web_config)), previous, dict(cfg), access, devices, old)
        app.state.mobile_connection_change = change
        try:
            identity_path = Path(old.identity["cert_path"])
            change.original_cert = await asyncio.to_thread(identity_path.read_bytes)
            same_bind = cfg["port"] == old.config.get("port", 8444)
            staging = {**cfg, "_additional_urls": [previous["public_url"]]}
            if same_bind:
                from .identity import configured_identity
                identity = await asyncio.to_thread(configured_identity, staging)
                ssl_context = old.server.config.ssl
                await asyncio.to_thread(ssl_context.load_cert_chain, identity["cert_path"], identity["key_path"])
                change.candidate = old
            else:
                change.candidate = await runtime.start_api_listener(app, {"mobile_api": staging})
                if change.candidate is None:
                    raise RuntimeError("Не удалось запустить проверку нового адреса")
                await stage_firewall(cfg["port"])
            payload = {"version": 1, "action": "connection_change", "url": cfg["public_url"],
                       "old_url": previous["public_url"], "id": change.id, "nonce": change.nonce,
                       "server_pin": change.candidate.identity["server_pin"]}
            if payload["server_pin"] != old.identity["server_pin"]:
                raise RuntimeError("Отпечаток панели изменился. Восстановите прежний ключ API")
            change.code = "b4vps:" + base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
            def qr():
                import qrcode
                output = io.BytesIO()
                qrcode.make(change.code).save(output, format="PNG")
                return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()
            change.qr = await asyncio.to_thread(qr)
            change.deadline, change.expires = clock() + TTL, time.time() + TTL
            change.timer = asyncio.create_task(watch(app, change))
            return {"ok": False, "confirmation_required": True, "change": change.status(include_qr=True)}
        except BaseException:
            await rollback(app, change, "failed", "Новые данные недоступны. Прежние настройки сохранены")
            raise


async def rollback(app, change, state, message):
    # Called under the runtime lock. Config has not been changed during staging.
    errors = []
    if change.candidate and change.candidate is not change.old:
        try:
            await change.candidate.stop()
        except Exception as error:
            errors.append(str(error))
    try:
        await stage_firewall(None)
    except Exception as error:
        errors.append(str(error))
    if change.original_cert is not None:
        try:
            from .identity import _write
            cert = Path(change.old.identity["cert_path"])
            await asyncio.to_thread(_write, cert, change.original_cert)
            ssl_context = getattr(getattr(getattr(change.old, "server", None), "config", None), "ssl", None)
            if ssl_context:
                await asyncio.to_thread(ssl_context.load_cert_chain, str(cert), change.old.identity["key_path"])
        except Exception as error:
            errors.append(str(error))
    change.state, change.message = state, message
    if errors:
        app.state.mobile_api_error = "Не удалось полностью убрать временное подключение: " + "; ".join(errors)
        change.message += ". " + app.state.mobile_api_error
    return change.status()


async def watch(app, change):
    from core.config import get_web_config
    from ...security import auth_version
    try:
        while change.state == "pending":
            await asyncio.sleep(min(1, max(.01, change.deadline - clock())))
            async with runtime._lock(app):
                if change.state != "pending":
                    return
                valid = change.version == auth_version(await asyncio.to_thread(get_web_config))
                if clock() >= change.deadline or not valid:
                    await rollback(app, change, "expired" if valid else "cancelled", "Подтверждение не получено. Прежние настройки сохранены")
    except asyncio.CancelledError:
        pass


async def status(app, change_id, owner):
    async with runtime._lock(app):
        change = getattr(app.state, "mobile_connection_change", None)
        if not change or change.id != change_id or change.owner != owner:
            raise HTTPException(404, "Подтверждение завершено или панель перезапущена. Несохранённые параметры не применены")
        if change.state == "pending" and clock() >= change.deadline:
            await rollback(app, change, "expired", "Время истекло. Прежние настройки сохранены")
        return change.status(include_qr=True)


async def cancel(app, change_id, owner):
    async with runtime._lock(app):
        change = getattr(app.state, "mobile_connection_change", None)
        if not change or change.id != change_id or change.owner != owner:
            raise HTTPException(404, "Запрос подтверждения не найден")
        if change.state == "pending":
            await rollback(app, change, "cancelled", "Изменение отменено. Прежние настройки сохранены")
        return change.status()


async def cancel_for_shutdown(app):
    async with runtime._lock(app):
        change = active(app)
        if change:
            await rollback(app, change, "cancelled", "Панель остановлена. Прежние настройки сохранены")
            if change.timer:
                change.timer.cancel()


def save_confirmed(change, device_id):
    from core import config
    from core.json_store import locked
    from ...security import auth_version
    # Same config -> device-store lock order as the account security flows.
    with locked(config.CONFIG_FILE.with_name(config.CONFIG_FILE.name + ".lock"), config._CONFIG_LOCK):
        with locked(change.access.store.lock_path, change.access.store._thread_lock):
            current = config.get_web_config()
            if (clock() >= change.deadline or auth_version(current) != change.version
                    or current.get("mobile_api", {}) != change.previous
                    or not change.access.device_exists(device_id)
                    or change.access.primary_device_id() != device_id):
                raise AccessDenied(409, "Подтверждение устарело. Прежние настройки сохранены")
            config.patch_web_config({"mobile_api": change.proposed})


async def confirm(app, access, endpoint, host, body):
    async with runtime._lock(app):
        change = getattr(app.state, "mobile_connection_change", None)
        if not change or body.get("id") != change.id:
            raise AccessDenied(404, "Запрос смены подключения не найден")
        if not endpoint or any(endpoint.get(key) != change.proposed[key] for key in ("host", "port")):
            raise AccessDenied(403, "Подключитесь к новому адресу API")
        try:
            if authority("https://" + host) != authority(change.proposed["public_url"]):
                raise ValueError()
        except (ValueError, AttributeError, UnicodeError):
            raise AccessDenied(403, "Подключитесь к новому адресу API")
        device_id = body.get("device_id")
        row = next((row for row in await asyncio.to_thread(change.access.store.read)
                    if row.get("kind") == "device" and row.get("id") == device_id and device_id in change.devices), None)
        if row is None:
            raise AccessDenied(403, "Подтвердить может только ранее привязанный телефон")
        if await asyncio.to_thread(access.primary_device_id) != device_id:
            raise AccessDenied(403, "Подтвердить смену API может только основной телефон")
        try:
            _public_key(row["public_key"]).verify(_decode(body.get("signature"), 256),
                proof_message(change.id, change.nonce, device_id, change.proposed["public_url"]), ec.ECDSA(hashes.SHA256()))
        except (InvalidSignature, ValueError, TypeError, KeyError):
            raise AccessDenied(403, "Телефон не подтвердил смену подключения")
        if change.state == "approved" and change.device_id == device_id:
            return {"ok": True, "state": "approved", "device_id": device_id, "public_url": change.proposed["public_url"]}
        if change.state != "pending" or clock() >= change.deadline:
            if change.state == "pending":
                await rollback(app, change, "expired", "Время истекло. Прежние настройки сохранены")
            raise AccessDenied(410, "Подтверждение истекло или отменено")
        try:
            await runtime._firewall(app, change.proposed["port"])
            await asyncio.to_thread(save_confirmed, change, device_id)
        except Exception:
            restore_error = None
            try:
                await runtime._firewall(app, change.previous["port"])
            except Exception as error:
                restore_error = error
            # A failed firewall restore must never skip closing the temporary
            # listener, removing its staging rule and restoring the certificate.
            await rollback(app, change, "failed", "Изменение не сохранено. Прежние настройки сохранены")
            if restore_error:
                message = "Не удалось восстановить прежнее правило firewall: " + str(restore_error)
                previous_error = getattr(app.state, "mobile_api_error", "")
                app.state.mobile_api_error = previous_error + "; " + message if previous_error else message
                change.message += ". " + message
            raise
        change.candidate.config.update(change.proposed)
        runtime._set_listener(app, change.candidate)
        change.state, change.device_id = "approved", device_id
        change.message = "Телефон подключился по новым данным. Настройки сохранены"
        try:
            await stage_firewall(None)
        except Exception as error:
            # The permanent new rule is already active. Keep confirmation usable
            # even if removing the temporary rule must be retried at shutdown.
            app.state.mobile_api_error = "Не удалось убрать временное правило API: " + str(error)
        # Let this HTTP response finish before shutting down another listener.
        if change.old is not change.candidate:
            asyncio.create_task(change.old.stop())
        await runtime._audit_settings(change.previous, change.proposed)
        return {"ok": True, "state": "approved", "device_id": device_id, "public_url": change.proposed["public_url"]}


async def preview(app, access, endpoint, host, body):
    """Discover a migration using the old device key and pinned new TLS endpoint.

    No session or browser cookie is sent to an unverified address. This proof
    is read-only; only confirm's nonce-bound primary proof can change settings.
    Also recovers a saved migration after its HTTP reply or app state was lost.
    """
    async with runtime._lock(app):
        from core.config import get_web_config
        proposed_url = body.get("url", "")
        change = getattr(app.state, "mobile_connection_change", None)
        # Terminal staging records are retained for Web status, but do not
        # describe the API that is actually committed and listening now.
        if change and change.state not in ("pending", "approved"):
            change = None
        cfg = change.proposed if change else (await asyncio.to_thread(get_web_config)).get("mobile_api", {})
        try:
            if (not endpoint or any(endpoint.get(key) != cfg.get(key) for key in ("host", "port"))
                    or authority(proposed_url) != authority(cfg["public_url"])
                    or authority("https://" + host) != authority(cfg["public_url"])):
                raise ValueError()
        except (ValueError, KeyError, AttributeError, UnicodeError):
            raise AccessDenied(403, "Подключитесь к новому адресу API")
        device_id = body.get("device_id")
        row = next((r for r in await asyncio.to_thread(access.store.read)
                    if r.get("kind") == "device" and r.get("id") == device_id), None)
        if not row:
            raise AccessDenied(403, "Телефон не привязан к этому сервису")
        try:
            _public_key(row["public_key"]).verify(_decode(body.get("signature"), 256),
                f"bot4vps-mobile-discover-v1\n{device_id}\n{proposed_url}".encode("ascii"), ec.ECDSA(hashes.SHA256()))
        except (InvalidSignature, ValueError, TypeError, KeyError):
            raise AccessDenied(403, "Телефон не подтвердил прежнюю связь")
        if change and change.state == "pending":
            if clock() >= change.deadline:
                await rollback(app, change, "expired", "Время истекло. Прежние настройки сохранены")
                raise AccessDenied(410, "Время подтверждения истекло")
            if await asyncio.to_thread(access.primary_device_id) != device_id or device_id not in change.devices:
                raise AccessDenied(403, "Смену API подтверждает основной телефон")
            payload = json.loads(base64.urlsafe_b64decode(change.code.removeprefix("b4vps:") + "=="))
            return {"ok": True, "state": "pending", "device_id": device_id, "payload": payload}
        if change and change.state != "approved":
            raise AccessDenied(410, "Изменение не подтверждено. Прежние настройки сохранены")
        return {"ok": True, "state": "approved", "device_id": device_id, "public_url": cfg["public_url"]}


async def confirm_on_endpoint(app, access, endpoint, scope, receive, send):
    from .listener import _json
    if scope.get("method") != "POST":
        await _json(send, 405, {"detail": "Требуется POST"})
        return
    try:
        await asyncio.to_thread(access.rate_limit, str((scope.get("client") or ("unknown",))[0]))
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
                    result = json.loads(raw)
                    if not isinstance(result, dict):
                        raise ValueError()
                    return result
        body = await asyncio.wait_for(read(), 5)
        host = next((value.decode("ascii") for key, value in scope.get("headers", []) if key.lower() == b"host"), "")
        operation = preview if scope.get("path", "").endswith("/preview") else confirm
        result = await operation(app, access, endpoint, host, body)
        await _json(send, 200, result)
    except (AccessDenied, HTTPException) as error:
        await _json(send, getattr(error, "status", getattr(error, "status_code", 403)), {"detail": str(error) if isinstance(error, AccessDenied) else error.detail})
    except (ValueError, TypeError, UnicodeError, asyncio.TimeoutError):
        await _json(send, 400, {"detail": "Неверное подтверждение смены подключения"})
    except Exception:
        await _json(send, 503, {"detail": "Не удалось применить подключение. Проверьте статус в панели"})
