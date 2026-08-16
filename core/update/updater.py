"""Ядро встроенного updater'а Bot4VPS (логика внутри процесса).

Ответственности:
- проверка новой версии по changelog из ветки main (единственный источник
  для проверки и обычного обновления);
- хранение состояния в data/update/state.json (атомарная запись);
- локальные changelog-файлы: changelog.md (текущая версия) и
  changelog_new.md (найденное обновление);
- запуск runner'а (core/update/runner.py) вне процесса для установки;
- реконсиляция состояния на старте после перезапуска.

HTTP — только stdlib urllib.request (новых зависимостей нет), вызовы из
async-кода идут через asyncio.to_thread.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from core.version import APP_VERSION

# --- GitHub (публичный репозиторий) -------------------------------
REPO_URL = "https://github.com/crashdmd/Bot4VPS"
CHANGELOG_URL = "https://raw.githubusercontent.com/crashdmd/Bot4VPS/main/core/update/changelog.md"
MAIN_TARBALL_URL = "https://codeload.github.com/crashdmd/Bot4VPS/tar.gz/refs/heads/main"
RELEASES_API = "https://api.github.com/repos/crashdmd/Bot4VPS/releases?per_page=100"
USER_AGENT = "Bot4VPS-Updater"

# --- Локальные файлы ----------------------------------------------
UPDATE_DIR = Path("data/update")
STATE_FILE = UPDATE_DIR / "state.json"
CHANGELOG_FILE = UPDATE_DIR / "changelog.md"          # только текущая версия
CHANGELOG_NEW_FILE = UPDATE_DIR / "changelog_new.md"  # найденное обновление

# Автооткат поддерживается только версиями с updater'ом на борту.
MIN_ROLLBACK_VERSION = (3, 0, 0)

_HTTP_TIMEOUT = 20
_BUSY_STATUSES = ("checking", "downloading", "installing", "rolling_back")

_VERSION_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$", re.IGNORECASE)
_SECTION_RE = re.compile(r"(?m)^## (\d+(?:\.\d+){0,2})\s*$")


# ==================================================================
# Версии и changelog
# ==================================================================

def parse_version(value: str) -> tuple[int, int, int]:
    """Нормализовать версию: 'v4.0' / '4.0' / 'v4.0.0' -> (4, 0, 0).

    Непоследовательные теги репозитория (v3.1, v2.1.0) приводятся к
    единому X.Y.Z; недостающие компоненты — 0.
    """
    s = str(value or "").strip()
    m = _VERSION_RE.match(s)
    if not m:
        raise ValueError("Неверный формат версии: %r" % value)
    parts = [int(g) if g else 0 for g in m.groups()]
    return (parts[0], parts[1], parts[2])


def parse_changelog_versions(md: str) -> list[str]:
    """Версии по заголовкам «## X.Y.Z» (в порядке появления в файле)."""
    return _SECTION_RE.findall(md or "")


def extract_changelog_section(md: str, version: str) -> str:
    """Текст секции «## <version>» до следующего «## » или конца файла."""
    want = parse_version(version)
    matches = list(_SECTION_RE.finditer(md or ""))
    for i, m in enumerate(matches):
        if parse_version(m.group(1)) == want:
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
            return md[start:end].strip()
    return ""


# ==================================================================
# Состояние (data/update/state.json)
# ==================================================================

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_state() -> dict:
    return {
        "schema": 1,
        "current_version": APP_VERSION,
        "previous_version": None,
        "status": "idle",  # idle|checking|downloading|installing|rolling_back|failed
        "available": None,  # None | {"version": "X.Y.Z", "found_at": ISO}
        "last_check": None,
        "last_check_error": None,
        "last_update_at": None,
        "action": None,  # None | {"type","target","started_at","backup_dir"}
        "last_error": None,
        "pid": None,
    }


def read_state() -> dict:
    """Толерантное чтение: битый/отсутствующий файл -> состояние по умолчанию."""
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("state.json: ожидается объект")
        state = default_state()
        state.update(data)
        return state
    except (OSError, ValueError):
        return default_state()


def write_state(**patches) -> dict:
    """Read-modify-write + атомарная запись (tmp -> fsync -> os.replace)."""
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    state = read_state()
    state.update(patches)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.flush()
        import os as _os
        _os.fsync(f.fileno())
    import os as _os
    _os.replace(tmp, STATE_FILE)
    return state


