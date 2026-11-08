"""Apply the separate local API listener and firewall without restarting Web."""
from __future__ import annotations

import asyncio

from core._internal.device_access.firewall import LocalApiFirewall
from .listener import start_api_listener


def _lock(app):
    if not hasattr(app.state, "mobile_api_lock"):
        app.state.mobile_api_lock = asyncio.Lock()
    return app.state.mobile_api_lock


def _set_listener(app, listener):
    app.state.mobile_api_listener = listener
    app.state.mobile_api_enabled = listener is not None


async def _firewall(app, port):
    try:
        message = await asyncio.to_thread(LocalApiFirewall().sync, port)
        app.state.mobile_api_error = ""
        return message
    except Exception as exc:
        app.state.mobile_api_error = str(exc)
        raise


async def _audit_settings(previous, cfg, *, error=None):
    from core import audit
    defaults = {"enabled": False, "host": "0.0.0.0", "port": 8444, "public_url": ""}
    changes = {key: {"before": previous.get(key, default), "after": cfg[key]}
               for key, default in defaults.items() if previous.get(key, default) != cfg[key]}
    if changes or error:
        await asyncio.to_thread(audit.record, audit.AuditAction.MOBILE_API_SETTINGS,
                                result=audit.AuditResult.FAILED if error else audit.AuditResult.OK,
                                params={"changes": changes}, error=error)


async def boot_mobile_api(app, web):
    async with _lock(app):
        _set_listener(app, None)
        cfg = web.get("mobile_api") or {}
        if not cfg.get("enabled"):
            await _firewall(app, None)
            return
        candidate = None
        try:
            candidate = await start_api_listener(app, web)
            await _firewall(app, cfg.get("port", 8444))
            _set_listener(app, candidate)
        except Exception as exc:
            if candidate:
                await candidate.stop()
            try:
                await _firewall(app, None)
            except Exception as cleanup:
                app.state.mobile_api_error = f"{exc}; очистка: {cleanup}"
            else:
                app.state.mobile_api_error = str(exc)
            raise


async def stop_mobile_api(app):
    async with _lock(app):
        listener = getattr(app.state, "mobile_api_listener", None)
        _set_listener(app, None)
        try:
            if listener:
                await listener.stop()
        finally:
            await _firewall(app, None)


async def apply_mobile_settings(app, cfg):
    from core.config import get_web_config, patch_web_config

    async with _lock(app):
        previous = dict((await asyncio.to_thread(get_web_config)).get("mobile_api") or {})
        old = getattr(app.state, "mobile_api_listener", None)
        if not cfg["enabled"]:
            # Stop even when cleanup fails; don't leave the API serving requests.
            _set_listener(app, None)
            errors = []
            if old:
                try:
                    await old.stop()
                except Exception as exc:
                    errors.append(str(exc))
            try:
                message = await _firewall(app, None)
            except Exception as exc:
                errors.append(str(exc))
            try:
                await asyncio.to_thread(patch_web_config, {"mobile_api": cfg})
            except Exception as exc:
                errors.append(f"Не удалось сохранить настройки: {exc}")
            if errors:
                app.state.mobile_api_error = "; ".join(errors)
                await _audit_settings(previous, cfg, error=app.state.mobile_api_error)
                raise RuntimeError("API остановлен. " + app.state.mobile_api_error)
            await _audit_settings(previous, cfg)
            return {"ok": True, "running": False, "restart_required": False,
                    "message": "API выключен. " + message}

        same_socket = old is not None and all(old.config.get(k, d) == cfg[k] for k, d in (("host", "0.0.0.0"), ("port", 8444)))
        # Binding a different interface on the same port can overlap the old bind.
        old_stopped = False
        candidate = None
        try:
            if old and not same_socket and old.config.get("port", 8444) == cfg["port"]:
                await old.stop()
                old_stopped = True
                _set_listener(app, None)
            candidate = old if same_socket else await start_api_listener(app, {"mobile_api": cfg})
            if candidate is None:
                raise RuntimeError("Не удалось запустить мобильный API")
            message = await _firewall(app, cfg["port"])
            await asyncio.to_thread(patch_web_config, {"mobile_api": cfg})
        except Exception as exc:
            rollback_errors = []
            if candidate and candidate is not old:
                try:
                    await candidate.stop()
                except Exception as error:
                    rollback_errors.append(str(error))
            try:
                await _firewall(app, old.config.get("port", 8444) if old else None)
            except Exception as error:
                rollback_errors.append(str(error))
            if old_stopped:
                try:
                    old = await start_api_listener(app, {"mobile_api": old.config})
                except Exception as error:
                    old = None
                    rollback_errors.append(str(error))
            _set_listener(app, old)
            app.state.mobile_api_error = str(exc) + ("; восстановление: " + "; ".join(rollback_errors) if rollback_errors else "")
            await _audit_settings(previous, cfg, error=app.state.mobile_api_error)
            raise RuntimeError(app.state.mobile_api_error) from exc
        candidate.config = dict(cfg)
        _set_listener(app, candidate)
        if old and old is not candidate and not old_stopped:
            try:
                await old.stop()
            except Exception as exc:
                app.state.mobile_api_error = f"Не удалось остановить прежний API: {exc}"
                await _audit_settings(previous, cfg, error=app.state.mobile_api_error)
                raise RuntimeError(app.state.mobile_api_error) from exc
        await _audit_settings(previous, cfg)
        return {"ok": True, "running": True, "restart_required": False,
                "message": "Настройки применены. " + message}
