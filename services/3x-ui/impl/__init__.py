# -*- coding: utf-8 -*-
"""Приватный подпакет реализации сервиса 3x-ui.

Не импортируется handlers напрямую — они работают через тонкий
оркестратор 3x-ui.py (родственный файл на уровень выше),
который реэкспортит Service.

Структура:
    service.py      - контракт Service, действия очереди, sync/get_*/fetch
    lifecycle.py    - установка/удаление/обновление на сервере (этап 2)
    installer.py    - тонкий установщик: раскладка офф-скрипта (этап 2)
    releases.py     - GitHub-каталог релизов (releases/latest redirect-приём)
    release_cache.py- локальный кэш артефактов data/services/3x-ui/version/
    validation.py   - валидация параметров и входных строк
"""
from .service import Service

__all__ = ["Service"]
