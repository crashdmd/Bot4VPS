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
        if (directory / fname).is_file():
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


def iter_project_files(name: str) -> List[PurePosixPath]:
    """Все файлы проекта относительными POSIX-путями (рекурсивно, sorted)."""
    directory = stack_dir(name)
    if not directory.is_dir():
        return []
    out: List[PurePosixPath] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(directory).as_posix()
        out.append(PurePosixPath(rel))
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
    """SHA-256 по всем файлам проекта (путь + содержимое).

    Используется для сравнения локальной версии с развёрнутой на сервере (§23).
    Детерминирован: файлы обходятся в отсортированном порядке.
    """
    directory = stack_dir(name)
    h = hashlib.sha256()
    for rel in iter_project_files(name):
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
    """Записать/заменить один файл проекта (например .env), не трогая остальные."""
    stack_name = validate_stack_name(name)
    rel = safe_relative_path(rel_path).as_posix()
    directory = STORE_DIR / stack_name

    files: Dict[str, bytes] = {}
    if directory.is_dir():
        for existing in iter_project_files(stack_name):
            files[existing.as_posix()] = (directory / Path(*existing.parts)).read_bytes()
    files[rel] = data

    # Если правим основной Compose-файл — валидируем как Compose.
    compose_name = find_compose_filename(directory)
    if compose_name and rel == compose_name:
        files[rel] = validate_compose_yaml(data.decode("utf-8")).encode("utf-8")

    _write_files_atomic(stack_name, files)
    return {"name": stack_name, "path": rel, "fingerprint": project_fingerprint(stack_name)}


def delete_project_file(name: str, rel_path: str) -> str:
    """Удалить один файл проекта. Основной Compose-файл удалить нельзя."""
    stack_name = validate_stack_name(name)
    rel = safe_relative_path(rel_path).as_posix()
    directory = STORE_DIR / stack_name
    compose_name = find_compose_filename(directory)
    if compose_name and rel == compose_name:
        raise StepError(
            "delete_file", -1, title="Нельзя удалить Compose-файл",
            detail="основной Compose-файл обязателен для проекта",
        )
    files: Dict[str, bytes] = {}
    found = False
    for existing in iter_project_files(stack_name):
        key = existing.as_posix()
        if key == rel:
            found = True
            continue
        files[key] = (directory / Path(*existing.parts)).read_bytes()
    if not found:
        raise StepError(
            "delete_file", -1, title="Файл не найден",
            detail=f"в проекте «{stack_name}» нет файла {rel}",
        )
    _write_files_atomic(stack_name, files)
    return rel


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


def read_zip_project(data: bytes) -> Dict[str, bytes]:
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
        return out


def import_zip(name: str, data: bytes) -> Dict[str, Any]:
    """Импортировать ZIP-архив как проект библиотеки."""
    return write_project(name, read_zip_project(data))


# --------------------------------------------------
# Сверка библиотеки с сервером
# --------------------------------------------------

def reconcile_stacks(
    library_list: List[Dict[str, Any]],
    server_list: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Сверить библиотеку Bot4VPS с реальным состоянием сервера.

    Чистая функция без SSH: на вход — list_stacks() и compose.list_server_stacks().

    Ключ сопоставления — имя проекта, но серверный deployment уникален по
    (project, working_dir, config_files) (§14). Библиотечный проект связывается
    только с тем deployment'ом, который развёрнут Bot4VPS (managed=True, т.е.
    working_dir внутри REMOTE_ROOT). Deployment с тем же именем, но из другого
    каталога, остаётся отдельной записью в server_only.

    project_match (§23) считается по fingerprint: сервер отдаёт fingerprint
    своих файлов, библиотека — свой. None, если файлы сервера прочитать не удалось.

    Returns:
        {"both": [{name, library, server, project_match}],
         "library_only": [...], "server_only": [...]}
    """
    lib_map = {s["name"]: s for s in library_list}

    both: List[Dict[str, Any]] = []
    server_only: List[Dict[str, Any]] = []
    matched_lib_names = set()

    for srv in server_list:
        name = srv.get("name")
        lib = lib_map.get(name) if name else None
        # Связываем с библиотекой только managed-развёртывания (наш каталог).
        if lib is not None and srv.get("managed"):
            srv_fp = srv.get("fingerprint")
            lib_fp = lib.get("fingerprint")
            match: Optional[bool] = None
            if srv_fp and lib_fp:
                match = (srv_fp == lib_fp)
            both.append({
                "name": name,
                "library": lib,
                "server": srv,
                "project_match": match,
            })
            matched_lib_names.add(name)
        else:
            server_only.append(srv)

    library_only = [s for n, s in lib_map.items() if n not in matched_lib_names]
    library_only.sort(key=lambda s: s["name"])

    return {
        "both": both,
        "library_only": library_only,
        "server_only": server_only,
    }
