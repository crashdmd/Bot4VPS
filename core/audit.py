"""Запись аудита: кто что сделал и чем это кончилось.

Тонкая обёртка над ``core.state_db.insert_audit`` (§8.1 плана): собирает
запись из актора текущего контекста (``core/actor``), маскирует параметры
**при записи** (§13) и кладёт строку в ``audit_records``.

Почему обёртка, а не вызовы ``insert_audit`` по месту: маскирование и
подстановка актора должны быть одинаковыми во всех точках эмиссии. Точка,
которая забудет маску, — это утечка секрета в БД, а точка, которая забудет
актора, — «system» вместо человека, то есть худший вид бага для аудита:
он выглядит правдоподобно.

**Аудит не имеет права сломать действие, которое записывает.** Ошибка
записи (битая БД, недоступный каталог) гасится здесь и печатается в
stdout: удаление сервера не должно падать из-за того, что не удалось
оставить пометку о нём.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, Dict, Mapping, Optional

from core.actor import Actor, ActorType, get_actor
from core.audit_actions import AuditAction, AuditResult
from core import state_db

NAME = "AUDIT"

# Чем заменяется секрет. Та же строка, что в ``core.telegram_health``:
# в логах и в аудите секрет выглядит одинаково.
MASK = "***"

# Потолки на значение в params. Размер пометки не должен зависеть от того,
# что в неё положили: список путей бэкапа на десятки тысяч строк превратил
# бы аудит в хранилище копий чужого вывода.
MAX_TEXT = 200
MAX_ITEMS = 20
MAX_DEPTH = 4

# Ключ считается секретным по имени: значения таких ключей не пишутся
# никогда, попадает только маска (§13). Список — про смысл, а не про
# конкретные поля панели: ``password_hash``, ``bot_token``, ``totp_secret``,
# ``recovery_codes``, ``private_key``, ``master_key`` ловятся все.
_SECRET_WORDS = (
    "password", "passwd", "passphrase", "token", "secret", "credential",
    "recovery", "private", "otp", "totp", "apikey", "api_key",
)
# Суффиксы имён, которые говорят «здесь значение, а не флаг»: ``ssh_key``,
# ``master_key``, ``api_key`` — секрет, а ``key_path`` — путь, и он нужен в
# истории как есть (маскировать путь к ключу значит потерять, каким ключом
# ходили).
_SECRET_SUFFIXES = ("_hash", "_pin", "_pwd", "_pass", "_key", "_code")

# Секреты, у которых имя безобидное, а значение — секрет по виду:
# зашифрованное (``enc1:``) и тело приватного ключа.
#
# Оба шаблона ищутся **внутри** текста, а не только в его начале: правило
# одно на оба (см. ``mask_text``), а в свободном тексте — в ошибке или в
# выводе задачи — секрет приходит посреди строки («ключ: …», «токен …
# отозван»). Якорь начала оставлял бы ``enc1:`` незамеченным ровно там,
# где он и появляется.
_ENC_RE = re.compile(r"enc1:")
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")


def mask_text(text: Any) -> str:
    """Замаскировать секреты внутри свободного текста (ошибки, вывод).

    Переиспользует существующее маскирование токена
    (``core.telegram_health.mask_bot_token``), чтобы в аудите и в логах
    секрет выглядел одинаково, и добавляет два случая, которых там нет:
    зашифрованное значение и тело приватного ключа.
    """
    value = str(text)
    for pattern in (_ENC_RE, _PRIVATE_KEY_RE):
        if pattern.search(value):
            return MASK
    try:
        from core.telegram_health import mask_bot_token

        value = mask_bot_token(value)
    except Exception:
        pass
    return value


def _secret_key(key: str) -> bool:
    """Секретный ли ключ по имени."""
    name = key.lower()
    if name in ("key", "secret", "token", "password"):
        return True
    if any(word in name for word in _SECRET_WORDS):
        return True
    return name.endswith(_SECRET_SUFFIXES)


def _scalar(value: Any) -> Any:
    """Привести значение к тому, что переживёт ``json.dumps``."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)[:MAX_TEXT]


