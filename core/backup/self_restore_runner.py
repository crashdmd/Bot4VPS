"""Standalone-исполнитель локального self-restore Bot4VPS — ВНЕ процесса.

Жёсткие ограничения (не нарушать — образец core/update/runner.py):
- ТОЛЬКО stdlib, ноль импортов core/ui: скрипт выполняется копией из
  временного каталога и обязан работать на любом venv, включая
  восстанавливаемый код более старой версии;
- запускается через systemd-run --scope (свой cgroup), иначе KillMode=mixed
  юнита убьёт его SIGKILL-ом через 3с после systemctl stop;
- глупый исполнитель: НЕ классифицирует tar-диагностики, НЕ пишет
  Operation-записи, НЕ решает семантику успеха — только команды и факты.
  Вся умность — в core/backup/self_restore.py (финализация).

Цикл: stop → tar extract → daemon-reload → (pip при изменении
requirements.txt) → start → health-check → state.json (терминальный статус
+ сырой tar exit/stderr + результат health). Ошибка на любом шаге после
stop — best-effort старт сервиса и статус failed: оставить машину без
сервиса хуже, чем поднять его на частично применённых файлах.

Запуск: <python> self_restore_runner.py <job.json>
"""
from __future__ import annotations

import hashlib
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HEALTH_INTERVAL = 3        # период опроса health
HEALTH_STREAK = 2          # сколько успешных проб подряд считается успехом
TAR_TIMEOUT = 1800         # лимит распаковки, секунд
PIP_TIMEOUT = 900          # лимит pip install, секунд


# ==================================================================
# state.json (раннер — владелец файла на время восстановления)
# ==================================================================

def _read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(path: Path, **patches) -> dict:
    state = _read_state(path)
    state.update(patches)
    state["updated_at"] = datetime.now().isoformat()
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return state


def _systemctl(job: dict, *args: str, timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", *args], capture_output=True, text=True, timeout=timeout
    )


# ==================================================================
# Шаги
# ==================================================================

def _wait_gate(job: dict, state_path: Path) -> bool:
    """Стоять до появления go-файла: ядро атомарно ставит мутационную границу
    (проверка отмены) и только потом отпускает раннер. Отсутствие go-файла в
    течение gate_timeout — отмена или гибель ядра: сервис не трогаем."""
    deadline = time.monotonic() + int(job.get("gate_timeout") or 60)
    go = Path(job["go_file"])
    while time.monotonic() < deadline:
        if go.exists():
            return True
        time.sleep(0.2)
    return False


def _stop_service(job: dict, state_path: Path) -> bool:
    if job.get("dev_no_systemd"):
        print("[self-restore] dev_no_systemd: пропуск systemctl stop", flush=True)
        _write_state(state_path, stop={"ok": True, "error": None})
        return True
    r = _systemctl(job, "stop", job["service_name"])
    ok = r.returncode == 0
    _write_state(
        state_path,
        stop={"ok": ok, "error": None if ok else (r.stderr or "").strip()[:300]},
    )
    return ok


def _extract(job: dict, state_path: Path) -> bool:
    """Распаковка ровно по trusted member list (флаги = core/backup)."""
    strip: list[str] = []
    if job["layout"] == "manifest_payload":
        root = "/"
        strip = ["--strip-components=1"]
    else:
        root = job["target_root"]
        Path(root).mkdir(parents=True, exist_ok=True)
    for directory in job.get("parent_directories") or ():
        Path(directory).mkdir(parents=True, exist_ok=True)
    command = [
        "tar", "-xz", "-p", "--overwrite", "--numeric-owner",
        *strip,
        "-C", str(root),
        "--null", "--verbatim-files-from", "--no-recursion",
        "--files-from=%s" % job["member_list"],
        "-f", job["archive"],
    ]
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    try:
        r = subprocess.run(
            command, capture_output=True, text=True, env=env, timeout=TAR_TIMEOUT
        )
        _write_state(
            state_path,
            extract={"exit_code": int(r.returncode), "stderr": (r.stderr or "")[:4000]},
        )
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        _write_state(
            state_path,
            extract={"exit_code": -1, "stderr": "timeout после %d с" % TAR_TIMEOUT},
        )
        return False
    except OSError as e:
        _write_state(state_path, extract={"exit_code": -1, "stderr": str(e)[:300]})
        return False


