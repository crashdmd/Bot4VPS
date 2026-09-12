from __future__ import annotations

import posixpath
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .ids import validate_id
from .time_utils import parse_utc_timestamp, utc_timestamp

SCHEMA_VERSION = 1
OPERATION_TYPES = {"create", "verify", "restore", "migrate", "import", "delete", "retention"}
OPERATION_MODES = {"manual", "automatic", "internal"}


class OperationStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {OperationStatus.COMPLETED.value, OperationStatus.FAILED.value, OperationStatus.CANCELLED.value}

ARTIFACT_KINDS = {"server", "bot4vps"}

# Сводка подготовленного восстановления персистится вместе с Operation, а
# реальный план бывает на десятки тысяч путей: списки в записи ограничены, полные
# количества остаются в counts, факт усечения — в truncated.
RESTORE_PLAN_SUMMARY_LIMIT = 200
RESTORE_PLAN_SUMMARY_KEYS = {"mode", "replace", "delete", "counts", "truncated"}
# ``add`` появился позже остальных полей. Ключ optional по той же причине, по
# которой optional сама сводка: schema проверяется при каждом чтении Operation,
# и обязательное поле превратило бы уже сохранённую историю в «повреждённую».
RESTORE_PLAN_SUMMARY_OPTIONAL_KEYS = {"add"}
_MAX_SUMMARY_PATH_LENGTH = 4096

RESTORE_SELECTION_VERSION = 3
RESTORE_SELECTION_MODES = {"full", "selected"}
RESTORE_SELECTION_SOURCE_KINDS = {"managed", "imported"}
RESTORE_SELECTION_MAX_PATHS = 512
RESTORE_SELECTION_ROOTS_LIMIT = RESTORE_PLAN_SUMMARY_LIMIT
RESTORE_SELECTION_KEYS = {
    "version",
    "source",
    "selection_mode",
    "selected_paths",
    "restore_mode",
    "target_root",
    "effective_plan_digest",
    "delete_set_digest",
    "protective_backup",
    "effective_roots",
    "effective_root_count",
    "effective_roots_truncated",
}
RESTORE_SELECTION_V2_KEYS = (
    RESTORE_SELECTION_KEYS - {"selected_paths"}
) | {"selected_directories"}
RESTORE_SELECTION_V1_KEYS = RESTORE_SELECTION_V2_KEYS - {"source"}


def _validate_restore_absolute_path(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or value == "/"
        or len(value) > _MAX_SUMMARY_PATH_LENGTH
        or "\x00" in value
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/")[1:])
        or posixpath.normpath(value) != value
    ):
        raise ValueError(f"Некорректный {field_name}")
    return value


def validate_restore_source(value: object) -> dict[str, Any]:
    """Validate the exact server-resolved source bound by Restore prepare."""
    if not isinstance(value, dict) or value.get("kind") not in RESTORE_SELECTION_SOURCE_KINDS:
        raise ValueError("Некорректный Restore source contract")
    if value["kind"] == "managed":
        if set(value) != {"kind", "artifact"}:
            raise ValueError("Некорректный managed Restore source")
        artifact = value["artifact"]
        if not isinstance(artifact, dict) or artifact.get("kind") not in ARTIFACT_KINDS:
            raise ValueError("Некорректный managed Restore artifact")
        artifact_kind = artifact["kind"]
        expected_keys = (
            {"kind", "backup_id", "server_id"}
            if artifact_kind == "server"
            else {"kind", "backup_id"}
        )
        if set(artifact) != expected_keys:
            raise ValueError("Некорректный managed Restore artifact")
        validate_id(artifact.get("backup_id"), field="restore.source.backup_id")
        if artifact_kind == "server":
            validate_id(artifact.get("server_id"), field="restore.source.server_id")
        return value

    if set(value) != {"kind", "entry_key", "destination"}:
        raise ValueError("Некорректный imported Restore source")
    validate_id(value.get("entry_key"), field="restore.source.entry_key")
    destination = value["destination"]
    if not isinstance(destination, dict):
        raise ValueError("Некорректный imported Restore destination")
    scope = destination.get("scope")
    expected_keys = (
        {"scope", "server_id"}
        if scope == "server"
        else {"scope"}
    )
    if scope not in {"server", "bot4vps"} or set(destination) != expected_keys:
        raise ValueError("Некорректный imported Restore destination")
    if scope == "server":
        validate_id(
            destination.get("server_id"),
            field="restore.source.destination.server_id",
        )
    return value


