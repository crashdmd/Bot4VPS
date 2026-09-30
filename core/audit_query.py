"""Operation-level audit reads for the Web API and timeline, without SSH."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence

from core import state_db
from core.audit_actions import RESULT_TITLES, actor_label, codes_matching_title, title_of
from core.audit_operations import (
    COMPLETED,
    INCOMPLETE,
    WAITING_RULE_SELECTION,
    params_of,
)
from core.actor import ActorType

DEFAULT_LIMIT = 50
MAX_LIMIT = 500
MARKS_ROWS = 3000
TAIL_LIMIT = 200
MAX_QUERY = 200
HISTORY_INDEX_LIMIT = 500
EVENT_INDEX_LIMIT = 1000

ACTOR_TYPES: tuple[str, ...] = tuple(kind.value for kind in ActorType)
RESULTS: tuple[str, ...] = (
    "ok",
    "failed",
    "cancelled",
    "awaiting_rule_selection",
    INCOMPLETE,
)
LOG_IN_TASK = "in_task"
LOG_NONE = "none"
NO_SERVER_TITLE = "Не о сервере"
GROUP_BY: tuple[str, ...] = ("actor", "action", "server", "result", "day")

_RAW_COLUMNS = ", ".join(state_db.AUDIT_COLUMNS)
_OPERATION_COLUMNS = (
    "operation_id, started_ts, sort_id, anchor_id, final_id, ended_ts, action, title, "
    "result, status, error, actor_type, actor_id, actor_role, actor_ip, server_id, "
    "server_name, op_id, task_id, event_id"
)
_OPERATION_BASE = """
    SELECT {columns}
    FROM audit_operations o
    WHERE EXISTS (
        SELECT 1
        FROM audit_operation_members m
        JOIN audit_records r ON r.id = m.record_id
        WHERE m.operation_id = o.operation_id
    )
"""
_TAIL_SQL = """
    SELECT rowid AS rid, id, ts, action, result, actor_type, actor_id, server_id
    FROM audit_records
    WHERE rowid > ? OR ts > ?
    ORDER BY rowid
    LIMIT ?
"""
_TAIL_LAST_SQL = """
    SELECT rowid AS rid, id, ts, action, result, actor_type, actor_id, server_id
    FROM audit_records
    ORDER BY rowid DESC
    LIMIT ?
