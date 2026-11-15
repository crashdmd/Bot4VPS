"""Temporary console-issued Web access is retained as inactive code only."""
from typing import NoReturn

from fastapi import HTTPException


def require_cli_recovery_enabled() -> NoReturn:
    """Fail closed: no environment, config, request or role can enable it."""
    raise HTTPException(404, "Не найдено")
