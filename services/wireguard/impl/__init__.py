# -*- coding: utf-8 -*-
"""Приватный подпакет реализации сервиса WireGuard.

Не импортируется handlers напрямую - они работают через тонкий
оркестратор wireguard.py (родственный файл на уровень выше),
который реэкспортит Service.

Структура:
    service.py      - контракт Service, действия очереди, sync/get_*/fetch
    lifecycle.py    - установка/удаление сервиса на сервере
    profiles.py     - add/remove/toggle клиентских профилей
    migration.py    - перенос классического wg0.conf -> peers/*.conf
    templates.py    - генерация wg0.conf / clients/<name>.conf
    validation.py   - валидация параметров и входных строк
    network.py      - выделение IP клиенту
"""
from .service import Service

__all__ = ["Service"]