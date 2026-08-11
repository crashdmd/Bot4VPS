# -*- coding: utf-8 -*-
"""Операции над контейнерами Docker (run/start/stop/restart/rm/logs).

По образцу services/wireguard/impl/profiles.py: SSH только через StepRunner +
exec_sudo, своё sudo/экранирование не пишем. Валидация входов — в validation.py
(до любых SSH-записей). Управляемые ботом контейнеры помечаются лейблом
bot4vps.managed=true (managed-флаг из on-disk маркера, не из БД).
"""
from __future__ import annotations

import shlex
from typing import Any, Dict, List

from core.integrator import StepRunner
from core.ssh import create_ssh_client, exec_sudo

from . import stats, validation


def _build_run_cmd(name: str, image: str, ports: List[str], envs: List[str], restart: str) -> str:
    """Собрать безопасную строку `docker run -d`. Каждый пользовательский токен —
    через shlex.quote (валидация уже прошла, quote — второй барьер)."""
    parts: List[str] = ["docker", "run", "-d"]
    parts += ["--name", shlex.quote(name)]
    # Managed-маркер: по нему UI отличает «наши» контейнеры от чужих.
    parts += ["--label", shlex.quote(f"{stats.MANAGED_LABEL}=true")]
    # restart: "no" — дефолт Docker, но явно указываем если не пусто.
    # Docker принимает --restart=policy (без пробела), validate_restart уже проверил.
    if restart:
        parts += [f"--restart={restart}"]
    for p in ports:
        parts += ["-p", shlex.quote(p)]
    for e in envs:
        parts += ["-e", shlex.quote(e)]
    parts.append(shlex.quote(image))
    return " ".join(parts)


def run_container(server: dict, params: Dict[str, Any], emit) -> Dict[str, str]:
    """Создать и запустить контейнер из провалидированных параметров."""
    name = validation.validate_name(params.get("name"))
    image = validation.validate_image(params.get("image"))
    ports = validation.validate_ports(params.get("ports"))
    envs = validation.validate_envs(params.get("env"))
    restart = validation.validate_restart(params.get("restart"))

    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    try:
        runner.run(
            "pull_image", f"docker pull {shlex.quote(image)}",
            title=f"Загрузка образа «{image}»",
        )
        runner.run(
            "run_container", _build_run_cmd(name, image, ports, envs, restart),
            title=f"Запуск контейнера «{name}»",
        )
    finally:
        ssh.close()
    return {"name": name, "image": image}


def _simple_action(server: dict, action: str, name: str, title: str, emit,
                   extra: str = "") -> None:
    """Обёртка для start/stop/restart/rm: один docker-подкоманд по имени."""
    name = validation.validate_name(name)
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    try:
        cmd = f"docker {action} {extra} {shlex.quote(name)}".replace("  ", " ").strip()
        runner.run(f"{action}_container", cmd, title=title)
    finally:
        ssh.close()


def start_container(server: dict, name: str, emit) -> None:
    _simple_action(server, "start", name, f"Запуск контейнера «{name}»", emit)


def stop_container(server: dict, name: str, emit) -> None:
    _simple_action(server, "stop", name, f"Остановка контейнера «{name}»", emit)


def restart_container(server: dict, name: str, emit) -> None:
    _simple_action(server, "restart", name, f"Перезапуск контейнера «{name}»", emit)


def remove_container(server: dict, name: str, emit) -> None:
    # -f: остановить и удалить одним шагом (том/данные не трогаем — только контейнер).
    _simple_action(server, "rm", name, f"Удаление контейнера «{name}»", emit, extra="-f")


def fetch_logs(server: dict, name: str, tail: int = 200) -> str:
    """Прочитать последние N строк логов контейнера (read-only, без StepRunner)."""
    name = validation.validate_name(name)
    try:
        tail_n = int(tail)
    except (TypeError, ValueError):
        tail_n = 200
    tail_n = max(1, min(tail_n, 2000))
    ssh = create_ssh_client(server)
    try:
        _, out, err = exec_sudo(
            ssh, server,
            f"docker logs --tail {tail_n} {shlex.quote(name)} 2>&1 || true",
        )
        return out or err or ""
    finally:
        ssh.close()
