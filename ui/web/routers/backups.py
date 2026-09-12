from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.backup.errors import BackupError, ErrorCode
from core.backup.manifest import validate_manifest
from core.backup.time_utils import (
    local_timezone,
    parse_utc_timestamp,
    timezone_from_utc_offset,
)
from core.config import get_backup_config, patch_backup_config
from core.storage import (
    BackupProfileConflictError,
    get_server_backup_profile,
    load_servers,
    server_backup_configured,
)
from ..backup_runtime import (
    call,
    locate_source_async,
    save_server_backup_profile_async,
    source_tree_async,
)

async def _run_sync(function, *args, **kwargs):
    return await asyncio.to_thread(function, *args, **kwargs)


def _temporary_import_path() -> Path:
    fd, temporary = tempfile.mkstemp(prefix="bot4vps-import-", suffix=".tar.gz")
    os.close(fd)
    return Path(temporary)


router = APIRouter(prefix="/api/backups", tags=["backups"])
logger = logging.getLogger(__name__)


_RESTORE_DIAGNOSTIC_FIELDS = frozenset({
    "schema_version",
    "inventory_hit",
    "inventory_lookup_validation_ms",
    "tar_scan_ms",
    "archive_member_count",
    "member_validation_ms",
    "inventory_cache_write_ms",
    "import_lock_wait_ms",
    "bundle_resolution_ms",
    "readiness_ms",
    "response_member_count",
    "manifest_validation_ms",
    "restore_plan_ms",
    "full_preview_tree_ms",
    "planned_member_count",
    "planning_context_ms",
    "directory_tree_ms",
    "directory_tree_included",
    "directory_tree_nodes",
    "effective_plan_ms",
    "effective_policy_ms",
    "effective_preview_tree_ms",
    "manager_total_ms",
})


def _attach_restore_diagnostics(
    result: dict,
    response: dict,
    *,
    started: float,
) -> dict:
    """Attach opt-in timing counters without archive paths or member content."""
    raw_diagnostics = response.get("diagnostics") or {}
    diagnostics = {
        key: value
        for key, value in raw_diagnostics.items()
        if key in _RESTORE_DIAGNOSTIC_FIELDS
        and isinstance(value, (bool, int, float))
    }
    diagnostics["router_before_serialization_ms"] = round(
        (time.perf_counter() - started) * 1000,
        3,
    )
    result["diagnostics"] = diagnostics
    diagnostics["serialization_estimate_ms"] = 0.0
    diagnostics["response_json_bytes_estimate"] = 0
    serialization_started = time.perf_counter()
    json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    diagnostics["serialization_estimate_ms"] = round(
        (time.perf_counter() - serialization_started) * 1000,
        3,
    )
    for _attempt in range(3):
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        encoded_size = len(encoded.encode("utf-8"))
        if diagnostics["response_json_bytes_estimate"] == encoded_size:
            break
        diagnostics["response_json_bytes_estimate"] = encoded_size
    return result


def _raise_safe(exc: Exception, status: int = 400):
    if isinstance(exc, BackupError):
        # SafeError — frozen dataclass, а не dict: обращение по ключу поднимало бы
        # TypeError прямо в обработчике и подменяло 400 с русским текстом на 500.
        safe = exc.to_safe_error()
        headers = {"X-Backup-Error": safe.code}
        if safe.details:
            headers["X-Backup-Details"] = json.dumps(
                safe.details,
                ensure_ascii=True,
                separators=(",", ":"),
            )
        raise HTTPException(status, detail=safe.message, headers=headers)
    if isinstance(exc, (ValueError, TypeError)):
        raise HTTPException(status, str(exc))
    if isinstance(exc, OSError):
        logger.exception("Backup profile/storage operation failed")
        raise HTTPException(status, "Не удалось сохранить профиль: проверьте доступность файла и права записи")
    logger.exception("Unexpected Backup Web API error")
    raise HTTPException(500, "Внутренняя ошибка Backup Manager")


def _raise_inventory_safe(exc: Exception):
    """Map lazy inventory states without exposing archive or storage details."""
    if isinstance(exc, BackupError):
        missing = exc.code in {
            ErrorCode.ARTIFACT_NOT_FOUND.value,
            ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE.value,
        }
        inventory_error = exc.details.get("inventory_error")
        conflict = inventory_error in {
            "not_ready",
            "cursor_stale",
            "watched_job_invalid",
            "rebuild_not_ready",
        }
        _raise_safe(exc, 404 if missing else 409 if conflict else 400)
    _raise_safe(exc, 400)


def _restore_inventory_prepare_response(result: dict):
    if result.get("status") in {"queued", "indexing"}:
        return JSONResponse(content=result, status_code=202)
    return result


