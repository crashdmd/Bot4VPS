"""Client of the local, fixed-operation root helper (never a sudo shell)."""
from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import time

SOCKET_PATH = "/run/bot4vps-helper/control.sock"
MAX_MESSAGE = 192 * 1024


class PrivilegeError(RuntimeError):
    pass


def separated() -> bool:
    """Layout marker, independent of whether the helper is currently alive."""
    from pathlib import Path
    from core.install_paths import get_install_path
    return (get_install_path() / "data" / "runtime").is_dir()


def request(operation: str, **params):
    body = json.dumps({"version": 1, "operation": operation, "params": params},
                      ensure_ascii=False, allow_nan=False).encode() + b"\n"
    if len(body) > MAX_MESSAGE:
        raise PrivilegeError("Слишком большой запрос к локальному помощнику")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(960)
            connection.connect(SOCKET_PATH)
            # Authenticate the server too: a service-user socket is not a root helper.
            _, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != 0:
                raise PrivilegeError("Локальный помощник не принадлежит root")
            connection.sendall(body)
            reply = bytearray()
            while not reply.endswith(b"\n"):
                chunk = connection.recv(min(65536, MAX_MESSAGE + 1 - len(reply)))
                if not chunk or len(reply) + len(chunk) > MAX_MESSAGE:
                    raise PrivilegeError("Некорректный ответ локального помощника")
                reply.extend(chunk)
        result = json.loads(reply)
        if result.get("ok") is not True:
            raise PrivilegeError(result.get("error") or "Операция локального помощника не выполнена")
        return result.get("result")
    except (OSError, ValueError) as exc:
        raise PrivilegeError("Локальный помощник недоступен: " + str(exc)) from exc


def systemctl(*args: str, timeout: int = 90) -> subprocess.CompletedProcess:
    if separated():
        result = request("service.control", args=list(args))
        if result["returncode"] == 0 and list(args) in [[verb, "bot4vps"] for verb in ("start", "stop", "restart")]:
            return _wait_service(args[0], timeout)
        return subprocess.CompletedProcess(["systemctl", *args], result["returncode"],
                                           result["stdout"], result["stderr"])
    return subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=timeout)


def _wait_service(action: str, timeout: int) -> subprocess.CompletedProcess:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = subprocess.run(["systemctl", "show", "bot4vps", "--property=ActiveState", "--property=Job"],
                                capture_output=True, text=True, timeout=5)
        if status.returncode:
            return status
        values = dict(line.split("=", 1) for line in status.stdout.splitlines() if "=" in line)
        if values.get("Job", "0").split(" ")[0] in ("", "0"):
            desired = ("inactive", "failed") if action == "stop" else ("active",)
            if values.get("ActiveState") in desired:
                return subprocess.CompletedProcess(["systemctl", action, "bot4vps"], 0, "", "")
            if values.get("ActiveState") == "failed":
                return subprocess.CompletedProcess(["systemctl", action, "bot4vps"], 1, "", "Служба bot4vps не запустилась")
        time.sleep(0.2)
    raise subprocess.TimeoutExpired(["systemctl", action, "bot4vps"], timeout)


def configure_unit(text: str) -> None:
    request("unit.configure", text=text)


def commit_unit() -> None:
    if separated():
        request("unit.commit")


def launch_task(kind: str, job_path: str | None = None) -> int:
    return request("task.launch", kind=kind, job_path=job_path)["pid"]
