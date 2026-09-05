"""Реестр занятости SSH-ключей по серверам (v28).

Локальный файл ``keys/registry.json``:

    {"<server_id>": {"<username>": ["SHA256:fp", ...]}}

Хранятся SHA256 fingerprints публичных частей (переименование файла ключа
не меняет fingerprint; сам открытый ключ секретом не является).

Назначение — быстрые сверки «кем занят ключ» без SSH-подключений:
- пользователь без sudo не сможет активировать ключ, уже используемый
  другим пользователем (реестр знает это без чтения чужих authorized_keys);
- список свободных ключей строится по реестру;
- SSH-скан authorized_keys на сервере (требует sudo) используется только
  для синхронизации реестра с реальным состоянием — при ключевых
  операциях на активном сервере и фоновым проходом раз в час.

Надёжность:
- запись только через ``atomic_write_json`` (tmp + fsync + os.replace):
  частичная запись физически невозможна;
- все изменения точечные: read-modify-write под flock (sidecar
  ``registry.json.lock`` + RLock), логика меняет только свою секцию,
  данные других серверов не перезатираются;
- самолечение: битый JSON → файл целиком в карантин, реестр стартует
  с пустого; отдельные битые записи (не-словарь у сервера, не-список у
  пользователя, кривой fingerprint) вычищаются, остальное сохраняется
  и файл переписывается в исправленном виде;
- ошибка реестра НИКОГДА не блокирует ключевые операции: все публичные
  функции глотают исключения и возвращают безопасное значение.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from core.json_store import atomic_write_json, locked, quarantine

try:
    import fcntl  # noqa: F401  # проверка доступности в locked()
except ImportError:  # pragma: no cover - прод Bot4VPS работает на Linux
    fcntl = None

# SHA256 fingerprint: base64 без padding (32 байта → 43 символа).
# Диапазон длины расширен намеренно: 16..86 символов.
_FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{16,86}$")

_REGISTRY_NAME = "registry.json"

_thread_lock = threading.RLock()


def _keys_dir() -> Path:
    # В проде /opt/bot4vps/keys; в dev — рядом с установкой.
    # Своя копия (а не импорт из ssh_access), чтобы избежать циклической
    # зависимости: ssh_access импортирует этот модуль для сверок.
    for candidate in (Path("/opt/bot4vps/keys"), Path(__file__).resolve().parents[2] / "keys"):
        if candidate.is_dir():
            return candidate
    return Path("/opt/bot4vps/keys")


def _registry_path() -> Path:
    return _keys_dir() / _REGISTRY_NAME


def _lock_path() -> Path:
    return _keys_dir() / (_REGISTRY_NAME + ".lock")


def _valid_fingerprint(value: Any) -> bool:
    return isinstance(value, str) and bool(_FINGERPRINT_RE.match(value))


# -- чтение с самолечением --


def _heal(raw: Any) -> tuple[dict[str, dict[str, list[str]]], bool]:
    """Привести сырой JSON к рабочей структуре; bool — были ли исправления.

    Битые куски вычищаются, валидные сохраняются (частичное восстановление
    вместо потери всего файла). Возврат ``None`` вместо dict — сигнал
    «файл неисправим целиком», обрабатывает вызывающий.
    """
    if not isinstance(raw, dict):
        return {}, False
    cleaned: dict[str, dict[str, list[str]]] = {}
    fixed = False
    for server_id, users in raw.items():
        if not isinstance(server_id, str) or not server_id or not isinstance(users, dict):
            fixed = True
            continue
        user_map: dict[str, list[str]] = {}
        for username, fingerprints in users.items():
            if not isinstance(username, str) or not username or not isinstance(fingerprints, list):
                fixed = True
                continue
            valid = [f for f in fingerprints if _valid_fingerprint(f)]
            if len(valid) != len(fingerprints) or len(set(valid)) != len(valid):
                fixed = True
            if valid:
                user_map[username] = sorted(set(valid))
        if user_map:
            cleaned[server_id] = user_map
        else:
            if users:
                fixed = True
    return cleaned, fixed


def _load_unlocked() -> dict[str, dict[str, list[str]]]:
    """Прочитать реестр под lock; битый файл — в карантин, старт с пустого.

    Вызывается ТОЛЬКО внутри ``locked()``.
    """
    path = _registry_path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"[KEY REGISTRY] Не удалось прочитать {path}: {exc}. "
            "Файл перенесён в карантин, реестр стартует с пустого.",
            flush=True,
        )
        quarantine(path)
        return {}
    if not isinstance(raw, dict):
        print(
            f"[KEY REGISTRY] {path} должен содержать JSON-объект. "
            "Файл перенесён в карантин, реестр стартует с пустого.",
            flush=True,
        )
        quarantine(path)
        return {}
    cleaned, fixed = _heal(raw)
    if fixed:
        # Самолечение сохраняется на диск: частичные повреждения
        # вычищаются, валидные данные остальных серверов сохраняются.
        print(
            f"[KEY REGISTRY] {path.name}: повреждённые записи исправлены, "
            "файл переписан.",
            flush=True,
        )
        try:
            atomic_write_json(path, cleaned)
        except Exception:
            # Не смогли переписать — работаем на исправленной копии в памяти.
            pass
    return cleaned


def _mutate(
    server_id: str,
    fn: Callable[[dict[str, list[str]]], dict[str, list[str]]],
) -> bool:
    """Точечный read-modify-write секции одного сервера под lock.

    На диск уходит весь документ, но меняется только секция ``server_id``
    (fn применяется к её копии); данные других серверов проходят как есть.
    Ошибки глотаются: реестр не должен блокировать ключевые операции.
    """
    try:
        with locked(_lock_path(), _thread_lock):
            current = _load_unlocked()
            section = current.get(server_id) or {}
            updated = fn(json.loads(json.dumps(section)))  # глубокая копия
            if updated:
                current[server_id] = updated
            else:
                current.pop(server_id, None)
            atomic_write_json(_registry_path(), current)
            return True
    except Exception as exc:
        print(f"[KEY REGISTRY] Ошибка обновления реестра: {exc}", flush=True)
        return False


# -- публичный API (никогда не бросает исключений) --


def record(server_id: str, username: str, fingerprint: str) -> bool:
    """Записать, что пользователь сервера использует ключ с этим fingerprint."""
    if not _valid_fingerprint(fingerprint) or not server_id or not username:
        return False
    return _mutate(
        server_id,
        lambda section: {**section, username: sorted(set(section.get(username, []) + [fingerprint]))},
    )


def forget(server_id: str, username: str, fingerprint: str) -> bool:
    """Вычеркнуть один fingerprint пользователя; пустые секции удаляются."""
    if not server_id or not username:
        return False

    def _drop(section: dict[str, list[str]]) -> dict[str, list[str]]:
        fps = [f for f in section.get(username, []) if f != fingerprint]
        if fps:
            section[username] = fps
        else:
            section.pop(username, None)
        return section

    return _mutate(server_id, _drop)


def forget_user(server_id: str, username: str) -> bool:
    """Удалить пользователя целиком (все его fingerprints)."""

    def _drop(section: dict[str, list[str]]) -> dict[str, list[str]]:
        section.pop(username, None)
        return section

    return _mutate(server_id, _drop)


def forget_server(server_id: str) -> bool:
    """Удалить сервер из реестра (при удалении сервера из панели)."""
    return _mutate(server_id, lambda section: {})


def replace_server(server_id: str, user_to_fingerprints: dict[str, list[str]]) -> bool:
    """Синхронизация секции сервера с истиной (SSH-скан authorized_keys).

    Точечно: заменяется только секция ``server_id``, остальные серверы
    не перезатираются.
    """
    if not server_id:
        return False
    cleaned: dict[str, list[str]] = {}
    for username, fingerprints in (user_to_fingerprints or {}).items():
        valid = sorted({f for f in fingerprints if _valid_fingerprint(f)})
        if username and valid:
            cleaned[username] = valid
    return _mutate(server_id, lambda section: cleaned)


def server_users(server_id: str) -> dict[str, list[str]]:
    """Полная секция сервера: {username: [fingerprints]}. Пустая — если нет."""
    try:
        with locked(_lock_path(), _thread_lock):
            data = _load_unlocked()
        section = data.get(server_id) or {}
        return {u: list(fps) for u, fps in section.items()}
    except Exception:
        return {}


def users_of(server_id: str, fingerprint: str) -> list[str]:
    """Все пользователи сервера, у которых записан этот fingerprint."""
    if not _valid_fingerprint(fingerprint):
        return []
    return sorted(
        u for u, fps in server_users(server_id).items() if fingerprint in fps
    )


def find_owner(
    server_id: str,
    fingerprint: str,
    exclude_user: Optional[str] = None,
) -> Optional[str]:
    """Пользователь, уже использующий ключ; None — ключ свободен.

    ``exclude_user`` — сам кандидат (свой собственный ключ не считается
    занятым).
    """
    users = users_of(server_id, fingerprint)
    for username in users:
        if username != exclude_user:
            return username
    return None
