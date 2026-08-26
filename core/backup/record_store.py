from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from core.json_store import atomic_write_json

from .errors import BackupError, ErrorCode
from .ids import validate_id
from .locks import LockCoordinator

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


class JsonRecordDirectory:
    """Unbounded one-record-per-file store for domain state."""

    def __init__(self, path: str | Path, coordinator: LockCoordinator, name: str):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.path.chmod(0o700)
        except OSError as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                f"Не удалось установить безопасные права {name} storage",
            ) from exc
        self.coordinator = coordinator
        self.name = name

    def _record_path(self, record_id: str) -> Path:
        try:
            validate_id(record_id, field=f"{self.name} id")
        except ValueError as exc:
            raise BackupError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
        return self.path / f"{record_id}.json"

    @contextmanager
    def locked(self, timeout: float = 30.0) -> Iterator[None]:
        handle = self.coordinator._acquire(self.path / ".lock", shared=False, timeout=timeout)
        try:
            yield
        finally:
            self.coordinator._unlock(handle)

    def _read_path(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as stream:
                raw = json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            raise BackupError(ErrorCode.STORAGE_BACKEND_ERROR, f"Повреждена запись {self.name}") from exc
        if not isinstance(raw, dict):
            raise BackupError(ErrorCode.STORAGE_BACKEND_ERROR, f"Некорректная запись {self.name}")
        return raw

    def get(self, record_id: str) -> dict | None:
        return self._read_path(self._record_path(record_id))

    def list(self) -> list[dict]:
        result = []
        for path in sorted(self.path.glob("*.json")):
            raw = self._read_path(path)
            if raw is not None:
                result.append(raw)
        return result

    def create(self, record_id: str, value: dict) -> None:
        path = self._record_path(record_id)
        with self.locked():
            if path.exists():
                raise BackupError(ErrorCode.OPERATION_CONFLICT, f"Запись {self.name} уже существует", retryable=True)
            atomic_write_json(path, value)

    def create_if_no_match(
        self,
        record_id: str,
        value: dict,
        predicate: Callable[[dict], bool],
    ) -> tuple[dict, bool]:
        """Атомарно вернуть matching record или создать новый."""
        path = self._record_path(record_id)
        with self.locked():
            for candidate_path in sorted(self.path.glob("*.json")):
                candidate = self._read_path(candidate_path)
                if candidate is not None and predicate(candidate):
                    return candidate, False
            if path.exists():
                raise BackupError(
                    ErrorCode.OPERATION_CONFLICT,
                    f"Запись {self.name} уже существует",
                    retryable=True,
                )
            atomic_write_json(path, value)
            return dict(value), True

    def mutate(self, record_id: str, fn: Callable[[dict], dict]) -> dict:
        path = self._record_path(record_id)
        with self.locked():
            current = self._read_path(path)
            if current is None:
                raise BackupError(ErrorCode.OPERATION_NOT_FOUND, f"Запись {self.name} не найдена")
            updated = fn(dict(current))
            atomic_write_json(path, updated)
            return updated

    def delete(self, record_id: str) -> bool:
        path = self._record_path(record_id)
        with self.locked():
            if not path.exists():
                return False
            path.unlink()
            return True
