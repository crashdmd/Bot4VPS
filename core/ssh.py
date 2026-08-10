import paramiko
import os
import shlex

from typing import Callable, Optional, Tuple


def create_ssh_client(server, timeout=8):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(
        paramiko.AutoAddPolicy()
    )

    auth_type = server.get(
        "auth_type",
        "password"
    )

    if auth_type == "key":
        ssh.connect(
            hostname=server["host"],
            port=server.get("port", 22),
            username=server["user"],
            key_filename=server["key_path"],
            timeout=timeout
        )
    else:
        ssh.connect(
            hostname=server["host"],
            port=server.get("port", 22),
            username=server["user"],
            password=server["password"],
            timeout=timeout
        )

    return ssh

def get_available_keys():
    return [
        f
        for f in os.listdir("/opt/bot4vps/keys")
        if not f.endswith(".pub")
    ]

def test_connection(server):
    try:
        ssh = create_ssh_client(server)
        ssh.close()

        return True, "OK"

    except Exception as e:
        return False, str(e)


def exec_sudo(
    ssh,
    server,
    command: str,
    emit: Optional[Callable[[str], None]] = None,
    timeout: int = 600,
) -> Tuple[int, str, str]:
    """Выполнить command на уже открытом ssh-клиенте с учётом sudo для не-root.

    Не-root: оборачивает в `sudo -S -p '' <command>` и скармливает пароль в stdin
    (та же схема, что в core/scripts.py::_run_script_sync). Root: как есть.

    emit (опц.) — синхронная callable(line): строки stdout стримятся в неё по
    ходу выполнения (для live-вывода через integrator.sync_progress). Синхронная,
    т.к. зовётся из asyncio.to_thread.

    Возвращает (exit_code, stdout, stderr). Команда ВСЕГДА оборачивается в
    `bash -c '<command>'` (с shlex.quote) — поэтому составные команды (&&, ;,
    VAR=, $(...), редиректы) выполняются в одном root-шелле единообразно,
    а сервис передаёт естественную строку и не думает про sudo/экранирование.
    """
    is_root = (server.get("user", "") or "").lower() == "root"
    quoted = shlex.quote(command)
    full = f"bash -c {quoted}" if is_root else f"sudo -S -p '' bash -c {quoted}"

    stdin, stdout, stderr = ssh.exec_command(full, timeout=timeout)
    if not is_root:
        stdin.write((server.get("password", "") or "") + "\n")
        stdin.flush()
        stdin.channel.shutdown_write()

    out_lines = []
    chan = stdout.channel
    while True:
        line = stdout.readline()
        if not line:
            if chan.exit_status_ready():
                break
            continue
        line = line.rstrip("\r\n")
        if line:
            out_lines.append(line)
            if emit:
                try:
                    emit(line)
                except Exception:
                    pass

    exit_code = chan.recv_exit_status()
    err = stderr.read().decode("utf-8", errors="ignore")
    return exit_code, "\n".join(out_lines), err