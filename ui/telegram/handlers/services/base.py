# -*- coding: utf-8 -*-
"""Базовый контракт для service-specific Telegram UI.

`service_handlers.py` — тонкий диспетчер: парсит callback, ищет ServiceUI по
service_id и делегирует заявленные op. Если у сервиса нет своего UI (или он не
заявил op) — рендерит generic-карточку из manifest + get_status + get_actions и
generic install wizard из params_schema.

Этот модуль — НИЖНИЙ слой: только stdlib/typing, никаких ui/core/service-импортов.
На него ссылается `_shared`, `wireguard` и сам диспетчер; отсутствие зависимостей
вверх гарантирует ацикличность графа импортов.

Добавление нового сервиса с богатым UI:
    1. core: Service (контракт) — уже через services/<id>/
    2. UI:   class FooUI(ServiceUI): service_id="foo"; claims_ops={...}; ...
    3.       register_service_ui(FooUI())  (в своём модуле, импорт через __init__)
Без правки `service_handlers.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Iterable, Optional


@dataclass(frozen=True)
class CallbackCtx:
    """Контекст одного inline-callback для ServiceUI.handle_callback.

    Иммутабелен — UI не может «подменить» op/service_id по ходу обработки.
    """
    op: str
    query: object               # telegram.CallbackQuery
    user_id: int
    service_id: str
    server_id: str
    name: Optional[str] = None
    src: Optional[str] = None


@dataclass(frozen=True)
class MessageCtx:
    """Контекст текстового сообщения для ServiceUI.handle_message.

    service_id/server_id UI достаёт из своего state-dict'а — это его приватное дело.
    """
    update: object              # telegram.Update
    context: object             # ContextTypes.DEFAULT_TYPE
    user_id: int


@dataclass(frozen=True)
class DocumentCtx:
    """Контекст присланного документа для ServiceUI.handle_document.

    `data` — УЖЕ скачанные байты: загрузку из Telegram делает transport-слой
    (диспетчер), а не сервисный UI. Иначе каждый ServiceUI начал бы сам ходить
    в Telegram API, и контракт снова оказался бы загрязнён транспортом.

    UI получает только то, что ему нужно для решения: имя файла (YAML или ZIP?),
    содержимое и `message` для ответа пользователю.
    """
    update: object              # telegram.Update
    context: object             # ContextTypes.DEFAULT_TYPE
    user_id: int
    filename: str
    data: bytes


class ServiceUI:
    """Опциональный Telegram-UI сервисного слоя.

    Сервис может вовсе не иметь UI — тогда диспетчер показывает generic-карточку
    и generic install wizard (работает для любого Service «из коробки»). Чтобы
    дать сервису богатый UI — наследуемся, задаём `service_id` и `claims_ops`,
    реализуем `handle_callback` (и при необходимости `handle_message`/`owns_message`).
    """

    service_id: ClassVar[str] = ""
    claims_ops: ClassVar[set] = set()

    #: Сервис сам рисует хаб раздела (вместо generic «Полная проверка /
    #: Установить / Управление»). Диспетчер при `tasks_svc:<id>` делегирует ему
    #: op "hub" вместо generic-хаба.
    owns_hub: ClassVar[bool] = False

    #: Куда возвращает «❌ Нет» в generic-подтверждении удаления сервиса.
    #: По умолчанию "settings" — экран настроек, откуда кнопка удаления и растёт.
    #: Если у сервиса нет "settings" (кнопка удаления живёт прямо на карточке
    #: сервера), нужно переопределить на op, который UI реально заявляет —
    #: иначе отказ от удаления упрётся в «операция недоступна».
    cancel_remove_op: ClassVar[str] = "settings"

    def claims(self, op: str) -> bool:
        """Перехватывать ли этот op. По умолчанию — membership в claims_ops.

        Метод (а не статичный set) — чтобы в будущем UI мог решать динамически
        (напр. не перехватывать op в особом состоянии сервиса).
        """
        return op in self.claims_ops

    async def handle_callback(self, ctx: CallbackCtx) -> bool:
        """Обработать перехваченный callback. True = обработано.

        False трактуется как «не обработано» (баг/пропущенная ветка) — диспетчер
        залогирует warning и попытается generic-fallback. Это страховка от
        регрессий при добавлении новых op.
        """
        return True

    def owns_message(self, user_id: int) -> bool:
        """Есть ли pending text-flow для user_id. Cheap predicate.

        Вызывается на КАЖДОМ текстовом сообщении пользователя (до handle_message),
        поэтому должен быть быстрым и не иметь побочных эффектов.
        """
        return False

    async def handle_message(self, ctx: MessageCtx) -> bool:
        """Обработать текстовый ввод многошагового flow. True = обработано."""
        return False

    def owns_document(self, user_id: int) -> bool:
        """Ждёт ли сервис документ от user_id. Cheap predicate.

        Проверяется до скачивания файла: если никто документ не ждёт, transport
        не тратит трафик на загрузку.
        """
        return False

    async def handle_document(self, ctx: DocumentCtx) -> bool:
        """Обработать присланный документ (байты уже скачаны). True = обработано."""
        return False


# --------------------------------------------------------------
# Реестр (идемпотентный по service_id; повторная регистрация перезаписывает)
# --------------------------------------------------------------

_REGISTRY: "dict[str, ServiceUI]" = {}


def register_service_ui(ui: ServiceUI) -> None:
    assert getattr(ui, "service_id", ""), "ServiceUI.service_id должен быть задан"
    _REGISTRY[ui.service_id] = ui


def get_service_ui(service_id: str) -> Optional[ServiceUI]:
    return _REGISTRY.get(service_id)


def all_service_uis() -> Iterable[ServiceUI]:
    return _REGISTRY.values()