def _raise_profile_safe(exc: Exception):
    """Return a safe, actionable profile error without exposing traceback/details."""
    if isinstance(exc, BackupProfileConflictError):
        _raise_safe(exc, 409)
    if isinstance(exc, (BackupError, ValueError, TypeError, OSError)):
        _raise_safe(exc, 400)
    logger.exception("Unexpected backup profile update error")
    raise HTTPException(500, "Не удалось сохранить профиль")


def _bot4vps_timezone():
    """Return the Bot4VPS host timezone reported by its operating system."""
    return local_timezone()


def _format_backup_timestamp(
    value: object,
    timezone_name: str | None = None,
    *,
    utc_offset: str | None = None,
) -> str | None:
    """Format immutable UTC data with explicit server-side timezone metadata."""
    if not isinstance(value, str) or not value:
        return None
    try:
        timestamp = parse_utc_timestamp(value)
        if utc_offset is not None:
            localized = timestamp.astimezone(timezone_from_utc_offset(utc_offset))
        elif timezone_name is not None:
            timezone_value = (
                ZoneInfo(timezone_name)
                if isinstance(timezone_name, str)
                else timezone_name
            )
            localized = timestamp.astimezone(timezone_value)
        else:
            localized = timestamp.astimezone(timezone_from_utc_offset("+00:00"))
    except (BackupError, OSError, TypeError, ValueError, ZoneInfoNotFoundError):
        return None
    return localized.strftime("%d.%m.%Y, %H:%M:%S")


def _project_catalog_display(catalog: object, bot4vps_timezone: str) -> object:
    """Add response-only display values; never mutate Catalog records.

    Все архивы Catalog создала эта установка, поэтому видимое время строится по её
    собственным часам — той же timezone, которую helpers имени архива получают
    через `local_timezone()` в `core/backup/manager.py`. `source.utc_offset` для
    отображения не используется: это часы источника, и у сервера в UTC они дают
    `10:57` там, где имя архива говорит `12-57`. Сам `source.utc_offset` остаётся
    в Catalog/Manifest как метаданные источника, а `created_at` остаётся UTC —
    проекция живёт только в ответе API.
    """
    if not isinstance(catalog, list):
        return catalog
    projected = []
    for raw in catalog:
        if not isinstance(raw, dict):
            projected.append(raw)
            continue
        item = dict(raw)
        timestamp = item.get("created_at") or item.get("published_at")
        item["display_created_at"] = _format_backup_timestamp(
            timestamp,
            bot4vps_timezone,
        )
        projected.append(item)
    return projected


def _project_imported_display(archives: object, bot4vps_timezone: str) -> object:
    """Project bounded persisted origin time without opening archive Preview."""
    if not isinstance(archives, list):
        return archives
    projected = []
    for raw in archives:
        if not isinstance(raw, dict):
            projected.append(raw)
            continue
        item = dict(raw)
        imported_display = _format_backup_timestamp(
            item.get("imported_at"),
            bot4vps_timezone,
        )
        origin = item.get("origin")
        origin_display = None
        if isinstance(origin, dict):
            origin_display = _format_backup_timestamp(
                origin.get("created_at"),
                utc_offset=origin.get("utc_offset"),
            )
        item["display_imported_at"] = imported_display
        item["display_created_at"] = origin_display or imported_display
        projected.append(item)
    return projected


def _manifest_source_display(manifest: object) -> str | None:
    """Project historical source time only from validated persisted metadata."""
    if not _manifest_valid_for_display(manifest):
        return None
    source = manifest.get("source")
    if not isinstance(source, dict):
        return None
    if source.get("kind") != manifest.get("type") or source.get("utc_offset") is None:
        return None
    return _format_backup_timestamp(
        manifest.get("created_at"),
        utc_offset=source.get("utc_offset"),
    )


def _manifest_valid_for_display(manifest: object) -> bool:
    """Do not use unvalidated optional Manifest fields as origin-time metadata."""
    if not isinstance(manifest, dict):
        return False
    try:
        validate_manifest(manifest)
    except BackupError:
        return False
    return True


class CreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(pattern="^(server|bot4vps)$")
    server_id: str | None = None
    label: str | None = Field(default=None, max_length=200)
    # Разовый пароль резервных копий для этого архива: переопределяет
    # сохранённый (enc1:). Не задан и сохранённый не настроен — архив
    # создаётся без шифрования.
    password: str | None = Field(default=None, min_length=1, max_length=256)
    # Явный выбор из модала создания: True — архив обязан быть зашифрован
    # (одноразовым паролем выше или сохранённым), False — plain-архив даже
    # при настроенном сохранённом пароле. None (по умолчанию) — авто:
    # сохранённый пароль, если настроен.
    encrypt: bool | None = None


class FilenameBody(BaseModel):
    filename: str = Field(min_length=1, max_length=255)


RestorePath = Annotated[str, Field(min_length=1, max_length=4096)]


class RestorePlanBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Корень задаётся только для чужого архива без manifest; для managed backup
    # scope берётся из Catalog, и присланный корень будет отвергнут явной ошибкой.
    target_root: str | None = Field(default=None, max_length=4096)
    selection_mode: str = Field(default="full", pattern="^(full|selected)$")
    selected_paths: list[RestorePath] = Field(
        default_factory=list,
        max_length=512,
    )
    include_directory_tree: bool = True
    # Пароль резервных копий: нужен только для зашифрованного архива (B4VE).
    # Не задан — используется сохранённый (enc1:), при его отсутствии план
    # по зашифрованному архиву вернёт ENCRYPTION_PASSWORD_REQUIRED.
    password: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_selection(self):
        if self.selection_mode == "selected" and not self.selected_paths:
            raise ValueError("Для выборочного Restore выберите хотя бы один элемент")
        if self.selection_mode == "full" and self.selected_paths:
            raise ValueError("selected_paths допустимы только для выборочного Restore")
        return self


class RestoreBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Prepare принимает пользовательские параметры плана. Apply принимает только
    # operation_id уже подготовленного server-owned контракта и явные согласия.
    target_root: str | None = Field(default=None, max_length=4096)
    restore_mode: str | None = Field(default=None, pattern="^(merge|clean)$")
    protective_backup: bool = True
    selection_mode: str = Field(default="full", pattern="^(full|selected)$")
    selected_paths: list[RestorePath] = Field(
        default_factory=list,
        max_length=512,
    )
    prepared_operation_id: str | None = Field(default=None, min_length=1, max_length=256)
    # apply=False — только подготовка плана, target не изменяется. Изменение
    # target требует apply=True вместе с confirm=True, а отказ от защитной копии —
    # ещё и confirm_without_protective=True. Отдельная валидация ниже не позволяет
    # браузеру повторно задавать target/mode/selection при применении.
    apply: bool = False
    confirm: bool = False
    confirm_without_protective: bool = False
    request_id: str | None = Field(default=None, max_length=256)
    # Пароль резервных копий (только для зашифрованных архивов). Допустим в
    # ОБЕИХ фазах: apply внутри пересобирает план и снова расшифровывает
    # архив, поэтому пароль передаётся и при применении. Может быть паролем,
    # которым архив был создан (текущий сохранённый не подошёл — смена пароля).
    password: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_restore_phase(self):
        if self.apply:
            if self.prepared_operation_id is None:
                raise ValueError("Для применения нужен prepared_operation_id")
            prepare_fields = {
                "target_root",
                "restore_mode",
                "protective_backup",
                "selection_mode",
                "selected_paths",
            }
            supplied = sorted(prepare_fields.intersection(self.model_fields_set))
            if supplied:
                raise ValueError(
                    "При применении нельзя повторно задавать параметры подготовки: "
                    + ", ".join(supplied)
                )
            return self

        if self.prepared_operation_id is not None:
            raise ValueError("prepared_operation_id используется только при применении")
        if self.restore_mode is None:
            raise ValueError("Для подготовки нужен restore_mode")
        if self.selection_mode == "selected" and not self.selected_paths:
            raise ValueError("Для выборочного Restore выберите хотя бы один элемент")
        if self.selection_mode == "full" and self.selected_paths:
            raise ValueError("selected_paths допустимы только для выборочного Restore")
        return self


class RestoreInventoryPrepareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_root: str | None = Field(default=None, min_length=1, max_length=4096)
    retry: bool = False
    rebuild: bool = False
    view: Literal["restore", "archive"] = "restore"
    # Пароль резервных копий — только для зашифрованного (B4VE) импорта без
    # готового сайдкара: состав файлов читается расшифровкой. Не задан —
    # используется сохранённый (enc1:); нет ни того, ни другого —
    # ENCRYPTION_PASSWORD_REQUIRED.
    password: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_mode(self):
        if self.retry and self.rebuild:
            raise ValueError("retry и rebuild несовместимы")
        if self.rebuild and self.view != "archive":
            raise ValueError("rebuild доступен только для archive view")
        if self.view == "archive" and self.target_root is not None:
            raise ValueError("archive view не принимает target_root")
        return self


class RestorePasswordProbeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Явный пароль (введённый в модалке) или тихая проба сохранённого на
    # сервере. Сам пароль в ответе не участвует — только факт совпадения.
    password: str | None = Field(default=None, min_length=1, max_length=256)
    use_stored: bool = False

    @model_validator(mode="after")
    def validate_probe(self):
        if not self.use_stored and not self.password:
            raise ValueError("Нужен password или use_stored")
        if self.use_stored and self.password:
            raise ValueError("password и use_stored несовместимы")
        return self


class RestoreInventoryChildrenBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_root: str | None = Field(default=None, min_length=1, max_length=4096)
    parent: str | None = Field(default=None, min_length=1, max_length=4096)
    cursor: str | None = Field(default=None, min_length=1, max_length=1024)
    limit: int | None = Field(default=None, ge=1, le=200)
    view: Literal["restore", "archive"] = "restore"

    @model_validator(mode="after")
    def validate_mode(self):
        if self.view == "archive" and self.target_root is not None:
            raise ValueError("archive view не принимает target_root")
        return self


class RestoreInventorySearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_root: str | None = Field(default=None, min_length=1, max_length=4096)
    query: str = Field(min_length=1, max_length=256)
    cursor: str | None = Field(default=None, min_length=1, max_length=1024)
    limit: int | None = Field(default=None, ge=1, le=200)


class ProfileBody(BaseModel):
    profile: dict


class BotSettingsBody(BaseModel):
    settings: dict


@router.get("")
async def overview(server_id: str | None = Query(default=None)):
    try:
        servers_data = await _run_sync(load_servers)
        servers = [
            {
                "id": s.get("id"),
                "name": s.get("name") or s.get("id"),
                "configured": server_backup_configured(s),
            }
            for s in servers_data
        ]
        backup_config = await _run_sync(get_backup_config)
        bot4vps_timezone = _bot4vps_timezone()
        filters = {"server_id": server_id} if server_id else {}
        catalog = await call("list_catalog", **filters)
        imported_archives = await call("list_imported_archives", server_id=server_id)
        operations = await call("list_operations", server_id=server_id, limit=50)
        return {
            "catalog": _project_catalog_display(catalog, bot4vps_timezone),
            "imported_archives": _project_imported_display(
                imported_archives,
                bot4vps_timezone,
            ),
            "operations": operations,
            "servers": servers,
            "server_id": server_id,
            "bot4vps": backup_config["bot4vps"],
        }
    except Exception as exc:
        _raise_safe(exc)


@router.post("/create", status_code=202)
async def create(body: CreateBody):
    try:
        if body.target == "server" and not body.server_id:
            raise BackupError(ErrorCode.INVALID_REQUEST, "Не выбран сервер")
        operation = await call(
            "submit_create",
            server_id=body.server_id if body.target == "server" else None,
            bot4vps=body.target == "bot4vps",
            label=body.label,
            password=body.password,
            encrypt=body.encrypt,
        )
        return {"operation": operation}
    except Exception as exc:
        _raise_safe(exc)


@router.get("/operations")
async def operations(server_id: str | None = None, limit: int = Query(50, ge=1, le=200)):
    try:
        return {"operations": await call("list_operations", server_id=server_id, limit=limit)}
    except Exception as exc:
        _raise_safe(exc)


@router.post("/operations/{operation_id}/cancel")
async def cancel(operation_id: str):
    try:
        return {"operation": await call("cancel_operation", operation_id)}
    except Exception as exc:
        _raise_safe(exc)


@router.delete("/operations/history")
async def clear_operation_history():
    try:
        return await call("clear_operation_history")
    except Exception as exc:
        _raise_safe(exc)


@router.patch("/imported/{entry_key}/filename")
async def rename_imported(
    entry_key: str,
    body: FilenameBody,
    server_id: str | None = Query(default=None),
):
    try:
        return await call(
            "rename_imported_archive",
            entry_key,
            body.filename,
            server_id=server_id,
        )
    except Exception as exc:
        _raise_safe(exc, 400)


@router.get("/imported/{entry_key}/preview")
async def imported_preview(
    entry_key: str,
    server_id: str | None = Query(default=None),
    include_members: bool = Query(default=True),
    diagnostics: bool = Query(default=False),
):
    """Return a bounded inventory-only descriptor for an imported archive."""
    del include_members, diagnostics
    try:
        response = await call(
            "preview_imported_archive",
            entry_key,
            server_id=server_id,
        )
        origin = response.get("origin")
        display_created_at = None
        if isinstance(origin, dict):
            display_created_at = _format_backup_timestamp(
                origin.get("created_at"),
                utc_offset=origin.get("utc_offset"),
            )
        if display_created_at is None:
            display_created_at = _format_backup_timestamp(
                response.get("imported_at"),
                _bot4vps_timezone(),
            )
        return {
            "entry_key": response["entry_key"],
            "filename": response["filename"],
            "destination": response["destination"],
            "format": response["format"],
            "bytes": response["bytes"],
            "imported_at": response.get("imported_at"),
            "display_created_at": display_created_at,
            "inventory": response["inventory"],
        }
    except Exception as exc:
        _raise_safe(exc, 404)


@router.get("/imported/{entry_key}/restore/readiness")
async def imported_restore_readiness(
    entry_key: str,
    server_id: str | None = Query(default=None),
):
    """Return bounded hints without Preview, TAR, or deep inventory reads."""
    try:
        response = await call(
            "imported_restore_readiness",
            entry_key,
            server_id=server_id,
        )
        return {
            "entry_key": response["entry_key"],
            "eligible": response["eligible"] is True,
            "requires_target_root": response["requires_target_root"] is True,
            "encrypted": response.get("encrypted") is True,
        }
    except Exception as exc:
        _raise_safe(exc, 404 if isinstance(exc, BackupError) else 400)


