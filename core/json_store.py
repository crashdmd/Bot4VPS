"""Общие примитивы надёжного JSON-хранения.

Объединяет паттерн, проверенный в ``task_history_store``: sidecar lock-файл
+ ``fcntl.flock`` (кросс-процессно) + ``threading.RLock`` (внутри процесса),
атомарная запись через tmp + ``os.replace`` + fsync файла и каталога,
карантин повреждённых файлов (``<имя>.corrupt-<ts>.json``).

Два хранилища:
- ``JsonDocumentStore`` — один JSON-документ (список) в одном файле
  (очередь уведомлений);
- ``JsonItemStore`` — один файл на запись (история задач, журнал событий).

Повреждение одного элемента не затрагивает остальные: плохой файл
переименовывается в карантин и пропускается.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - production Bot4VPS runs on Linux
    fcntl = None

# Допустимые id записей: младшие 12 hex задач, 32 hex событий.
_ID_RE = re.compile(r"^[0-9a-f]{6,64}$")

# Возраст мусорных tmp-файлов, после которого prune их удаляет.
_TMP_TTL_SECONDS = 24 * 60 * 60

_fcntl_warned = False


def _warn_fcntl_once(name: str) -> None:
    global _fcntl_warned
    if fcntl is None and not _fcntl_warned:
        _fcntl_warned = True
        print(
            f"[{name}] WARNING: fcntl недоступен; "
            "межпроцессная блокировка отключена",
            flush=True,
        )


def atomic_write_json(path: Path, data: Any) -> None:
    """Атомарно записать JSON: tmp + fsync + os.replace + fsync каталога."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            temp_path = Path(tmp.name)
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(temp_path, path)
        temp_path = None
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # Не все файловые системы (и не Windows) поддерживают fsync каталога.
            pass
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def quarantine(path: Path) -> Optional[Path]:
    """Переименовать повреждённый файл в ``<stem>.corrupt-<ts><suffix>``."""
    path = Path(path)
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = path.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}")
    try:
        path.rename(target)
        return target
    except OSError:
        return None


@contextmanager
def locked(lock_path: Path, thread_lock: threading.RLock) -> Iterator[None]:
    """Кросс-процессная (flock sidecar) + поточная блокировка."""
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with thread_lock:
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class JsonDocumentStore:
    """Единый JSON-документ (список) + sidecar lock — очередь уведомлений."""

    def __init__(self, path: str | Path, *, name: str = "JSON STORE"):
        self.path = Path(path)
        self.name = name
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self._thread_lock = threading.RLock()
        _warn_fcntl_once(name)

    def read(self) -> list[dict[str, Any]]:
        """Прочитать документ; повреждённый файл — в карантин, результат []."""
        if not self.path.exists():
            return []
        try:
            with self.path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"[{self.name}] Не удалось прочитать {self.path}: {exc}. "
                "Файл перенесён в карантин.",
                flush=True,
            )
            with locked(self.lock_path, self._thread_lock):
                quarantine(self.path)
            return []
        if not isinstance(raw, list):
            print(
                f"[{self.name}] {self.path} должен содержать JSON-массив; "
                "файл перенесён в карантин.",
                flush=True,
            )
            with locked(self.lock_path, self._thread_lock):
                quarantine(self.path)
            return []
        return [dict(item) for item in raw if isinstance(item, dict)]

    def mutate(self, fn: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]) -> list[dict[str, Any]]:
        """Весь read-modify-write под одним lock; вернуть новое состояние."""
        with locked(self.lock_path, self._thread_lock):
            current = self._read_unlocked()
            updated = fn(current)
            self._write_unlocked(updated)
            return [dict(item) for item in updated]

    def write(self, data: list[dict[str, Any]]) -> None:
        with locked(self.lock_path, self._thread_lock):
            self._write_unlocked(data)

    # -- внутреннее (вызываются только под lock) --

    def _read_unlocked(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            with self.path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"[{self.name}] Не удалось прочитать {self.path}: {exc}. "
                "Файл перенесён в карантин, очередь считается пустой.",
                flush=True,
            )
            quarantine(self.path)
            return []
        if not isinstance(raw, list):
            print(
                f"[{self.name}] {self.path} должен содержать JSON-массив; "
                "файл перенесён в карантин.",
                flush=True,
            )
            quarantine(self.path)
            return []
        return [dict(item) for item in raw if isinstance(item, dict)]

    def _write_unlocked(self, data: list[dict[str, Any]]) -> None:
        atomic_write_json(self.path, data)


