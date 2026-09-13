import json
import os
import ssl
import socket
import threading
import time
from datetime import datetime
from core.storage import (
    load_servers,
    find_server,
    is_group_ssl_enabled
)

MONITOR_FILE = "monitor.json"

# Блокировка для атомарных RMW над monitor.json.
# Онлайн- и SSL-мониторинг пишут файл из разных потоков (asyncio.to_thread),
# поэтому нужен потокобезопасный locking.
_MONITOR_LOCK = threading.RLock()


def load_monitor():
    if not os.path.exists(MONITOR_FILE):
        return {}
    with open(MONITOR_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_monitor(data):
    with open(MONITOR_FILE, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=4
        )


def get_server_monitor(server_id):
    data = load_monitor()
    return data.get(server_id)


def update_server_uptime(
    server_id: str,
    uptime: str,
    uptime_seconds: float | None = None,
):
    """Сохраняет последнее успешно полученное значение uptime в кэше."""
    if not uptime or uptime == "N/A":
        return

    with _MONITOR_LOCK:
        monitor = load_monitor()
        entry = monitor.setdefault(server_id, {})
        system = entry.setdefault("system", {})
        changed = system.get("uptime") != uptime
        if changed:
            system["uptime"] = uptime

        if uptime_seconds is not None:
            try:
                seconds = float(uptime_seconds)
            except (TypeError, ValueError):
                seconds = None
            if seconds is not None and seconds >= 0:
                cached_seconds = system.get("uptime_seconds")
                if changed or cached_seconds is None:
                    if cached_seconds != seconds:
                        system["uptime_seconds"] = seconds
                        changed = True

        if changed:
            save_monitor(monitor)


STATUS_VALID = "valid"
STATUS_WARNING = "warning"
STATUS_EXPIRED = "expired"
STATUS_ERROR = "error"


def check_certificate(host):
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
    except Exception as e:
        return {
            "status": STATUS_ERROR,
            "error": str(e),
            "checked": datetime.now().strftime("%Y-%m-%d %H:%M")
        }

    expires = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
    days_left = (expires - datetime.now()).days

    if days_left < 0:
        status = STATUS_EXPIRED
    elif days_left <= 5:
        status = STATUS_WARNING
    else:
        status = STATUS_VALID

    return {
        "status": status,
        "days_left": days_left,
        "expires": expires.strftime("%Y-%m-%d"),
        "checked": datetime.now().strftime("%Y-%m-%d %H:%M")
    }


def compare_certificate(old_cert, new_cert):
    if (
        old_cert["status"] == STATUS_VALID
        and new_cert["status"] == STATUS_VALID
        and old_cert["expires"] != new_cert["expires"]
    ):
        return "renewed"

    if (
        old_cert["status"] != STATUS_EXPIRED
        and new_cert["status"] == STATUS_EXPIRED
    ):
        return "expired"

    return None


def update_server_certificate(server):
    if not server.get("certificate_check", True):
        return None

    host = server["host"]
    ssl_host = server.get("ssl_host", host)

    # Тяжёлые сетевые операции — вне блокировки, чтобы не держать лок
    # во время DNS/SSL-проверок.
    try:
        host_ip = socket.gethostbyname(host)
    except OSError:
        host_ip = host

    try:
        ssl_ip = socket.gethostbyname(ssl_host)
    except OSError:
        ssl_ip = ssl_host

    new_cert = check_certificate(ssl_host)

    # Атомарный RMW monitor.json — под блокировкой.
    with _MONITOR_LOCK:
        monitor = load_monitor()
        entry = monitor.setdefault(server["id"], {})

        old_cert = entry.get("certificate")
        event = None

        if old_cert:
            event = compare_certificate(old_cert, new_cert)

        entry["name"] = server["name"]
        entry["host"] = host
        entry["host_ip"] = host_ip
        entry["ssl_host"] = ssl_host
        entry["ssl_ip"] = ssl_ip
        entry["certificate"] = new_cert

        save_monitor(monitor)

    if event:
        print(f"{server['name']}: {event}", flush=True)
        return {
            "server_id": server["id"],
            "server_name": server["name"],
            "event": event,
            "old_expires": old_cert["expires"],
            "new_expires": new_cert["expires"]
        }
    return None


def run_monitor(group_name: str | None = None):
    servers = load_servers()
    if group_name:
        servers = [s for s in servers if s.get("group") == group_name]

    events = []
    for server in servers:
        if not is_group_ssl_enabled(server.get("group", "")):
            continue
        if not server.get("certificate_check", False):
            continue

        print(f"SSL: {server['name']}")
        event = update_server_certificate(server)
        if event:
            events.append(event)

    return events


def run_daily_monitor():
    return run_monitor()


def refresh_server_state(server_id: str):
    """
    Обновляет состояние сервера после выполнения скриптов.
    Сейчас обновляет только SSL. В будущем можно расширить.
    """

    server = find_server(server_id)
    if not server:
        return False

    updated = False

    if server.get("certificate_check"):
        try:
            update_server_certificate(server)
            updated = True
            print(f"[STATE] SSL обновлён для сервера: {server.get('name')}", flush=True)
        except Exception as e:
            print(f"[STATE] Ошибка обновления SSL для {server.get('name')}: {e}", flush=True)

    return updated

# ==========================================================
# Лёгкий опрос доступности (TCP, без SSH)
#
# Используется, когда панель открыта (SSE-клиент активен):
# свежий статус без тяжёлого SSH-прогона. Обновляет только
# availability (сеть/статус), system-блок не трогает.
# ==========================================================

# Сколько секунд статус считается актуальным для лёгкого опроса.
LIGHT_CHECK_TTL_SECONDS = 30.0

# Дедупликация: id серверов, чей пинг уже в полёте (другой поток/вкладка).
_inflight_light_checks: set[str] = set()
_inflight_lock = threading.Lock()


def _probe_server_online(server: dict) -> bool:
    """Лёгкая проба по ядерному критерию: ICMP → TCP port → 80 → 443.

    Единый зонд для availability-монитора и SSE-петли (см. _probe_network).
    """
    from core.servers import _probe_network
    try:
        _ms, network = _probe_network(
            server.get("host") or "", server.get("port") or 22
        )
        return network != "none"
    except Exception:
        return False


def light_check_stale(server: dict, monitor: dict | None = None) -> bool:
    """Нужен ли лёгкий опрос: статуса нет либо он старше LIGHT_CHECK_TTL_SECONDS."""
    entry = (monitor if monitor is not None else load_monitor()).get(server.get("id")) or {}
    avail = entry.get("availability") or {}
    if avail.get("online") is None:
        return True
    checked = avail.get("checked")
    if not checked:
        return True
    try:
        checked_at = datetime.strptime(str(checked), "%Y-%m-%d %H:%M")
    except ValueError:
        return True
    return (datetime.now() - checked_at).total_seconds() > LIGHT_CHECK_TTL_SECONDS


def light_check_servers(servers: list[dict]) -> list[dict]:
    """
    Лёгкая проверка списка серверов, обновляет availability.

    Проба — ядерный критерий (ICMP → TCP port → 80 → 443), SSH не трогает.
    Возвращает список событий online/offline для уведомлений.
    Серверы с актуальным статусом и уже проверяемые — пропускаются.
    """
    if not servers:
        return []

    with _inflight_lock:
        todo = [s for s in servers if s.get("id") and s["id"] not in _inflight_light_checks]
        for s in todo:
            _inflight_light_checks.add(s["id"])
    if not todo:
        return []

    # Актуальность переоцениваем под общим снимком monitor (одна загрузка файла).
    monitor = load_monitor()
    todo = [s for s in todo if light_check_stale(s, monitor)]

    events = []
    try:
        for server in todo:
            server_id = server["id"]
            try:
                online = _probe_server_online(server)
                event = update_server_availability(
                    server,
                    online=online,
                    error="",
                    # system не передаём: проба не даёт системных данных
                )
                if event:
                    events.append(event)
            except Exception as e:
                print(f"[LIGHT CHECK] Ошибка для {server.get('name', '?')}: {e}", flush=True)
            finally:
                with _inflight_lock:
                    _inflight_light_checks.discard(server_id)
    finally:
        # гарантированно чистим, если серверы исчезли из todo после фильтра
        with _inflight_lock:
            for s in todo:
                _inflight_light_checks.discard(s.get("id"))
    return events


# ==========================================================
# Мониторинг доступности
# ==========================================================
def refresh_ssh_error(server, ok: bool, error: str = ""):
    """Живые SSH-пробы (metrics/probe из Web) сразу синхронизируют
    ssh_error в monitor, не дожидаясь system_sync (15 минут):
    статус в списке серверов сам выздоравливает и сам желтеет.
    Пишет только при изменении — виджет опрашивает каждые 3 секунды.
    """
    sid = server.get("id")
    if not sid:
        return
    new = "" if ok else (error or "")
    with _MONITOR_LOCK:
        monitor = load_monitor()
        avail = (monitor.get(sid) or {}).get("availability")
        if not avail:
            return
        if (avail.get("ssh_error") or "") == new:
            return
        avail["ssh_error"] = new
        avail["checked"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        save_monitor(monitor)


# ==========================================================
# Живые SSH-пробы (страница «Серверы» открыта)
# ==========================================================
# Тот же принцип, что у метрик дашборда: страница сама дёргает пробу
# каждые ~3с, пока открыта. Закрыли вкладку — проб нет. Гварды не дают
# пробам наслаиваться (мёртвый сервер висит в connect до 8с).
_SSH_PROBE_MIN_INTERVAL = 2.5
_ssh_probe_lock = threading.Lock()
_ssh_probe_last: dict[str, float] = {}
_ssh_probe_inflight: set[str] = set()

# Backoff авто-проб после неудачного SSH. Список «Серверы» дёргает развёртку
# каждые ~3с, карточка — /metrics и /probe каждые 5с: с неверным паролем в
# servers.json это ~20 неудачных аутентификаций в минуту, и панель банит себя
# сама (fail2ban на сервере). После любой неудачи подключения
# (create_ssh_client) авто-пробы ждут _SSH_BACKOFF_INTERVAL; успех любого
# подключения сбрасывает backoff. Явные действия пользователя (QS, терминал,
# бэкапы) не ограничены — гейт стоит только у автоматических проб.
_SSH_BACKOFF_INTERVAL = 60.0
_ssh_probe_failures: dict[str, int] = {}


def note_ssh_probe(server_id: str):
    """Внешняя SSH-проба (метрики/probe дашборда) отмечается здесь,
    чтобы фоновая развёртка не пробивала тот же сервер повторно
    в том же такте."""
    if not server_id:
        return
    with _ssh_probe_lock:
        _ssh_probe_last[server_id] = time.monotonic()


def note_ssh_failure(server_id: str):
    """Неудачное SSH-подключение (любой потребитель): авто-пробы уходят
    в backoff, окно ожидания отсчитывается от этой неудачи."""
    if not server_id:
        return
    with _ssh_probe_lock:
        _ssh_probe_failures[server_id] = _ssh_probe_failures.get(server_id, 0) + 1
        _ssh_probe_last[server_id] = time.monotonic()


def note_ssh_success(server_id: str):
    """Успешное SSH-подключение снимает backoff — сервер снова доступен."""
    if not server_id:
        return
    with _ssh_probe_lock:
        _ssh_probe_failures.pop(server_id, None)


def _probe_interval_locked(server_id: str) -> float:
    """Минимальный интервал авто-проб: номинал ~3с, в backoff — минута."""
    if server_id in _ssh_probe_failures:
        return _SSH_BACKOFF_INTERVAL
    return _SSH_PROBE_MIN_INTERVAL


def ssh_probe_throttled(server_id: str) -> bool:
    """Ждать ли авто-пробе (metrics/probe открытой карточки, развёртка
    списка) из-за недавней неудачи SSH."""
    if not server_id:
        return False
    with _ssh_probe_lock:
        return _throttled_locked(server_id, time.monotonic())


def _throttled_locked(server_id: str, now: float) -> bool:
    if server_id not in _ssh_probe_failures:
        return False
    return now - _ssh_probe_last.get(server_id, 0.0) < _SSH_BACKOFF_INTERVAL


def ssh_probe_one(server) -> tuple[bool, str]:
    """Минимальная SSH-проба: рукопожатие + аутентификация, без команд."""
    from core.ssh import create_ssh_client
    if server.get("auth_type") == "key":
        key_path = str(server.get("key_path") or "")
        if key_path and not os.path.exists(key_path):
            return False, f"SSH-ключ не найден: {key_path}"
    try:
        client = create_ssh_client(server)
        try:
            client.close()
        except Exception:
            pass
        return True, ""
    except Exception as e:
        return False, str(e)


def ssh_probe_servers(servers):
    """Фоновая SSH-развёртка всех серверов (страница «Серверы» открыта).

    Гварды: не чаще раза в такт на сервер, без наложения на уже идущие
    и внешние (note_ssh_probe) пробы. Результат — refresh_ssh_error в
    monitor.json; UI получает его следующим SSE-снапшотом.
    """
    now = time.monotonic()
    todo = []
    with _ssh_probe_lock:
        for s in servers:
            sid = s.get("id")
            if not sid or sid in _ssh_probe_inflight:
                continue
            # интервал на сервер: номинал ~3с, после неудачи SSH — backoff
            if now - _ssh_probe_last.get(sid, 0.0) < _probe_interval_locked(sid):
                continue
            _ssh_probe_inflight.add(sid)
            _ssh_probe_last[sid] = now
            todo.append(s)
    if not todo:
        return

    def _run(server):
        try:
            ok, error = ssh_probe_one(server)
            refresh_ssh_error(server, ok, error)
        except Exception as e:
            print(f"[SSH PROBE] {server.get('name', '?')}: {e}", flush=True)
        finally:
            with _ssh_probe_lock:
                _ssh_probe_inflight.discard(server.get("id"))

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(16, len(todo))) as ex:
        list(ex.map(_run, todo))


def update_server_availability(
    server,
    online: bool,
    error: str = "",
    system: dict | None = None,
    ssh_error: str | None = None,
):
    """
    Обновляет состояние доступности сервера.

    system — опциональный блок системных сведений (hostname, ОС, ядро…),
    собранный в том же SSH-запросе, что и метрики. Пишется только если
    передан (при недоступном SSH прежние данные не затираются).

    error — сетевая ошибка недоступности (для события offline).
    ssh_error — ошибка SSH-аутентификации: НЕ флипает online/offline,
    хранится отдельно (индикация в UI «⚠ SSH: ошибка»).
    None = проба SSH не выполнялаcь — прежнее значение сохраняется
    (сетевые зонды не должны затирать статус, записанный SSH-пробой
    из metrics/system_sync).

    Возвращает:
        None
        {
            "server_id": "...",
            "server_name": "...",
            "event": "offline" | "online",
            "error": "..."
        }
    """

    with _MONITOR_LOCK:

        monitor = load_monitor()

        entry = monitor.setdefault(server["id"], {})

        availability = entry.get("availability")

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        if system is not None:
            entry["system"] = system

        # Первый запуск / новый сервер
        if availability is None:
            entry["availability"] = {
                "online": online,
                "last_error": error,
                "ssh_error": ssh_error or "",
                "checked": now
            }

            save_monitor(monitor)
            return None

        previous_online = availability["online"]

        availability["online"] = online
        availability["last_error"] = error
        # SSH-проба не выполнялась — статус аутентификации не трогаем
        if ssh_error is not None:
            availability["ssh_error"] = ssh_error
        availability["checked"] = now

        save_monitor(monitor)

    if previous_online == online:
        return None

    if online:
        return {
            "server_id": server["id"],
            "server_name": server["name"],
            "event": "online"
        }

    return {
        "server_id": server["id"],
        "server_name": server["name"],
        "event": "offline",
        "error": error
    }

def check_server_availability(server):
    """
    Проверяет доступность сервера и обновляет состояние мониторинга.
    Возвращает:
        (info, event)
    """
    from core.servers import (
        get_server_info,
        is_server_online,
    )
    info = get_server_info(server)

    # system — только при успешном SSH, чтобы не затирать кэш N/A
    system = None
    if info.get("ssh"):
        system = {
            "hostname": info.get("hostname") or "N/A",
            "os": info.get("os") or "N/A",
            "os_version": info.get("os_version") or "N/A",
            "kernel": info.get("kernel") or "N/A",
            "arch": info.get("arch") or "N/A",
            "uptime": info.get("uptime") or "N/A",
            "uptime_seconds": info.get("uptime_seconds"),
        }

    # Доступность — чисто сетевой критерий (см. _probe_network):
    # плохой пароль/ключ НЕ переводит сервер в offline — это отдельное поле
    # ssh_error для индикации, не событие «сервер недоступен».
    event = update_server_availability(
        server,
        online=is_server_online(info),
        error="",
        ssh_error=info.get("ssh_error") or "",
        system=system,
    )
    return info, event

# ==========================================================
# Job-функции для JobQueue
# ==========================================================

# Ядерный интервал SSH-сбора system-данных (молчаливый job).
SYSTEM_SYNC_INTERVAL_MIN = 15


async def availability_monitor_job(context):
    """Лёгкий сетевой монитор доступности с уведомлениями.

    Настраивается в Настройках (секция online: enabled/interval).
    Проба — новый критерий (ICMP → TCP port → 80 → 443), параллельно,
    SSH не трогает. Событие online/offline → уведомление.
    """
    from concurrent.futures import ThreadPoolExecutor
    from core.storage import load_servers
    from core.event_service import notify_event
    from core.event_types import EventType, EventLevel, EventReason

    servers = load_servers()

    def _probe(server: dict) -> dict | None:
        """Лёгкая проба одного сервера: возвращает событие смены или None."""
        from core.servers import _probe_network
        try:
            _ms, network = _probe_network(
                server.get("host") or "", server.get("port") or 22
            )
        except Exception:
            network = "none"
        online = network != "none"
        try:
            return update_server_availability(server, online=online, error="")
        except Exception as e:
            print(f"[AVAILABILITY] {server.get('name', '?')}: {e}", flush=True)
            return None

    events: list[dict] = []
    if servers:
        with ThreadPoolExecutor(max_workers=min(16, len(servers))) as ex:
            for event in ex.map(_probe, servers):
                if event:
                    events.append(event)

    for event in events:
        try:
            if event["event"] == "offline":
                details = {**event, "reason": EventReason.SERVER_OFFLINE.value}
                message = (
                    f"Сервер «{event['server_name']}» стал недоступен."
                    + (f"\nОшибка: {event.get('error')}" if event.get("error") else "")
                )
                await notify_event(
                    EventType.SERVER, EventLevel.CRITICAL,
                    "Сервер недоступен", message, details,
                )
            elif event["event"] == "online":
                details = {**event, "reason": EventReason.SERVER_ONLINE.value}
                await notify_event(
                    EventType.SERVER, EventLevel.INFO,
                    "Сервер снова доступен",
                    f"Сервер «{event['server_name']}» снова в сети.", details,
                )
        except Exception as e:
            print(f"[AVAILABILITY] notify: {e}", flush=True)


async def online_monitor_job(context):
    """Ядерный SSH-job: обновляет system-данные в monitor.json.

    Молчаливый: SSH-сбор (hostname, ОС, uptime, RAM…), уведомления НЕ шлёт —
    уведомления о доступности/недоступности теперь зона лёгкого
    availability-монитора. Интервал ядерный (см. schedule_monitor_jobs),
    настройки в UI для него не выносятся.
    """
    from concurrent.futures import ThreadPoolExecutor
    from core.storage import load_servers

    servers = load_servers()

    def _collect(server: dict) -> None:
        try:
            check_server_availability(server)
        except Exception as e:
            print(
                f"[SYSTEM SYNC] Ошибка для {server.get('name', '?')}: {e}",
                flush=True,
            )

    # Параллельно: серверы собираются за ~max(SSH), а не за сумму
    if servers:
        with ThreadPoolExecutor(max_workers=min(8, len(servers))) as ex:
            list(ex.map(_collect, servers))


def _load_reported_missing_keys() -> dict:
    """Состояние «уже пожаловались на отсутствие ключа» (анти-спам)."""
    path = os.path.join("data", "key_integrity.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        return state if isinstance(state.get("reported"), dict) else {"reported": {}}
    except Exception:
        return {"reported": {}}


def _save_reported_missing_keys(state: dict) -> None:
    path = os.path.join("data", "key_integrity.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, path)


async def keys_integrity_job(context):
    """Проверка SSH-ключей серверов: файл из key_path должен существовать.

    Ключ мог быть удалён вручную или из «Файлов» — сервер молча потеряет
    доступ по SSH. Жалуемся один раз на каждый ключ (пока не вернётся):
    CRITICAL-событие + уведомление. Локальная проверка ФС, SSH не трогает.
    """
    from core.event_service import notify_event
    from core.event_types import EventType, EventLevel, EventReason

    state = _load_reported_missing_keys()
    reported: dict = state["reported"]

    missing: list[dict] = []
    for server in load_servers():
        if server.get("auth_type") != "key":
            continue
        key_path = str(server.get("key_path") or "")
        if not key_path or os.path.exists(key_path):
            continue
        missing.append({
            "server": server.get("name") or server.get("host") or server.get("id") or "?",
            "key_path": key_path,
        })

    # новые пропажи → событие; вернувшиеся ключи молча убираем из state
    for item in missing:
        if item["key_path"] in reported:
            continue
        reported[item["key_path"]] = datetime.now().isoformat(timespec="seconds")
        try:
            await notify_event(
                EventType.SSH,
                EventLevel.CRITICAL,
                "SSH-ключ сервера не найден",
                f"Сервер «{item['server']}» использует ключ "
                f"{item['key_path']}, но файла нет — SSH-подключение невозможно. "
                f"Восстановите ключ из резервной копии или смените способ входа.",
                {
                    "reason": EventReason.SSH_KEY_MISSING.value,
                    "server_name": item["server"],
                    "key_path": item["key_path"],
                },
            )
        except Exception as e:
            print(f"[KEY INTEGRITY] notify: {e}", flush=True)

    for key_path in list(reported):
        if key_path not in {m["key_path"] for m in missing}:
            del reported[key_path]

    _save_reported_missing_keys({"reported": reported})


async def ssl_monitor_job(context):
    """Периодический SSL-мониторинг"""
    from core.event_service import notify_event
    from core.event_types import EventType, EventLevel, EventReason

    events = run_daily_monitor()

    if not events:
        return

    for event in events:
        if event["event"] == "renewed":
            details = {
                **event,
                "reason": EventReason.SSL_RENEWED.value,
            }
            message = (
                f"Сертификат сервера "
                f"«{event['server_name']}» успешно обновлён."
            )
            await notify_event(
                EventType.SSL,
                EventLevel.INFO,
                "SSL сертификат обновлён",
                message,
                details,
            )

        elif event["event"] == "expired":
            details = {
                **event,
                "reason": EventReason.SSL_EXPIRED.value,
            }
            message = (
                f"Сертификат сервера "
                f"«{event['server_name']}» истёк."
            )
            await notify_event(
                EventType.SSL,
                EventLevel.CRITICAL,
                "SSL сертификат истёк",
                message,
                details,
            )


def schedule_monitor_jobs(job_queue):
    """
    Пересоздаёт jobs мониторинга на основе текущего config.json.
    Вызывается при старте и после изменения настроек в админке.

    Ядерный system-sync (SSH-сбор) планируется всегда, с фиксированным
    интервалом SYSTEM_SYNC_INTERVAL_MIN: это не настройка, а часть ядра —
    system-данные в monitor.json нужны постоянно. Настройка «online»
    в config.json теперь управляет availability-монитором
    (лёгкий сетевой чек с уведомлениями), а не SSH-сбором.
    """
    from core.config import get_monitor_config

    monitor = get_monitor_config()

    for name in ("online_monitor", "ssl_monitor", "system_sync", "keys_integrity"):
        for job in job_queue.get_jobs_by_name(name):
            job.schedule_removal()

    # Ядерный молчаливый SSH-сбор — всегда
    job_queue.run_repeating(
        online_monitor_job,
        interval=SYSTEM_SYNC_INTERVAL_MIN * 60,
        first=30,
        name="system_sync",
    )
    print(
        f"[JOBS] system_sync (SSH, молча): every {SYSTEM_SYNC_INTERVAL_MIN} min",
        flush=True,
    )

    # Целостность SSH-ключей: локальная проверка ФС, всегда
    job_queue.run_repeating(
        keys_integrity_job,
        interval=SYSTEM_SYNC_INTERVAL_MIN * 60,
        first=45,
        name="keys_integrity",
    )
    print("[JOBS] keys_integrity: every %d min" % SYSTEM_SYNC_INTERVAL_MIN, flush=True)

    # Availability-монитор: лёгкая сетевая проба + уведомления
    if monitor["online"]["enabled"]:
        job_queue.run_repeating(
            availability_monitor_job,
            interval=monitor["online"]["interval"] * 60,
            first=60,
            name="online_monitor",
        )
        print(
            f"[JOBS] availability_monitor: every {monitor['online']['interval']} min",
            flush=True,
        )
    else:
        print("[JOBS] availability_monitor: disabled", flush=True)

    if monitor["ssl"]["enabled"]:
        job_queue.run_repeating(
            ssl_monitor_job,
            interval=monitor["ssl"]["interval"] * 60,
            first=15,
            name="ssl_monitor",
        )
        print(
            f"[JOBS] ssl_monitor: every {monitor['ssl']['interval']} min",
            flush=True,
        )
    else:
        print("[JOBS] ssl_monitor: disabled", flush=True)

    # Суточная проверка обновлений Bot4VPS (встроенный updater, 4.0+)
    from core.update.scheduler import schedule_update_jobs

    schedule_update_jobs(job_queue)
