"""
Task Manager for Bot4VPS.

Очередь задач на сервер + реестр исполнителей.
Task хранит сериализуемое описание (kind + payload);
исполнитель выбирается по kind из registry.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.task_history_store import TaskHistoryStore


# --------------------------------------------------
# Статусы / результат
# --------------------------------------------------

class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    SUCCESS_WITH_WARNINGS = "success_warn"
    FAILED = "failed"
    CANCELLED = "cancelled"


STATUS_EMOJI = {
    TaskStatus.QUEUED: "⏳",
    TaskStatus.RUNNING: "▶",
    TaskStatus.SUCCESS: "✅",
    TaskStatus.SUCCESS_WITH_WARNINGS: "⚠️",
    TaskStatus.FAILED: "❌",
    TaskStatus.CANCELLED: "⚠️",
}

_TERMINAL = {
    TaskStatus.SUCCESS,
    TaskStatus.SUCCESS_WITH_WARNINGS,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
}


@dataclass
class TaskResult:
    success: bool
    exit_code: Optional[int] = None
    output: str = ""
    error: Optional[str] = None
    warnings: bool = False


# executor(payload, task, progress_cb) -> TaskResult
ExecutorFn = Callable[
    [Dict[str, Any], "Task", Callable[[str], Awaitable[None]]],
    Awaitable[TaskResult],
]


# --------------------------------------------------
# Реестр исполнителей
# --------------------------------------------------

_EXECUTORS: Dict[str, ExecutorFn] = {}


def register_executor(kind: str, fn: ExecutorFn) -> None:
    """
    Зарегистрировать исполнитель типа задач.

        register_executor("script", run_script_executor)
        register_executor("backup", run_backup_executor)
    """
    if not kind or not callable(fn):
        raise ValueError("kind and callable required")
    _EXECUTORS[kind] = fn


def get_executor(kind: str) -> Optional[ExecutorFn]:
    return _EXECUTORS.get(kind)


def list_executors() -> List[str]:
    return sorted(_EXECUTORS.keys())


# --------------------------------------------------
# Task
# --------------------------------------------------

@dataclass
class Task:
    id: str
    name: str
    server_id: str
    server_name: str
    status: TaskStatus
    created_at: datetime
    # сериализуемое описание
    kind: str = "custom"
    payload: Dict[str, Any] = field(default_factory=dict)
    # runtime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    output_lines: List[str] = field(default_factory=list)
    result: Optional[TaskResult] = None
    error: Optional[str] = None
    attempt: int = 1
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _done_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _asyncio_task: Optional[asyncio.Task] = field(default=None, repr=False)

    def append_output(self, line: str):
        if not line:
            return
        line = str(line).rstrip("\n\r")
        if line:
            self.output_lines.append(line)

    def output_text(self, limit: int = 80) -> str:
        lines = self.output_lines
        if len(lines) > limit:
            return "...\n" + "\n".join(lines[-limit:])
        return "\n".join(lines)

    @property
    def is_successful(self) -> bool:
        return self.status in (TaskStatus.SUCCESS, TaskStatus.SUCCESS_WITH_WARNINGS)

    @property
    def is_done(self) -> bool:
        return self.status in _TERMINAL

    @property
    def duration_seconds(self) -> Optional[float]:
        if not self.started_at or not self.finished_at:
            return None
        return (self.finished_at - self.started_at).total_seconds()

    def duration_human(self) -> str:
        sec = self.duration_seconds
        if sec is None:
            return "—"
        if sec < 1:
            return "<1 сек"
        sec = int(sec)
        if sec < 60:
            return f"{sec} сек"
        minutes, s = divmod(sec, 60)
        if minutes < 60:
            return f"{minutes} мин {s} сек" if s else f"{minutes} мин"
        hours, m = divmod(minutes, 60)
        return f"{hours} ч {m} мин"

    async def wait(self, timeout: Optional[float] = None) -> "Task":
        if self.is_done:
            return self
        try:
            await asyncio.wait_for(self._done_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Сериализуемое представление (без runtime-объектов)."""
        return {
            "id": self.id,
            "name": self.name,
            "server_id": self.server_id,
            "server_name": self.server_name,
            "status": self.status.value,
            "kind": self.kind,
            "payload": self.payload,
            "attempt": self.attempt,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "error": self.error,
            "output_lines": self.output_lines[-200:],
            "duration_seconds": self.duration_seconds,
            "result": {
                "success": self.result.success,
                "exit_code": self.result.exit_code,
                "output": (self.result.output or "")[-4000:],
                "error": self.result.error,
                "warnings": self.result.warnings,
            } if self.result else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """Восстановить завершённую задачу из результата :meth:`to_dict`."""
        if not isinstance(data, dict):
            raise ValueError("запись задачи должна быть объектом")

        status = TaskStatus(data["status"])
        if status not in _TERMINAL:
            raise ValueError(f"статус {status.value!r} не является завершённым")

        def parse_datetime(value: Any, field_name: str, required: bool = False):
            if value in (None, ""):
                if required:
                    raise ValueError(f"отсутствует {field_name}")
                return None
            try:
                return datetime.fromisoformat(str(value))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"некорректное поле {field_name}") from exc

        result_data = data.get("result")
        result = None
        if result_data is not None:
            if not isinstance(result_data, dict):
                raise ValueError("поле result должно быть объектом или null")
            result = TaskResult(
                success=bool(result_data.get("success")),
                exit_code=result_data.get("exit_code"),
                output=str(result_data.get("output") or ""),
                error=result_data.get("error"),
                warnings=bool(result_data.get("warnings")),
            )

        payload = data.get("payload") or {}
        output_lines = data.get("output_lines") or []
        if not isinstance(payload, dict):
            raise ValueError("поле payload должно быть объектом")
        if not isinstance(output_lines, list):
            raise ValueError("поле output_lines должно быть массивом")

        task = cls(
            id=str(data["id"]),
            name=str(data["name"]),
            server_id=str(data["server_id"]),
            server_name=str(data.get("server_name") or data["server_id"]),
            status=status,
            created_at=parse_datetime(data.get("created_at"), "created_at", required=True),
            kind=str(data.get("kind") or "custom"),
            payload=dict(payload),
            started_at=parse_datetime(data.get("started_at"), "started_at"),
            finished_at=parse_datetime(data.get("finished_at"), "finished_at"),
            output_lines=[str(line) for line in output_lines],
            result=result,
            error=data.get("error"),
            attempt=max(1, int(data.get("attempt") or 1)),
        )
        task._done_event.set()
        return task


