# -*- coding: utf-8 -*-
"""3x-ui - тонкий файл-оркестратор (точка входа по конвенции services.<id>.<id>).

Реализация разбита по зонам ответственности в приватном подпакете impl/.
Публичный контракт модуля: class Service (наследник core.integrator.Service).
Web (3xui.js) и будущий TG-хендлер работают через core.integrator, а не сюда.

Паттерн повторяет services/docker/docker.py и services/wireguard/wireguard.py.
"""
from __future__ import annotations

from .impl import Service

__all__ = ["Service"]
