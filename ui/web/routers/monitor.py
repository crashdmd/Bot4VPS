
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
        from core.config import get_monitor_config
        return get_monitor_config()
    except Exception as e:
        return err(e)


@router.post("/api/monitor/config")
async def api_monitor_set(body: MonitorPatch):
    try:
        from core.config import (
            set_monitor_enabled,
            set_monitor_interval,
            get_monitor_config,
        )
        if body.name not in ("online", "ssl"):
            raise HTTPException(400, "name: online|ssl")
        if body.enabled is not None:
            set_monitor_enabled(body.name, bool(body.enabled))
        if body.interval is not None:
            if body.interval < 1:
                raise HTTPException(400, "interval >= 1")
            set_monitor_interval(body.name, int(body.interval))
        # В unified-процессе пересоздаём jobs сразу (раньше только TG умел)
        try:
            from bot import get_application
            from core.monitor import schedule_monitor_jobs
            tg = get_application()
            if tg is not None and tg.job_queue is not None:
                schedule_monitor_jobs(tg.job_queue)
        except Exception as e:
            print(f"[WEB] monitor reschedule: {e}", flush=True)
        return {"ok": True, "monitor": get_monitor_config()}
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


def _snapshot_online():
    from core.storage import load_servers
    from core.monitor import get_server_monitor
    rows = []
    online_n = offline_n = unk = 0
    for s in load_servers():
        mon = get_server_monitor(s["id"]) or {}
        avail = mon.get("availability") or {}
        on = avail.get("online")
        if on is True:
            online_n += 1
            st = "online"
        elif on is False:
            offline_n += 1
            st = "offline"
        else:
            unk += 1
            st = "unknown"
        host = s.get("host") or ""
        ms, method = None, "—"
        try:
            from core.servers import _probe_network
            latency, net = _probe_network(host)
            if latency is not None:
                ms = latency
            method = "Ping" if net == "ping" else ("HTTP" if net == "http" else "—")
        except Exception:
            port = int(s.get("port") or 22)
            ok_ping, ms2 = _tcp_ping_ms(host, port)
            if ok_ping:
                ms = ms2
                method = "Ping"
        rows.append({
            "id": s["id"],
            "name": s.get("name"),
            "status": st,
            "online": on,
            "ms": ms if st == "online" else (ms if ms is not None else None),
            "method": method if st == "online" else method,
            "error": avail.get("last_error") or "",
        })
    return {
        "rows": rows,
        "online": online_n,
        "offline": offline_n,
        "unknown": unk,
        "total": len(rows),
    }


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
            from core.monitor import check_server_availability

            for server in load_servers():
                try:
                    _info, event = await asyncio.to_thread(
                        check_server_availability, server
                    )
                    if event:
                        changed.append(event)
                        try:
                            await _notify_online_event(event)
                        except Exception as ne:
                            print(f"[WEB] notify online: {ne}", flush=True)
                except Exception as e:
                    print(f"[WEB] online check {server.get('name')}: {e}", flush=True)

            snap = _snapshot_online()
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
