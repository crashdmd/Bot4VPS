# -*- coding: utf-8 -*-
"""Установка/удаление Docker Engine на сервере (Phase 1).

Установка — через официальный скрипт get.docker.com (ставит apt-репозиторий + GPG,
тянет compose-плагин, корректно отрабатывает уже установленный Docker).
Удаление — purge пакетов; /var/lib/docker (образы/тома/контейнеры) НЕ трогаем.

По образцу services/wireguard/impl/lifecycle.py (StepRunner + exec_sudo + soft-хелперы).
"""
from __future__ import annotations

from typing import Any, Dict

from core.integrator import StepError, StepRunner
from core.ssh import create_ssh_client, exec_sudo

from . import templates

# Пакеты, которые ставит get.docker.com и которые мы сносим при удалении.
_DOCKER_PACKAGES = (
    "docker-ce docker-ce-cli containerd.io "
    "docker-buildx-plugin docker-compose-plugin docker-ce-rootless-extras"
)


def _enable_docker_soft(runner: StepRunner) -> None:
    """Включить и (ре)запустить docker.service — restart гарантирует, что демон
    подхватит свежий daemon.json. Если systemctl вернул ошибку — проверяем
    фактическое состояние через `docker info` (как _enable_service_soft у WG):
    если демон отвечает, считаем шаг успешным."""
    title = "Запуск и автозагрузка docker.service"
    runner.emit(f"• {title}")
    exit_code, out, err = exec_sudo(
        runner.ssh, runner.server,
        "systemctl enable docker && systemctl restart docker",
        emit=lambda line: runner.emit("   " + line),
    )
    if exit_code == 0:
        runner.completed.append("enable_service")
        return

    detail = (err.strip() or out.strip() or f"exit {exit_code}")[:500]
    runner.emit(f"   [!] systemctl вернул код {exit_code}")
    for line in detail.splitlines()[:8]:
        runner.emit(f"   {line}")

    info = runner.probe("docker info >/dev/null 2>&1 && echo ok || echo fail")
    if info == "ok":
        runner.emit(
            "   [!] systemctl вернул ошибку, но демон Docker отвечает. "
            "Установку считаем успешной."
        )
        runner.completed.append("enable_service")
        return
    runner.failed = "enable_service"
    raise StepError(
        "enable_service", exit_code, title=title,
        detail=detail or "docker daemon не отвечает после restart",
    )


def _purge_packages_soft(runner: StepRunner) -> None:
    """apt purge docker-* часто даёт ненулевой exit (зависимости/lock). Проверяем
    факт удаления по отсутствию пакетов (как _purge_packages_soft у WG)."""
    title = "Удаление пакетов Docker"
    runner.emit(f"• {title}")
    exit_code, out, err = exec_sudo(
        runner.ssh, runner.server,
        "DEBIAN_FRONTEND=noninteractive apt-get purge -y " + _DOCKER_PACKAGES + " "
        "2>&1; ec=$?; "
        "DEBIAN_FRONTEND=noninteractive apt-get autoremove -y 2>/dev/null || true; "
        "exit $ec",
        emit=lambda line: runner.emit("   " + line),
    )
    still = runner.probe(
        "dpkg -l " + _DOCKER_PACKAGES + " 2>/dev/null | "
        "awk '/^ii/{print $2}' || true"
    ).strip()
    if exit_code == 0 or not still:
        if exit_code != 0:
            runner.emit(
                f"   [!] apt вернул код {exit_code}, но пакеты docker-* не установлены — OK"
            )
            if err or out:
                for line in (err or out).strip().splitlines()[-6:]:
                    runner.emit(f"   {line}")
        runner.completed.append("purge_packages")
        return

    detail = (err.strip() or out.strip() or f"exit {exit_code}")[:500]
    runner.emit(f"   [!] пакеты всё ещё установлены: {still}")
    runner.failed = "purge_packages"
    raise StepError("purge_packages", exit_code or 100, title=title, detail=detail)


def install(server: dict, params: Dict[str, Any], emit) -> StepRunner:
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    try:
        runner.run("check_os", "grep -Eiq '(debian|ubuntu)' /etc/os-release",
                   title="Проверка ОС (Debian/Ubuntu)")
        runner.run("ensure_deps",
                   "DEBIAN_FRONTEND=noninteractive apt-get update -qq && "
                   "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl ca-certificates",
                   title="Обновление apt + curl/ca-certificates")
        runner.run("get_docker_script",
                   "curl -fsSL https://get.docker.com -o /tmp/get-docker.sh",
                   title="Скачивание официального установочного скрипта")
        runner.run("run_installer", "sh /tmp/get-docker.sh",
                   title="Установка Docker Engine (get.docker.com)")
        templates.write_daemon_config(runner)
        _enable_docker_soft(runner)
        runner.run("verify", "docker version --format '{{.Server.Version}}'",
                   title="Проверка: docker version (сервер)")
    finally:
        ssh.close()
    return runner


def remove(server: dict, emit) -> StepRunner:
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    try:
        runner.run("disable_service",
                   "systemctl disable --now docker containerd 2>/dev/null; true",
                   title="Остановка и отключение docker/containerd")
        _purge_packages_soft(runner)
        # Намеренно НЕ трогаем /var/lib/docker — образы/тома/контейнеры сохраняем.
        runner.run("cleanup_unit",
                   "rm -f /etc/systemd/system/docker.service "
                   "/etc/systemd/system/containerd.service; "
                   "systemctl daemon-reload 2>/dev/null || true",
                   title="Очистка юнитов systemd")
    finally:
        ssh.close()
    return runner