"""
_LAST_ROWID_SQL = "SELECT MAX(rowid) AS last, MAX(ts) AS last_ts FROM audit_records"


def _since_until(since: Optional[int], until: Optional[int]) -> None:
    if since is not None and until is not None and int(since) > int(until):
        raise ValueError("from: больше to")


def _like(text: str) -> str:
    escaped = str(text).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _like_prefix(text: str) -> str:
    escaped = str(text).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}%"


def _operation_window(since: Optional[int], until: Optional[int]) -> tuple[str, list[Any]]:
    sql, params = "", []
    if since is not None:
        sql += " AND COALESCE(o.ended_ts, o.started_ts) >= ?"
        params.append(int(since))
    if until is not None:
        sql += " AND o.started_ts <= ?"
        params.append(int(until))
    return sql, params


def _operation_result(row: dict) -> str:
    if row.get("status") == INCOMPLETE:
        return INCOMPLETE
    if row.get("status") == WAITING_RULE_SELECTION:
        return "awaiting_rule_selection"
    return str(row.get("result") or "")


def _actor(row: dict) -> dict:
    return {
        "type": row.get("actor_type"),
        "id": row.get("actor_id"),
        "role": row.get("actor_role"),
        "ip": row.get("actor_ip"),
    }


def _server(row: dict) -> Optional[dict]:
    if not row.get("server_id") and not row.get("server_name"):
        return None
    return {"id": row.get("server_id"), "name": row.get("server_name")}


def _references(operation: dict, members: Sequence[dict]) -> tuple[Optional[str], Optional[str]]:
    task_id = operation.get("task_id")
    event_id = operation.get("event_id")
    for row in members:
        task_id = task_id or row.get("task_id")
        event_id = event_id or row.get("event_id")
    return task_id, event_id


def _operation_record(operation: dict, members: Sequence[dict] = ()) -> dict:
    task_id, event_id = _references(operation, members)
    started = int(operation["started_ts"])
    ended = operation.get("ended_ts")
    ended = int(ended) if ended is not None else None
    return {
        # id remains a raw anchor id so saved deep links and chart marks remain valid.
        "id": operation["anchor_id"],
        "operation_id": operation["operation_id"],
        "ts": started,
        "started_at": started,
        "ended_at": ended,
        "duration_seconds": (ended - started) if ended is not None else None,
        "actor": _actor(operation),
        "server": _server(operation),
        "action": operation["action"],
        "title": operation["title"],
        "result": _operation_result(operation),
        "status": operation["status"],
        "error": operation.get("error"),
        "op_id": operation.get("op_id"),
        "task_id": task_id,
        "event_id": event_id,
    }


def log_attachment(row: dict) -> dict:
    return {"available": False, "reason": LOG_IN_TASK if row.get("task_id") else LOG_NONE}


def _task_index(rows: Sequence[dict]) -> dict:
    from core.task_manager import task_manager

    index: dict[str, Any] = {}
    for server_id in {row.get("server_id") for row in rows if row.get("server_id")}:
        running = task_manager.get_running(server_id)
        if running is not None:
            index[running.id] = running
        for queued in task_manager.get_queue(server_id):
            index.setdefault(queued.id, queued)
    for task in task_manager.get_history(limit=HISTORY_INDEX_LIMIT):
        index.setdefault(task.id, task)
    return index


def _event_index(rows: Sequence[dict]) -> dict:
    wanted = {row.get("event_id") for row in rows if row.get("event_id")}
    if not wanted:
        return {}
    from core.events import get_events

    return {
        event["id"]: event
        for event in get_events(limit=EVENT_INDEX_LIMIT)
        if event.get("id") in wanted
    }


def _attachments(task_id: Optional[str], event_id: Optional[str], tasks: dict, events: dict) -> dict:
    return {
        "event": bool(event_id) and event_id in events,
        "task": bool(task_id) and task_id in tasks,
        "log": False,
    }


def _masked(text: Any) -> Optional[str]:
    if text is None:
        return None
    from core import audit

    return audit.mask_text(text)


def _masked_list(items: Any) -> list:
    if isinstance(items, str):
        return [_masked(items) or ""]
    if not isinstance(items, (list, tuple)):
        return []
    return [_masked(item) or "" for item in items]


def _task_view(task: Any) -> dict:
    from core import audit

    data = task.to_dict()
    result = data.get("result") or {}
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "kind": data.get("kind"),
        "status": data.get("status"),
        "attempt": data.get("attempt"),
        "server_id": data.get("server_id"),
        "server_name": data.get("server_name"),
        "actor": data.get("actor"),
        "created_at": data.get("created_at"),
        "started_at": data.get("started_at"),
        "finished_at": data.get("finished_at"),
        "duration_seconds": data.get("duration_seconds"),
        "error": _masked(data.get("error")),
        "success": result.get("success"),
        "exit_code": result.get("exit_code"),
        "cancelled": result.get("cancelled"),
        "warnings": _masked_list(result.get("warnings")),
        "output": _masked(result.get("output")),
        "output_lines": _masked_list(data.get("output_lines")),
        "payload": audit.mask_params(data.get("payload") or {}),
    }


def _event_view(event: dict) -> dict:
    from core import audit

    return {
        "id": event.get("id"),
        "timestamp": event.get("timestamp"),
        "ts_epoch": event.get("ts_epoch"),
        "type": event.get("type"),
        "level": event.get("level"),
        "title": _masked(event.get("title")),
        "message": _masked(event.get("message")),
        "details": audit.mask_params(event.get("details") or {}),
        "read": event.get("read"),
        "read_time": event.get("read_time"),
    }


def _members(operation_ids: Sequence[str], path=None) -> dict[str, list[dict]]:
    ids = [str(value) for value in operation_ids]
    if not ids:
        return {}
    placeholders = ", ".join("?" for _ in ids)
    rows = state_db.query(
        f"SELECT m.operation_id, {_RAW_COLUMNS} FROM audit_operation_members m "
        f"JOIN audit_records r ON r.id = m.record_id "
        # При равном ts started-запись раньше финала: имена записей — uuid,
        # и «начало»/«финал» одной секунды иначе меняются местами от прогона
        # к прогону (тот же tie-break, что в audit_operations._ordered).
        f"WHERE m.operation_id IN ({placeholders}) "
        f"ORDER BY r.ts, CASE WHEN r.result = 'started' THEN 0 ELSE 1 END, r.id",
        ids,
        path,
    )
    grouped = {operation_id: [] for operation_id in ids}
    for row in rows:
        grouped.setdefault(row.pop("operation_id"), []).append(row)
    return grouped


def _operation_sql() -> str:
    return _OPERATION_BASE.format(columns=f"o.{_OPERATION_COLUMNS.replace(', ', ', o.')}")


def _cursor_of(row: dict) -> str:
    return f"{int(row['started_ts'])}:{row['sort_id']}"


def parse_cursor(cursor: Optional[str]) -> Optional[tuple[int, str]]:
    if cursor is None or cursor == "":
        return None
    ts_part, sep, sort_id = str(cursor).partition(":")
    if not sep or not sort_id:
        raise ValueError(f"cursor: ожидается «ts:id», получено {cursor!r}")
    try:
        return int(ts_part), sort_id
    except ValueError as exc:
        raise ValueError(f"cursor: ожидается «ts:id», получено {cursor!r}") from exc


def _search_clause(query: str) -> tuple[str, list[Any]]:
    pattern = _like(query)
    codes = codes_matching_title(query)
    clauses = [
        "o.title LIKE ? ESCAPE '\\'",
        "o.action LIKE ? ESCAPE '\\'",
        "o.error LIKE ? ESCAPE '\\'",
        "EXISTS (SELECT 1 FROM audit_operation_members sm JOIN audit_records sr "
        "ON sr.id = sm.record_id WHERE sm.operation_id = o.operation_id "
        "AND (sr.params LIKE ? ESCAPE '\\' OR sr.error LIKE ? ESCAPE '\\' "
        "OR sr.action LIKE ? ESCAPE '\\'))",
    ]
    params: list[Any] = [pattern, pattern, pattern, pattern, pattern, pattern]
    if codes:
        placeholders = ", ".join("?" for _ in codes)
        clauses.append(f"o.action IN ({placeholders})")
        params.extend(codes)
    return " AND (" + " OR ".join(clauses) + ")", params


def list_records(
    *,
    since: Optional[int] = None,
    until: Optional[int] = None,
    actor_type: Optional[str] = None,
    actor_id: Optional[str] = None,
    server_id: Optional[str] = None,
    action: Optional[str] = None,
    action_prefix: Optional[str] = None,
    result: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = DEFAULT_LIMIT,
    cursor: Optional[str] = None,
    path=None,
) -> dict:
    limit = int(limit)
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError(f"limit: 1..{MAX_LIMIT}")
    if actor_type is not None and actor_type not in ACTOR_TYPES:
        raise ValueError(f"actor_type: {'|'.join(ACTOR_TYPES)}")
    if result is not None and result not in RESULTS:
        raise ValueError(f"result: {'|'.join(RESULTS)}")
    if q is not None and len(str(q)) > MAX_QUERY:
        raise ValueError(f"q: не длиннее {MAX_QUERY} символов")
    _since_until(since, until)

    sql, params = _operation_sql(), []
    window, window_params = _operation_window(since, until)
    sql += window
    params.extend(window_params)
    for column, value in (("actor_type", actor_type), ("actor_id", actor_id), ("server_id", server_id), ("action", action)):
        if value:
            sql += f" AND o.{column} = ?"
            params.append(value)
    if result:
        if result == INCOMPLETE:
            sql += " AND o.status = ?"
            params.append(INCOMPLETE)
        elif result == "awaiting_rule_selection":
            sql += " AND o.status = ?"
            params.append(WAITING_RULE_SELECTION)
        else:
            sql += " AND o.status = ? AND o.result = ?"
            params.extend((COMPLETED, result))
    if action_prefix:
        sql += " AND o.action LIKE ? ESCAPE '\\'"
        params.append(_like_prefix(action_prefix))
    if q:
        clause, search_params = _search_clause(str(q))
        sql += clause
        params.extend(search_params)
    position = parse_cursor(cursor)
    if position is not None:
        started_ts, sort_id = position
        sql += " AND (o.started_ts < ? OR (o.started_ts = ? AND o.sort_id < ?))"
        params.extend((started_ts, started_ts, sort_id))
    sql += " ORDER BY o.started_ts DESC, o.sort_id DESC LIMIT ?"
    params.append(limit + 1)
    rows = state_db.query(sql, params, path)
    page = rows[:limit]
    by_operation = _members([row["operation_id"] for row in page], path)
    all_members = [member for members in by_operation.values() for member in members]
    tasks = _task_index(all_members)
    events = _event_index(all_members)
    items = []
    for row in page:
        members = by_operation.get(row["operation_id"], [])
        item = _operation_record(row, members)
        task_id, event_id = _references(row, members)
        item["attachments"] = _attachments(task_id, event_id, tasks, events)
        items.append(item)
    return {
        "items": items,
        "next_cursor": _cursor_of(page[-1]) if len(rows) > limit and page else None,
    }


def _technical_record(row: dict) -> dict:
    return {
        "id": row["id"],
        "ts": int(row["ts"]),
        "actor": _actor(row),
        "server": _server(row),
        "action": row["action"],
        "title": title_of(row["action"]),
        "result": row["result"],
        "error": row.get("error"),
        "failure_detail": row.get("failure_detail"),
        "op_id": row.get("op_id"),
        "task_id": row.get("task_id"),
        "event_id": row.get("event_id"),
        "params": params_of(row),
    }


def record_detail(record_id: str, path=None) -> Optional[dict]:
    rows = state_db.query(
        _operation_sql() + " AND (o.operation_id = ? OR EXISTS (SELECT 1 FROM audit_operation_members m "
        "WHERE m.operation_id = o.operation_id AND m.record_id = ?)) LIMIT 1",
        (record_id, record_id),
        path,
    )
    if not rows:
        return None
    operation = rows[0]
    members = _members([operation["operation_id"]], path).get(operation["operation_id"], [])
    if not members:
        return None
    task_id, event_id = _references(operation, members)
    tasks = _task_index(members)
    events = _event_index(members)
    record = _operation_record(operation, members)
    record["attachments"] = _attachments(task_id, event_id, tasks, events)
    anchor = next((row for row in members if row["id"] == operation["anchor_id"]), members[0])
    task = tasks.get(task_id) if task_id else None
    event = events.get(event_id) if event_id else None
    return {
        "record": record,
        "params": params_of(anchor),
        "task": _task_view(task) if task is not None else None,
        "event": _event_view(event) if event is not None else None,
        "log": log_attachment({"task_id": task_id}),
        "technical_records": [_technical_record(row) for row in members],
    }


def _facet_rows(column_sql: str, path=None) -> list[dict]:
    return state_db.query(
        _operation_sql() + f" GROUP BY {column_sql} ORDER BY n DESC, {column_sql}",
        (),
        path,
    )


def facets(path=None) -> dict:
    actors = [
        {"type": row.get("actor_type"), "id": row.get("actor_id"),
         "label": actor_label(row.get("actor_type"), row.get("actor_id")), "count": int(row["n"])}
        for row in state_db.query(
            "SELECT o.actor_type, CASE WHEN o.actor_type = 'web' THEN NULL ELSE o.actor_id END AS actor_id, "
            "COUNT(*) AS n FROM (" + _operation_sql() + ") o "
            "GROUP BY o.actor_type, CASE WHEN o.actor_type = 'web' THEN NULL ELSE o.actor_id END "
            "ORDER BY n DESC, actor_id", (), path)
    ]
    actions = [
        {"code": row["action"], "title": row["title"], "count": int(row["n"])}
        for row in state_db.query(
            "SELECT o.action, o.title, COUNT(*) AS n FROM (" + _operation_sql() + ") o "
            "GROUP BY o.action, o.title ORDER BY n DESC, o.action", (), path)
    ]
    servers = [
        {"id": row.get("server_id"), "name": row.get("server_name"), "count": int(row["n"]),
         "last_ts": int(row["last_ts"])}
        for row in state_db.query(
            "SELECT o.server_id, o.server_name, COUNT(*) AS n, MAX(o.started_ts) AS last_ts "
            "FROM (" + _operation_sql() + ") o WHERE o.server_id IS NOT NULL "
            "GROUP BY o.server_id ORDER BY n DESC, o.server_id", (), path)
    ]
    results = [
        {"value": row["result"], "title": "Нет записи о завершении" if row["result"] == INCOMPLETE
         else RESULT_TITLES.get(row["result"], row["result"]), "count": int(row["n"])}
        for row in state_db.query(
            "SELECT CASE "
            "WHEN o.status = 'incomplete' THEN 'incomplete' "
            "WHEN o.status = 'waiting_rule_selection' THEN 'awaiting_rule_selection' "
            "ELSE o.result END AS result, "
            "COUNT(*) AS n FROM (" + _operation_sql() + ") o GROUP BY result ORDER BY n DESC, result", (), path)
    ]
    return {"actors": actors, "actions": actions, "servers": servers, "results": results}


def _local_midnight(ts: int) -> int:
    moment = datetime.fromtimestamp(int(ts)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(moment.timestamp())


def _stat_window(since: Optional[int], until: Optional[int], path=None) -> list[dict]:
    window, params = _operation_window(since, until)
    return state_db.query(_operation_sql() + window, params, path)


def _bucket(group_by: str, row: dict) -> dict:
    if group_by == "actor":
        actor_type, actor_id = row.get("actor_type"), row.get("actor_id")
        return {"key": f"{actor_type}:{actor_id or ''}", "label": actor_label(actor_type, actor_id),
                "count": int(row["n"]), "actor_type": actor_type, "actor_id": actor_id}
    if group_by == "action":
        return {"key": row["action"], "label": row["title"], "count": int(row["n"])}
    if group_by == "server":
        return {"key": row.get("server_id"), "label": row.get("server_name") or row.get("server_id") or NO_SERVER_TITLE,
                "count": int(row["n"]), "last_ts": int(row["last_ts"])}
    return {"key": row["result"], "label": "Нет записи о завершении" if row["result"] == INCOMPLETE
            else RESULT_TITLES.get(row["result"], row["result"]), "count": int(row["n"])}


def _day_buckets(rows: Sequence[dict], since: Optional[int], until: Optional[int]) -> list[dict]:
    stamps = [int(row["started_ts"]) for row in rows]
    if not stamps:
        return []
    first = _local_midnight(int(since) if since is not None else min(stamps))
    last = _local_midnight(int(until) if until is not None else max(stamps))
    counts: dict[int, int] = {}
    for stamp in stamps:
        day = _local_midnight(stamp)
        counts[day] = counts.get(day, 0) + 1
    buckets = []
    day = first
    while day <= last:
        buckets.append({"key": day, "label": datetime.fromtimestamp(day).strftime("%Y-%m-%d"), "count": counts.get(day, 0)})
        day = _local_midnight(day + 26 * 3600)
    return buckets


def stats(*, group_by: str, since: Optional[int] = None, until: Optional[int] = None, path=None) -> dict:
    if group_by not in GROUP_BY:
        raise ValueError(f"group_by: {'|'.join(GROUP_BY)}")
    _since_until(since, until)
    rows = _stat_window(since, until, path)
    if group_by == "day":
        buckets = _day_buckets(rows, since, until)
    else:
        grouped: dict[tuple, dict] = {}
        for row in rows:
            result = _operation_result(row)
            if group_by == "actor":
                key = (row.get("actor_type"), row.get("actor_id"))
            elif group_by == "action":
                key = (row["action"], row["title"])
            elif group_by == "server":
                key = (row.get("server_id"), row.get("server_name"))
            else:
                key = (result,)
            bucket = grouped.setdefault(key, {**row, "result": result, "n": 0, "last_ts": int(row["started_ts"])})
            bucket["n"] += 1
            bucket["last_ts"] = max(bucket["last_ts"], int(row["started_ts"]))
        buckets = [_bucket(group_by, row) for row in sorted(grouped.values(), key=lambda item: (-item["n"], str(item.get("action") or item.get("result") or item.get("server_id") or "")))]
    return {"group_by": group_by, "from": int(since) if since is not None else None,
            "to": int(until) if until is not None else None, "total": len(rows), "buckets": buckets}


def window_operations(server_id: str, since: Optional[int], until: Optional[int], limit: int = MARKS_ROWS, path=None) -> list[dict]:
    _since_until(since, until)
    window, params = _operation_window(since, until)
    sql = _operation_sql() + " AND o.server_id = ?" + window + " ORDER BY o.started_ts DESC, o.sort_id DESC LIMIT ?"
    return state_db.query(sql, [server_id, *params, max(1, int(limit))], path)


def window_rows(server_id: str, since: Optional[int], until: Optional[int], limit: int = MARKS_ROWS, path=None) -> list[dict]:
    """Compatibility raw rows for callers that need physical audit records."""
    _since_until(since, until)
    sql = f"SELECT {_RAW_COLUMNS} FROM audit_records WHERE server_id = ?"
    params: list[Any] = [server_id]
    if since is not None:
        sql += " AND ts >= ?"
        params.append(int(since))
    if until is not None:
        sql += " AND ts <= ?"
        params.append(int(until))
    sql += " ORDER BY ts DESC, id DESC LIMIT ?"
    params.append(max(1, int(limit)))
    return state_db.query(sql, params, path)


def _tail_row(row: dict) -> dict:
    return {"id": row["id"], "ts": int(row["ts"]), "action": row["action"],
            "title": title_of(row["action"]), "result": row["result"],
            "actor_type": row.get("actor_type"), "actor_id": row.get("actor_id"),
            "server_id": row.get("server_id")}


def tail_mark(path=None) -> tuple[int, int]:
    rows = state_db.query(_LAST_ROWID_SQL, (), path)
    if not rows or rows[0]["last"] is None:
        return 0, 0
    return int(rows[0]["last"]), int(rows[0]["last_ts"] or 0)


def tail_after(cursor_rowid: int = 0, cursor_ts: int = 0, limit: int = TAIL_LIMIT, path=None) -> tuple[list, int, int]:
    cursor_rowid, cursor_ts = max(0, int(cursor_rowid)), max(0, int(cursor_ts))
    newest_rowid, newest_ts = tail_mark(path)
    if newest_rowid == 0:
        return [], cursor_rowid, cursor_ts
    take = max(1, int(limit))
    if cursor_rowid > newest_rowid:
        rows = list(reversed(state_db.query(_TAIL_LAST_SQL, (take,), path)))
        return [_tail_row(row) for row in rows], newest_rowid, newest_ts
    rows = state_db.query(_TAIL_SQL, (cursor_rowid, cursor_ts, take), path)
    return ([_tail_row(row) for row in rows], max([cursor_rowid] + [int(row["rid"]) for row in rows]),
            max([cursor_ts] + [int(row["ts"]) for row in rows]))


__all__ = [
    "DEFAULT_LIMIT", "MAX_LIMIT", "MARKS_ROWS", "TAIL_LIMIT", "ACTOR_TYPES", "RESULTS", "GROUP_BY",
    "LOG_IN_TASK", "LOG_NONE", "NO_SERVER_TITLE", "list_records", "record_detail", "facets", "stats",
    "window_operations", "window_rows", "params_of", "log_attachment", "parse_cursor", "tail_mark", "tail_after",
]
