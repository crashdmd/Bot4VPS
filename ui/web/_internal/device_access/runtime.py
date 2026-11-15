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


def listener_running(listener):
    task = getattr(listener, "task", None)
    return bool(listener is not None and (task is None or not task.done())
                and not getattr(getattr(listener, "server", None), "should_exit", False))


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
        from .connection_change import stage_firewall, staged_firewall_pending
        _set_listener(app, None)
        candidate = None
        try:
            if await asyncio.to_thread(staged_firewall_pending):
                await stage_firewall(None)
            cfg = dict(web.get("mobile_api") or {})
            if not cfg.get("enabled"):
                from .access import MobileAccess
                if await asyncio.to_thread(MobileAccess().devices):
                    from core.config import patch_web_config
                    cfg["enabled"] = True
                    await asyncio.to_thread(patch_web_config, {"mobile_api": cfg})
            if not cfg.get("enabled"):
                await _firewall(app, None)
                return
            candidate = await start_api_listener(app, {**web, "mobile_api": cfg})
            await _firewall(app, cfg.get("port", 8444))
            _set_listener(app, candidate)
        except Exception as exc:
            errors = []
            if candidate:
                try:
                    await candidate.stop()
                except Exception as cleanup:
                    errors.append(str(cleanup))
            try:
                await _firewall(app, None)
            except Exception as cleanup:
                errors.append(str(cleanup))
            app.state.mobile_api_error = str(exc) + ("; очистка: " + "; ".join(errors) if errors else "")
            raise


async def stop_mobile_api(app):
    from .connection_change import cancel_for_shutdown, stage_firewall
    await cancel_for_shutdown(app)
    async with _lock(app):
        listener = getattr(app.state, "mobile_api_listener", None)
        _set_listener(app, None)
        try:
            if listener:
                await listener.stop()
        finally:
            await stage_firewall(None)
            await _firewall(app, None)


async def _apply_mobile_settings(app, cfg):
    from core.config import get_web_config, patch_web_config

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

    # A changed public address can renew the certificate. Restart even
    # on the same port so the listener loads its new TLS context.
    same_socket = listener_running(old) and all(old.config.get(k, d) == cfg[k] for k, d in (("host", "0.0.0.0"), ("port", 8444), ("public_url", "")))
    # Replacing a listener on the same port requires stopping its old bind.
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


async def apply_mobile_settings(app, cfg, *, access=None):
    from fastapi import HTTPException
    from core.config import get_web_config
    from .access import MobileAccess
    async with _lock(app):
        pending = getattr(app.state, "mobile_connection_change", None)
        if pending and pending.state == "pending":
            raise HTTPException(409, "Завершите или отмените подтверждение смены подключения")
        access = access or MobileAccess()
        try:
            devices = await asyncio.to_thread(access.devices)
        except OSError as error:
            raise RuntimeError("Не удалось проверить доступ телефонов. Прежнее подключение сохранено") from error
        if devices:
            if not cfg["enabled"]:
                raise HTTPException(409, "Нельзя выключить API, пока есть привязанный телефон")
            previous = (await asyncio.to_thread(get_web_config)).get("mobile_api") or {}
            defaults = {"host": "0.0.0.0", "port": 8444, "public_url": "",
                        "public_address": previous.get("public_url", "")}
            if any(previous.get(key, defaults.get(key)) != value for key, value in cfg.items() if key != "enabled"):
                raise HTTPException(409, "Изменение подключения требует подтверждения привязанным телефоном")
        return await _apply_mobile_settings(app, cfg)


async def recover_mobile_api(app):
    """Restore the saved enabled API after an unexpected listener shutdown."""
    from core.config import get_web_config
    async with _lock(app):
        change = getattr(app.state, "mobile_connection_change", None)
        if change and change.state == "pending":
            return False
        old = getattr(app.state, "mobile_api_listener", None)
        if listener_running(old):
            return False
        saved = (await asyncio.to_thread(get_web_config)).get("mobile_api") or {}
        if saved.get("enabled") is not True:
            return False
        cfg = {"enabled": True, "host": "0.0.0.0", "port": 8444, "public_url": "", **saved}
        await _apply_mobile_settings(app, cfg)
        return True


async def mobile_api_watchdog(app):
    delay = 5
    while True:
        await asyncio.sleep(delay)
        try:
            await recover_mobile_api(app)
            delay = 5
        except asyncio.CancelledError:
            raise
        except Exception as error:
            app.state.mobile_api_error = str(error)
            delay = min(delay * 2, 60)