class JsonItemStore:
    """Одна запись — один файл ``<id>.json`` + store-wide sidecar lock.

    Порядок записей — по возрастанию ``(*time_field, id)``, где время —
    первое непустое из ``sort_fields`` (по умолчанию ``timestamp``);
    записи без всех полей времени падают в конец кластера одинаковых
    ключей и упорядочиваются по ``id``. Для дешёвых частых чтений
    (SSE ~3 c, опрос задач ~1.5 c) держится кэш в процессе,
    валидируемый дешёвым ``revision()`` (один ``os.scandir`` без открытия
    файлов).
    """

    def __init__(
        self,
        dir_path: str | Path,
        *,
        limit: int = 100,
        name: str = "ITEM STORE",
        validator: Optional[Callable[[dict[str, Any]], Any]] = None,
        sort_fields: tuple[str, ...] = ("timestamp",),
    ):
        self.dir_path = Path(dir_path)
        self.limit = max(1, int(limit))
        self.name = name
        self.lock_path = self.dir_path / ".lock"
        self._validator = validator
        self._sort_fields = tuple(sort_fields) or ("timestamp",)
        self._thread_lock = threading.RLock()
        self._cache: Optional[list[dict[str, Any]]] = None
        self._cache_stamp: Optional[str] = None
        _warn_fcntl_once(name)

    def set_validator(
        self,
        validator: Optional[Callable[[dict[str, Any]], Any]],
    ) -> None:
        """Назначить проверку записи (например, Task.from_dict)."""
        self._validator = validator

    # -- публичные операции --

    def load(self) -> list[dict[str, Any]]:
        """Полный список по возрастанию (с кэшем по revision)."""
        stamp = self.revision()
        if self._cache is not None and stamp == self._cache_stamp:
            return [dict(item) for item in self._cache]
        with locked(self.lock_path, self._thread_lock):
            records = self._read_all_unlocked()
            # Stamp берём после завершения чтения: запись, случившаяся
            # в процессе, будет замечена следующим вызовом.
            stamp = self._stamp_unlocked()
            self._cache = records
            self._cache_stamp = stamp
            return [dict(item) for item in records]

    def get(self, item_id: str) -> Optional[dict[str, Any]]:
        """Прочитать одну запись по id (без полного сканирования)."""
        path = self._item_path(item_id)
        if path is None or not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"[{self.name}] Повреждённый файл {path.name}: {exc}. "
                "Перенесён в карантин.",
                flush=True,
            )
            with locked(self.lock_path, self._thread_lock):
                quarantine(path)
            return None
        if not isinstance(raw, dict) or not self._is_valid_record(raw):
            print(
                f"[{self.name}] Некорректная запись в {path.name}; "
                "файл перенесён в карантин.",
                flush=True,
            )
            with locked(self.lock_path, self._thread_lock):
                quarantine(path)
            return None
        return dict(raw)

    def append(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        """Атомарно записать один файл + prune; вернуть полный список."""
        item_id = str(item.get("id") or "")
        path = self._item_path(item_id)
        if path is None:
            raise ValueError("Запись должна содержать корректный id")
        with locked(self.lock_path, self._thread_lock):
            atomic_write_json(path, item)
            self._prune_unlocked()
            self._cache = None
            self._cache_stamp = None
            return self._read_all_unlocked()

    def update(self, item_id: str, **fields: Any) -> bool:
        """Перезаписать один файл под lock; False, если записи нет."""
        path = self._item_path(item_id)
        if path is None:
            return False
        with locked(self.lock_path, self._thread_lock):
            if not path.exists():
                return False
            try:
                with path.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
            except (OSError, json.JSONDecodeError):
                print(
                    f"[{self.name}] Повреждённый файл {path.name}; "
                    "перенесён в карантин, обновление невозможно.",
                    flush=True,
                )
                quarantine(path)
                self._cache = None
                self._cache_stamp = None
                return False
            if not isinstance(raw, dict):
                quarantine(path)
                self._cache = None
                self._cache_stamp = None
                return False
            raw.update(fields)
            atomic_write_json(path, raw)
            self._cache = None
            self._cache_stamp = None
            return True

    def delete(self, item_id: str) -> tuple[bool, list[dict[str, Any]]]:
        """Удалить один файл; вернуть (удалено, остаток списка)."""
        path = self._item_path(item_id)
        if path is None:
            return False, self.load()
        with locked(self.lock_path, self._thread_lock):
            if not path.exists():
                return False, self._read_all_unlocked()
            try:
                path.unlink()
            except OSError:
                return False, self._read_all_unlocked()
            self._cache = None
            self._cache_stamp = None
            return True, self._read_all_unlocked()

    def clear(self) -> int:
        """Удалить все файлы записей; вернуть число удалённых."""
        with locked(self.lock_path, self._thread_lock):
            removed = 0
            for path in self._list_item_files_unlocked():
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
            self._cache = None
            self._cache_stamp = None
            return removed

    def replace_all(self, items: list[dict[str, Any]]) -> None:
        """Полная замена содержимого (совместимость save_events)."""
        with locked(self.lock_path, self._thread_lock):
            for path in self._list_item_files_unlocked():
                try:
                    path.unlink()
                except OSError:
                    pass
            written = 0
            for item in items:
                item_id = str(item.get("id") or "") if isinstance(item, dict) else ""
                path = self._item_path(item_id)
                if path is None:
                    print(
                        f"[{self.name}] replace_all: пропущена запись без корректного id",
                        flush=True,
                    )
                    continue
                atomic_write_json(path, item)
                written += 1
            if written > self.limit:
                self._prune_unlocked()
            self._cache = None
            self._cache_stamp = None

    def revision(self) -> str:
        """Дешёвый маркер изменения для SSE (один scandir, без чтения)."""
        return self._stamp_unlocked()

    def prune(self) -> None:
        """Принудительно применить текущий ``limit`` (горячая смена лимита)."""
        with locked(self.lock_path, self._thread_lock):
            self._prune_unlocked()
            self._cache = None
            self._cache_stamp = None

    # -- внутреннее (под lock, если не указано иное) --

    def _item_path(self, item_id: str) -> Optional[Path]:
        if not isinstance(item_id, str) or not _ID_RE.match(item_id):
            return None
        return self.dir_path / f"{item_id}.json"

    def _is_valid_record(self, item: dict[str, Any]) -> bool:
        if self._validator is None:
            return True
        try:
            self._validator(item)
            return True
        except Exception:
            return False

    def _list_item_files_unlocked(self) -> list[Path]:
        if not self.dir_path.exists():
            return []
        result: list[Path] = []
        try:
            with os.scandir(self.dir_path) as it:
                for entry in it:
                    name = entry.name
                    if not name.endswith(".json") or not entry.is_file():
                        continue
                    stem = name[: -len(".json")]
                    if _ID_RE.match(stem):
                        result.append(Path(entry.path))
        except OSError:
            return []
        return result

    def _read_all_unlocked(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in self._list_item_files_unlocked():
            try:
                with path.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                print(
                    f"[{self.name}] Повреждённый файл {path.name}: {exc}. "
                    "Перенесён в карантин.",
                    flush=True,
                )
                quarantine(path)
                continue
            if not isinstance(raw, dict):
                print(
                    f"[{self.name}] Некорректная запись в {path.name}; "
                    "файл перенесён в карантин.",
                    flush=True,
                )
                quarantine(path)
                continue
            if str(raw.get("id") or "") != path.stem or not self._is_valid_record(raw):
                print(
                    f"[{self.name}] Запись #{path.stem} не прошла проверку; "
                    "файл перенесён в карантин.",
                    flush=True,
                )
                quarantine(path)
                continue
            records.append(dict(raw))
        records.sort(key=self._record_sort_key)
        return records

    def _record_sort_key(self, record: dict[str, Any]) -> tuple[str, str]:
        """Ключ порядка: первое непустое поле времени + id (стабильно)."""
        for field in self._sort_fields:
            value = str(record.get(field) or "")
            if value:
                return (value, str(record.get("id") or ""))
        return ("", str(record.get("id") or ""))

    def _stamp_unlocked(self) -> str:
        if not self.dir_path.exists():
            return "missing"
        max_mtime_ns = 0
        count = 0
        total_size = 0
        try:
            with os.scandir(self.dir_path) as it:
                for entry in it:
                    name = entry.name
                    if not name.endswith(".json") or not entry.is_file():
                        continue
                    stem = name[: -len(".json")]
                    if not _ID_RE.match(stem):
                        continue
                    count += 1
                    total_size += entry.stat().st_size
                    mtime_ns = entry.stat().st_mtime_ns
                    if mtime_ns > max_mtime_ns:
                        max_mtime_ns = mtime_ns
        except OSError:
            return "missing"
        return f"{max_mtime_ns}:{count}:{total_size}"

    def _prune_unlocked(self) -> None:
        """Удалить самые старые записи сверх лимита + смести старые tmp."""
        if not self.dir_path.exists():
            return
        files = self._list_item_files_unlocked()
        if len(files) > self.limit:
            # Сортируем по mtime как дешёвый proxy возраста; точный порядок
            # даёт сортировка по содержимому, но для prune достаточно.
            files.sort(key=lambda p: p.stat().st_mtime_ns)
            for path in files[: len(files) - self.limit]:
                try:
                    path.unlink()
                except OSError:
                    pass
        # Сметаем остатки аварийных tmp-файлов старше суток.
        now = time.time()
        try:
            with os.scandir(self.dir_path) as it:
                for entry in it:
                    if (
                        entry.name.endswith(".tmp")
                        and entry.is_file()
                        and now - entry.stat().st_mtime > _TMP_TTL_SECONDS
                    ):
                        try:
                            os.unlink(entry.path)
                        except OSError:
                            pass
        except OSError:
            pass
