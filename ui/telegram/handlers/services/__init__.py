# -*- coding: utf-8 -*-
"""service-specific Telegram UI: контракт + per-service UI-модули.

Импорт этого пакета (он происходит, когда `service_handlers.py` делает
`from .services.base import ...`) регистрирует все известные ServiceUI как
side-effect. Саморегистрирующийся пакет — граф импортов ацикличен (см. _shared.py).

Добавить UI нового сервиса:
    1. core:    Service (контракт) — services/<id>/
    2. ui:      class FooUI(ServiceUI) в services/foo.py + register_service_ui(FooUI())
    3.          добавить `from . import foo` ниже
Без правки `service_handlers.py`.
"""
from .base import (  # noqa: F401
    CallbackCtx,
    DocumentCtx,
    MessageCtx,
    ServiceUI,
    all_service_uis,
    get_service_ui,
    register_service_ui,
)

# Side-effect: регистрация ServiceUI в реестре.
from . import wireguard  # noqa: F401
from . import docker  # noqa: F401
