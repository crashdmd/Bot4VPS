import time
import socket
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

from ping3 import ping

from core.actor import in_thread_context
from core.host_keys import HostKeyMismatchError
from core.ssh import create_ssh_client, exec_sudo, test_connection
from core.storage import find_server


# Разделитель между секциями вывода batched-команды сбора метрик.
_INFO_SEP = "::BOT4VPS_SEP::"

# Жёсткий потолок на удалённую команду сбора. `df` обращается к каждому
# монтированию и на мёртвом NFS блокируется навсегда, вешая всю пробу
# (create_ssh_client ограничивает только соединение, а не чтение канала).
# Потолок нужен в двух местах: на удалённой стороне (`timeout` — убивает
# зависший `df` даже если клиент уже мёртв) и на клиентской (settimeout на
# канал — чтобы панель не ждала вечно). Он же защищает system_sync целиком:
# одна зависшая проба не съедает воркер пула и не задерживает остальные.
_INFO_TIMEOUT = 8
# Запас на чтение после удалённого timeout: канал должен успеть отдать
# то, что команда успела напечатать, прежде чем клиент сдастся.
_INFO_READ_GRACE = 4

# Системные метрики и сведения об ОС — одной shell-командой
# (без дополнительных SSH round-trip'ов).
#
# Секции 0..9 — человекочитаемые, на них завязана карточка сервера:
# формат и порядок менять нельзя. Секции 10..12 добавлены для метрик
# (числами) и дописаны В КОНЕЦ: номер секции — это индекс в разборе
# (core/servers.py:_probe_ssh), поэтому вставка в середину сдвинула бы
# все существующие поля.
#
# Почему числа отдельной секцией, а не разбором строк: «12G / 40G»
# пришлось бы разбирать регуляркой, и первое же нестандартное поведение
# df (или другой локали) сломало бы ряд молча. Числа берём там, где они
# уже числа.
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
    "awk '{print $1}' /proc/uptime 2>/dev/null || echo N/A; "
    "echo '" + _INFO_SEP + "'; "
    # 10: память и swap числами (МБ) — две строки «used total»
    "free -m | awk '/Mem:/ {print $3\" \"$2} /Swap:/ {print $3\" \"$2}'; "
    "echo '" + _INFO_SEP + "'; "
    # 11: число ядер — для load/nproc
    "nproc 2>/dev/null || echo N/A; "
    "echo '" + _INFO_SEP + "'; "
    # 12: все реальные монтирования в 1K-блоках. Псевдо-ФС отфильтрованы:
    # без этого в ряду дисков окажутся tmpfs/overlay/efivarfs с их «ёмкостью»,
    # а кончается обычно /var или отдельный диск с данными, не корень.
    # Секция последняя намеренно: если `df` не успеет, потеряются только
    # монтирования, а load/память из секций 1 и 10 уже получены.
    "df -Pkl -x tmpfs -x devtmpfs -x squashfs -x overlay -x efivarfs 2>/dev/null"
)


def _shell_single_quote(text: str) -> str:
    """Обернуть строку в одинарные кавычки так, чтобы её съел sh.

    Внутри _INFO_CMD есть свои одинарные кавычки (awk-программы), поэтому
    простого `'{text}'` мало: закрываем кавычку, экранируем и снова
    открываем — стандартный приём POSIX sh.
    """
    return "'" + text.replace("'", "'\\''") + "'"


