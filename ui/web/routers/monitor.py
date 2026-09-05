
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..deps import err

router = APIRouter(tags=["monitor"])


class MonitorPatch(BaseModel):
    name: str
    enabled: Optional[bool] = None
    interval: Optional[int] = None


@router.get("/api/monitor/config")
async def api_monitor_get():
    try:
        from core.config import get_monitor_config, get_update_check_config
        cfg = get_monitor_config()
        cfg["update"] = get_update_check_config()
        return cfg
    except Exception as e:
        return err(e)


@router.post("/api/monitor/config")
async def api_monitor_set(body: MonitorPatch):
    try:
        from core.config import (
            set_monitor_enabled,
            set_monitor_interval,
            get_monitor_config,
            get_update_check_config,
        )
        if body.name == "update":
            # Чекбокс «Проверять обновления»: только enabled, без interval
            if body.enabled is None:
                raise HTTPException(400, "enabled обязателен")
            from core.config import set_update_check_enabled
            set_update_check_enabled(bool(body.enabled))
        elif body.name in ("online", "ssl"):
            if body.enabled is not None:
                set_monitor_enabled(body.name, bool(body.enabled))
            if body.interval is not None:
                if body.interval < 1:
                    raise HTTPException(400, "interval >= 1")
                set_monitor_interval(body.name, int(body.interval))
        else:
            raise HTTPException(400, "name: online|ssl|update")
        # Jobs мониторинга — собственность ядра: пересоздаём в ядерной
        # очереди (раньше дёргали JobQueue PTB-приложения, что ломало
        # мониторинг при выключенном Telegram).
        try:
            from core.jobs_runtime import reschedule_core_jobs
            reschedule_core_jobs()
        except Exception as e:
            print(f"[WEB] monitor reschedule: {e}", flush=True)
        cfg = get_monitor_config()
        cfg["update"] = get_update_check_config()
        return {"ok": True, "monitor": cfg}
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


async def _notify_online_event(event: dict):
    from core.event_service import notify_event
    from core.event_types import EventType, EventLevel, EventReason
    if event["event"] == "offline":
        details = {**event, "reason": EventReason.SERVER_OFFLINE.value}
        message = (
            f"Сервер «{event['server_name']}» стал недоступен."
            + (f"\nОшибка: {event.get('error')}" if event.get("error") else "")
        )
        await notify_event(
            EventType.SERVER, EventLevel.CRITICAL,
            "Сервер недоступен", message, details,
        )
    elif event["event"] == "online":
        details = {**event, "reason": EventReason.SERVER_ONLINE.value}
        message = f"Сервер «{event['server_name']}» снова в сети."
        await notify_event(
            EventType.SERVER, EventLevel.INFO,
            "Сервер снова доступен", message, details,
        )


async def _notify_ssl_event(event: dict):
    from core.event_service import notify_event
    from core.event_types import EventType, EventLevel, EventReason
    if event["event"] == "renewed":
        details = {**event, "reason": EventReason.SSL_RENEWED.value}
        await notify_event(
            EventType.SSL, EventLevel.INFO,
            "SSL сертификат обновлён",
            f"Сертификат сервера «{event['server_name']}» успешно обновлён.",
            details,
        )
    elif event["event"] == "expired":
        details = {**event, "reason": EventReason.SSL_EXPIRED.value}
        await notify_event(
            EventType.SSL, EventLevel.CRITICAL,
            "SSL сертификат истёк",
            f"Сертификат сервера «{event['server_name']}» истёк.",
            details,
        )


def _tcp_ping_ms(host: str, port: int, timeout: float = 2.0):
    import socket
    import time
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True, round((time.perf_counter() - t0) * 1000, 1)
    except Exception:
        return False, round((time.perf_counter() - t0) * 1000, 1)


def _snapshot_online(probe_results: dict[str, dict] | None = None):
    """Снимок статусов для модалки «Проверить».

    probe_results — {server_id: {online, ms, method}} из лёгкого чека:
    если переданы, сеть второй раз не трогаем, ping-мс берём из пробы.
    """
    from core.storage import load_servers
    from core.monitor import get_server_monitor
    rows = []
    online_n = offline_n = unk = 0
    for s in load_servers():
        mon = get_server_monitor(s["id"]) or {}
        avail = mon.get("availability") or {}
        probe = (probe_results or {}).get(s["id"]) or {}
        on = probe.get("online", avail.get("online"))
        if on is True:
            online_n += 1
            st = "online"
        elif on is False:
            offline_n += 1
            st = "offline"
        else:
            unk += 1
            st = "unknown"
        ms = probe.get("ms")
        method = probe.get("method") or "—"
        rows.append({
            "id": s["id"],
            "name": s.get("name"),
            "status": st,
            "online": on,
            "ms": ms,
            "method": method,
            "error": avail.get("last_error") or "",
            "ssh_error": avail.get("ssh_error") or "",
        })
    return {
        "rows": rows,
        "online": online_n,
        "offline": offline_n,
        "unknown": unk,
        "total": len(rows),
    }


