from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from core.json_store import JsonDocumentStore

from .errors import BackupError, ErrorCode
from .ids import validate_id
from .inventory import build_archive_inventory
from .manifest import inspect_archive, verify_archive_with_members
from .models import ArtifactRef
from .time_utils import parse_utc_timestamp, utc_now, utc_timestamp
from .validation import validate_storage_key


INVENTORY_JOB_SCHEMA_VERSION = 2
INVENTORY_PRIORITY_BACKGROUND = 10
INVENTORY_PRIORITY_INTERACTIVE = 100
INVENTORY_JOB_RETRY_DELAYS = (30, 120, 600, 3600)
INVENTORY_JOB_MAX_ATTEMPTS = len(INVENTORY_JOB_RETRY_DELAYS) + 1
INVENTORY_JOB_TERMINAL_TTL_SECONDS = 7 * 24 * 60 * 60
INVENTORY_JOB_MAX_RECORDS = 1000
INVENTORY_INDEXER_POLL_SECONDS = 15.0

_ACTIVE_STATUSES = {"queued", "indexing", "retry_wait", "running"}
_DUE_STATUSES = {"queued", "retry_wait"}
_TERMINAL_STATUSES = {"completed", "failed", "obsolete"}
_JOB_STATUSES = _ACTIVE_STATUSES | _TERMINAL_STATUSES
_JOB_KEYS_V1 = {
    "schema_version",
    "job_id",
    "identity",
    "source",
    "archive",
    "status",
    "priority",
    "reason",
    "attempts",
    "next_attempt_at",
    "created_at",
    "updated_at",
    "started_at",
    "finished_at",
    "error",
    "result",
}
_JOB_KEYS = _JOB_KEYS_V1 | {"operation"}
_JOB_OPERATIONS = {"prepare", "rebuild"}
_TRANSIENT_ERROR_CODES = {
    ErrorCode.ARTIFACT_IN_USE.value,
    ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE.value,
    ErrorCode.CATALOG_CONFLICT.value,
    ErrorCode.LOCK_TIMEOUT.value,
    ErrorCode.STAGING_IO_FAILED.value,
    ErrorCode.STORAGE_BACKEND_ERROR.value,
}


class _ObsoleteInventoryJob(Exception):
    pass


