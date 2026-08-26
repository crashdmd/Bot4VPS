from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Iterator

from core.install_paths import get_backup_data_path, get_backup_lock_path
from core.json_store import atomic_write_json

from .errors import BackupError, ErrorCode
from .ids import validate_id
from .models import ArtifactRef
from .time_utils import utc_timestamp

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


@dataclass
class Permit:
    operation_id: str
    kind: str
    owner_pid: int = field(default_factory=os.getpid)
    _locks: list[tuple[IO[str], int]] = field(default_factory=list, repr=False)
    _coordinator: "LockCoordinator | None" = field(default=None, repr=False)
    _maintenance: bool = field(default=False, repr=False)
    _released: bool = field(default=False, repr=False)

    def add(self, handle: IO[str], mode: int) -> None:
        self._locks.append((handle, mode))

    def release(self) -> None:
        if self._released:
            return
        clear_maintenance = self._maintenance and self._coordinator is not None
        while self._locks:
            handle, _ = self._locks.pop()
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
        self._released = True
        if clear_maintenance:
            self._coordinator._clear_maintenance(self.operation_id)

    def __enter__(self) -> "Permit":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class LockCoordinator:
    def __init__(self, lock_root: str | Path | None = None, data_root: str | Path | None = None):
        if fcntl is None:
            raise BackupError(ErrorCode.LOCKING_UNAVAILABLE, "Обязательная flock-блокировка недоступна")
        self.root = Path(lock_root or get_backup_lock_path())
        self.data_root = Path(data_root or get_backup_data_path())
        self.maintenance_state_path = self.data_root / "maintenance_state.json"
        self._prepare_layout()

    def _prepare_layout(self) -> None:
        for path in (self.root, self.root / "targets", self.root / "artifacts", self.root / "retention", self.root / "operations", self.root / "imports", self.root / "destinations"):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                path.chmod(0o700)
            except OSError as exc:
                raise BackupError(
                    ErrorCode.LOCKING_UNAVAILABLE,
                    "Не удалось установить безопасные права lock directory",
                ) from exc
        self.data_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.data_root.chmod(0o700)
        except OSError as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Не удалось установить безопасные права backup data directory",
            ) from exc

    @staticmethod
    def _validated(value: str, field: str) -> str:
        try:
            return validate_id(value, field=field, min_length=1)
        except ValueError as exc:
            raise BackupError(ErrorCode.INVALID_REQUEST, str(exc)) from exc

    @classmethod
    def _target_name(cls, value: str) -> str:
        if not isinstance(value, str) or not value:
            raise BackupError(ErrorCode.INVALID_REQUEST, "Некорректный target_key")
        parts = value.split(":", 1)
        if len(parts) == 2:
            cls._validated(parts[0], "target kind")
            cls._validated(parts[1], "target id")
            return f"{parts[0]}--{parts[1]}"
        return cls._validated(value, "target_key")

    def _acquire(self, path: Path, *, shared: bool, timeout: float) -> IO[str]:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        handle = path.open("a+", encoding="utf-8")
        mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            try:
                fcntl.flock(handle.fileno(), mode | fcntl.LOCK_NB)
                return handle
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise BackupError(ErrorCode.LOCK_TIMEOUT, f"Истекло время ожидания lock {path.name}", retryable=True)
                time.sleep(0.05)
            except OSError as exc:
                handle.close()
                raise BackupError(ErrorCode.LOCKING_UNAVAILABLE, "Не удалось получить обязательную flock-блокировку") from exc

    @staticmethod
    def _unlock(handle: IO[str]) -> None:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def _read_maintenance(self) -> dict:
        try:
            with self.maintenance_state_path.open("r", encoding="utf-8") as stream:
                raw = json.load(stream)
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Повреждено состояние maintenance",
            ) from exc
        if not isinstance(raw, dict):
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Повреждено состояние maintenance",
            )
        return raw

    def _write_maintenance(self, *, intent, active) -> None:
        atomic_write_json(self.maintenance_state_path, {
            "schema_version": 1,
            "intent": intent,
            "active": active,
            "updated_at": utc_timestamp(),
        })

    def begin_backup(self, operation_id: str, target_key: str, timeout: float = 30.0) -> Permit:
        operation_id = self._validated(operation_id, "operation_id")
        target_lock_name = self._target_name(target_key)
        permit = Permit(operation_id, "backup", _coordinator=self)
        admission = self._acquire(self.root / "admission.lock", shared=False, timeout=timeout)
        try:
            state = self._read_maintenance()
            if state.get("intent") or state.get("active"):
                raise BackupError(ErrorCode.MAINTENANCE_ACTIVE, "Активна или ожидает maintenance-операция", retryable=True)
            maintenance = self._acquire(self.root / "maintenance.lock", shared=True, timeout=timeout)
            permit.add(maintenance, fcntl.LOCK_SH)
        finally:
            self._unlock(admission)
        try:
            target = self._acquire(
                self.root / "targets" / f"{target_lock_name}.lock",
                shared=False,
                timeout=timeout,
            )
            permit.add(target, fcntl.LOCK_EX)
            return permit
        except Exception:
            permit.release()
            raise

    def begin_maintenance(
        self,
        operation_id: str,
        kind: str,
        target_key: str | None = None,
        timeout: float = 300.0,
    ) -> Permit:
        operation_id = self._validated(operation_id, "operation_id")
        if kind not in {"restore", "update", "migrate"}:
            raise BackupError(ErrorCode.INVALID_REQUEST, "Некорректный вид maintenance-операции")
        target_lock_name = self._target_name(target_key) if target_key else None
        intent = {
            "operation_id": operation_id,
            "type": kind,
            "requested_at": utc_timestamp(),
            "owner_pid": os.getpid(),
        }
        permit = Permit(operation_id, kind, _coordinator=self, _maintenance=True)
        admission = None
        try:
            # Admission is the first lock in the global order. Keep it while
            # acquiring Maintenance so a backup cannot slip in between the
            # intent marker and the exclusive maintenance lock.
            admission = self._acquire(self.root / "admission.lock", shared=False, timeout=timeout)
            state = self._read_maintenance()
            if state.get("intent") or state.get("active"):
                raise BackupError(ErrorCode.MAINTENANCE_ACTIVE, "Другая maintenance-операция уже активна", retryable=True)
            self._write_maintenance(intent=intent, active=None)
            maintenance = self._acquire(self.root / "maintenance.lock", shared=False, timeout=timeout)
            permit.add(maintenance, fcntl.LOCK_EX)
            self._write_maintenance(intent=intent, active={**intent, "started_at": utc_timestamp()})
        except Exception:
            if admission is not None:
                self._unlock(admission)
                admission = None
            permit.release()
            self._clear_maintenance(operation_id)
            raise
        finally:
            if admission is not None:
                self._unlock(admission)
        try:
            if target_lock_name:
                target = self._acquire(
                    self.root / "targets" / f"{target_lock_name}.lock",
                    shared=False,
                    timeout=timeout,
                )
                permit.add(target, fcntl.LOCK_EX)
            return permit
        except Exception:
            permit.release()
            self._clear_maintenance(operation_id)
            raise

    def reconcile_maintenance_state(self) -> bool:
        """Очистить stale state только без Maintenance и Operation owner locks."""
        admission = self._acquire(
            self.root / "admission.lock",
            shared=False,
            timeout=5.0,
        )
        maintenance = None
        owner = None
        try:
            state = self._read_maintenance()
            marker = state.get("active") or state.get("intent")
            if not marker:
                return False
            operation_id = marker.get("operation_id") if isinstance(marker, dict) else None
            if not isinstance(operation_id, str):
                raise BackupError(
                    ErrorCode.STORAGE_BACKEND_ERROR,
                    "Повреждено состояние maintenance",
                )
            try:
                maintenance = self._acquire(
                    self.root / "maintenance.lock",
                    shared=False,
                    timeout=0.0,
                )
            except BackupError as exc:
                if exc.code == ErrorCode.LOCK_TIMEOUT.value:
                    return False
                raise
            try:
                owner = self._acquire(
                    self.root / "operations" / f"{self._validated(operation_id, 'operation_id')}.lock",
                    shared=False,
                    timeout=0.0,
                )
            except BackupError as exc:
                if exc.code == ErrorCode.LOCK_TIMEOUT.value:
                    return False
                raise
            self._write_maintenance(intent=None, active=None)
            return True
        finally:
            if owner is not None:
                self._unlock(owner)
            if maintenance is not None:
                self._unlock(maintenance)
            self._unlock(admission)

    def _clear_maintenance(self, operation_id: str) -> None:
        try:
            admission = self._acquire(self.root / "admission.lock", shared=False, timeout=5.0)
        except BackupError:
            return
        try:
            state = self._read_maintenance()
            intent = state.get("intent")
            active = state.get("active")
            if (intent or {}).get("operation_id") == operation_id or (active or {}).get("operation_id") == operation_id:
                self._write_maintenance(intent=None, active=None)
        finally:
            self._unlock(admission)

    @contextmanager
    def destination_lock(
        self,
        server_id: str | None = None,
        timeout: float = 30.0,
    ) -> Iterator[None]:
        """Serialize visible filename mutations within one destination.

        ``None`` is the Bot4VPS destination; a server destination is keyed by
        its validated server id. The lock deliberately covers the whole
        destination rather than embedding an arbitrary user filename in a
        filesystem path, so collision scans and replacements observe one
        atomic namespace across Catalog and imported bundles.
        """
        if server_id is None:
            name = "bot4vps"
        else:
            name = f"server--{self._validated(str(server_id), 'server_id')}"
        handle = self._acquire(
            self.root / "destinations" / f"{name}.lock",
            shared=False,
            timeout=timeout,
        )
        try:
            yield
        finally:
            self._unlock(handle)

    def _artifact_path(self, ref: "ArtifactRef") -> Path:
        if not isinstance(ref, ArtifactRef):
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Artifact lock требует ArtifactRef",
            )
        path = self.root / "artifacts"
        for part in ref.namespace_parts:
            path = path / self._validated(part, "artifact namespace")
        return path / f"{self._validated(ref.backup_id, 'backup_id')}.lock"

    def _artifact(self, ref: "ArtifactRef", *, shared: bool, timeout: float, kind: str) -> Permit:
        handle = self._acquire(self._artifact_path(ref), shared=shared, timeout=timeout)
        permit = Permit(ref.backup_id, kind, _coordinator=self)
        permit.add(handle, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        return permit

    def acquire_artifact_read(self, ref: "ArtifactRef", timeout: float = 30.0) -> Permit:
        return self._artifact(ref, shared=True, timeout=timeout, kind="artifact_read")

    def acquire_artifact_publish(self, ref: "ArtifactRef", timeout: float = 30.0) -> Permit:
        return self._artifact(ref, shared=False, timeout=timeout, kind="artifact_publish")

    def acquire_artifact_delete(self, ref: "ArtifactRef", timeout: float = 30.0) -> Permit:
        return self._artifact(ref, shared=False, timeout=timeout, kind="artifact_delete")

    def _import_path(self, entry_key: str, server_id: str | None) -> Path:
        entry_key = self._validated(entry_key, "entry_key")
        if server_id is None:
            namespace = self.root / "imports" / "bot4vps"
        else:
            namespace = (
                self.root
                / "imports"
                / "servers"
                / self._validated(server_id, "server_id")
            )
        return namespace / f"{entry_key}.lock"

    def _import_bundle(
        self,
        entry_key: str,
        *,
        server_id: str | None,
        shared: bool,
        timeout: float,
        kind: str,
    ) -> Permit:
        handle = self._acquire(
            self._import_path(entry_key, server_id),
            shared=shared,
            timeout=timeout,
        )
        permit = Permit(entry_key, kind, _coordinator=self)
        permit.add(handle, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        return permit

    def acquire_import_read(
        self,
        entry_key: str,
        *,
        server_id: str | None = None,
        timeout: float = 30.0,
    ) -> Permit:
        return self._import_bundle(
            entry_key,
            server_id=server_id,
            shared=True,
            timeout=timeout,
            kind="import_read",
        )

    def acquire_import_publish(
        self,
        entry_key: str,
        *,
        server_id: str | None = None,
        timeout: float = 30.0,
    ) -> Permit:
        return self._import_bundle(
            entry_key,
            server_id=server_id,
            shared=False,
            timeout=timeout,
            kind="import_publish",
        )

    def acquire_import_delete(
        self,
        entry_key: str,
        *,
        server_id: str | None = None,
        timeout: float = 30.0,
    ) -> Permit:
        return self._import_bundle(
            entry_key,
            server_id=server_id,
            shared=False,
            timeout=timeout,
            kind="import_delete",
        )

    def acquire_operation_owner(self, operation_id: str, timeout: float = 30.0) -> Permit:
        """Эксклюзивный durable owner lock конкретной Operation.

        OS flock является источником истины: после смерти runner lock освобождается
        автоматически, поэтому reconciliation может безопасно проверить владельца.
        """
        operation_id = self._validated(operation_id, "operation_id")
        handle = self._acquire(
            self.root / "operations" / f"{operation_id}.lock",
            shared=False,
            timeout=timeout,
        )
        permit = Permit(operation_id, "operation_owner", _coordinator=self)
        permit.add(handle, fcntl.LOCK_EX)
        return permit

    def try_acquire_operation_owner(self, operation_id: str) -> Permit | None:
        """Взять owner lock без ожидания; None означает живого владельца."""
        try:
            return self.acquire_operation_owner(operation_id, timeout=0.0)
        except BackupError as exc:
            if exc.code == ErrorCode.LOCK_TIMEOUT.value:
                return None
            raise

    @contextmanager
    def reconciliation_lock(self, timeout: float = 30.0) -> Iterator[None]:
        """Сериализует startup reconciliation между процессами."""
        handle = self._acquire(self.root / "reconciliation.lock", shared=False, timeout=timeout)
        try:
            yield
        finally:
            self._unlock(handle)

    @contextmanager
    def catalog_lock(self, timeout: float = 30.0) -> Iterator[None]:
        handle = self._acquire(self.root / "catalog.lock", shared=False, timeout=timeout)
        try:
            yield
        finally:
            self._unlock(handle)

    @contextmanager
    def retention_scope_lock(self, scope: str, timeout: float = 30.0) -> Iterator[None]:
        safe_scope = self._validated(scope.replace(":", "-"), "retention scope")
        handle = self._acquire(self.root / "retention" / f"{safe_scope}.lock", shared=False, timeout=timeout)
        try:
            yield
        finally:
            self._unlock(handle)

    def release(self, permit: Permit) -> None:
        permit.release()
