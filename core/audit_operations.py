"""Проекция пользовательских операций поверх append-only аудита.

Одна операция может состоять из нескольких записей, связанных ``op_id`` или
``task_id``. Этот модуль держит единую семантику такой группы для списка
аудита, деталей и марок таймлайна. Он не открывает SSH и не меняет исходные
``audit_records``.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable, Optional

from core.audit_actions import AuditResult, title_of

TASK_PREFIX = "task."
INCOMPLETE = "incomplete"
WAITING_RULE_SELECTION = "waiting_rule_selection"
COMPLETED = "completed"

_RESULT_RANK = {
    AuditResult.OK.value: 0,
    AuditResult.CANCELLED.value: 1,
    AuditResult.FAILED.value: 2,
}


def params_of(row: dict) -> dict:
    raw = row.get("params")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _ordered(rows: Iterable[dict]) -> list[dict]:
    # При равном ts началу пары — started-запись: «начало» и финал в одну
    # секунду (терминал, быстрый QS-шаг) иначе соревнуются случайным uuid,
    # и anchor операции недетерминированно доставался закрывающей записи.
    # Симметрично _RESULT_RANK в final_of, который тем же способом выбирает
    # «какой финал последний».
    return sorted(
        rows,
        key=lambda row: (
            int(row["ts"]),
            0 if str(row.get("result")) == AuditResult.STARTED.value else 1,
            str(row["id"]),
        ),
    )


def collapse(rows: Iterable[dict]) -> list[list[dict]]:
    """Транзитивно склеить строки общим ``op_id`` или ``task_id``."""
    ordered = _ordered(rows)
    parent = list(range(len(ordered)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    seen_by_key: dict[tuple[str, str], int] = {}
    for index, row in enumerate(ordered):
        for kind in ("op_id", "task_id"):
            value = row.get(kind)
            if not value:
                continue
            key = (kind, str(value))
            previous = seen_by_key.get(key)
            if previous is None:
                seen_by_key[key] = index
            else:
                union(index, previous)

    groups: dict[int, list[dict]] = {}
    for index, row in enumerate(ordered):
        groups.setdefault(find(index), []).append(row)
    return [groups[root] for root in sorted(groups)]


def is_task(row: dict) -> bool:
    return str(row.get("action") or "").startswith(TASK_PREFIX)


def anchor_of(group: Iterable[dict]) -> dict:
    rows = _ordered(group)
    for row in rows:
        if not is_task(row):
            return row
    return rows[0]


def final_of(group: Iterable[dict]) -> Optional[dict]:
    terminals = {
        AuditResult.OK.value,
        AuditResult.FAILED.value,
        AuditResult.CANCELLED.value,
    }
    finals = [row for row in group if row.get("result") in terminals]
    if not finals:
        return None
    last_ts = max(int(row["ts"]) for row in finals)
    same_time = [row for row in finals if int(row["ts"]) == last_ts]
    return max(same_time, key=lambda row: _RESULT_RANK.get(str(row.get("result")), 0))


def waiting_of(group: Iterable[dict]) -> Optional[dict]:
    waiting = [
        row for row in group
        if row.get("result") == AuditResult.AWAITING_RULE_SELECTION.value
    ]
    return _ordered(waiting)[-1] if waiting else None


def operation_title(group: Iterable[dict], action: str) -> str:
    rows = _ordered(group)
    actions = {str(row.get("action") or "") for row in rows}
    if "terminal.open" in actions and "terminal.close" in actions:
        return "Работа в терминале"
    for row in rows:
        task_name = params_of(row).get("task_name")
        if task_name:
            return str(task_name)
    return title_of(action)


def operation_error(group: Iterable[dict], anchor: dict, final: Optional[dict]) -> Optional[str]:
    action = str(anchor.get("action") or "")
    params = params_of(anchor)
    if action == "packages.install" and (str((final or anchor).get("error") or "") == "empty" or params.get("packages") == []):
        return "Не выбран ни один пакет"
    if final and final.get("error"):
        return str(final["error"])
    if waiting_of(group) is not None:
        return None
    for row in reversed(_ordered(group)):
        if row.get("error"):
            return str(row["error"])
    return None


def summary(group: Iterable[dict], operation_id: str) -> dict:
    """Безопасная отображаемая сводка одной уже связанной операции."""
    rows = _ordered(group)
    head = rows[0]
    anchor = anchor_of(rows)
    final = final_of(rows)
    waiting = waiting_of(rows) if final is None else None
    action = str(anchor.get("action") or "")
    ended_at = int((final or waiting)["ts"]) if final is not None or waiting is not None else None
    return {
        "operation_id": str(operation_id),
        "started_ts": int(head["ts"]),
        "sort_id": str(head["id"]),
        "anchor_id": str(anchor["id"]),
        "final_id": str(final["id"]) if final is not None else None,
        "ended_ts": ended_at,
        "action": action,
        "title": operation_title(rows, action),
        "result": str((final or waiting or head).get("result") or ""),
        "status": (
            COMPLETED if final is not None
            else WAITING_RULE_SELECTION if waiting is not None
            else INCOMPLETE
        ),
        "error": operation_error(rows, anchor, final),
        "actor_type": anchor.get("actor_type"),
        "actor_id": anchor.get("actor_id"),
        "actor_role": anchor.get("actor_role"),
        "actor_ip": anchor.get("actor_ip"),
        "server_id": anchor.get("server_id"),
        "server_name": anchor.get("server_name"),
        "op_id": anchor.get("op_id"),
        "task_id": anchor.get("task_id") or head.get("task_id"),
        "event_id": anchor.get("event_id"),
    }


_OPERATION_COLUMNS = (
    "operation_id", "started_ts", "sort_id", "anchor_id", "final_id", "ended_ts",
    "action", "title", "result", "status", "error", "actor_type", "actor_id",
    "actor_role", "actor_ip", "server_id", "server_name", "op_id", "task_id", "event_id",
)


def _insert_summary(conn: sqlite3.Connection, value: dict) -> None:
    fields = ", ".join(_OPERATION_COLUMNS)
    placeholders = ", ".join("?" for _ in _OPERATION_COLUMNS)
    conn.execute(
        f"INSERT OR REPLACE INTO audit_operations ({fields}) VALUES ({placeholders})",
        tuple(value.get(column) for column in _OPERATION_COLUMNS),
    )


def _keys(row: dict) -> list[tuple[str, str]]:
    return [(kind, str(row[kind])) for kind in ("op_id", "task_id") if row.get(kind)]


def _members(conn: sqlite3.Connection, operation_id: str) -> list[dict]:
    columns = ", ".join(f"r.{column}" for column in (
        "id", "ts", "actor_type", "actor_id", "actor_role", "actor_ip", "server_id",
        "server_name", "action", "result", "error", "op_id", "event_id", "task_id", "params",
    ))
    return [dict(row) for row in conn.execute(
        f"SELECT {columns} FROM audit_records r "
        "JOIN audit_operation_members m ON m.record_id = r.id "
        "WHERE m.operation_id = ? "
        "ORDER BY r.ts, CASE WHEN r.result = 'started' THEN 0 ELSE 1 END, r.id",
        (operation_id,),
    ).fetchall()]


def _operation_sort_key(conn: sqlite3.Connection, operation_id: str) -> tuple[int, str]:
    row = conn.execute(
        "SELECT started_ts, sort_id FROM audit_operations WHERE operation_id = ?",
        (operation_id,),
    ).fetchone()
    return (int(row[0]), str(row[1])) if row is not None else (2**63 - 1, operation_id)


def incorporate(conn: sqlite3.Connection, row: dict) -> None:
    """Включить только что вставленную raw-строку в derived operation tables."""
    keys = _keys(row)
    linked: set[str] = set()
    for kind, value in keys:
        linked.update(str(found[0]) for found in conn.execute(
            "SELECT operation_id FROM audit_operation_keys WHERE kind = ? AND value = ?",
            (kind, value),
        ).fetchall())

    operation_id = min(linked, key=lambda item: _operation_sort_key(conn, item)) if linked else str(row["id"])
    if linked:
        placeholders = ", ".join("?" for _ in linked)
        conn.execute(
            f"UPDATE audit_operation_members SET operation_id = ? WHERE operation_id IN ({placeholders})",
            (operation_id, *linked),
        )
        conn.execute(
            f"UPDATE audit_operation_keys SET operation_id = ? WHERE operation_id IN ({placeholders})",
            (operation_id, *linked),
        )
        conn.execute(
            f"DELETE FROM audit_operations WHERE operation_id IN ({placeholders}) AND operation_id != ?",
            (*linked, operation_id),
        )

    conn.execute(
        "INSERT INTO audit_operation_members (record_id, operation_id) VALUES (?, ?)",
        (str(row["id"]), operation_id),
    )
    for kind, value in keys:
        conn.execute(
            "INSERT OR REPLACE INTO audit_operation_keys (kind, value, operation_id) VALUES (?, ?, ?)",
            (kind, value, operation_id),
        )
    _insert_summary(conn, summary(_members(conn, operation_id), operation_id))


def rebuild(conn: sqlite3.Connection) -> None:
    """Построить derived-проекцию для существующего append-only журнала."""
    conn.execute("DELETE FROM audit_operation_members")
    conn.execute("DELETE FROM audit_operation_keys")
    conn.execute("DELETE FROM audit_operations")
    rows = [dict(row) for row in conn.execute(
        "SELECT id, ts, actor_type, actor_id, actor_role, actor_ip, server_id, server_name, "
        "action, result, error, op_id, event_id, task_id, params "
        "FROM audit_records ORDER BY ts, id"
    ).fetchall()]
    for row in rows:
        incorporate(conn, row)


__all__ = [
    "COMPLETED", "INCOMPLETE", "WAITING_RULE_SELECTION", "anchor_of", "collapse", "final_of",
    "incorporate", "is_task", "operation_title", "params_of", "rebuild", "summary", "waiting_of",
]