def _light_online_check(servers: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    """Параллельная лёгкая проба всех серверов (новый критерий: ICMP →
    TCP port → 80 → 443). Возвращает ({server_id: {online, ms, method}},
    [events]).

    Статус и событие смены пишутся/создаются здесь один раз;
    network-зонд один — snapshot сеть второй раз не трогает.
    """
    from concurrent.futures import ThreadPoolExecutor

    from core.monitor import update_server_availability
    from core.servers import _probe_network

    def _one(server: dict) -> tuple[dict, dict | None]:
        host = server.get("host") or ""
        port = server.get("port") or 22
        try:
            ms, network = _probe_network(host, port)
        except Exception:
            ms, network = None, "none"
        online = network != "none"
        method = "Ping" if network == "ping" else ("TCP" if network == "tcp" else ("HTTP" if network == "http" else "—"))
        result = {"online": online, "ms": ms, "method": method}
        event = None
        try:
            event = update_server_availability(server, online=online, error="")
        except Exception as e:
            print(f"[MONITOR CHECK] {server.get('name', '?')}: {e}", flush=True)
        return result, event

    results: dict[str, dict] = {}
    events: list[dict] = []
    if not servers:
        return results, events
    with ThreadPoolExecutor(max_workers=min(16, len(servers))) as ex:
        futures = {ex.submit(_one, s): s for s in servers}
        for future, server in futures.items():
            try:
                result, event = future.result()
                results[server["id"]] = result
                if event:
                    events.append(event)
            except Exception as e:
                print(f"[MONITOR CHECK] {server.get('name', '?')}: {e}", flush=True)
                results[server["id"]] = {"online": None, "ms": None, "method": "—"}
    return results, events


def _snapshot_ssl():
    from core.storage import load_servers
    from core.monitor import get_server_monitor
    rows = []
    counts = {"valid": 0, "warning": 0, "expired": 0, "error": 0, "skip": 0}
    for s in load_servers():
        if not s.get("certificate_check"):
            counts["skip"] += 1
            rows.append({
                "id": s["id"], "name": s.get("name"),
                "status": "skip", "days_left": None, "expires": "", "checked": "",
            })
            continue
        mon = get_server_monitor(s["id"]) or {}
        cert = mon.get("certificate") or {}
        st = cert.get("status") or "error"
        counts[st] = counts.get(st, 0) + 1
        rows.append({
            "id": s["id"],
            "name": s.get("name"),
            "status": st,
            "days_left": cert.get("days_left"),
            "expires": cert.get("expires") or "",
            "checked": cert.get("checked") or "",
            "error": cert.get("error") or "",
        })
    return {"rows": rows, "counts": counts, "total": len(rows)}


@router.post("/api/monitor/check/{kind}")
async def api_monitor_check(kind: str):
    try:
        if kind not in ("online", "ssl"):
            raise HTTPException(400, "kind: online|ssl")

        changed = []

        if kind == "online":
            from core.storage import load_servers

            # Лёгкий параллельный чек: новый критерий доступности
            # (ICMP → TCP port → 80 → 443), без SSH. События о смене
            # статуса собираются в самой пробе (один network-зонд).
            servers = load_servers()
            probe_results, events = await asyncio.to_thread(
                _light_online_check, servers
            )
            for event in events:
                changed.append(event)
                try:
                    await _notify_online_event(event)
                except Exception as ne:
                    print(f"[WEB] notify online: {ne}", flush=True)

            snap = _snapshot_online(probe_results)
            return {
                "ok": True,
                "kind": "online",
                "changes": len(changed),
                "events": changed,
                "summary": {
                    "total": snap["total"],
                    "online": snap["online"],
                    "offline": snap["offline"],
                    "unknown": snap["unknown"],
                },
                "servers": snap["rows"],
            }

        # ssl
        from core.monitor import run_daily_monitor
        events = await asyncio.to_thread(run_daily_monitor)
        for event in events or []:
            changed.append(event)
            try:
                await _notify_ssl_event(event)
            except Exception as ne:
                print(f"[WEB] notify ssl: {ne}", flush=True)

        snap = _snapshot_ssl()
        return {
            "ok": True,
            "kind": "ssl",
            "changes": len(changed),
            "events": changed,
            "summary": snap["counts"],
            "servers": snap["rows"],
        }
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.get("/api/events")
async def api_events(limit: int = 25):
    try:
        from core.events import get_events
        return {"events": get_events(limit=limit)}
    except Exception as e:
        return err(e)


class MarkReadBody(BaseModel):
    event_id: str


@router.post("/api/events/mark-read")
async def api_events_mark_read(body: MarkReadBody):
    try:
        from core.events import mark_as_read
        mark_as_read(body.event_id)
        return {"ok": True, "event_id": body.event_id}
    except Exception as e:
        return err(e)


@router.delete("/api/events")
async def api_events_clear():
    try:
        import core.events as ev
        if hasattr(ev, "clear_events") and callable(ev.clear_events):
            ev.clear_events()
            return {"ok": True}
        for name in ("save_events", "write_events", "set_events"):
            if hasattr(ev, name):
                getattr(ev, name)([])
                return {"ok": True}
        from pathlib import Path
        for candidate in (Path("data/events.json"), Path("events.json"), Path("storage/events.json")):
            if candidate.exists():
                candidate.write_text("[]", encoding="utf-8")
                return {"ok": True, "path": str(candidate)}
        raise HTTPException(501, "Не найден clear_events() / events.json")
    except HTTPException:
        raise
    except Exception as e:
        return err(e)
