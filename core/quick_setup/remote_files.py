# -*- coding: utf-8 -*-
"""Безопасные атомарные изменения небольших удалённых конфигураций."""
from __future__ import annotations

import base64
import os
import shlex
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

from core.ssh import exec_plain, exec_sudo

_MAX_FILE_BYTES = 512 * 1024


@dataclass(frozen=True)
class RemoteFileSnapshot:
    path: str
    existed: bool
    content: bytes = b""
    mode: int = 0o644
    uid: int = 0
    gid: int = 0


def _path(path: str) -> str:
    value = str(path or "")
    if not value.startswith("/") or "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError("Некорректный путь конфигурации")
    return value


def snapshot_file(
    ssh,
    server: dict,
    path: str,
    *,
    max_bytes: int = _MAX_FILE_BYTES,
    sudo: bool = True,
) -> RemoteFileSnapshot:
    """Снять bounded snapshot regular file и отклонить symlink/hardlink.

    sudo=False — чтение без sudo (собственные файлы текущего пользователя).
    """
    path = _path(path)
    q = shlex.quote(path)
    command = (
        f"if [ -L {q} ]; then echo SYMLINK; exit 40; fi; "
        f"if [ ! -e {q} ]; then echo ABSENT; exit 0; fi; "
        f"if [ ! -f {q} ]; then echo NOT_REGULAR; exit 41; fi; "
        f"set -- $(stat -c '%s %a %u %g %h' {q}); "
        f"[ \"$1\" -le {int(max_bytes)} ] || {{ echo TOO_LARGE; exit 42; }}; "
        f"[ \"$5\" -eq 1 ] || {{ echo HARDLINK; exit 43; }}; "
        f"printf 'FILE %s %s %s\\n' \"$2\" \"$3\" \"$4\"; "
        f"base64 < {q} | tr -d '\\n'; printf '\\n'"
    )
    code, out, err = (exec_sudo if sudo else exec_plain)(ssh, server, command, timeout=30)
    lines = (out or "").splitlines()
    tag = lines[0].strip() if lines else ""
    if code == 0 and tag == "ABSENT":
        return RemoteFileSnapshot(path=path, existed=False)
    if code != 0 or not tag.startswith("FILE "):
        labels = {
            "SYMLINK": "Символьные ссылки не поддерживаются",
            "NOT_REGULAR": "Путь не является обычным файлом",
            "TOO_LARGE": "Файл слишком большой для безопасного редактирования",
            "HARDLINK": "Файлы с несколькими hardlink не поддерживаются",
        }
        raise RuntimeError(labels.get(tag, (err or out or f"snapshot exit {code}")[:800]))
    parts = tag.split()
    if len(parts) != 4:
        raise RuntimeError("Некорректный ответ snapshot")
    try:
        content = base64.b64decode(lines[1] if len(lines) > 1 else "", validate=True)
        mode = int(parts[1], 8)
        uid, gid = int(parts[2]), int(parts[3])
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Некорректные metadata snapshot") from exc
    if len(content) > max_bytes:
        raise RuntimeError("Файл слишком большой для безопасного редактирования")
    return RemoteFileSnapshot(path=path, existed=True, content=content, mode=mode, uid=uid, gid=gid)


