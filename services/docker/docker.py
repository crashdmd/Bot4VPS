# -*- coding: utf-8 -*-
"""Docker - тонкий файл-оркестратор (точка входа по конвенции services.<id>.<id>).

Реализация разбита по зонам ответственности в приватном подпакете impl/.
Публичный контракт модуля: class Service (наследник core.integrator.Service).
Web (docker.js) и будущий TG-хендлер работают через core.integrator, а не сюда.
"""
from __future__ import annotations

from .impl import Service

__all__ = ["Service"]
