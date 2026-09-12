"""Смена порта Web UI (Настройки → Безопасность).

Порт живёт только в systemd-юните ``/etc/systemd/system/bot4vps.service``
(``ExecStart=... --port N``). Смена порта перезапускает сам сервис, а значит
убивает и процесс-обработчик HTTP-запроса — работу выполняет отсоединённый
раннер (``python -m core.web_port``), переживший restart благодаря
``systemd-run --scope`` (паттерн core/update/updater.py::_launch_runner).

Раннер стартует только на Linux с systemd; в dev-окружении (Windows и т.п.)
endpoint-ы возвращают ``changeable: false``.

Файл состояния ``data/web_port.json`` — источник истины для UI:
``status: pending → restarting → done | failed``. На любом сбое раннер
откатывает юнит к сохранённому содержимому и возвращает сервис на старый порт.

Модуль импортируется и web-слоем (хелперы), и запускается как ``__main__``
раннер — поэтому только stdlib в импортах верхнего уровня.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
STATE_FILE = APP_DIR / "data" / "web_port.json"
# Тот же юнит, что core/backup/bot4vps_sources.py::DEFAULT_SYSTEMD_UNIT —
# дублируем литерал: раннер обязан обходиться без импорта core.
UNIT_PATH = Path("/etc/systemd/system/bot4vps.service")
SERVICE_NAME = "bot4vps"

HEALTH_INTERVAL = 3
HEALTH_TIMEOUT = 45
ROLLBACK_HEALTH_TIMEOUT = 30
LOG_LIMIT = 30


# ==================================================================
# Состояние (data/web_port.json)
# ==================================================================

def _default_state() -> dict:
    return {
        "status": "idle",  # idle|pending|restarting|done|failed
        "old_port": None,
        "new_port": None,
        "started_at": None,
        "finished_at": None,
        "pid": None,
        "error": None,
        "log": [],
    }


def read_state() -> dict:
    """Толерантное чтение: битый/отсутствующий файл -> состояние по умолчанию."""
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("web_port.json: ожидается объект")
        state = _default_state()
        state.update(data)
        return state
    except (OSError, ValueError):
        return _default_state()


def write_state(**patches) -> dict:
    """Read-modify-write + атомарная запись (tmp -> fsync -> os.replace)."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = read_state()
    state.update(patches)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE_FILE)
    return state


def _log(message: str) -> None:
    """Строка в journald (через scope-юнит) + в state.log для UI."""
    print("[web_port] %s" % message, flush=True)
    state = read_state()
    entries = list(state.get("log") or [])
    entries.append("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), message))
    write_state(log=entries[-LOG_LIMIT:])


# ==================================================================
# Хелперы для web-слоя
# ==================================================================

def current_port_from_unit() -> int | None:
    """Порт из ExecStart установленного юнита (None, если юнита/порта нет)."""
    try:
        text = UNIT_PATH.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"--port\s+(\d+)", text)
    return int(m.group(1)) if m else None


def changeable() -> tuple[bool, str | None]:
    """Смена порта доступна: юнит есть, systemd-инструменты в PATH."""
    if not UNIT_PATH.exists():
        return False, "systemd-юнит %s не найден" % UNIT_PATH
    if shutil.which("systemd-run") is None or shutil.which("systemctl") is None:
        return False, "systemd недоступен (разработка без systemd)"
    return True, None


def busy() -> bool:
    return read_state().get("status") in ("pending", "restarting")


def launch(new_port: int) -> int:
    """Запустить раннер отдельным процессом, переживающим restart сервиса.

    systemd-run --scope даёт раннеру собственный cgroup: KillMode=mixed
    юнита при stop SIGKILL-ит все процессы сервисного cgroup через 3с —
    раннер, запущенный обычным Popen, был бы убит собственным restart'ом
    (см. core/update/updater.py::_launch_runner). Popen-фолбэк — только
    для dev-окружений без systemd-run.
    """
    cmd = [sys.executable, "-m", "core.web_port"]
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    try:
        proc = subprocess.Popen(
            ["systemd-run", "--scope", "--collect",
             "--unit", "bot4vps-port-%s" % ts] + cmd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(APP_DIR),
        )
        pid = proc.pid
    except (FileNotFoundError, OSError):
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(APP_DIR),
        )
        pid = proc.pid
    return pid


# ==================================================================
# Раннер (python -m core.web_port)
# ==================================================================

def _atomic_write_unit(text: str) -> None:
    """Атомарная запись юнита: tmp в каталоге юнита -> fsync -> replace."""
    UNIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(UNIT_PATH.parent), prefix="bot4vps.service.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, UNIT_PATH)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _systemctl(*args: str, timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", *args], capture_output=True, text=True, timeout=timeout
    )


