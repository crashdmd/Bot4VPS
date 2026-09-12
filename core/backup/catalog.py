from __future__ import annotations

import json
import os
import time
from datetime import timedelta
from pathlib import Path

from core.install_paths import get_backup_data_path
from core.json_store import atomic_write_json

from .errors import BackupError, ErrorCode
from .ids import new_claim_id, validate_id
from .locks import LockCoordinator
from .models import ArtifactRef
from .time_utils import normalize_utc_offset, parse_utc_timestamp, utc_now, utc_timestamp
from .validation import validate_archive_filename, validate_storage_key


_CATALOG_KEYS = {
    "schema_version", "backup_id", "artifact_version", "type", "purpose",
    "mode", "filename", "source", "created_at", "published_at", "storage",
    "archive", "manifest", "verification", "operation_id", "retention",
}
_LEGACY_CATALOG_KEYS = {
    "schema_version", "backup_id", "artifact_version", "type", "purpose",
    "mode", "label", "source", "created_at", "published_at", "storage",
    "archive", "manifest", "verification", "operation_id", "retention",
}
_LEGACY_CATALOG_KEYS_V3 = {
    "schema_version", "backup_id", "artifact_version", "type", "purpose",
    "mode", "display_name", "source", "created_at", "published_at", "storage",
    "archive", "manifest", "verification", "operation_id", "retention",
}
_STORAGE_KEYS = {"backend", "key", "checksum_key"}
_SERVER_SOURCE_KEYS = {"server_id", "server_name_snapshot"}
_SERVER_SOURCE_KEYS_V5 = _SERVER_SOURCE_KEYS | {"utc_offset"}
_BOT_SOURCE_KEYS = {"install_path"}
_BOT_SOURCE_KEYS_V5 = _BOT_SOURCE_KEYS | {"utc_offset"}
_ARCHIVE_KEYS_V1 = {
    "format", "bytes", "source_bytes", "file_count", "checksum_algorithm",
    "checksum", "encrypted",
}
_ARCHIVE_KEYS_V2 = _ARCHIVE_KEYS_V1 | {"filename"}
_MANIFEST_PROJECTION_KEYS = {"version", "producer_version", "source_paths"}
_VERIFICATION_KEYS = {"status", "verified_at"}
_RETENTION_KEYS = {"eligible", "claim"}
_CLAIM_KEYS = {
    "claim_id", "run_id", "owner_operation_id", "claimed_at", "expires_at",
    "artifact_version", "state",
}


