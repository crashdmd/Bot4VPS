# -*- coding: utf-8 -*-
"""Шаблоны конфигов Docker (Phase 1: /etc/docker/daemon.json).

По образцу services/wireguard/impl/templates.create_server_config:
SFTP во /tmp + атомарный mv (секретов в шаблоне нет — рендер не нужен).
"""
from __future__ import annotations

from core.integrator import StepRunner
from core.ssh import private_remote_upload
import shlex

# Лог-ротация по умолчанию — защита от разбухания json-логов контейнеров.
# Докер читает daemon.json при старте демона.
_DAEMON_JSON = (
    '{\n'
    '  "log-driver": "json-file",\n'
    '  "log-opts": {\n'
    '    "max-size": "10m",\n'
    '    "max-file": "3"\n'
    '  }\n'
    '}\n'
)


def write_daemon_config(runner: StepRunner) -> None:
    """Записать /etc/docker/daemon.json с дефолтной лог-ротацией.

    Не перезаписывает существующий пользовательский конфиг — если файл уже
    есть (ручная настройка), шаг считаем выполненным и не трогаем.
    """
    exists = runner.probe("test -f /etc/docker/daemon.json && echo yes || echo no")
    if exists == "yes":
        runner.emit("• /etc/docker/daemon.json уже существует — пропускаем")
        runner.completed.append("daemon_config")
        return

    with private_remote_upload(runner.ssh, runner.server, _DAEMON_JSON) as tmp_path:
        runner.run(
            "daemon_config",
            f"install -d -m 755 /etc/docker && install -m 644 {shlex.quote(tmp_path)} /etc/docker/daemon.json",
            title="Создание /etc/docker/daemon.json (log-rotation)",
        )
