"""Действующий субъект операции: кто именно выполняет действие.

Единственное место, где живёт понятие «актор» (см.
``plans/AUDIT_AND_METRICS_PLAN.md``, §6). В запись аудита попадает **снимок**
актора на момент действия: тип интерфейса, логин, роль, IP. Снимок, а не
ссылка — смена роли задним числом не должна переписывать историю.

Актор лежит в ``contextvars`` и потому виден вниз по стеку вызовов без
протаскивания параметра через десятки функций. Здесь же — обёртка
``in_thread_context`` для ловушки, ради которой этот модуль и существует:

``contextvars`` распространяются на ``asyncio.to_thread`` и
``anyio.to_thread.run_sync`` (он же ``starlette.concurrency.run_in_threadpool``,
через который FastAPI гоняет синхронные эндпоинты) — но **НЕ** на
``ThreadPoolExecutor.submit`` и ``loop.run_in_executor``. Прямые пулы в
проекте есть (мониторинг, Quick Setup), и без обёртки актор теряется
**молча**: в аудите вместо пользователя оказался бы ``system`` — худший
вид бага для аудита, потому что выглядит правдоподобно.

Дефолт — ``system``: если действие инициировано джобой или планировщиком,
актор не выставляется вовсе.
"""
from __future__ import annotations

import contextvars
import functools
import getpass
import socket
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional


class ActorType(str, Enum):
    """Интерфейс, через который пришло действие."""

    WEB = "web"
    TG = "tg"
    CLI = "cli"
    SYSTEM = "system"


class ActorRole(str, Enum):
    """Роль актора — словарь, а не свободная строка.

    Иначе через полгода ``actor_role`` станет кашей из «админ», «admin»,
    «Администратор». На сегодня словарь минимальный: в панели один
    администратор. ``operator`` / ``observer`` добавятся сюда вместе с
    логикой прав, но не раньше — права по ролям в этом этапе не
    подключаются (§16.6).
    """

    ADMIN = "admin"


@dataclass(frozen=True)
class Actor:
    """Снимок действующего субъекта.

    Поля намеренно совпадают с колонками ``audit_records``
    (``actor_type`` / ``actor_id`` / ``actor_role`` / ``actor_ip``), поэтому
    ``to_dict()`` кладётся в запись без переупаковки. Тип и роль —
    ``str``-значения enum'ов: запись сериализуема и в JSON, и в TEXT sqlite.
    """

    type: str = ActorType.SYSTEM.value
    id: Optional[str] = None
    role: Optional[str] = None
    ip: Optional[str] = None

    # ----------------------------------------------------------
    # Фабрики: единственный способ собрать актора (см. §6.2).
    # ----------------------------------------------------------

    @classmethod
    def system(cls) -> "Actor":
        """Джобы, планировщик, фоновые задачи — «действовала панель»."""
        return cls(type=ActorType.SYSTEM.value)

    @classmethod
    def web(
        cls,
        user: Optional[str],
        *,
        role: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> "Actor":
        """Web-сессия. Без логина (выключенная авторизация) — вход есть,
        имени нет: роль не выдумываем, иначе в истории появился бы
        «админ», которого никто не предъявлял."""
        if not user:
            return cls(type=ActorType.WEB.value, ip=ip)
        return cls(
            type=ActorType.WEB.value,
            id=str(user),
            role=role or ActorRole.ADMIN.value,
            ip=ip,
        )

    @classmethod
    def telegram(cls, user_id: Any) -> "Actor":
        """Telegram-бот. Роль та же, что у web: бот отвечает только
        allowlist'у (``core.auth.is_allowed``), а администратор сегодня
        один — множественность пользователей появится вместе с правами."""
        return cls(
            type=ActorType.TG.value,
            id=str(user_id),
            role=ActorRole.ADMIN.value,
        )

    @classmethod
    def cli(cls) -> "Actor":
        """Консоль на хосте. Роль — NULL осознанно: это аварийный вход
        локального суперпользователя, а не «админ панели»; маппить его в
        admin значило бы записать в историю неправду (§16.6)."""
        try:
            user = getpass.getuser()
        except Exception:
            user = "?"
        try:
            host = socket.gethostname()
        except Exception:
            host = "?"
        return cls(type=ActorType.CLI.value, id=f"{user}@{host}")

    # ----------------------------------------------------------
    # Сериализация
    # ----------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "id": self.id,
            "role": self.role,
            "ip": self.ip,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "Actor":
        """Восстановить снимок (история задач, запись аудита, БД)."""
        if not isinstance(data, dict) or not data:
            return cls.system()
        return cls(
            type=str(data.get("type") or ActorType.SYSTEM.value),
            id=data.get("id") or None,
            role=data.get("role") or None,
            ip=data.get("ip") or None,
        )


# Актор текущего контекста. None = «никто не выставлял» = system.
_ACTOR: contextvars.ContextVar[Optional[Actor]] = contextvars.ContextVar(
    "bot4vps_actor", default=None
)


def get_actor() -> Actor:
    """Актор текущего контекста; по умолчанию — ``system``.

    Никогда не возвращает None: вызывающему коду не нужно думать про
    «а актор вообще есть?» — на то и дефолт.
    """
    return _ACTOR.get() or Actor.system()


def set_actor(actor: Optional[Actor]) -> contextvars.Token:
    """Выставить актора на время обработки (вход в панель: web/tg/cli)."""
    return _ACTOR.set(actor)


def reset_actor(token: contextvars.Token) -> None:
    """Снять ранее выставленного актора (симметрично ``set_actor``)."""
    _ACTOR.reset(token)


def in_thread_context(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Обернуть функцию, уходящую в пул потоков, чтобы актор не потерялся.

    Снимок контекста берётся **здесь**, в вызывающем потоке (до ``submit``);
    в рабочем потоке выполняется копия снимка. Копия на задачу, а не общий
    снимок на всех: одну и ту же ``Context`` нельзя входить параллельно из
    нескольких потоков (RuntimeError), а ``ex.map``/``submit`` такую
    параллельность дают легко.

    Использование::

        with ThreadPoolExecutor(max_workers=n) as ex:
            list(ex.map(in_thread_context(work), items))
    """
    ctx = contextvars.copy_context()

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return ctx.copy().run(fn, *args, **kwargs)

    return wrapper
