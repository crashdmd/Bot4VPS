"""Постоянное хранилище завершённых задач Task Manager.

Все операции read-modify-write проходят через единый lock-файл и завершаются
атомарной заменой ``logs/tasks.json``. Основной JSON-файл не блокируется:
после ``os.replace`` у него меняется inode, поэтому для flock нужен постоянный
sidecar-файл.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - production Bot4VPS runs on Linux
    fcntl = None


class TaskHistoryStore:
    """Единый источник истины для ``logs/tasks.json``."""

    def __init__(
        self,
        path: str | Path = "logs/tasks.json",
        limit: int = 100,
        validator: Optional[Callable[[dict[str, Any]], Any]] = None,
    ):
        self.path = Path(path)
        self.limit = max(1, int(limit))
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self._validator = validator
        self._thread_lock = threading.RLock()
        if fcntl is None:
            print(
                "[TASK HISTORY] WARNING: fcntl недоступен; "
                "межпроцессная блокировка отключена",
                flush=True,
            )

    def set_validator(
        self,
        validator: Optional[Callable[[dict[str, Any]], Any]],
    ) -> None:
        """Назначить проверку записи через канонический Task.from_dict()."""
        self._validator = validator

    def _is_valid_record(self, item: dict[str, Any], index: int) -> bool:
        if self._validator is None:
            return True
        try:
            self._validator(item)
            return True
        except Exception as exc:
            print(
                f"[TASK HISTORY] Пропущена некорректная запись #{index}: {exc}",
                flush=True,
            )
            return False

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._thread_lock:
            with self.lock_path.open("a+", encoding="utf-8") as lock_file:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if fcntl is not None:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _read_unlocked(self) -> tuple[list[dict[str, Any]], bool]:
        """Вернуть валидные записи и признак пропущенных/повреждённых данных."""
        if not self.path.exists():
            return [], False
        try:
            with self.path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"[TASK HISTORY] Не удалось прочитать {self.path}: {exc}. "
                "Повреждённый файл сохранён без изменений.",
                flush=True,
            )
            return [], True

        if not isinstance(raw, list):
            print(
                f"[TASK HISTORY] {self.path} должен содержать JSON-массив; "
                "файл сохранён без изменений.",
                flush=True,
            )
            return [], True

        valid: list[dict[str, Any]] = []
        skipped = 0
        for index, item in enumerate(raw):
            if isinstance(item, dict) and self._is_valid_record(item, index):
                valid.append(item)
            else:
                skipped += 1
                if not isinstance(item, dict):
                    print(
                        f"[TASK HISTORY] Пропущена запись #{index}: ожидался объект",
                        flush=True,
                    )
        return valid[-self.limit :], skipped > 0

    def _backup_corrupt_unlocked(self) -> Optional[Path]:
        """Сохранить исходный файл перед заменой очищенным состоянием."""
        if not self.path.exists():
            return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = self.path.with_name(f"{self.path.stem}.corrupt-{stamp}{self.path.suffix}")
        try:
            shutil.copy2(self.path, backup)
            print(
                f"[TASK HISTORY] Исходный файл сохранён как {backup}",
                flush=True,
            )
            return backup
        except OSError as exc:
            raise OSError(
                f"Не удалось сохранить резервную копию повреждённой истории: {exc}"
            ) from exc

    def _write_unlocked(self, records: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=self.path.name + ".",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                temp_path = Path(tmp.name)
                json.dump(records[-self.limit :], tmp, ensure_ascii=False, indent=2)
                tmp.write("\n")
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(temp_path, self.path)
            temp_path = None
            try:
                directory_fd = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                # Не все файловые системы поддерживают fsync каталога.
                pass
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _copy(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # JSON round-trip не нужен: записи уже получены из JSON или Task.to_dict().
        return [dict(item) for item in records]

    def revision(self) -> str:
        """Дешёвый маркер изменения для SSE без чтения содержимого файла."""
        try:
            stat = self.path.stat()
            return f"{stat.st_ino}:{stat.st_mtime_ns}:{stat.st_size}"
        except OSError:
            return "missing"

    def load(self) -> list[dict[str, Any]]:
        with self._locked():
            records, _ = self._read_unlocked()
            return self._copy(records)

    def append(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        """Актуальное чтение + idempotent append + limit + atomic write."""
        task_id = str(task.get("id") or "")
        if not task_id:
            raise ValueError("Историческая задача должна содержать id")
        with self._locked():
            records, damaged = self._read_unlocked()
            if damaged:
                self._backup_corrupt_unlocked()
            records = [item for item in records if str(item.get("id")) != task_id]
            records.append(dict(task))
            records = records[-self.limit :]
            self._write_unlocked(records)
            return self._copy(records)

    def delete(self, task_id: str) -> tuple[bool, list[dict[str, Any]]]:
        """Удалить запись внутри одного защищённого read-modify-write."""
        with self._locked():
            records, damaged = self._read_unlocked()
            updated = [item for item in records if str(item.get("id")) != task_id]
            deleted = len(updated) != len(records)
            if deleted:
                if damaged:
                    self._backup_corrupt_unlocked()
                self._write_unlocked(updated)
            return deleted, self._copy(updated if deleted else records)

    def clear(self) -> int:
        """Атомарно сохранить пустой JSON-массив и вернуть число записей."""
        with self._locked():
            records, damaged = self._read_unlocked()
            if damaged:
                self._backup_corrupt_unlocked()
            self._write_unlocked([])
            return len(records)