@router.post("/imported/{entry_key}/restore/password-probe")
async def imported_restore_password_probe(
    entry_key: str,
    body: RestorePasswordProbeBody | None = None,
    server_id: str | None = Query(default=None),
):
    """Быстрая проверка пароля зашифрованного импорта (первый кусок B4VE)."""
    try:
        request = body or RestorePasswordProbeBody(use_stored=True)
        return await call(
            "imported_restore_password_probe",
            entry_key,
            server_id=server_id,
            password=request.password,
            use_stored=request.use_stored,
        )
    except Exception as exc:
        _raise_safe(exc, 404 if isinstance(exc, BackupError) else 400)


@router.post("/imported/{entry_key}/restore/inventory/prepare")
async def prepare_imported_restore_inventory(
    entry_key: str,
    body: RestoreInventoryPrepareBody | None = None,
    server_id: str | None = Query(default=None),
):
    try:
        request = body or RestoreInventoryPrepareBody()
        result = await call(
            "prepare_imported_restore_inventory",
            entry_key,
            server_id=server_id,
            target_root=request.target_root,
            retry=request.retry,
            rebuild=request.rebuild,
            view=request.view,
            password=request.password,
        )
        return _restore_inventory_prepare_response(result)
    except Exception as exc:
        _raise_inventory_safe(exc)


@router.get("/imported/{entry_key}/restore/inventory/status")
async def imported_restore_inventory_status(
    entry_key: str,
    server_id: str | None = Query(default=None),
    target_root: str | None = Query(default=None, min_length=1, max_length=4096),
    view: Literal["restore", "archive"] = Query(default="restore"),
    job_id: str | None = Query(default=None, min_length=1, max_length=256),
):
    try:
        return await call(
            "imported_restore_inventory_status",
            entry_key,
            server_id=server_id,
            target_root=target_root,
            view=view,
            job_id=job_id,
        )
    except Exception as exc:
        _raise_inventory_safe(exc)


@router.post("/imported/{entry_key}/restore/tree/children")
async def imported_restore_inventory_children(
    entry_key: str,
    body: RestoreInventoryChildrenBody,
    server_id: str | None = Query(default=None),
):
    try:
        return await call(
            "imported_restore_inventory_children",
            entry_key,
            server_id=server_id,
            target_root=body.target_root,
            parent=body.parent,
            cursor=body.cursor,
            limit=body.limit,
            view=body.view,
        )
    except Exception as exc:
        _raise_inventory_safe(exc)


@router.post("/imported/{entry_key}/restore/tree/search")
async def search_imported_restore_inventory(
    entry_key: str,
    body: RestoreInventorySearchBody,
    server_id: str | None = Query(default=None),
):
    try:
        return await call(
            "search_imported_restore_inventory",
            entry_key,
            query=body.query,
            server_id=server_id,
            target_root=body.target_root,
            cursor=body.cursor,
            limit=body.limit,
        )
    except Exception as exc:
        _raise_inventory_safe(exc)


@router.post("/imported/{entry_key}/restore/plan")
async def imported_restore_plan(
    entry_key: str,
    body: RestorePlanBody | None = None,
    server_id: str | None = Query(default=None),
    diagnostics: bool = Query(default=False),
):
    """Построить план imported Restore без чтения или изменения target."""
    try:
        diagnostics_started = time.perf_counter() if diagnostics is True else None
        request = body or RestorePlanBody()
        call_options = {
            "server_id": server_id,
            "target_root": request.target_root,
            "selection_mode": request.selection_mode,
            "selected_paths": request.selected_paths,
            "include_directory_tree": request.include_directory_tree,
            "password": request.password,
        }
        if diagnostics_started is not None:
            call_options["include_diagnostics"] = True
        response = await call(
            "plan_imported_restore",
            entry_key,
            **call_options,
        )
        archive = response["archive"]
        plan = response.get("plan")
        result = {
            "entry_key": archive["entry_key"],
            "filename": archive.get("filename"),
            "destination": archive["destination"],
            "format": archive.get("format"),
            "directory_tree": response["directory_tree"],
            "full_restore_unavailable": response["full_restore_unavailable"],
            "policy": response["policy"],
            "preview": response.get("preview"),
            "delete": response.get("delete"),
            "notice": response.get("notice"),
        }
        if plan is None:
            result.update({
                "layout": None,
                "scope_origin": None,
                "target_root": request.target_root,
                "selection_mode": request.selection_mode,
                "selected_paths": request.selected_paths,
                "roots": [],
                "counts": None,
                "paths": [],
            })
        else:
            result.update({
                "layout": plan["layout"],
                "scope_origin": plan["origin"],
                "target_root": plan["target_root"],
                "selection_mode": plan["selection_mode"],
                "selected_paths": plan["selected_paths"],
                "roots": plan["roots"],
                "counts": plan["counts"],
                "paths": [entry["path"] for entry in plan["entries"]],
            })
        if diagnostics_started is not None:
            return _attach_restore_diagnostics(
                result,
                response,
                started=diagnostics_started,
            )
        return result
    except Exception as exc:
        missing = isinstance(exc, BackupError) and exc.code in {
            ErrorCode.ARTIFACT_NOT_FOUND.value,
            ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE.value,
        }
        _raise_safe(exc, 404 if missing else 400)


