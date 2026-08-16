"""Метрики хоста, на котором запущен Bot4VPS, и статус его компонентов.

Только стандартная библиотека: CPU и память читаются из /proc, диск —
shutil.disk_usage. psutil намеренно не используется, чтобы не тянуть
зависимость на боевой сервер.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..deps import err

router = APIRouter(tags=["system"])

# Предыдущий снимок /proc/stat: CPU считается как разница между вызовами,
# иначе пришлось бы усыплять запрос на интервал измерения.
_cpu_prev: tuple[float, int, int] | None = None   # (ts, total, idle)
_CPU_STALE = 60.0     # снимок старее — считаем непригодным

# Предыдущий снимок /proc/net/dev для Traffic
_net_prev: tuple[float, int, int] | None = None   # (ts, rx_bytes, tx_bytes)
_NET_STALE = 60.0


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return None


def _cpu_sample() -> tuple[int, int] | None:
    """(total, idle) из первой строки /proc/stat."""
    raw = _read("/proc/stat")
    if not raw:
        return None
    for line in raw.splitlines():
        if line.startswith("cpu "):
            parts = [int(x) for x in line.split()[1:] if x.isdigit()]
            if len(parts) < 4:
                return None
            # idle = idle + iowait
            idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
            return sum(parts), idle
    return None


async def _cpu_percent() -> float | None:
    """Загрузка CPU в процентах по разнице двух снимков /proc/stat."""
    global _cpu_prev
    cur = _cpu_sample()
    if cur is None:
        return None
    now = time.monotonic()
    prev = _cpu_prev
    _cpu_prev = (now, cur[0], cur[1])

    # первый вызов или слишком старый снимок — берём короткую пробу на месте
    if prev is None or now - prev[0] > _CPU_STALE:
        await asyncio.sleep(0.12)
        nxt = _cpu_sample()
        if nxt is None:
            return None
        _cpu_prev = (time.monotonic(), nxt[0], nxt[1])
        base, idle_base = cur
    else:
        base, idle_base = prev[1], prev[2]
        nxt = cur

    d_total = nxt[0] - base
    d_idle = nxt[1] - idle_base

    # Два вызова подряд: между ними прошло меньше тика (обычно 10 мс),
    # разница нулевая. Досыпаем и мерим ещё раз, иначе отдали бы N/A.
    if d_total <= 0:
        await asyncio.sleep(0.12)
        again = _cpu_sample()
        if again is None:
            return None
        _cpu_prev = (time.monotonic(), again[0], again[1])
        d_total = again[0] - nxt[0]
        d_idle = again[1] - nxt[1]
        if d_total <= 0:
            return None

    return round(max(0.0, min(100.0, (1 - d_idle / d_total) * 100)), 1)


def _mem() -> tuple[float | None, str]:
    """(процент занятой памяти, «занято / всего»)."""
    raw = _read("/proc/meminfo")
    if not raw:
        return None, "N/A"
    vals: dict[str, int] = {}
    for line in raw.splitlines():
        k, _, rest = line.partition(":")
        num = rest.strip().split(" ")[0]
        if num.isdigit():
            vals[k] = int(num)          # килобайты
    total = vals.get("MemTotal")
    if not total:
        return None, "N/A"
    avail = vals.get("MemAvailable")
    if avail is None:
        avail = (vals.get("MemFree", 0) + vals.get("Cached", 0)
                 + vals.get("Buffers", 0))
    used = max(0, total - avail)
    return round(used / total * 100, 1), f"{_gb(used)} / {_gb(total)} ГБ"


def _gb(kb: int) -> str:
    return f"{kb / 1024 / 1024:.1f}"


def _disk() -> tuple[float | None, str]:
    """(процент занятого диска, «занято / всего») для раздела с ботом."""
    try:
        u = shutil.disk_usage(Path(__file__).resolve().parents[3])
    except OSError:
        return None, "N/A"
    if not u.total:
        return None, "N/A"
    gb = 1024 ** 3
    return (round(u.used / u.total * 100, 1),
            f"{u.used / gb:.1f} / {u.total / gb:.1f} ГБ")


def _uptime() -> float | None:
    """Аптайм хоста в секундах."""
    raw = _read("/proc/uptime")
    if not raw:
        return None
    try:
        return float(raw.split()[0])
    except (ValueError, IndexError):
        return None


def _proc_service_uptime() -> float | None:
    """Аптайм процесса по /proc — резерв, когда systemd недоступен.

    Бот и веб — один процесс, поэтому берём время старта текущего процесса:
    поле 22 в /proc/self/stat (starttime) даётся в тиках с момента загрузки,
    значит аптайм сервиса = аптайм хоста − starttime/HZ. В контейнерах
    (LXC/OpenVZ) /proc/uptime показывает время контейнера, а starttime
    отсчитывается от хоста — разница уходит в минус и обрезается до нуля.
    Поэтому основной источник — systemd, а это лишь запасной путь.
    """
    host = _uptime()
    if host is None:
        return None
    raw = _read("/proc/self/stat")
    if not raw:
        return None
    try:
        # Имя команды в скобках может содержать пробелы — режем по ')'.
        fields = raw[raw.rindex(")") + 1:].split()
        starttime_ticks = float(fields[19])  # 22-е поле минус первые два
        hz = os.sysconf("SC_CLK_TCK") or 100
        return max(0.0, host - starttime_ticks / hz)
    except (ValueError, IndexError, OSError):
        return None


# Время старта юнита спрашиваем у systemd один раз и запоминаем: если systemd
# перезапустит bot4vps, вместе с юнитом умрёт и этот процесс, поэтому значение
# устареть не может. Заодно не дёргаем systemctl на каждый запрос /api/system.
_svc_start: float | None = None     # unix-время старта главного процесса юнита
_svc_start_done = False


def _systemd_start_unix() -> float | None:
    """Unix-время старта bot4vps по данным systemd, иначе None."""
    import subprocess
    try:
        out = subprocess.run(
            ["systemctl", "show", "bot4vps", "--timestamp=unix",
             "--property=ExecMainStartTimestamp", "--value"],
            capture_output=True, timeout=3, text=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None

    # systemd >= 247: «@1786542725» — не зависит ни от локали, ни от таймзоны.
    if out.startswith("@"):
        try:
            return float(out[1:])
        except ValueError:
            return None

    # systemd < 247 игнорирует --timestamp и печатает
    # «Wed 2026-08-12 15:04:05 MSK» в локальном времени: режем день недели
    # и зону, остаток разбираем как локальное время.
    parts = out.split()
    if len(parts) >= 3:
        try:
            stamp = time.strptime(f"{parts[1]} {parts[2]}",
                                  "%Y-%m-%d %H:%M:%S")
            return time.mktime(stamp)
        except (ValueError, OverflowError):
            return None
    return None


async def _service_uptime() -> float | None:
    """Аптайм службы Bot4VPS в секундах."""
    global _svc_start, _svc_start_done
    if not _svc_start_done:
        _svc_start_done = True
        # systemctl — блокирующий вызов, событийный цикл держать нельзя
        _svc_start = await asyncio.to_thread(_systemd_start_unix)
    if _svc_start is not None:
        return max(0.0, time.time() - _svc_start)
    # Запуск не под systemd (например, python3 bot.py) — считаем по /proc.
    return _proc_service_uptime()


def _net_sample() -> tuple[int, int] | None:
    """(rx_bytes, tx_bytes) суммарно по всем интерфейсам /proc/net/dev."""
    raw = _read("/proc/net/dev")
    if not raw:
        return None
    rx_total = tx_total = 0
    for line in raw.splitlines():
        # пропускаем заголовки
        if ":" not in line:
            continue
        # формат: "  eth0: rx_bytes rx_packets ... tx_bytes tx_packets ..."
        iface, _, stats = line.partition(":")
        iface = iface.strip()
        # игнорируем loopback
        if iface == "lo":
            continue
        parts = stats.split()
        if len(parts) < 9:
            continue
        try:
            rx_total += int(parts[0])    # rx_bytes
            tx_total += int(parts[8])    # tx_bytes
        except ValueError:
            continue
    return rx_total, tx_total


async def _traffic() -> tuple[str, float | None, float | None]:
    """Скорость сети: («↓ X ↑ Y», rx Б/с, tx Б/с).

    Числовые скорости нужны фронту для графика сети — из строки их
    парсить нельзя (единицы плавают между Б/КБ/МБ).
    """
    global _net_prev
    cur = _net_sample()
    if cur is None:
        return "N/A", None, None
    now = time.monotonic()
    prev = _net_prev
    _net_prev = (now, cur[0], cur[1])

    # первый вызов или слишком старый снимок — короткая проба
    if prev is None or now - prev[0] > _NET_STALE:
        await asyncio.sleep(1.0)
        nxt = _net_sample()
        if nxt is None:
            return "N/A", None, None
        _net_prev = (time.monotonic(), nxt[0], nxt[1])
        dt = 1.0
        d_rx = nxt[0] - cur[0]
        d_tx = nxt[1] - cur[1]
    else:
        dt = now - prev[0]
        d_rx = cur[0] - prev[1]
        d_tx = cur[1] - prev[2]

    if dt <= 0:
        return "N/A", None, None

    rx_rate = max(0.0, d_rx / dt)
    tx_rate = max(0.0, d_tx / dt)
    label = f"↓ {_human_bytes(rx_rate)}/с ↑ {_human_bytes(tx_rate)}/с"
    return label, round(rx_rate, 1), round(tx_rate, 1)


def _human_bytes(b: float) -> str:
    """Человекочитаемый размер."""
    for unit in ["Б", "КБ", "МБ", "ГБ"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} ТБ"


def _temp() -> str:
    """Температура первого найденного thermal_zone* или N/A."""
    # /sys/class/thermal/thermal_zone0/temp возвращает милликельвины (mC)
    for zone in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            millicelsius = int(zone.read_text())
            celsius = millicelsius / 1000
            return f"{celsius:.1f}°C"
        except (OSError, ValueError):
            continue
    return "N/A"


def _hostname() -> str:
    """Имя хоста."""
    raw = _read("/etc/hostname")
    if raw:
        return raw.strip()
    try:
        import socket
        return socket.gethostname()
    except Exception:
        return "N/A"


def _ip() -> str:
    """Внешний IP машины."""
    try:
        import socket
        # Подключаемся к внешнему адресу, чтобы узнать свой IP
        # (не отправляем данные, просто создаем сокет)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "N/A"


def _os_info() -> dict:
    """Информация об ОС: имя, версия и ядро."""
    try:
        raw = _read("/etc/os-release")
        if raw:
            info = {}
            for line in raw.splitlines():
                if "=" in line:
                    k, _, v = line.partition("=")
                    info[k] = v.strip('"')
            name = info.get("NAME", "Linux")
            version = info.get("VERSION", info.get("VERSION_ID", "N/A"))
            return {
                "name": info.get("PRETTY_NAME", name),
                "short_name": name,
                "version": version,
                "kernel": _kernel(),
            }
    except Exception:
        pass
    return {"name": "Linux", "short_name": "Linux",
            "version": "N/A", "kernel": _kernel()}


def _kernel() -> str:
    """Версия ядра."""
    raw = _read("/proc/version")
    if raw:
        # "Linux version 5.15.0-..."
        parts = raw.split()
        if len(parts) >= 3:
            return parts[2]
    return "N/A"


def _timezone() -> str:
    """Часовой пояс."""
    try:
        import time
        return time.tzname[time.daylight]
    except Exception:
        return "N/A"


def _server_time() -> str:
    """Локальное время хоста, где запущен Bot4VPS: «ДД.ММ.ГГГГ ЧЧ:ММ:СС»."""
    try:
        return time.strftime("%d.%m.%Y %H:%M:%S", time.localtime())
    except Exception:
        return "N/A"





def _refresh_bot_globals_safe() -> None:
    """Обновить BOT_TOKEN/ALLOWED_USERS из config.json.

    На старых bot.py функции может не быть — тогда просто читаем config
    и выставляем атрибуты модуля bot, чтобы статус не падал с ImportError.
    """
    try:
        from bot import refresh_bot_globals
        refresh_bot_globals()
        return
    except ImportError:
        pass
    try:
        import bot as bot_mod
        from core.config import _read_config_raw
        try:
            cfg = _read_config_raw()
        except Exception:
            from core.config import load_config
            cfg = load_config()
        token = (cfg.get("bot_token") or "").strip()
        users = list(cfg.get("allowed_users") or [])
        bot_mod.BOT_TOKEN = token
        if hasattr(bot_mod, "ALLOWED_USERS"):
            bot_mod.ALLOWED_USERS = users
    except Exception:
        pass


def _bot_status() -> dict:
    """Статус Telegram-бота.

    Выключен — ТОЛЬКО если telegram_enabled=false.
    При enabled=true: Работает либо Ошибка (с причиной в error).
    """
    try:
        from bot import BOT_TOKEN, get_application
        from core.config import get_telegram_config, _is_bot_token_configured
        _refresh_bot_globals_safe()
        tg = get_telegram_config()
    except Exception as e:
        return {
            "ok": False,
            "state": "error",
            "detail": "Ошибка",
            "error": str(e),
        }

    if not tg.get("enabled", True):
        return {"ok": False, "state": "disabled", "detail": "Выключен"}

    # --- enabled=true: только Работает / Ошибка ---
    token = (BOT_TOKEN or "").strip()
    if not _is_bot_token_configured(token):
        return {
            "ok": False,
            "state": "no_token",
            "detail": "Ошибка",
            "error": "не задан Bot Token",
        }

    if tg.get("user_id") is None:
        return {
            "ok": False,
            "state": "no_user",
            "detail": "Ошибка",
            "error": "не задан User ID",
        }

    app = get_application()
    if app is None:
        reason = "бот не запущен"
        try:
            from bot import get_last_start_error
            last = get_last_start_error()
            if last:
                reason = last
        except Exception:
            pass
        return {
            "ok": False,
            "state": "stopped",
            "detail": "Ошибка",
            "error": reason,
        }

    try:
        running = bool(app.running)
        polling = bool(app.updater and app.updater.running)
    except Exception as e:
        return {
            "ok": False,
            "state": "error",
            "detail": "Ошибка",
            "error": str(e),
        }

    if running and polling:
        return {"ok": True, "state": "running", "detail": "Работает"}
    if running and not polling:
        return {
            "ok": False,
            "state": "no_polling",
            "detail": "Ошибка",
            "error": "нет polling",
        }
    reason = "бот остановлен"
    try:
        from bot import get_last_start_error
        last = get_last_start_error()
        if last:
            reason = last
    except Exception:
        pass
    return {
        "ok": False,
        "state": "stopped",
        "detail": "Ошибка",
        "error": reason,
    }


def _errors(limit: int = 200) -> dict:
    """Сводка ошибок из журнала событий."""
    try:
        from core.events import get_events
        events = get_events(limit=limit)
    except Exception as e:
        return {"ok": False, "critical": 0, "warning": 0, "detail": str(e)}

    crit = warn = 0
    last = None
    for e in events:
        lvl = (e.get("level") or "").lower()
        if lvl == "critical":
            crit += 1
        elif lvl == "warning":
            warn += 1
        else:
            continue
        if last is None:
            last = {
                "level": lvl,
                "message": e.get("message") or e.get("title") or "",
                "timestamp": e.get("timestamp") or "",
            }
    return {"ok": True, "critical": crit, "warning": warn,
            "scanned": len(events), "last": last}


@router.get("/api/system")
async def api_system():
    """Метрики хоста с ботом + статус Web и Telegram-бота."""
    try:
        cpu = await _cpu_percent()
        ram_pct, ram = _mem()
        disk_pct, disk = _disk()
        traffic, net_rx, net_tx = await _traffic()
        temp = _temp()
        os_info = _os_info()
        return {
            "ok": True,
            "cpu": cpu,
            "ram_pct": ram_pct, "ram": ram,
            "disk_pct": disk_pct, "disk": disk,
            "traffic": traffic,
            # байты/с — фронт строит по ним график сети
            "net_rx": net_rx, "net_tx": net_tx,
            "temp": temp,
            "hostname": _hostname(),
            "ip": _ip(),
            "os": os_info["name"],
            "os_version": os_info["version"],
            "kernel": os_info["kernel"],
            "timezone": _timezone(),
            "server_time": _server_time(),
            "uptime_seconds": _uptime(),
            # аптайм самого сервиса — виджет показывает его отдельно от хоста
            "service_uptime_seconds": await _service_uptime(),
            # запрос дошёл до обработчика — веб-часть заведомо жива
            "web": {"ok": True, "state": "running", "detail": "работает"},
            "bot": _bot_status(),
            "errors": _errors(),
        }
    except Exception as e:
        return err(str(e))


# Аргументы journalctl зафиксированы в коде: это не выполнение произвольных
# команд, а один жёстко заданный вызов только для журнала bot4vps.
# -n 30 отдаёт последние 30 строк сразу, -f оставляет поток открытым.
_JOURNAL_ARGV = [
    "journalctl", "-u", "bot4vps",
    "-n", "30", "-f",
    "--output=short-iso", "--no-pager",
]
_JOURNAL_IDLE = 20.0   # без новых строк — отправляем ping, чтобы не рвался SSE


async def _journal_stream(request: Request):
    """SSE-генератор: строки journalctl как события `line`."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *_JOURNAL_ARGV,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        yield "event: fail\ndata: journalctl не найден\n\n"
        return
    except OSError as e:
        yield f"event: fail\ndata: {e}\n\n"
        return

    yield "event: hello\ndata: ok\n\n"
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                raw = await asyncio.wait_for(
                    proc.stdout.readline(), timeout=_JOURNAL_IDLE)
            except asyncio.TimeoutError:
                yield ": ping\n\n"      # комментарий SSE, фронт его игнорирует
                continue
            if not raw:
                # journalctl закончился сам (нет юнита, нет прав и т.п.).
                # Говорим об этом явно: иначе EventSource сочтёт разрыв
                # аварией и начнёт переподключаться, плодя процессы.
                await proc.wait()
                yield f"event: end\ndata: {proc.returncode}\n\n"
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            # \n внутри строки сломал бы кадр SSE — режем на data-поля
            payload = "".join(f"data: {p}\n" for p in line.split("\n"))
            yield f"event: line\n{payload}\n"
    finally:
        # Клиент закрыл окно или упало соединение — journalctl не должен жить.
        if proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass


@router.get("/api/system/journal")
async def api_system_journal(request: Request):
    """Живой журнал службы bot4vps (SSE). Только чтение, только эта служба."""
    return StreamingResponse(
        _journal_stream(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/system/restart")
async def api_system_restart():
    """Перезапуск службы bot4vps через systemctl."""
    import subprocess
    try:
        subprocess.run(
            ["systemctl", "restart", "bot4vps"],
            check=True,
            capture_output=True,
            timeout=5,
        )
        return {"ok": True, "message": "Служба bot4vps перезапускается"}
    except subprocess.CalledProcessError as e:
        return err(f"Ошибка: {e.stderr.decode('utf-8', errors='replace')}")
    except subprocess.TimeoutExpired:
        return err("Превышено время ожидания")
    except FileNotFoundError:
        return err("systemctl не найден")
    except Exception as e:
        return err(str(e))


# ------------------------------------------------------------------
# Управление Telegram-ботом из Web UI (настройки)
# ------------------------------------------------------------------

from pydantic import BaseModel


class TelegramSettingsBody(BaseModel):
    user_id: str | int | None = None
    bot_token: str | None = None


def _telegram_status_payload() -> dict:
    from core.config import get_telegram_config
    cfg = get_telegram_config()
    status = _bot_status()
    return {
        "ok": True,
        "enabled": bool(cfg.get("enabled", True)),
        "user_id": cfg.get("user_id"),
        "token_set": bool(cfg.get("token_set")),
        "needs_setup": bool(cfg.get("needs_setup")),
        "status": status,
    }


@router.get("/api/telegram/status")
async def api_telegram_status():
    """Статус + настройки Telegram (токен никогда не отдаётся)."""
    return _telegram_status_payload()


@router.post("/api/telegram/start")
async def api_telegram_start():
    """Включить Telegram-бота: telegram_enabled=true + start_telegram.

    Сначала проверяем Token/User ID. Если данных нет — ошибка и
    telegram_enabled НЕ меняем (включение атомарно с точки зрения UI).
    """
    from core.config import set_telegram_enabled, get_telegram_config
    from bot import start_telegram, get_application

    def _running():
        try:
            from bot import is_telegram_running
            return is_telegram_running()
        except ImportError:
            app = get_application()
            if app is None:
                return False
            try:
                return bool(app.running and app.updater and app.updater.running)
            except Exception:
                return False

    _refresh_bot_globals_safe()
    tg = get_telegram_config()
    missing = []
    if not tg.get("token_set"):
        missing.append("Bot Token")
    if tg.get("user_id") is None:
        missing.append("User ID")
    if missing:
        return {
            "ok": False,
            "error": "Сначала задайте: " + ", ".join(missing),
            **_telegram_status_payload(),
        }

    set_telegram_enabled(True)
    if _running():
        return {"ok": True, "message": "Уже запущен", **_telegram_status_payload()}
    try:
        # если application «полуживой» — сначала стоп
        if get_application() is not None:
            from bot import stop_telegram
            await stop_telegram()
        await start_telegram()
        return {"ok": True, "message": "Запущен", **_telegram_status_payload()}
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            **_telegram_status_payload(),
        }


@router.post("/api/telegram/stop")
async def api_telegram_stop():
    """Выключить Telegram-бота: stop + telegram_enabled=false."""
    from core.config import set_telegram_enabled
    from bot import stop_telegram

    try:
        await stop_telegram()
    except Exception as e:
        set_telegram_enabled(False)
        return {"ok": False, "error": str(e), **_telegram_status_payload()}
    set_telegram_enabled(False)
    return {"ok": True, "message": "Остановлен", **_telegram_status_payload()}


@router.post("/api/telegram/restart")
async def api_telegram_restart():
    """Перезапустить Telegram-бота (оставляет telegram_enabled=true).

    Без Token/User ID — ошибка, telegram_enabled не трогаем.
    """
    from core.config import set_telegram_enabled, get_telegram_config
    from bot import get_application

    _refresh_bot_globals_safe()
    tg = get_telegram_config()
    missing = []
    if not tg.get("token_set"):
        missing.append("Bot Token")
    if tg.get("user_id") is None:
        missing.append("User ID")
    if missing:
        return {
            "ok": False,
            "error": "Сначала задайте: " + ", ".join(missing),
            **_telegram_status_payload(),
        }

    set_telegram_enabled(True)
    try:
        try:
            from bot import restart_telegram
            await restart_telegram()
        except ImportError:
            from bot import stop_telegram, start_telegram
            await stop_telegram()
            await start_telegram()
        return {"ok": True, "message": "Перезапущен", **_telegram_status_payload()}
    except Exception as e:
        return {"ok": False, "error": str(e), **_telegram_status_payload()}


@router.post("/api/telegram/settings")
async def api_telegram_settings(body: TelegramSettingsBody):
    """Сохранить User ID и/или Bot Token. Токен пустой — не менять."""
    from core.config import set_telegram_credentials

    try:
        set_telegram_credentials(user_id=body.user_id, bot_token=body.bot_token)
        _refresh_bot_globals_safe()
    except ValueError as e:
        return {"ok": False, "error": str(e), **_telegram_status_payload()}
    except Exception as e:
        return {"ok": False, "error": str(e), **_telegram_status_payload()}
    return {"ok": True, "message": "Сохранено", **_telegram_status_payload()}
