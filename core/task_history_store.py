"""Постоянное хранилище завершённых задач Task Manager.

Каждая задача — отдельный файл ``logs/tasks/<task_id>.json``. Все операции
read-modify-write проходят через единый sidecar lock-файл каталога и
завершаются атомарной заменой (tmp + ``os.replace`` + fsync файла и
каталога). Механика общая с другими хранилищами — см. ``core/json_store``.
"""
from __future__ import annotations

from pathlib import Path
import json
from typing import Any, Callable, Optional

from core.json_store import JsonItemStore, locked


def mask_task_text(text, payload: dict) -> str:
    """Скрыть известные секретные параметры и распознаваемые секреты."""
    from core.audit import _secret_key, mask_text, MASK

    secrets = []
    def collect(value, secret=False):
        if isinstance(value, dict):
            for key, item in value.items():
                collect(item, secret or _secret_key(str(key)))
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item, secret)
        elif secret and value is not None and not isinstance(value, bool):
            if str(value):
                secrets.append(str(value))
    collect(payload)
    value = str(text or "")
    for secret in sorted(set(secrets), key=len, reverse=True):
        value = value.replace(secret, MASK)
    return mask_text(value)


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
        # Старую plaintext-историю переводим под тем же lock, без потери retry.
        with locked(self._store.lock_path, self._store._thread_lock):
            records = self._store.load()
            for record in records:
                if "private_enc" not in record:
                    self._store.update(str(record["id"]), **self._encode(record))
            return [self._decode(record) for record in self._store.load()]

    @staticmethod
    def _encode(task):
        from core.secretbox import encrypt
        raw = dict(task)
        raw.pop("private_enc", None)
        safe = dict(raw)
        safe["payload"] = {}
        safe["error"] = None
        safe["output_lines"] = []
        if isinstance(raw.get("result"), dict):
            safe["result"] = dict(raw["result"])
            for key in ("output", "error"):
                safe["result"][key] = None
        # Весь исходный документ: неизвестные секреты в выводе тоже защищены.
        safe["private_enc"] = encrypt(json.dumps(raw, ensure_ascii=False))
        return safe

    @staticmethod
    def _decode(record):
        from core.secretbox import decrypt, SecretBoxError, MasterKeyMissingError
        if "private_enc" in record:
            try:
                return json.loads(decrypt(record["private_enc"]))
            except MasterKeyMissingError:
                raise
            except (SecretBoxError, ValueError, TypeError):
                # После осознанной смены мастер-ключа старая история не
                # должна скрывать новые записи. Ciphertext остаётся на диске.
                safe = dict(record)
                safe.pop("private_enc", None)
                safe["payload"] = {}
                safe["payload_available"] = False
                message = "Приватные данные задачи недоступны: нужен исходный мастер-ключ"
                safe["output_lines"] = [message]
                if isinstance(safe.get("result"), dict):
                    safe["result"] = {**safe["result"], "output": message}
                return safe
        return dict(record)

    def append(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        """Атомарная запись одного файла + idempotent replace + prune."""
        task_id = str(task.get("id") or "")
        if not task_id:
            raise ValueError("Историческая задача должна содержать id")
        return [self._decode(record) for record in self._store.append(self._encode(task))]

    def delete(self, task_id: str) -> tuple[bool, list[dict[str, Any]]]:
        """Удалить запись внутри одного защищённого read-modify-write."""
        deleted, records = self._store.delete(task_id)
        return deleted, [self._decode(record) for record in records]

    def clear(self) -> int:
        """Удалить все файлы истории и вернуть число удалённых."""
        return self._store.clear()

    def revision(self) -> str:
        """Дешёвый маркер изменения для SSE без чтения содержимого."""
        return self._store.revision()