@router.post("/imported/{entry_key}/restore")
async def imported_restore(
    entry_key: str,
    body: RestoreBody,
    server_id: str | None = Query(default=None),
):
    """Запустить подготовку или подтверждённое применение imported Restore."""
    try:
        if body.apply:
            restore_options = {
                "prepared_operation_id": body.prepared_operation_id,
                "apply": True,
                "confirm": body.confirm,
                "confirm_without_protective": body.confirm_without_protective,
                "request_id": body.request_id,
                "password": body.password,
            }
        else:
            restore_options = {
                "target_root": body.target_root,
                "restore_mode": body.restore_mode,
                "protective_backup": body.protective_backup,
                "selection_mode": body.selection_mode,
                "selected_paths": body.selected_paths,
                "apply": False,
                "request_id": body.request_id,
                "password": body.password,
            }
        operation = await call(
            "submit_imported_restore",
            entry_key,
            server_id=server_id,
            **restore_options,
        )
        return {"operation": operation, "entry_key": entry_key}
    except Exception as exc:
        missing = isinstance(exc, BackupError) and exc.code in {
            ErrorCode.ARTIFACT_NOT_FOUND.value,
            ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE.value,
        }
        _raise_safe(exc, 404 if missing else 400)


@router.get("/imported/{entry_key}/download")
async def imported_download(
    entry_key: str,
    background_tasks: BackgroundTasks,
    server_id: str | None = Query(default=None),
):
    try:
        resolved = await call(
            "resolve_imported_download",
            entry_key,
            server_id=server_id,
        )
        background_tasks.add_task(resolved["permit"].release)
        media_type = "application/gzip" if resolved["format"] == "tar.gz" else "application/x-tar"
        return FileResponse(
            resolved["path"],
            filename=resolved["filename"],
            media_type=media_type,
            background=background_tasks,
        )
    except Exception as exc:
        _raise_safe(exc, 404 if isinstance(exc, BackupError) else 400)


@router.delete("/imported/{entry_key}")
async def imported_delete(
    entry_key: str,
    server_id: str | None = Query(default=None),
):
    try:
        return await call(
            "delete_imported_archive",
            entry_key,
            server_id=server_id,
        )
    except Exception as exc:
        _raise_safe(exc, 404 if isinstance(exc, BackupError) else 400)


@router.patch("/{backup_id}/filename")
async def rename_managed(
    backup_id: str,
    body: FilenameBody,
    server_id: str | None = Query(default=None),
):
    try:
        return await call(
            "rename_managed_archive",
            backup_id,
            body.filename,
            server_id=server_id,
        )
    except Exception as exc:
        _raise_safe(exc, 400)


@router.get("/{backup_id}/preview")
async def preview(backup_id: str, server_id: str | None = Query(default=None)):
    """Return a bounded inventory-only descriptor for a managed archive."""
    try:
        response = await call("preview_managed_archive", backup_id, server_id=server_id)
        return {
            "backup_id": response["backup_id"],
            "filename": response.get("filename"),
            "type": response["type"],
            "format": response["format"],
            "bytes": response["bytes"],
            "created_at": response.get("created_at"),
            "published_at": response.get("published_at"),
            "display_created_at": _format_backup_timestamp(
                response.get("created_at") or response.get("published_at"),
                _bot4vps_timezone(),
            ),
            "inventory": response["inventory"],
        }
    except Exception as exc:
        _raise_safe(exc, 404)


@router.post("/{backup_id}/restore/password-probe")
async def restore_password_probe(
    backup_id: str,
    body: RestorePasswordProbeBody | None = None,
    server_id: str | None = Query(default=None),
):
    """Быстрая проверка пароля зашифрованного managed-архива (первый кусок)."""
    try:
        request = body or RestorePasswordProbeBody(use_stored=True)
        return await call(
            "restore_password_probe",
            backup_id,
            server_id=server_id,
            password=request.password,
            use_stored=request.use_stored,
        )
    except Exception as exc:
        _raise_inventory_safe(exc)


