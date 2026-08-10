# -*- coding: utf-8 -*-
"""WireGuard - тонкий файл-оркестратор.

Исторически весь сервис WireGuard жил в одном файле wireguard.py,
к которому привязаны handlers/integrator (импортируют Service).
После рефакторинга реализация разбита по зонам ответственности и
вынесена в приватный подпакет impl/. Этот файл сохранен
как обратно-совместимая точка входа - handlers ничего не меняют в коде.

Публичный контракт модуля: class Service (наследник core.integrator.Service).
Все остальное (lifecycle, profiles, migration, templates, validation,
network) - внутренняя кухня impl/ и снаружи не используется.
"""
from __future__ import annotations

from .impl import Service

__all__ = ["Service"]