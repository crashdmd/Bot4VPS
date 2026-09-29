"""Server timeline: metric series plus one mark per logical audit operation."""
from __future__ import annotations

import time
from typing import Optional

from core import state_db
from core.actor import ActorType
from core.audit_operations import INCOMPLETE
from core.audit_query import MARKS_ROWS, window_operations

KIND_ACTION = "action"
KIND_SYSTEM = "system"
KINDS = (KIND_ACTION, KIND_SYSTEM)


def _mark(operation: dict) -> dict:
    started = int(operation["started_ts"])
    ended = operation.get("ended_ts")
    return {
        "audit_id": operation["anchor_id"],
        "ts": started,
        "ts_end": int(ended) if ended is not None else started,
        "ended_at": int(ended) if ended is not None else None,
        "kind": (
            KIND_SYSTEM
            if str(operation.get("actor_type") or "") == ActorType.SYSTEM.value
            else KIND_ACTION
        ),
        "action": operation["action"],
        "title": operation["title"],
        "result": INCOMPLETE if operation.get("status") == INCOMPLETE else operation["result"],
        "actor": {"type": operation.get("actor_type"), "id": operation.get("actor_id")},
        "task_id": operation.get("task_id"),
        "_operation_id": operation.get("operation_id"),
    }


def _availability_mark(transition: dict) -> dict:
    ts = int(transition["ts"])
    online = bool(transition.get("online"))
    return {
        "audit_id": str(transition["id"]),
        "ts": ts,
        "ts_end": ts,
        "kind": KIND_SYSTEM,
        "action": "server.availability",
        "title": "Сервер снова доступен" if online else "Сервер недоступен",
        "result": "ok" if online else "failed",
        "actor": {"type": ActorType.SYSTEM.value, "id": None},
        "task_id": None,
        "availability": {"online": online, "error": transition.get("error") or None},
    }


def _peak(record: dict) -> dict:
    return {
        "captured_at": int(record["captured_ts"]),
        "metrics": {
            "load1": record.get("load1"),
            "load5": record.get("load5"),
            "load15": record.get("load15"),
            "cpu_count": record.get("cpu_count"),
            "ram_used_kb": record.get("ram_used_kb"),
            "ram_total_kb": record.get("ram_total_kb"),
            "swap_used_kb": record.get("swap_used_kb"),
            "swap_total_kb": record.get("swap_total_kb"),
            "uptime_sec": record.get("uptime_sec"),
            "disks": record.get("disks") or [],
        },
    }


def _attach_peaks(marks_list: list[dict]) -> None:
    operation_ids = [mark.get("_operation_id") for mark in marks_list if mark.get("_operation_id")]
    peaks = state_db.operation_metric_peaks_for_audit_operations(operation_ids)
    for mark in marks_list:
        operation_id = mark.pop("_operation_id", None)
        if not operation_id:
            continue
        peak = peaks.get(str(operation_id))
        if peak is not None:
            mark["peak"] = _peak(peak)


def marks(server_id: str, since: int, until: int) -> tuple[list, bool]:
    operations = window_operations(server_id, since, until, limit=MARKS_ROWS)
    transitions = state_db.iter_availability_transitions(server_id, since=since, until=until)
    combined = [_mark(operation) for operation in operations]
    combined.extend(_availability_mark(transition) for transition in transitions)
    combined.sort(key=lambda mark: (int(mark["ts"]), 0 if mark["kind"] == KIND_SYSTEM else 1,
                                    str(mark["audit_id"])))
    truncated = len(combined) > MARKS_ROWS or len(operations) >= MARKS_ROWS
    if len(combined) > MARKS_ROWS:
        combined = combined[-MARKS_ROWS:]
    _attach_peaks(combined)
    return combined, truncated


def _legacy_marks(server_id: str, since: int, until: int) -> tuple[list, bool]:
    """Compatibility alias for callers that need the public marks contract."""
    return marks(server_id, since, until)


def timeline(
    server_id: str,
    *,
    since: Optional[int] = None,
    until: Optional[int] = None,
    step: str = "auto",
    now: Optional[int] = None,
    line_context: bool = False,
) -> dict:
    from core.metrics import series as metrics_series

    series = metrics_series(
        server_id,
        since=since,
        until=until,
        step=step,
        now=now,
        line_context=line_context,
    )
    window_from = int(series["from"])
    window_to = int(series["to"])
    interval_marks, truncated = marks(server_id, window_from, window_to)
    return {
        "server_id": server_id,
        "from": window_from,
        "to": window_to,
        "step": series["step"],
        "series": {
            "load1": series["series"]["load1"],
            "ram_pct": series["series"]["ram_pct"],
            "disk_max_pct": series["series"]["disk_max_pct"],
        },
        "available": series["available"],
        "labels": series["labels"],
        "raw_values": series.get("raw_values", {}),
        "raw_values_available": bool(series.get("raw_values_available")),
        "marks": interval_marks,
        "marks_truncated": truncated,
        "gaps": series["gaps"],
        "disk_gaps": series["disk_gaps"],
        "now": int(now if now is not None else time.time()),
    }


__all__ = ["KIND_ACTION", "KIND_SYSTEM", "KINDS", "marks", "timeline"]
