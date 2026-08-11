# -*- coding: utf-8 -*-
"""Операции с образами Docker (Phase 4).

list_images   - список образов (docker images)
pull_image    - загрузка образа (docker pull)
remove_image  - удаление образа (docker rmi)
prune_images  - очистка неиспользуемых образов (docker image prune -f)
"""
from __future__ import annotations

import json
import shlex
from typing import Any, Dict, List

from core.integrator import StepRunner
from core.ssh import create_ssh_client

from . import validation


def _parse_images_json(text: str) -> List[Dict[str, Any]]:
    """Разобрать вывод `docker images --format '{{json .}}'` → список образов."""
    out: List[Dict[str, Any]] = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        repo = str(obj.get("Repository") or "")
        tag = str(obj.get("Tag") or "")
        if not repo or repo == "<none>":
            continue
        out.append({
            "id": str(obj.get("ID") or "")[:12],
            "repository": repo,
            "tag": tag,
            "size": str(obj.get("Size") or ""),
            "created": str(obj.get("CreatedSince") or ""),
        })
    return out


def list_images(server: dict) -> List[Dict[str, Any]]:
    """Получить список образов на сервере (read-only, без изменений).

    Возвращает:
        [{"id", "repository", "tag", "size", "created"}, ...]
    """
    from core.ssh import exec_sudo
    ssh = create_ssh_client(server)
    try:
        _, out, _ = exec_sudo(
            ssh, server,
            "docker images --no-trunc --format '{{json .}}' 2>/dev/null || true",
        )
        return _parse_images_json(out)
    finally:
        ssh.close()


def pull_image(server: dict, image: str, emit) -> str:
    """Загрузить образ (docker pull). Валидация + StepRunner.

    Args:
        image: имя образа (например nginx:alpine)
        emit: progress callback

    Returns:
        Провалидированное имя образа
    """
    image_val = validation.validate_image(image)
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    try:
        runner.run(
            "pull_image", f"docker pull {shlex.quote(image_val)}",
            title=f"Загрузка образа «{image_val}»",
        )
    finally:
        ssh.close()
    return image_val


def remove_image(server: dict, image: str, emit) -> str:
    """Удалить образ (docker rmi). Валидация + StepRunner.

    Args:
        image: полное имя образа (repo:tag или image_id)
        emit: progress callback

    Returns:
        Провалидированное имя образа
    """
    # Для удаления можем принять либо полное имя, либо ID (12 символов hex)
    image_val = image.strip()
    if not image_val:
        from core.integrator import StepError
        raise StepError("remove_image", -1, title="Удаление образа",
                        detail="имя образа не может быть пустым")

    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    try:
        runner.run(
            "remove_image", f"docker rmi {shlex.quote(image_val)}",
            title=f"Удаление образа «{image_val}»",
        )
    finally:
        ssh.close()
    return image_val


def prune_images(server: dict, emit) -> str:
    """Удалить неиспользуемые образы (docker image prune -a -f).

    Удаляет ВСЕ образы, не привязанные к контейнерам (включая tagged).

    Returns:
        Краткая статистика освобождённого места
    """
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    try:
        output = runner.run(
            "prune_images", "docker image prune -a -f",
            title="Очистка неиспользуемых образов",
        )
        # Вывод docker image prune содержит строку "Total reclaimed space: ..."
        for line in output.split("\n"):
            if "reclaimed" in line.lower():
                return line.strip()
        return "Очистка завершена"
    finally:
        ssh.close()