class ArchiveInventoryIndexer:
    """Persist and execute background rebuilds of archive inventory sidecars.

    Jobs contain immutable artifact identity, never caller-supplied filesystem
    paths. The worker resolves every managed artifact through Catalog and Storage
    again while holding its artifact lock.
    """

    def __init__(
        self,
        data_root: str | Path,
        coordinator=None,
        *,
        catalog=None,
        storage=None,
        poll_seconds: float = INVENTORY_INDEXER_POLL_SECONDS,
    ) -> None:
        self.jobs = JsonDocumentStore(
            Path(data_root) / "inventory-index-jobs.json",
            name="BACKUP INVENTORY INDEXER",
        )
        self.coordinator = coordinator
        self.catalog = catalog
        self.storage = storage
        self.poll_seconds = max(0.05, float(poll_seconds))
        self._owner = None
        self._stop = asyncio.Event()
        self._loop_task: asyncio.Task | None = None

    @staticmethod
    def _validate_managed_source(source: object) -> dict:
        if not isinstance(source, dict) or source.get("kind") != "managed":
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Некорректный managed source inventory job",
            )
        backup_type = source.get("type")
        expected_keys = {
            "kind",
            "backup_id",
            "type",
            "artifact_version",
            "storage_key",
        }
        if backup_type == "server":
            expected_keys.add("server_id")
        if backup_type not in {"server", "bot4vps"} or set(source) != expected_keys:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Managed source inventory job не соответствует закрытой schema",
            )
        version = source.get("artifact_version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Некорректная artifact_version inventory job",
            )
        try:
            ArtifactRef.create(
                kind=backup_type,
                backup_id=source.get("backup_id"),
                server_id=source.get("server_id"),
            )
            validate_storage_key(source.get("storage_key"))
        except (TypeError, ValueError) as exc:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Некорректная managed identity inventory job",
            ) from exc
        return dict(source)

    @staticmethod
    def _validate_imported_source(source: object) -> dict:
        if not isinstance(source, dict) or source.get("kind") != "imported":
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Некорректный imported source inventory job",
            )
        destination = source.get("destination")
        if not isinstance(destination, dict):
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Некорректный imported destination inventory job",
            )
        scope = destination.get("scope")
        expected_destination = (
            {"scope", "server_id"} if scope == "server" else {"scope"}
        )
        if (
            set(source) != {"kind", "entry_key", "destination"}
            or scope not in {"server", "bot4vps"}
            or set(destination) != expected_destination
        ):
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Imported source inventory job не соответствует закрытой schema",
            )
        try:
            validate_id(source.get("entry_key"), field="inventory entry_key")
            if scope == "server":
                validate_id(
                    destination.get("server_id"),
                    field="inventory destination.server_id",
                )
        except (TypeError, ValueError) as exc:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Некорректная imported identity inventory job",
            ) from exc
        return {
            "kind": "imported",
            "entry_key": source["entry_key"],
            "destination": dict(destination),
        }

    @classmethod
    def _validate_source(cls, source: object) -> dict:
        if isinstance(source, dict) and source.get("kind") == "managed":
            return cls._validate_managed_source(source)
        if isinstance(source, dict) and source.get("kind") == "imported":
            return cls._validate_imported_source(source)
        raise BackupError(
            ErrorCode.INVALID_REQUEST,
            "Неизвестный source inventory job",
        )

    @staticmethod
    def _validate_archive(archive: object) -> dict:
        if not isinstance(archive, dict) or set(archive) != {
            "sha256",
            "bytes",
            "format",
        }:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Некорректная archive binding inventory job",
            )
        checksum = archive.get("sha256")
        size = archive.get("bytes")
        archive_format = archive.get("format")
        if (
            not isinstance(checksum, str)
            or len(checksum) != 64
            or any(char not in "0123456789abcdef" for char in checksum)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or archive_format not in {"tar", "tar.gz"}
        ):
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Некорректная archive binding inventory job",
            )
        return {
            "sha256": checksum,
            "bytes": size,
            "format": archive_format,
        }

    @classmethod
    def _validate_managed_archive(cls, archive: object) -> dict:
        archive = cls._validate_archive(archive)
        if archive["format"] != "tar.gz":
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Managed inventory job требует tar.gz archive",
            )
        return archive

    @staticmethod
    def _identity(source: dict) -> dict:
        if source.get("kind") == "imported":
            destination = source["destination"]
            return {
                "kind": "imported",
                "entry_key": source["entry_key"],
                "server_id": (
                    destination.get("server_id")
                    if destination.get("scope") == "server"
                    else None
                ),
            }
        return {
            "kind": "managed",
            "backup_id": source["backup_id"],
            "type": source["type"],
            "server_id": source.get("server_id"),
            "artifact_version": source["artifact_version"],
        }

    @staticmethod
    def _timestamp_or_max(value: object) -> datetime:
        try:
            return parse_utc_timestamp(value)
        except (TypeError, ValueError):
            return datetime.max.replace(tzinfo=utc_now().tzinfo)

    @staticmethod
    def _timestamp_or_min(value: object) -> datetime:
        try:
            return parse_utc_timestamp(value)
        except (TypeError, ValueError):
            return datetime.min.replace(tzinfo=utc_now().tzinfo)

    @classmethod
    def _normalize_persisted_job(cls, row: object) -> dict | None:
        """Validate one durable row and normalize the closed v1 schema to v2."""
        if not isinstance(row, dict):
            return None
        schema_version = row.get("schema_version")
        if schema_version == 1 and set(row) == _JOB_KEYS_V1:
            candidate = dict(row)
            candidate["schema_version"] = INVENTORY_JOB_SCHEMA_VERSION
            candidate["operation"] = "prepare"
        elif schema_version == INVENTORY_JOB_SCHEMA_VERSION and set(row) == _JOB_KEYS:
            candidate = dict(row)
        else:
            return None

        priority = candidate.get("priority")
        attempts = candidate.get("attempts")
        job_id = candidate.get("job_id")
        if (
            not isinstance(job_id, str)
            or not job_id.startswith("inv-")
            or len(job_id) != 36
            or any(char not in "0123456789abcdef" for char in job_id[4:])
            or candidate.get("status") not in _JOB_STATUSES
            or candidate.get("operation") not in _JOB_OPERATIONS
            or not isinstance(priority, int)
            or isinstance(priority, bool)
            or not INVENTORY_PRIORITY_BACKGROUND <= priority <= 1000
            or not isinstance(attempts, int)
            or isinstance(attempts, bool)
            or attempts < 0
            or not isinstance(candidate.get("reason"), str)
            or not candidate["reason"]
            or len(candidate["reason"]) > 128
        ):
            return None
        try:
            source = cls._validate_source(candidate.get("source"))
            archive = (
                cls._validate_managed_archive(candidate.get("archive"))
                if source.get("kind") == "managed"
                else cls._validate_archive(candidate.get("archive"))
            )
            if candidate.get("identity") != cls._identity(source):
                return None
            for field in ("created_at", "updated_at"):
                parse_utc_timestamp(candidate.get(field))
            for field in ("next_attempt_at", "started_at", "finished_at"):
                value = candidate.get(field)
                if value is not None:
                    parse_utc_timestamp(value)
        except (BackupError, TypeError, ValueError):
            return None
        error = candidate.get("error")
        if error is not None and (
            not isinstance(error, dict)
            or set(error) != {"code", "message"}
            or not isinstance(error.get("code"), str)
            or not error["code"]
            or not isinstance(error.get("message"), str)
            or not error["message"]
        ):
            return None
        result = candidate.get("result")
        if result is not None and result not in {
            "already_valid",
            "compatibility_only",
            "migrated",
            "rebuilt",
            "explicit_rebuild",
        }:
            return None
        return candidate if archive == candidate["archive"] else None

    @classmethod
    def _valid_persisted_job(cls, row: object) -> bool:
        """Reject malformed durable rows before they can wedge queue dispatch."""
        return cls._normalize_persisted_job(row) is not None

    @classmethod
    def _sanitize_rows(cls, rows: list[dict]) -> list[dict]:
        sanitized = []
        seen_ids = set()
        for row in rows:
            normalized = cls._normalize_persisted_job(row)
            if normalized is None:
                continue
            job_id = normalized["job_id"]
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            sanitized.append(normalized)
        return sanitized

    def _prune(self, rows: list[dict], *, now: datetime) -> list[dict]:
        rows = self._sanitize_rows(rows)
        cutoff = now - timedelta(seconds=INVENTORY_JOB_TERMINAL_TTL_SECONDS)
        retained = [
            row
            for row in rows
            if row.get("status") not in _TERMINAL_STATUSES
            or self._timestamp_or_max(row.get("finished_at")) >= cutoff
        ]
        if len(retained) <= INVENTORY_JOB_MAX_RECORDS:
            return retained
        terminal = sorted(
            (
                row
                for row in retained
                if row.get("status") in _TERMINAL_STATUSES
            ),
            key=lambda row: self._timestamp_or_min(row.get("finished_at")),
        )
        remove_ids = {
            row.get("job_id")
            for row in terminal[: len(retained) - INVENTORY_JOB_MAX_RECORDS]
        }
        return [row for row in retained if row.get("job_id") not in remove_ids]

    def enqueue_managed(
        self,
        *,
        source: dict,
        archive: dict,
        reason: str,
        priority: int = INVENTORY_PRIORITY_BACKGROUND,
        retry: bool = False,
        rebuild: bool = False,
    ) -> dict:
        source = self._validate_managed_source(source)
        archive = self._validate_managed_archive(archive)
        return self._enqueue(
            source=source,
            archive=archive,
            reason=reason,
            priority=priority,
            retry=retry,
            rebuild=rebuild,
        )

    def enqueue_imported(
        self,
        *,
        source: dict,
        archive: dict,
        reason: str,
        priority: int = INVENTORY_PRIORITY_BACKGROUND,
        retry: bool = False,
        rebuild: bool = False,
    ) -> dict:
        source = self._validate_imported_source(source)
        return self._enqueue(
            source=source,
            archive=archive,
            reason=reason,
            priority=priority,
            retry=retry,
            rebuild=rebuild,
        )

    def _enqueue(
        self,
        *,
        source: dict,
        archive: dict,
        reason: str,
        priority: int = INVENTORY_PRIORITY_BACKGROUND,
        retry: bool = False,
        rebuild: bool = False,
    ) -> dict:
        source = self._validate_source(source)
        archive = self._validate_archive(archive)
        reason = str(reason or "inventory_unavailable").strip()[:128]
        if not reason or any(ord(char) < 32 or ord(char) == 127 for char in reason):
            reason = "inventory_unavailable"
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Некорректный priority inventory job",
            )
        if not isinstance(retry, bool):
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Некорректный retry inventory job",
            )
        if not isinstance(rebuild, bool):
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Некорректный rebuild inventory job",
            )
        if retry and rebuild:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Retry и rebuild inventory job несовместимы",
            )
        priority = max(INVENTORY_PRIORITY_BACKGROUND, min(priority, 1000))
        now_value = utc_now()
        now = utc_timestamp(now_value)
        identity = self._identity(source)
        operation = "rebuild" if rebuild else "prepare"
        value = {
            "schema_version": INVENTORY_JOB_SCHEMA_VERSION,
            "job_id": f"inv-{uuid4().hex}",
            "identity": identity,
            "source": source,
            "archive": archive,
            "operation": operation,
            "status": "queued",
            "priority": priority,
            "reason": reason,
            "attempts": 0,
            "next_attempt_at": now,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
            "error": None,
            "result": None,
        }
        selected = None

        def update_active(candidate: dict, index: int, rows: list[dict]) -> list[dict]:
            nonlocal selected
            selected = dict(candidate)
            status = candidate.get("status")
            make_due = status == "retry_wait" and (retry or rebuild)
            if int(candidate.get("priority") or 0) < priority or make_due:
                selected["priority"] = max(
                    int(candidate.get("priority") or 0),
                    priority,
                )
                selected["reason"] = reason
                selected["updated_at"] = now
                if make_due:
                    selected["next_attempt_at"] = now
                rows[index] = selected
            return rows

        def revive(candidate: dict, index: int, rows: list[dict]) -> list[dict]:
            nonlocal selected
            selected = dict(candidate)
            selected.update({
                "status": "queued",
                "priority": priority,
                "reason": reason,
                "attempts": 0,
                "next_attempt_at": now,
                "updated_at": now,
                "started_at": None,
                "finished_at": None,
                "error": None,
                "result": None,
            })
            rows[index] = selected
            return rows

        def mutate(rows: list[dict]) -> list[dict]:
            nonlocal selected
            rows = self._prune(rows, now=now_value)
            matching = [
                (index, candidate)
                for index, candidate in enumerate(rows)
                if candidate.get("identity") == identity
                and candidate.get("archive") == archive
            ]

            # One active rebuild owns all equivalent explicit requests. An
            # ordinary prepare can also wait on it because rebuild is a strict
            # superset of preparation.
            for index, candidate in matching:
                if (
                    candidate.get("status") in _ACTIVE_STATUSES
                    and candidate.get("operation") == "rebuild"
                ):
                    return update_active(candidate, index, rows)

            if rebuild:
                # A never-started prepare can be promoted without losing work.
                # Once execution began, retain it and queue a separately
                # watchable rebuild behind it.
                for index, candidate in matching:
                    if (
                        candidate.get("status") == "queued"
                        and candidate.get("operation") == "prepare"
                        and int(candidate.get("attempts") or 0) == 0
                    ):
                        selected = dict(candidate)
                        selected.update({
                            "operation": "rebuild",
                            "priority": max(
                                int(candidate.get("priority") or 0),
                                priority,
                            ),
                            "reason": reason,
                            "updated_at": now,
                        })
                        rows[index] = selected
                        return rows
            else:
                for index, candidate in matching:
                    if candidate.get("status") in _ACTIVE_STATUSES:
                        return update_active(candidate, index, rows)

            if not rebuild:
                for _index, candidate in matching:
                    if (
                        candidate.get("status") == "completed"
                        and candidate.get("result") == "compatibility_only"
                    ):
                        selected = dict(candidate)
                        return rows

            # Retry revives only the same operation. A new explicit rebuild
            # also revives its prior failed durable row without requiring the
            # unrelated normal-retry flag.
            for index, candidate in reversed(matching):
                if candidate.get("status") != "failed":
                    continue
                same_operation = candidate.get("operation") == operation
                if same_operation and (retry or rebuild):
                    return revive(candidate, index, rows)
                if same_operation:
                    selected = dict(candidate)
                    return rows

            selected = value
            rows.append(value)
            return rows

        self.jobs.mutate(mutate)
        return dict(selected)

    def get_job_by_id(self, job_id: str) -> dict | None:
        """Return one durable job by its opaque ID without exposing neighbors."""
        if (
            not isinstance(job_id, str)
            or not job_id.startswith("inv-")
            or len(job_id) != 36
            or any(char not in "0123456789abcdef" for char in job_id[4:])
        ):
            return None
        rows = self.list_jobs()
        selected = next(
            (row for row in rows if row.get("job_id") == job_id),
            None,
        )
        if selected is None:
            return None
        result = dict(selected)
        if selected.get("status") in {"queued", "retry_wait"}:
            queued = [
                row
                for row in rows
                if row.get("status") in {"queued", "retry_wait"}
            ]
            queued.sort(key=lambda row: (
                -int(row.get("priority") or 0),
                self._timestamp_or_max(row.get("next_attempt_at")),
                self._timestamp_or_max(row.get("created_at")),
                str(row.get("job_id") or ""),
            ))
            result["position"] = next(
                (
                    index
                    for index, row in enumerate(queued, start=1)
                    if row.get("job_id") == job_id
                ),
                None,
            )
        return result

    def list_jobs(self) -> list[dict]:
        return self._sanitize_rows(self.jobs.read())

    def get_job(self, *, source: dict, archive: dict) -> dict | None:
        """Return the current durable job for one immutable artifact binding."""
        source = self._validate_source(source)
        archive = (
            self._validate_managed_archive(archive)
            if source.get("kind") == "managed"
            else self._validate_archive(archive)
        )
        identity = self._identity(source)
        matches = [
            row
            for row in self.list_jobs()
            if row.get("identity") == identity and row.get("archive") == archive
        ]
        if not matches:
            return None
        active = [row for row in matches if row.get("status") in _ACTIVE_STATUSES]
        candidates = active or matches
        selected = max(
            candidates,
            key=lambda row: (
                self._timestamp_or_min(row.get("updated_at")),
                str(row.get("job_id") or ""),
            ),
        )
        result = dict(selected)
        if selected.get("status") in {"queued", "retry_wait"}:
            queued = [
                row
                for row in self.list_jobs()
                if row.get("status") in {"queued", "retry_wait"}
            ]
            queued.sort(key=lambda row: (
                -int(row.get("priority") or 0),
                self._timestamp_or_max(row.get("next_attempt_at")),
                self._timestamp_or_max(row.get("created_at")),
                str(row.get("job_id") or ""),
            ))
            result["position"] = next(
                (
                    index
                    for index, row in enumerate(queued, start=1)
                    if row.get("job_id") == selected.get("job_id")
                ),
                None,
            )
        return result

    def recover_interrupted(self) -> int:
        """Return abandoned in-progress jobs to the durable due queue."""
        recovered = 0
        now = utc_timestamp()

        def mutate(rows: list[dict]) -> list[dict]:
            nonlocal recovered
            rows = self._sanitize_rows(rows)
            updated = []
            for row in rows:
                if row.get("status") not in {"indexing", "running"}:
                    updated.append(row)
                    continue
                changed = dict(row)
                changed.update({
                    "status": "retry_wait",
                    "next_attempt_at": now,
                    "updated_at": now,
                    "started_at": None,
                    "error": {
                        "code": "INDEXER_INTERRUPTED",
                        "message": "Построение inventory было прервано и будет повторено",
                    },
                })
                updated.append(changed)
                recovered += 1
            return updated

        self.jobs.mutate(mutate)
        return recovered

    def claim_next(self, *, now: datetime | None = None) -> dict | None:
        """Atomically claim the highest-priority due job."""
        now_value = now or utc_now()
        now_text = utc_timestamp(now_value)
        selected_id = None
        claimed = None

        def mutate(rows: list[dict]) -> list[dict]:
            nonlocal selected_id, claimed
            rows = self._sanitize_rows(rows)
            due = [
                row
                for row in rows
                if row.get("status") in _DUE_STATUSES
                and self._timestamp_or_max(row.get("next_attempt_at")) <= now_value
            ]
            if not due:
                return self._prune(rows, now=now_value)
            selected = min(
                due,
                key=lambda row: (
                    -int(row.get("priority") or 0),
                    self._timestamp_or_max(row.get("next_attempt_at")),
                    self._timestamp_or_max(row.get("created_at")),
                    str(row.get("job_id") or ""),
                ),
            )
            selected_id = selected.get("job_id")
            updated = []
            for row in rows:
                if row.get("job_id") != selected_id:
                    updated.append(row)
                    continue
                changed = dict(row)
                changed.update({
                    "status": "indexing",
                    "attempts": int(row.get("attempts") or 0) + 1,
                    "started_at": now_text,
                    "updated_at": now_text,
                    "next_attempt_at": None,
                    "error": None,
                })
                claimed = changed
                updated.append(changed)
            return updated

        self.jobs.mutate(mutate)
        return dict(claimed) if claimed is not None else None

    def _set_terminal(
        self,
        job: dict,
        status: str,
        *,
        now: datetime,
        result: str | None = None,
        error: dict | None = None,
    ) -> None:
        now_text = utc_timestamp(now)

        def mutate(rows: list[dict]) -> list[dict]:
            updated = []
            for row in rows:
                if row.get("job_id") != job.get("job_id"):
                    updated.append(row)
                    continue
                changed = dict(row)
                changed.update({
                    "status": status,
                    "updated_at": now_text,
                    "finished_at": now_text,
                    "next_attempt_at": None,
                    "result": result,
                    "error": error,
                })
                updated.append(changed)
            return self._prune(updated, now=now)

        self.jobs.mutate(mutate)

    @staticmethod
    def _safe_error(exc: Exception) -> dict:
        if isinstance(exc, BackupError):
            return {
                "code": exc.code,
                "message": exc.safe_message,
            }
        return {
            "code": "INVENTORY_INDEX_FAILED",
            "message": "Не удалось построить archive inventory",
        }

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        if isinstance(exc, BackupError):
            return exc.retryable or exc.code in _TRANSIENT_ERROR_CODES
        return isinstance(exc, OSError)

    def _set_failure(self, job: dict, exc: Exception, *, now: datetime) -> None:
        attempts = int(job.get("attempts") or 0)
        if not self._retryable(exc) or attempts >= INVENTORY_JOB_MAX_ATTEMPTS:
            self._set_terminal(
                job,
                "failed",
                now=now,
                error=self._safe_error(exc),
            )
            return
        delay = INVENTORY_JOB_RETRY_DELAYS[min(
            attempts - 1,
            len(INVENTORY_JOB_RETRY_DELAYS) - 1,
        )]
        now_text = utc_timestamp(now)
        retry_at = utc_timestamp(now + timedelta(seconds=delay))
        safe_error = self._safe_error(exc)

        def mutate(rows: list[dict]) -> list[dict]:
            rows = self._sanitize_rows(rows)
            updated = []
            for row in rows:
                if row.get("job_id") != job.get("job_id"):
                    updated.append(row)
                    continue
                changed = dict(row)
                changed.update({
                    "status": "retry_wait",
                    "updated_at": now_text,
                    "started_at": None,
                    "next_attempt_at": retry_at,
                    "error": safe_error,
                })
                updated.append(changed)
            return updated

        self.jobs.mutate(mutate)

    def _require_worker_dependencies(self) -> None:
        if self.coordinator is None or self.catalog is None or self.storage is None:
            raise RuntimeError("ArchiveInventoryIndexer worker dependencies are unavailable")

    def _current_managed_binding(self, record: dict) -> tuple[dict, dict]:
        backup_type = record.get("type")
        source_record = record.get("source")
        server_id = (
            source_record.get("server_id")
            if backup_type == "server" and isinstance(source_record, dict)
            else None
        )
        storage_key, checksum_key = self.storage.canonical_keys(
            record.get("backup_id"),
            backup_type,
            server_id,
        )
        storage_record = record.get("storage")
        archive_record = record.get("archive")
        if (
            not isinstance(storage_record, dict)
            or storage_record.get("key") != storage_key
            or storage_record.get("checksum_key") != checksum_key
            or not isinstance(archive_record, dict)
        ):
            raise _ObsoleteInventoryJob()
        source = {
            "kind": "managed",
            "backup_id": record["backup_id"],
            "type": backup_type,
            "artifact_version": record.get("artifact_version"),
            "storage_key": storage_key,
        }
        if backup_type == "server":
            source["server_id"] = server_id
        archive = {
            "sha256": archive_record.get("checksum"),
            "bytes": archive_record.get("bytes"),
            "format": archive_record.get("format"),
        }
        return (
            self._validate_managed_source(source),
            self._validate_managed_archive(archive),
        )

    def _build_managed_inventory(
        self,
        *,
        archive_path: Path,
        source: dict,
        archive: dict,
    ) -> Path:
        actual_checksum = self.storage.calculate_checksum(archive_path)
        if actual_checksum != archive["sha256"]:
            raise BackupError(
                ErrorCode.CHECKSUM_MISMATCH,
                "Checksum опубликованного archive не совпадает с Catalog",
            )
        inspection = verify_archive_with_members(
            archive_path,
            expected_backup_id=source["backup_id"],
            expected_type=source["type"],
        )
        members = inspection.pop("members")
        staging_id = f"inv-{uuid4().hex}"
        try:
            inventory = build_archive_inventory(
                members=members,
                manifest=inspection["manifest"],
                source=source,
                archive=archive,
                consume_members=True,
            )
            self.storage.create_staging(staging_id, "create")
            staging_archive = self.storage.staging_archive_path(
                staging_id,
                source["backup_id"],
                "create",
            )
            return self.storage.write_archive_inventory_staging(
                staging_archive,
                inventory,
            )
        except Exception:
            self.storage.remove_staging(staging_id, "create")
            raise
        finally:
            members.clear()

    def _execute_managed(self, job: dict) -> str:
        self._require_worker_dependencies()
        source = self._validate_managed_source(job.get("source"))
        archive = self._validate_managed_archive(job.get("archive"))
        rebuild = job.get("operation") == "rebuild"
        ref = ArtifactRef.create(
            kind=source["type"],
            backup_id=source["backup_id"],
            server_id=source.get("server_id"),
        )
        try:
            permit = self.coordinator.acquire_artifact_publish(ref)
        except BackupError:
            raise
        with permit:
            try:
                record = self.catalog.get(ref)
            except BackupError as exc:
                if exc.code == ErrorCode.ARTIFACT_NOT_FOUND.value:
                    raise _ObsoleteInventoryJob() from exc
                raise
            current_source, current_archive = self._current_managed_binding(record)
            if current_source != source or current_archive != archive:
                raise _ObsoleteInventoryJob()
            if record.get("retention", {}).get("claim") is not None:
                raise BackupError(
                    ErrorCode.ARTIFACT_IN_USE,
                    "Backup занят destructive operation",
                    retryable=True,
                )
            archive_path = self.storage.resolve_key(record["storage"]["key"])
            checksum_path = self.storage.resolve_key(
                record["storage"]["checksum_key"]
            )
            if (
                not rebuild
                and self.storage.read_managed_archive_inventory(
                    archive_path,
                    checksum_path,
                    expected_source=source,
                    expected_archive=archive,
                ) is not None
            ):
                return "already_valid"

            if record.get("archive", {}).get("encrypted"):
                # Sidecar inventory зашифрованного архива строится из plaintext
                # при создании. Переинвентаризировать B4VE без пароля нельзя:
                # чистый финальный отказ вместо попытки открыть шифротекст как TAR.
                raise BackupError(
                    ErrorCode.ARCHIVE_INVALID,
                    "Зашифрованный archive inventory недоступен без пароля "
                    "резервных копий",
                )

            staging_inventory = self._build_managed_inventory(
                archive_path=archive_path,
                source=source,
                archive=archive,
            )
            try:
                installed = self.storage.install_managed_archive_inventory(
                    staging_inventory,
                    archive_path,
                    checksum_path,
                    expected_source=source,
                    expected_archive=archive,
                    replace_existing=rebuild,
                )
                if installed:
                    return "explicit_rebuild" if rebuild else "rebuilt"
                if (
                    not rebuild
                    and self.storage.read_managed_archive_inventory(
                        archive_path,
                        checksum_path,
                        expected_source=source,
                        expected_archive=archive,
                    ) is not None
                ):
                    return "already_valid"
                raise BackupError(
                    ErrorCode.STORAGE_BACKEND_ERROR,
                    "Не удалось установить archive inventory",
                    retryable=True,
                )
            finally:
                self.storage.remove_staging(
                    staging_inventory.parent.name,
                    "create",
                )

    @staticmethod
    def _import_server_id(source: dict) -> str | None:
        destination = source["destination"]
        return (
            destination.get("server_id")
            if destination.get("scope") == "server"
            else None
        )

    def _install_imported_inventory(
        self,
        *,
        resolved: dict,
        inventory: dict,
        replace_existing: bool = False,
    ) -> bool:
        installed = self.storage.write_import_archive_inventory(
            resolved,
            inventory,
            verify_archive_checksum=False,
            replace_existing=replace_existing,
        )
        if installed:
            return True
        if (
            not replace_existing
            and self.storage.read_import_archive_inventory(resolved) is not None
        ):
            return False
        raise BackupError(
            ErrorCode.STORAGE_BACKEND_ERROR,
            "Не удалось установить archive inventory import bundle",
            retryable=True,
        )

    def _execute_imported(self, job: dict) -> str:
        self._require_worker_dependencies()
        source = self._validate_imported_source(job.get("source"))
        archive = self._validate_archive(job.get("archive"))
        rebuild = job.get("operation") == "rebuild"
        entry_key = source["entry_key"]
        server_id = self._import_server_id(source)
        with self.coordinator.acquire_import_publish(
            entry_key,
            server_id=server_id,
        ):
            try:
                resolved = self.storage.resolve_import_bundle(
                    entry_key,
                    server_id=server_id,
                )
            except BackupError as exc:
                if exc.code == ErrorCode.ARTIFACT_NOT_FOUND.value:
                    raise _ObsoleteInventoryJob() from exc
                raise

            current_source, current_archive = self.storage.import_inventory_bindings(
                resolved
            )
            try:
                current_source = self._validate_imported_source(current_source)
                current_archive = self._validate_archive(current_archive)
            except BackupError as exc:
                raise _ObsoleteInventoryJob() from exc
            if current_source != source or current_archive != archive:
                raise _ObsoleteInventoryJob()

            if (
                not rebuild
                and self.storage.read_import_archive_inventory(resolved) is not None
            ):
                return "already_valid"

            if resolved["publication"].get("encrypted"):
                # Зашифрованный импорт публикуется без инвентаризации:
                # состав файлов читается только при Restore с паролем.
                raise BackupError(
                    ErrorCode.ARCHIVE_INVALID,
                    "Импортированный зашифрованный архив: состав файлов "
                    "недоступен без пароля резервных копий",
                )

            legacy = (
                self.storage.read_legacy_import_archive_inventory(resolved)
                if not rebuild
                else None
            )
            if legacy is not None:
                members = legacy["members"]
                try:
                    try:
                        inventory = build_archive_inventory(
                            members=members,
                            manifest=legacy["manifest"],
                            source=source,
                            archive=archive,
                            consume_members=True,
                        )
                    except BackupError:
                        # A strict v1 can describe a readable archive that is not
                        # safe/indexable. Keep that published compatibility state
                        # without paying for a TAR pass that would produce the same
                        # member graph.
                        return "compatibility_only"
                    installed = self._install_imported_inventory(
                        resolved=resolved,
                        inventory=inventory,
                    )
                    return "migrated" if installed else "already_valid"
                finally:
                    members.clear()

            archive_path = Path(resolved["archive"])
            actual_checksum = self.storage.calculate_checksum(archive_path)
            if actual_checksum != archive["sha256"]:
                raise BackupError(
                    ErrorCode.CHECKSUM_MISMATCH,
                    "Checksum import archive не соответствует publication",
                )
            inspection = inspect_archive(archive_path)
            members = inspection.pop("members")
            try:
                try:
                    inventory = build_archive_inventory(
                        members=members,
                        manifest=inspection.get("manifest"),
                        source=source,
                        archive=archive,
                        consume_members=True,
                    )
                except BackupError:
                    # Ordinary imports intentionally remain publishable even when
                    # their physical member graph cannot become a lazy v2 index.
                    return "compatibility_only"
                installed = self._install_imported_inventory(
                    resolved=resolved,
                    inventory=inventory,
                    replace_existing=rebuild,
                )
                if rebuild:
                    return "explicit_rebuild"
                return "rebuilt" if installed else "already_valid"
            finally:
                members.clear()

    def execute_claimed(
        self,
        job: dict,
        *,
        now: datetime | None = None,
    ) -> str:
        """Execute one already claimed job and persist its final/retry state."""
        now_value = now or utc_now()
        try:
            kind = job.get("identity", {}).get("kind")
            if kind == "managed":
                result = self._execute_managed(job)
            elif kind == "imported":
                result = self._execute_imported(job)
            else:
                raise _ObsoleteInventoryJob()
        except _ObsoleteInventoryJob:
            self._set_terminal(job, "obsolete", now=now_value)
            return "obsolete"
        except Exception as exc:
            self._set_failure(job, exc, now=now_value)
            return "failed"
        self._set_terminal(
            job,
            "completed",
            now=now_value,
            result=result,
        )
        return result

    def run_pending(
        self,
        *,
        max_jobs: int = 1,
        now: datetime | None = None,
    ) -> int:
        """Synchronously execute up to ``max_jobs`` due jobs."""
        self._require_worker_dependencies()
        if not isinstance(max_jobs, int) or isinstance(max_jobs, bool) or max_jobs < 1:
            raise ValueError("max_jobs должен быть integer >= 1")
        processed = 0
        for _ in range(max_jobs):
            job = self.claim_next(now=now)
            if job is None:
                break
            self.execute_claimed(job, now=now)
            processed += 1
        return processed

    async def start(self) -> None:
        self._require_worker_dependencies()
        if self._loop_task is not None and not self._loop_task.done():
            return
        if self._owner is None:
            owner = await asyncio.to_thread(
                self.coordinator.try_acquire_operation_owner,
                "inventory-indexer",
            )
            if owner is None:
                print(
                    "[BACKUP INVENTORY] другой процесс уже владеет indexer lock",
                    flush=True,
                )
                return
            self._owner = owner
        self._stop.clear()
        try:
            await asyncio.to_thread(self.recover_interrupted)
            self._loop_task = asyncio.create_task(
                self._run_loop(),
                name="backup-inventory-indexer",
            )
        except Exception:
            self._owner.release()
            self._owner = None
            raise

    async def stop(self) -> None:
        self._stop.set()
        try:
            task = self._loop_task
            if task is not None:
                await task
            self._loop_task = None
        finally:
            if self._owner is not None:
                self._owner.release()
                self._owner = None

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                processed = await asyncio.to_thread(self.run_pending)
            except Exception as exc:
                print(
                    "[BACKUP INVENTORY] цикл indexer завершился с ошибкой: "
                    f"{type(exc).__name__}",
                    flush=True,
                )
                processed = 0
            if processed:
                continue
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self.poll_seconds,
                )
            except asyncio.TimeoutError:
                pass


_indexer: ArchiveInventoryIndexer | None = None


async def start_archive_inventory_indexer() -> ArchiveInventoryIndexer:
    global _indexer
    if _indexer is None:
        from core.config import get_backup_config

        from .manager import BackupManager

        _indexer = BackupManager(get_backup_config()).inventory_indexer
    await _indexer.start()
    return _indexer


async def stop_archive_inventory_indexer() -> None:
    global _indexer
    indexer = _indexer
    _indexer = None
    if indexer is not None:
        await indexer.stop()