def _daemon_reload(job: dict, state_path: Path) -> bool:
    if job.get("dev_no_systemd"):
        _write_state(state_path, daemon_reload={"ok": True, "error": None})
        return True
    r = _systemctl(job, "daemon-reload")
    ok = r.returncode == 0
    _write_state(
        state_path,
        daemon_reload={"ok": ok, "error": None if ok else (r.stderr or "").strip()[:300]},
    )
    return ok


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _pip_if_changed(job: dict, state_path: Path) -> bool:
    """pip install только если восстановленный requirements.txt изменился.

    venv не пересобирается (его нет в архиве); удаление пакетов при
    понижении версии не делается — это предупреждение prepare, не действие.
    """
    new_req = Path(job["app_dir"]) / "requirements.txt"
    if not new_req.exists():
        _write_state(state_path, pip={"ran": False, "ok": True, "error": None})
        return True
    try:
        changed = _file_hash(new_req) != job.get("requirements_current_sha256")
    except OSError as e:
        _write_state(state_path, pip={"ran": False, "ok": False, "error": str(e)[:300]})
        return False
    if not changed:
        _write_state(state_path, pip={"ran": False, "ok": True, "error": None})
        return True
    try:
        r = subprocess.run(
            [job["venv_python"], "-m", "pip", "install", "--no-input", "-q",
             "-r", "requirements.txt"],
            cwd=job["app_dir"], capture_output=True, text=True, timeout=PIP_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        _write_state(
            state_path,
            pip={"ran": True, "ok": False, "error": "timeout после %d с" % PIP_TIMEOUT},
        )
        return False
    ok = r.returncode == 0
    _write_state(
        state_path,
        pip={
            "ran": True,
            "ok": ok,
            "error": None if ok else (r.stderr or "").strip()[:400],
        },
    )
    return ok


def _start_service(job: dict, state_path: Path) -> bool:
    if job.get("dev_no_systemd"):
        _write_state(state_path, start={"ok": True, "error": None})
        return True
    r = _systemctl(job, "start", job["service_name"])
    ok = r.returncode == 0
    _write_state(
        state_path,
        start={"ok": ok, "error": None if ok else (r.stderr or "").strip()[:300]},
    )
    return ok


def _restored_unit_health(job: dict) -> tuple[str, int]:
    """Режим и порт health из ВОССТАНОВЛЕННОГО юнита.

    Архив побеждает: юнит мог приехать tg-only, с другим портом или с TLS.
    uvicorn в ExecStart → HTTP(S) health на порту из --port (схема — по
    наличию --ssl-certfile: self-signed проверять нечем, unverified);
    иначе — только is-active (новой Telegram-механики раннер не изобретает;
    свежесть state-файла TG проверяет core-финализация).
    """
    try:
        text = Path(job["unit_path"]).read_text(encoding="utf-8")
    except OSError:
        return "http", int(job.get("health_port") or 8080)
    if "uvicorn" not in text:
        return "is_active", 0
    import re
    m = re.search(r"--port\s+(\d+)", text)
    port = int(m.group(1)) if m else int(job.get("health_port") or 8080)
    if re.search(r"--ssl-certfile\s+\S+", text):
        return "https", port
    return "http", port


def _health(job: dict, state_path: Path) -> bool:
    if job.get("dev_no_systemd"):
        _write_state(state_path, health={"mode": "dev", "ok": True, "detail": None})
        return True
    mode, port = _restored_unit_health(job)
    deadline = time.monotonic() + int(job.get("health_timeout") or 120)
    expected = job.get("expected_version") or None
    streak = 0
    last = ""
    while time.monotonic() < deadline:
        if mode == "is_active":
            r = _systemctl(job, "is-active", job["service_name"], timeout=15)
            if r.returncode == 0 and r.stdout.strip() == "active":
                streak += 1
                if streak >= HEALTH_STREAK:
                    _write_state(
                        state_path,
                        health={"mode": mode, "ok": True, "detail": None},
                    )
                    return True
            else:
                streak = 0
                last = (r.stdout or "").strip() or (r.stderr or "").strip()[:200]
        else:
            url = "%s://127.0.0.1:%d/api/upd/health" % (mode, port)
            ctx = ssl._create_unverified_context() if mode == "https" else None
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "Bot4VPS-SelfRestore"}
                )
                with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                if expected is None or data.get("version") == expected:
                    streak += 1
                    if streak >= HEALTH_STREAK:
                        _write_state(
                            state_path,
                            health={"mode": mode, "ok": True, "detail": None},
                        )
                        return True
                else:
                    streak = 0
                    last = "версия %s != %s" % (data.get("version"), expected)
            except Exception as e:
                streak = 0
                last = str(e)
        # heartbeat: цикл бывает долгим (до health_timeout)
        _write_state(state_path)
        time.sleep(HEALTH_INTERVAL)
    _write_state(
        state_path,
        health={"mode": mode, "ok": False, "detail": last[:300] or "таймаут"},
    )
    return False


