# -*- coding: utf-8 -*-
"""Приватный подпакет реализации сервиса Docker.

Структура:
    service.py       - контракт Service, действия очереди, sync/get_*
    lifecycle.py     - установка/удаление Docker Engine на сервере
    templates.py     - генерация /etc/docker/daemon.json
    validation.py    - валидаторы имени/образа/порта/env/restart
    stats.py         - парсеры docker ps / docker stats (без SSH)
    containers.py    - контейнеры: run/start/stop/restart/rm/logs
    images.py        - образы: list/pull/rmi/prune
    compose_store.py - ЛОКАЛЬНАЯ библиотека стеков + валидация YAML
                       (data/services/docker/compose/<stack>/docker-compose.yml)
    compose.py       - деплой стека на сервер и up/down/restart/logs
                       (/opt/bot4vps/<stack>/docker-compose.yml)

Два уровня хранения Compose (compose_store ↔ compose) не смешивать: первый —
persistent-библиотека Bot4VPS, второй — рабочая копия на управляемом сервере.
"""
from .service import Service

__all__ = ["Service"]
