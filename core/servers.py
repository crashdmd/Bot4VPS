import asyncio
import time
import socket

from ping3 import ping

from core.ssh import create_ssh_client
from core.storage import find_server
from core.monitor import get_server_monitor, format_certificate


def get_server_info(server):
    result = {
        "ping": None,
        "network": "none",
        "ssh": False,
        "ssh_error": None,
        "uptime": "N/A",
        "load": "N/A",
        "ram": "N/A",
        "disk": "N/A"
    }

    host = server["host"]

    # 1. Обычный ping
    try:
        latency = ping(host, timeout=2)
        if latency:
            result["ping"] = round(latency * 1000, 1)
            result["network"] = "ping"
    except:
        pass

    # 2. TCP fallback с надёжным измерением времени
    if result["network"] == "none":
        for port in (80, 443):
            sock = None
            try:
                start = time.perf_counter()
                sock = socket.create_connection((host, port), timeout=3)
                duration = round((time.perf_counter() - start) * 1000, 1)
                result["ping"] = duration
                result["network"] = "http"
                break
            except:
                continue
            finally:
                if sock:
                    try:
                        sock.close()
                    except:
                        pass

    # 3. SSH + системная информация
    try:
        ssh = create_ssh_client(server)
        result["ssh"] = True

        cmds = {
            "uptime": "uptime -p",
            "load": "cat /proc/loadavg | awk '{print $1\" \"$2\" \"$3}'",
            "ram": "free -m | awk '/Mem:/ {print $3\" MB / \"$2\" MB\"}'",
            "disk": "df -h / | awk 'NR==2 {print $3\" / \"$2}'",
        }
        for k, cmd in cmds.items():
            _, out, _ = ssh.exec_command(cmd)
            result[k] = out.read().decode().strip() or "N/A"
        ssh.close()
    except Exception as e:
        result["ssh_error"] = str(e)
        print(
            f"Info error {server.get('name')}: {e}",
            flush=True
        )

    return result

def is_server_online(info):
    """
    Возвращает True, если сервер доступен по сети.
    """
    return info["network"] != "none"

def format_ssh_error(error):
    if not error:
        return "Неизвестная ошибка."

    text = error.lower()

    if "authentication failed" in text:
        return (
            "Ошибка аутентификации.\n"
            "Проверьте пароль или SSH-ключ."
        )

    if (
        "password authentication failed" in text
        or "publickey" in text
    ):
        return (
            "Для подключения к серверу "
            "необходимо использовать SSH-ключ."
        )

    if "connection refused" in text:
        return (
            "SSH-порт недоступен.\n"
            "Проверьте настройки сервера."
        )

    if (
        "network is unreachable" in text
        or "errno 101" in text
    ):
        return (
            "Сеть недоступна.\n"
            "Проверьте IP-адрес, сетевое "
            "подключение или маршрут до сервера."
        )

    if (
        "timed out" in text
        or "timeout" in text
    ):
        return (
            "Сервер не отвечает.\n"
            "Проверьте доступность сервера "
            "или соединение."
        )

    if (
        "no valid connections" in text
        or "unable to connect" in text
    ):
        return (
            "Не удалось подключиться "
            "к SSH-серверу."
        )

    if "no such file" in text:
        return (
            "Файл SSH-ключа не найден."
        )

    return error


def reboot_server(server):
    try:
        ssh = create_ssh_client(server)

        cmd = "/sbin/reboot" if server["user"].lower() == "root" else "sudo /sbin/reboot"
        print(f"→ Executing on {server['name']}: {cmd}", flush=True)

        _, stdout, stderr = ssh.exec_command(cmd)
        err = stderr.read().decode().strip()
        status = stdout.channel.recv_exit_status()
        
        print(f"Reboot {server['name']} | status={status} | stderr='{err}'", flush=True)
        ssh.close()
        return True
    except Exception as e:
        print(f"Reboot FAILED {server.get('name')}: {e}", flush=True)
        return False


async def wait_for_reboot(server, timeout=120):
    await asyncio.sleep(10)
    print(f"Waiting for {server['name']}...", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        try:
            ssh = create_ssh_client(server)
            ssh.close()
            return True
        except:
            await asyncio.sleep(5)
    return False