@router.post("/{backup_id}/restore/inventory/prepare")
async def prepare_restore_inventory(
    backup_id: str,
    body: RestoreInventoryPrepareBody | None = None,
    server_id: str | None = Query(default=None),
):
    try:
        request = body or RestoreInventoryPrepareBody()
        result = await call(
            "prepare_restore_inventory",
            backup_id,
            server_id=server_id,
            target_root=request.target_root,
            retry=request.retry,
            rebuild=request.rebuild,
            view=request.view,
        )
        return _restore_inventory_prepare_response(result)
    except Exception as exc:
        _raise_inventory_safe(exc)


@router.get("/{backup_id}/restore/inventory/status")
async def restore_inventory_status(
    backup_id: str,
    server_id: str | None = Query(default=None),
    target_root: str | None = Query(default=None, min_length=1, max_length=4096),
    view: Literal["restore", "archive"] = Query(default="restore"),
    job_id: str | None = Query(default=None, min_length=1, max_length=256),
):
    try:
        return await call(
            "restore_inventory_status",
            backup_id,
            server_id=server_id,
            target_root=target_root,
            view=view,
            job_id=job_id,
        )
    except Exception as exc:
        _raise_inventory_safe(exc)


@router.post("/{backup_id}/restore/tree/children")
async def restore_inventory_children(
    backup_id: str,
    body: RestoreInventoryChildrenBody,
    server_id: str | None = Query(default=None),
):
    try:
        return await call(
            "restore_inventory_children",
            backup_id,
            server_id=server_id,
            target_root=body.target_root,
            parent=body.parent,
            cursor=body.cursor,
            limit=body.limit,
            view=body.view,
        )
    except Exception as exc:
        _raise_inventory_safe(exc)


@router.post("/{backup_id}/restore/tree/search")
async def search_restore_inventory(
    backup_id: str,
    body: RestoreInventorySearchBody,
    server_id: str | None = Query(default=None),
):
    try:
        return await call(
            "search_restore_inventory",
            backup_id,
            query=body.query,
            server_id=server_id,
            target_root=body.target_root,
            cursor=body.cursor,
            limit=body.limit,
        )
    except Exception as exc:
        _raise_inventory_safe(exc)


@router.post("/{backup_id}/restore/plan")
async def restore_plan(
    backup_id: str,
    body: RestorePlanBody | None = None,
    server_id: str | None = Query(default=None),
):
    """Показать, куда лёг бы архив. Ничего не изменяет и target не читает."""
    try:
        request = body or RestorePlanBody()
        response = await call(
            "plan_restore",
            backup_id,
            server_id=server_id,
            target_root=request.target_root,
            selection_mode=request.selection_mode,
            selected_paths=request.selected_paths,
            include_directory_tree=request.include_directory_tree,
            password=request.password,
        )
        record = response["archive"]
        plan = response.get("plan")
        result = {
            "backup_id": record["backup_id"],
            "filename": record.get("filename"),
            "type": record["type"],
            "source": record["source"],
            "directory_tree": response["directory_tree"],
            "full_restore_unavailable": response["full_restore_unavailable"],
            "policy": response["policy"],
            "preview": response.get("preview"),
            "delete": response.get("delete"),
            "notice": response.get("notice"),
        }
        if plan is None:
            result.update({
                "layout": None,
                "scope_origin": None,
                "target_root": request.target_root,
                "selection_mode": request.selection_mode,
                "selected_paths": request.selected_paths,
                "roots": [],
                "counts": None,
                "paths": [],
            })
        else:
            result.update({
                "layout": plan["layout"],
                "scope_origin": plan["origin"],
                "target_root": plan["target_root"],
                "selection_mode": plan["selection_mode"],
                "selected_paths": plan["selected_paths"],
                "roots": plan["roots"],
                "counts": plan["counts"],
                "paths": [entry["path"] for entry in plan["entries"]],
            })
        return result
    except Exception as exc:
        missing = isinstance(exc, BackupError) and exc.code in {
            ErrorCode.ARTIFACT_NOT_FOUND.value,
            ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE.value,
        }
        _raise_safe(exc, 404 if missing else 400)


@router.post("/{backup_id}/restore")
async def restore(
    backup_id: str,
    body: RestoreBody,
    server_id: str | None = Query(default=None),
):
    """Запустить Restore: подготовку плана или его применение.

    По умолчанию (apply=False) данные на target не изменяются. Применение
    выполняется только по явному apply/confirm от пользователя.

    Возвращается зарегистрированная Operation: ход выполнения виден в общем
    списке операций, отдельного механизма прогресса у Restore нет.
    """
    try:
        if body.apply:
            restore_options = {
                "prepared_operation_id": body.prepared_operation_id,
                "apply": True,
                "confirm": body.confirm,
                "confirm_without_protective": body.confirm_without_protective,
                "request_id": body.request_id,
                "password": body.password,
            }
        else:
            restore_options = {
                "target_root": body.target_root,
                "restore_mode": body.restore_mode,
                "protective_backup": body.protective_backup,
                "selection_mode": body.selection_mode,
                "selected_paths": body.selected_paths,
                "apply": False,
                "request_id": body.request_id,
                "password": body.password,
            }
        operation = await call(
            "submit_restore",
            backup_id,
            server_id=server_id,
            **restore_options,
        )
        return {"operation": operation}
    except Exception as exc:
        missing = isinstance(exc, BackupError) and exc.code in {
            ErrorCode.ARTIFACT_NOT_FOUND.value,
            ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE.value,
        }
        _raise_safe(exc, 404 if missing else 400)


