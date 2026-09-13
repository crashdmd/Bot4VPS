import asyncio
import time
import socket
from concurrent.futures import ThreadPoolExecutor

from ping3 import ping

from core.host_keys import HostKeyMismatchError
from core.ssh import create_ssh_client, exec_sudo
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
    "uname -m 2>/dev/null || echo N/A; "
    "echo '" + _INFO_SEP + "'; "
    "awk '{print $1}' /proc/uptime 2>/dev/null || echo N/A"
)


def _probe_network(host, port: int | None = None):
    """Сетевая доступность: ICMP → TCP на порт сервера (обычно SSH) → 80 → 443.

    Критерий ONLINE: ответил хотя бы один зонд. Порядок от дешёвого к
    fallback'у: ICMP не грузит сервер, TCP на известный port честно ловит
    «закрытый» VPS без ICMP и без веба, 80/443 — последний fallback.
    Возвращает (ping_ms, network): network — "ping" | "tcp" | "http" | "none".
    """
    try:
        latency = ping(host, timeout=2)
        if latency:
            return round(latency * 1000, 1), "ping"
    except Exception:
        pass

    ports = []
    if port:
        ports.append(int(port))
    ports.extend((80, 443))

    for tcp_port in ports:
        sock = None
        try:
            start = time.perf_counter()
            sock = socket.create_connection((host, tcp_port), timeout=2)
            return round((time.perf_counter() - start) * 1000, 1), "tcp"
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
        "host_key_mismatch": False,
        "uptime": "N/A",
        "uptime_seconds": None,
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

            # 0..3 — прежние метрики; 4..8 — system; 9 — точный uptime.
            out["uptime"] = _part(0)
            try:
                out["uptime_seconds"] = float(_part(9))
            except (TypeError, ValueError):
                out["uptime_seconds"] = None
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
    except HostKeyMismatchError as e:
        # Верификация host key заблокировала подключение ДО пароля:
        # карточке сервера нужен явный флаг — баннер предложит принять ключ
        out["ssh_error"] = str(e)
        out["host_key_mismatch"] = True
        print(
            f"Info error {server.get('name')}: host key mismatch",
            flush=True
        )
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
        "uptime_seconds": None,
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
        net_future = ex.submit(_probe_network, host, server.get("port"))
        ssh_future = ex.submit(_probe_ssh, server)
        result["ping"], result["network"] = net_future.result()
        result.update(ssh_future.result())

    return result

def get_server_info_without_ssh(server, ssh_error=""):
    """Проба карточки во время SSH backoff: сеть проверяем живьём (дёшево,
    без аутентификации), SSH-статус — последняя известная причина из monitor.

    Открытая карточка опрашивает /probe каждые 5с; без этого хелпера она
    продолжала бы долбить недоступный сервер неудачными подключениями.
    """
    ping, network = _probe_network(server["host"], server.get("port"))
    return {
        "ping": ping,
        "network": network,
        "ssh": False,
        "ssh_error": ssh_error or None,
        "host_key_mismatch": classify_ssh_error(ssh_error) == "host_key",
        "uptime": "N/A",
        "uptime_seconds": None,
        "load": "N/A",
        "ram": "N/A",
        "disk": "N/A",
        "hostname": "N/A",
        "os": "N/A",
        "os_version": "N/A",
        "kernel": "N/A",
        "arch": "N/A",
    }


def is_server_online(info):
    """
    Возвращает True, если сервер доступен по сети.
    """
    return info["network"] != "none"

def format_ssh_error(error):
    if not error:
        return "Неизвестная ошибка."

    text = error.lower()

    if "host key" in text:
        return (
            "Host key сервера изменился — подключения заблокированы,\n"
            "пароль не отправлялся. Если сервер переустановлен,\n"
            "примите новый ключ кнопкой ниже."
        )

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


def classify_ssh_error(error) -> str:
    """Машинный вид ошибки SSH для UI-меток.

    Возвращает один из: key_missing | auth | port | network | timeout |
    connect | unknown. Те же критерии, что у format_ssh_error (её текст —
    для карточки сервера, этот код — для компактных меток виджета дашборда).
    """
    if not error:
        return "unknown"
    text = str(error).lower()
    if "host key" in text:
        return "host_key"
    if "ключ не найден" in text or "no such file" in text:
        return "key_missing"
    if (
        "authentication failed" in text
        or "password authentication failed" in text
        or "publickey" in text
        or "permission denied" in text
    ):
        return "auth"
    if "connection refused" in text:
        return "port"
    if "network is unreachable" in text or "errno 101" in text:
        return "network"
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if "no valid connections" in text or "unable to connect" in text:
        return "connect"
    return "unknown"


def reboot_server(server):
    ssh = None
    try:
        ssh = create_ssh_client(server)
        print(f"→ Executing reboot on {server['name']}", flush=True)
        status, out, err = exec_sudo(ssh, server, "/sbin/reboot", timeout=30)
        print(
            f"Reboot {server['name']} | status={status} | stderr='{(err or '')[:300]}'",
            flush=True,
        )
        # После принятой reboot-команды канал может оборваться, поэтому успех
        # определяет exit status; пустой transport после этого не считается ошибкой.
        return status == 0
    except Exception as e:
        print(f"Reboot FAILED {server.get('name')}: {e}", flush=True)
        return False
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


async def wait_for_reboot(server, timeout=120):
    await asyncio.sleep(10)
    print(f"Waiting for {server['name']}...", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        try:
            # paramiko-подключение блокирует — без to_thread каждая
            # попытка (до TCP/SSH-таймаута) замораживала event loop
            # на всё время ожидания перезагрузки (до 2 минут)
            ssh = await asyncio.to_thread(create_ssh_client, server)
        except Exception:
            ssh = None
        if ssh is not None:
            ssh.close()
            return True
        await asyncio.sleep(5)
    return False