def validate_restore_selection(value: object) -> dict[str, Any]:
    """Validate current contracts and keep persisted v1/v2 history readable."""
    if not isinstance(value, dict):
        raise ValueError("Некорректный Restore selection contract")
    version = value.get("version")
    expected_keys = {
        RESTORE_SELECTION_VERSION: RESTORE_SELECTION_KEYS,
        2: RESTORE_SELECTION_V2_KEYS,
        1: RESTORE_SELECTION_V1_KEYS,
    }.get(version)
    if expected_keys is None:
        raise ValueError("Некорректная версия Restore selection contract")
    if set(value) != expected_keys:
        raise ValueError("Некорректный Restore selection contract")
    if version in {2, RESTORE_SELECTION_VERSION}:
        validate_restore_source(value["source"])

    selection_mode = value["selection_mode"]
    selection_key = (
        "selected_paths"
        if version == RESTORE_SELECTION_VERSION
        else "selected_directories"
    )
    selected = value[selection_key]
    if selection_mode not in RESTORE_SELECTION_MODES:
        raise ValueError("Некорректный Restore selection mode")
    if (
        not isinstance(selected, list)
        or len(selected) > RESTORE_SELECTION_MAX_PATHS
    ):
        raise ValueError("Некорректные selected paths")
    normalized_selected: list[str] = []
    for path in selected:
        normalized = _validate_restore_absolute_path(
            path,
            field_name=(
                "selected path"
                if version == RESTORE_SELECTION_VERSION
                else "selected directory"
            ),
        )
        if normalized in normalized_selected:
            raise ValueError("Дублирующийся selected path")
        normalized_selected.append(normalized)

    if version == RESTORE_SELECTION_VERSION:
        ordered = sorted(
            normalized_selected,
            key=lambda path: (len(path.split("/")), path),
        )
        if normalized_selected != ordered:
            raise ValueError("Selected paths не имеют canonical order")
        for index, path in enumerate(normalized_selected):
            if any(
                path.startswith(parent.rstrip("/") + "/")
                for parent in normalized_selected[:index]
            ):
                raise ValueError("Вложенный selected path не нормализован")
    else:
        for index, path in enumerate(normalized_selected):
            if any(
                path.startswith(parent.rstrip("/") + "/")
                for parent in normalized_selected[:index]
            ):
                raise ValueError("Вложенный selected directory не нормализован")

    if selection_mode == "full" and selected:
        raise ValueError("Full Restore не содержит selected paths")
    if selection_mode == "selected" and not selected:
        raise ValueError("Selected Restore требует path scope")

    from .restore_apply import RESTORE_MODES, RESTORE_MODE_CLEAN

    restore_mode = value["restore_mode"]
    if restore_mode not in RESTORE_MODES:
        raise ValueError("Некорректный Restore mode в selection contract")
    target_root = value["target_root"]
    if target_root is not None:
        _validate_restore_absolute_path(target_root, field_name="Restore target root")
    for key in ("effective_plan_digest", "delete_set_digest"):
        digest = value[key]
        if digest is not None and (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError(f"Некорректный Restore {key}")
    if value["effective_plan_digest"] is None:
        raise ValueError("Restore selection contract не содержит plan digest")
    if (restore_mode == RESTORE_MODE_CLEAN) != (
        value["delete_set_digest"] is not None
    ):
        raise ValueError("Restore delete-set digest не соответствует mode")
    if not isinstance(value["protective_backup"], bool):
        raise ValueError("Некорректный protective backup выбор")

    roots = value["effective_roots"]
    root_count = value["effective_root_count"]
    truncated = value["effective_roots_truncated"]
    if (
        not isinstance(roots, list)
        or not roots
        or len(roots) > RESTORE_SELECTION_ROOTS_LIMIT
        or not isinstance(root_count, int)
        or isinstance(root_count, bool)
        or root_count < len(roots)
        or not isinstance(truncated, bool)
        or truncated != (root_count > len(roots))
    ):
        raise ValueError("Некорректные effective roots Restore")
    seen_roots: set[str] = set()
    for path in roots:
        normalized = _validate_restore_absolute_path(
            path,
            field_name="effective Restore root",
        )
        if normalized in seen_roots:
            raise ValueError("Дублирующийся effective Restore root")
        seen_roots.add(normalized)
    return value


def _validate_summary_paths(value: object, *, field_name: str) -> list[str]:
    if not isinstance(value, list) or len(value) > RESTORE_PLAN_SUMMARY_LIMIT:
        raise ValueError(f"Некорректный restore plan {field_name}")
    for path in value:
        if (
            not isinstance(path, str)
            or not path
            or len(path) > _MAX_SUMMARY_PATH_LENGTH
            or any(ord(char) < 32 or ord(char) == 127 for char in path)
        ):
            raise ValueError(f"Некорректный restore plan {field_name}")
    return value


def validate_restore_plan_summary(value: object) -> dict[str, Any]:
    """Информационная сводка R2: что восстановление запишет и что удалит.

    Сводка ничего не разрешает: она не влияет на ``mutation_started`` и не
    является признаком применения. ``delete = None`` означает «режим не удаляет»
    (merge), а не «удалять нечего» — в UI это разные утверждения. ``replace`` и
    ``add`` разделены по фактическому состоянию target: первое уже существует и
    будет перезаписано, второго на сервере нет и оно появится. ``counts``
    хранит полные количества до усечения, поэтому ``truncated`` обязан совпадать
    с фактом «counts больше сохранённого списка»: иначе UI показал бы «и ещё N»
    там, где ничего не отброшено.

    Вызывается из schema-валидации Operation, поэтому нарушения — ``ValueError``,
    а не ``BackupError``: запись с некорректной сводкой считается повреждённой.
    """
    # Локальный импорт: режимы принадлежат restore_apply, а models импортируют
    # модули, которым Restore не нужен вовсе (locks, disk, catalog).
    from .restore_apply import RESTORE_MODES, RESTORE_MODE_MERGE

    keys = set(value) if isinstance(value, dict) else set()
    if not isinstance(value, dict) or not (
        RESTORE_PLAN_SUMMARY_KEYS
        <= keys
        <= RESTORE_PLAN_SUMMARY_KEYS | RESTORE_PLAN_SUMMARY_OPTIONAL_KEYS
    ):
        raise ValueError("Некорректная restore plan summary")
    if value["mode"] not in RESTORE_MODES:
        raise ValueError("Некорректный режим в restore plan summary")
    replace = _validate_summary_paths(value["replace"], field_name="replace")
    delete = value["delete"]
    if delete is not None:
        delete = _validate_summary_paths(delete, field_name="delete")
    if value["mode"] == RESTORE_MODE_MERGE and delete is not None:
        raise ValueError("Обычное восстановление не удаляет: delete должен быть null")
    counts = value["counts"]
    truncated = value["truncated"]
    # Список и его метрики появляются вместе: counts без своего списка (и наоборот)
    # означал бы, что «и ещё N» не с чем сопоставить.
    expected_meta = {"replace", "delete"} | (keys & RESTORE_PLAN_SUMMARY_OPTIONAL_KEYS)
    if (
        not isinstance(counts, dict)
        or set(counts) != expected_meta
        or not isinstance(truncated, dict)
        or set(truncated) != expected_meta
        or not all(isinstance(truncated[key], bool) for key in truncated)
    ):
        raise ValueError("Некорректная restore plan summary")
    if not isinstance(counts["replace"], int) or isinstance(counts["replace"], bool) or counts["replace"] < len(replace):
        raise ValueError("Некорректный restore plan counts.replace")
    if delete is None:
        if counts["delete"] is not None or truncated["delete"]:
            raise ValueError("Некорректный restore plan counts.delete")
    elif (
        not isinstance(counts["delete"], int)
        or isinstance(counts["delete"], bool)
        or counts["delete"] < len(delete)
    ):
        raise ValueError("Некорректный restore plan counts.delete")
    if truncated["replace"] != (counts["replace"] > len(replace)):
        raise ValueError("Некорректный restore plan truncated.replace")
    if delete is not None and truncated["delete"] != (counts["delete"] > len(delete)):
        raise ValueError("Некорректный restore plan truncated.delete")
    if "add" in keys:
        added = _validate_summary_paths(value["add"], field_name="add")
        if (
            not isinstance(counts["add"], int)
            or isinstance(counts["add"], bool)
            or counts["add"] < len(added)
        ):
            raise ValueError("Некорректный restore plan counts.add")
        if truncated["add"] != (counts["add"] > len(added)):
            raise ValueError("Некорректный restore plan truncated.add")
    return value


@dataclass(frozen=True)
class ArtifactRef:
    """Composite artifact identity: namespace + backup_id.

    Storage уже хранит артефакты в namespace (``servers/<server_id>/`` и
    ``bot4vps/``), поэтому один и тот же ``backup_id`` на разных серверах —
    законная ситуация. ArtifactRef делает эту identity явной для Catalog и
    artifact locks: конфликт возможен только при совпадении namespace +
    backup_id.
    """

    kind: str
    backup_id: str
    server_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ARTIFACT_KINDS:
            raise ValueError("Некорректный artifact kind")
        validate_id(self.backup_id, field="backup_id")
        if self.kind == "server":
            if self.server_id is None:
                raise ValueError("server artifact требует server_id")
            validate_id(self.server_id, field="server_id")
        elif self.server_id is not None:
            raise ValueError("bot4vps artifact не имеет server_id")

    @classmethod
    def for_server(cls, server_id: str, backup_id: str) -> "ArtifactRef":
        return cls(kind="server", backup_id=backup_id, server_id=server_id)

    @classmethod
    def for_bot4vps(cls, backup_id: str) -> "ArtifactRef":
        return cls(kind="bot4vps", backup_id=backup_id)

    @classmethod
    def create(cls, *, kind: str, backup_id: str, server_id: str | None = None) -> "ArtifactRef":
        if kind == "bot4vps":
            return cls.for_bot4vps(backup_id)
        if kind == "server":
            if server_id is None:
                raise ValueError("server artifact требует server_id")
            return cls.for_server(server_id, backup_id)
        raise ValueError("Некорректный artifact kind")

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "ArtifactRef":
        if not isinstance(record, dict):
            raise ValueError("Catalog record должен быть object")
        kind = record.get("type")
        backup_id = record.get("backup_id")
        if not isinstance(backup_id, str):
            raise ValueError("Некорректный backup_id")
        if kind == "bot4vps":
            return cls.for_bot4vps(backup_id)
        if kind == "server":
            source = record.get("source")
            server_id = source.get("server_id") if isinstance(source, dict) else None
            if not isinstance(server_id, str):
                raise ValueError("Некорректный source.server_id")
            return cls.for_server(server_id, backup_id)
        raise ValueError("Некорректный artifact kind")

    @property
    def namespace(self) -> str:
        if self.kind == "bot4vps":
            return "bot4vps"
        return f"servers/{self.server_id}"

    @property
    def namespace_parts(self) -> tuple[str, ...]:
        if self.kind == "bot4vps":
            return ("bot4vps",)
        return ("servers", str(self.server_id))

    def __str__(self) -> str:
        return f"{self.namespace}/{self.backup_id}"


@dataclass
class OperationRecord:
    operation_id: str
    request_id: str
    type: str
    target: dict[str, Any]
    mode: str = "manual"
    initiated_from_telegram: bool = False
    attempt: int = 1
    status: str = OperationStatus.QUEUED.value
    stage: str = "validate_request"
    source_backup_id: str | None = None
    result_backup_id: str | None = None
    parent_operation_id: str | None = None
    task_id: str | None = None
    created_at: str = field(default_factory=utc_timestamp)
    started_at: str | None = None
    updated_at: str = field(default_factory=utc_timestamp)
    finished_at: str | None = None
    heartbeat_at: str | None = None
    progress: dict[str, Any] = field(default_factory=lambda: {"processed_files": 0, "processed_bytes": 0, "estimated_total_bytes": None, "archive_bytes": 0, "percent": None})
    cancellation: dict[str, Any] = field(default_factory=lambda: {"requested": False, "requested_at": None, "allowed": True})
    restore: dict[str, Any] = field(default_factory=lambda: {"protective_backup_id": None, "mutation_started": False})
    error: dict[str, Any] | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> "OperationRecord":
        if not isinstance(self.initiated_from_telegram, bool):
            raise ValueError("Некорректный initiated_from_telegram Operation")
        if self.schema_version != 1 or self.type not in OPERATION_TYPES or self.mode not in OPERATION_MODES:
            raise ValueError("Некорректные schema/type/mode Operation")
        validate_id(self.operation_id, field="operation_id")
        for name in ("source_backup_id", "result_backup_id", "parent_operation_id", "task_id"):
            value = getattr(self, name)
            if value is not None:
                validate_id(value, field=name)
        if not isinstance(self.request_id, str) or not self.request_id or len(self.request_id) > 256:
            raise ValueError("Некорректный request_id Operation")
        if any(ord(char) < 32 or ord(char) == 127 for char in self.request_id):
            raise ValueError("Некорректный request_id Operation")
        if not isinstance(self.target, dict) or not isinstance(self.stage, str) or not self.stage:
            raise ValueError("Некорректные target/stage Operation")
        kind = self.target.get("kind")
        if self.type == "create":
            if kind == "server":
                required_target_keys = {"kind", "server_id"}
            elif kind == "bot4vps":
                required_target_keys = {"kind"}
            else:
                raise ValueError("Некорректный target.kind Operation")
            optional_target_keys: set[str] = set()
        else:
            required_target_keys = {
                "verify": {"kind", "backup_id"},
                # Restore адресует target установки, а не артефакт: у сервера это
                # namespace server_id, у Bot4VPS namespace единственный.
                "restore": (
                    {"kind", "server_id"}
                    if kind == "server"
                    else {"kind"}
                ),
                "migrate": {"kind", "server_id"},
                "import": (
                    {"kind", "server_id"}
                    if kind == "server"
                    else {"kind"}
                ),
                "delete": {"kind", "backup_id"},
                "retention": {"kind", "scope"},
            }[self.type]
            # verify/delete адресуют конкретный artifact namespace: один и тот же
            # backup_id может существовать на разных серверах, поэтому target
            # уточняется опциональным server_id. Schema остаётся закрытой.
            optional_target_keys = {
                "verify": {"server_id"},
                "delete": {"server_id"},
            }.get(self.type, set())
            allowed_kinds = {
                "verify": {"backup"},
                "restore": {"server", "bot4vps"},
                "migrate": {"server"},
                "import": {"server", "bot4vps", "unknown"},
                "delete": {"backup"},
                "retention": {"retention_scope"},
            }[self.type]
            if kind not in allowed_kinds:
                raise ValueError("Некорректный target.kind Operation")
        if not required_target_keys <= set(self.target) <= required_target_keys | optional_target_keys:
            raise ValueError("Operation target не соответствует закрытой schema")
        for key in ("backup_id", "server_id"):
            if key in self.target:
                validate_id(self.target[key], field=f"target.{key}")
        if "scope" in self.target:
            scope = self.target["scope"]
            if not isinstance(scope, str) or (
                scope != "bot4vps" and not scope.startswith("server:")
            ):
                raise ValueError("Некорректный retention scope")
        if self.type in {"verify", "delete"} and "backup_id" not in self.target:
            raise ValueError("Operation target не содержит backup_id")
        if self.type == "retention" and "scope" not in self.target:
            raise ValueError("Retention Operation не содержит scope")
        if self.status not in {item.value for item in OperationStatus} or not isinstance(self.attempt, int) or isinstance(self.attempt, bool) or self.attempt < 1:
            raise ValueError("Некорректные status/attempt Operation")
        timestamps = {"created_at": self.created_at, "updated_at": self.updated_at}
        for name in ("started_at", "finished_at", "heartbeat_at"):
            value = getattr(self, name)
            if value is not None:
                timestamps[name] = value
        parsed = {name: parse_utc_timestamp(value) for name, value in timestamps.items()}
        if parsed["updated_at"] < parsed["created_at"]:
            raise ValueError("updated_at раньше created_at")
        if "started_at" in parsed and parsed["started_at"] < parsed["created_at"]:
            raise ValueError("started_at раньше created_at")
        if "finished_at" in parsed and parsed["finished_at"] < parsed.get("started_at", parsed["created_at"]):
            raise ValueError("finished_at раньше начала Operation")
        if "heartbeat_at" in parsed and parsed["heartbeat_at"] < parsed["created_at"]:
            raise ValueError("heartbeat_at раньше created_at")
        if self.status == OperationStatus.QUEUED.value and (self.started_at is not None or self.finished_at is not None):
            raise ValueError("Queued Operation не должна иметь started/finished timestamp")
        if self.status in {
            OperationStatus.RUNNING.value,
            OperationStatus.VERIFYING.value,
            OperationStatus.COMPLETED.value,
        } and self.started_at is None:
            raise ValueError("Started Operation должна иметь started_at")
        if (self.status in TERMINAL_STATUSES) != (self.finished_at is not None):
            raise ValueError("Terminal Operation должна иметь finished_at")
        progress_keys = {"processed_files", "processed_bytes", "estimated_total_bytes", "archive_bytes", "percent"}
        if not isinstance(self.progress, dict) or set(self.progress) != progress_keys:
            raise ValueError("Некорректный progress Operation")
        for key in ("processed_files", "processed_bytes", "archive_bytes"):
            value = self.progress.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"Некорректный progress.{key}")
        estimate = self.progress.get("estimated_total_bytes")
        if estimate is not None and (not isinstance(estimate, int) or isinstance(estimate, bool) or estimate < 0):
            raise ValueError("Некорректный progress estimate")
        percent = self.progress.get("percent")
        if percent is not None and (isinstance(percent, bool) or not isinstance(percent, (int, float)) or not 0 <= percent <= 100):
            raise ValueError("Некорректный progress.percent")
        if self.status == OperationStatus.COMPLETED.value and percent != 100.0:
            raise ValueError("Completed Operation должна иметь progress=100")
        if self.status != OperationStatus.COMPLETED.value and percent == 100:
            raise ValueError("Только completed Operation может иметь progress=100")
        cancellation_keys = {"requested", "requested_at", "allowed"}
        if not isinstance(self.cancellation, dict) or set(self.cancellation) != cancellation_keys or not isinstance(self.cancellation.get("requested"), bool) or not isinstance(self.cancellation.get("allowed"), bool):
            raise ValueError("Некорректная cancellation projection")
        requested_at = self.cancellation.get("requested_at")
        if requested_at is not None:
            parse_utc_timestamp(requested_at)
        if self.cancellation.get("requested") != (requested_at is not None):
            raise ValueError("Некорректный cancellation timestamp")
        restore_keys = {"protective_backup_id", "mutation_started"}
        # `plan` — информационная сводка подготовки (R2). Ключ optional, а не
        # обязательный: записи Operation персистятся и валидируются при каждом
        # чтении, поэтому требование нового ключа объявило бы «повреждённой» всю
        # уже сохранённую историю. Schema остаётся закрытой — как у target.
        restore_optional_keys = {
            "plan",
            "selection",
            "preflight_conflicts",
            "skipped_members",
            "extraction",
            "verification",
            # Локальный self-restore: указатель на state.json раннера и его
            # входы. Запись валидируется _validate_restore_details.
            "self_restore",
        }
        if (
            not isinstance(self.restore, dict)
            or not restore_keys <= set(self.restore) <= restore_keys | restore_optional_keys
            or not isinstance(self.restore.get("mutation_started"), bool)
        ):
            raise ValueError("Некорректная restore projection")
        protective = self.restore.get("protective_backup_id")
        if protective is not None:
            validate_id(protective, field="protective_backup_id")
        plan = self.restore.get("plan")
        if plan is not None:
            validate_restore_plan_summary(plan)
        selection = self.restore.get("selection")
        if selection is not None:
            validate_restore_selection(selection)
        self._validate_restore_details()
        if self.type not in {"restore", "migrate"} and (
            protective is not None
            or plan is not None
            or selection is not None
            or self.restore["mutation_started"]
        ):
            raise ValueError("Restore projection неприменима к Operation")
        if self.error is not None:
            error_keys = set(self.error)
            if not error_keys <= {"code", "message", "retryable", "correlation_id", "details"} or not {"code", "message", "retryable", "correlation_id"} <= error_keys or not all(isinstance(self.error.get(k), str) and self.error[k] for k in ("code", "message", "correlation_id")) or not isinstance(self.error.get("retryable"), bool):
                raise ValueError("Некорректный safe error Operation")
            if "details" in self.error and not isinstance(self.error["details"], dict):
                raise ValueError("Некорректные details safe error Operation")
            if any(len(self.error[key]) > 512 or any(ord(char) < 32 and char not in "\t" for char in self.error[key]) for key in ("code", "message", "correlation_id")):
                raise ValueError("Некорректный safe error Operation")
        if self.status == OperationStatus.FAILED.value and self.error is None:
            raise ValueError("Failed Operation должна иметь safe error")
        if self.status != OperationStatus.FAILED.value and self.error is not None:
            raise ValueError("Error допустим только для failed Operation")
        if not isinstance(self.warnings, list):
            raise ValueError("Некорректные warnings Operation")
        for warning in self.warnings:
            if not isinstance(warning, dict) or set(warning) != {"code", "message"}:
                raise ValueError("Некорректный warning Operation")
            if not all(isinstance(warning[key], str) and warning[key] and len(warning[key]) <= 512 for key in ("code", "message")):
                raise ValueError("Некорректный warning Operation")
        return self

    def _validate_restore_details(self) -> None:
        """Validate optional, operation-local Restore facts without touching manifests."""
        details = self.restore
        optional = {
            key: details[key]
            for key in ("preflight_conflicts", "skipped_members", "extraction", "verification", "self_restore")
            if key in details
        }
        if self.type not in {"restore", "migrate"} and optional:
            raise ValueError("Дополнительные Restore facts неприменимы к Operation")
        advisory = details.get("preflight_conflicts")
        if advisory is not None:
            advisory_keys = {
                "at",
                "status",
                "complete",
                "truncated",
                "scanned",
                "candidate_count",
                "match_count",
                "stored_match_count",
                "matches",
                "diagnostic",
                "race_disclaimer",
            }
            if not isinstance(advisory, dict) or set(advisory) != advisory_keys:
                raise ValueError("Некорректный Restore preflight")
            status = advisory.get("status")
            if status not in {"complete", "truncated", "malformed", "unavailable"}:
                raise ValueError("Некорректный Restore preflight status")
            try:
                parse_utc_timestamp(advisory["at"])
            except (TypeError, ValueError):
                raise ValueError("Некорректное время Restore preflight") from None
            if not isinstance(advisory.get("race_disclaimer"), str) or not advisory["race_disclaimer"] or len(advisory["race_disclaimer"]) > 512:
                raise ValueError("Некорректная оговорка Restore preflight")
            for key in ("scanned", "candidate_count", "match_count", "stored_match_count"):
                value = advisory.get(key)
                if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 100000:
                    raise ValueError("Некорректный Restore preflight count")
            if advisory["scanned"] > 10000 or advisory["candidate_count"] > 10000:
                raise ValueError("Некорректный Restore preflight bound")
            complete = advisory.get("complete")
            truncated = advisory.get("truncated")
            if not isinstance(complete, bool) or not isinstance(truncated, bool):
                raise ValueError("Некорректный Restore preflight flags")
            if status == "complete" and (not complete or truncated):
                raise ValueError("Некорректное состояние complete Restore preflight")
            if status == "truncated" and (complete or not truncated):
                raise ValueError("Некорректное состояние truncated Restore preflight")
            if status in {"malformed", "unavailable"} and complete:
                raise ValueError("Некорректное состояние Restore preflight")
            if truncated != (status == "truncated"):
                raise ValueError("Некорректный Restore preflight truncated")
            matches = advisory.get("matches")
            if not isinstance(matches, list) or len(matches) > 1000:
                raise ValueError("Некорректный Restore preflight matches")
            if advisory["stored_match_count"] != len(matches) or advisory["stored_match_count"] > advisory["match_count"]:
                raise ValueError("Некорректное число сохранённых Restore matches")
            seen_matches: set[tuple[int, str]] = set()
            for match in matches:
                if not isinstance(match, dict) or set(match) != {"pid", "path", "process"}:
                    raise ValueError("Некорректный Restore process match")
                pid = match.get("pid")
                if not isinstance(pid, int) or isinstance(pid, bool) or not 0 < pid <= 2**31 - 1:
                    raise ValueError("Некорректный Restore process pid")
                path = match.get("path")
                if (
                    not isinstance(path, str)
                    or not path.startswith("/")
                    or path == "/"
                    or len(path) > 4096
                    or "\x00" in path
                    or "\\" in path
                    or any(part in {"", ".", ".."} for part in path.split("/")[1:])
                    or posixpath.normpath(path) != path
                ):
                    raise ValueError("Некорректный Restore process path")
                key = (pid, path)
                if key in seen_matches:
                    raise ValueError("Дублирующийся Restore process match")
                seen_matches.add(key)
                process = match.get("process")
                if process is not None and (
                    not isinstance(process, str)
                    or len(process) > 256
                    or any(ord(char) < 32 or ord(char) == 127 for char in process)
                ):
                    raise ValueError("Некорректная Restore process identity")
            diagnostic = advisory.get("diagnostic")
            if diagnostic is not None and (
                not isinstance(diagnostic, str)
                or len(diagnostic) > 512
                or any(ord(char) < 32 and char not in "\t" for char in diagnostic)
            ):
                raise ValueError("Некорректная диагностика Restore preflight")
            if status in {"complete", "truncated"} and diagnostic is not None:
                raise ValueError("Некорректная диагностика успешного Restore preflight")
            if status in {"malformed", "unavailable"} and not diagnostic:
                raise ValueError("Restore preflight без диагностики")
        skipped = details.get("skipped_members")
        if skipped is not None:
            if not isinstance(skipped, list) or len(skipped) > 100000:
                raise ValueError("Некорректный список пропущенных Restore members")
            for item in skipped:
                if not isinstance(item, dict):
                    raise ValueError("Некорректный Restore skipped member")
                if not {"member_name", "path", "type", "reason"} <= set(item):
                    raise ValueError("Неполный Restore skipped member")
                if not isinstance(item["member_name"], str) or len(item["member_name"]) > 4096:
                    raise ValueError("Некорректное имя Restore member")
                if not isinstance(item["path"], str) or not item["path"].startswith("/") or len(item["path"]) > 4096:
                    raise ValueError("Некорректный путь Restore member")
                if item["reason"] not in {"etxtbsy", "hardlink_dependency"}:
                    raise ValueError("Некорректная причина пропуска Restore member")
                if item.get("diagnostic") is not None and (not isinstance(item["diagnostic"], str) or len(item["diagnostic"]) > 4096):
                    raise ValueError("Некорректная диагностика Restore member")
        for key in ("extraction", "verification"):
            value = details.get(key)
            if value is not None:
                if not isinstance(value, dict) or len(value) > 32:
                    raise ValueError(f"Некорректная Restore {key} projection")
                for name, item in value.items():
                    if not isinstance(name, str) or len(name) > 64:
                        raise ValueError(f"Некорректное поле Restore {key}")
                    if isinstance(item, bool) or not isinstance(item, (str, int, float, type(None), list, dict)):
                        raise ValueError(f"Некорректное значение Restore {key}")
                    if isinstance(item, str) and len(item) > 4096:
                        raise ValueError(f"Слишком длинное значение Restore {key}")
        self_restore = details.get("self_restore")
        if self_restore is not None:
            # Указатель на состояние раннера локального restore: пути входов и
            # детерминированный job (переигрываемый идемпотентно). Глубокую
            # схему job не проверяем — она детерминирована operation_id и
            # писается ровно одним местом (apply_self_restore).
            if not isinstance(self_restore, dict) or set(self_restore) != {"state_dir", "state_file", "entries_file", "job"}:
                raise ValueError("Некорректная Restore self-restore проекция")
            for key in ("state_dir", "state_file", "entries_file"):
                path = self_restore[key]
                if not isinstance(path, str) or not path.startswith("/") or len(path) > 4096:
                    raise ValueError(f"Некорректный путь Restore self-restore: {key}")
            job = self_restore["job"]
            if not isinstance(job, dict) or not job:
                raise ValueError("Некорректный job Restore self-restore")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return deepcopy(self.__dict__)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "OperationRecord":
        if not isinstance(raw, dict):
            raise ValueError("Operation должна быть object")
        value = deepcopy(raw)
        # Origin was added after the first persisted schema.  Fill only a
        # missing field; an explicitly supplied non-bool value must not be
        # silently coerced into provenance.
        value.setdefault("initiated_from_telegram", False)
        return cls(**value).validate()


@dataclass
class CatalogRecord:
    backup_id: str
    artifact_version: int
    type: str
    purpose: str
    mode: str
    source: dict[str, Any]
    created_at: str
    published_at: str
    storage: dict[str, Any]
    archive: dict[str, Any]
    manifest: dict[str, Any]
    verification: dict[str, Any]
    operation_id: str
    label: str | None = None
    retention: dict[str, Any] = field(default_factory=lambda: {"eligible": False, "claim": None})
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.__dict__)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CatalogRecord":
        return cls(**deepcopy(raw))


@dataclass(frozen=True)
class DiskState:
    state: str
    creation_disabled: bool
    free_bytes: int
    filesystem: str
    checked_at: str
    emergency_entered_at: str | None
    last_transition_at: str
    reason: str | None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)