def _mask_value(key: str, value: Any, depth: int) -> Any:
    if _secret_key(key) and not isinstance(value, bool):
        # Флаг (``token_set: true``) секретом не является: он говорит
        # «значение есть», а не «вот оно». Всё остальное под секретным
        # именем — маска, включая числа и None-подобные заглушки.
        return MASK
    if isinstance(value, str):
        if _ENC_RE.match(value) or _PRIVATE_KEY_RE.search(value):
            return MASK
        masked = mask_text(value)
        if depth >= MAX_DEPTH:
            return masked[:MAX_TEXT]
        return masked if len(masked) <= MAX_TEXT else masked[:MAX_TEXT] + "…"
    if depth >= MAX_DEPTH:
        return _scalar(value)
    if isinstance(value, Mapping):
        return {str(k): _mask_value(str(k), v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        masked_items = [_mask_value(key, item, depth + 1) for item in items[:MAX_ITEMS]]
        if len(items) > MAX_ITEMS:
            masked_items.append(f"… ещё {len(items) - MAX_ITEMS}")
        return masked_items
    return _scalar(value)


def mask_params(params: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Маскировать параметры действия **до** записи в БД (§13).

    Возвращает новый словарь: исходный не меняется — он принадлежит
    вызывающему коду и может ещё использоваться (например, уйти в событие).
    Пустой словарь остаётся пустым, ``None`` — тоже: «параметров нет» и
    «параметры есть, но пустые» в аудите не различимы и не должны быть.
    """
    if not params:
        return {}
    return _mask_value("params", dict(params), 0)


def new_op_id() -> str:
    """Сквозной id операции. Конвенция та же, что у бэкапа (``op-<hex>``)."""
    return f"op-{uuid.uuid4().hex}"


def _value_of(value: Any) -> str:
    """Строковое значение enum'а.

    ``str(AuditAction.SERVER_ADD)`` в Python 3.11+ даёт
    ``AuditAction.SERVER_ADD`` — в колонку обязан попасть ``server.add``,
    иначе фильтры по ``action`` перестанут сходиться.
    """
    return str(getattr(value, "value", value))


def record(
    action: Any,
    *,
    result: Any,
    server_id: Optional[str] = None,
    server_name: Optional[str] = None,
    op_id: Optional[str] = None,
    event_id: Optional[str] = None,
    task_id: Optional[str] = None,
    error: Optional[Any] = None,
    failure_detail: Optional[Any] = None,
    params: Optional[Mapping[str, Any]] = None,
    actor: Optional[Actor] = None,
    ts: Optional[int] = None,
) -> str:
    """Записать пометку аудита и вернуть её id ("" — записать не удалось).

    ``actor`` подставляется из контекста (``core.actor``), но может быть
    передан явно: так пишутся финалы операций, доживших до конца в другом
    процессе (обновление панели, §16.3) — актор берётся из снимка, а не из
    того, кто оказался рядом в момент завершения.
    """
    try:
        who = actor or get_actor()
        row = {
            "id": uuid.uuid4().hex,
            "ts": int(ts if ts is not None else time.time()),
            "actor_type": who.type,
            "actor_id": who.id,
            "actor_role": who.role,
            "actor_ip": who.ip,
            "server_id": server_id,
            "server_name": server_name,
            "action": _value_of(action),
            "result": _value_of(result),
            "error": (mask_text(error)[:500] or None) if error else None,
            "failure_detail": (mask_text(failure_detail).strip()[:500] or None)
            if failure_detail else None,
            "op_id": op_id,
            "event_id": event_id,
            "task_id": task_id,
            "params": (
                json.dumps(mask_params(params), ensure_ascii=False, sort_keys=True)
                if params
                else None
            ),
        }
        state_db.insert_audit(row)
        return row["id"]
    except Exception as exc:  # аудит не ломает записываемое действие
        print(f"[{NAME}] запись не удалась: {exc}", flush=True)
        return ""


def snapshot(actor: Optional[Actor] = None) -> Dict[str, Any]:
    """Снимок актора для хранения рядом с операцией (§6: снимок, не ссылка)."""
    return (actor or get_actor()).to_dict()


def from_snapshot(data: Any) -> Actor:
    """Восстановить актора из снимка (для финалов в другом процессе)."""
    return Actor.from_dict(data if isinstance(data, dict) else None)


def has_final(op_id: Optional[str]) -> bool:
    """Есть ли у операции финальная пометка (``ok``/``failed``/``cancelled``).

    Пару ``started`` → финал закрывают разные процессы (обновление панели,
    смена её порта), и каждый из них может увидеть исход первым. Проверка
    делает закрытие идемпотентным: у операции ровно один финал.
    """
    if not op_id:
        return False
    try:
        rows = state_db.iter_audit(op_id=op_id, limit=5)
    except Exception:
        return False
    return any(row.get("result") != AuditResult.STARTED.value for row in rows)


def inherit_actor(op_id: Optional[str]) -> Optional[Actor]:
    """Актор, начавший операцию ``op_id`` — по её записи ``started``.

    Нужен финалам, которые пишет уже другой процесс: self-restore и
    обновление панели перезапускают её, и в новом процессе контекста
    нажавшего нет. Актор берётся из **снимка** в записи ``started`` — это
    не ссылка на текущие права, а то же самое, что записано в истории.

    ``None`` — «начала операции в БД нет» (её не писали или БД недоступна):
    отсутствие данных и ``system`` — разные ответы, и что писать в этом
    случае, решает вызывающий.
    """
    if not op_id:
        return None
    try:
        rows = state_db.iter_audit(op_id=op_id, limit=5)
    except Exception:
        return None
    for row in rows:  # свежие сверху: у завершающейся операции это ``started``
        if row.get("result") == AuditResult.STARTED.value:
            return Actor(
                type=row.get("actor_type") or ActorType.SYSTEM.value,
                id=row.get("actor_id"),
                role=row.get("actor_role"),
                ip=row.get("actor_ip"),
            )
    return None


__all__ = [
    "MASK",
    "mask_params",
    "mask_text",
    "new_op_id",
    "record",
    "snapshot",
    "from_snapshot",
    "has_final",
    "inherit_actor",
    "AuditAction",
    "AuditResult",
]
