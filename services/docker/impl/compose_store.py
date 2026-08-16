# -*- coding: utf-8 -*-
"""Локальная библиотека Compose-проектов Bot4VPS.

МОДЕЛЬ: объект библиотеки — не один YAML, а ПРОЕКТ (директория):

    data/services/docker/compose/<stack>/
        docker-compose.yml   (обязателен — основной Compose-файл)
        .env                 (опционально)
        config/              (опционально, любая вложенность)
        ...

ДВА УРОВНЯ ХРАНЕНИЯ (не смешивать):
  * ЭТОТ модуль — локальная библиотека Bot4VPS: здесь проект создаётся,
    редактируется и живёт независимо от серверов. SSH здесь НЕТ.
  * compose.py — деплой и запуск на управляемом сервере.

Содержимое дополнительных файлов НЕ интерпретируется — сохраняется структура.
Запись атомарная (temp → fsync → os.replace), как в core/storage.py.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import tempfile
import threading
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

import yaml

from core.integrator import StepError

# Корень локальной библиотеки (runtime-данные, не исходники).
STORE_DIR = Path("data/services/docker/compose")

# Имена основного Compose-файла — в порядке приоритета Docker Compose.
COMPOSE_FILENAMES = (
    "compose.yaml", "compose.yml",
    "docker-compose.yaml", "docker-compose.yml",
)
# Имя по умолчанию при создании проекта из одного YAML.
DEFAULT_COMPOSE_FILENAME = "docker-compose.yml"

# Имя стека = имя каталога и одновременно compose project name.
STACK_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

MAX_COMPOSE_SIZE = 256 * 1024          # основной YAML
MAX_PROJECT_FILE_SIZE = 5 * 1024 * 1024   # любой файл проекта
MAX_PROJECT_TOTAL_SIZE = 50 * 1024 * 1024  # весь проект (защита от zip-бомбы)
MAX_PROJECT_FILES = 500

# Конфиг-набор проекта (docs/compose-model.md §3): ОДИН набор правил для
# fingerprint, импорта и деплоя. Библиотека — конфиг-бэкап, а не бэкап данных:
# runtime-данные контейнера (data/, logs/, …) не относятся к конфигурации, и
# живой проект с ними вечно «расходился» бы с библиотекой.
CONFIG_EXCLUDE_DIRS = frozenset({
    "data", "logs", "log", "cache", "tmp", "temp",
    "uploads", "backup", "backups", "node_modules", ".git",
})
CONFIG_DATA_DIR_SUFFIX = "_data"     # pg_data, mysql_data, …
CONFIG_MAX_FILE_SIZE = 1024 * 1024   # конфиг больше 1 МиБ — это не конфиг
_CONFIG_BINARY_SNIFF = 8192          # NUL-байт в первых 8 КиБ = бинарный

_STORE_LOCK = threading.RLock()


# --------------------------------------------------
# Валидация имён и путей
# --------------------------------------------------

def validate_stack_name(val: Any) -> str:
    """Имя стека: строчная латиница, цифры, дефис, подчёркивание.

    Строго по регэкспу — имя идёт и в путь на диске, и в `-p <project>`.
    Отсекает path traversal на самом входе.
    """
    name = str(val or "").strip().lower()
    if not STACK_NAME_RE.match(name):
        raise StepError(
            "validate_stack_name", -1, title="Имя стека",
            detail=(
                f"недопустимое имя: {val!r}. Разрешены строчные латинские буквы, "
                f"цифры, дефис и подчёркивание (до 63 символов)"
            ),
        )
    return name


def safe_relative_path(raw: Any) -> PurePosixPath:
    """Проверить относительный путь файла ВНУТРИ проекта.

    Защита от archive/path traversal (§5): отклоняем абсолютные пути, «..»,
    имена дисков Windows и всё, что уводит за пределы каталога проекта.
    Возвращает нормализованный POSIX-путь.
    """
    text = str(raw or "").strip().replace("\\", "/")
    if not text:
        raise StepError(
            "validate_path", -1, title="Путь в проекте", detail="пустой путь",
        )
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise StepError(
            "validate_path", -1, title="Путь в проекте",
            detail=f"абсолютные пути запрещены: {raw!r}",
        )
    parts = [p for p in PurePosixPath(text).parts if p not in ("", ".")]
    if not parts:
        raise StepError(
            "validate_path", -1, title="Путь в проекте", detail=f"пустой путь: {raw!r}",
        )
    for p in parts:
        if p == "..":
            raise StepError(
                "validate_path", -1, title="Путь в проекте",
                detail=f"выход за пределы проекта запрещён: {raw!r}",
            )
        if p.startswith("/") or ":" in p:
            raise StepError(
                "validate_path", -1, title="Путь в проекте",
                detail=f"недопустимый элемент пути: {p!r}",
            )
    return PurePosixPath(*parts)


def validate_compose_yaml(text: Any) -> str:
    """Предварительная проверка основного Compose-файла (§6, §7).

    Намеренно НЕ строгая: authoritative-проверка — `docker compose config -q`
    на сервере. Здесь только то, что даёт быстрый и понятный UX:
      * файл не пустой и в пределах лимита;
      * YAML парсится (номер строки/столбца в ошибке);
      * верхний уровень — словарь;
      * есть непустая секция services.
    Содержимое сервисов НЕ проверяем — Compose допускает extends, profiles,
    !reset, x-* и прочее, чего простой валидатор знать не обязан.

    Возвращает нормализованный текст (CRLF → LF, финальный перевод строки).
    """
    raw = text if isinstance(text, str) else str(text or "")
    if not raw.strip():
        raise StepError(
            "validate_compose", -1, title="Compose-файл", detail="файл пустой",
        )
    if len(raw.encode("utf-8")) > MAX_COMPOSE_SIZE:
        raise StepError(
            "validate_compose", -1, title="Compose-файл",
            detail=f"файл больше {MAX_COMPOSE_SIZE // 1024} КБ",
        )

    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"

    try:
        data = yaml.safe_load(normalized)
    except yaml.YAMLError as e:
        detail = str(getattr(e, "problem", None) or e)
        mark = getattr(e, "problem_mark", None)
        if mark is not None:
            detail = f"строка {mark.line + 1}, столбец {mark.column + 1}: {detail}"
        raise StepError(
            "validate_compose", -1, title="Ошибка синтаксиса YAML",
            detail=detail[:500],
        )

    if not isinstance(data, dict):
        raise StepError(
            "validate_compose", -1, title="Compose-файл",
            detail="ожидается YAML-словарь на верхнем уровне",
        )
    services = data.get("services")
    if not isinstance(services, dict) or not services:
        raise StepError(
            "validate_compose", -1, title="Compose-файл",
            detail="отсутствует непустая секция services",
        )
    return normalized


def parse_service_names(text: str) -> List[str]:
    """Имена сервисов из compose-текста (для UI). Пустой список при ошибке."""
    try:
        data = yaml.safe_load(text or "")
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    services = data.get("services")
    if isinstance(services, dict):
        return [str(k) for k in services.keys()]
    return []


def parse_declared_subnets(text: str) -> List[str]:
    """Подсети из networks.*.ipam.config[].subnet.

    Нужны для проверки конфликта с адресацией сервера ДО `up`: объявив подсеть,
    совпадающую с сетью сервера, Docker перетянет маршрут на свой bridge и
    оборвёт SSH (реальный инцидент 2026-08-11). Сверка — в
    compose.detect_subnet_conflicts.
    """
    out: List[str] = []
    try:
        data = yaml.safe_load(text or "")
    except Exception:
        return out
    # Текст может оказаться не Compose-файлом (например, не удалось прочитать
    # его с сервера) — тогда просто нечего проверять.
    if not isinstance(data, dict):
        return out
    networks = data.get("networks")
    if not isinstance(networks, dict):
        return out
    for net in networks.values():
        if not isinstance(net, dict):
            continue
        ipam = net.get("ipam")
        if not isinstance(ipam, dict):
            continue
        config = ipam.get("config")
        if not isinstance(config, list):
            continue
        for item in config:
            if isinstance(item, dict) and item.get("subnet"):
                subnet = str(item["subnet"]).strip()
                if subnet and subnet not in out:
                    out.append(subnet)
    return out


# --------------------------------------------------
# Пути и структура проекта
# --------------------------------------------------

def stack_dir(name: str) -> Path:
    """Каталог проекта в локальной библиотеке (имя валидируется)."""
    return STORE_DIR / validate_stack_name(name)


def find_compose_filename(directory: Path) -> Optional[str]:
    """Имя основного Compose-файла в каталоге (по приоритету Docker Compose)."""
    for fname in COMPOSE_FILENAMES:
        candidate = directory / fname
        if candidate.is_file() and not candidate.is_symlink():
            return fname
    return None


def stack_file(name: str) -> Path:
    """Путь к основному Compose-файлу проекта.

    Если файла ещё нет — возвращает путь с именем по умолчанию (для создания).
    """
    directory = stack_dir(name)
    found = find_compose_filename(directory)
    return directory / (found or DEFAULT_COMPOSE_FILENAME)


def stack_exists(name: str) -> bool:
    """Проект существует, если в его каталоге есть основной Compose-файл."""
    directory = stack_dir(name)
    return directory.is_dir() and find_compose_filename(directory) is not None


def stack_exists_safe(name: str) -> bool:
    """То же, но без исключения на недопустимом имени.

    Имя внешнего проекта приходит от Docker и может не проходить нашу
    валидацию (заглавные буквы, точки) — для проверки «есть ли такой в
    библиотеке» это не ошибка, а просто «нет».
    """
    try:
        return stack_exists(name)
    except Exception:
        return False


def project_dir_exists(name: str) -> bool:
    """Есть ли каталог проекта, даже пока в нём нет Compose-файла."""
    return stack_dir(name).is_dir()


def _project_target(name: str, rel_path: str = "", *, require_project: bool = True) -> Path:
    """Безопасно разрешить путь внутри каталога проекта.

    Помимо проверки ``..`` учитывает симлинки, которые могли быть добавлены в
    библиотеку вручную: итоговый путь обязан остаться внутри реального каталога
    проекта.
    """
    directory = stack_dir(name)
    store = STORE_DIR.resolve()
    resolved_dir = directory.resolve()
    if resolved_dir.parent != store or directory.is_symlink():
        raise StepError(
            "validate_path", -1, title="Путь в проекте",
            detail="каталог проекта находится вне локальной Docker-библиотеки",
        )
    if require_project and not directory.is_dir():
        raise StepError(
            "project_not_found", -1, title="Проект не найден",
            detail=f"проект «{validate_stack_name(name)}» отсутствует в библиотеке",
        )
    if not rel_path:
        return resolved_dir
    rel = safe_relative_path(rel_path)
    target = (resolved_dir / Path(*rel.parts)).resolve()
    if target != resolved_dir and resolved_dir not in target.parents:
        raise StepError(
            "validate_path", -1, title="Путь в проекте",
            detail=f"выход за пределы проекта запрещён: {rel_path!r}",
        )
    return target


def list_library_projects() -> List[Dict[str, Any]]:
    """Каталоги локальной библиотеки для «Файлы → Docker», включая пустые."""
    out: List[Dict[str, Any]] = []
    if not STORE_DIR.is_dir():
        return out
    for entry in sorted(STORE_DIR.iterdir(), key=lambda p: p.name.lower()):
        if not entry.is_dir() or entry.is_symlink() or entry.name.startswith("."):
            continue
        try:
            name = validate_stack_name(entry.name)
        except StepError:
            continue
        files = iter_project_files(name)
        total = 0
        newest = 0.0
        for rel in files:
            try:
                st = (entry / Path(*rel.parts)).stat()
                total += st.st_size
                newest = max(newest, st.st_mtime)
            except OSError:
                pass
        out.append({
            "name": name,
            "is_dir": True,
            "files": len(files),
            "size": total,
            "mtime": int(newest),
            "compose_file": find_compose_filename(entry) or "",
        })
    return out


def list_project_directory(name: str, rel_dir: str = "") -> List[Dict[str, Any]]:
    """Непосредственные дочерние объекты каталога проекта для файлового UI."""
    directory = _project_target(name, rel_dir)
    if not directory.is_dir():
        raise StepError(
            "list_directory", -1, title="Папка не найдена",
            detail=f"в проекте «{name}» нет папки {rel_dir or '/'}",
        )
    project_root = _project_target(name)
    compose_name = find_compose_filename(project_root)
    out: List[Dict[str, Any]] = []
    for item in sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if item.is_symlink():
            continue
        try:
            resolved = item.resolve()
            if resolved != project_root and project_root not in resolved.parents:
                continue
            st = item.stat()
        except OSError:
            continue
        rel = item.relative_to(project_root).as_posix()
        out.append({
            "name": item.name,
            "path": rel,
            "is_dir": item.is_dir(),
            "size": None if item.is_dir() else st.st_size,
            "mtime": int(st.st_mtime),
            "is_compose": not item.is_dir() and rel == compose_name,
        })
    return out


def create_empty_project(name: str) -> Dict[str, Any]:
    """Создать пустой каталог проекта без Compose-файла и без deployment."""
    stack_name = validate_stack_name(name)
    target = STORE_DIR / stack_name
    with _STORE_LOCK:
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Проект «{stack_name}» уже существует.")
        target.mkdir(mode=0o755)
    return {"name": stack_name, "files": 0}


def create_project_directory(name: str, rel_path: str) -> Dict[str, Any]:
    """Создать одну папку в существующем проекте, не объединяя конфликты."""
    stack_name = validate_stack_name(name)
    target = _project_target(stack_name, rel_path)
    parent = target.parent
    project_root = _project_target(stack_name)
    if parent != project_root and project_root not in parent.parents:
        raise StepError("create_directory", -1, title="Путь в проекте", detail="путь вне проекта")
    with _STORE_LOCK:
        if not parent.is_dir():
            raise StepError(
                "create_directory", -1, title="Папка не найдена",
                detail="родительская папка не существует",
            )
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Объект «{PurePosixPath(rel_path).name}» уже существует.")
        target.mkdir(mode=0o755)
    return {"name": stack_name, "path": safe_relative_path(rel_path).as_posix()}


def create_project_file(name: str, rel_path: str, data: bytes = b"") -> Dict[str, Any]:
    """Создать новый файл проекта атомарно, никогда не перезаписывая конфликт."""
    stack_name = validate_stack_name(name)
    rel = safe_relative_path(rel_path).as_posix()
    if len(data) > MAX_PROJECT_FILE_SIZE:
        raise StepError(
            "create_file", -1, title="Файл слишком большой",
            detail=f"больше {MAX_PROJECT_FILE_SIZE // (1024 * 1024)} МБ",
        )
    target = _project_target(stack_name, rel)
    parent = target.parent
    project_root = _project_target(stack_name)
    if parent != project_root and project_root not in parent.parents:
        raise StepError("create_file", -1, title="Путь в проекте", detail="путь вне проекта")

    # Загруженный основной Compose-файл проверяем до записи. Пустой файл при
    # явном создании разрешён: пользователь сразу откроет его в редакторе.
    if rel in COMPOSE_FILENAMES and data:
        data = validate_compose_yaml(data.decode("utf-8")).encode("utf-8")

    with _STORE_LOCK:
        if not parent.is_dir():
            raise StepError(
                "create_file", -1, title="Папка не найдена",
                detail="родительская папка не существует",
            )
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Объект «{PurePosixPath(rel).name}» уже существует.")
        if len(iter_project_files(stack_name)) >= MAX_PROJECT_FILES:
            raise StepError(
                "create_file", -1, title="Слишком много файлов",
                detail=f"в проекте уже {MAX_PROJECT_FILES} файлов",
            )
        current_total = sum(
            (_project_target(stack_name, p.as_posix()).stat().st_size
             for p in iter_project_files(stack_name))
        )
        if current_total + len(data) > MAX_PROJECT_TOTAL_SIZE:
            raise StepError(
                "create_file", -1, title="Проект слишком большой",
                detail=f"суммарно больше {MAX_PROJECT_TOTAL_SIZE // (1024 * 1024)} МБ",
            )
        fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            # Повторная проверка внутри lock непосредственно перед публикацией.
            if target.exists() or target.is_symlink():
                raise FileExistsError(f"Объект «{PurePosixPath(rel).name}» уже существует.")
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
    return {"name": stack_name, "path": rel, "size": len(data)}


def iter_project_files(name: str) -> List[PurePosixPath]:
    """Все файлы проекта относительными POSIX-путями (рекурсивно, sorted)."""
    directory = stack_dir(name)
    if not directory.is_dir():
        return []
    out: List[PurePosixPath] = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(directory).as_posix()
        out.append(PurePosixPath(rel))
    return out


# --------------------------------------------------
# Конфиг-набор проекта (docs/compose-model.md §3)
# --------------------------------------------------

def _is_config_dir(name: str) -> bool:
    """Каталог исключается из конфиг-набора (runtime-данные контейнера)."""
    n = (name or "").strip().lower()
    return n in CONFIG_EXCLUDE_DIRS or (
        n.endswith(CONFIG_DATA_DIR_SUFFIX) and len(n) > len(CONFIG_DATA_DIR_SUFFIX)
    )


def is_config_file(rel_path: str, size: Optional[int] = None,
                   head: Optional[bytes] = None) -> bool:
    """Принадлежит ли файл конфиг-набору проекта.

    Один предикат для fingerprint, импорта с сервера и деплоя из библиотеки —
    все три работают с одинаковым набором, иначе сверка версий расходилась бы
    из-за правил отбора, а не из-за правок. Критерий — содержимое, не
    расширение: безымянные конфиги остаются в наборе.

    rel_path: путь внутри проекта (POSIX). size/head опциональны — их знает
    локальная ФС; на удалённом списке могут отсутствовать, тогда проверяется
    только путь.
    """
    parts = PurePosixPath(str(rel_path or "")).parts
    if not parts:
        return False
    for p in parts[:-1]:
        if _is_config_dir(p):
            return False
    fname = parts[-1]
    if fname in (".", "..") or fname.startswith("/"):
        return False
    if size is not None and size > CONFIG_MAX_FILE_SIZE:
        return False
    if head is not None and b"\0" in head[:_CONFIG_BINARY_SNIFF]:
        return False
    return True


def filter_config_files(files: Dict[str, bytes]) -> List[str]:
    """Оставить из {rel_path: bytes} только конфиг-набор (sorted rel-пути).

    Чистая функция: фильтрует прочитанный с сервера tar-набор тем же
    предикатом, что и локальную библиотеку.
    """
    out: List[str] = []
    for rel, data in files.items():
        if is_config_file(rel, size=len(data), head=data):
            out.append(rel)
    return sorted(out)


def iter_config_files(name: str) -> List[PurePosixPath]:
    """Файлы проекта, входящие в конфиг-набор (sorted, относительные пути).

    Отличается от iter_project_files только отбором: runtime-данные (data/,
    logs/, …) и крупные/бинарные файлы в конфиг-бэкап не попадают.
    """
    directory = stack_dir(name)
    out: List[PurePosixPath] = []
    for rel in iter_project_files(name):
        full = directory / Path(*rel.parts)
        try:
            size = full.stat().st_size
        except OSError:
            continue
        if not is_config_file(rel.as_posix(), size=size, head=None):
            continue
        # Размер прошёл — нюхаем бинарность только головой, не читая мегабайты.
        try:
            with open(full, "rb") as f:
                head = f.read(_CONFIG_BINARY_SNIFF)
        except OSError:
            continue
        if not is_config_file(rel.as_posix(), size=size, head=head):
            continue
        out.append(rel)
    return out


def list_project_files(name: str) -> List[Dict[str, Any]]:
    """Файлы проекта для UI: [{path, size, is_compose}]."""
    directory = stack_dir(name)
    compose_name = find_compose_filename(directory)
    out: List[Dict[str, Any]] = []
    for rel in iter_project_files(name):
        full = directory / rel
        try:
            size = full.stat().st_size
        except OSError:
            size = 0
        out.append({
            "path": rel.as_posix(),
            "size": size,
            "is_compose": rel.as_posix() == compose_name,
        })
    return out


def read_project_file(name: str, rel_path: str) -> str:
    """Прочитать текстовый файл проекта (для редактора)."""
    rel = safe_relative_path(rel_path)
    full = stack_dir(name) / Path(*rel.parts)
    if not full.is_file():
        raise StepError(
            "read_file", -1, title="Файл не найден",
            detail=f"в проекте «{name}» нет файла {rel.as_posix()}",
        )
    try:
        return full.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise StepError(
            "read_file", -1, title="Бинарный файл",
            detail=f"{rel.as_posix()} не является текстовым (UTF-8)",
        )


def read_project_bytes(name: str, rel_path: str) -> bytes:
    """Прочитать файл проекта как байты (для деплоя — работает и с бинарными)."""
    rel = safe_relative_path(rel_path)
    full = stack_dir(name) / Path(*rel.parts)
    if not full.is_file():
        raise StepError(
            "read_file", -1, title="Файл не найден",
            detail=f"в проекте «{name}» нет файла {rel.as_posix()}",
        )
    return full.read_bytes()


def project_fingerprint(name: str) -> str:
    """SHA-256 по КОНФИГ-НАБОРУ проекта (путь + содержимое).

    Используется для сравнения локальной версии с развёрнутой на сервере
    (docs/compose-model.md §3). Runtime-данные (data/, logs/, …) не участвуют:
    иначе живой проект вечно «расходился» бы с библиотекой. Детерминирован:
    файлы обходятся в отсортированном порядке.
    """
    directory = stack_dir(name)
    h = hashlib.sha256()
    for rel in iter_config_files(name):
        h.update(rel.as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update((directory / Path(*rel.parts)).read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def fingerprint_files(files: Dict[str, bytes]) -> str:
    """Fingerprint произвольного набора файлов {rel_path: bytes}.

    Та же схема, что project_fingerprint — чтобы сравнивать локальный проект
    с прочитанным с сервера.
    """
    h = hashlib.sha256()
    for rel in sorted(files.keys()):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(files[rel])
        h.update(b"\0")
    return h.hexdigest()


# --------------------------------------------------
# CRUD библиотеки
# --------------------------------------------------

def list_stacks() -> List[Dict[str, Any]]:
    """Все проекты библиотеки: [{name, compose_file, services[], files, size,
    has_env, extra_files[], updated_at, fingerprint}].

    Каталоги без Compose-файла игнорируются. Битый YAML не роняет список — у
    такого проекта пустой services[] (пользователь увидит и починит).
    """
    out: List[Dict[str, Any]] = []
    if not STORE_DIR.is_dir():
        return out
    for entry in sorted(STORE_DIR.iterdir()):
        if not entry.is_dir():
            continue
        compose_name = find_compose_filename(entry)
        if not compose_name:
            continue
        name = entry.name
        try:
            text = (entry / compose_name).read_text(encoding="utf-8")
        except Exception:
            text = ""
        rels = iter_project_files(name)
        total = 0
        newest = 0.0
        for rel in rels:
            try:
                st = (entry / Path(*rel.parts)).stat()
                total += st.st_size
                newest = max(newest, st.st_mtime)
            except OSError:
                pass
        extra = [r.as_posix() for r in rels if r.as_posix() != compose_name]
        out.append({
            "name": name,
            "compose_file": compose_name,
            "services": parse_service_names(text),
            "files": len(rels),
            "size": total,
            "has_env": any(r.as_posix() == ".env" for r in rels),
            "extra_files": extra,
            "updated_at": newest,
            "fingerprint": project_fingerprint(name),
        })
    return out


def read_stack(name: str) -> str:
    """Прочитать основной Compose-файл проекта."""
    directory = stack_dir(name)
    compose_name = find_compose_filename(directory)
    if not compose_name:
        raise StepError(
            "read_stack", -1, title="Стек не найден",
            detail=f"проект «{name}» отсутствует в библиотеке",
        )
    return (directory / compose_name).read_text(encoding="utf-8")


def _write_files_atomic(name: str, files: Dict[str, bytes]) -> None:
    """Атомарно заменить весь каталог проекта набором файлов.

    Пишем в соседний temp-каталог, затем меняем местами через os.replace —
    при сбое на любом шаге прежний проект остаётся нетронутым (§6).
    """
    stack_name = validate_stack_name(name)
    target = STORE_DIR / stack_name
    with _STORE_LOCK:
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(prefix=f".{stack_name}.new-", dir=STORE_DIR))
        old_dir: Optional[Path] = None
        try:
            for rel_str, data in files.items():
                rel = safe_relative_path(rel_str)
                dest = tmp_dir / Path(*rel.parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
            if target.exists():
                old_dir = Path(tempfile.mkdtemp(prefix=f".{stack_name}.old-", dir=STORE_DIR))
                old_inner = old_dir / "p"
                os.replace(target, old_inner)
            os.replace(tmp_dir, target)
            tmp_dir = None  # успешно переехал
        finally:
            if tmp_dir is not None and tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            if old_dir is not None:
                shutil.rmtree(old_dir, ignore_errors=True)


def write_stack(name: str, text: str) -> Dict[str, Any]:
    """Создать/обновить ТОЛЬКО основной Compose-файл, не теряя остальные файлы.

    Валидация до записи: при битом YAML существующий проект не меняется.
    """
    stack_name = validate_stack_name(name)
    normalized = validate_compose_yaml(text)

    directory = STORE_DIR / stack_name
    compose_name = find_compose_filename(directory) or DEFAULT_COMPOSE_FILENAME

    files: Dict[str, bytes] = {}
    if directory.is_dir():
        for rel in iter_project_files(stack_name):
            files[rel.as_posix()] = (directory / Path(*rel.parts)).read_bytes()
    files[compose_name] = normalized.encode("utf-8")

    _write_files_atomic(stack_name, files)
    return {
        "name": stack_name,
        "compose_file": compose_name,
        "services": parse_service_names(normalized),
        "fingerprint": project_fingerprint(stack_name),
    }


def write_project(name: str, files: Dict[str, bytes]) -> Dict[str, Any]:
    """Создать/заменить проект целиком набором файлов {rel_path: bytes}.

    Требуется основной Compose-файл; он валидируется до записи.
    Используется ZIP-импортом и импортом проекта с сервера.
    """
    stack_name = validate_stack_name(name)
    if not files:
        raise StepError(
            "write_project", -1, title="Пустой проект", detail="нет файлов",
        )
    if len(files) > MAX_PROJECT_FILES:
        raise StepError(
            "write_project", -1, title="Слишком много файлов",
            detail=f"в проекте больше {MAX_PROJECT_FILES} файлов",
        )

    normalized: Dict[str, bytes] = {}
    total = 0
    for rel_str, data in files.items():
        rel = safe_relative_path(rel_str).as_posix()
        if len(data) > MAX_PROJECT_FILE_SIZE:
            raise StepError(
                "write_project", -1, title="Файл слишком большой",
                detail=f"{rel}: больше {MAX_PROJECT_FILE_SIZE // (1024 * 1024)} МБ",
            )
        total += len(data)
        if total > MAX_PROJECT_TOTAL_SIZE:
            raise StepError(
                "write_project", -1, title="Проект слишком большой",
                detail=f"суммарно больше {MAX_PROJECT_TOTAL_SIZE // (1024 * 1024)} МБ",
            )
        normalized[rel] = data

    compose_name = next((f for f in COMPOSE_FILENAMES if f in normalized), None)
    if not compose_name:
        raise StepError(
            "write_project", -1, title="Не найден Compose-файл",
            detail=(
                "в корне проекта должен быть один из файлов: "
                + ", ".join(COMPOSE_FILENAMES)
            ),
        )

    try:
        compose_text = normalized[compose_name].decode("utf-8")
    except UnicodeDecodeError:
        raise StepError(
            "write_project", -1, title="Compose-файл",
            detail=f"{compose_name} не в кодировке UTF-8",
        )
    validated = validate_compose_yaml(compose_text)
    normalized[compose_name] = validated.encode("utf-8")

    _write_files_atomic(stack_name, normalized)
    return {
        "name": stack_name,
        "compose_file": compose_name,
        "services": parse_service_names(validated),
        "files": len(normalized),
        "fingerprint": project_fingerprint(stack_name),
    }


def save_project_file(name: str, rel_path: str, data: bytes) -> Dict[str, Any]:
    """Атомарно записать один файл проекта, сохранив остальные файлы и папки."""
    stack_name = validate_stack_name(name)
    rel = safe_relative_path(rel_path).as_posix()
    if len(data) > MAX_PROJECT_FILE_SIZE:
        raise StepError(
            "save_file", -1, title="Файл слишком большой",
            detail=f"больше {MAX_PROJECT_FILE_SIZE // (1024 * 1024)} МБ",
        )

    project_root = _project_target(stack_name)
    target = _project_target(stack_name, rel)
    lexical_target = project_root / Path(*PurePosixPath(rel).parts)
    if lexical_target.is_symlink():
        raise StepError(
            "save_file", -1, title="Путь в проекте",
            detail="запись через симлинк запрещена",
        )
    if target.exists() and not target.is_file():
        raise StepError(
            "save_file", -1, title="Файл не найден",
            detail=f"{rel} не является файлом",
        )
    if not target.parent.is_dir():
        raise StepError(
            "save_file", -1, title="Папка не найдена",
            detail="родительская папка не существует",
        )

    # Если правим основной Compose-файл — валидируем его до записи.
    compose_name = find_compose_filename(project_root)
    if compose_name and rel == compose_name:
        try:
            data = validate_compose_yaml(data.decode("utf-8")).encode("utf-8")
        except UnicodeDecodeError:
            raise StepError(
                "save_file", -1, title="Compose-файл",
                detail=f"{compose_name} не в кодировке UTF-8",
            )

    with _STORE_LOCK:
        existing_files = iter_project_files(stack_name)
        if not target.exists() and len(existing_files) >= MAX_PROJECT_FILES:
            raise StepError(
                "save_file", -1, title="Слишком много файлов",
                detail=f"в проекте уже {MAX_PROJECT_FILES} файлов",
            )
        old_size = target.stat().st_size if target.is_file() else 0
        current_total = sum(
            (_project_target(stack_name, p.as_posix()).stat().st_size
             for p in existing_files)
        )
        if current_total - old_size + len(data) > MAX_PROJECT_TOTAL_SIZE:
            raise StepError(
                "save_file", -1, title="Проект слишком большой",
                detail=f"суммарно больше {MAX_PROJECT_TOTAL_SIZE // (1024 * 1024)} МБ",
            )

        mode = (target.stat().st_mode & 0o777) if target.is_file() else 0o644
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent,
        )
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp_name, mode)
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    return {"name": stack_name, "path": rel, "fingerprint": project_fingerprint(stack_name)}


def delete_project_entry(
    name: str,
    rel_path: str,
    *,
    allow_directory: bool = True,
) -> Dict[str, Any]:
    """Удалить файл или каталог внутри проекта, не затрагивая runtime Docker.

    Путь повторно проверяется на уровне хранилища. Удаление через симлинк
    запрещено даже тогда, когда симлинк указывает обратно внутрь проекта.
    Основной Compose-файл определяется только через ``find_compose_filename``.
    """
    stack_name = validate_stack_name(name)
    rel_obj = safe_relative_path(rel_path)
    rel = rel_obj.as_posix()

    with _STORE_LOCK:
        project_root = _project_target(stack_name)
        lexical_target = project_root / Path(*rel_obj.parts)

        # resolve() защищает от выхода наружу, а отдельный проход запрещает сам
        # факт удаления через симлинк (включая симлинки, ведущие внутрь проекта).
        current = project_root
        for part in rel_obj.parts:
            current = current / part
            if current.is_symlink():
                raise StepError(
                    "delete_entry", -1, title="Путь в проекте",
                    detail="удаление через симлинк запрещено",
                )
        target = _project_target(stack_name, rel)

        if not lexical_target.exists():
            raise StepError(
                "delete_entry", -1, title="Файл или папка не найдены",
                detail=f"в проекте «{stack_name}» нет {rel}",
            )

        compose_name = find_compose_filename(project_root)
        if compose_name:
            compose_path = PurePosixPath(compose_name)
            removes_compose = (
                rel_obj == compose_path
                or (
                    lexical_target.is_dir()
                    and len(rel_obj.parts) < len(compose_path.parts)
                    and compose_path.parts[:len(rel_obj.parts)] == rel_obj.parts
                )
            )
            if removes_compose:
                raise StepError(
                    "delete_entry", -1, title="Нельзя удалить Compose-файл",
                    detail="основной Compose-файл обязателен для проекта",
                )

        if lexical_target.is_dir():
            if not allow_directory:
                raise StepError(
                    "delete_file", -1, title="Файл не найден",
                    detail=f"{rel} является папкой",
                )
            shutil.rmtree(target)
            kind = "directory"
        elif lexical_target.is_file():
            target.unlink()
            kind = "file"
        else:
            raise StepError(
                "delete_entry", -1, title="Нельзя удалить объект",
                detail=f"{rel} не является обычным файлом или папкой",
            )

    return {"name": stack_name, "path": rel, "kind": kind}


def delete_project_file(name: str, rel_path: str) -> str:
    """Совместимый API удаления одного не-Compose файла проекта."""
    removed = delete_project_entry(name, rel_path, allow_directory=False)
    return str(removed["path"])


def delete_stack(name: str) -> str:
    """Удалить проект из локальной библиотеки (на сервере ничего не трогаем)."""
    stack_name = validate_stack_name(name)
    directory = STORE_DIR / stack_name
    with _STORE_LOCK:
        if directory.is_dir():
            shutil.rmtree(directory, ignore_errors=True)
    return stack_name


# --------------------------------------------------
# Импорт ZIP-архива
# --------------------------------------------------

def _strip_common_root(names: List[str]) -> Optional[str]:
    """Если все файлы архива лежат в одном общем каталоге — вернуть его имя.

    ZIP вида `uptime-kuma/docker-compose.yml` распаковывается в корень проекта.
    """
    roots = set()
    for n in names:
        parts = [p for p in PurePosixPath(n).parts if p not in ("", ".")]
        if not parts:
            continue
        roots.add(parts[0] if len(parts) > 1 else "")
    if len(roots) == 1:
        only = roots.pop()
        return only or None
    return None


def _read_zip_project_details(data: bytes) -> Tuple[Dict[str, bytes], Optional[str]]:
    """Разобрать ZIP в {rel_path: bytes} с защитой от path traversal (§5).

    Отклоняет абсолютные пути, «..», симлинки. Снимает общий корневой каталог,
    если он один. Сам файл на диск не пишет — это делает write_project.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise StepError(
            "read_zip", -1, title="Повреждённый архив", detail=str(e)[:200],
        )
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if not infos:
            raise StepError(
                "read_zip", -1, title="Пустой архив", detail="в архиве нет файлов",
            )
        if len(infos) > MAX_PROJECT_FILES:
            raise StepError(
                "read_zip", -1, title="Слишком много файлов",
                detail=f"в архиве больше {MAX_PROJECT_FILES} файлов",
            )

        # Проверяем пути ДО распаковки (архив может быть враждебным).
        for info in infos:
            # Симлинки в ZIP: старший бит режима s_ifmt == 0xA000.
            if (info.external_attr >> 16) & 0xF000 == 0xA000:
                raise StepError(
                    "read_zip", -1, title="Симлинки запрещены",
                    detail=f"архив содержит симлинк: {info.filename}",
                )
            safe_relative_path(info.filename)

        root = _strip_common_root([i.filename for i in infos])
        out: Dict[str, bytes] = {}
        total = 0
        for info in infos:
            if info.file_size > MAX_PROJECT_FILE_SIZE:
                raise StepError(
                    "read_zip", -1, title="Файл слишком большой",
                    detail=f"{info.filename}: больше {MAX_PROJECT_FILE_SIZE // (1024 * 1024)} МБ",
                )
            total += info.file_size
            if total > MAX_PROJECT_TOTAL_SIZE:
                raise StepError(
                    "read_zip", -1, title="Архив слишком большой",
                    detail=f"распакованный размер больше {MAX_PROJECT_TOTAL_SIZE // (1024 * 1024)} МБ",
                )
            rel = safe_relative_path(info.filename)
            parts = list(rel.parts)
            if root and parts and parts[0] == root:
                parts = parts[1:]
            if not parts:
                continue
            out[PurePosixPath(*parts).as_posix()] = zf.read(info)
        if not out:
            raise StepError(
                "read_zip", -1, title="Пустой архив",
                detail="после нормализации путей не осталось файлов",
            )
        return out, root