# ==================================================================
# HTTP (stdlib)
# ==================================================================

def _http_get(url: str, timeout: int = _HTTP_TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_changelog() -> str:
    """Актуальный changelog.md из ветки main."""
    return _http_get(CHANGELOG_URL).decode("utf-8", errors="replace")


# ==================================================================
# Проверка обновлений
# ==================================================================

async def check_for_update(*, notify: bool) -> dict:
    """Сравнить верхнюю версию changelog из main с установленной.

    Никогда не бросает исключение: ошибки сети уходят в
    state.last_check_error. Возвращает срез состояния для UI.
    """
    if read_state()["status"] in _BUSY_STATUSES:
        return {"status": read_state()["status"], "update_available": False,
                "busy": True}

    write_state(status="checking")
    try:
        md = await asyncio.to_thread(fetch_changelog)
        versions = parse_changelog_versions(md)
        if not versions:
            raise ValueError("changelog.md в main не содержит заголовков «## X.Y.Z»")

        top = versions[0]
        is_newer = parse_version(top) > parse_version(APP_VERSION)
        if is_newer:
            section = extract_changelog_section(md, top)
            UPDATE_DIR.mkdir(parents=True, exist_ok=True)
            CHANGELOG_NEW_FILE.write_text(section + "\n", encoding="utf-8")
            write_state(
                available={"version": top, "found_at": _now_iso()},
                last_check=_now_iso(),
                last_check_error=None,
                status="idle",
            )
            if notify:
                await _notify_found(top)
            return {"status": "idle", "update_available": True, "version": top}

        # Обновлений нет: сброс найденного (main мог уехать назад/версию сняли)
        if CHANGELOG_NEW_FILE.exists():
            CHANGELOG_NEW_FILE.unlink()
        write_state(
            available=None,
            last_check=_now_iso(),
            last_check_error=None,
            status="idle",
        )
        return {"status": "idle", "update_available": False}
    except Exception as e:  # сеть/парсинг — не роняем вызывающего
        message = _friendly_check_error(e)
        write_state(
            last_check=_now_iso(),
            last_check_error=message,
            status="idle",
        )
        return {"status": "idle", "update_available": False, "error": message}


def _friendly_check_error(e: Exception) -> str:
    """Человекочитаемое сообщение об ошибке проверки вместо сырого HTTP."""
    import urllib.error

    if isinstance(e, urllib.error.HTTPError):
        if e.code == 404:
            return (
                "changelog.md не найден в ветке main репозитория "
                "(появится после публикации версии 4.0.0)"
            )
        if e.code == 403:
            return "GitHub отклонил запрос (лимит API). Повторите позже"
        return "GitHub вернул ошибку %d" % e.code
    if isinstance(e, urllib.error.URLError):
        return "Нет соединения с GitHub: %s" % (e.reason or e)
    return str(e)


async def _notify_found(version: str) -> None:
    from core.event_service import notify_event
    from core.event_types import EventLevel, EventReason, EventType

    await notify_event(
        EventType.UPDATE,
        EventLevel.INFO,
        "Доступно обновление Bot4VPS",
        "Найдена новая версия %s (установлена %s)." % (version, APP_VERSION),
        details={
            "version": version,
            "current": APP_VERSION,
            "reason": EventReason.UPDATE_AVAILABLE.value,
        },
    )


# ==================================================================
# Версии для отката + GitHub Releases
# ==================================================================

def list_rollback_versions() -> list[str]:
    """Версии ≥ 3.0.0 из из локального changelog.md (кроме текущей), новые сверху.

    Releases здесь НЕ опрашиваются: список определяется заголовками
    changelog.md в main (ТЗ п.15).
    """
    md = Path(__file__).with_name("changelog.md").read_text(
        encoding="utf-8"
    )
    current = parse_version(APP_VERSION)
    seen: set[tuple[int, int, int]] = set()
    result: list[str] = []
    for v in parse_changelog_versions(md):
        t = parse_version(v)
        if t < MIN_ROLLBACK_VERSION or t == current or t in seen:
            continue
        seen.add(t)
        result.append(v)
    result.sort(key=parse_version, reverse=True)
    return result


def resolve_release(version: str) -> dict:
    """Найти GitHub Release по нормализованной версии (только для отката).

    Возвращает {"version", "asset_url"}: первый кастомный ассет
    (.tar.gz/.tgz), иначе — автогенерируемый tarball_url релиза.
    """
    want = parse_version(version)
    data = json.loads(_http_get(RELEASES_API).decode("utf-8"))
    for rel in data if isinstance(data, list) else []:
        tag = str(rel.get("tag_name") or "")
        try:
            if parse_version(tag) != want:
                continue
        except ValueError:
            continue
        asset_url = None
        for asset in rel.get("assets") or []:
            name = str(asset.get("name") or "").lower()
            if name.endswith((".tar.gz", ".tgz")):
                asset_url = asset.get("browser_download_url")
                if asset_url:
                    break
        url = asset_url or rel.get("tarball_url")
        if not url:
            continue
        return {"version": version, "asset_url": url}
    raise ValueError(
        "Версия %s не найдена в GitHub Releases" % normalize_version(want)
    )


def normalize_version(t: tuple[int, int, int]) -> str:
    return "%d.%d.%d" % t


# ==================================================================
# Запуск установки (runner вне процесса)
# ==================================================================

def _app_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _service_name() -> str:
    return "bot4vps"


def _health_port() -> int:
    """Порт из установленного systemd-юнита (fallback 8080)."""
    unit = Path("/etc/systemd/system/bot4vps.service")
    try:
        text = unit.read_text(encoding="utf-8")
        m = re.search(r"--port\s+(\d+)", text)
        if m:
            return int(m.group(1))
    except OSError:
        pass
    return 8080


def _build_job(action: str, target: str, download_url: str, work_dir: Path) -> dict:
    return {
        "action": action,  # "update" | "rollback"
        "target_version": target,
        "previous_version": APP_VERSION,
        "app_dir": str(_app_dir()),
        "venv_python": sys.executable,
        "service_name": _service_name(),
        "download_url": download_url,
        "state_file": str(_app_dir() / STATE_FILE),
        "work_dir": str(work_dir),
        "health_port": _health_port(),
        "health_timeout": 120,
        "dev_no_systemd": False,
    }


def _launch_runner(job: dict) -> int:
    """Запустить runner.py отдельным процессом, переживающим restart.

    systemd-run --scope даёт раннеру собственный cgroup: KillMode=mixed
    юнита при stop SIGKILL-ит все процессы сервисного cgroup через 3с —
    раннер, запущенный обычным Popen, был бы убит собственным restart'ом.
    Фолбэк (нет systemd-run, локальная разработка): Popen в новой сессии.
    """
    work_dir = Path(job["work_dir"])
    work_dir.mkdir(parents=True, exist_ok=True)
    src = Path(__file__).with_name("runner.py")
    dst = work_dir / "runner.py"
    shutil.copyfile(src, dst)
    (work_dir / "job.json").write_text(
        json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    cmd = [job["venv_python"], str(dst), str(work_dir / "job.json")]
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    try:
        proc = subprocess.Popen(
            ["systemd-run", "--scope", "--collect",
             "--unit", "bot4vps-upd-%s" % ts] + cmd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        # systemd-run --scope держит процесс до завершения ребёнка
        pid = proc.pid
    except (FileNotFoundError, OSError):
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        pid = proc.pid
    return pid


async def start_install() -> dict:
    """Установить найденное обновление из main (без повторной проверки)."""
    state = read_state()
    if state["status"] in _BUSY_STATUSES:
        raise RuntimeError("Обновление уже выполняется")
    available = state.get("available")
    if not available:
        raise RuntimeError("Нет доступного обновления. Сначала выполните проверку")

    work_dir = Path(tempfile.mkdtemp(prefix="bot4vps_update_"))
    job = _build_job("update", available["version"], MAIN_TARBALL_URL, work_dir)
    pid = await asyncio.to_thread(_launch_runner, job)
    write_state(
        status="downloading",
        action={
            "type": "update",
            "target": available["version"],
            "started_at": _now_iso(),
        },
        pid=pid,
        last_error=None,
    )
    return {"ok": True, "status": "downloading", "target": available["version"]}


async def start_rollback(version: str) -> dict:
    """Откат на конкретную версию через её GitHub Release."""
    target = parse_version(version)
    if target < MIN_ROLLBACK_VERSION:
        raise ValueError("Откат доступен только для версий 4.0.0 и новее")
    if normalize_version(target) == normalize_version(parse_version(APP_VERSION)):
        raise ValueError("Версия %s уже установлена" % normalize_version(target))

    state = read_state()
    if state["status"] in _BUSY_STATUSES:
        raise RuntimeError("Откат уже выполняется")

    release = await asyncio.to_thread(resolve_release, version)
    work_dir = Path(tempfile.mkdtemp(prefix="bot4vps_update_"))
    job = _build_job("rollback", normalize_version(target),
                     release["asset_url"], work_dir)
    pid = await asyncio.to_thread(_launch_runner, job)
    write_state(
        status="downloading",
        action={
            "type": "rollback",
            "target": normalize_version(target),
            "started_at": _now_iso(),
        },
        pid=pid,
        last_error=None,
    )
    return {"ok": True, "status": "downloading",
            "target": normalize_version(target)}


# ==================================================================
# Инициализация на старте + реконсиляция
# ==================================================================

async def init_on_startup() -> None:
    """Вызывается из lifespan FastAPI (и при старте TG-процесса).

    1. Засеять локальный changelog текущей версии из поставляемого файла.
    2. Реконсилировать состояние после перезапуска: раннер завершает
       установку сам, но уведомления шлёт процесс через notify_event.
    """
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    if not CHANGELOG_FILE.exists():
        shipped = Path(__file__).with_name("changelog.md")
        section = extract_changelog_section(
            shipped.read_text(encoding="utf-8"), APP_VERSION
        )
        CHANGELOG_FILE.write_text((section or shipped.read_text()) + "\n",
                                  encoding="utf-8")

    state = read_state()
    action = state.get("action")
    if not action or state.get("status") not in _BUSY_STATUSES:
        # Обычный старт: синхронизировать current_version с кодом.
        if state.get("current_version") != APP_VERSION:
            write_state(current_version=APP_VERSION)
        return

    # Старт после обновления/отката: сравнить код с целью операции.
    now = parse_version(APP_VERSION)
    target = parse_version(action["target"])
    prev = parse_version(action.get("previous_version") or state.get(
        "previous_version") or APP_VERSION)

    if now == target:
        _finalize_success(state, action)
    elif now == prev:
        _finalize_failure(state, action)
    else:
        # Неизвестная версия (ручная правка?) — сброс без события.
        write_state(status="failed", action=None, pid=None,
                    last_error="Неожиданная версия после перезапуска: %s"
                               % APP_VERSION)


def _finalize_success(state: dict, action: dict) -> None:
    # changelog_new уже применён раннером в changelog; сбрасываем остатки
    if CHANGELOG_NEW_FILE.exists():
        CHANGELOG_NEW_FILE.unlink()
    write_state(
        status="idle",
        current_version=APP_VERSION,
        previous_version=action.get("previous_version"),
        last_update_at=_now_iso(),
        action=None,
        pid=None,
        last_error=None,
    )
    asyncio.get_event_loop().create_task(_notify_result(action, True))


def _finalize_failure(state: dict, action: dict) -> None:
    write_state(
        status="failed",
        action=None,
        pid=None,
    )
    asyncio.get_event_loop().create_task(_notify_result(action, False))


async def _notify_result(action: dict, ok: bool) -> None:
    from core.event_service import notify_event
    from core.event_types import EventLevel, EventReason, EventType

    is_rollback = action.get("type") == "rollback"
    target = action.get("target")
    if ok:
        reason = (
            EventReason.ROLLBACK_DONE
            if is_rollback
            else EventReason.UPDATE_INSTALLED
        )
        await notify_event(
            EventType.UPDATE,
            EventLevel.INFO,
            "Bot4VPS обновлён до %s" % target,
            ("Откат на версию %s выполнен." if is_rollback
             else "Установлена версия %s.") % target,
            details={
                "version": target,
                "type": action.get("type"),
                "reason": reason.value,
            },
        )
    else:
        reason = (
            EventReason.ROLLBACK_FAILED
            if is_rollback
            else EventReason.UPDATE_FAILED
        )
        await notify_event(
            EventType.UPDATE,
            EventLevel.WARNING,
            "Не удалось %s до %s" % ("откатиться" if is_rollback else "обновиться", target),
            "Предыдущая рабочая версия восстановлена."
            if not is_rollback else "Восстановлена предыдущая версия.",
            details={
                "version": target,
                "type": action.get("type"),
                "reason": reason.value,
            },
        )
