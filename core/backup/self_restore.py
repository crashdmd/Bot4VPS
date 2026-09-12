"""Локальный self-restore Bot4VPS: оркестратор, общий для Web и CLI.

Владелец семантики (раннер в self_restore_runner.py — глупый исполнитель):
запуск раннера вне процесса (паттерн core/update/updater.py — systemd-run
--scope, иначе KillMode=mixed убьёт его при stop), протокол «go-файл» для
атомарной мутационной границы, финализация по state.json раннера.

Один и тот же путь для обоих входов:

* Web: submit_*_restore(apply=True) → restore() → apply_self_restore().
  Web-процесс умирает на systemctl stop — это нормально: истина в state.json
  раннера и Operation-записи; закрывает startup-hook reconcile_self_restores
  (общий для uvicorn и bot.py).
* CLI: тот же apply_self_restore(), но CLI-процесс живёт всё окно и
  финализирует сразу по завершении раннера.

Мутационная граница: раннер паркуется на go-файле после старта; ядро
атомарно проверяет отмену и выставляет признак мутации
(mark_restore_mutation_started) и только потом отпускает раннер. Отказ
запуска или отменённая операция — до границы: сервис жив, дерево не тронуто.
"""
from __future__ import annotations

import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from core.install_paths import get_install_path
from core.version import APP_VERSION

from .errors import BackupError, ErrorCode
from .models import OperationStatus, TERMINAL_STATUSES
from .restore_apply import (
    RESTORE_MODE_MERGE,
    classify_restore_tar_diagnostics,
    create_restore_member_list,
    verify_applied_restore_local,
)

SERVICE_NAME = "bot4vps"
UNIT_PATH = "/etc/systemd/system/bot4vps.service"

# Каталог состояния раннеров: data/backup/self_restore/<operation_id>/.
# Внутри восстанавливаемого дерева, но не пересекается с member list архива
# (operation_id уникален) и не является членом архива — extraction его не
# трогает. Переживает рестарт (в отличие от /tmp), поэтому reconcile после
# перезапуска сервиса всегда находит состояние раннера.
STATE_SUBDIR = "self_restore"

RUNNER_NAME = "self_restore_runner.py"
GATE_TIMEOUT = 60            # сколько раннер ждёт go-файл, секунд
POLL_INTERVAL = 1.0          # период опроса state.json раннера
# Порог протухания heartbeat. Все долгие шаги раннера — одиночные
# subprocess.run со своими таймаутами (tar 1800с, pip 900с), между которыми
# heartbeat не пишется; порог обязан быть больше суммы худших случаев.
RUNNER_STALE_AFTER = 3600.0

_STAGE_VIEW = {
    # stage раннера → (stage Operation, percent)
    "gate": ("self_restore_launch", 40.0),
    "stop": ("stopping_service", 45.0),
    "extract": ("extracting", 60.0),
    "daemon_reload": ("daemon_reload", 70.0),
    "pip": ("installing_dependencies", 75.0),
    "start": ("starting_service", 85.0),
    "health": ("health_check", 92.0),
}


def _apply_failure(message: str, **details) -> BackupError:
    return BackupError(
        ErrorCode.RESTORE_APPLY_FAILED,
        message,
        details=dict(details) or None,
    )