@dataclass
class QueueState:
    paused: bool = False
    failed_task_id: Optional[str] = None
    failed_task_name: Optional[str] = None
    paused_at: Optional[datetime] = None
    retry_count: int = 0

    def record_failure(self, task: Task):
        """Запомнить последнюю ошибку для retry, не останавливая очередь."""
        if self.failed_task_id != task.id:
            self.retry_count = 0
        self.paused = False
        self.failed_task_id = task.id
        self.failed_task_name = task.name
        self.paused_at = None

    def pause(self, task: Task):
        if self.failed_task_id != task.id:
            self.retry_count = 0
        self.paused = True
        self.failed_task_id = task.id
        self.failed_task_name = task.name
        self.paused_at = datetime.now()

    def note_retry(self):
        self.retry_count += 1

    def clear_failure(self):
        self.paused = False
        self.failed_task_id = None
        self.failed_task_name = None
        self.paused_at = None
        self.retry_count = 0

    def reset(self):
        self.clear_failure()


# --------------------------------------------------
# Task Manager
# --------------------------------------------------


def _task_output_for_event(task: "Task") -> Optional[str]:
    """Вывод задачи для журнала (до 120 строк / 8 КБ)."""
    lines = list(task.output_lines or [])
    if task.result and task.result.output:
        for ln in str(task.result.output).splitlines():
            if ln not in lines:
                lines.append(ln)
    text = "\n".join(lines[-120:])
    if task.error and task.error not in text:
        text = (text + "\n" if text else "") + f"ERROR: {task.error}"
    return (text[:8000] if text else None)


