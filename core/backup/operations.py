from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from core.install_paths import get_backup_data_path
from core.json_store import atomic_write_json

from .errors import BackupError, ErrorCode, SafeError
from .ids import new_operation_id
from .locks import LockCoordinator
from .models import (
    OperationRecord,
    OperationStatus,
    TERMINAL_STATUSES,
)
from .record_store import JsonRecordDirectory
from .time_utils import utc_timestamp


_ALLOWED_TRANSITIONS = {
    OperationStatus.QUEUED.value: {
        OperationStatus.RUNNING.value,
        OperationStatus.CANCELLED.value,
        OperationStatus.FAILED.value,
    },
    OperationStatus.RUNNING.value: {
        OperationStatus.VERIFYING.value,
        OperationStatus.COMPLETED.value,
        OperationStatus.FAILED.value,
        OperationStatus.CANCELLED.value,
    },
    OperationStatus.VERIFYING.value: {
        OperationStatus.COMPLETED.value,
        OperationStatus.FAILED.value,
        OperationStatus.CANCELLED.value,
    },
}


class OperationStore:
    """Durable Operation storage split into active state and terminal history.

    Active records live in ``operations/running``.  A terminal transition writes
    the final validated record and atomically renames it into ``operations``.
    ``records`` remains an alias for the active directory for compatibility with
    the create publication critical section.
    """

    def __init__(self, data_root: str | Path | None = None, coordinator: LockCoordinator | None = None):
        self.data_root = Path(data_root or get_backup_data_path())
        self.coordinator = coordinator or LockCoordinator(data_root=self.data_root)
        self.history = JsonRecordDirectory(self.data_root / "operations", self.coordinator, "operation_history")
        self.running = JsonRecordDirectory(self.history.path / "running", self.coordinator, "operation_running")
        self.records = self.running
        self._migrate_layout()

    @staticmethod
    def _validate(record: dict) -> dict:
        try:
            return OperationRecord.from_dict(record).to_dict()
        except (TypeError, ValueError) as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Повреждена запись Operation",
            ) from exc

    @staticmethod
    def _same_logical_request(
        record: dict,
        *,
        request_id: str,
        operation_type: str,
        target: dict[str, Any],
    ) -> bool:
        return (
            record.get("status") not in TERMINAL_STATUSES
            and record.get("request_id") == request_id
            and record.get("type") == operation_type
            and record.get("target") == target
        )

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            fd = os.open(path, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Не удалось зафиксировать каталог Operation",
            ) from exc

    @staticmethod
    def _read_json(path: Path) -> dict | None:
        try:
            with path.open("r", encoding="utf-8") as stream:
                value = json.load(stream)
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise BackupError(ErrorCode.STORAGE_BACKEND_ERROR, "Повреждена запись Operation") from exc
        if not isinstance(value, dict):
            raise BackupError(ErrorCode.STORAGE_BACKEND_ERROR, "Повреждена запись Operation")
        return value

    def _move_locked(self, source: Path, destination: Path) -> None:
        """Move one record while both directory locks are held."""
        if destination.exists():
            source_value = self._read_json(source)
            destination_value = self._read_json(destination)
            if source_value == destination_value:
                source.unlink(missing_ok=True)
                self._fsync_directory(source.parent)
                return
            raise BackupError(
                ErrorCode.OPERATION_CONFLICT,
                "Operation одновременно присутствует в active state и history",
            )
        try:
            os.replace(source, destination)
            self._fsync_directory(source.parent)
            self._fsync_directory(destination.parent)
        except OSError as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Не удалось атомарно перенести Operation в историю",
                retryable=True,
            ) from exc

    def _migrate_layout(self) -> None:
        """Idempotently classify legacy flat and interrupted terminal records."""
        with self.running.locked():
            with self.history.locked():
                # Legacy flat non-terminal records belong to active state.
                for source in sorted(self.history.path.glob("*.json")):
                    raw = self._read_json(source)
                    if raw is None:
                        continue
                    record = self._validate(raw)
                    if record["status"] in TERMINAL_STATUSES:
                        continue
                    self._move_locked(source, self.running._record_path(record["operation_id"]))
                # A crash after the final atomic write but before the rename may
                # leave a terminal record in running. Finish that move on startup.
                for source in sorted(self.running.path.glob("*.json")):
                    raw = self._read_json(source)
                    if raw is None:
                        continue
                    record = self._validate(raw)
                    if record["status"] not in TERMINAL_STATUSES:
                        continue
                    self._move_locked(source, self.history._record_path(record["operation_id"]))

    def create(
        self,
        *,
        operation_type: str,
        target: dict[str, Any],
        request_id: str,
        mode: str = "manual",
        attempt: int = 1,
        parent_operation_id: str | None = None,
        operation_id: str | None = None,
        initiated_from_telegram: bool = False,
    ) -> dict:
        normalized_target = dict(target)
        operation = OperationRecord(
            operation_id=operation_id or new_operation_id(),
            request_id=request_id,
            type=operation_type,
            target=normalized_target,
            mode=mode,
            attempt=attempt,
            parent_operation_id=parent_operation_id,
            initiated_from_telegram=initiated_from_telegram,
        )
        try:
            operation_value = operation.to_dict()
        except (TypeError, ValueError) as exc:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Некорректная Operation",
            ) from exc
        value, _ = self.running.create_if_no_match(
            operation.operation_id,
            operation_value,
            lambda record: self._same_logical_request(
                self._validate(record),
                request_id=request_id,
                operation_type=operation_type,
                target=normalized_target,
            ),
        )
        return self._validate(value)

    def get(self, operation_id: str) -> dict:
        record = self.running.get(operation_id)
        if record is None:
            record = self.history.get(operation_id)
        if record is None:
            raise BackupError(ErrorCode.OPERATION_NOT_FOUND, "Операция backup не найдена")
        return self._validate(record)

    @staticmethod
    def _sorted(records: list[dict]) -> list[dict]:
        return sorted(records, key=lambda item: (item["created_at"], item["operation_id"]))

    def list(self) -> list[dict]:
        """Return terminal history only."""
        records = [self._validate(record) for record in self.history.list()]
        return self._sorted(records)

    def list_active(self) -> list[dict]:
        records = [self._validate(record) for record in self.running.list()]
        # Interrupted terminal moves are not active even before restart repair.
        records = [record for record in records if record["status"] not in TERMINAL_STATUSES]
        return self._sorted(records)

    def list_all(self) -> list[dict]:
        return self._sorted(self.list() + self.list_active())

    def find_by_request_id(
        self,
        request_id: str,
        *,
        operation_type: str | None = None,
        target: dict[str, Any] | None = None,
        active_only: bool = False,
    ) -> dict | None:
        records = self.list_active() if active_only else self.list_all()
        for record in records:
            if record["request_id"] != request_id:
                continue
            if operation_type is not None and record["type"] != operation_type:
                continue
            if target is not None and record["target"] != target:
                continue
            return record
        return None

    def clear_history(self) -> int:
        """Delete only direct terminal JSON records; never descend into running."""
        deleted = 0
        with self.history.locked():
            for path in sorted(self.history.path.glob("*.json")):
                try:
                    path.unlink()
                    deleted += 1
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise BackupError(
                        ErrorCode.STORAGE_BACKEND_ERROR,
                        "Не удалось очистить историю Backup Manager",
                    ) from exc
            self._fsync_directory(self.history.path)
        return deleted

    def _mutate_validated(
        self,
        operation_id: str,
        fn: Any,
    ) -> dict:
        def validate_and_mutate(record: dict) -> dict:
            current = self._validate(record)
            updated = fn(current)
            return self._validate(updated)

        try:
            return self.running.mutate(operation_id, validate_and_mutate)
        except BackupError as exc:
            # Terminal records are intentionally no longer in ``running``.  Keep
            # the public mutation boundary stable: attempting to mutate a known
            # terminal operation is a conflict, while an unknown id remains a
            # not-found error.
            if exc.code == ErrorCode.OPERATION_NOT_FOUND.value:
                terminal_record = self.history.get(operation_id)
                if terminal_record is not None:
                    record = self._validate(terminal_record)
                    if record["status"] in TERMINAL_STATUSES:
                        raise BackupError(
                            ErrorCode.OPERATION_CONFLICT,
                            "Терминальная операция неизменяема",
                        ) from exc
            raise

    def set_result_backup_id(
        self,
        operation_id: str,
        backup_id: str,
    ) -> dict:
        def mutate(record: dict) -> dict:
            if record.get("status") in TERMINAL_STATUSES:
                raise BackupError(
                    ErrorCode.OPERATION_CONFLICT,
                    "Терминальная операция неизменяема",
                )
            existing = record.get("result_backup_id")
            if existing is not None and existing != backup_id:
                raise BackupError(
                    ErrorCode.OPERATION_CONFLICT,
                    "Operation уже связана с другим backup_id",
                )
            record["result_backup_id"] = backup_id
            record["updated_at"] = utc_timestamp()
            return record

        return self._mutate_validated(operation_id, mutate)

    @staticmethod
    def _apply_transition(
        record: dict,
        status: str,
        *,
        stage: str | None,
        error: SafeError | dict | None,
        result_backup_id: str | None,
    ) -> dict:
        current = record.get("status")
        if current in TERMINAL_STATUSES:
            raise BackupError(ErrorCode.OPERATION_CONFLICT, "Терминальная операция неизменяема")
        if status not in _ALLOWED_TRANSITIONS.get(current, set()):
            raise BackupError(ErrorCode.OPERATION_CONFLICT, f"Недопустимый переход {current} -> {status}")
        if status == OperationStatus.CANCELLED.value and not record.get("cancellation", {}).get("allowed", True):
            raise BackupError(ErrorCode.RESTORE_CANCEL_FORBIDDEN, "После начала mutation отмена запрещена")
        now = utc_timestamp()
        record["status"] = status
        record["updated_at"] = now
        record["heartbeat_at"] = now
        if current == OperationStatus.QUEUED.value and status == OperationStatus.RUNNING.value:
            record["started_at"] = now
        if stage is not None:
            record["stage"] = stage
        if result_backup_id is not None:
            record["result_backup_id"] = result_backup_id
        if error is not None:
            record["error"] = error.to_dict() if isinstance(error, SafeError) else dict(error)
        if status in TERMINAL_STATUSES:
            record["finished_at"] = now
            if status == OperationStatus.COMPLETED.value:
                record.setdefault("progress", {})["percent"] = 100.0
        return record

    def transition(
        self,
        operation_id: str,
        status: str,
        *,
        stage: str | None = None,
        error: SafeError | dict | None = None,
        result_backup_id: str | None = None,
    ) -> dict:
        if status not in TERMINAL_STATUSES:
            return self._mutate_validated(
                operation_id,
                lambda record: self._apply_transition(
                    record,
                    status,
                    stage=stage,
                    error=error,
                    result_backup_id=result_backup_id,
                ),
            )

        with self.running.locked():
            with self.history.locked():
                source = self.running._record_path(operation_id)
                raw = self.running._read_path(source)
                if raw is None:
                    raise BackupError(ErrorCode.OPERATION_NOT_FOUND, "Операция backup не найдена")
                updated = self._validate(
                    self._apply_transition(
                        self._validate(raw),
                        status,
                        stage=stage,
                        error=error,
                        result_backup_id=result_backup_id,
                    )
                )
                atomic_write_json(source, updated)
                self._move_locked(source, self.history._record_path(operation_id))
                return updated

    def update_stage(self, operation_id: str, stage: str, *, heartbeat: bool = True) -> dict:
        def mutate(record: dict) -> dict:
            if record.get("status") in TERMINAL_STATUSES:
                raise BackupError(ErrorCode.OPERATION_CONFLICT, "Терминальная операция неизменяема")
            now = utc_timestamp()
            record["stage"] = str(stage)
            record["updated_at"] = now
            if heartbeat:
                record["heartbeat_at"] = now
            return record
        return self._mutate_validated(operation_id, mutate)

    def update_progress(self, operation_id: str, **values: Any) -> dict:
        def mutate(record: dict) -> dict:
            if record.get("status") in TERMINAL_STATUSES:
                raise BackupError(ErrorCode.OPERATION_CONFLICT, "Терминальная операция неизменяема")
            progress = dict(record.get("progress") or {})
            for key in ("processed_files", "processed_bytes", "archive_bytes"):
                if key in values:
                    value = int(values[key])
                    if value < int(progress.get(key) or 0):
                        raise BackupError(ErrorCode.OPERATION_CONFLICT, "Progress counters не могут уменьшаться")
                    progress[key] = value
            if "estimated_total_bytes" in values:
                estimate = values["estimated_total_bytes"]
                progress["estimated_total_bytes"] = None if estimate is None else max(0, int(estimate))
            if "percent" in values:
                percent = values["percent"]
                if percent is not None and not 0 <= float(percent) < 100:
                    raise BackupError(ErrorCode.OPERATION_CONFLICT, "До completed percent должен быть в диапазоне [0,100)")
                old = progress.get("percent")
                if old is not None and percent is not None and float(percent) < float(old):
                    raise BackupError(ErrorCode.OPERATION_CONFLICT, "Progress percent не может уменьшаться")
                progress["percent"] = None if percent is None else float(percent)
            now = utc_timestamp()
            record["progress"] = progress
            record["updated_at"] = now
            record["heartbeat_at"] = now
            return record
        return self._mutate_validated(operation_id, mutate)

    def request_cancel(self, operation_id: str) -> dict:
        def mutate(record: dict) -> dict:
            if record.get("status") in TERMINAL_STATUSES:
                raise BackupError(ErrorCode.OPERATION_CONFLICT, "Терминальная операция неизменяема")
            cancellation = dict(record.get("cancellation") or {})
            if not cancellation.get("allowed", True) or record.get("restore", {}).get("mutation_started"):
                raise BackupError(ErrorCode.RESTORE_CANCEL_FORBIDDEN, "После начала mutation отмена запрещена")
            cancellation.update({"requested": True, "requested_at": utc_timestamp()})
            record["cancellation"] = cancellation
            record["updated_at"] = utc_timestamp()
            return record
        return self._mutate_validated(operation_id, mutate)

    def add_warnings(self, operation_id: str, warnings) -> dict:
        """Добавить к Operation замечания, не отменяющие успех.

        Используются для нефатальной диагностики результата, например когда tar
        сообщает об изменившемся во время чтения файле. Warning — не ошибка: он не
        переводит операцию в failed и не мешает публикации, поэтому добавляется
        отдельно от ``transition``. Один и тот же ``(code, message)`` не
        накапливается: pipeline может увидеть одинаковое замечание несколько раз.

        Список замечаний терминальной операции неизменяем, как и всё остальное в
        ней: замечания записываются до перехода в completed.
        """
        prepared: list[dict] = []
        for warning in warnings or ():
            code = str((warning or {}).get("code") or "").strip()
            message = str((warning or {}).get("message") or "").strip()
            if not code or not message:
                raise BackupError(ErrorCode.INVALID_REQUEST, "Некорректный warning Operation")
            prepared.append({"code": code[:512], "message": message[:512]})
        if not prepared:
            return self.get(operation_id)

        def mutate(record: dict) -> dict:
            if record.get("status") in TERMINAL_STATUSES:
                raise BackupError(ErrorCode.OPERATION_CONFLICT, "Терминальная операция неизменяема")
            existing = list(record.get("warnings") or [])
            known = {(item.get("code"), item.get("message")) for item in existing}
            for warning in prepared:
                key = (warning["code"], warning["message"])
                if key in known:
                    continue
                known.add(key)
                existing.append(warning)
            now = utc_timestamp()
            record.update({"warnings": existing, "updated_at": now, "heartbeat_at": now})
            return record

        return self._mutate_validated(operation_id, mutate)

    def mark_restore_mutation_started(self, operation_id: str) -> dict:
        """Пересечь destructive boundary: дальше target изменяется.

        Проверка запрошенной отмены стоит здесь, а не у вызывающего: она обязана
        быть атомарной с постановкой признака мутации. Иначе ``request_cancel``
        успевал бы встать между проверкой и записью и остался бы «принятой
        отменой», которую применение уже не исполнит.
        """
        def mutate(record: dict) -> dict:
            if record.get("status") in TERMINAL_STATUSES:
                raise BackupError(ErrorCode.OPERATION_CONFLICT, "Терминальная операция неизменяема")
            if record.get("type") not in {"restore", "migrate"}:
                raise BackupError(ErrorCode.OPERATION_CONFLICT, "Mutation boundary применима только к restore/migrate")
            if record.get("cancellation", {}).get("requested"):
                raise BackupError(ErrorCode.CANCELLED_BY_USER, "Операция отменена пользователем")
            restore = dict(record.get("restore") or {})
            restore["mutation_started"] = True
            cancellation = dict(record.get("cancellation") or {})
            cancellation["allowed"] = False
            now = utc_timestamp()
            record.update({"stage": "applying", "restore": restore, "cancellation": cancellation, "updated_at": now, "heartbeat_at": now})
            return record
        return self._mutate_validated(operation_id, mutate)

    def attach_protective_backup(self, operation_id: str, backup_id: str) -> dict:
        """Связать restore с уже опубликованной защитной копией.

        Защитная копия — обычный backup; единственный след в Operation — этот
        идентификатор. Повторная привязка другого backup_id запрещена: иначе
        история операции указывала бы не на ту копию, из которой откатываются.
        """
        def mutate(record: dict) -> dict:
            if record.get("status") in TERMINAL_STATUSES:
                raise BackupError(ErrorCode.OPERATION_CONFLICT, "Терминальная операция неизменяема")
            if record.get("type") not in {"restore", "migrate"}:
                raise BackupError(ErrorCode.OPERATION_CONFLICT, "Защитная копия применима только к restore/migrate")
            restore = dict(record.get("restore") or {})
            existing = restore.get("protective_backup_id")
            if existing is not None and existing != backup_id:
                raise BackupError(ErrorCode.OPERATION_CONFLICT, "Operation уже связана с другой защитной копией")
            restore["protective_backup_id"] = backup_id
            now = utc_timestamp()
            record.update({"restore": restore, "updated_at": now, "heartbeat_at": now})
            return record
        return self._mutate_validated(operation_id, mutate)

    def attach_restore_plan(self, operation_id: str, plan: dict) -> dict:
        """Сохранить в Operation информационную сводку подготовленного плана.

        Единственный способ показать пользователю, что именно будет заменено и
        удалено: расчёт живёт в фоновом потоке подготовки и вместе с ним исчезает.
        Сводка ничего не разрешает — ``mutation_started`` она не меняет и
        признаком применения не является. Повторная привязка другой сводки к той
        же операции запрещена: план подготовки у операции один.
        """
        def mutate(record: dict) -> dict:
            if record.get("status") in TERMINAL_STATUSES:
                raise BackupError(ErrorCode.OPERATION_CONFLICT, "Терминальная операция неизменяема")
            if record.get("type") not in {"restore", "migrate"}:
                raise BackupError(ErrorCode.OPERATION_CONFLICT, "План восстановления применим только к restore/migrate")
            restore = dict(record.get("restore") or {})
            existing = restore.get("plan")
            if existing is not None and existing != plan:
                raise BackupError(ErrorCode.OPERATION_CONFLICT, "Operation уже связана с другим планом восстановления")
            restore["plan"] = plan
            now = utc_timestamp()
            record.update({"restore": restore, "updated_at": now, "heartbeat_at": now})
            return record
        return self._mutate_validated(operation_id, mutate)

    def attach_restore_selection(self, operation_id: str, selection: dict) -> dict:
        """Persist one immutable server-owned prepare/apply selection contract."""
        def mutate(record: dict) -> dict:
            if record.get("status") in TERMINAL_STATUSES:
                raise BackupError(
                    ErrorCode.OPERATION_CONFLICT,
                    "Терминальная операция неизменяема",
                )
            if record.get("type") not in {"restore", "migrate"}:
                raise BackupError(
                    ErrorCode.OPERATION_CONFLICT,
                    "Selection восстановления применим только к restore/migrate",
                )
            restore = dict(record.get("restore") or {})
            existing = restore.get("selection")
            if existing is not None and existing != selection:
                raise BackupError(
                    ErrorCode.OPERATION_CONFLICT,
                    "Operation уже связана с другим selection восстановления",
                )
            restore["selection"] = selection
            now = utc_timestamp()
            record.update({
                "restore": restore,
                "updated_at": now,
                "heartbeat_at": now,
            })
            return record

        return self._mutate_validated(operation_id, mutate)

    def attach_restore_metadata(self, operation_id: str, key: str, value) -> dict:
        """Persist one immutable, operation-local Restore projection.

        Facts are written before terminal transition.  Replaying the same update
        is idempotent; replacing a different value is rejected to avoid making
        an Operation describe two different extraction attempts.
        """
        allowed = {
            "preflight_conflicts",
            "skipped_members",
            "extraction",
            "verification",
            # Локальный self-restore: указатель на state.json раннера и каталог
            # его входов (member list, job). Записывается до запуска раннера,
            # значение детерминировано operation_id — replay идемпотентен.
            "self_restore",
        }
        if key not in allowed:
            raise BackupError(ErrorCode.INVALID_REQUEST, "Некорректный ключ Restore metadata")

        def mutate(record: dict) -> dict:
            if record.get("status") in TERMINAL_STATUSES:
                raise BackupError(ErrorCode.OPERATION_CONFLICT, "Терминальная операция неизменяема")
            if record.get("type") not in {"restore", "migrate"}:
                raise BackupError(ErrorCode.OPERATION_CONFLICT, "Restore metadata неприменима к Operation")
            restore = dict(record.get("restore") or {})
            existing = restore.get(key)
            if existing is not None and existing != value:
                raise BackupError(ErrorCode.OPERATION_CONFLICT, f"Restore metadata {key} уже сохранена")
            restore[key] = value
            now = utc_timestamp()
            record.update({"restore": restore, "updated_at": now, "heartbeat_at": now})
            return record

        return self._mutate_validated(operation_id, mutate)

    def complete_create_locked(
        self,
        operation_id: str,
        *,
        result_backup_id: str,
        stage: str = "completed",
    ) -> dict:
        """Finish create while the caller already holds ``running.lock``."""
        source = self.running._record_path(operation_id)
        current_raw = self.running._read_path(source)
        if current_raw is None:
            raise BackupError(ErrorCode.OPERATION_NOT_FOUND, "Операция backup не найдена")
        current = self._validate(current_raw)
        if current["status"] in TERMINAL_STATUSES:
            raise BackupError(ErrorCode.OPERATION_CONFLICT, "Терминальная операция неизменяема")
        if current.get("cancellation", {}).get("requested"):
            raise BackupError(ErrorCode.CANCELLED_BY_USER, "Backup отменён пользователем")
        if current["status"] not in {
            OperationStatus.RUNNING.value,
            OperationStatus.VERIFYING.value,
        }:
            raise BackupError(ErrorCode.OPERATION_CONFLICT, "Create Operation нельзя завершить из текущего состояния")
        updated = self._validate(
            self._apply_transition(
                current,
                OperationStatus.COMPLETED.value,
                stage=stage,
                error=None,
                result_backup_id=result_backup_id,
            )
        )
        with self.history.locked():
            atomic_write_json(source, updated)
            self._move_locked(source, self.history._record_path(operation_id))
        return updated

    def mark_abandoned(self, operation_id: str) -> dict:
        safe = BackupError(ErrorCode.OPERATION_ABANDONED, "Операция прервана перезапуском процесса", retryable=True).to_safe_error()
        current = self.get(operation_id)
        if current.get("status") in TERMINAL_STATUSES:
            return current
        return self.transition(operation_id, OperationStatus.FAILED.value, stage="crash_reconciliation", error=safe)
