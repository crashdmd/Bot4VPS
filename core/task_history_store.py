"""Постоянное хранилище завершённых задач Task Manager.

Каждая задача — отдельный файл ``logs/tasks/<task_id>.json``. Все операции
read-modify-write проходят через единый sidecar lock-файл каталога и
завершаются атомарной заменой (tmp + ``os.replace`` + fsync файла и
каталога). Механика общая с другими хранилищами — см. ``core/json_store``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from core.json_store import JsonItemStore


class TaskHistoryStore:
    """Единый источник истины для ``logs/tasks/<task_id>.json``."""

    def __init__(
        self,
        path: str | Path = "logs/tasks",
        limit: int = 100,
        validator: Optional[Callable[[dict[str, Any]], Any]] = None,
    ):
        self._store = JsonItemStore(
            path,
            limit=limit,
            name="TASK HISTORY",
            validator=validator,
            # Записи задач несут created_at (timestamp — поле событий);
            # записи без обоих полей упорядочиваются по id, как раньше.
            sort_fields=("created_at", "timestamp"),
        )

    @property
    def path(self) -> Path:
        return self._store.dir_path

    def set_validator(
        self,
        validator: Optional[Callable[[dict[str, Any]], Any]],
    ) -> None:
        """Назначить проверку записи через канонический Task.from_dict()."""
        self._store.set_validator(validator)

    def set_limit(self, limit: int) -> None:
        """Горячая смена лимита истории (Настройки → История и данные)."""
        self._store.limit = max(1, int(limit))
        self._store.prune()

    def load(self) -> list[dict[str, Any]]:
        """Записи по возрастанию (актуальное чтение под lock)."""
        return self._store.load()

    def append(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        """Атомарная запись одного файла + idempotent replace + prune."""
        task_id = str(task.get("id") or "")
        if not task_id:
            raise ValueError("Историческая задача должна содержать id")
        return self._store.append(task)

    def delete(self, task_id: str) -> tuple[bool, list[dict[str, Any]]]:
        """Удалить запись внутри одного защищённого read-modify-write."""
        return self._store.delete(task_id)

    def clear(self) -> int:
        """Удалить все файлы истории и вернуть число удалённых."""
        return self._store.clear()

    def revision(self) -> str:
        """Дешёвый маркер изменения для SSE без чтения содержимого."""
        return self._store.revision()
