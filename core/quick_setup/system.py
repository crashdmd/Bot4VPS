# -*- coding: utf-8 -*-
"""Раздел «Система»: проверка обновлений, apt upgrade, reboot + ожидание SSH."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from core.ssh import create_ssh_client, exec_sudo
from core.servers import reboot_server_with_readiness

from .models import OpResult, SystemStatus


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def check_updates(server: dict) -> SystemStatus:
    """apt update + проверка наличия обновляемых пакетов (без upgrade)."""
    status = SystemStatus(last_check=_now_iso())
    ssh = None
    try:
        ssh = create_ssh_client(server, timeout=15)
        # refresh индексов; не считаем ненулевой код фатальным, если дальше list сработал
        code_u, out_u, err_u = exec_sudo(
            ssh, server, "apt-get update -qq", timeout=180
        )
        code, out, err = exec_sudo(
            ssh,
            server,
            "apt-get -s upgrade 2>/dev/null | awk '/^Inst /{c++} END{print c+0}'",
            timeout=120,
        )
        if code != 0:
            status.updates_available = None
            status.updates_summary = "не удалось проверить"
            status.error = (err or out or f"exit {code}").strip()[:500]
            return status
        try:
            count = int((out or "0").strip().splitlines()[-1].strip() or "0")
        except ValueError:
            count = 0
        status.updates_available = count > 0
        if count > 0:
            status.updates_summary = f"доступны ({count})"
        else:
            status.updates_summary = "система актуальна"
        if code_u != 0 and not status.error:
            # предупреждение, но список пакетов получили
            status.error = None
        return status
    except Exception as e:
        status.updates_available = None
        status.updates_summary = "ошибка проверки"
        status.error = str(e)[:500]
        return status
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def upgrade_system(server: dict) -> OpResult:
    """Одна операция: apt-get update && apt-get upgrade -y."""
    ssh = None
    lines: list[str] = []
    try:
        ssh = create_ssh_client(server, timeout=20)
        from core.operation_metrics import measure

        measure(ssh)

        def emit(line: str) -> None:
            if line:
                lines.append(line)

        code1, out1, err1 = exec_sudo(
            ssh, server, "apt-get update -y", emit=emit, timeout=300
        )
        if code1 != 0:
            return OpResult(
                ok=False,
                message="apt-get update завершился с ошибкой",
                output="\n".join(lines)[-8000:],
                error=(err1 or out1 or f"exit {code1}")[:1000],
            )

        measure(ssh)
        code2, out2, err2 = exec_sudo(
            ssh,
            server,
            "DEBIAN_FRONTEND=noninteractive apt-get upgrade -y",
            emit=emit,
            timeout=1800,
        )
        output = "\n".join(lines)[-8000:]
        if code2 != 0:
            return OpResult(
                ok=False,
                message="apt-get upgrade завершился с ошибкой",
                output=output,
                error=(err2 or out2 or f"exit {code2}")[:1000],
            )
        return OpResult(
            ok=True,
            message="Система обновлена",
            output=output,
            data={"last_check": _now_iso()},
        )
    except Exception as e:
        return OpResult(
            ok=False,
            message="Ошибка обновления системы",
            output="\n".join(lines)[-4000:],
            error=str(e)[:1000],
        )
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def reboot_and_wait(
    server: dict,
    *,
    initial_delay: float = 12.0,
    poll_interval: float = 5.0,
    timeout: float = 180.0,
) -> OpResult:
    outcome = reboot_server_with_readiness(
        server,
        initial_delay=initial_delay,
        poll_interval=poll_interval,
        timeout=timeout,
    )
    if not outcome.accepted:
        return OpResult(
            ok=False,
            message="Не удалось отправить команду перезагрузки",
            error=outcome.error,
        )
    if outcome.ready:
        return OpResult(
            ok=True,
            message="Сервер перезагружен, SSH восстановлен",
            data={
                "ready": True,
                "attempts": outcome.attempts,
                "waited_sec": outcome.waited_sec,
            },
        )
    return OpResult(
        ok=True,
        message="Сервер перезагружен, но SSH не восстановился вовремя",
        data={
            "ready": False,
            "attempts": outcome.attempts,
            "waited_sec": outcome.waited_sec,
            "warning": "readiness_timeout",
        },
    )
