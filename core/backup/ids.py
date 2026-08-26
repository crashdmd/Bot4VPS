from __future__ import annotations

import re
import uuid


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,127}$")


def new_id(prefix: str) -> str:
    if not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,15}", prefix):
        raise ValueError("Некорректный prefix")
    return f"{prefix}-{uuid.uuid4().hex}"


def validate_id(value: str, *, field: str = "id", min_length: int = 6) -> str:
    if not isinstance(value, str) or len(value) < min_length or not _ID_RE.fullmatch(value):
        raise ValueError(f"Некорректный {field}")
    if value in {".", ".."} or ".." in value or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError(f"Некорректный {field}")
    return value


def new_backup_id() -> str:
    return new_id("bkp")


def new_operation_id() -> str:
    return new_id("op")


def new_claim_id() -> str:
    return new_id("ret")


def new_run_id() -> str:
    return new_id("ret-run")