def _read_json(path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json_atomic(path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def state_dir_for(data_root, operation_id: str) -> Path:
    return Path(data_root) / STATE_SUBDIR / operation_id


# --------------------------------------------------------------------------- #
# Осмотр архива для предупреждений prepare и expected_version
# --------------------------------------------------------------------------- #

def inspect_self_restore_archive(archive_path, plan: dict) -> dict:
    """Версия producer и текст юнита из архива — один проход tarfile.

    Возвращаются только факты для предупреждений и health; план эта функция
    не строит и не валидирует (это уже сделал restore()).
    """
    version: str | None = None
    unit_text: str | None = None
    unit_member: str | None = None
    for entry in plan.get("entries") or ():
        if str(entry.get("path")) == UNIT_PATH:
            unit_member = str(entry.get("name"))
            break
    try:
        with tarfile.open(str(archive_path), "r:gz") as tar:
            for name in ("payload/manifest.json", "manifest.json"):
                try:
                    member = tar.getmember(name)
                except KeyError:
                    continue
                if member.isfile():
                    stream = tar.extractfile(member)
                    if stream is not None:
                        manifest = json.loads(stream.read().decode("utf-8"))
                        version = str(
                            (manifest.get("producer") or {}).get("version") or ""
                        ) or None
                    break
            if unit_member is not None:
                try:
                    member = tar.getmember(unit_member)
                except KeyError:
                    member = None
                if member is not None and member.isfile():
                    stream = tar.extractfile(member)
                    if stream is not None:
                        unit_text = stream.read().decode("utf-8", "replace")
    except (OSError, ValueError, tarfile.TarError):
        # Осмотр вспомогательный: нечитаемый архив уже отвергнут физической
        # валидацией restore(); здесь отказ не должен блокировать применение.
        return {"version": None, "unit_text": None}
    return {"version": version, "unit_text": unit_text}


def _current_unit_text() -> str | None:
    try:
        return Path(UNIT_PATH).read_text(encoding="utf-8")
    except OSError:
        return None


def _unit_mode(unit_text: str | None) -> str | None:
    if unit_text is None:
        return None
    return "web+tg" if "uvicorn" in unit_text else "tg-only"


def _unit_port(unit_text: str | None) -> str | None:
    if unit_text is None:
        return None
    for line in unit_text.splitlines():
        if "--port" in line:
            parts = line.split()
            for index, part in enumerate(parts):
                if part == "--port" and index + 1 < len(parts):
                    return parts[index + 1]
    return None


def self_restore_prepare_warnings(inspected: dict) -> list[str]:
    """Предупреждения prepare: версия кода, режим юнита, порт.

    Архив побеждает (restore — не миграция): предупреждение, а не отказ.
    """
    warnings: list[str] = []
    version = inspected.get("version")
    if version and version != APP_VERSION:
        warnings.append(
            f"Архив создан версией {version}, текущая — {APP_VERSION}: после "
            "восстановления код будет заменён на версию из архива"
        )
    current_unit = _current_unit_text()
    archived_unit = inspected.get("unit_text")
    if archived_unit is not None and current_unit is not None:
        current_mode = _unit_mode(current_unit)
        archived_mode = _unit_mode(archived_unit)
        if current_mode != archived_mode:
            warnings.append(
                f"Режим юнита изменится: сейчас {current_mode}, в архиве "
                f"{archived_mode}"
            )
        elif current_mode == "web+tg":
            current_port = _unit_port(current_unit)
            archived_port = _unit_port(archived_unit)
            if current_port != archived_port:
                warnings.append(
                    f"Порт Web-панели изменится: сейчас {current_port}, "
                    f"в архиве {archived_port}"
                )
    return warnings


def prepare_warnings_for(
    manager,
    *,
    source_kind: str,
    record: dict,
    resolved_import,
    decrypted_archive,
    plan: dict,
) -> list[str]:
    """Предупреждения prepare для bot4vps-цели: версия, режим юнита, порт.

    Зашифрованный архив без пароля осмотреть нельзя — предупреждений не
    будет (apply спросит пароль раньше и покажет их там же).
    """
    archive = decrypted_archive
    if archive is None and source_kind != "managed":
        archive = (resolved_import or {}).get("archive")
    if archive is None and source_kind == "managed":
        try:
            archive = manager.storage.resolve_key(record["storage"]["key"])
        except Exception:
            return []
    if archive is None or not Path(archive).is_file():
        return []
    from .archive_crypto import is_encrypted_file

    if is_encrypted_file(archive):
        return []
    return self_restore_prepare_warnings(
        inspect_self_restore_archive(archive, plan)
    )


# --------------------------------------------------------------------------- #
# Запуск раннера
# --------------------------------------------------------------------------- #

def _prune_finished_state_dirs(manager, *, keep_seconds: float = 86400.0) -> None:
    """Убрать каталоги состояний терминальных операций старше суток."""
    root = Path(manager.data_root) / STATE_SUBDIR
    if not root.is_dir():
        return
    now = time.time()
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        try:
            record = manager.operations.get(entry.name)
        except Exception:
            record = None
        if record is None or record.get("status") not in TERMINAL_STATUSES:
            continue
        try:
            if now - entry.stat().st_mtime > keep_seconds:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue


def _build_job(
    *,
    operation_id: str,
    archive_file: Path,
    member_list: Path,
    plan: dict,
    roots,
    cleanup_archive: bool,
    expected_version: str | None,
    backup_filename: str | None,
    state_file: Path,
    go_file: Path,
) -> dict:
    layout = plan.get("layout")
    parent_directories = sorted(
        {
            posixpath.dirname(posixpath.normpath(str(root)))
            for root in roots or ()
            if posixpath.dirname(posixpath.normpath(str(root))) not in ("", "/")
        }
    )
    return {
        "operation_id": operation_id,
        "service_name": SERVICE_NAME,
        "backup_filename": backup_filename,
        "archive": str(archive_file),
        "member_list": str(member_list),
        "cleanup_archive": bool(cleanup_archive),
        "layout": layout,
        "target_root": plan.get("target_root"),
        "parent_directories": parent_directories,
        "roots": [str(root) for root in roots or ()],
        "app_dir": str(get_install_path()),
        "venv_python": sys.executable,
        "unit_path": UNIT_PATH,
        "requirements_current_sha256": _requirements_sha256(),
        "expected_version": expected_version,
        "health_port": _current_unit_port() or 8080,
        "health_timeout": 120,
        "gate_timeout": GATE_TIMEOUT,
        "state_file": str(state_file),
        "go_file": str(go_file),
        "dev_no_systemd": bool(os.environ.get("BOT4VPS_SELF_RESTORE_DEV_NO_SYSTEMD")),
    }


def _requirements_sha256() -> str | None:
    import hashlib

    path = get_install_path() / "requirements.txt"
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _current_unit_port() -> str | None:
    return _unit_port(_current_unit_text())


def _launch_runner(job: dict) -> int:
    """Запустить раннер вне процесса (systemd-run --scope, фолбэк Popen).

    Копия скрипта и job.json — во временном каталоге ВНЕ дерева установки:
    extraction перезаписывает core/backup/self_restore_runner.py, а Python
    читает исходник скрипта лениво.
    """
    work_dir = Path(tempfile.mkdtemp(prefix="bot4vps_self_restore_"))
    src = Path(__file__).with_name(RUNNER_NAME)
    dst = work_dir / RUNNER_NAME
    shutil.copyfile(src, dst)
    (work_dir / "job.json").write_text(
        json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    command = [job["venv_python"], str(dst), str(work_dir / "job.json")]
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    try:
        proc = subprocess.Popen(
            ["systemd-run", "--scope", "--collect",
             "--unit", "bot4vps-self-restore-%s" % timestamp] + command,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (FileNotFoundError, OSError):
        proc = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    return proc.pid


def _state_heartbeat_age(state: dict) -> float | None:
    try:
        updated = datetime.fromisoformat(str(state.get("updated_at") or ""))
    except ValueError:
        return None
    return max(0.0, (datetime.now() - updated).total_seconds())


def apply_self_restore(
    manager,
    *,
    operation_id: str,
    plan: dict,
    roots,
    archive_file: Path,
    decrypted_archive,
    mode: str,
    warnings: list[str],
    protective_result,
    backup_filename: str | None,
) -> dict:
    """Локальное применение: раннер вне процесса + финализация по его state.

    Вызывается из restore() после сводки, контрактов и защитной копии.
    Возвращает результат в форме SSH-пути; при провале раннера поднимает
    ошибку мутации (переход и событие уже сделаны финализацией).
    """
    if mode != RESTORE_MODE_MERGE:
        raise BackupError(
            ErrorCode.RESTORE_PRECHECK_FAILED,
            "Для Bot4VPS доступно только обычное восстановление",
        )
    if not archive_file or not Path(archive_file).is_file():
        raise BackupError(
            ErrorCode.ARTIFACT_NOT_FOUND,
            "Архив восстановления не найден",
        )

    _prune_finished_state_dirs(manager)

    inspected = inspect_self_restore_archive(archive_file, plan)
    warnings.extend(self_restore_prepare_warnings(inspected))

    state_dir = state_dir_for(manager.data_root, operation_id)
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "state.json"
    go_file = state_dir / "go"
    member_list, _ = create_restore_member_list(
        plan, operation_id, directory=state_dir
    )
    # Худой план для финализации: финализатор может работать в другом процессе
    # (startup-hook) и даже на восстановленном коде — полный план он не имеет
    # права пересобрать (архив мог быть расшифрован паролем, которого уже нет).
    entries_payload = {
        "layout": plan.get("layout"),
        "target_root": plan.get("target_root"),
        "roots": [str(root) for root in roots or ()],
        "entries": [
            {
                key: entry.get(key)
                for key in ("name", "type", "size", "path", "root", "linkname")
                if key in entry
            }
            for entry in plan.get("entries") or ()
        ],
    }
    _write_json_atomic(state_dir / "entries.json", entries_payload)

    job = _build_job(
        operation_id=operation_id,
        archive_file=Path(archive_file),
        member_list=member_list,
        plan=plan,
        roots=roots,
        cleanup_archive=decrypted_archive is not None,
        expected_version=inspected.get("version"),
        backup_filename=backup_filename,
        state_file=state_file,
        go_file=go_file,
    )
    manager.operations.attach_restore_metadata(
        operation_id,
        "self_restore",
        {
            "state_dir": str(state_dir),
            "state_file": str(state_file),
            "entries_file": str(state_dir / "entries.json"),
            "job": job,
        },
    )

    manager.operations.update_stage(operation_id, "self_restore_launch")
    try:
        _launch_runner(job)
    except OSError as exc:
        # Раннер не стартовал: сервис не останавливался, дерево не тронуто —
        # чистый отказ ДО мутационной границы.
        raise BackupError(
            ErrorCode.RESTORE_PRECHECK_FAILED,
            "Не удалось запустить исполнитель локального восстановления",
            retryable=True,
            details={"error": str(exc)[:300]},
        ) from exc

    # ─────────────── DESTRUCTIVE BOUNDARY ───────────────
    # Атомарная проверка отмены + признак мутации; раннер в это время стоит
    # на go-файле и сервиса ещё не трогал. Отпускаем его только после
    # успешной постановки границы.
    manager.operations.mark_restore_mutation_started(operation_id)
    go_file.write_text("go\n", encoding="utf-8")

    record = poll_runner_state(manager, operation_id)
    if record.get("status") != OperationStatus.COMPLETED.value:
        failure = (record.get("error") or {}).get("message") if isinstance(record.get("error"), dict) else None
        raise _apply_failure(
            failure or "Локальное восстановление Bot4VPS не завершено",
            operation_status=record.get("status"),
            self_restore=record.get("self_restore"),
        )

    return {
        "operation": record,
        "archive": None,
        "mode": mode,
        "plan": plan,
        "preview": None,
        "delete": None,
        "protective_backup": manager._protective_backup_view(protective_result),
        "applied": True,
        "removed": 0,
        "verification": (record.get("restore") or {}).get("verification"),
        "warnings": warnings,
        "notice": (
            "Restore применён локально: файлы из backup записаны в установку, "
            "сервис перезапущен и проверен."
        ),
    }


# --------------------------------------------------------------------------- #
# Наблюдение за раннером (общее для submit-поллинга и startup-adoption)
# --------------------------------------------------------------------------- #

def poll_runner_state(manager, operation_id: str) -> dict:
    """Опрашивать state.json раннера до терминального статуса и финализировать.

    Общий хвост apply_self_restore: stage/progress тянутся в Operation,
    liveness — по heartbeat (tar и pip — одиночные subprocess.run со своими
    таймаутами, между которыми раннер состояние не обновляет).
    """
    op = manager.operations.get(operation_id)
    state_file = ((op.get("restore") or {}).get("self_restore") or {}).get(
        "state_file"
    )
    deadline = False
    seen_stage = None
    while True:
        state = _read_json(state_file) if state_file else {}
        stage = str(state.get("stage") or "")
        if stage and stage != seen_stage and stage in _STAGE_VIEW:
            seen_stage = stage
            view_stage, percent = _STAGE_VIEW[stage]
            manager.operations.update_stage(operation_id, view_stage)
            manager.operations.update_progress(operation_id, percent=percent)
        if state.get("status") in ("succeeded", "failed"):
            break
        age = _state_heartbeat_age(state)
        if state and (age is None or age > RUNNER_STALE_AFTER):
            deadline = True
            break
        time.sleep(POLL_INTERVAL)

    return finalize_self_restore(
        manager,
        operation_id,
        runner_finished=not deadline,
    )


def adopt_live_self_restores(manager) -> list[dict]:
    """«Удочерить» живые self-restore операции на старте Web-процесса.

    Раннер сам останавливает сервис — вместе с ним гибнет и поток,
    опрашивающий state.json. Новый процесс обязан довести наблюдение до
    конца под owner-permit: без этого reconcile_startup пометит операцию
    abandoned (раннер permit не держит — он «глупый исполнитель»), а
    успешно завершившийся раннер навсегда оставит в записи «failed».
    Вызывать ПОСЛЕ reconcile_self_restores и ДО старта планировщиков.
    """
    adopted: list[dict] = []
    for op in manager.list_operations(operation_type="restore"):
        if op.get("status") in TERMINAL_STATUSES:
            continue
        meta = (op.get("restore") or {}).get("self_restore")
        if not isinstance(meta, dict):
            continue
        state = _read_json(meta.get("state_file")) if meta.get("state_file") else {}
        # Терминальные и протухшие раннеры закрывает reconcile_self_restores;
        # здесь — только живые.
        if not state or state.get("status") != "running":
            continue
        age = _state_heartbeat_age(state)
        if age is None or age > RUNNER_STALE_AFTER:
            continue
        permit = manager.coordinator.try_acquire_operation_owner(
            op["operation_id"]
        )
        if permit is None:
            # Кто-то уже наблюдает (CLI-поллинг пережил рестарт сервиса).
            continue
        watcher = threading.Thread(
            target=_watch_adopted_self_restore,
            args=(manager, op["operation_id"], permit),
            name=f"self-restore-adopt-{op['operation_id'][-12:]}",
            daemon=True,
        )
        watcher.start()
        adopted.append(op)
    return adopted


def _watch_adopted_self_restore(manager, operation_id: str, permit) -> None:
    try:
        poll_runner_state(manager, operation_id)
    except Exception as exc:
        # Наблюдатель не должен ронять процесс: провал финализации виден
        # в записи операции (следующий startup-reconcile её закроет).
        print(
            f"[SELF-RESTORE ADOPT] наблюдение op {operation_id} "
            f"завершилось ошибкой: {exc}",
            flush=True,
        )
    finally:
        permit.release()


# --------------------------------------------------------------------------- #
# Финализация (общая для CLI-поллинга и startup-reconcile)
# --------------------------------------------------------------------------- #

_CATALOG_RECORD_RE = re.compile(r"^bkp-[0-9a-f]{32}$")


def _isolated_catalog_records(missing: list, manager) -> list[str]:
    """Среди отсутствующих путей — изолированные записи каталога.

    Merge-restore пишет записи каталога из payload архива, но сами архивы
    живут во внешнем storage и в payload не входят. Запись, чей архив
    удалён после снапшота (superseded protective-копия, retention), старт
    нового процесса изолирует по storage_pair_missing — такой «missing»
    не означает неполный restore.

    Доказательство легитимности — тройное, а не «архива нет»:
    1) tar с exit 0 записал запись на диск (пропуск файла исключён
       классификатором выше);
    2) карантинная копия ``invalid/<backup_id>.invalid-*.json`` существует
       — значит запись убрала штатная изоляция reconcile_startup, а не
       сторонний удалятор (isolate() переносит файл, а не удаляет);
    3) архива действительно нет в storage — независимо перепроверяем
       обоснование storage_pair_missing.
    Без карантинной копии (например, finish_delete при прерванном
    retention-delete) — не терпим: пусть сбой виден, а не маскируется.
    """
    catalog_root = posixpath.normpath(
        str(Path(manager.data_root) / "catalog")
    ).rstrip("/")
    quarantine_root = Path(catalog_root) / "invalid"
    tolerated: list[str] = []
    for item in missing:
        normalized = posixpath.normpath(str(item))
        prefix = catalog_root + "/"
        if not normalized.startswith(prefix):
            continue
        relative = normalized[len(prefix):]
        namespace, _, name = relative.rpartition("/")
        backup_id = name[:-5] if name.endswith(".json") else ""
        if not namespace or not _CATALOG_RECORD_RE.fullmatch(backup_id):
            continue
        try:
            archive = manager.storage.resolve_key(
                f"{namespace}/{backup_id}.tar.gz"
            )
        except BackupError:
            continue
        if archive.is_file():
            continue
        if any(quarantine_root.glob(f"{backup_id}.invalid-*.json")):
            tolerated.append(normalized)
    return tolerated


def finalize_self_restore(
    manager,
    operation_id: str,
    *,
    runner_finished: bool,
) -> dict:
    """Закрыть операцию self-restore по state.json раннера. Идемпотентно.

    ``runner_finished=True`` — вызывающий процесс дождался выхода раннера
    (CLI-поллинг); ``False`` — startup-reconcile: раннер мог закончиться
    давно, а мог и умереть — решает heartbeat state.json.
    """
    op = manager.operations.get(operation_id)
    if op.get("status") in TERMINAL_STATUSES:
        return op
    meta = (op.get("restore") or {}).get("self_restore") or {}
    state_file = meta.get("state_file")
    state = _read_json(state_file) if state_file else {}
    entries_payload = _read_json(meta.get("entries_file")) if meta.get("entries_file") else {}

    def _fail(message: str, **details) -> dict:
        boundary = bool((state.get("stop") or {}).get("ok"))
        if boundary:
            # Мутация началась (сервис останавливался) — граница обязана
            # стоять в записи, даже если ставивший её процесс умер.
            try:
                manager.operations.mark_restore_mutation_started(operation_id)
            except BackupError:
                pass
        if boundary:
            details.setdefault("target_state", "partially_modified_or_unknown")
        else:
            details.setdefault("target_state", "unmodified")
        error = _apply_failure(message, **details)
        failed = manager.operations.transition(
            operation_id,
            OperationStatus.FAILED.value,
            stage=str(state.get("stage") or op.get("stage") or "failed"),
            error=error.to_safe_error(),
        )
        manager._emit_restore_event(
            operation=failed,
            notifications={},
            success=False,
            mutation_started=boundary,
            error=error.to_safe_error().to_dict(),
            backup_filename=(meta.get("job") or {}).get("backup_filename"),
            server_name="Bot4VPS",
            server_id=None,
            mode=RESTORE_MODE_MERGE,
            protective_backup=(op.get("restore") or {}).get("protective_backup_id"),
        )
        return failed

    if not state:
        return _fail(
            "Исполнитель локального восстановления не оставил состояния: "
            "запуск не состоялся либо состояние потеряно",
            phase="launch",
        )
    if state.get("status") == "running":
        age = _state_heartbeat_age(state)
        if runner_finished:
            return _fail(
                "Исполнитель восстановления завершился без терминального статуса",
                phase=str(state.get("stage") or "unknown"),
                runner_state=state,
            )
        if age is not None and age <= RUNNER_STALE_AFTER:
            # Раннер ещё жив: операция остаётся running, reconcile уйдёт.
            return manager.operations.get(operation_id)
        return _fail(
            "Исполнитель восстановления не отвечает (heartbeat протух) — "
            "состояние установки неизвестно",
            phase=str(state.get("stage") or "unknown"),
            runner_state=state,
        )

    # Граница: сервис останавливался раннером.
    if (state.get("stop") or {}).get("ok"):
        try:
            manager.operations.mark_restore_mutation_started(operation_id)
        except BackupError:
            pass

    # Классификация tar-диагностик — существующим классификатором, по
    # худому плану из entries.json (полный план пересобирать нельзя:
    # расшифровка требовала пароля, которого у финализатора нет).
    extract = state.get("extract") or {}
    classified = classify_restore_tar_diagnostics(
        int(extract.get("exit_code") if extract.get("exit_code") is not None else -1),
        str(extract.get("stderr") or ""),
        plan=entries_payload,
    )
    if not classified.get("ok"):
        return _fail(
            "Распаковка архива завершилась ошибкой",
            phase="extract",
            tar_exit_code=extract.get("exit_code"),
            tar_error=str(extract.get("stderr") or "")[:500] or None,
            tar_classification=classified.get("reason"),
        )
    if classified.get("skipped"):
        busy = [str(item.get("path")) for item in classified["skipped"]]
        return _fail(
            "Занятые файлы при остановленном сервисе: восстановление "
            "применено не полностью",
            phase="extract",
            tar_exit_code=extract.get("exit_code"),
            busy_paths=busy[:20],
            busy_count=len(busy),
        )

    verification = verify_applied_restore_local(entries_payload)
    if verification["missing_count"] and verification["missing_count"] <= len(
        verification["missing"]
    ):
        # Записи каталога, чьих архивов уже нет в storage (прежде всего
        # superseded protective-копии: новая защитная копия удаляет прежнюю
        # ДО apply, extract воскрешает запись из архива, а старт нового
        # процесса изолирует её по storage_pair_missing), — легитимное
        # состояние, а не недоприменённый restore.
        tolerated = _isolated_catalog_records(
            list(verification["missing"]), manager
        )
        if len(tolerated) == verification["missing_count"]:
            verification = dict(verification)
            verification["missing"] = []
            verification["missing_count"] = 0
            verification["tolerated_missing_catalog"] = tolerated
    manager.operations.attach_restore_metadata(
        operation_id,
        "extraction",
        {
            "tar_exit_code": int(extract.get("exit_code") or 0),
            "skipped_count": 0,
            "diagnostics": list(classified.get("diagnostics") or [])[:256],
            # bool запрещён схемой extraction-проекции — строковый маркер
            "scope": "local",
        },
    )
    manager.operations.attach_restore_metadata(
        operation_id,
        "verification",
        verification,
    )
    if verification["missing_count"]:
        return _fail(
            "Восстановление применено не полностью: результат не совпал с планом",
            phase="verify",
            **verification,
        )

    pip = state.get("pip") or {}
    if pip.get("ran") and not pip.get("ok"):
        return _fail(
            "pip install не удался: зависимости не соответствуют архиву, "
            "сервис не может быть объявлен восстановленным",
            phase="pip",
            pip_error=str(pip.get("error") or "")[:400] or None,
        )

    start = state.get("start") or {}
    if not start.get("ok"):
        return _fail(
            "Не удалось запустить сервис после восстановления",
            phase="start",
            start_error=str(start.get("error") or "")[:400] or None,
        )

    health = state.get("health") or {}
    if not health.get("ok"):
        return _fail(
            "Health-check не пройден после восстановления",
            phase="health",
            health=health,
        )

    if str(health.get("mode")) == "is_active":
        tg_ok, tg_note = _telegram_freshness()
        if not tg_ok:
            return _fail(
                "Telegram-сервис поднялся без свежего состояния бота",
                phase="health",
                telegram=tg_note,
            )

    # Понижение кода без pip-синхронизации — предупреждение, не отказ.
    if pip.get("ran"):
        manager.operations.add_warnings(
            operation_id,
            [{
                "code": "restore_warning",
                "message": (
                    "requirements.txt изменён: пакеты доустановлены без "
                    "удаления лишних (понижение версии может оставить "
                    "зависимости новее кода)"
                ),
            }],
        )

    completed = manager.operations.transition(
        operation_id,
        OperationStatus.COMPLETED.value,
        stage="applied",
    )
    manager._emit_restore_event(
        operation=completed,
        notifications={},
        success=True,
        mutation_started=True,
        backup_filename=(meta.get("job") or {}).get("backup_filename"),
        server_name="Bot4VPS",
        server_id=None,
        mode=RESTORE_MODE_MERGE,
        protective_backup=(op.get("restore") or {}).get("protective_backup_id"),
    )
    return completed


def _telegram_freshness(timeout: float = 30.0) -> tuple[bool, str | None]:
    """Свежесть data/telegram_state.json против старта сервиса (tg-only).

    Ровно логика telegram_running() из ui/cli/ops.py: состояние от предыдущего
    запуска протухло. Новую TG-механику не изобретаем — читаем существующий
    state-файл, который пишет сам процесс бота.
    """
    from core.telegram_state import read_state

    deadline = time.monotonic() + timeout
    while True:
        state = read_state()
        status = str(state.get("status") or "")
        started = _service_started_at()
        try:
            updated = datetime.fromisoformat(str(state.get("updated_at") or ""))
        except ValueError:
            updated = None
        if status in ("running", "disabled", "no_token"):
            if started is None or updated is None or updated >= started:
                return True, None
            note = "состояние Telegram протухло (до старта сервиса)"
        elif status in ("failed", "stopped"):
            return False, str(state.get("error") or status)
        else:
            note = "состояние Telegram не определено"
        if time.monotonic() >= deadline:
            return False, note
        time.sleep(1.0)


def _service_started_at() -> datetime | None:
    try:
        result = subprocess.run(
            ["systemctl", "show", SERVICE_NAME, "--property=ActiveEnterTimestamp"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = (result.stdout or "").strip()
    if "=" not in line:
        return None
    raw = line.split("=", 1)[1].strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%a %Y-%m-%d %H:%M:%S %Z")
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Startup-reconcile: общий hook для uvicorn (app.py) и bot.py
# --------------------------------------------------------------------------- #

def reconcile_self_restores(manager) -> list[dict]:
    """Закрыть висящие self-restore операции на старте сервиса.

    Обязан выполняться ДО старта планировщиков и бэкап-задач: до него
    maintenance-состояние могло остаться от погибшего процесса, и задачи
    увидели бы ложный MAINTENANCE_ACTIVE (или, хуже, не увидели бы его в
    окне полуприменённого восстановления).
    """
    try:
        manager.coordinator.reconcile_maintenance_state()
    except Exception:
        pass
    closed: list[dict] = []
    for op in manager.list_operations(operation_type="restore"):
        if op.get("status") in TERMINAL_STATUSES:
            continue
        if (op.get("restore") or {}).get("self_restore") is None:
            continue
        closed.append(
            finalize_self_restore(
                manager,
                op["operation_id"],
                runner_finished=False,
            )
        )
    return closed


# --------------------------------------------------------------------------- #
# Живой view для get_operation (единый watch Web и поллинга CLI)
# --------------------------------------------------------------------------- #

def enrich_operation(record: dict) -> dict:
    """Прогресс раннера в view операции (только чтение, не персистится)."""
    restore = record.get("restore") or {}
    meta = restore.get("self_restore")
    if not meta or record.get("status") in TERMINAL_STATUSES:
        return record
    state = _read_json(meta.get("state_file"))
    if not state:
        return record
    enriched = dict(record)
    enriched["self_restore"] = {
        "stage": state.get("stage"),
        "status": state.get("status"),
        "updated_at": state.get("updated_at"),
        "error": state.get("error"),
    }
    return enriched
