"""Ядро встроенного updater'а Bot4VPS (логика внутри процесса).

Ответственности:
- проверка новой версии по подписанному описанию GitHub Release;
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
from core.update import release_verify

# --- GitHub (публичный репозиторий) -------------------------------
REPO_URL = "https://github.com/crashdmd/Bot4VPS"
CHANGELOG_URL = "https://raw.githubusercontent.com/crashdmd/Bot4VPS/main/core/update/changelog.md"
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
        # Незакрытая пара аудита обновления (§16.3): снимок актора, кода
        # действия и цели, снятые до перезапуска. Живёт отдельным ключом, а
        # не внутри ``action``, потому что ``action`` переписывает раннер
        # целиком — а раннер про аудит знать не должен.
        "audit_op": None,
        "last_error": None,
        "pid": None,
    }


# ==================================================================
# Аудит обновления (пара started → ok/failed, §16.3)
# ==================================================================

def _already_finalized(op_id: str) -> bool:
    """Есть ли у операции уже финальная пометка аудита.

    Нужна из-за двух входов в закрытие пары: состояние операции читают и
    lifespan uvicorn, и старт чистого ТГ-процесса. Оба могут увидеть один и
    тот же ``audit_op`` — второй пометки у операции быть не должно.
    """
    from core import audit

    return audit.has_final(op_id)


def _audit_update_started(action_code, target: str) -> None:
    """Пометка «начал обновление» и снимок для финала в новом процессе.

    Актор берётся из контекста: кнопку нажал человек в Web, и это последний
    момент, когда он ещё «рядом» — обновление перезапустит панель, и финал
    запишет уже другой процесс (§6).
    """
    from core import audit
    from core.audit_actions import AuditResult

    op_id = audit.new_op_id()
    audit.record(
        action_code,
        result=AuditResult.STARTED,
        op_id=op_id,
        params={"version": target, "type": getattr(action_code, "value", action_code)},
    )
    write_state(audit_op={
        "op_id": op_id,
        "action": getattr(action_code, "value", action_code),
        "target": target,
        "actor": audit.snapshot(),
        "started_at": _now_iso(),
    })


def _audit_update_finished(
    state: dict,
    action: dict | None,
    *,
    ok: bool,
    error: str | None = None,
) -> None:
    """Финальная пометка обновления и снятие блока ``audit_op``.

    Актор — из снимка, снятого при запуске: в этом процессе человека уже
    нет (он тот же лишь формально — после перезапуска контекст пуст).
    """
    from core import audit
    from core.audit_actions import AuditAction, AuditResult

    block = state.get("audit_op") or {}
    op_id = block.get("op_id")
    action_code = block.get("action") or (
        AuditAction.UPDATE_ROLLBACK.value
        if (action or {}).get("type") == "rollback"
        else AuditAction.UPDATE_INSTALL.value
    )
    if op_id and not _already_finalized(op_id):
        audit.record(
            action_code,
            result=AuditResult.OK if ok else AuditResult.FAILED,
            op_id=op_id,
            error=error,
            params={
                "version": (action or {}).get("target") or block.get("target"),
                "type": action_code.rsplit(".", 1)[-1],
            },
            actor=audit.from_snapshot(block.get("actor")),
        )
    write_state(audit_op=None)


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
        data = resp.read(4 * 1024 * 1024 + 1)
        if len(data) > 4 * 1024 * 1024:
            raise ValueError("Ответ GitHub слишком большой")
        return data


def fetch_changelog() -> str:
    """Актуальный changelog.md из ветки main."""
    return _http_get(CHANGELOG_URL).decode("utf-8", errors="replace")


def current_version_changelog() -> str:
    """Описание УСТАНОВЛЕННОЙ версии — секция из поставляемого changelog.md.

    Локальный data/update/changelog.md — кэш: он сеется при старте и
    обновляется раннером, но при ручном деплое кода (без updater'а)
    остаётся от предыдущей версии — показывалась, например, 4.5 на
    установленной 5.0. Поэтому источником всегда служит файл из
    поставки кода, а локальный по пути самоисцеляется.
    """
    shipped_path = Path(__file__).with_name("changelog.md")
    shipped = shipped_path.read_text(encoding="utf-8")
    section = extract_changelog_section(shipped, APP_VERSION)
    if not section:
        # версии нет в поставляемом файле (нетипичный тег/срез кода) —
        # показываем последний доступный локальный вариант
        if CHANGELOG_FILE.exists():
            return CHANGELOG_FILE.read_text(encoding="utf-8").strip()
        return shipped.strip()
    try:
        UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        CHANGELOG_FILE.write_text(section + "\n", encoding="utf-8")
    except OSError:
        pass  # кэш не обязан писаться: источник — файл поставки
    return section


# ==================================================================
# Проверка обновлений
# ==================================================================

def _stale_available(state: dict) -> bool:
    """available, не превосходящий установленную версию — показывать
    «Доступна X» на установленной X бессмысленно. Оставался до фикса
    _finalize_success; также покрывает ручную подмену кода без updater."""
    available = state.get("available")
    if not available:
        return False
    try:
        return parse_version(str(available.get("version") or "")) <= parse_version(
            APP_VERSION
        )
    except ValueError:
        return True


async def check_for_update(*, notify: bool) -> dict:
    """Предлагать только подписанный релиз новее установленной версии.

    Никогда не бросает исключение: ошибки сети уходят в
    state.last_check_error. Возвращает срез состояния для UI.
    """
    state = read_state()
    if state["status"] in _BUSY_STATUSES:
        return {"status": state["status"], "update_available": False,
                "busy": True}

    # Guard и клейминг checking — синхронный код без await: на одном event
    # loop два вызова не могут interleaving'ом оба пройти guard.
    write_state(status="checking")
    try:
        release = await asyncio.to_thread(_latest_signed_update)
        if release is not None:
            top = release["version"]
            section = release["payload"]["changelog"]
            UPDATE_DIR.mkdir(parents=True, exist_ok=True)
            CHANGELOG_NEW_FILE.write_text(section + "\n", encoding="utf-8")
            write_state(
                available={"version": top, "found_at": _now_iso(), "release": release},
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
    except asyncio.CancelledError:
        # CancelledError — потомок BaseException: обычный except Exception
        # его не ловит, и без этой ветки status навсегда застревал в checking.
        if read_state().get("status") == "checking":
            _reset_check_state("Проверка обновления отменена")
        raise
    except Exception as e:  # сеть/парсинг — не роняем вызывающего
        message = _friendly_check_error(e)
        if read_state().get("status") == "checking":
            _reset_check_state(message)
        else:
            # Результат уже записан (сбой был в уведомлении) — не затираем его
            write_state(last_check=_now_iso(), last_check_error=message)
        return {"status": "idle", "update_available": False, "error": message}


def _reset_check_state(message: str) -> None:
    """Согласованно завершить неуспешную проверку: выйти из checking и
    сбросить артефакты ранее найденного обновления (available/changelog_new),
    чтобы UI не показывал обновление, которого актуальная проверка не нашла."""
    if CHANGELOG_NEW_FILE.exists():
        CHANGELOG_NEW_FILE.unlink()
    write_state(
        available=None,
        last_check=_now_iso(),
        last_check_error=message,
        status="idle",
    )


def _friendly_check_error(e: Exception) -> str:
    """Человекочитаемое сообщение об ошибке проверки вместо сырого HTTP."""
    import urllib.error

    if isinstance(e, urllib.error.HTTPError):
        if e.code == 404:
            return (
                "Подписанное описание релиза не найдено в GitHub. "
                "Установка неподписанного обновления запрещена"
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


def get_rollback_version_section(version: str) -> str:
    """Секция «## <version>» из поставляемого changelog.md — описание версии.

    Источник тот же, что и у списка версий отката, — локальный файл репо:
    список и описания не могут разъехаться.
    """
    want = parse_version(version)
    shipped = Path(__file__).with_name("changelog.md").read_text(
        encoding="utf-8"
    )
    section = extract_changelog_section(shipped, normalize_version(want))
    if not section:
        raise ValueError(
            "Описание версии %s не найдено" % normalize_version(want)
        )
    return section


def _published_release_tags() -> list[str]:
    data = json.loads(_http_get(RELEASES_API).decode("utf-8"))
    tags = []
    for rel in data if isinstance(data, list) else []:
        if not isinstance(rel, dict) or rel.get("draft") or rel.get("prerelease"):
            continue
        tag = str(rel.get("tag_name") or "")
        try:
            parse_version(tag)
        except ValueError:
            continue
        tags.append(tag)
    return sorted(set(tags), key=parse_version, reverse=True)


def _signed_release(tag: str) -> dict:
    envelope = release_verify.decode_envelope(_http_get(release_verify.manifest_url(tag)))
    payload = release_verify.verify_envelope(envelope, tag)
    if payload["tag"] != tag:
        raise release_verify.ReleaseTrustError("Подпись относится к другому тегу релиза")
    return {"version": payload["version"], "asset_url": release_verify.archive_url(payload),
            "payload": payload, "envelope": envelope}


def _latest_signed_update() -> dict | None:
    tags = _published_release_tags()
    newest = next((tag for tag in tags if parse_version(tag) > parse_version(APP_VERSION)), None)
    return _signed_release(newest) if newest is not None else None


def resolve_release(version: str) -> dict:
    """Pre-7.0 rollback uses the fixed HTTPS repository; newer releases require signatures."""
    want = parse_version(version)
    if want < (7, 0, 0):
        from .legacy_release import resolve
        return resolve('rollback', version)
    for tag in _published_release_tags():
        if parse_version(tag) == want:
            return _signed_release(tag)
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


def _health_scheme() -> str:
    """Схема из установленного юнита (--ssl-certfile => https).

    Обновление не трогает юнит — схема после рестарта та же, что сейчас.
    """
    unit = Path("/etc/systemd/system/bot4vps.service")
    try:
        text = unit.read_text(encoding="utf-8")
        if re.search(r"--ssl-certfile\s+\S+", text):
            return "https"
    except OSError:
        pass
    return "http"


def _health_mode() -> str:
    """Telegram-only не имеет HTTP health endpoint."""
    try:
        unit = Path("/etc/systemd/system/bot4vps.service").read_text(encoding="utf-8")
        if re.search(r"^ExecStart=.*\bbot\.py(?:\s|$)", unit, re.MULTILINE):
            return "service"
    except OSError:
        pass
    return "web"


def _build_job(action: str, target: str, release: dict, work_dir: Path) -> dict:
    envelope = release.get("envelope")
    legacy = action == 'rollback' and MIN_ROLLBACK_VERSION <= parse_version(target) < (7, 0, 0)
    if legacy:
        from .legacy_release import resolve
        # Re-resolve instead of trusting URLs/commits supplied by an interface.
        old = resolve(action, target)
        download_url = old['archive_url']
    elif not isinstance(envelope, dict):
        raise RuntimeError("У обновления нет подписи. Выполните проверку обновлений заново")
    else:
        payload = release_verify.verify_envelope(envelope, target)
        download_url = release_verify.archive_url(payload)
    return {
        "action": action,  # "update" | "rollback"
        "target_version": target,
        "previous_version": APP_VERSION,
        "app_dir": str(_app_dir()),
        "venv_python": sys.executable,
        "service_name": _service_name(),
        "download_url": download_url,
        "release_envelope": envelope,
        "legacy_rollback": legacy,
        "state_file": str(_app_dir() / STATE_FILE),
        "work_dir": str(work_dir),
        "health_port": _health_port(),
        "health_scheme": _health_scheme(),
        "health_mode": _health_mode(),
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
    from core.local_privileges import separated, request
    if separated():
        return request("update.install", action=job["action"], target=job["target_version"],
                       envelope=job["release_envelope"])["pid"]
    work_dir = Path(job["work_dir"])
    work_dir.mkdir(parents=True, exist_ok=True)
    src = Path(__file__).with_name("runner.py")
    dst = work_dir / "runner.py"
    shutil.copyfile(src, dst)
    # Это проверяющий код из ТЕКУЩЕЙ установки, до загрузки нового архива.
    shutil.copyfile(Path(__file__).with_name("release_verify.py"), work_dir / "release_verify.py")
    shutil.copyfile(Path(__file__).with_name("legacy_release.py"), work_dir / "legacy_release.py")
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
    """Установить выбранный подписанный архив; main и URL из кэша не доверяем."""
    state = read_state()
    if state["status"] in _BUSY_STATUSES:
        raise RuntimeError("Обновление уже выполняется")
    available = state.get("available")
    if not available:
        raise RuntimeError("Нет доступного обновления. Сначала выполните проверку")

    target = available["version"]
    if parse_version(target) <= parse_version(APP_VERSION):
        raise RuntimeError("Выбранное обновление не новее установленной версии")
    return await _start_verified_install("update", target, available.get("release") or {})


async def _start_verified_install(action: str, target: str, release: dict) -> dict:
    from core.audit_actions import AuditAction
    work_dir = Path(tempfile.mkdtemp(prefix="bot4vps_update_"))
    launch_task = None
    try:
        job = _build_job(action, target, release, work_dir)
        _audit_update_started(AuditAction.UPDATE_ROLLBACK if action == "rollback" else AuditAction.UPDATE_INSTALL, target)
        write_state(status="downloading", action={"type": action, "target": target, "started_at": _now_iso()}, pid=None, last_error=None)
        launch_task = asyncio.create_task(asyncio.to_thread(_launch_runner, job))
        pid = await asyncio.shield(launch_task)
        # Раннер мог уже завершиться. Не возвращаем его финальное состояние
        # в downloading, как это было при записи статуса после запуска.
        if read_state()["status"] in _BUSY_STATUSES:
            write_state(pid=pid)
        return {"ok": True, "status": read_state()["status"], "target": target}
    except asyncio.CancelledError:
        # Отмена HTTP-запроса не отменяет уже запущенную установку и не
        # удаляет файлы, которые ещё использует поток запуска раннера.
        async def finish_launch():
            try:
                pid = await launch_task
                if read_state()["status"] in _BUSY_STATUSES:
                    write_state(pid=pid)
            except Exception:
                state = read_state()
                shutil.rmtree(work_dir, ignore_errors=True)
                write_state(status="failed", last_error="Не удалось запустить проверенное обновление", action=None, pid=None)
                _audit_update_finished(state, state.get("action"), ok=False, error="Не удалось запустить проверенное обновление")
        if launch_task is not None:
            asyncio.create_task(finish_launch())
        raise
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        if read_state()["status"] in _BUSY_STATUSES:
            state = read_state()
            write_state(status="failed", last_error="Не удалось запустить проверенное обновление", action=None, pid=None)
            _audit_update_finished(state, state.get("action"), ok=False, error="Не удалось запустить проверенное обновление")
        raise


async def start_rollback(version: str) -> dict:
    """Откат на конкретную версию через её GitHub Release."""
    target = parse_version(version)
    if target < MIN_ROLLBACK_VERSION:
        # Граница — не произвольная: Web UI появился в 3.0, откат из панели
        # на более старые версии невозможен в принципе.
        raise ValueError("Откат доступен только для версий 3.0.0 и новее")
    if normalize_version(target) == normalize_version(parse_version(APP_VERSION)):
        raise ValueError("Версия %s уже установлена" % normalize_version(target))

    state = read_state()
    if state["status"] in _BUSY_STATUSES:
        raise RuntimeError("Откат уже выполняется")

    write_state(status="checking")
    try:
        release = await asyncio.to_thread(resolve_release, version)
        return await _start_verified_install("rollback", normalize_version(target), release)
    except BaseException:
        if read_state()["status"] == "checking":
            write_state(status="idle", last_check_error="Не удалось проверить подпись версии для отката")
        raise


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
    state = read_state()
    # Локальный changelog сеем не только при отсутствии: после смены
    # версии (в том числе ручного деплоя кода) он обязан отражать
    # установленную версию, а не оставаться от прежней.
    if not CHANGELOG_FILE.exists() or state.get("current_version") != APP_VERSION:
        try:
            current_version_changelog()
        except OSError:
            pass
    if state.get("status") == "checking":
        # Проверка шла внутри процесса и не пережила перезапуск (раннер в ней
        # не участвует, action отсутствует) — без сброса status остался бы
        # checking навсегда и блокировал бы все последующие проверки.
        write_state(status="idle",
                    last_check_error="Проверка обновления прервана перезапуском")
        state = read_state()
    action = state.get("action")
    if not action or state.get("status") not in _BUSY_STATUSES:
        # Обновление могло закончиться раньше этого запуска: раннер дописал
        # в state.json финал сам (status idle/failed, action=None). Пара
        # аудита при этом обязана закрыться — иначе «начал обновление»
        # осталось бы висеть без исхода.
        _finalize_audit(state, action)
        # Обычный старт: синхронизировать current_version с кодом.
        if state.get("current_version") != APP_VERSION:
            write_state(current_version=APP_VERSION)
        # Лечение зависшего available (не новее установленной — мог
        # остаться до фикса _finalize_success): баннер «Доступна X» на
        # установленной X не должен переживать рестарт.
        if _stale_available(state):
            if CHANGELOG_NEW_FILE.exists():
                CHANGELOG_NEW_FILE.unlink()
            write_state(available=None)
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
        _audit_update_finished(
            state,
            action,
            ok=False,
            error="Неожиданная версия после перезапуска: %s" % APP_VERSION,
        )
        write_state(status="failed", action=None, pid=None,
                    last_error="Неожиданная версия после перезапуска: %s"
                               % APP_VERSION)


def _finalize_audit(state: dict, action: dict | None) -> None:
    """Закрыть пару аудита по уже записанному исходу операции.

    Исход берётся из достигнутой версии — то же правило, что у ветки
    «старт после обновления»: код совпал с целью операции — успех, остался
    прежним (или отличается) — провал. Кто именно увидел результат первым,
    неважно: вторую пометку отсекает ``_already_finalized``.
    """
    if not (state.get("audit_op") or {}).get("op_id"):
        return
    try:
        target = parse_version((state.get("audit_op") or {}).get("target") or "")
    except (TypeError, ValueError):
        write_state(audit_op=None)
        return

    _audit_update_finished(
        state,
        action,
        ok=parse_version(APP_VERSION) == target,
        error=state.get("last_error"),
    )


def _finalize_success(state: dict, action: dict) -> None:
    # changelog_new уже применён раннером в changelog; сбрасываем остатки
    if CHANGELOG_NEW_FILE.exists():
        CHANGELOG_NEW_FILE.unlink()
    _audit_update_finished(state, action, ok=True)
    write_state(
        status="idle",
        current_version=APP_VERSION,
        previous_version=action.get("previous_version"),
        last_update_at=_now_iso(),
        # available обязан сбрасываться вместе с changelog_new: иначе UI
        # показывает «Доступна X» уже на установленной X, а клик по кнопке
        # падает 404 «Нет доступного обновления» (changelog_new удалён).
        available=None,
        action=None,
        pid=None,
        last_error=None,
    )
    asyncio.get_event_loop().create_task(_notify_result(action, True))


def _finalize_failure(state: dict, action: dict) -> None:
    _audit_update_finished(state, action, ok=False, error=state.get("last_error"))
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