# Команда с потолком на удалённой стороне. `timeout` запускает команду в
# отдельной группе процессов и шлёт сигнал всей группе, поэтому зависший
# `df` умирает вместе с ней. Проверка наличия — на случай минимальных
# образов без coreutils: без timeout проба остаётся рабочей (потолок на
# клиенте никуда не девается), просто хуже.
_TIMED_INFO_CMD = (
    "if command -v timeout >/dev/null 2>&1; then "
    f"timeout {_INFO_TIMEOUT} sh -c {_shell_single_quote(_INFO_CMD)}; "
    "else "
    f"sh -c {_shell_single_quote(_INFO_CMD)}; "
    "fi"
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


def _int_or_none(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _float_or_none(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_load(text):
    """Секция 1: «0.15 0.10 0.05» → три числа."""
    fields = text.split()
    if len(fields) < 3:
        return None, None, None
    return (
        _float_or_none(fields[0]),
        _float_or_none(fields[1]),
        _float_or_none(fields[2]),
    )


def _parse_memory(text):
    """Секция 10: строки «used total» в МБ — память, затем swap.

    Swap может не прийти вовсе (контейнер без swap) — тогда это (None,
    None), то есть в БД NULL, а не ноль.
    """
    pairs = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 2:
            continue
        used, total = _int_or_none(fields[0]), _int_or_none(fields[1])
        if used is None or total is None:
            continue
        pairs.append((used, total))
    mem = pairs[0] if pairs else (None, None)
    swap = pairs[1] if len(pairs) > 1 else (None, None)
    return mem, swap


def _parse_mounts(text):
    """Секция 12: `df -Pkl` — по строке на реальное монтирование.

    -P (POSIX) не даёт длинному имени устройства перенести строку, поэтому
    разбор построчный, а точка монтирования берётся «остатком» — в ней
    может быть пробел. Возвращает dict'ы под колонки ``metric_disks``
    (без server_id/ts, их добавит запись).
    """
    mounts = []
    seen = set()
    for line in text.splitlines():
        fields = line.split(None, 5)
        if len(fields) < 6:
            continue
        device, total, used, _avail, capacity, mount = fields
        total_kb, used_kb = _int_or_none(total), _int_or_none(used)
        # Шапка вывода, обрезанные строки и нулевая ёмкость: total не число
        # значит данных нет — писать «0 из 0» нельзя (§7.2).
        if not total_kb or used_kb is None or mount in seen:
            continue
        pct = None
        if capacity.endswith("%"):
            pct = _float_or_none(capacity[:-1])
        if pct is None:
            pct = round(used_kb * 100.0 / total_kb, 2)
        seen.add(mount)
        mounts.append({
            "mount": mount,
            "fs": device,
            "used_kb": used_kb,
            "total_kb": total_kb,
            "used_pct": pct,
        })
    return mounts


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
        "metrics_ok": False,
        "metrics": None,
    }
    try:
        ssh = create_ssh_client(server, timeout=5)
        out["ssh"] = True
        try:
            # timeout= ограничивает блокирующие чтения канала, а не только
            # установку соединения: сюда упирается чтение, если удалённый
            # `timeout` не установлен или не сработал.
            _, stdout, _ = ssh.exec_command(
                _TIMED_INFO_CMD, timeout=_INFO_TIMEOUT + _INFO_READ_GRACE
            )
            channel = stdout.channel
            chunks = []
            timed_out = False
            while True:
                try:
                    data = channel.recv(65536)
                except socket.timeout:
                    timed_out = True
                    break
                if not data:  # EOF — команда закрыла канал
                    break
                chunks.append(data)
            # recv_exit_status() дожидается закрытия канала и на зависшем
            # канале съел бы весь потолок — поэтому только после EOF.
            exit_status = None if timed_out else channel.recv_exit_status()
            if timed_out:
                channel.close()

            raw = b"".join(chunks).decode("utf-8", errors="ignore")
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

            # Числовые метрики (секции 1, 10, 11, 12) — отдельно от
            # человекочитаемых строк: карточка читает строки, БД числа.
            mem, swap = _parse_memory(_part(10))
            load1, load5, load15 = _parse_load(_part(1))
            metrics = {
                "load1": load1,
                "load5": load5,
                "load15": load15,
                "cpu_count": _int_or_none(_part(11)),
                # free -m отдаёт мегабайты, а колонки БД — килобайты
                # (как /proc/meminfo): переводим здесь, у источника строки,
                # чтобы дальше шёл простой перенос в колонки.
                "ram_used_kb": None if mem[0] is None else mem[0] * 1024,
                "ram_total_kb": None if mem[1] is None else mem[1] * 1024,
                "swap_used_kb": None if swap[0] is None else swap[0] * 1024,
                "swap_total_kb": None if swap[1] is None else swap[1] * 1024,
                "mounts": _parse_mounts(_part(12)),
            }
            out["metrics"] = metrics
            # Признак «пробу можно записывать»: есть load и общий объём
            # памяти. Без них точка была бы набором дыр на графике —
            # недоступный сервер выглядел бы простаивающим (§7.4).
            out["metrics_ok"] = bool(
                load1 is not None and metrics["ram_total_kb"]
            )

            # Диагностика частичного сбора. ssh_error при этом НЕ ставим:
            # SSH работает, сломан сбор — карточка не должна говорить
            # «сервер не отвечает». В stdout, потому что сценарий (мёртвый
            # NFS в df) иначе не виден вообще.
            if timed_out:
                print(
                    f"Info timeout {server.get('name')}: сбор не уложился "
                    f"в {_INFO_TIMEOUT + _INFO_READ_GRACE}s",
                    flush=True,
                )
            elif exit_status:
                print(
                    f"Info partial {server.get('name')}: команда сбора "
                    f"прервана (exit={exit_status})",
                    flush=True,
                )
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


def collect_server_metrics(server: dict) -> dict:
    """Собрать только bounded числовые метрики без network/overview probe."""
    try:
        probe = _probe_ssh(server)
    except Exception:
        return {"status": "failed", "error_code": "collector_error"}
    metrics = probe.get("metrics") or {}
    if probe.get("metrics_ok"):
        uptime = probe.get("uptime_seconds")
        try:
            uptime_sec = int(float(uptime)) if uptime is not None else None
        except (TypeError, ValueError):
            uptime_sec = None
        return {
            "status": "captured",
            "metrics": {
                "load1": metrics.get("load1"),
                "load5": metrics.get("load5"),
                "load15": metrics.get("load15"),
                "cpu_count": metrics.get("cpu_count"),
                "ram_used_kb": metrics.get("ram_used_kb"),
                "ram_total_kb": metrics.get("ram_total_kb"),
                "swap_used_kb": metrics.get("swap_used_kb"),
                "swap_total_kb": metrics.get("swap_total_kb"),
                "uptime_sec": uptime_sec,
                "mounts": metrics.get("mounts") or (),
            },
        }
    if probe.get("ssh"):
        return {"status": "failed", "error_code": "metrics_unavailable"}
    kind = classify_ssh_error(probe.get("ssh_error"))
    code = {
        "timeout": "timeout",
        "port": "port",
        "auth": "auth",
        "host_key": "host_key",
        "key_missing": "auth",
        "connect": "connect",
        "network": "connect",
    }.get(kind, "collector_error")
    return {"status": "unavailable", "error_code": code}


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
        "metrics_ok": False,
        "metrics": None,
    }

    host = server["host"]

    # Сетевая проверка и SSH идут параллельно:
    # общее время ~ max(network, ssh), а не их сумма.
    # in_thread_context — проба запускается и из web-запроса (карточка/
    # проверка), поэтому актор должен пережить пул (core/actor.py).
    with ThreadPoolExecutor(max_workers=2) as ex:
        net_future = ex.submit(in_thread_context(_probe_network), host, server.get("port"))
        ssh_future = ex.submit(in_thread_context(_probe_ssh), server)
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
        # SSH не пробовали — числовых метрик нет вовсе (не «нулевые»).
        "metrics_ok": False,
        "metrics": None,
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


@dataclass(frozen=True)
class RebootOutcome:
    accepted: bool
    ready: bool | None
    attempts: int
    waited_sec: float
    error: str | None
    operation_id: str


def _dispatch_reboot(server: dict) -> tuple[bool, str | None]:
    ssh = None
    try:
        ssh = create_ssh_client(server)
        print(f"→ Executing reboot on {server['name']}", flush=True)
        status, out, err = exec_sudo(ssh, server, "/sbin/reboot", timeout=30)
        print(
            f"Reboot {server['name']} | status={status} | stderr='{(err or '')[:300]}'",
            flush=True,
        )
        if status == 0:
            return True, None
        return False, (err or "").strip()[:200] or f"exit {status}"
    except Exception as e:
        error = str(e)
        print(f"Reboot FAILED {server.get('name')}: {error}", flush=True)
        return False, error
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def reboot_server(server: dict) -> bool:
    """Совместимый dispatch-only вход для старых внутренних вызовов."""
    accepted, error = _dispatch_reboot(server)
    _audit_reboot(server, accepted=accepted, error=error, operation_id=None)
    return accepted


def reboot_server_with_readiness(
    server: dict,
    *,
    initial_delay: float = 10.0,
    poll_interval: float = 5.0,
    timeout: float = 120.0,
    wait_readiness: bool = True,
) -> RebootOutcome:
    """Единый lifecycle reboot: dispatch, readiness, audit и peak metrics.

    ``wait_readiness=False`` — dispatch без цикла ожидания (ready=None):
    для Web-кнопки, которой нельзя держать HTTP-запрос до двух минут —
    любой прокси с read-timeout короче ожидания отдал бы 5xx при
    фактически принятой перезагрузке. Возвращение сервера в этом случае
    показывает карточка собственным поллингом. Пара аудита
    started → финал и peak-метрики закрываются здесь же, в обоих режимах.
    """
    from core import audit
    from core.audit_actions import AuditAction, AuditResult
    from core.operation_metrics import begin, reboot_identity

    operation_id = audit.new_op_id()
    session = begin(reboot_identity(
        operation_id,
        server_id=server.get("id"),
        server_name=server.get("name"),
    ))
    audit.record(
        AuditAction.SERVER_REBOOT,
        result=AuditResult.STARTED,
        server_id=server.get("id"),
        server_name=server.get("name"),
        op_id=operation_id,
    )
    if session is not None:
        session.start()
    accepted = False
    ready: bool | None = None
    attempts = 0
    waited_sec = 0.0
    error = None
    started_at = time.monotonic()
    try:
        accepted, error = _dispatch_reboot(server)
        if accepted and wait_readiness:
            time.sleep(initial_delay)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                attempts += 1
                ready, error = test_connection(server)
                if ready:
                    error = None
                    break
                time.sleep(poll_interval)
            if not ready:
                error = error or "timeout"
        waited_sec = round(time.monotonic() - started_at, 1)
        _audit_reboot(
            server,
            accepted=accepted,
            error=error,
            operation_id=operation_id,
        )
        return RebootOutcome(
            accepted=accepted,
            ready=ready,
            attempts=attempts,
            waited_sec=waited_sec,
            error=error,
            operation_id=operation_id,
        )
    except Exception as exc:
        error = str(exc)
        _audit_reboot(
            server,
            accepted=False,
            error=error,
            operation_id=operation_id,
        )
        return RebootOutcome(
            accepted=False,
            ready=ready,
            attempts=attempts,
            waited_sec=round(time.monotonic() - started_at, 1),
            error=error,
            operation_id=operation_id,
        )
    finally:
        if session is not None:
            session.stop()
            session.close()


def _audit_reboot(
    server: dict,
    *,
    accepted: bool,
    error: str | None,
    operation_id: str | None,
) -> None:
    """Результат reboot — факт принятия команды, не readiness outcome."""
    try:
        from core import audit
        from core.audit_actions import AuditAction, AuditResult

        audit.record(
            AuditAction.SERVER_REBOOT,
            result=AuditResult.OK if accepted else AuditResult.FAILED,
            server_id=server.get("id"),
            server_name=server.get("name"),
            op_id=operation_id,
            error=None if accepted else error,
        )
    except Exception as e:
        print(f"[AUDIT] перезагрузка сервера: пометка не удалась: {e}", flush=True)