def read_zip_project(data: bytes) -> Dict[str, bytes]:
    """Разобрать безопасный ZIP и вернуть нормализованные файлы проекта."""
    files, _root = _read_zip_project_details(data)
    return files


def _suggest_zip_stack_name(root: Optional[str], archive_name: str) -> str:
    """Безопасное имя проекта из общей папки ZIP либо имени архива."""
    raw = root or Path(archive_name or "project.zip").stem or "project"
    value = re.sub(r"[^a-z0-9_-]+", "-", str(raw).strip().lower()).strip("-_")
    value = value[:63].rstrip("-_") or "project"
    if not value[0].isalnum():
        value = ("project-" + value)[:63].rstrip("-_")
    return validate_stack_name(value)


def suggest_zip_stack_name(data: bytes, archive_name: str) -> str:
    """Проверить ZIP и определить имя проекта без записи на диск."""
    _files, root = _read_zip_project_details(data)
    return _suggest_zip_stack_name(root, archive_name)


def import_zip_new(data: bytes, archive_name: str, name: str = "") -> Dict[str, Any]:
    """Создать новый ZIP-проект, исключая замену/слияние существующего."""
    files, root = _read_zip_project_details(data)
    stack_name = validate_stack_name(name) if str(name or "").strip() else _suggest_zip_stack_name(root, archive_name)
    target = STORE_DIR / stack_name
    with _STORE_LOCK:
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Проект «{stack_name}» уже существует.")
        result = write_project(stack_name, files)
    result["suggested_name"] = stack_name
    return result