def atomic_write(
    ssh,
    server: dict,
    path: str,
    content: bytes | str,
    *,
    mode: int = 0o644,
    uid: Optional[int] = None,
    gid: Optional[int] = None,
    create_only: bool = False,
    sudo: bool = True,
) -> None:
    """Записать через temp в том же каталоге и atomic rename/create.

    sudo=False — запись без sudo: chown пропускается (непривилегированный
    пользователь не может менять владельца; свои файлы уже принадлежат ему).
    """
    path = _path(path)
    raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    if len(raw) > _MAX_FILE_BYTES:
        raise ValueError("Конфигурация превышает 512 КБ")
    directory = os.path.dirname(path)
    temp = f"{directory}/.bot4vps-{uuid.uuid4().hex}.tmp"
    q_path, q_dir, q_temp = map(shlex.quote, (path, directory, temp))
    encoded = base64.b64encode(raw).decode("ascii")
    owner = ""
    if sudo and uid is not None and gid is not None:
        owner = f" && chown {int(uid)}:{int(gid)} {q_temp}"
    publish = (
        f"(ln {q_temp} {q_path} || {{ [ -e {q_path} ] && printf TARGET_EXISTS >&2; false; }}) "
        f"&& rm -f -- {q_temp}"
        if create_only
        else f"mv -f -- {q_temp} {q_path}"
    )
    command = (
        f"[ -d {q_dir} ] && [ ! -L {q_dir} ] || exit 44; "
        f"[ ! -L {q_path} ] || exit 40; "
        f"umask 077; printf %s {shlex.quote(encoded)} | base64 -d > {q_temp} && "
        f"chmod {int(mode):o} {q_temp}{owner} && {publish}; "
        f"rc=$?; [ $rc -eq 0 ] || rm -f -- {q_temp}; exit $rc"
    )
    code, out, err = (exec_sudo if sudo else exec_plain)(ssh, server, command, timeout=30)
    if code != 0:
        if create_only and "TARGET_EXISTS" in str(err or out):
            raise FileExistsError("Файл уже существует")
        raise RuntimeError((err or out or f"atomic write exit {code}")[:1000])


def restore_file(ssh, server: dict, snapshot: RemoteFileSnapshot, *, sudo: bool = True) -> None:
    """Точно вернуть исходный файл или удалить созданный вместо absent."""
    if snapshot.existed:
        atomic_write(
            ssh,
            server,
            snapshot.path,
            snapshot.content,
            mode=snapshot.mode,
            uid=snapshot.uid,
            gid=snapshot.gid,
            sudo=sudo,
        )
        return
    path = _path(snapshot.path)
    q = shlex.quote(path)
    code, out, err = (exec_sudo if sudo else exec_plain)(
        ssh,
        server,
        f"[ ! -L {q} ] || exit 40; rm -f -- {q}",
        timeout=20,
    )
    if code != 0:
        raise RuntimeError((err or out or f"restore delete exit {code}")[:1000])


def mutate_file(
    ssh,
    server: dict,
    path: str,
    content: bytes | str,
    *,
    validate: Callable[[], tuple[bool, str]],
    apply: Callable[[], tuple[bool, str]],
    verify: Callable[[], tuple[bool, str]],
    mode: int = 0o644,
) -> dict:
    """snapshot → write → validate → apply → verify с точным rollback."""
    snapshot = snapshot_file(ssh, server, path)
    stage = "write"
    try:
        atomic_write(ssh, server, path, content, mode=mode)
        stage = "validate"
        ok, detail = validate()
        if not ok:
            raise RuntimeError(detail or "Проверка конфигурации не пройдена")
        stage = "apply"
        ok, detail = apply()
        if not ok:
            raise RuntimeError(detail or "Конфигурация не применена")
        stage = "verify"
        ok, detail = verify()
        if not ok:
            raise RuntimeError(detail or "Применённое состояние не подтверждено")
        return {"ok": True, "stage": "verified", "existed_before": snapshot.existed}
    except Exception as exc:
        rollback_error = None
        try:
            restore_file(ssh, server, snapshot)
            valid, valid_detail = validate()
            applied, apply_detail = apply() if valid else (False, valid_detail)
            if not valid or not applied:
                rollback_error = (apply_detail or valid_detail or "rollback verification failed")[:1000]
        except Exception as rollback_exc:
            rollback_error = str(rollback_exc)[:1000]
        error = RuntimeError(str(exc))
        error.stage = stage  # type: ignore[attr-defined]
        error.rollback_error = rollback_error  # type: ignore[attr-defined]
        raise error
