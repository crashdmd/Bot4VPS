"""Standalone-установщик Bot4VPS — запускается ВНЕ процесса приложения.

Жёсткие ограничения (не нарушать):
- ТОЛЬКО stdlib, ноль импортов core/ui — скрипт выполняется копией из
  временного каталога и должен работать под любым venv 4.0.0+;
- запускается через systemd-run --scope (свой cgroup), иначе KillMode=mixed
  юнита убьёт его SIGKILL-ом через 3с после systemctl restart;
- пользовательские данные (config.json, servers.json, data/, scripts/,
  keys/, logs/, backup/, venv/) не трогаются — заменяется только код из
  CODE_PATHS.

Цикл: download → extract → backup → swap → pip → restart → health-check;
при ошибке на любом шаге после backup — авторестарт предыдущей версии.

Запуск: <python> runner.py <job.json>
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path

USER_AGENT = "Bot4VPS-Updater"

# Что заменяется при обновлении (и что бэкапится). Всё остальное — данные.
CODE_PATHS = [
    "bot.py", "state.py", "core", "ui", "services", "deploy",
    "requirements.txt", "install.sh",
]

MIN_FREE_MB = 200          # свободное место перед установкой
BACKUP_KEEP = 3            # сколько update_backup_* хранить
HEALTH_INTERVAL = 3        # период опроса health
POLL_STATE_INTERVAL = 0.5  # период записи heartbeat в state.json

BUSY = ("downloading", "installing", "rolling_back")


# ==================================================================
# state.json (раннер — владелец файла на время установки)
# ==================================================================

def _read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(path: Path, **patches) -> dict:
    state = _read_state(path)
    state.update(patches)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return state


# ==================================================================
# Шаги
# ==================================================================

def _download(url: str, dest: Path) -> None:
    """Скачивание в .part с докачкой-невозможностью: пишем заново."""
    part = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp, open(part, "wb") as f:
        shutil.copyfileobj(resp, f, length=1024 * 256)
        f.flush()
        os.fsync(f.fileno())
    os.replace(part, dest)


def _safe_member(name: str) -> bool:
    """tar-slip guard: только относительные пути без .."""
    pure = Path(name)
    if pure.is_absolute() or ".." in pure.parts:
        return False
    return True


def _extract_tar(tar_path: Path, dest_dir: Path) -> Path:
    """Распаковать tar.gz, снять верхний каталог (Bot4VPS-main/ и т.п.).

    Возвращает путь к содержимому проекта (dest_dir/new).
    """
    new_dir = dest_dir / "new"
    new_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as tar:
        members = tar.getmembers()
        # Верхний каталог архива GitHub (может отсутствовать в кастомных ассетах)
        tops = {m.name.split("/")[0] for m in members if m.name}
        strip = 1 if len(tops) == 1 and not tops.pop().startswith(".") else 0
        for m in members:
            if not _safe_member(m.name):
                raise RuntimeError("Архив содержит недопустимый путь: %s" % m.name)
            if strip:
                if "/" not in m.name:
                    continue  # сам верхний каталог
                m.name = m.name.split("/", 1)[1]
                if not m.name:
                    continue
            if m.isdir():
                (new_dir / m.name).mkdir(parents=True, exist_ok=True)
            elif m.isfile():
                target = new_dir / m.name
                target.parent.mkdir(parents=True, exist_ok=True)
                extracted = tar.extractfile(m)
                if extracted is None:
                    continue
                with open(target, "wb") as f:
                    shutil.copyfileobj(extracted, f)
                if m.mode & 0o111:  # сохранить exec-биты (git archive хранит)
                    os.chmod(target, m.mode)
            # symlinks в архивах исходников GitHub не бывает; пропускаем
    if not any(new_dir.iterdir()):
        raise RuntimeError("Архив пуст")
    return new_dir


def _backup_code(app_dir: Path, backup_dir: Path) -> None:
    """Резервная копия кода (только CODE_PATHS, без __pycache__)."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    for name in CODE_PATHS:
        src = app_dir / name
        if not src.exists():
            continue
        if src.is_dir():
            shutil.copytree(src, backup_dir / name,
                            ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(src, backup_dir / name)


def _swap_code(app_dir: Path, new_dir: Path) -> None:
    """Заменить CODE_PATHS на новые; данные не трогаем."""
    for name in CODE_PATHS:
        dst = app_dir / name
        if dst.is_dir():
            shutil.rmtree(dst)
        elif dst.exists():
            dst.unlink()
        src = new_dir / name
        if src.exists():
            shutil.move(str(src), str(dst))
    # Почистить __pycache__ в новом дереве (переехал из архива)
    for pycache in app_dir.rglob("__pycache__"):
        if any(pycache.match(c) for c in CODE_PATHS):
            continue
        shutil.rmtree(pycache, ignore_errors=True)


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _pip_install_if_changed(job: dict, old_req: Path) -> None:
    """pip install только если requirements.txt изменился."""
    new_req = Path(job["app_dir"]) / "requirements.txt"
    if not new_req.exists():
        return
    if old_req.exists() and _file_hash(old_req) == _file_hash(new_req):
        return
    result = subprocess.run(
        [job["venv_python"], "-m", "pip", "install", "--no-input", "-q",
         "-r", "requirements.txt"],
        cwd=job["app_dir"], capture_output=True, text=True, timeout=900,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "pip install не удался: %s" % (result.stderr or "").strip()[:400]
        )


def _systemctl(job: dict, *args: str, timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", *args], capture_output=True, text=True, timeout=timeout
    )


def _restart_service(job: dict) -> None:
    if job.get("dev_no_systemd"):
        print("[runner] dev_no_systemd: пропуск systemctl restart", flush=True)
        return
    r = _systemctl(job, "restart", job["service_name"])
    if r.returncode != 0:
        raise RuntimeError(
            "systemctl restart не удался: %s" % (r.stderr or "").strip()[:300]
        )


def _health(job: dict, expected_version: str) -> tuple[bool, str]:
    """GET /api/upd/health с 127.0.0.1 до совпадения версии (2 подряд)."""
    if job.get("dev_no_systemd"):
        print("[runner] dev_no_systemd: пропуск health-check", flush=True)
        return True, "dev"
    url = "http://127.0.0.1:%d/api/upd/health" % job["health_port"]
    deadline = time.monotonic() + job.get("health_timeout", 120)
    streak = 0
    last = ""
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("version") == expected_version:
                streak += 1
                if streak >= 2:
                    return True, "ok"
            else:
                streak = 0
                last = "версия %s != %s" % (data.get("version"), expected_version)
        except Exception as e:
            streak = 0
            last = str(e)
        time.sleep(HEALTH_INTERVAL)
    return False, last or "таймаут"


def _extract_changelog_to(app_dir: Path, version: str, out_path: Path) -> None:
    """Секция «## <version>» из НОВОГО core/update/changelog.md → out_path."""
    import re
    src = app_dir / "core" / "update" / "changelog.md"
    md = src.read_text(encoding="utf-8")
    pat = re.compile(r"(?m)^## (\d+(?:\.\d+){0,2})\s*$")
    matches = list(pat.finditer(md))
    want = _parse_version(version)
    for i, m in enumerate(matches):
        if _parse_version(m.group(1)) == want:
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(md[start:end].strip() + "\n", encoding="utf-8")
            return
    # Секции нет — пишем заглушку, файл обязан существовать
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("Changelog версии %s недоступен.\n" % version,
                        encoding="utf-8")


def _parse_version(value: str) -> tuple[int, int, int]:
    import re
    s = str(value or "").strip()
    m = re.match(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$", s, re.IGNORECASE)
    if not m:
        raise ValueError("Неверный формат версии: %r" % value)
    parts = [int(g) if g else 0 for g in m.groups()]
    return (parts[0], parts[1], parts[2])


def _normalize(t: tuple[int, int, int]) -> str:
    return "%d.%d.%d" % t


def _restore(job: dict, backup_dir: Path, state_path: Path) -> None:
    """Восстановить код из бэкапа и перезапустить. Best-effort."""
    app_dir = Path(job["app_dir"])
    try:
        for name in CODE_PATHS:
            dst = app_dir / name
            src = backup_dir / name
            if src.exists():
                if dst.is_dir():
                    shutil.rmtree(dst)
                elif dst.exists():
                    dst.unlink()
                if src.is_dir():
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
            elif dst.exists():
                # Пути не было в старой версии — убрать новый
                if dst.is_dir():
                    shutil.rmtree(dst)
                else:
                    dst.unlink()
        _write_state(state_path, status="rolling_back")
        try:
            _restart_service(job)
            ok, info = _health(job, job["previous_version"])
            if not ok:
                print("[runner] restore: сервис не поднялся (%s)" % info, flush=True)
        except Exception as e:
            print("[runner] restore restart failed: %s" % e, flush=True)
    except Exception as e:
        print("[runner] RESTORE FAILED: %s" % e, flush=True)


def _cleanup(work_dir: Path, app_dir: Path) -> None:
    shutil.rmtree(work_dir, ignore_errors=True)
    backups = sorted(app_dir.glob("backup/update_backup_*"))
    while len(backups) > BACKUP_KEEP:
        shutil.rmtree(backups.pop(0), ignore_errors=True)


# ==================================================================
# main
# ==================================================================

def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: runner.py <job.json>", file=sys.stderr)
        return 2
    job = json.loads(Path(argv[1]).read_text(encoding="utf-8"))

    app_dir = Path(job["app_dir"])
    state_path = Path(job["state_file"])
    work_dir = Path(job["work_dir"])
    action = job["action"]           # "update" | "rollback"
    target = job["target_version"]
    previous = job["previous_version"]

    busy_status = "rolling_back" if action == "rollback" else "installing"

    try:
        # --- 1. downloading ------------------------------------------
        _write_state(state_path, status="downloading")

        usage = shutil.disk_usage(app_dir)
        if usage.free < MIN_FREE_MB * 1024 * 1024:
            raise RuntimeError(
                "Недостаточно свободного места: %d МБ (нужно %d)"
                % (usage.free // 1024 // 1024, MIN_FREE_MB)
            )

        tar_path = work_dir / "src.tar.gz"
        _download(job["download_url"], tar_path)
        new_dir = _extract_tar(tar_path, work_dir)

        # --- 2. installing -------------------------------------------
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = app_dir / "backup" / ("update_backup_%s" % ts)
        _write_state(state_path, status=busy_status,
                     action={"type": action, "target": target,
                             "started_at": ts, "backup_dir": str(backup_dir),
                             "previous_version": previous})
        old_req = app_dir / "requirements.txt"
        old_req_hash = _file_hash(old_req) if old_req.exists() else ""
        _backup_code(app_dir, backup_dir)
        _swap_code(app_dir, new_dir)

        # requirements из НОВОГО кода мог исчезнуть из старого хеша —
        # сравнение внутри _pip_install_if_changed идёт по файлам
        _pip_install_if_changed(job, backup_dir / "requirements.txt")

        # --- 3. restart + health -------------------------------------
        _restart_service(job)
        ok, info = _health(job, target)

        if ok:
            # Успех: changelog_new → changelog, состояние, очистка
            _extract_changelog_to(
                app_dir, target,
                app_dir / "data" / "update" / "changelog.md"
            )
            changelog_new = app_dir / "data" / "update" / "changelog_new.md"
            if changelog_new.exists():
                changelog_new.unlink()
            _write_state(
                state_path,
                status="idle",
                current_version=target,
                previous_version=previous,
                last_update_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                action=None,
                pid=None,
                last_error=None,
            )
            _cleanup(work_dir, app_dir)
            print("[runner] OK: %s -> %s" % (previous, target), flush=True)
            return 0

        # --- 4. провал → restore -------------------------------------
        _write_state(state_path, last_error="Сервис не поднялся: %s" % info)
        _restore(job, backup_dir, state_path)
        _write_state(state_path, status="failed", action=None, pid=None)
        # Бэкап не удаляем — для разбора полётов
        _cleanup(work_dir, app_dir)
        print("[runner] FAILED: %s" % info, file=sys.stderr, flush=True)
        return 1

    except Exception as e:
        err = str(e)
        print("[runner] ERROR: %s" % err, file=sys.stderr, flush=True)
        # Если backup уже был сделан — восстановиться; иначе просто failed
        st = _read_state(state_path)
        backup_dir = (st.get("action") or {}).get("backup_dir")
        if backup_dir and Path(backup_dir).exists():
            _restore(job, Path(backup_dir), state_path)
        _write_state(state_path, status="failed", last_error=err,
                     action=None, pid=None)
        _cleanup(work_dir, app_dir)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