def _cleanup_inputs(job: dict) -> None:
    """Best-effort уборка входов раннера (права на это только у него при
    гибели вызвавшего процесса). Каталожные архивы НЕ трогаются —
    удаляется только расшифрованный temp (cleanup_archive) и member list."""
    if job.get("cleanup_archive"):
        try:
            os.unlink(job["archive"])
        except OSError:
            pass
    try:
        os.unlink(job["member_list"])
    except OSError:
        pass


# ==================================================================
# main
# ==================================================================

def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: self_restore_runner.py <job.json>", file=sys.stderr)
        return 2
    job = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    state_path = Path(job["state_file"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    _write_state(
        state_path,
        operation_id=job["operation_id"],
        status="running",
        stage="gate",
        error=None,
    )

    failure: str | None = None

    # --- 0. gate: мутационная граница решается ядром ------------------
    if not _wait_gate(job, state_path):
        # Go-файл не появился: отмена (ядро увидело request_cancel) либо
        # вызвавший процесс погиб. Сервис жив, дерево не тронуто.
        _write_state(
            state_path,
            status="failed",
            stage="gate",
            error="Подтверждение запуска не получено: восстановление не начиналось",
        )
        _cleanup_inputs(job)
        return 1

    # --- 1. stop: мутационная граница -------------------------------
    _write_state(state_path, stage="stop")
    if not _stop_service(job, state_path):
        # Сервис жив, дерево не тронуто: чистый отказ без мутации.
        _write_state(
            state_path,
            status="failed",
            stage="stop",
            error="Не удалось остановить сервис: восстановление не начиналось",
        )
        _cleanup_inputs(job)
        return 1

    # --- 2. extract -------------------------------------------------
    _write_state(state_path, stage="extract")
    if not _extract(job, state_path):
        failure = "Распаковка архива завершилась ошибкой (детали в extract)"

    # --- 3. daemon-reload -------------------------------------------
    _write_state(state_path, stage="daemon_reload")
    if not _daemon_reload(job, state_path):
        if failure is None:
            failure = "systemctl daemon-reload не удался"

    # --- 4. pip (только при изменении requirements.txt) -------------
    _write_state(state_path, stage="pip")
    if not _pip_if_changed(job, state_path):
        if failure is None:
            failure = "pip install не удался: зависимости не соответствуют архиву"

    # --- 5. start (best-effort при любой ошибке выше) ---------------
    _write_state(state_path, stage="start")
    if not _start_service(job, state_path):
        if failure is None:
            failure = "Не удалось запустить сервис после восстановления"

    # --- 6. health ---------------------------------------------------
    _write_state(state_path, stage="health")
    if failure is None and not _health(job, state_path):
        failure = "Health-check не пройден после восстановления"

    _cleanup_inputs(job)
    if failure is None:
        _write_state(state_path, status="succeeded", error=None)
        print("[self-restore] OK", flush=True)
        return 0
    _write_state(state_path, status="failed", error=failure)
    print("[self-restore] FAILED: %s" % failure, file=sys.stderr, flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