def _has_exact_keys(value: object, keys: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == keys


class CatalogStore:
    def __init__(self, data_root: str | Path | None = None, coordinator: LockCoordinator | None = None):
        self.data_root = Path(data_root or get_backup_data_path())
        self.path = self.data_root / "catalog"
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.path.chmod(0o700)
        except OSError as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Не удалось установить безопасные права Catalog storage",
            ) from exc
        self.coordinator = coordinator or LockCoordinator(data_root=self.data_root)

    def _path(self, ref: ArtifactRef) -> Path:
        """Canonical nested путь record внутри namespace artifact identity."""
        if not isinstance(ref, ArtifactRef):
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Catalog record адресуется ArtifactRef",
            )
        path = self.path
        for part in ref.namespace_parts:
            path = path / part
        return path / f"{ref.backup_id}.json"

    @staticmethod
    def _validated_backup_id(backup_id: str) -> str:
        try:
            return validate_id(backup_id, field="backup_id")
        except ValueError as exc:
            raise BackupError(ErrorCode.INVALID_REQUEST, str(exc)) from exc

    @staticmethod
    def _ref_from_path(path: Path, *, kind: str, server_id: str | None = None) -> ArtifactRef | None:
        try:
            return ArtifactRef.create(kind=kind, backup_id=path.stem, server_id=server_id)
        except ValueError:
            return None

    def _server_namespace_dirs(self) -> list[Path]:
        servers_dir = self.path / "servers"
        if not servers_dir.is_dir():
            return []
        try:
            return sorted(item for item in servers_dir.iterdir() if item.is_dir())
        except OSError as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Не удалось прочитать Catalog namespace",
            ) from exc

    def _iter_record_paths(self):
        """Обойти все namespace Catalog: (ref|None, path)."""
        bot_dir = self.path / "bot4vps"
        if bot_dir.is_dir():
            for path in sorted(bot_dir.glob("*.json")):
                if path.is_file():
                    yield self._ref_from_path(path, kind="bot4vps"), path
        for server_dir in self._server_namespace_dirs():
            for path in sorted(server_dir.glob("*.json")):
                if path.is_file():
                    yield self._ref_from_path(path, kind="server", server_id=server_dir.name), path

    def find_refs(self, backup_id: str) -> list[ArtifactRef]:
        """Все namespace, в которых опубликован данный backup_id."""
        backup_id = self._validated_backup_id(backup_id)
        found: list[ArtifactRef] = []
        if (self.path / "bot4vps" / f"{backup_id}.json").is_file():
            found.append(ArtifactRef.for_bot4vps(backup_id))
        for server_dir in self._server_namespace_dirs():
            if not (server_dir / f"{backup_id}.json").is_file():
                continue
            try:
                found.append(ArtifactRef.for_server(server_dir.name, backup_id))
            except ValueError:
                continue
        return found

    def resolve_ref(self, backup_id: str) -> ArtifactRef:
        """Восстановить ArtifactRef по одному backup_id (для frozen Web API)."""
        refs = self.find_refs(backup_id)
        if not refs:
            raise BackupError(ErrorCode.ARTIFACT_NOT_FOUND, "Опубликованный backup не найден")
        if len(refs) > 1:
            raise BackupError(
                ErrorCode.CATALOG_CONFLICT,
                "backup_id опубликован в нескольких namespace: требуется явный выбор",
            )
        return refs[0]

    def resolve(self, target: ArtifactRef | str) -> ArtifactRef:
        if isinstance(target, ArtifactRef):
            return target
        if isinstance(target, str):
            return self.resolve_ref(target)
        raise BackupError(ErrorCode.INVALID_REQUEST, "Catalog record адресуется ArtifactRef")

    def _ensure_namespace_dir(self, ref: ArtifactRef) -> Path:
        directory = self._path(ref).parent
        if directory.is_dir():
            return directory
        try:
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory.chmod(0o700)
        except OSError as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Не удалось создать Catalog namespace",
            ) from exc
        node = directory
        while True:
            parent = node.parent
            self._fsync_directory(parent)
            if parent == self.path:
                break
            node = parent
        return directory

    @staticmethod
    def _migrate_filename_layout(record: dict) -> dict:
        """Convert historical visible-name fields to the single canonical filename."""
        if record.get("schema_version") in {4, 5}:
            return record
        archive = dict(record.get("archive") or {})
        candidates = (
            record.get("display_name") if record.get("schema_version") == 3 else record.get("label"),
            archive.get("filename"),
            Path((record.get("storage") or {}).get("key", "")).name,
        )
        filename = None
        for candidate in candidates:
            try:
                filename = validate_archive_filename(candidate, error_code=ErrorCode.CATALOG_CONFLICT)
                break
            except BackupError:
                continue
        if filename is None:
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Catalog не содержит безопасного имени filename")
        updated = dict(record)
        updated.pop("label", None)
        updated.pop("display_name", None)
        updated["schema_version"] = 4
        updated["filename"] = filename
        archive.pop("filename", None)
        updated["archive"] = archive
        CatalogStore._validate(updated)
        return updated

    @staticmethod
    def _validate(record: dict) -> None:
        if not isinstance(record, dict):
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Catalog record должен быть объектом")
        schema_version = record.get("schema_version")
        valid_shape = (
            _has_exact_keys(record, _CATALOG_KEYS) and schema_version in {4, 5}
        ) or (
            _has_exact_keys(record, _LEGACY_CATALOG_KEYS) and schema_version in {1, 2}
        ) or (
            _has_exact_keys(record, _LEGACY_CATALOG_KEYS_V3) and schema_version == 3
        )
        if not valid_shape:
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Catalog record не соответствует schema v1/v2/v3/v4/v5")
        try:
            validate_id(record.get("backup_id"), field="backup_id")
            validate_id(record.get("operation_id"), field="operation_id")
            parse_utc_timestamp(record.get("created_at"))
            parse_utc_timestamp(record.get("published_at"))
        except (TypeError, ValueError) as exc:
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Catalog содержит некорректные ID/timestamps") from exc
        version = record.get("artifact_version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректный artifact_version")
        if record.get("type") not in {"server", "bot4vps"}:
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректный тип backup")
        if record.get("purpose") not in {"regular", "protective", "pre_update", "migration_source"}:
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректное назначение backup")
        if record.get("mode") not in {"manual", "automatic", "internal"}:
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректный режим backup")
        if schema_version in {4, 5}:
            try:
                validate_archive_filename(
                    record.get("filename"),
                    error_code=ErrorCode.CATALOG_CONFLICT,
                )
            except BackupError as exc:
                raise BackupError(
                    ErrorCode.CATALOG_CONFLICT,
                    "Некорректное имя filename в Catalog",
                ) from exc
        else:
            legacy_name = record.get("display_name") if schema_version == 3 else record.get("label")
            if legacy_name is not None and (
                not isinstance(legacy_name, str)
                or not legacy_name
                or any(ord(char) < 32 or ord(char) == 127 for char in legacy_name)
            ):
                raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректное legacy имя Catalog")
        storage = record.get("storage")
        if not _has_exact_keys(storage, _STORAGE_KEYS) or storage.get("backend") != "local":
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректный storage Catalog")
        try:
            validate_storage_key(storage.get("key"))
            validate_storage_key(storage.get("checksum_key"))
        except BackupError as exc:
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректный storage key Catalog") from exc
        source = record.get("source")
        if not isinstance(source, dict):
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректная source projection Catalog")
        if record.get("type") == "bot4vps":
            expected_prefix = f"bot4vps/{record['backup_id']}.tar.gz"
        else:
            try:
                validate_id(source.get("server_id"), field="source.server_id")
            except (TypeError, ValueError) as exc:
                raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректный source.server_id Catalog") from exc
            expected_prefix = f"servers/{source['server_id']}/{record['backup_id']}.tar.gz"
        if storage.get("key") != expected_prefix or storage.get("checksum_key") != expected_prefix + ".sha256":
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Storage key не соответствует canonical artifact identity")
        manifest_projection = record.get("manifest")
        source_keys = (
            (_SERVER_SOURCE_KEYS_V5 if record.get("type") == "server" else _BOT_SOURCE_KEYS_V5)
            if schema_version == 5
            else (_SERVER_SOURCE_KEYS if record.get("type") == "server" else _BOT_SOURCE_KEYS)
        )
        if (
            not _has_exact_keys(source, source_keys)
            or not _has_exact_keys(
                manifest_projection,
                _MANIFEST_PROJECTION_KEYS,
            )
        ):
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректная source/manifest projection Catalog")
        if schema_version == 5:
            try:
                normalized_offset = normalize_utc_offset(source.get("utc_offset"))
            except ValueError as exc:
                raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректный source.utc_offset Catalog") from exc
            if source.get("utc_offset") != normalized_offset:
                raise BackupError(
                    ErrorCode.CATALOG_CONFLICT,
                    "source.utc_offset Catalog должен иметь канонический формат +HH:MM",
                )
        if record.get("type") == "server":
            try:
                validate_id(source.get("server_id"), field="source.server_id")
            except (TypeError, ValueError) as exc:
                raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректный source.server_id Catalog") from exc
            server_name = source.get("server_name_snapshot")
            if not isinstance(server_name, str) or not server_name or len(server_name) > 200 or any(
                ord(char) < 32 or ord(char) == 127 for char in server_name
            ):
                raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректный server_name_snapshot Catalog")
        elif not isinstance(source.get("install_path"), str) or not source["install_path"].startswith("/"):
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректный source.install_path Catalog")
        manifest_version = manifest_projection.get("version")
        if manifest_version not in {1, 2} or not isinstance(manifest_projection.get("producer_version"), str):
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректная manifest projection Catalog")
        if schema_version == 5 and manifest_version != 2:
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Catalog v5 требует Manifest v2")
        if schema_version != 5 and manifest_version != 1:
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Manifest v2 требует Catalog v5")
        source_paths = manifest_projection.get("source_paths")
        if not isinstance(source_paths, list) or any(not isinstance(path, str) or not path.startswith("/") for path in source_paths):
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректные source_paths Catalog")
        archive = record.get("archive")
        expected_archive_keys = _ARCHIVE_KEYS_V1 if schema_version in {1, 4, 5} else _ARCHIVE_KEYS_V2
        if not _has_exact_keys(archive, expected_archive_keys):
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректная archive projection Catalog")
        if schema_version in {2, 3}:
            try:
                validate_archive_filename(
                    archive.get("filename"),
                    error_code=ErrorCode.CATALOG_CONFLICT,
                )
            except BackupError as exc:
                raise BackupError(
                    ErrorCode.CATALOG_CONFLICT,
                    "Некорректное имя archive в Catalog",
                ) from exc
        checksum = archive.get("checksum")
        if (
            archive.get("format") != "tar.gz"
            or archive.get("checksum_algorithm") != "sha256"
            or not isinstance(archive.get("encrypted"), bool)
            or not isinstance(checksum, str)
            or len(checksum) != 64
            or any(char not in "0123456789abcdef" for char in checksum)
        ):
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректная archive projection Catalog")
        for field in ("bytes", "source_bytes", "file_count"):
            value = archive.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise BackupError(ErrorCode.CATALOG_CONFLICT, f"archive.{field} должен быть неотрицательным integer")
        verification = record.get("verification")
        if not _has_exact_keys(verification, _VERIFICATION_KEYS):
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректная verification projection Catalog")
        if verification.get("status") != "verified":
            raise BackupError(ErrorCode.VERIFY_FAILED, "В Catalog можно публиковать только verified backup")
        try:
            parse_utc_timestamp(verification.get("verified_at"))
        except (TypeError, ValueError) as exc:
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректный verification timestamp") from exc
        retention = record.get("retention")
        if not _has_exact_keys(retention, _RETENTION_KEYS) or not isinstance(retention.get("eligible"), bool):
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректная retention projection")
        claim = retention.get("claim")
        if claim is not None:
            if not _has_exact_keys(claim, _CLAIM_KEYS) or claim.get("state") not in {"claimed", "deleting", "delete_failed"}:
                raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректный retention claim")
            claim_version = claim.get("artifact_version")
            if not isinstance(claim_version, int) or isinstance(claim_version, bool) or claim_version < 1:
                raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректный retention claim artifact_version")
            try:
                validate_id(claim["claim_id"], field="claim_id")
                validate_id(claim["run_id"], field="run_id")
                validate_id(claim["owner_operation_id"], field="owner_operation_id")
                parse_utc_timestamp(claim["claimed_at"])
                parse_utc_timestamp(claim["expires_at"])
            except (TypeError, ValueError) as exc:
                raise BackupError(ErrorCode.CATALOG_CONFLICT, "Некорректные retention claim IDs/timestamps") from exc

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            directory_fd = os.open(path, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Не удалось зафиксировать изменение Catalog directory",
            ) from exc

    def _read(self, path: Path, ref: ArtifactRef | None) -> dict:
        if not path.exists():
            raise BackupError(ErrorCode.ARTIFACT_NOT_FOUND, "Опубликованный backup не найден")
        try:
            with path.open("r", encoding="utf-8") as stream:
                record = json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            raise BackupError(ErrorCode.STORAGE_BACKEND_ERROR, "Catalog record повреждён") from exc
        self._validate(record)
        record = self._migrate_filename_layout(record)
        if ref is not None:
            try:
                actual = ArtifactRef.from_record(record)
            except ValueError as exc:
                raise BackupError(
                    ErrorCode.CATALOG_CONFLICT,
                    "Catalog record не содержит artifact identity",
                ) from exc
            if actual != ref:
                raise BackupError(
                    ErrorCode.CATALOG_CONFLICT,
                    "Catalog record не соответствует artifact identity",
                )
        return record

    def get(self, target: ArtifactRef | str) -> dict:
        ref = self.resolve(target)
        return self._read(self._path(ref), ref)

    def list(self, *, backup_type: str | None = None, server_id: str | None = None) -> list[dict]:
        records = []
        for ref, path in self._iter_record_paths():
            if ref is None:
                continue
            try:
                record = self._read(path, ref)
            except BackupError as exc:
                if exc.code == ErrorCode.ARTIFACT_NOT_FOUND.value:
                    continue
                raise
            if backup_type and record.get("type") != backup_type:
                continue
            if server_id and record.get("source", {}).get("server_id") != server_id:
                continue
            records.append(record)
        return sorted(records, key=lambda item: (item.get("created_at", ""), item.get("backup_id", "")), reverse=True)

    def exists(self, target: ArtifactRef | str) -> bool:
        if isinstance(target, ArtifactRef):
            return self._path(target).exists()
        return bool(self.find_refs(target))

    def commit_published(self, record: dict, *, lock_held: bool = False) -> dict:
        self._validate(record)
        try:
            ref = ArtifactRef.from_record(record)
        except ValueError as exc:
            raise BackupError(
                ErrorCode.CATALOG_CONFLICT,
                "Catalog record не содержит artifact identity",
            ) from exc
        path = self._path(ref)

        def commit() -> None:
            if path.exists():
                raise BackupError(ErrorCode.ARTIFACT_ALREADY_EXISTS, "Backup ID уже опубликован")
            self._ensure_namespace_dir(ref)
            atomic_write_json(path, record)

        if lock_held:
            commit()
        else:
            with self.coordinator.catalog_lock():
                commit()
        return dict(record)

    def update_filename(
        self,
        target: ArtifactRef | str,
        filename: str,
    ) -> dict:
        """Atomically change only the canonical visible archive filename."""
        filename = validate_archive_filename(filename)
        with self.coordinator.catalog_lock():
            ref = self.resolve(target)
            record = self.get(ref)
            if record.get("retention", {}).get("claim") is not None:
                raise BackupError(
                    ErrorCode.CATALOG_CONFLICT,
                    "Catalog record занят destructive operation",
                    retryable=True,
                )
            updated = dict(record)
            if updated.get("schema_version") != 5:
                updated["schema_version"] = 4
            updated.pop("label", None)
            updated.pop("display_name", None)
            updated["filename"] = filename
            archive = dict(updated.get("archive") or {})
            archive.pop("filename", None)
            updated["archive"] = archive
            self._validate(updated)
            atomic_write_json(self._path(ref), updated)
            self._fsync_directory(self._path(ref).parent)
            return updated

    def update_verification(self, target: ArtifactRef | str, projection: dict, expected_version: int) -> dict:
        with self.coordinator.catalog_lock():
            ref = self.resolve(target)
            record = self.get(ref)
            if record.get("retention", {}).get("claim") is not None:
                raise BackupError(
                    ErrorCode.CATALOG_CONFLICT,
                    "Catalog record занят destructive operation",
                    retryable=True,
                )
            if int(record.get("artifact_version", 0)) != int(expected_version):
                raise BackupError(ErrorCode.CATALOG_CONFLICT, "Catalog version изменилась", retryable=True)
            record["verification"] = dict(projection)
            record["artifact_version"] = expected_version + 1
            self._validate(record)
            atomic_write_json(self._path(ref), record)
            return record

    def remove_after_delete(self, target: ArtifactRef | str, expected_version: int, *, lock_held: bool = False) -> None:
        def remove() -> None:
            ref = self.resolve(target)
            record = self.get(ref)
            if int(record.get("artifact_version", 0)) != int(expected_version):
                raise BackupError(ErrorCode.CATALOG_CONFLICT, "Catalog version изменилась", retryable=True)
            path = self._path(ref)
            path.unlink()
            self._fsync_directory(path.parent)

        if lock_held:
            remove()
        else:
            with self.coordinator.catalog_lock():
                remove()

    def isolate(self, target: ArtifactRef | str, reason: str, *, lock_held: bool = False) -> str:
        """Убрать record из active Catalog до восстановления/ручного разбора."""
        ref = self.resolve(target)
        source = self._path(ref)
        backup_id = ref.backup_id
        invalid_dir = self.path / "invalid"
        invalid_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        invalid_dir.chmod(0o700)
        self._fsync_directory(self.path)

        def move() -> str:
            if not source.exists():
                return ""
            destination = invalid_dir / f"{backup_id}.invalid-{time.time_ns()}.json"
            os.replace(source, destination)
            self._fsync_directory(invalid_dir)
            self._fsync_directory(source.parent)
            return str(destination)

        if lock_held:
            return move()
        with self.coordinator.catalog_lock():
            return move()

    def isolate_path(self, source: Path, reason: str) -> str:
        """Изолировать Catalog JSON с именем, не являющимся valid backup_id."""
        try:
            source = source.resolve(strict=True)
            source.relative_to(self.path.resolve())
        except (OSError, ValueError) as exc:
            raise BackupError(ErrorCode.INVALID_REQUEST, "Некорректный путь Catalog record") from exc
        invalid_dir = self.path / "invalid"
        invalid_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        invalid_dir.chmod(0o700)
        self._fsync_directory(self.path)
        with self.coordinator.catalog_lock():
            if not source.is_file():
                return ""
            destination = invalid_dir / f"invalid-{time.time_ns()}.json"
            os.replace(source, destination)
            self._fsync_directory(invalid_dir)
            self._fsync_directory(self.path)
            return str(destination)

    def scan_invalid(self) -> list[dict]:
        """Проверить active records, не прерывая scan на одном повреждённом файле."""
        invalid = []
        candidates: list[tuple[ArtifactRef | None, Path]] = list(self._iter_record_paths())
        # Файлы в корне Catalog не принадлежат ни одному namespace: это либо
        # мусор, либо не перенесённый flat record. Их identity недоступна,
        # поэтому изоляция выполняется по пути.
        candidates.extend((None, path) for path in sorted(self.path.glob("*.json")) if path.is_file())
        for ref, path in candidates:
            try:
                with path.open("r", encoding="utf-8") as stream:
                    record = json.load(stream)
                self._validate(record)
                if ref is None:
                    raise BackupError(
                        ErrorCode.CATALOG_CONFLICT,
                        "Catalog record вне namespace artifact identity",
                    )
                if ArtifactRef.from_record(record) != ref:
                    raise BackupError(
                        ErrorCode.CATALOG_CONFLICT,
                        "Catalog record не соответствует artifact identity",
                    )
            except (BackupError, OSError, json.JSONDecodeError, UnicodeError, TypeError, ValueError):
                invalid.append({"backup_id": path.stem, "path": path, "ref": ref})
        return invalid

    def has_flat_records(self) -> bool:
        """Есть ли не перенесённые записи pre-namespace layout."""
        return any(path.is_file() for path in self.path.glob("*.json"))

    def migrate_flat_layout(self, *, lock_held: bool = False) -> dict:
        """Идемпотентно перенести flat records в namespace layout.

        Физический Storage не меняется. Исходный файл удаляется только после
        успешной записи нового; при расхождении содержимого record остаётся на
        месте и попадает в conflicts.
        """
        def migrate() -> dict:
            result: dict[str, list[str]] = {"migrated": [], "skipped": [], "conflicts": []}
            for path in sorted(self.path.glob("*.json")):
                if not path.is_file():
                    continue
                try:
                    with path.open("r", encoding="utf-8") as stream:
                        record = json.load(stream)
                except (OSError, json.JSONDecodeError, UnicodeError):
                    result["skipped"].append(path.name)
                    continue
                try:
                    self._validate(record)
                    ref = ArtifactRef.from_record(record)
                except (BackupError, TypeError, ValueError):
                    result["skipped"].append(path.name)
                    continue
                if path.stem != ref.backup_id:
                    result["skipped"].append(path.name)
                    continue
                destination = self._path(ref)
                if destination.exists():
                    try:
                        with destination.open("r", encoding="utf-8") as stream:
                            existing = json.load(stream)
                    except (OSError, json.JSONDecodeError, UnicodeError):
                        existing = None
                    if existing == record:
                        path.unlink()
                        self._fsync_directory(self.path)
                        result["migrated"].append(str(ref))
                    else:
                        result["conflicts"].append(str(ref))
                    continue
                self._ensure_namespace_dir(ref)
                atomic_write_json(destination, record)
                if not destination.exists():
                    result["conflicts"].append(str(ref))
                    continue
                path.unlink()
                self._fsync_directory(self.path)
                result["migrated"].append(str(ref))
            return result

        if lock_held:
            return migrate()
        with self.coordinator.catalog_lock():
            return migrate()

    def migrate_filename_layout(self, *, lock_held: bool = False) -> dict:
        """Idempotently persist the one-filename schema for active records."""
        def migrate() -> dict:
            result: dict[str, list[str]] = {"migrated": [], "skipped": []}
            for ref, path in self._iter_record_paths():
                if ref is None:
                    continue
                try:
                    with path.open("r", encoding="utf-8") as stream:
                        record = json.load(stream)
                    self._validate(record)
                    updated = self._migrate_filename_layout(record)
                    if ArtifactRef.from_record(updated) != ref:
                        raise ValueError("artifact identity mismatch")
                except (BackupError, OSError, json.JSONDecodeError, UnicodeError, TypeError, ValueError):
                    result["skipped"].append(str(ref))
                    continue
                if updated == record:
                    continue
                atomic_write_json(path, updated)
                self._fsync_directory(path.parent)
                result["migrated"].append(str(ref))
            return result

        if lock_held:
            return migrate()
        with self.coordinator.catalog_lock():
            return migrate()

    def begin_delete(
        self,
        target: ArtifactRef | str,
        *,
        owner_operation_id: str,
        ttl_seconds: int,
    ) -> dict:
        """Атомарно зафиксировать delete intent до filesystem I/O."""
        from .ids import new_claim_id, new_run_id
        from .time_utils import utc_now, utc_timestamp
        with self.coordinator.catalog_lock():
            ref = self.resolve(target)
            record = self.get(ref)
            retention = record.setdefault("retention", {})
            claim = retention.get("claim")
            if claim is not None:
                if claim.get("state") != "delete_failed":
                    raise BackupError(ErrorCode.ARTIFACT_IN_USE, "Backup уже занят retention/delete операцией", retryable=True)
                retention["claim"] = None
            now = utc_now()
            delete_claim = {
                "claim_id": new_claim_id(),
                "run_id": new_run_id(),
                "owner_operation_id": owner_operation_id,
                "claimed_at": utc_timestamp(now),
                "expires_at": utc_timestamp(now + timedelta(seconds=max(1, int(ttl_seconds)))),
                "artifact_version": int(record["artifact_version"]),
                "state": "deleting",
            }
            retention["claim"] = delete_claim
            record["artifact_version"] = int(record["artifact_version"]) + 1
            self._validate(record)
            atomic_write_json(self._path(ref), record)
            return record

    def finish_delete(
        self,
        target: ArtifactRef | str,
        *,
        expected_version: int,
        expected_claim_id: str,
        lock_held: bool = False,
    ) -> None:
        def finish() -> None:
            ref = self.resolve(target)
            record = self.get(ref)
            claim = record.get("retention", {}).get("claim") or {}
            if int(record.get("artifact_version", 0)) != int(expected_version) or claim.get("claim_id") != expected_claim_id or claim.get("state") != "deleting":
                raise BackupError(ErrorCode.CATALOG_CONFLICT, "Delete intent конфликтует", retryable=True)
            path = self._path(ref)
            path.unlink()
            self._fsync_directory(path.parent)

        if lock_held:
            finish()
        else:
            with self.coordinator.catalog_lock():
                finish()

    def mark_delete_failed(self, target: ArtifactRef | str, *, expected_version: int, expected_claim_id: str) -> dict:
        with self.coordinator.catalog_lock():
            ref = self.resolve(target)
            record = self.get(ref)
            claim = record.get("retention", {}).get("claim") or {}
            if int(record.get("artifact_version", 0)) != int(expected_version) or claim.get("claim_id") != expected_claim_id:
                raise BackupError(ErrorCode.CATALOG_CONFLICT, "Delete intent конфликтует", retryable=True)
            claim["state"] = "delete_failed"
            record["retention"]["claim"] = claim
            record["artifact_version"] = int(expected_version) + 1
            self._validate(record)
            atomic_write_json(self._path(ref), record)
            return record

    def claim_retention_scope(
        self,
        *,
        scope: str,
        keep_last: int,
        run_id: str,
        owner_operation_id: str,
        ttl_seconds: int,
    ) -> list[dict]:
        """Выбрать и claim кандидатов одним Catalog snapshot."""
        if not isinstance(keep_last, int) or isinstance(keep_last, bool) or keep_last < 1:
            raise BackupError(ErrorCode.INVALID_REQUEST, "keep_last должен быть integer >= 1")
        if scope == "bot4vps":
            def in_scope(record: dict) -> bool:
                return record.get("type") == "bot4vps"
        elif scope.startswith("server:"):
            server_id = scope.split(":", 1)[1]
            try:
                validate_id(server_id, field="server_id")
            except ValueError as exc:
                raise BackupError(ErrorCode.INVALID_REQUEST, str(exc)) from exc

            def in_scope(record: dict) -> bool:
                return record.get("type") == "server" and record.get("source", {}).get("server_id") == server_id
        else:
            raise BackupError(ErrorCode.INVALID_REQUEST, "Некорректный retention scope")
        try:
            validate_id(run_id, field="run_id")
            validate_id(owner_operation_id, field="owner_operation_id")
        except ValueError as exc:
            raise BackupError(ErrorCode.INVALID_REQUEST, str(exc)) from exc

        now = utc_now()
        with self.coordinator.retention_scope_lock(scope):
            with self.coordinator.catalog_lock():
                eligible = [
                    record for record in self.list()
                    if in_scope(record)
                    and record.get("mode") == "automatic"
                    and record.get("purpose") == "regular"
                    and record.get("verification", {}).get("status") == "verified"
                    and record.get("retention", {}).get("eligible") is True
                    and record.get("retention", {}).get("claim") is None
                ]
                eligible.sort(key=lambda record: (record["created_at"], record["backup_id"]))
                candidates = eligible[:-keep_last] if keep_last else eligible
                claimed = []
                for record in candidates:
                    version = int(record["artifact_version"])
                    claim = {
                        "claim_id": new_claim_id(),
                        "run_id": run_id,
                        "owner_operation_id": owner_operation_id,
                        "claimed_at": utc_timestamp(now),
                        "expires_at": utc_timestamp(now + timedelta(seconds=max(1, int(ttl_seconds)))),
                        "artifact_version": version,
                        "state": "claimed",
                    }
                    claimed.append(self.claim(ArtifactRef.from_record(record), claim, version, lock_held=True))
                return claimed

    def begin_claimed_delete(
        self,
        target: ArtifactRef | str,
        *,
        expected_version: int,
        expected_claim_id: str,
        owner_operation_id: str,
        lock_held: bool = False,
    ) -> dict:
        """CAS-переход retention claim: claimed → deleting."""
        def update() -> dict:
            ref = self.resolve(target)
            record = self.get(ref)
            claim = record.get("retention", {}).get("claim") or {}
            if (
                int(record.get("artifact_version", 0)) != int(expected_version)
                or claim.get("claim_id") != expected_claim_id
                or claim.get("owner_operation_id") != owner_operation_id
                or claim.get("state") != "claimed"
                or claim.get("artifact_version") != expected_version - 1
                or record.get("mode") != "automatic"
                or record.get("purpose") != "regular"
                or record.get("retention", {}).get("eligible") is not True
            ):
                raise BackupError(ErrorCode.RETENTION_CLAIM_CONFLICT, "Retention delete claim конфликтует", retryable=True)
            claim["state"] = "deleting"
            record["retention"]["claim"] = claim
            record["artifact_version"] = expected_version + 1
            self._validate(record)
            atomic_write_json(self._path(ref), record)
            return record

        if lock_held:
            return update()
        with self.coordinator.catalog_lock():
            return update()

    def claim(self, target: ArtifactRef | str, claim: dict, expected_version: int, *, lock_held: bool = False) -> dict:
        def update() -> dict:
            ref = self.resolve(target)
            record = self.get(ref)
            if int(record.get("artifact_version", 0)) != int(expected_version) or record.get("retention", {}).get("claim"):
                raise BackupError(ErrorCode.RETENTION_CLAIM_CONFLICT, "Retention claim конфликтует", retryable=True)
            record.setdefault("retention", {})["claim"] = dict(claim)
            record["artifact_version"] = expected_version + 1
            self._validate(record)
            atomic_write_json(self._path(ref), record)
            return record

        if lock_held:
            return update()
        with self.coordinator.catalog_lock():
            return update()

    def release_claim(
        self,
        target: ArtifactRef | str,
        *,
        expected_version: int,
        expected_claim_id: str,
        lock_held: bool = False,
    ) -> dict:
        def update() -> dict:
            ref = self.resolve(target)
            record = self.get(ref)
            claim = record.get("retention", {}).get("claim") or {}
            if (
                int(record.get("artifact_version", 0)) != int(expected_version)
                or claim.get("claim_id") != expected_claim_id
            ):
                raise BackupError(
                    ErrorCode.RETENTION_CLAIM_CONFLICT,
                    "Retention claim конфликтует",
                    retryable=True,
                )
            record.setdefault("retention", {})["claim"] = None
            record["artifact_version"] = expected_version + 1
            self._validate(record)
            atomic_write_json(self._path(ref), record)
            return record

        if lock_held:
            return update()
        with self.coordinator.catalog_lock():
            return update()