def _health_ok(port: int, timeout: float) -> bool:
    """GET /api/upd/health на 127.0.0.1:port; успех = 2 OK подряд.

    Версию сверять не нужно: до смены на новом порту никто не слушает,
    ответить может только перезапущенный сервис (гард loopback-only
    уже встроен в сам эндпоинт).

    Схема — из юнита (``--ssl-certfile`` => https): смена порта не трогает
    TLS-флаги, значит health идёт по той же схеме, что слушает сервис.
    Дублирование core/web_tls.py осознанное — раннер живёт без импортов core.
    """
    try:
        unit_text = UNIT_PATH.read_text(encoding="utf-8")
    except OSError:
        unit_text = ""
    if re.search(r"--ssl-certfile\s+\S+", unit_text):
        url = "https://127.0.0.1:%d/api/upd/health" % port
        ctx = ssl._create_unverified_context()  # самоподписанные тоже валидны
    else:
        url = "http://127.0.0.1:%d/api/upd/health" % port
        ctx = None
    deadline = time.monotonic() + timeout
    streak = 0
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "bot4vps-web-port"}
            )
            with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                streak += 1
                if streak >= 2:
                    return True
            else:
                streak = 0
        except Exception:
            streak = 0
        time.sleep(HEALTH_INTERVAL)
    return False


def _rollback(unit_backup: str, old_port: int, reason: str) -> None:
    """Вернуть исходный юнит, перезапустить сервис, зафиксировать failed."""
    _log("откат: %s" % reason)
    try:
        _atomic_write_unit(unit_backup)
        r = _systemctl("daemon-reload", timeout=60)
        if r.returncode != 0:
            _log("daemon-reload при откате не удался: %s" % (r.stderr or "").strip()[:300])
        r = _systemctl("restart", SERVICE_NAME)
        if r.returncode != 0:
            _log("restart при откате не удался: %s" % (r.stderr or "").strip()[:300])
            raise RuntimeError(r.stderr or "systemctl restart failed")
        # Старый порт должен ответить; если нет — тоже ошибка, но юнит уже
        # восстановлен, сервис перезапущен (следующий старт поднимет его).
        if not _health_ok(old_port, ROLLBACK_HEALTH_TIMEOUT):
            _log("сервис не ответил на старом порту %d" % old_port)
        write_state(
            status="failed",
            error=reason,
            finished_at=datetime.now().isoformat(),
        )
    except Exception as e:
        write_state(
            status="failed",
            error="%s; откат завершился ошибкой: %s" % (reason, e),
            finished_at=datetime.now().isoformat(),
        )


def _apply() -> int:
    state = read_state()
    if state.get("status") != "pending":
        # Идемпотентность против двойного запуска
        print("[web_port] статус %r — ничего не делаю" % state.get("status"), flush=True)
        return 0

    new_port = state.get("new_port")
    old_port = state.get("old_port")
    if not isinstance(new_port, int) or not isinstance(old_port, int):
        write_state(
            status="failed", error="повреждённое состояние (порты)",
            finished_at=datetime.now().isoformat(),
        )
        return 1

    write_state(status="restarting")
    _log("смена порта %d -> %d" % (old_port, new_port))

    # 1. Читаем юнит
    try:
        unit_text = UNIT_PATH.read_text(encoding="utf-8")
    except OSError as e:
        # Юнит не тронут — откатывать нечего, просто фиксируем ошибку
        _log("не удалось прочитать юнит: %s" % e)
        write_state(
            status="failed", error="не удалось прочитать юнит: %s" % e,
            finished_at=datetime.now().isoformat(),
        )
        return 1

    # 2. Точечная замена --port; валидация до записи на диск
    new_text, n = re.subn(r"--port\s+\d+", "--port %d" % new_port, unit_text)
    if n != 1:
        _rollback(unit_text, old_port,
                  "в ExecStart юнита ожидается ровно один «--port N», найдено %d" % n)
        return 1

    # 3. Переписываем юнит атомарно
    try:
        _atomic_write_unit(new_text)
    except OSError as e:
        _rollback(unit_text, old_port, "не удалось записать юнит: %s" % e)
        return 1
    _log("юнит обновлён (--port %d)" % new_port)

    # 4. daemon-reload + restart
    r = _systemctl("daemon-reload", timeout=60)
    if r.returncode != 0:
        _rollback(unit_text, old_port,
                  "daemon-reload не удался: %s" % (r.stderr or "").strip()[:300])
        return 1
    r = _systemctl("restart", SERVICE_NAME)
    if r.returncode != 0:
        _rollback(unit_text, old_port,
                  "systemctl restart не удался: %s" % (r.stderr or "").strip()[:300])
        return 1
    _log("сервис перезапущен, ждём health на порту %d" % new_port)

    # 5. Health-check нового порта
    if _health_ok(new_port, HEALTH_TIMEOUT):
        write_state(
            status="done",
            finished_at=datetime.now().isoformat(),
        )
        _log("готово: Web UI работает на порту %d" % new_port)
        return 0

    _rollback(unit_text, old_port,
              "сервис не поднялся на порту %d за %dс" % (new_port, HEALTH_TIMEOUT))
    return 1


if __name__ == "__main__":
    sys.exit(_apply())
