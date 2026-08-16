import asyncio
import time
import socket
from concurrent.futures import ThreadPoolExecutor

from ping3 import ping

from core.ssh import create_ssh_client
from core.storage import find_server


# Разделитель между секциями вывода batched-команды сбора метрик.
_INFO_SEP = "::BOT4VPS_SEP::"

# Системные метрики и сведения об ОС — одной shell-командой
# (без дополнительных SSH round-trip'ов).
_INFO_CMD = (
    "uptime -p; "
    "echo '" + _INFO_SEP + "'; "
    "cat /proc/loadavg | awk '{print $1\" \"$2\" \"$3}'; "
    "echo '" + _INFO_SEP + "'; "
    "free -m | awk '/Mem:/ {print $3\" MB / \"$2\" MB\"}'; "
    "echo '" + _INFO_SEP + "'; "
    "df -h / | awk 'NR==2 {print $3\" / \"$2}'; "
    "echo '" + _INFO_SEP + "'; "
    "hostname 2>/dev/null || cat /etc/hostname 2>/dev/null || echo N/A; "
    "echo '" + _INFO_SEP + "'; "
    "( . /etc/os-release 2>/dev/null; echo \"${ID:-N/A}\" ); "
    "echo '" + _INFO_SEP + "'; "
    "( . /etc/os-release 2>/dev/null; echo \"${VERSION_ID:-N/A}\" ); "
    "echo '" + _INFO_SEP + "'; "
    "uname -r 2>/dev/null || echo N/A; "
    "echo '" + _INFO_SEP + "'; "
    "uname -m 2>/dev/null || echo N/A"
)


def _probe_network(host):
    """Сетевая доступность: ping, затем TCP 80/443. Возвращает (ping_ms, network)."""
    try:
        latency = ping(host, timeout=2)
        if latency:
            return round(latency * 1000, 1), "ping"
    except Exception:
        pass

    for port in (80, 443):
        sock = None
        try:
            start = time.perf_counter()
            sock = socket.create_connection((host, port), timeout=2)
            return round((time.perf_counter() - start) * 1000, 1), "http"
        except Exception:
            continue
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
    return None, "none"


def _probe_ssh(server):
    """SSH-подключение и сбор метрик одной командой."""
    out = {
        "ssh": False,
        "ssh_error": None,
        "uptime": "N/A",
        "load": "N/A",
        "ram": "N/A",
        "disk": "N/A",
        "hostname": "N/A",
        "os": "N/A",
        "os_version": "N/A",
        "kernel": "N/A",
        "arch": "N/A",
    }
    try:
        ssh = create_ssh_client(server, timeout=5)
        out["ssh"] = True
        try:
            _, stdout, _ = ssh.exec_command(_INFO_CMD)
            raw = stdout.read().decode("utf-8", errors="ignore")
            parts = [p.strip() for p in raw.split(_INFO_SEP)]

            def _part(i):
                return parts[i] if i < len(parts) and parts[i] else "N/A"

            # 0..3 — прежние метрики; 4..8 — system
            out["uptime"] = _part(0)
            out["load"] = _part(1)
            out["ram"] = _part(2)
            out["disk"] = _part(3)
            out["hostname"] = _part(4)
            out["os"] = _part(5)
            out["os_version"] = _part(6)
            out["kernel"] = _part(7)
            out["arch"] = _part(8)
        finally:
            ssh.close()
    except Exception as e:
        out["ssh_error"] = str(e)
        print(
            f"Info error {server.get('name')}: {e}",
            flush=True
        )
    return out


def get_server_info(server):
    result = {
        "ping": None,
        "network": "none",
        "ssh": False,
        "ssh_error": None,
        "uptime": "N/A",
        "load": "N/A",
        "ram": "N/A",
        "disk": "N/A",
        "hostname": "N/A",
        "os": "N/A",
        "os_version": "N/A",
        "kernel": "N/A",
        "arch": "N/A",
    }

    host = server["host"]

    # Сетевая проверка и SSH идут параллельно:
    # общее время ~ max(network, ssh), а не их сумма.
    with ThreadPoolExecutor(max_workers=2) as ex:
        net_future = ex.submit(_probe_network, host)
        ssh_future = ex.submit(_probe_ssh, server)
        result["ping"], result["network"] = net_future.result()
        result.update(ssh_future.result())

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