@router.delete("/{backup_id}")
async def delete(
    backup_id: str,
    server_id: str | None = Query(default=None),
):
    try:
        return await call("delete", backup_id, server_id=server_id)
    except Exception as exc:
        _raise_safe(exc, 404 if isinstance(exc, BackupError) else 400)


@router.get("/{backup_id}/download")
async def download(
    backup_id: str,
    background_tasks: BackgroundTasks,
    server_id: str | None = Query(default=None),
):
    try:
        resolved = await call("resolve_download", backup_id, server_id=server_id)
        background_tasks.add_task(resolved["permit"].release)
        return FileResponse(
            resolved["path"],
            filename=resolved["filename"],
            media_type="application/gzip",
            background=background_tasks,
        )
    except Exception as exc:
        _raise_safe(exc, 404 if isinstance(exc, BackupError) else 400)


def _write_upload_chunk(output, chunk: bytes, *, written: int, limit: int | None) -> int:
    next_size = written + len(chunk)
    if limit is not None and next_size > limit:
        raise BackupError(ErrorCode.IMPORT_TOO_LARGE, "Import archive превышает допустимый размер")
    output.write(chunk)
    return next_size


@router.post("/import")
async def import_archive(
    file: UploadFile = File(...),
    password: str | None = Form(default=None, max_length=256),
    destination_server_id: str | None = Query(default=None),
    request_id: str | None = Query(default=None),
    filename: str | None = Query(default=None, max_length=255),
    replace: bool = Query(default=False),
    confirm_bot4vps_replace: bool = Query(default=False),
):
    path = await _run_sync(_temporary_import_path)
    max_archive_bytes = (await _run_sync(get_backup_config))["bot4vps"]["limits"].get("max_archive_bytes")
    limit = int(max_archive_bytes) if max_archive_bytes is not None else None
    written = 0
    output = None
    try:
        output = await asyncio.to_thread(path.open, "wb")
        while chunk := await file.read(1024 * 1024):
            written = await asyncio.to_thread(
                _write_upload_chunk,
                output,
                chunk,
                written=written,
                limit=limit,
            )
        await asyncio.to_thread(output.flush)
        await asyncio.to_thread(os.fsync, output.fileno())
        await asyncio.to_thread(output.close)
        output = None
        return await call(
            "import_backup",
            path,
            filename=filename or file.filename,
            destination_server_id=destination_server_id,
            request_id=request_id,
            replace=replace,
            confirm_bot4vps_replace=confirm_bot4vps_replace,
            password=password or None,
        )
    except Exception as exc:
        _raise_safe(exc)
    finally:
        if output is not None:
            await asyncio.to_thread(output.close)
        await asyncio.to_thread(path.unlink, missing_ok=True)
        await file.close()


@router.get("/profiles/{server_id}")
async def profile_get(server_id: str):
    try:
        return {"profile": await _run_sync(get_server_backup_profile, server_id)}
    except Exception as exc:
        _raise_safe(exc, 404)


@router.put("/profiles/{server_id}")
async def profile_put(server_id: str, body: ProfileBody):
    try:
        return {
            "profile": await save_server_backup_profile_async(server_id, body.profile)
        }
    except Exception as exc:
        _raise_profile_safe(exc)


@router.patch("/bot4vps-settings")
async def bot_settings(body: BotSettingsBody):
    try:
        config = await _run_sync(patch_backup_config, {"bot4vps": body.settings})
        return {"bot4vps": config["bot4vps"]}
    except Exception as exc:
        _raise_safe(exc)


@router.get("/source-tree/{server_id}/locate")
async def source_tree_locate(
    server_id: str,
    path: str = Query(..., min_length=1, max_length=4096),
):
    try:
        return await locate_source_async(server_id, path)
    except Exception as exc:
        _raise_safe(exc)


@router.get("/source-tree/{server_id}")
async def source_tree_browser(
    server_id: str,
    path: str = Query("/", min_length=1, max_length=4096),
    cursor: int = Query(0, ge=0, le=10_000),
    limit: int = Query(100, ge=1, le=200),
):
    try:
        return await source_tree_async(
            server_id,
            path,
            cursor=cursor,
            limit=limit,
        )
    except Exception as exc:
        _raise_safe(exc)