class TaskManager:
    def __init__(
        self,
        history_limit: int = 100,
        history_store: Optional[TaskHistoryStore] = None,
    ):
        self._queues: Dict[str, List[Task]] = {}
        self._running: Dict[str, Task] = {}
        self._queue_state: Dict[str, QueueState] = {}
        self._history_limit = history_limit
        self._history_store = history_store or TaskHistoryStore(
            "logs/tasks.json", limit=history_limit
        )
        # Хранилище проверяет записи каноническим восстановлением Task, поэтому
        # частично повреждённые объекты обнаруживаются до любой перезаписи.
        self._history_store.set_validator(Task.from_dict)
        self._history: List[Task] = []
        self._lock = asyncio.Lock()
        self._live_subscribers: Dict[str, List[Callable[[str], Awaitable[None]]]] = {}
        self._refresh_history()

    def _tasks_from_records(self, records: List[Dict[str, Any]]) -> List[Task]:
        tasks: List[Task] = []
        for index, record in enumerate(records):
            try:
                tasks.append(Task.from_dict(record))
            except Exception as exc:
                task_id = record.get("id") if isinstance(record, dict) else None
                print(
                    f"[TASK HISTORY] Пропущена запись #{index}"
                    f"{f' ({task_id})' if task_id else ''}: {exc}",
                    flush=True,
                )
        return tasks[-self._history_limit :]

    def _refresh_history(self) -> None:
        """Синхронизировать RAM-кэш с актуальным состоянием хранилища."""
        try:
            self._history = self._tasks_from_records(self._history_store.load())
        except Exception as exc:
            print(f"[TASK HISTORY] Ошибка загрузки: {exc}", flush=True)

    def _state(self, server_id: str) -> QueueState:
        if server_id not in self._queue_state:
            self._queue_state[server_id] = QueueState()
        return self._queue_state[server_id]

    async def enqueue(
        self,
        *,
        name: str,
        server_id: str,
        server_name: str,
        kind: str,
        payload: Optional[Dict[str, Any]] = None,
        attempt: int = 1,
    ) -> Task:
        if kind not in _EXECUTORS:
            raise ValueError(
                f"Неизвестный тип задачи '{kind}'. "
                f"Зарегистрированные: {list_executors() or 'нет'}"
            )

        task = Task(
            id=uuid.uuid4().hex[:12],
            name=name,
            server_id=server_id,
            server_name=server_name,
            status=TaskStatus.QUEUED,
            created_at=datetime.now(),
            kind=kind,
            payload=dict(payload or {}),
            attempt=attempt,
        )

        async with self._lock:
            queue = self._queues.setdefault(server_id, [])
            st = self._state(server_id)
            will_wait = server_id in self._running or bool(queue) or st.paused
            queue.append(task)

        if will_wait:
            self._emit_task_event(task, "queued")
        else:
            asyncio.create_task(self._pump(server_id))
        return task

    def queue_position(self, task_id: str) -> Optional[int]:
        for q in self._queues.values():
            for i, t in enumerate(q):
                if t.id == task_id:
                    return i + 1
        return None

    def tasks_ahead(self, task_id: str) -> int:
        pos = self.queue_position(task_id)
        return 0 if pos is None else pos - 1

    async def cancel(self, task_id: str) -> bool:
        async with self._lock:
            for q in self._queues.values():
                for i, t in enumerate(q):
                    if t.id == task_id:
                        t.status = TaskStatus.CANCELLED
                        t.finished_at = datetime.now()
                        t._done_event.set()
                        q.pop(i)
                        self._push_history(t)
                        self._emit_task_event(t, "cancelled")
                        return True
            for t in list(self._running.values()):
                if t.id == task_id:
                    t._cancel_event.set()
                    if t._asyncio_task and not t._asyncio_task.done():
                        t._asyncio_task.cancel()
                    return True
        return False

    async def continue_queue(self, server_id: str) -> bool:
        async with self._lock:
            st = self._state(server_id)
            if not st.paused:
                return False
            st.clear_failure()
        asyncio.create_task(self._pump(server_id))
        return True

    async def retry_last_failed(self, server_id: str) -> Optional[Task]:
        async with self._lock:
            self._refresh_history()
            st = self._state(server_id)
            failed = None
            if st.failed_task_id:
                for t in reversed(self._history):
                    if t.id == st.failed_task_id:
                        failed = t
                        break
            if not failed:
                for t in reversed(self._history):
                    if t.server_id == server_id and t.status == TaskStatus.FAILED:
                        failed = t
                        break
            if not failed or failed.kind not in _EXECUTORS:
                return None

            st.note_retry()
            retry = Task(
                id=uuid.uuid4().hex[:12],
                name=failed.name,
                server_id=failed.server_id,
                server_name=failed.server_name,
                status=TaskStatus.QUEUED,
                created_at=datetime.now(),
                kind=failed.kind,
                payload=dict(failed.payload),
                attempt=failed.attempt + 1,
            )
            self._queues.setdefault(server_id, []).insert(0, retry)
            st.paused = False
            st.paused_at = None

        asyncio.create_task(self._pump(server_id))
        return retry

    async def clear_queue(self, server_id: str) -> int:
        async with self._lock:
            q = self._queues.get(server_id, [])
            n = len(q)
            for t in q:
                t.status = TaskStatus.CANCELLED
                t.finished_at = datetime.now()
                t._done_event.set()
                self._push_history(t)
            self._queues[server_id] = []
            self._state(server_id).reset()
        return n

    def get_running(self, server_id: str) -> Optional[Task]:
        return self._running.get(server_id)

    def get_queue(self, server_id: str) -> List[Task]:
        return list(self._queues.get(server_id, []))

    def get_queue_state(self, server_id: str) -> QueueState:
        return self._state(server_id)

    def is_paused(self, server_id: str) -> bool:
        return self._state(server_id).paused

    def history_revision(self) -> str:
        return self._history_store.revision()

    def get_task(self, task_id: str) -> Optional[Task]:
        for t in self._running.values():
            if t.id == task_id:
                return t
        for q in self._queues.values():
            for t in q:
                if t.id == task_id:
                    return t
        self._refresh_history()
        for t in self._history:
            if t.id == task_id:
                return t
        return None

    def get_history(self, limit: int = 20, server_id: Optional[str] = None) -> List[Task]:
        if limit <= 0:
            return []
        self._refresh_history()
        items = self._history
        if server_id:
            items = [t for t in items if t.server_id == server_id]
        return list(reversed(items[-limit:]))

    async def delete_history_task(self, task_id: str) -> bool:
        """Удалить только завершённую запись, не затрагивая очередь и events."""
        async with self._lock:
            deleted, records = self._history_store.delete(task_id)
            self._history = self._tasks_from_records(records)
            return deleted

    async def clear_history(self) -> int:
        """Очистить только историю Task Manager, сохранив в файле ``[]``."""
        async with self._lock:
            cleared = self._history_store.clear()
            self._history = []
            return cleared

    def subscribe_live(self, task_id: str, callback: Callable[[str], Awaitable[None]]):
        self._live_subscribers.setdefault(task_id, []).append(callback)

    def unsubscribe_live(self, task_id: str, callback: Callable[[str], Awaitable[None]]):
        subs = self._live_subscribers.get(task_id, [])
        if callback in subs:
            subs.remove(callback)
        if not subs:
            self._live_subscribers.pop(task_id, None)

    async def _pump(self, server_id: str):
        async with self._lock:
            st = self._state(server_id)
            if st.paused or server_id in self._running:
                return
            q = self._queues.get(server_id, [])
            if not q:
                return
            task = q.pop(0)
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now()
            self._running[server_id] = task

        async def progress_cb(line: str):
            task.append_output(line)
            for cb in list(self._live_subscribers.get(task.id, [])):
                try:
                    await cb(line)
                except Exception as e:
                    print(f"[TASK] live cb error: {e}", flush=True)

        async def runner():
            try:
                if task._cancel_event.is_set():
                    raise asyncio.CancelledError()

                executor = get_executor(task.kind)
                if not executor:
                    raise RuntimeError(f"Исполнитель '{task.kind}' не зарегистрирован")

                result = await executor(task.payload, task, progress_cb)
                task.result = result

                if task._cancel_event.is_set():
                    task.status = TaskStatus.CANCELLED
                    task.error = "Отменено"
                elif result.success:
                    task.status = (
                        TaskStatus.SUCCESS_WITH_WARNINGS
                        if (result.warnings or result.exit_code == 30)
                        else TaskStatus.SUCCESS
                    )
                else:
                    task.status = TaskStatus.FAILED
                    task.error = result.error or f"exit {result.exit_code}"
            except asyncio.CancelledError:
                task.status = TaskStatus.CANCELLED
                task.error = "Отменено"
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error = str(e)
                task.result = TaskResult(success=False, error=str(e))
            finally:
                task.finished_at = datetime.now()
                task._done_event.set()

        task._asyncio_task = asyncio.create_task(runner())
        await task._asyncio_task

        async with self._lock:
            self._running.pop(server_id, None)
            self._push_history(task)
            st = self._state(server_id)

            if task.is_successful:
                self._emit_task_event(task, "finished")
                if st.failed_task_id:
                    st.clear_failure()
                should_continue = bool(self._queues.get(server_id)) and not st.paused
            elif task.status == TaskStatus.FAILED:
                self._emit_task_event(task, "failed")
                # Ошибка завершает только эту задачу. Данные о ней сохраняем
                # для истории/retry, но следующую задачу запускаем автоматически.
                st.record_failure(task)
                should_continue = bool(self._queues.get(server_id))
            else:
                self._emit_task_event(task, "cancelled")
                should_continue = bool(self._queues.get(server_id)) and not st.paused

        if should_continue:
            asyncio.create_task(self._pump(server_id))

    def _push_history(self, task: Task):
        if not task.is_done:
            return
        try:
            records = self._history_store.append(task.to_dict())
            self._history = self._tasks_from_records(records)
        except Exception as exc:
            # Ошибка диска не должна менять результат уже выполненной SSH-задачи.
            print(f"[TASK HISTORY] Не удалось сохранить задачу {task.id}: {exc}", flush=True)
            self._history = [t for t in self._history if t.id != task.id]
            self._history.append(task)
            self._history = self._history[-self._history_limit :]

    def _emit_task_event(self, task: Task, kind: str):
        try:
            from core.event_service import create_event
            from core.event_types import EventType, EventLevel, EventReason

            reason_map = {
                "queued": EventReason.TASK_QUEUED,
                "finished": EventReason.TASK_FINISHED,
                "failed": EventReason.TASK_FAILED,
                "cancelled": EventReason.TASK_CANCELLED,
            }
            titles = {
                "queued": f"Задача в очереди: {task.name}",
                "finished": f"Задача завершена: {task.name}",
                "failed": f"Задача с ошибкой: {task.name}",
                "cancelled": f"Задача отменена: {task.name}",
            }
            level = EventLevel.INFO
            if kind == "failed":
                level = EventLevel.CRITICAL
            elif kind == "cancelled" or task.status == TaskStatus.SUCCESS_WITH_WARNINGS:
                level = EventLevel.WARNING

            create_event(
                event_type=EventType.TASK,
                level=level,
                title=titles.get(kind, task.name),
                message=(
                    f"Сервер: {task.server_name}\n"
                    f"Тип: {task.kind}\n"
                    f"Статус: {STATUS_EMOJI.get(task.status, '')} {task.status.value}\n"
                    f"Попытка: {task.attempt}\n"
                    f"Длительность: {task.duration_human()}"
                    + (f"\n{task.error}" if task.error else "")
                ),
                details={
                    "task_id": task.id,
                    "server_id": task.server_id,
                    "server_name": task.server_name,
                    "task_name": task.name,
                    "kind": task.kind,
                    "status": task.status.value,
                    "attempt": task.attempt,
                    "duration_seconds": task.duration_seconds,
                    "reason": reason_map[kind].value,
                    "error": (task.error or "")[:500] or None,
                    "output": (
                        _task_output_for_event(task)
                        if kind in ("finished", "failed", "cancelled")
                        else None
                    ),
                },
                notify=(kind in ("queued", "finished", "failed", "cancelled"))
            )
        except Exception as e:
            print(f"[TASK] event error: {e}", flush=True)

    def _emit_queue_paused(self, server_id: str, failed_task: Task, st: QueueState):
        try:
            from core.event_service import create_event
            from core.event_types import EventType, EventLevel, EventReason

            q = self._queues.get(server_id, [])
            names = ", ".join(t.name for t in q) or "—"
            create_event(
                event_type=EventType.TASK,
                level=EventLevel.WARNING,
                title="Очередь на паузе",
                message=(
                    f"Сервер: {failed_task.server_name}\n"
                    f"Ошибка в задаче «{failed_task.name}».\n"
                    f"В очереди ещё: {len(q)}\n{names}\n"
                    f"Повторов этой задачи: {st.retry_count}"
                ),
                details={
                    "server_id": server_id,
                    "server_name": failed_task.server_name,
                    "failed_task_id": failed_task.id,
                    "queue_len": len(q),
                    "retry_count": st.retry_count,
                    "reason": EventReason.TASK_QUEUE_PAUSED.value,
                },
                notify=True,
            )
        except Exception as e:
            print(f"[TASK] pause event error: {e}", flush=True)


task_manager = TaskManager()