def import_zip(name: str, data: bytes) -> Dict[str, Any]:
    """Импортировать ZIP-архив как проект библиотеки."""
    return write_project(name, read_zip_project(data))


# --------------------------------------------------
# Сверка библиотеки с сервером (docs/compose-model.md §2, §4-5)
# --------------------------------------------------

def reconcile_stacks(
    library_list: List[Dict[str, Any]],
    server_list: List[Dict[str, Any]],
    ignored: Optional[List[str]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Сверить библиотеку Bot4VPS с реальным состоянием сервера.

    Чистая функция без SSH: на вход — list_stacks(), compose.list_server_stacks()
    и список игнор-ключей (project|working_dir, docs/compose-model.md §11).

    Идентичность развёртывания — (project, working_dir); имя — не
    идентификатор. Связь библиотека ↔ сервер устанавливается по имени ТОЛЬКО
    когда она однозначна: в библиотеке есть проект «name» и на сервере ровно
    одно развёртывание с этим именем. Несколько одноимённых развёртываний
    (конфликт имён) между собой не сливаются и с библиотекой не связываются —
    пользователь разбирается сам (удалить лишнее или проигнорировать).

    Игнорируемые развёртывания (ключ в ignored) исключаются из строк, а их
    имена НЕ считаются «занятыми»: если остальные развёртывания с этим именем
    нет, библиотечный проект получает честный статус absent, а не conflict.

    Возвращает ЕДИНЫЙ список строк таблицы (не три группы): каждая строка —
    один проект с точки зрения пользователя:
        {name, source, status, working_dir, key, containers_total,
         containers_running, in_library, lib_match, name_conflict,
         conflict_count, library, server}

    source:
        "server"  — развёртывание на сервере (связано с библиотекой или нет)
        "library" — только локальная копия, развёртывания на сервере нет
    status (docs/compose-model.md §4):
        "running"  — контейнеры работают
        "stopped"  — развёртывание есть, работающих контейнеров нет
        "absent"   — развёртывания нет, есть только локальная копия
        "conflict" — имя в библиотеке, на сервере несколько неигнорируемых
                     развёртываний с этим именем (строка-заглушка библиотечной
                     копии; установка из библиотеки заблокирована)
    lib_match: True/False по fingerprint конфиг-набора (§3); None — сравнить
    не удалось (серверные файлы не прочитаны или локальной копии нет).
    """
    lib_map = {s["name"]: s for s in library_list}
    ignored_set = set(ignored or [])

    # Игнорируемые развёртывания исключаются СРАЗУ: не дают строк, а их имена
    # не считаются «занятыми» — если других с этим именем нет, библиотечный
    # проект честно получает absent, а не conflict (§11).
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    for srv in server_list:
        name = srv.get("name")
        if not name or _server_ignore_key(srv) in ignored_set:
            continue
        by_name.setdefault(name, []).append(srv)

    rows: List[Dict[str, Any]] = []

    def lib_match_of(srv: Dict[str, Any], lib: Optional[Dict[str, Any]]) -> Optional[bool]:
        if lib is None:
            return None
        srv_fp = srv.get("fingerprint")
        lib_fp = lib.get("fingerprint")
        if not srv_fp or not lib_fp:
            return None
        return srv_fp == lib_fp

    # --- серверные развёртывания ---
    for name, deps in sorted(by_name.items()):
        lib = lib_map.get(name)
        for srv in deps:
            running = int(srv.get("containers_running") or 0)
            rows.append({
                "name": name,
                "source": "server",
                "status": "running" if running > 0 else "stopped",
                "working_dir": srv.get("working_dir"),
                "key": srv.get("key"),
                "containers_total": int(srv.get("containers_total") or 0),
                "containers_running": running,
                "in_library": lib is not None,
                "lib_match": lib_match_of(srv, lib),
                "name_conflict": len(deps) > 1,
                "conflict_count": len(deps),
                "library": lib,
                "server": srv,
            })

        # Конфликт имён: библиотечная копия отдельной строкой-заглушкой,
        # «Установить» для неё заблокирована (§4).
        if lib is not None and len(deps) > 1:
            rows.append({
                "name": name,
                "source": "library",
                "status": "conflict",
                "working_dir": None,
                "key": None,
                "containers_total": 0,
                "containers_running": 0,
                "in_library": True,
                "lib_match": None,
                "name_conflict": True,
                "conflict_count": len(deps),
                "library": lib,
                "server": None,
            })

    # --- только библиотека (на сервере видимых развёртываний нет) ---
    for name, lib in sorted(lib_map.items()):
        if name in by_name:
            continue
        rows.append({
            "name": name,
            "source": "library",
            "status": "absent",
            "working_dir": None,
            "key": None,
            "containers_total": 0,
            "containers_running": 0,
            "in_library": True,
            "lib_match": None,
            "name_conflict": False,
            "conflict_count": 0,
            "library": lib,
            "server": None,
        })

    rows.sort(key=lambda r: (r["name"], r.get("working_dir") or ""))
    return {"rows": rows}


def _server_ignore_key(srv: Dict[str, Any]) -> str:
    """Игнор-ключ серверной записи: «project|working_dir» (без config_files).

    Полный Deployment.key включает config_files — добавление override-файла
    меняло бы ключ, и игнор «слетал» бы. Для игнора достаточно стабильной
    пары (project, working_dir).
    """
    return f"{srv.get('name')}|{srv.get('working_dir')}"
