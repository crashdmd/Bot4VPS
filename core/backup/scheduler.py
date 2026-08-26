from __future__ import annotations

import asyncio
from datetime import datetime, time as wall_time, timezone
from pathlib import Path

from core.config import get_backup_config
from core.install_paths import get_backup_data_path
from core.json_store import JsonDocumentStore
from core.storage import load_servers

from .locks import LockCoordinator
from .manager import BackupManager
from .models import OperationStatus, TERMINAL_STATUSES
from .time_utils import local_timezone, utc_now, utc_timestamp
from .validation import normalize_server_profile


_POLL_SECONDS = 30.0
_STATE_FILENAME = "automatic_state.json"


class AutomaticBackupScheduler:
    """Dispatch the saved daily backup schedules exactly once per occurrence."""

    def __init__(self, *, data_root: str | Path | None = None, poll_seconds: float = _POLL_SECONDS):
        self.data_root = Path(data_root or get_backup_data_path())
        self.state = JsonDocumentStore(
            self.data_root / _STATE_FILENAME,
            name="BACKUP AUTOMATIC SCHEDULER",
        )
        self.poll_seconds = max(1.0, float(poll_seconds))
        self.coordinator = LockCoordinator(data_root=self.data_root)
        self._scheduler_owner = None
        self._stop = asyncio.Event()
        self._loop_task: asyncio.Task | None = None
        self._workers: set[asyncio.Task] = set()
        self._run_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._loop_task is not None and not self._loop_task.done():
            return
        if self._scheduler_owner is None:
            owner = await asyncio.to_thread(
                self.coordinator.try_acquire_operation_owner,
                "automatic-scheduler",
            )
            if owner is None:
                print(
                    "[BACKUP SCHEDULER] другой процесс уже владеет scheduler lock",
                    flush=True,
                )
                return
            self._scheduler_owner = owner
        self._stop.clear()
        try:
            # Reconciliation owns abandoned Operation recovery and must complete
            # before an automatic occurrence is allowed to dispatch.
            await asyncio.to_thread(self._reconcile)
            await self._recover_interrupted_occurrences()
            self._loop_task = asyncio.create_task(
                self._run_loop(),
                name="backup-automatic-scheduler",
            )
        except Exception:
            self._scheduler_owner.release()
            self._scheduler_owner = None
            raise

    async def stop(self) -> None:
        self._stop.set()
        try:
            task = self._loop_task
            if task is not None:
                await task
            self._loop_task = None
            if self._workers:
                await asyncio.gather(*tuple(self._workers), return_exceptions=True)
        finally:
            if self._scheduler_owner is not None:
                self._scheduler_owner.release()
                self._scheduler_owner = None

    def _reconcile(self) -> None:
        BackupManager(get_backup_config(), data_root=self.data_root).reconcile_startup()

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._dispatch_due_occurrences()
            except Exception as exc:
                print(
                    f"[BACKUP SCHEDULER] цикл проверки завершился с ошибкой: {type(exc).__name__}",
                    flush=True,
                )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass

    @staticmethod
    def _jobs() -> list[dict]:
        config = get_backup_config()
        jobs: list[dict] = []
        automatic = config["bot4vps"]["automatic"]
        if automatic["enabled"]:
            jobs.append({
                "job_key": "bot4vps",
                "target": {"kind": "bot4vps"},
                "scope": "bot4vps",
                "daily_time": automatic["daily_time"],
                "timezone": automatic["timezone"],
                "keep_last": automatic["keep_last"],
            })

        for server in load_servers():
            server_id = server.get("id") if isinstance(server, dict) else None
            raw_profile = server.get("backup") if isinstance(server, dict) else None
            if not isinstance(server_id, str) or not isinstance(raw_profile, dict):
                continue
            try:
                profile = normalize_server_profile(raw_profile)
            except Exception:
                # Invalid profiles are rejected by the settings boundary. A
                # damaged legacy entry must not stop valid schedules.
                continue
            automatic = profile["automatic"]
            if not automatic["enabled"] or not profile["sources"]:
                continue
            jobs.append({
                "job_key": f"server:{server_id}",
                "target": {"kind": "server", "server_id": server_id},
                "scope": f"server:{server_id}",
                "daily_time": automatic["daily_time"],
                "timezone": automatic["timezone"],
                "keep_last": automatic["keep_last"],
            })
        return jobs

    @staticmethod
    def _due_occurrence(job: dict, now: datetime, zone=None) -> str | None:
        zone = zone or local_timezone()
        local_now = now.astimezone(zone)
        hour, minute = (int(part) for part in job["daily_time"].split(":", 1))
        candidate = datetime.combine(
            local_now.date(),
            wall_time(hour=hour, minute=minute),
            tzinfo=zone,
        )
        # A spring-forward wall time may not exist. UTC round-tripping maps it
        # to the first real instant represented by that configured wall time.
        normalized = candidate.astimezone(timezone.utc).astimezone(zone)
        if (
            normalized.date() != candidate.date()
            or normalized.hour != candidate.hour
            or normalized.minute != candidate.minute
        ):
            candidate = normalized
        if now.astimezone(timezone.utc) < candidate.astimezone(timezone.utc):
            return None
        return utc_timestamp(candidate)

    def _claim(self, job: dict, occurrence: str) -> dict | None:
        record = {
            "schema_version": 1,
            "job_key": job["job_key"],
            "occurrence": occurrence,
            "request_id": f"automatic-create:{job['job_key']}:{occurrence}",
            "retention_request_id": f"automatic-retention:{job['job_key']}:{occurrence}",
            "target": dict(job["target"]),
            "scope": job["scope"],
            "keep_last": int(job["keep_last"]),
            "status": "claimed",
            "claimed_at": utc_timestamp(),
            "finished_at": None,
        }
        claimed = False

        def mutate(rows: list[dict]) -> list[dict]:
            nonlocal claimed
            if any(
                row.get("job_key") == job["job_key"]
                and row.get("occurrence") == occurrence
                for row in rows
            ):
                return rows
            claimed = True
            return [row for row in rows if row.get("job_key") != job["job_key"]] + [record]

        self.state.mutate(mutate)
        return record if claimed else None

    def _set_status(self, record: dict, status: str) -> None:
        finished_at = utc_timestamp() if status in {"completed", "failed", "retention_failed"} else None

        def mutate(rows: list[dict]) -> list[dict]:
            updated = []
            for row in rows:
                if (
                    row.get("job_key") == record.get("job_key")
                    and row.get("occurrence") == record.get("occurrence")
                ):
                    changed = dict(row)
                    changed["status"] = status
                    changed["finished_at"] = finished_at
                    updated.append(changed)
                else:
                    updated.append(row)
            return updated

        self.state.mutate(mutate)
        record["status"] = status
        record["finished_at"] = finished_at

    async def _dispatch_due_occurrences(self) -> None:
        now = utc_now()
        zone = await asyncio.to_thread(local_timezone)
        for job in self._jobs():
            occurrence = self._due_occurrence(job, now, zone)
            if occurrence is None:
                continue
            record = await asyncio.to_thread(self._claim, job, occurrence)
            if record is not None:
                self._spawn(self._run_occurrence(record))

    def _spawn(self, coroutine) -> None:
        worker = asyncio.create_task(coroutine)
        self._workers.add(worker)
        worker.add_done_callback(self._workers.discard)

    async def _run_occurrence(self, record: dict) -> None:
        # Automatic jobs are intentionally serialized. Concurrent target-level
        # creates would mutate Catalog/history while a Bot4VPS self-backup is
        # taking its immutable source snapshot.
        async with self._run_lock:
            try:
                await asyncio.to_thread(self._create, record)
                await asyncio.to_thread(self._set_status, record, "retention_pending")
                await asyncio.to_thread(self._retain, record)
            except Exception as exc:
                status = "retention_failed" if record.get("status") == "retention_pending" else "failed"
                await asyncio.to_thread(self._set_status, record, status)
                print(
                    f"[BACKUP SCHEDULER] {record.get('job_key')} завершён с ошибкой: {type(exc).__name__}",
                    flush=True,
                )
                return
            await asyncio.to_thread(self._set_status, record, "completed")

    def _create(self, record: dict) -> None:
        manager = BackupManager(get_backup_config(), data_root=self.data_root)
        target = record["target"]
        if target["kind"] == "bot4vps":
            manager.create_bot4vps(
                request_id=record["request_id"],
                mode="automatic",
            )
        else:
            manager.create(
                target["server_id"],
                request_id=record["request_id"],
                mode="automatic",
            )

    def _retain(self, record: dict) -> None:
        BackupManager(get_backup_config(), data_root=self.data_root).apply_retention(
            record["scope"],
            keep_last=int(record["keep_last"]),
            request_id=record["retention_request_id"],
        )

    async def _recover_interrupted_occurrences(self) -> None:
        jobs = {job["job_key"]: job for job in self._jobs()}
        manager = await asyncio.to_thread(
            BackupManager,
            get_backup_config(),
            data_root=self.data_root,
        )
        now = utc_now()
        for record in await asyncio.to_thread(self.state.read):
            status = record.get("status")
            if status == "retention_pending":
                self._spawn(self._resume_retention(record))
                continue
            if status != "claimed":
                continue
            operation = await asyncio.to_thread(
                manager.operations.find_by_request_id,
                record.get("request_id"),
            )
            if operation is not None and operation.get("status") == OperationStatus.COMPLETED.value:
                await asyncio.to_thread(self._set_status, record, "retention_pending")
                self._spawn(self._resume_retention(record))
                continue
            if operation is not None and operation.get("status") in TERMINAL_STATUSES:
                await asyncio.to_thread(self._set_status, record, "failed")
                continue
            job = jobs.get(record.get("job_key"))
            current_occurrence = self._due_occurrence(job, now) if job is not None else None
            if operation is None and current_occurrence == record.get("occurrence"):
                self._spawn(self._run_occurrence(record))
            elif operation is None:
                await asyncio.to_thread(self._set_status, record, "failed")
            # A non-terminal Operation that survived reconciliation is owned by
            # another live process. Its durable claim remains untouched.

    async def _resume_retention(self, record: dict) -> None:
        async with self._run_lock:
            try:
                await asyncio.to_thread(self._retain, record)
            except Exception as exc:
                await asyncio.to_thread(self._set_status, record, "retention_failed")
                print(
                    f"[BACKUP SCHEDULER] retention {record.get('job_key')} завершён с ошибкой: {type(exc).__name__}",
                    flush=True,
                )
                return
            await asyncio.to_thread(self._set_status, record, "completed")


_scheduler: AutomaticBackupScheduler | None = None


async def start_automatic_backup_scheduler() -> AutomaticBackupScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AutomaticBackupScheduler()
    await _scheduler.start()
    return _scheduler


async def stop_automatic_backup_scheduler() -> None:
    global _scheduler
    scheduler = _scheduler
    _scheduler = None
    if scheduler is not None:
        await scheduler.stop()
