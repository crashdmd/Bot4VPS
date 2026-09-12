from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import json
import os
import posixpath
import shlex
import shutil
import stat
import tarfile
import tempfile
import threading
import time
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from uuid import uuid4

from core.install_paths import get_backup_data_path, resolve_storage_root
from core.storage import find_server
from core.version import APP_VERSION

from core.config import get_stored_backup_password
from core.event_service import create_event, dispatch_notifiers
from core.event_types import EventLevel, EventReason, EventType
from core.secretbox import SecretBoxError

from .archive_crypto import (
    MAX_PASSWORD_LEN,
    decrypt_file,
    encrypt_in_place,
    is_encrypted_file,
    verify_password,
)
from .bot4vps_sources import iter_source_entries, resolve_bot4vps_sources

from .catalog import CatalogStore
from .disk import DiskMonitor
from .errors import BackupError, ErrorCode
from .ids import new_backup_id, new_operation_id, new_run_id
from .inventory import (
    LAYOUT_FIXED_ABSOLUTE,
    LAYOUT_RELATIVE_TARGET_ROOT,
    archive_inventory_policy_summary,
    archive_inventory_query_cache,
    build_archive_inventory,
    expand_archive_inventory_members,
    project_archive_inventory,
    project_archive_inventory_view,
    query_archive_inventory_children,
    query_archive_inventory_search,
    query_archive_inventory_view_children,
)
from .inventory_indexer import (
    INVENTORY_PRIORITY_INTERACTIVE,
    ArchiveInventoryIndexer,
)
from core.json_store import atomic_write_json
from .locks import LockCoordinator
from .manifest import (
    _member_type,
    _validate_managed_members,
    inspect_archive,
    validate_archive_physical,
    validate_manifest,
    verify_archive,
    verify_archive_with_members,
)
from .models import (
    ArtifactRef,
    OperationStatus,
    RESTORE_SELECTION_ROOTS_LIMIT,
    RESTORE_SELECTION_VERSION,
    TERMINAL_STATUSES,
    validate_restore_selection,
)
from .operations import OperationStore
from .record_store import JsonRecordDirectory
from .restore_apply import (
    RESTORE_MODE_CLEAN,
    RESTORE_MODE_MERGE,
    assert_free_space,
    assert_free_space_local,
    assert_no_symlink_components,
    assert_no_symlink_components_local,
    assert_no_symlink_ancestors,
    assert_no_symlink_ancestors_local,
    assert_restore_capability,
    clear_stale_remote_archives,
    create_restore_member_list,
    delete_target_paths,
    discard_remote_restore_inputs,
    existing_archive_paths,
    existing_local_paths,
    existing_target_paths,
    extract_restore_archive,
    filter_self_restore_live_state,
    normalize_restore_mode,
    preflight_restore_processes,
    planned_removals,
    protective_sources,
    read_target_inventory,
    remote_archive_path,
    remote_member_list_path,
    restore_plan_summary,
    restore_space_requirements,
    restore_space_requirements_local,
    upload_restore_archive,
    upload_restore_member_list,
    verify_applied_restore,
)
from .self_restore import (
    apply_self_restore,
    enrich_operation,
    prepare_warnings_for,
    reconcile_self_restores,
)
from .restore_plan import (
    SELECTION_MODE_FULL,
    _build_restore_planning_context,
    assert_online_restore_scope_safe,
    build_effective_restore_plan,
    build_preview_tree,
    build_restore_directory_tree,
    build_restore_plan,
    effective_restore_plan_digest,
    filtered_restore_verification_plan,
    normalize_selection_mode,
    restore_delete_set_digest,
)
from .source_selection import (
    SourceSelectionError,
    build_privileged_source_probe,
    parse_privileged_source_probe,
)
from .storage import LEGACY_ARCHIVE_INVENTORY_SCHEMA_VERSION, LocalBackupStorage
from .time_utils import (
    local_timezone,
    local_utc_offset,
    normalize_utc_offset,
    parse_utc_timestamp,
    utc_now,
    utc_timestamp,
)
from .validation import (
    MAX_ARCHIVE_FILENAME_LENGTH,
    normalize_backup_config,
    normalize_notifications,
    normalize_server_profile,
    validate_archive_filename,
)


# Видимое имя защитной копии перед Restore: ``<имя установки>_before.restore_<дата>``.
# Дата — видимая метка момента создания, а не разрешение копиям накапливаться: у
# target всегда ровно одна защитная копия, прежняя удаляется после публикации новой.
PROTECTIVE_FILENAME_INFIX = "_before.restore_"
PROTECTIVE_DATE_LENGTH = len("ДД.ММ.ГГГГ")


def _joined_reasons(prefix: str, reasons, *, limit: int = 480) -> str:
    """Собрать одну строку сообщения из перечня причин, не потеряв конкретику.

    Причины перечисляются в самом safe_message, а не только в details: иначе
    пользователь увидит «backup не удался» и останется без единого имени
    проблемного источника. Длина обрезается здесь: сообщение об ошибке
    операции ограничено 512 символами и не допускает переводов строки.
    """
    body = "; ".join(str(reason).replace("\n", " ").strip() for reason in reasons if str(reason).strip())
    message = f"{prefix}: {body}" if body else prefix
    return message if len(message) <= limit else message[: limit - 1] + "…"


def _probe_privileged_source_kind(exec_sudo, ssh, server: dict, path: str) -> str:
    command = build_privileged_source_probe(path)
    code, stdout, stderr = exec_sudo(ssh, server, command, timeout=30)
    return parse_privileged_source_probe(path, code, stdout, stderr)


def _streamed_member_relative_name(name: str) -> str:
    """Снять ровно префикс './' у члена удалённого tar, не срезая символы.

    Каталог стримится как ``tar -C <source> .``, поэтому имена приходят как
    ``./x``. ``str.lstrip("./")`` снимал бы *набор* символов и калечил первый
    компонент: ``./.env`` → ``env``, ``./..data`` → ``data``.
    """
    while name.startswith("./"):
        name = name[2:]
    return "" if name in {"", "."} else name


def _payload_prefix_for_source(source_path: str, *, is_directory: bool) -> str:
    """Payload-префикс, к которому приклеиваются имена членов source-архива.

    Для каталога члены относительны самого каталога, поэтому префикс — сам
    source path. Для файла tar вызывается как ``-C <parent> <basename>``, то
    есть единственный член уже несёт basename, и префиксом должен быть
    родительский каталог — иначе получается ``payload/etc/app.conf/app.conf``.
    """
    if is_directory:
        return "payload/" + source_path.lstrip("/")
    parent = posixpath.dirname(source_path.rstrip("/")).lstrip("/")
    return "payload/" + parent if parent else "payload"


def _absolute_member_path(payload_prefix: str, rel: str) -> str:
    """Путь члена на сервере, восстановленный из его же payload-префикса.

    Сообщения об объектах должны называть путь так, как его видит пользователь на
    сервере, а не имя внутри архива. Раскладка берётся из того же префикса, что и
    имя члена, чтобы не появилась вторая реализация того же соответствия.
    """
    inner = payload_prefix[len("payload"):].lstrip("/")
    return "/" + (f"{inner}/{rel}" if inner else rel)


# Типы членов, которые archive v1 не переносит. FIFO, устройства и неизвестный
# typeflag нельзя ни записать осмысленно, ни восстановить: содержимого у них нет,
# а смысл целиком в inode на конкретной системе. Unix-сокеты сюда не попадают —
# их не архивирует сам tar, сообщая ``socket ignored``, и это уже разобрано
# классификацией потока в :func:`core.ssh.classify_tar_stream`.
_UNSUPPORTED_MEMBER_LABELS = {
    "fifo": "FIFO",
    "character_device": "символьное устройство",
    "block_device": "блочное устройство",
    "other": "неподдерживаемый тип объекта",
}


def _plan_source_members(source_archive, *, on_member=None) -> dict:
    """Решить судьбу каждого члена source-архива ДО записи manifest.

    Один проход по членам одного потокового tar; повторное чтение большого gzip
    потока удвоило бы работу. Возвращает:

    * ``skip`` — имена, которые repack не переносит;
    * ``flatten`` — ``имя → цель`` для жёсткой ссылки на symlink-член: такой член
      пишется обычной символьной ссылкой с той же целью. Оставить его жёсткой
      ссылкой нельзя: сквозь второе имя символьной ссылки можно писать за пределы
      корня, а cross-member инвариант архива смотрит только на symlink-члены;
    * ``unsupported`` — ``(подпись, имя)`` объектов, из-за которых выбранный
      source должен быть отклонён без публикации неполного payload;
    * ``hardlinks`` — попадает ли в архив хотя бы один hardlink-член.

    ``on_member(member, member_type, rel)`` вызывается для каждого члена: учёт
    размеров, лимитов и проверка диска остаются на стороне вызывающего.
    """
    skip: set[str] = set()
    flatten: dict[str, str] = {}
    unsupported: list[tuple[str, str]] = []
    symlinks: dict[str, str] = {}
    files: set[str] = set()
    has_hardlinks = False
    for member in source_archive:
        rel = _streamed_member_relative_name(member.name)
        if not rel:
            continue
        member_type = _member_type(member)
        if on_member is not None:
            on_member(member, member_type, rel)
        if member_type in _UNSUPPORTED_MEMBER_LABELS:
            skip.add(rel)
            unsupported.append((_UNSUPPORTED_MEMBER_LABELS[member_type], rel))
        elif member_type == "file":
            files.add(rel)
        elif member_type == "symlink":
            symlinks[rel] = member.linkname
        elif member_type == "hardlink":
            target = _streamed_member_relative_name(str(member.linkname or ""))
            if target in files:
                has_hardlinks = True
            elif target in symlinks:
                flatten[rel] = symlinks[target]
            elif target in skip:
                # Второе имя пропущенного спец. файла. Оставить ссылку значило бы
                # оставить в архиве ссылку без цели и уронить верификацию — то
                # есть весь бэкап — из-за объекта, который и так не переносится.
                skip.add(rel)
                unsupported.append(("второе имя пропущенного объекта", rel))
            else:
                # tar не выдаёт ссылку раньше её цели, поэтому сюда попадает лишь
                # повреждённый или чужой поток. Пропустить безопаснее, чем
                # записать ссылку в никуда: распаковка сорвалась бы на target.
                skip.add(rel)
                unsupported.append(("жёсткая ссылка без цели в архиве", rel))
    return {
        "skip": skip,
        "flatten": flatten,
        "unsupported": unsupported,
        "hardlinks": has_hardlinks,
    }


class _CountingReader:
    """Count bytes when tarfile actually consumes a regular-file payload."""

    def __init__(self, stream, on_read, *, before_read=None):
        self._stream = stream
        self._on_read = on_read
        self._before_read = before_read

    def read(self, size: int = -1) -> bytes:
        if self._before_read is not None:
            self._before_read()
        chunk = self._stream.read(size)
        if chunk:
            self._on_read(len(chunk))
        return chunk


class _ArchiveProgress:
    """Persist truthful create progress without inventing boundary values."""

    _MAX_PERSIST_INTERVAL = 0.75

    def __init__(self, operations: OperationStore, operation_id: str, total_bytes: int):
        self._operations = operations
        self._operation_id = operation_id
        self.total_bytes = max(0, int(total_bytes))
        self.processed_bytes = 0
        self.processed_files = 0
        self._operations.update_progress(
            operation_id,
            processed_files=0,
            processed_bytes=0,
            estimated_total_bytes=self.total_bytes,
            percent=None,
        )
        self._last_persisted_at = time.monotonic()

    def reader(self, stream, *, before_read=None) -> _CountingReader:
        return _CountingReader(stream, self.consume, before_read=before_read)

    def consume(self, count: int) -> None:
        self.processed_bytes += max(0, int(count))
        # Source discovery supplies the immutable total. Never report more than
        # that total if a malformed tar member yields unexpected extra bytes.
        self.processed_bytes = min(self.processed_bytes, self.total_bytes)
        self._persist()

    def finish_file(self) -> None:
        self.processed_files += 1
        self._persist()

    def finish(self, *, archive_bytes: int) -> None:
        values = {
            "processed_files": self.processed_files,
            "processed_bytes": self.processed_bytes,
            "estimated_total_bytes": self.total_bytes,
            "archive_bytes": int(archive_bytes),
        }
        # At the exact source boundary the mathematical value is 100. Only the
        # terminal COMPLETED transition may persist 100, so retain the last real
        # sub-100 value until that transition.
        if self.total_bytes and self.processed_bytes < self.total_bytes:
            values["percent"] = self.processed_bytes * 100.0 / self.total_bytes
        self._operations.update_progress(self._operation_id, **values)

    def _persist(self) -> None:
        if self.total_bytes <= 0 or self.processed_bytes >= self.total_bytes:
            return
        now = time.monotonic()
        if now - self._last_persisted_at < self._MAX_PERSIST_INTERVAL:
            return
        percent = self.processed_bytes * 100.0 / self.total_bytes
        self._operations.update_progress(
            self._operation_id,
            processed_files=self.processed_files,
            processed_bytes=self.processed_bytes,
            estimated_total_bytes=self.total_bytes,
            # Before the first real whole percent keep the numeric value unknown,
            # but still publish truthful byte/file counters during a large file.
            percent=percent if percent >= 1.0 else None,
        )
        self._last_persisted_at = now


class BackupManager:
    """Единый core facade Backup Manager.

    Этап 1 реализует import/verify/delete, publication protocol, catalog,
    operations, disk admission и startup reconciliation. SSH create и
    mutation workflows подключаются в следующих этапах через этот facade.
    """

    def __init__(self, backup_config: dict, *, data_root: str | Path | None = None, lock_root: str | Path | None = None):
        self.config = normalize_backup_config(backup_config)
        self.data_root = Path(data_root or get_backup_data_path())
        self.coordinator = LockCoordinator(lock_root=lock_root, data_root=self.data_root)
        self.storage = LocalBackupStorage(resolve_storage_root(self.config))
        self.catalog = CatalogStore(self.data_root, self.coordinator)
        self.operations = OperationStore(self.data_root, self.coordinator)
        self.inventory_indexer = ArchiveInventoryIndexer(
            self.data_root,
            self.coordinator,
            catalog=self.catalog,
            storage=self.storage,
        )
        self.retention_runs = JsonRecordDirectory(
            self.data_root / "retention",
            self.coordinator,
            "retention run",
        )
        self.disk = DiskMonitor(self.storage.root, self.config["safety"], self.data_root)
        self._migrate_catalog_identity()
        self._migrate_import_filename_layout()

    def _migrate_catalog_identity(self) -> None:
        """Идемпотентно перенести identity layout и каноническое filename.

        Production собирает facade на каждый запрос и не выполняет
        reconcile_startup, поэтому перенос обязан происходить здесь: иначе уже
        опубликованные записи могли бы остаться невидимыми или навсегда
        сохранять несколько пользовательских имён. Физический Storage при этом
        не меняется.
        """
        try:
            with self.coordinator.catalog_lock():
                if self.catalog.has_flat_records():
                    self.catalog.migrate_flat_layout(lock_held=True)
                self.catalog.migrate_filename_layout(lock_held=True)
        except BackupError:
            # Отказ миграции не должен ломать создание facade: записи остаются
            # на месте, попытка повторится при следующем обращении, а
            # некорректные файлы изолирует reconciliation.
            return

    def _migrate_import_filename_layout(self) -> None:
        """Persist schema v1 import names as the single canonical filename."""
        try:
            refs = self.storage.iter_import_bundle_refs()
        except BackupError:
            return
        for server_id, entry_key in refs:
            try:
                with self.coordinator.acquire_import_publish(
                    entry_key,
                    server_id=server_id,
                ):
                    resolved = self.storage.resolve_import_bundle(
                        entry_key,
                        server_id=server_id,
                    )
                    if not resolved["publication_migration_required"]:
                        continue
                    self.storage.update_import_filename(
                        resolved["publication_path"],
                        resolved["publication"]["filename"],
                    )
            except BackupError:
                # Повреждённый или одновременно меняющийся bundle не блокирует
                # facade; безопасная повторная попытка произойдёт позже.
                continue

    def _resolve_encryption_password(
        self,
        explicit: str | None,
        encrypt: bool | None = None,
        *,
        missing_ok: bool = False,
    ) -> str | None:
        """Пароль шифрования архива: одноразовый → сохранённый (enc1:) → None.

        Явный пароль (одноразовый, из API) приоритетнее сохранённого. Пустая
        строка/None означает «не передавали» — работаем с сохранённым.
        ``encrypt`` — решение о шифровании: False — plain-архив даже при
        настроенном сохранённом пароле, True — архив обязан быть зашифрованным.
        ``missing_ok=True`` означает, что True пришёл не от человека, а выведен
        из настроек цели (``encrypt`` в профиле): плановый бэкап без пароля не
        срывается — отсутствующий бэкап хуже нешифрованного, поэтому создаётся
        plain-архив с warning-записью в журнал. От человека (``missing_ok``
        False) тихий plain был бы обманом выбора — чистый отказ. Если
        сохранённый пароль не может быть расшифрован (мастер-ключ
        недоступен/утерян), фолбэк plain+warning — в обоих режимах. Сам пароль
        нигде не логируется.
        """
        if encrypt is False:
            return None
        if explicit:
            if len(explicit) > MAX_PASSWORD_LEN:
                raise BackupError(
                    ErrorCode.INVALID_REQUEST,
                    f"Пароль шифрования — строка до {MAX_PASSWORD_LEN} символов",
                )
            return explicit
        try:
            resolved = get_stored_backup_password() or None
        except SecretBoxError:
            create_event(
                EventType.BACKUP,
                EventLevel.WARNING,
                "Шифрование бэкапа пропущено",
                "Мастер-ключ недоступен — сохранённый пароль резервных копий "
                "не может быть расшифрован. Архив создан без шифрования.",
            )
            return None
        if encrypt is True and resolved is None:
            if missing_ok:
                create_event(
                    EventType.BACKUP,
                    EventLevel.WARNING,
                    "Защита бэкапа пропущена",
                    "В настройках цели включена защита паролем, но сам пароль "
                    "резервных копий не задан. Архив создан без шифрования. "
                    "Задайте пароль в Настройки → Безопасность.",
                )
                return None
            # Пользователь явно потребовал шифрование, но пароля нет:
            # тихий plain-архив был бы обманом выбора.
            raise BackupError(
                ErrorCode.ENCRYPTION_PASSWORD_REQUIRED,
                "Не задан пароль резервных копий: настройте его в "
                "Настройки → Безопасность или введите разовый пароль",
            )
        return resolved

    def _decrypt_restore_archive(self, archive_path: Path, password: str | None) -> Path:
        """Расшифровать B4VE-архив во временный plain tar.gz в staging (0600).

        Возвращает путь к расшифрованному файлу; удаление временного каталога —
        ответственность вызывающего (``remove_staging`` в finally): расшифрованные
        байты не должны переживать операцию. Пароль: явный ввод (Web-визард или
        модалка «архив создан до смены пароля») → сохранённый (enc1:). Нет
        пароля — чистый ENCRYPTION_PASSWORD_REQUIRED, неверный —
        ENCRYPTION_PASSWORD_INVALID (из decrypt_file).
        """
        if password:
            if len(password) > MAX_PASSWORD_LEN:
                raise BackupError(
                    ErrorCode.INVALID_REQUEST,
                    f"Пароль резервных копий — строка до {MAX_PASSWORD_LEN} символов",
                )
        else:
            try:
                password = get_stored_backup_password()
            except SecretBoxError as exc:
                raise BackupError(
                    ErrorCode.ENCRYPTION_PASSWORD_REQUIRED,
                    "Архив зашифрован, а сохранённый пароль резервных копий "
                    "недоступен (мастер-ключ не задан). Введите пароль вручную",
                ) from exc
            if not password:
                raise BackupError(
                    ErrorCode.ENCRYPTION_PASSWORD_REQUIRED,
                    "Архив зашифрован: введите пароль резервных копий",
                )
        staging_dir = f"dec-{uuid4().hex}"
        plain = self.storage.staging_archive_path(staging_dir, "decrypted", "create")
        try:
            self.storage.create_staging(staging_dir, "create")
            decrypt_file(archive_path, plain, password)
        except BaseException:
            self.storage.remove_staging(staging_dir, "create")
            raise
        return plain

    @staticmethod
    def _discard_decrypted_restore_archive(plain: Path | None) -> None:
        """Удалить временный расшифрованный restore-архив (best effort)."""
        if plain is None:
            return
        try:
            shutil.rmtree(plain.parent, ignore_errors=True)
        except Exception:
            pass

    def _managed_inventory_binding(
        self,
        *,
        backup_id: str,
        backup_type: str,
        server_id: str | None,
        checksum: str,
        archive_bytes: int,
    ) -> tuple[dict, dict]:
        """Build the immutable identity stored in a managed v2 sidecar."""
        storage_key, _ = self.storage.canonical_keys(
            backup_id,
            backup_type,
            server_id,
        )
        source = {
            "kind": "managed",
            "backup_id": backup_id,
            "type": backup_type,
            "artifact_version": 1,
            "storage_key": storage_key,
        }
        if backup_type == "server":
            source["server_id"] = server_id
        return source, {
            "sha256": checksum,
            "bytes": int(archive_bytes),
            "format": "tar.gz",
        }

    def _stage_native_archive_inventory(
        self,
        *,
        archive_path: Path,
        inspection: dict,
        source: dict,
        archive: dict,
    ) -> Path | None:
        """Consume the one TAR inspection and stage its compact UI index.

        Inventory is a repairable cache. Failure here must not invalidate an
        archive that passed the authoritative physical verification.
        """
        members = inspection.pop("members")
        try:
            inventory = build_archive_inventory(
                members=members,
                manifest=inspection["manifest"],
                source=source,
                archive=archive,
                consume_members=True,
            )
            return self.storage.write_archive_inventory_staging(
                archive_path,
                inventory,
            )
        except Exception:
            return None
        finally:
            # On the successful consume path ``members`` is already the compact
            # row array owned by ``inventory``. On failure this drops the only
            # retained full metadata graph instead of carrying it to publication.
            members.clear()

    def _install_or_queue_managed_inventory(
        self,
        *,
        staging_inventory: Path | None,
        archive_path: Path,
        checksum_path: Path,
        source: dict,
        archive: dict,
    ) -> bool:
        """Install a staged cache after publication, or persist a repair job."""
        installed = False
        if staging_inventory is not None:
            try:
                installed = self.storage.install_managed_archive_inventory(
                    staging_inventory,
                    archive_path,
                    checksum_path,
                    expected_source=source,
                    expected_archive=archive,
                )
            except Exception:
                installed = False
        if installed:
            return True
        try:
            self.inventory_indexer.enqueue_managed(
                source=source,
                archive=archive,
                reason=(
                    "staging_inventory_unavailable"
                    if staging_inventory is None
                    else "sidecar_install_failed"
                ),
            )
        except Exception:
            # A cache/queue storage outage cannot retroactively fail a published,
            # verified backup. Startup reconciliation will rediscover it later.
            pass
        return False

    @staticmethod
    def _artifact_ref(
        *,
        kind: str,
        backup_id: str,
        server_id: str | None = None,
    ) -> ArtifactRef:
        """ArtifactRef с safe BackupError вместо ValueError."""
        try:
            return ArtifactRef.create(kind=kind, backup_id=backup_id, server_id=server_id)
        except ValueError as exc:
            raise BackupError(ErrorCode.INVALID_REQUEST, str(exc)) from exc

    @staticmethod
    def _native_archive_filename(
        name: object,
        created_at: str,
        *,
        collision_index: int = 1,
    ) -> str:
        """Build an installation-local filename with a collision suffix."""
        if not isinstance(collision_index, int) or isinstance(collision_index, bool) or collision_index < 1:
            raise ValueError("collision_index должен быть положительным integer")
        timestamp = parse_utc_timestamp(created_at).astimezone(local_timezone())
        collision_suffix = "" if collision_index == 1 else f"-{collision_index}"
        suffix = (
            f"-{timestamp.strftime('%d.%m.%Y_%H-%M')}"
            f"{collision_suffix}.tar.gz"
        )
        raw_prefix = str(name or "server").strip() or "server"
        safe_prefix = "".join(
            "_" if char in "/\\" or ord(char) < 32 or ord(char) == 127 else char
            for char in raw_prefix
        )
        safe_prefix = safe_prefix[: MAX_ARCHIVE_FILENAME_LENGTH - len(suffix)] or "server"
        return validate_archive_filename(safe_prefix + suffix)

    @staticmethod
    def _protective_filename_prefix(name: object) -> str:
        """``<имя установки>_before.restore_`` — общий префикс защитных копий.

        По этому префиксу опознаётся прежняя защитная копия установки, поэтому
        обрезка здесь та же, что в полном имени: префикс обязан совпадать с
        началом того, что построит `_protective_backup_filename`. Дата в конце
        имени всегда одной длины, но префикс её длину не учитывает — под него
        попадает и историческое имя `_before.restore_data`.
        """
        suffix_length = len(PROTECTIVE_FILENAME_INFIX) + PROTECTIVE_DATE_LENGTH
        raw_prefix = str(name or "server").strip() or "server"
        safe_prefix = "".join(
            "_" if char in "/\\" or ord(char) < 32 or ord(char) == 127 else char
            for char in raw_prefix
        )
        safe_prefix = safe_prefix[: MAX_ARCHIVE_FILENAME_LENGTH - suffix_length] or "server"
        return safe_prefix + PROTECTIVE_FILENAME_INFIX

    @staticmethod
    def _protective_backup_filename(
        name: object,
        created_at: str,
    ) -> str:
        """``<имя установки>_before.restore_<ДД.ММ.ГГГГ>`` — имя с датой копии.

        Дата берётся из момента создания самой защитной копии и проецируется по
        timezone установки, как и обычное имя архива. Дата — только видимая метка:
        копия у установки остаётся одна, прежняя удаляется после публикации новой
        (`_protective_backup`). Санитизация та же, что у обычного имени архива,
        иначе имя сервера с ``/`` не прошло бы валидацию.
        """
        timestamp = parse_utc_timestamp(created_at).astimezone(local_timezone())
        date = timestamp.strftime("%d.%m.%Y")
        return validate_archive_filename(
            BackupManager._protective_filename_prefix(name) + date
        )

    @staticmethod
    def _capture_remote_utc_offset(exec_sudo, ssh, server: dict) -> str | None:
        """Read the source server's actual wall-clock offset without guessing.

        A failed probe does not block backup creation; that archive remains v1.
        Видимое время в UI от этого не зависит — оно строится по часам установки,
        как и имя архива (`_project_catalog_display` в `ui/web/routers/backups.py`).
        """
        try:
            code, stdout, _ = exec_sudo(ssh, server, "date +%z", timeout=30)
            if code != 0:
                return None
            return normalize_utc_offset(stdout.strip())
        except Exception:
            # Metadata is best-effort: transport-specific SSH failures must not
            # turn an otherwise valid backup into a failed operation.
            return None

    @staticmethod
    def _import_archive_filename(
        source_archive: str | Path,
        filename: str | None,
    ) -> str:
        value = filename if filename is not None else Path(source_archive).name
        return validate_archive_filename(value)

    @staticmethod
    def _record_ref(record: dict) -> ArtifactRef:
        """Artifact identity опубликованной записи Catalog."""
        try:
            return ArtifactRef.from_record(record)
        except ValueError as exc:
            raise BackupError(
                ErrorCode.CATALOG_CONFLICT,
                "Catalog record не содержит artifact identity",
            ) from exc

    @staticmethod
    def _backup_id_of(target: ArtifactRef | str) -> str:
        if isinstance(target, ArtifactRef):
            return target.backup_id
        if isinstance(target, str):
            return target
        raise BackupError(ErrorCode.INVALID_REQUEST, "Некорректный backup_id")

    def _optional_ref(self, target: ArtifactRef | str) -> ArtifactRef | None:
        """Namespace адресуемого artifact; None — если запись недоступна.

        Frozen Web API передаёт только строку, поэтому namespace приходится
        восстанавливать по Catalog. Неоднозначный backup_id (один и тот же id в
        нескольких namespace) отдаёт CATALOG_CONFLICT: авто-выбор запрещён.
        """
        if isinstance(target, ArtifactRef):
            return target
        try:
            return self.catalog.resolve_ref(self._backup_id_of(target))
        except BackupError as exc:
            if exc.code == ErrorCode.ARTIFACT_NOT_FOUND.value:
                return None
            raise

    def _requested_ref(
        self,
        backup_id: ArtifactRef | str,
        server_id: str | None,
    ) -> ArtifactRef | str:
        """Явный namespace из Web-запроса; без server_id — прежнее поведение.

        Web-граница передаёт строковый backup_id, поэтому server namespace
        приходит рядом с ним отдельным параметром запроса. Отсутствие server_id
        оставляет прежний путь через ``catalog.resolve_ref``: уникальный id (в
        том числе bot4vps) разрешается однозначно, а неоднозначный по-прежнему
        даёт CATALOG_CONFLICT — авто-выбор namespace запрещён.
        """
        if server_id is None or isinstance(backup_id, ArtifactRef):
            return backup_id
        return self._artifact_ref(
            kind="server",
            backup_id=self._backup_id_of(backup_id),
            server_id=server_id,
        )

    @staticmethod
    def _destination_server_id(ref: ArtifactRef) -> str | None:
        """Return the visible filename namespace for an artifact ref."""
        return ref.server_id if ref.kind == "server" else None

    @staticmethod
    def _destination_label(server_id: str | None) -> str:
        return "server" if server_id is not None else "bot4vps"

    def _find_filename_conflict(
        self,
        filename: str,
        *,
        server_id: str | None,
        exclude_ref: ArtifactRef | None = None,
        exclude_entry_key: str | None = None,
    ) -> dict | None:
        """Find one visible filename owner in a destination namespace.

        A scan is safe as an optimistic hint before locking, but only a scan
        performed while holding ``destination_lock(server_id)`` is definitive.
        Catalog and imported bundles remain physically separate; this is only a
        Core-side namespace projection used to make a user filename unique.
        """
        filename = validate_archive_filename(filename)
        if server_id is None:
            records = self.catalog.list(backup_type="bot4vps")
        else:
            records = self.catalog.list(backup_type="server", server_id=server_id)
        for record in records:
            try:
                ref = self._record_ref(record)
            except BackupError:
                continue
            if exclude_ref is not None and ref == exclude_ref:
                continue
            if record.get("filename") == filename:
                return {
                    "kind": "managed",
                    "filename": filename,
                    "ref": ref,
                    "record": record,
                    "backup_id": ref.backup_id,
                    "server_id": server_id,
                    "requires_confirmation": ref.kind == "bot4vps",
                }

        for publication in self.storage.list_import_bundles(server_id=server_id):
            entry_key = publication.get("entry_key")
            if exclude_entry_key is not None and entry_key == exclude_entry_key:
                continue
            if publication.get("filename") == filename:
                return {
                    "kind": "imported",
                    "filename": filename,
                    "entry_key": entry_key,
                    "publication": publication,
                    "server_id": server_id,
                    "requires_confirmation": False,
                }
        return None

    def _managed_protective_copies(
        self,
        display_name: str,
        *,
        server_id: str | None,
    ) -> list[dict]:
        """Managed-копии ``<имя>_before.restore_*`` в namespace назначения.

        Ровно одна защитная копия на target — инвариант, но опознать её нечем,
        кроме имени: копия хранится как обычный backup (`purpose=regular`), и
        отдельного признака в Catalog у неё нет. Поэтому отбор идёт по префиксу
        имени, и под него попадают в том числе копии прошлых дней и историческое
        `_before.restore_data`.

        Импортированные архивы сюда не попадают намеренно: пользовательский архив
        нельзя удалять за совпадение имени. Если импортированный занял ровно то
        имя, которое нужно новой копии, вызывающий останавливает Restore.

        Определяющим результат становится только под ``destination_lock``.
        """
        prefix = self._protective_filename_prefix(display_name)
        if server_id is None:
            records = self.catalog.list(backup_type="bot4vps")
        else:
            records = self.catalog.list(backup_type="server", server_id=server_id)
        found: list[dict] = []
        for record in records:
            filename = record.get("filename")
            if not isinstance(filename, str) or not filename.startswith(prefix):
                continue
            try:
                ref = self._record_ref(record)
            except BackupError:
                continue
            found.append({
                "kind": "managed",
                "filename": filename,
                "ref": ref,
                "record": record,
                "backup_id": ref.backup_id,
                "server_id": server_id,
                "requires_confirmation": ref.kind == "bot4vps",
            })
        return found

    def _available_native_archive_filename(
        self,
        name: object,
        created_at: str,
        *,
        server_id: str | None,
    ) -> str:
        """Choose the first free installation-local name while destination lock is held.

        The first archive keeps the historical ``name-date`` form. Further
        archives created in the same installation-local minute receive ``-2``, ``-3``,
        and so on. The caller holds the destination namespace lock, so two
        concurrent publications cannot select the same suffix.
        """
        collision_index = 1
        while True:
            filename = self._native_archive_filename(
                name,
                created_at,
                collision_index=collision_index,
            )
            if self._find_filename_conflict(filename, server_id=server_id) is None:
                return filename
            collision_index += 1

    @staticmethod
    def _filename_conflict_error(
        conflict: dict,
        *,
        confirmation_required: bool = False,
    ) -> BackupError:
        filename = str(conflict["filename"])
        details = {
            "filename": filename,
            "destination": {
                "scope": "server" if conflict.get("server_id") is not None else "bot4vps",
                "server_id": conflict.get("server_id"),
            },
            "kind": conflict.get("kind"),
            "requires_confirmation": bool(
                confirmation_required or conflict.get("requires_confirmation")
            ),
        }
        if conflict.get("kind") == "managed":
            details["backup_id"] = conflict.get("backup_id")
        else:
            details["entry_key"] = conflict.get("entry_key")
        return BackupError(
            ErrorCode.ARCHIVE_FILENAME_CONFLICT,
            f"Backup с именем `{filename}` уже существует на этом сервере.",
            retryable=True,
            details=details,
        )

    @staticmethod
    def _replace_confirmation_error(conflict: dict) -> BackupError:
        error = BackupManager._filename_conflict_error(
            conflict,
            confirmation_required=True,
        )
        return BackupError(
            ErrorCode.ARCHIVE_REPLACE_CONFIRMATION_REQUIRED,
            f"Перед заменой backup `{conflict['filename']}` требуется подтверждение.",
            retryable=True,
            details=error.details,
        )

    def _delete_managed_for_replacement(
        self,
        conflict: dict,
        *,
        operation_id: str,
    ) -> None:
        """Remove a managed collision while its artifact lock is held."""
        ref = conflict.get("ref")
        if not isinstance(ref, ArtifactRef):
            raise BackupError(ErrorCode.CATALOG_CONFLICT, "Не удалось адресовать заменяемый backup")
        intent = self.catalog.begin_delete(
            ref,
            owner_operation_id=operation_id,
            ttl_seconds=int(self.config["safety"]["claim_ttl_seconds"]),
        )
        claim = intent["retention"]["claim"]
        expected_version = int(intent["artifact_version"])
        try:
            archive_path = self.storage.resolve_key(intent["storage"]["key"])
            checksum_path = self.storage.resolve_key(intent["storage"]["checksum_key"])
            self.storage.delete_pair(archive_path, checksum_path)
        except Exception as exc:
            try:
                self.catalog.mark_delete_failed(
                    ref,
                    expected_version=expected_version,
                    expected_claim_id=claim["claim_id"],
                )
            except BackupError:
                pass
            if isinstance(exc, BackupError):
                raise
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Не удалось заменить существующий backup",
                retryable=True,
            ) from exc
        self.catalog.finish_delete(
            ref,
            expected_version=expected_version,
            expected_claim_id=claim["claim_id"],
        )

    @staticmethod
    def _same_filename_conflict(left: dict | None, right: dict | None) -> bool:
        if left is None or right is None or left.get("kind") != right.get("kind"):
            return left is None and right is None
        if left["kind"] == "managed":
            return left.get("ref") == right.get("ref")
        return (
            left.get("entry_key") == right.get("entry_key")
            and left.get("server_id") == right.get("server_id")
        )

    def _assert_filename_available(
        self,
        filename: str,
        *,
        server_id: str | None,
        exclude_ref: ArtifactRef | None = None,
        exclude_entry_key: str | None = None,
    ) -> None:
        conflict = self._find_filename_conflict(
            filename,
            server_id=server_id,
            exclude_ref=exclude_ref,
            exclude_entry_key=exclude_entry_key,
        )
        if conflict is not None:
            raise self._filename_conflict_error(conflict)

    def _artifact_target(
        self,
        *,
        target: ArtifactRef | str,
    ) -> tuple[dict, ArtifactRef | None, str]:
        """Operation target + namespace для verify/delete одного artifact."""
        backup_id = self._backup_id_of(target)
        ref = self._optional_ref(target)
        operation_target = {"kind": "backup", "backup_id": backup_id}
        if ref is not None and ref.kind == "server":
            operation_target["server_id"] = str(ref.server_id)
        return operation_target, ref, backup_id

    def _storage_ref(self, path: Path, backup_id: str) -> ArtifactRef | None:
        """Artifact identity по каноническому пути Storage.

        Storage layout не меняется: ``bot4vps/<backup_id>`` и
        ``servers/<server_id>/<backup_id>``. Всё, что лежит вне этих двух форм,
        namespace не имеет, поэтому не может быть опубликованным артефактом.
        """
        try:
            parts = path.relative_to(self.storage.root).parts
        except ValueError:
            return None
        try:
            if len(parts) == 2 and parts[0] == "bot4vps":
                return ArtifactRef.for_bot4vps(backup_id)
            if len(parts) == 3 and parts[0] == "servers":
                return ArtifactRef.for_server(parts[1], backup_id)
        except ValueError:
            return None
        return None

    @staticmethod
    def _publication_namespace_allows(operation: dict, ref: ArtifactRef) -> bool:
        """Может ли незавершённая publication относиться к этому namespace.

        Orphan-recovery связывает pair с Operation по ``result_backup_id``; при
        namespace identity этого недостаточно — Operation, публиковавшая в
        другой namespace, не должна «оживлять» чужой артефакт с тем же
        backup_id. Import без destination (``kind == "unknown"``) namespace не
        фиксирует: его определяет manifest, поэтому допустим в любом namespace.
        """
        target = operation.get("target") or {}
        kind = target.get("kind")
        if kind == "bot4vps":
            return ref.kind == "bot4vps"
        if kind == "server":
            server_id = target.get("server_id")
            return (
                ref.kind == "server"
                and isinstance(server_id, str)
                and ref.server_id == server_id
            )
        return True

    @staticmethod
    def _critical_failure(code: str) -> bool:
        return code in {
            ErrorCode.ARCHIVE_INVALID.value,
            ErrorCode.CHECKSUM_MISMATCH.value,
            ErrorCode.CHECKSUM_MISSING.value,
            ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE.value,
            ErrorCode.DISK_SPACE_CRITICAL.value,
            ErrorCode.DISK_SPACE_EMERGENCY.value,
        }

    @staticmethod
    def _category_enabled(notifications: dict | None, category: str, success: bool) -> bool:
        """True, если для категории (`backup`/`restore`) включён push нужного исхода.

        Мастер-тумблер `enabled` гейтит обе подкатегории; пустой или битый объект
        трактуется как «выключено» — так защитная копия (`notifications={}`) пишет
        журнал, но push не делает.
        """
        section = (notifications or {}).get(category)
        if not isinstance(section, dict) or not section.get("enabled"):
            return False
        return bool(section.get("success" if success else "error"))

    def _emit_backup_event(
        self,
        *,
        operation: dict,
        notifications: dict,
        success: bool,
        error: dict | None = None,
        cancelled: bool = False,
        backup_id: str | None = None,
        backup_filename: str | None = None,
        backup_bytes: int | None = None,
        server_name: str,
    ) -> None:
        """Persist and, when selected, deliver a Backup event via event_service.

        The manager remains synchronous, so immediate delivery is bridged to the
        existing async notifier registry from its worker thread. Queueing still
        happens in event_service and remains the retry path when delivery fails.
        """
        error_code = str((error or {}).get("code") or "")
        critical = (not success) and not cancelled and self._critical_failure(error_code)
        telegram_report = bool(operation.get("initiated_from_telegram"))
        notify = (
            not telegram_report
            and (
                critical
                or self._category_enabled(notifications, "backup", success)
            )
        )
        if cancelled:
            reason = EventReason.BACKUP_CANCELLED.value
            title = "Резервная копия отменена"
            message = "Создание резервной копии отменено."
        else:
            reason = EventReason.BACKUP_COMPLETED.value if success else EventReason.BACKUP_FAILED.value
            title = "Backup завершён" if success else "Backup завершился с ошибкой"
            message = (
                "Backup опубликован успешно."
                if success
                else str((error or {}).get("message") or "Не удалось создать backup.")
            )
        details = {
            "reason": reason,
            "operation_id": operation.get("operation_id"),
            "target": operation.get("target"),
            "backup_id": backup_id or operation.get("result_backup_id"),
            "backup_filename": backup_filename,
            "backup_bytes": backup_bytes,
            "server_name": server_name,
            "mode": operation.get("mode"),
            "initiated_from_telegram": bool(operation.get("initiated_from_telegram")),
        }
        if error:
            details["error"] = dict(error)
        try:
            event_id = create_event(
                event_type=EventType.BACKUP,
                level=EventLevel.CRITICAL if critical else (EventLevel.INFO if success else EventLevel.WARNING),
                title=title,
                message=message,
                details=details,
                notify=notify,
                enqueue=False if telegram_report else None,
            )
            if notify:
                notification = {
                    "type": EventType.BACKUP.value,
                    "level": EventLevel.CRITICAL.value if critical else (EventLevel.INFO.value if success else EventLevel.WARNING.value),
                    "title": title,
                    "message": message,
                    "details": details,
                }
                try:
                    asyncio.run(
                        dispatch_notifiers(
                            notification,
                            event_id,
                            fallback_to_queue=False,
                        )
                    )
                except RuntimeError:
                    # Обычная queue-first доставка уже зафиксирована create_event.
                    # Telegram-origin до этого блока не доходит: его результат
                    # редактирует watcher исходного progress-сообщения.
                    pass
        except Exception as exc:
            # Notification failure must never turn a completed/failed backup
            # operation into a different lifecycle result.
            print(f"[BACKUP NOTIFY] {exc}", flush=True)

    def _emit_restore_event(
        self,
        *,
        operation: dict,
        notifications: dict,
        success: bool,
        mutation_started: bool = False,
        error: dict | None = None,
        cancelled: bool = False,
        backup_filename: str | None = None,
        server_name: str,
        server_id: str | None = None,
        mode: str | None = None,
        protective_backup: str | None = None,
    ) -> None:
        """Persist and, when selected, deliver a Restore event via event_service.

        Критичность определяется не набором кодов, как у backup, а фактом начала
        мутации target: провал после mutation необратим и обязан быть CRITICAL с
        принудительным push (тумблер ``restore.error`` его не отключает). Успех и
        провал до mutation гейтятся настройками категории ``restore``. Мост
        доставки повторяет ``_emit_backup_event``: manager синхронный, а
        ``restore()`` работает в daemon-потоке, поэтому ``asyncio.run`` корректен.
        """
        critical = (not success) and not cancelled and bool(mutation_started)
        telegram_report = bool(operation.get("initiated_from_telegram"))
        notify = (
            not telegram_report
            and (
                critical
                or self._category_enabled(notifications, "restore", success)
            )
        )
        if cancelled:
            reason = EventReason.RESTORE_CANCELLED.value
            title = "Восстановление отменено"
            message = "Восстановление отменено пользователем."
        else:
            reason = EventReason.RESTORE_COMPLETED.value if success else EventReason.RESTORE_FAILED.value
            title = "Восстановление завершено" if success else "Восстановление завершилось с ошибкой"
            message = (
                "Данные из backup записаны на сервер, результат проверен."
                if success
                else str((error or {}).get("message") or "Не удалось выполнить восстановление.")
            )
        details = {
            "reason": reason,
            "operation_id": operation.get("operation_id"),
            "target": operation.get("target"),
            "server_name": server_name,
            "server_id": server_id,
            "backup_filename": backup_filename,
            "mode": mode,
            "mutation_started": bool(mutation_started),
            "protective_backup": protective_backup,
            "initiated_from_telegram": bool(operation.get("initiated_from_telegram")),
        }
        if error:
            details["error"] = dict(error)
        try:
            event_id = create_event(
                event_type=EventType.BACKUP,
                level=EventLevel.CRITICAL if critical else (EventLevel.INFO if success else EventLevel.WARNING),
                title=title,
                message=message,
                details=details,
                notify=notify,
                enqueue=False if telegram_report else None,
            )
            if notify:
                notification = {
                    "type": EventType.BACKUP.value,
                    "level": EventLevel.CRITICAL.value if critical else (EventLevel.INFO.value if success else EventLevel.WARNING.value),
                    "title": title,
                    "message": message,
                    "details": details,
                }
                try:
                    asyncio.run(
                        dispatch_notifiers(
                            notification,
                            event_id,
                            fallback_to_queue=False,
                        )
                    )
                except RuntimeError:
                    # Обычная queue-first доставка уже зафиксирована create_event.
                    # Telegram-origin до этого блока не доходит: его результат
                    # редактирует watcher исходного progress-сообщения.
                    pass
        except Exception as exc:
            # Как и у backup: сбой уведомления не меняет lifecycle Restore-операции.
            print(f"[RESTORE NOTIFY] {exc}", flush=True)

    def _require_backup_profile(self, server_id: str) -> tuple[dict, dict]:
        """Вернуть (сервер, нормализованный профиль) или отказать сразу.

        Пустой профиль — легальное состояние (пользователь убрал все адреса), но
        создавать по нему backup нечего. Отказ обязан приходить до Operation, SSH
        и staging: иначе ошибка всплыла бы только на этапе манифеста, уже после
        подключения и упаковки, оставив FAILED Operation от случайного клика.
        """
        server = find_server(server_id)
        if server is None:
            raise BackupError(ErrorCode.SOURCE_NOT_FOUND, "Сервер backup не найден")
        raw_profile = server.get("backup")
        if not isinstance(raw_profile, dict):
            # Без этой проверки normalize_server_profile ответил бы техническим
            # «Поддерживается только schema_version=1» вместо понятной причины.
            raise BackupError(
                ErrorCode.PROFILE_NO_SOURCES,
                "Backup сервера не настроен: сначала добавьте источники в профиле",
            )
        try:
            profile = normalize_server_profile(raw_profile)
        except (BackupError, TypeError, ValueError) as exc:
            if isinstance(exc, BackupError):
                raise
            raise BackupError(ErrorCode.PROFILE_INVALID, "Профиль backup сервера некорректен") from exc
        if not profile["sources"]:
            raise BackupError(
                ErrorCode.PROFILE_NO_SOURCES,
                "В профиле сервера нет источников — backup не создан",
            )
        return server, profile

    def _profile_for_sources_override(
        self,
        server_id: str,
        sources: list[dict],
    ) -> tuple[dict, dict]:
        """Профиль для backup по явно заданному списку источников.

        Защитная копия перед Restore обязана создаваться и там, где профиль
        backup не настроен — это ровно самый опасный случай. Проверка «в профиле
        нет источников» относится к выбору пользователя, а не к явному списку
        путей, поэтому здесь она не применяется. Лимиты профиля наследуются: они
        защищают то же хранилище. Флаг шифрования тоже наследуется: копия —
        полноценный архив в общем списке, защита определяется настройкой цели.
        Уведомления — нет.
        """
        server = find_server(server_id)
        if server is None:
            raise BackupError(ErrorCode.SOURCE_NOT_FOUND, "Сервер backup не найден")
        limits: dict = {}
        encrypt_flag = False
        raw_profile = server.get("backup")
        if isinstance(raw_profile, dict):
            try:
                existing = normalize_server_profile(raw_profile)
            except Exception:
                # Метаданные профиля — best effort: некорректный профиль не
                # должен отменять защитную копию перед Restore.
                existing = None
            if existing is not None:
                limits = dict(existing["limits"])
                encrypt_flag = bool(existing.get("encrypt"))
        return server, {
            "schema_version": 1,
            "sources": [
                {"path": item["path"], "exclusions": list(item.get("exclusions") or [])}
                for item in sources
            ],
            "automatic": {"enabled": False},
            "limits": limits,
            # Уведомления профиля намеренно не наследуются: защитная копия —
            # внутренний шаг Restore, о котором пользователь узнаёт из панели
            # Restore. Событие журнала создаётся как обычно, push не делается.
            "notifications": {},
            "encrypt": encrypt_flag,
        }

    def create(
        self,
        server_id: str,
        *,
        request_id: str | None = None,
        purpose: str = "regular",
        mode: str = "manual",
        label: str | None = None,
        sources_override: list[dict] | None = None,
        locks_held: bool = False,
        initiated_from_telegram: bool = False,
        password: str | None = None,
        encrypt: bool | None = None,
    ) -> dict:
        """Создать server backup через binary SSH streaming.

        ``sources_override`` заменяет источники профиля явным списком (защитная
        копия перед Restore копирует ровно затрагиваемые пути). Источники профиля
        и override имеют одинаковую обычную семантику: отдельного «полного» режима
        нет. ``locks_held`` означает, что вызывающий уже держит maintenance/target-
        локи: повторный ``begin_backup`` из-под maintenance дал бы
        MAINTENANCE_ACTIVE, а flock не реентрантен — тот же процесс ушёл бы в
        собственную блокировку.
        """
        from core.ssh import (
            BinaryStreamCancelled,
            classify_tar_stream,
            create_ssh_client,
            detect_tar_capability,
            exec_binary_stream,
            exec_sudo,
        )
        if sources_override is None:
            server, profile = self._require_backup_profile(server_id)
        else:
            server, profile = self._profile_for_sources_override(
                server_id,
                sources_override,
            )
        # Шифрование по умолчанию — свойство цели (encrypt в профиле): ручной
        # запуск, расписание и Telegram не передают encrypt сами. Явный
        # аргумент вызова перекрывает профиль (API: принудительно plain или
        # зашифрованный); явный пароль без флага тоже означает «зашифровать».
        # derived-флаг без пароля не рвёт бэкап (см.
        # _resolve_encryption_password, missing_ok).
        derived_encrypt = encrypt is None
        if derived_encrypt:
            encrypt = bool(profile.get("encrypt")) or bool(password)
        request_id = request_id or f"create-{uuid4().hex}"
        operation_id = new_operation_id()
        owner = self.coordinator.acquire_operation_owner(operation_id)
        target = {"kind": "server", "server_id": server_id}
        try:
            operation = self.operations.create(
                operation_type="create",
                target=target,
                request_id=request_id,
                mode=mode,
                operation_id=operation_id,
                initiated_from_telegram=initiated_from_telegram,
            )
        except Exception:
            owner.release()
            raise
        if operation["operation_id"] != operation_id:
            owner.release()
            if operation["status"] == OperationStatus.COMPLETED.value:
                return {
                    "operation": operation,
                    "catalog": self.catalog.get(
                        self._artifact_ref(
                            kind="server",
                            backup_id=operation["result_backup_id"],
                            server_id=server_id,
                        )
                    ),
                }
            error = operation.get("error") or {}
            raise BackupError(
                error.get("code", ErrorCode.OPERATION_CONFLICT.value),
                error.get("message", "Create Operation уже существует"),
                retryable=bool(error.get("retryable", True)),
                correlation_id=error.get("correlation_id"),
            )

        def raise_if_cancelled() -> None:
            if self.operations.get(operation_id)["cancellation"]["requested"]:
                raise BackupError(
                    ErrorCode.CANCELLED_BY_USER,
                    "Backup отменён пользователем",
                )

        backup_permit = None
        staging_created = False
        ssh = None
        filename = None
        remote_archives: list[Path] = []
        source_is_directory: list[bool] = []
        try:
            if not locks_held:
                backup_permit = self.coordinator.begin_backup(
                    operation_id, f"server:{server_id}"
                )
            self.operations.transition(operation_id, OperationStatus.RUNNING.value, stage="preflight")
            self.disk.require_creation_allowed()
            staging = self.storage.create_staging(operation_id, "create")
            staging_created = True
            backup_id = new_backup_id()
            artifact_ref = self._artifact_ref(
                kind="server", backup_id=backup_id, server_id=server_id
            )
            self.operations.set_result_backup_id(operation_id, backup_id)
            ssh = create_ssh_client(server)
            source_utc_offset = self._capture_remote_utc_offset(
                exec_sudo,
                ssh,
                server,
            )
            capability = detect_tar_capability(ssh, server)
            if not capability.get("usable"):
                raise BackupError(
                    ErrorCode.ARCHIVE_CREATE_FAILED,
                    "Удалённый tar не поддерживает безопасный gzip streaming",
                )
            limits = dict(self.config["bot4vps"]["limits"])
            limits.update(profile.get("limits", {}))
            max_source_bytes = limits.get("max_source_bytes")
            max_archive_bytes = limits.get("max_archive_bytes")
            transfer_bytes = 0
            last_persisted_transfer = 0
            total_source_bytes = 0
            total_files = 0
            # Каждый source выбран явно и поэтому должен попасть в архив
            # целиком: недоступность не превращается в незаметный пропуск.
            effective_sources: list[dict] = []
            source_warnings: list[dict] = []
            unreadable: list[str] = []
            probed: list[tuple[dict, str]] = []
            for source in profile["sources"]:
                source_path = source["path"]
                try:
                    source_kind = _probe_privileged_source_kind(
                        exec_sudo,
                        ssh,
                        server,
                        source_path,
                    )
                except SourceSelectionError as exc:
                    unreadable.append(str(exc))
                    continue
                probed.append((source, source_kind))
            if unreadable:
                # Проверка доступности дешёвая, поэтому проходит по всем
                # источникам до первой передачи данных: пользователь получает
                # полный список проблем за один запуск.
                raise BackupError(
                    ErrorCode.SOURCE_PERMISSION_DENIED
                    if any("прав" in item for item in unreadable)
                    else ErrorCode.SOURCE_NOT_FOUND,
                    _joined_reasons("Источники недоступны для чтения", unreadable),
                )

            for index, (source, source_kind) in enumerate(probed):
                source_path = source["path"]
                is_directory = source_kind == "directory"
                remote_path = staging / f"remote-{index}.tar.gz"
                argv = ["tar", "-czf", "-"]
                argv.extend(f"--exclude={pattern}" for pattern in source["exclusions"])
                if is_directory:
                    argv.extend(["-C", source_path, "."])
                else:
                    parent = str(PurePosixPath(source_path).parent)
                    basename = PurePosixPath(source_path).name
                    argv.extend(["-C", parent, basename])
                self.operations.update_stage(operation_id, "streaming_source")
                try:
                    current_kind = _probe_privileged_source_kind(
                        exec_sudo,
                        ssh,
                        server,
                        source_path,
                    )
                except SourceSelectionError as exc:
                    raise BackupError(
                        ErrorCode.SOURCE_PERMISSION_DENIED
                        if "прав" in str(exc)
                        else ErrorCode.SOURCE_NOT_FOUND,
                        _joined_reasons(
                            "Источник изменился или стал недоступен перед чтением",
                            [str(exc)],
                        ),
                    ) from exc
                if current_kind != source_kind:
                    raise BackupError(
                        ErrorCode.SOURCE_NOT_FOUND,
                        f"Тип источника изменился перед чтением: {source_path}",
                    )
                with remote_path.open("wb") as output:
                    def receive(chunk: bytes) -> None:
                        nonlocal transfer_bytes, last_persisted_transfer
                        self.disk.require_creation_allowed()
                        if max_archive_bytes is not None and transfer_bytes + len(chunk) > int(max_archive_bytes):
                            raise BackupError(
                                ErrorCode.ARCHIVE_LIMIT_EXCEEDED,
                                "Промежуточный archive превышает допустимый размер",
                            )
                        output.write(chunk)
                        transfer_bytes += len(chunk)
                        if transfer_bytes - last_persisted_transfer >= 1024 * 1024:
                            self.operations.update_progress(
                                operation_id,
                                archive_bytes=transfer_bytes,
                                percent=None,
                            )
                            last_persisted_transfer = transfer_bytes
                    try:
                        exit_code, diagnostics = exec_binary_stream(
                            ssh, server, argv, receive, timeout=600,
                            is_cancelled=lambda: bool(self.operations.get(operation_id)["cancellation"]["requested"]),
                        )
                    except BinaryStreamCancelled as exc:
                        raise BackupError(
                            ErrorCode.CANCELLED_BY_USER,
                            "Backup отменён пользователем",
                        ) from exc
                    output.flush()
                    os.fsync(output.fileno())
                verdict = classify_tar_stream(
                    exit_code,
                    diagnostics,
                    implementation=str(capability.get("implementation") or "unknown"),
                )
                if not verdict["ok"]:
                    reason = "; ".join(verdict["failures"][:3])
                    raise BackupError(
                        ErrorCode.SOURCE_PERMISSION_DENIED,
                        _joined_reasons(
                            "Удалённый tar не смог прочитать источник",
                            [f"{source_path}: {reason}"],
                        ),
                    )
                effective_sources.append(source)
                remote_archives.append(remote_path)
                source_is_directory.append(is_directory)
                source_warnings.extend(
                    {
                        "code": "tar_diagnostic",
                        "message": f"{source_path}: {line}"[:512],
                    }
                    for line in verdict["warnings"]
                )

            if not effective_sources:
                # Пустой архив опубликовать нельзя: при clean-восстановлении
                # объявленный корень без payload означает удаление его содержимого.
                raise BackupError(
                    ErrorCode.PROFILE_NO_SOURCES,
                    _joined_reasons(
                        "Не удалось прочитать ни один источник",
                        unreadable
                        or [item["message"] for item in source_warnings]
                        or ["источники не заданы"],
                    ),
                )

            if not (len(remote_archives) == len(source_is_directory) == len(effective_sources)):
                # zip() при repack молча отбросил бы source: manifest объявил бы
                # путь, payload которого в archive нет.
                raise BackupError(
                    ErrorCode.ARCHIVE_CREATE_FAILED,
                    "Внутренняя рассинхронизация metadata источников",
                )

            # max_source_bytes is defined as the uncompressed size of regular
            # file members that remain after the requested exclusions. It is
            # measured from the streamed tar before publication; excluded
            # members and directories do not contribute to this limit.
            self.operations.update_progress(
                operation_id,
                processed_files=0,
                processed_bytes=0,
                archive_bytes=transfer_bytes,
                percent=None,
            )

            total_files = 0
            total_source_bytes = 0
            member_plans: list[dict] = []
            self.operations.update_stage(operation_id, "inspecting_streamed_sources")
            raise_if_cancelled()
            for source, remote_path, is_directory in zip(
                effective_sources, remote_archives, source_is_directory
            ):
                raise_if_cancelled()
                source_path = source["path"]

                def account(member, member_type, rel, _source_path=source_path) -> None:
                    nonlocal total_files, total_source_bytes
                    del rel, _source_path
                    raise_if_cancelled()
                    self.disk.require_creation_allowed()
                    if member_type != "file":
                        # Ни каталог, ни ссылка не несут содержимого: жёсткая
                        # ссылка — второе имя уже посчитанного файла, и учесть её
                        # ещё раз значило бы завысить и лимит, и прогресс.
                        return
                    total_files += 1
                    total_source_bytes += member.size
                    if max_source_bytes is not None and total_source_bytes > int(max_source_bytes):
                        raise BackupError(
                            ErrorCode.SOURCE_LIMIT_EXCEEDED,
                            "Источник превышает допустимый размер",
                        )

                with tarfile.open(remote_path, "r:gz") as source_archive:
                    plan = _plan_source_members(source_archive, on_member=account)
                raise_if_cancelled()
                member_plans.append(plan)
                if not plan["unsupported"]:
                    continue
                prefix = _payload_prefix_for_source(source_path, is_directory=is_directory)
                described = [
                    f"{label} {_absolute_member_path(prefix, rel)}"
                    for label, rel in plan["unsupported"]
                ]
                # Источники выбраны пользователем поимённо: молча выбросить из
                # них объект нельзя, а отказ обязан назвать путь и тип, а не
                # сказать «backup не удался».
                raise BackupError(
                    ErrorCode.ARCHIVE_SPECIAL_FILE_UNSUPPORTED,
                    _joined_reasons(
                        f"Источник {source_path} содержит объекты, которые backup не переносит",
                        described,
                    ),
                )

            raise_if_cancelled()
            if len(member_plans) != len(effective_sources):
                # repack идёт по zip() из четырёх списков: рассинхронизация молча
                # сдвинула бы решения на чужой источник.
                raise BackupError(
                    ErrorCode.ARCHIVE_CREATE_FAILED,
                    "Внутренняя рассинхронизация metadata источников",
                )
            # Пароль резолвится как можно позже: до этого момента операция ещё
            # может быть отменена, а секрет не должен жить в памяти дольше
            # необходимого. Сюда входит и plain-фолбэк при недоступном мастер-ключе
            # и при профильно-выведенном флаге без заданного пароля.
            encrypt_password = self._resolve_encryption_password(
                password, encrypt, missing_ok=derived_encrypt
            )

            archive_progress = _ArchiveProgress(
                self.operations,
                operation_id,
                total_source_bytes,
            )
            manifest_source = {
                "kind": "server",
                "server_id": server_id,
                "server_name": str(server.get("name") or server_id),
            }
            if source_utc_offset is not None:
                manifest_source["utc_offset"] = source_utc_offset
            manifest = {
                "manifest_version": 2 if source_utc_offset is not None else 1,
                "backup_id": backup_id, "type": "server",
                "purpose": purpose, "mode": mode, "label": label,
                "created_at": operation["created_at"], "completed_at": utc_timestamp(),
                "archive": {"format": "tar.gz", "encrypted": encrypt_password is not None},
                "producer": {"name": "bot4vps", "version": "1"},
                "source": manifest_source,
                # Только реально попавшие в архив источники. Объявить путь, чей
                # payload в архив не попал, нельзя: при clean-восстановлении
                # такой корень был бы очищен целиком.
                "sources": [
                    {"path": item["path"], "payload_prefix": "payload/" + item["path"].lstrip("/"), "exclusions": list(item["exclusions"])}
                    for item in effective_sources
                ],
                "content": {
                    # Объявление описывает содержимое, а не запрет: hardlink-члены
                    # допустимы, и verify_archive сверяет флаг с реальными членами.
                    "metadata": {"hardlinks": any(plan["hardlinks"] for plan in member_plans)},
                    "file_count": total_files,
                    "source_bytes": total_source_bytes,
                },
                "bot4vps": None,
            }

            def write_archive(path: Path, content: dict) -> None:
                raise_if_cancelled()
                self.disk.require_creation_allowed()
                with tarfile.open(path, "w:gz") as final_archive:
                    raw = json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    info = tarfile.TarInfo("manifest.json")
                    info.mode = 0o600
                    info.size = len(raw)
                    final_archive.addfile(info, io.BytesIO(raw))
                    for source, remote_path, is_directory, plan in zip(
                        effective_sources, remote_archives, source_is_directory, member_plans
                    ):
                        raise_if_cancelled()
                        prefix = _payload_prefix_for_source(
                            source["path"], is_directory=is_directory
                        )
                        with tarfile.open(remote_path, "r:gz") as source_archive:
                            for member in source_archive:
                                raise_if_cancelled()
                                self.disk.require_creation_allowed()
                                rel = _streamed_member_relative_name(member.name)
                                if not rel or rel in plan["skip"]:
                                    continue
                                copied = copy.copy(member)
                                copied.name = prefix + "/" + rel
                                if rel in plan["flatten"]:
                                    copied.type = tarfile.SYMTYPE
                                    copied.linkname = plan["flatten"][rel]
                                elif copied.islnk():
                                    # Цель жёсткой ссылки — имя внутри архива, а не
                                    # путь на диске, поэтому она переезжает вместе
                                    # с членами. GNU tar снимает с неё префикс
                                    # ``--strip-components`` так же, как с имени.
                                    copied.linkname = prefix + "/" + _streamed_member_relative_name(
                                        str(member.linkname or "")
                                    )
                                stream = source_archive.extractfile(member) if copied.isfile() else None
                                if copied.isfile() and stream is None:
                                    raise BackupError(
                                        ErrorCode.SOURCE_PERMISSION_DENIED,
                                        "Не удалось прочитать tar member",
                                    )
                                if stream is None:
                                    final_archive.addfile(copied)
                                else:
                                    with stream:
                                        final_archive.addfile(
                                            copied,
                                            archive_progress.reader(
                                                stream,
                                                before_read=raise_if_cancelled,
                                            ),
                                        )
                                    archive_progress.finish_file()
                                self.disk.require_creation_allowed()
                                raise_if_cancelled()
                            raise_if_cancelled()
                self.disk.require_creation_allowed()
                raise_if_cancelled()

            archive_path = self.storage.staging_archive_path(operation_id, backup_id, "create")
            self.operations.update_stage(operation_id, "repackaging_archive")
            write_archive(archive_path, manifest)
            archive_size = archive_path.stat().st_size
            if max_archive_bytes is not None and archive_size > int(max_archive_bytes):
                raise BackupError(
                    ErrorCode.ARCHIVE_LIMIT_EXCEEDED,
                    "Итоговый archive превышает допустимый размер",
                )
            archive_progress.finish(
                # archive_bytes is one operation-wide monotonic counter. The
                # streamed remote tar and the repackaged tar.gz are different
                # byte streams; the latter may be smaller, so never publish a
                # lower value at the stage boundary.
                archive_bytes=max(transfer_bytes, archive_size),
            )
            self.operations.transition(operation_id, OperationStatus.VERIFYING.value, stage="verifying_staging")
            # SHA-256 is a raw byte pass. It intentionally precedes the one and
            # only TAR member inspection so the same owned member graph can be
            # consumed directly by the inventory builder.
            checksum = self.storage.calculate_checksum(archive_path)
            inspection = verify_archive_with_members(
                archive_path,
                expected_backup_id=backup_id,
                expected_type="server",
            )
            validated = inspection["manifest"]
            if encrypt_password is not None:
                # TAR-инспекция прошла по plain-байтам — теперь staging-архив
                # шифруется на месте (B4VE). .sha256, inventory binding и
                # Catalog обязаны ссылаться на зашифрованные байты, поэтому
                # checksum и archive_size пересчитываются. write_checksum
                # идёт после шифрования (O_EXCL не позволяет перезапись).
                encrypt_in_place(archive_path, encrypt_password)
                encrypt_password = None
                archive_size = archive_path.stat().st_size
                checksum = self.storage.calculate_checksum(archive_path)
            staging_checksum = self.storage.write_checksum(archive_path, checksum)
            inventory_source, inventory_archive = self._managed_inventory_binding(
                backup_id=backup_id,
                backup_type="server",
                server_id=server_id,
                checksum=checksum,
                archive_bytes=archive_size,
            )
            staging_inventory = self._stage_native_archive_inventory(
                archive_path=archive_path,
                inspection=inspection,
                source=inventory_source,
                archive=inventory_archive,
            )
            if staging_inventory is None:
                source_warnings.append({
                    "code": "inventory_pending",
                    "message": "Индекс содержимого Backup будет построен в фоне",
                })
            if source_warnings:
                # Замечания записываются только здесь: пока архив не собран и не
                # проверен, «успех с оговоркой» — не тот результат, о котором
                # можно отчитаться. Запись идёт до блока публикации: там уже
                # держится lock записи операции, а он не реентрантен.
                self.operations.add_warnings(operation_id, source_warnings)
            self.operations.update_stage(operation_id, "publishing_artifact")
            with self.coordinator.acquire_artifact_publish(artifact_ref):
                with self.coordinator.destination_lock(server_id):
                    # Operation record lock is held across the final cancellation
                    # check, Catalog publication, and COMPLETED transition. This
                    # makes request_cancel linearize either before the fence or
                    # after a terminal completed operation.
                    with self.operations.records.locked():
                        current = self.operations.get(operation_id)
                        if current["cancellation"]["requested"]:
                            raise BackupError(ErrorCode.CANCELLED_BY_USER, "Backup отменён пользователем")
                        base_name = server.get("name") or server_id
                        filename = self._available_native_archive_filename(
                            base_name,
                            validated["created_at"],
                            server_id=server_id,
                        )
                        self._assert_filename_available(
                            filename,
                            server_id=server_id,
                        )
                        with self.coordinator.catalog_lock():
                            final_archive, final_checksum = self.storage.publish_pair(
                                archive_path, staging_checksum, backup_id=backup_id,
                                backup_type="server", server_id=server_id,
                            )
                            record = self._catalog_record(
                                manifest=validated, operation_id=operation_id,
                                archive_path=final_archive, checksum_path=final_checksum, checksum=checksum,
                                filename=filename,
                            )
                            self.catalog.commit_published(record, lock_held=True)
                        completed = self.operations.complete_create_locked(
                            operation_id,
                            result_backup_id=backup_id,
                        )
            self._install_or_queue_managed_inventory(
                staging_inventory=staging_inventory,
                archive_path=final_archive,
                checksum_path=final_checksum,
                source=inventory_source,
                archive=inventory_archive,
            )
            self._emit_backup_event(
                operation=completed,
                notifications=profile.get("notifications", {}),
                success=True,
                backup_id=backup_id,
                backup_filename=record["filename"],
                backup_bytes=(record.get("archive") or {}).get("bytes"),
                server_name=str(server.get("name") or server_id),
            )
            return {"operation": completed, "catalog": record}
        except BackupError as exc:
            current = self.operations.get(operation_id)
            if current["status"] not in TERMINAL_STATUSES:
                status = OperationStatus.CANCELLED.value if exc.code == ErrorCode.CANCELLED_BY_USER.value else OperationStatus.FAILED.value
                if status == OperationStatus.CANCELLED.value:
                    cancelled = self.operations.transition(
                        operation_id,
                        status,
                        stage="cancelled",
                    )
                    self._emit_backup_event(
                        operation=cancelled,
                        notifications=profile.get("notifications", {}),
                        success=False,
                        cancelled=True,
                        backup_id=cancelled.get("result_backup_id"),
                        backup_filename=filename,
                        server_name=str(server.get("name") or server_id),
                    )
                else:
                    failed = self.operations.transition(
                        operation_id,
                        status,
                        stage=current.get("stage") or "failed",
                        error=exc.to_safe_error(),
                    )
                    self._emit_backup_event(
                        operation=failed,
                        notifications=profile.get("notifications", {}),
                        success=False,
                        error=exc.to_safe_error().to_dict(),
                        backup_filename=filename,
                        server_name=str(server.get("name") or server_id),
                    )
            raise
        except Exception as exc:
            safe = BackupError(ErrorCode.ARCHIVE_CREATE_FAILED, "Не удалось создать server backup", retryable=True)
            current = self.operations.get(operation_id)
            if current["status"] not in TERMINAL_STATUSES:
                self.operations.transition(operation_id, OperationStatus.FAILED.value, stage=current.get("stage") or "failed", error=safe.to_safe_error())
                self._emit_backup_event(
                    operation=self.operations.get(operation_id),
                    notifications=profile.get("notifications", {}),
                    success=False,
                    error=safe.to_safe_error().to_dict(),
                    backup_filename=filename,
                    server_name=str(server.get("name") or server_id),
                )
            raise safe from exc
        finally:
            if ssh is not None:
                try: ssh.close()
                except Exception: pass
            if staging_created: self.storage.remove_staging(operation_id, "create")
            if backup_permit is not None: backup_permit.release()
            owner.release()

    def create_bot4vps(
        self,
        *,
        request_id: str | None = None,
        purpose: str = "regular",
        mode: str = "manual",
        label: str | None = None,
        locks_held: bool = False,
        initiated_from_telegram: bool = False,
        password: str | None = None,
        encrypt: bool | None = None,
    ) -> dict:
        """Создать локальный backup текущей установки через общий pipeline.

        ``locks_held`` — как в :meth:`create`: вызывающий уже держит maintenance
        и target lock (защитная копия перед Restore Bot4VPS). Источники здесь и
        так фиксированы политикой установки и совпадают со scope восстановления,
        поэтому ``sources_override`` не нужен.
        """
        # Шифрование по умолчанию — свойство цели (backup.bot4vps.encrypt),
        # как в create(): расписание и Telegram не передают encrypt сами;
        # явный пароль без флага тоже означает «зашифровать».
        derived_encrypt = encrypt is None
        if derived_encrypt:
            encrypt = bool(self.config["bot4vps"].get("encrypt")) or bool(password)
        request_id = request_id or f"create-bot4vps-{uuid4().hex}"
        operation_id = new_operation_id()
        owner = self.coordinator.acquire_operation_owner(operation_id)
        target = {"kind": "bot4vps"}
        try:
            operation = self.operations.create(
                operation_type="create",
                target=target,
                request_id=request_id,
                mode=mode,
                operation_id=operation_id,
                initiated_from_telegram=initiated_from_telegram,
            )
        except Exception:
            owner.release()
            raise
        if operation["operation_id"] != operation_id:
            owner.release()
            if operation["status"] == OperationStatus.COMPLETED.value:
                return {
                    "operation": operation,
                    "catalog": self.catalog.get(
                        self._artifact_ref(
                            kind="bot4vps",
                            backup_id=operation["result_backup_id"],
                        )
                    ),
                }
            error = operation.get("error") or {}
            raise BackupError(
                error.get("code", ErrorCode.OPERATION_CONFLICT.value),
                error.get("message", "Create Operation уже существует"),
                retryable=bool(error.get("retryable", True)),
                correlation_id=error.get("correlation_id"),
            )

        backup_permit = None
        staging_created = False
        filename = None
        try:
            policy = resolve_bot4vps_sources()
            if not locks_held:
                backup_permit = self.coordinator.begin_backup(operation_id, "bot4vps")
            self.operations.transition(operation_id, OperationStatus.RUNNING.value, stage="preflight")
            self.disk.require_creation_allowed()
            self.storage.create_staging(operation_id, "create")
            staging_created = True
            backup_id = new_backup_id()
            artifact_ref = self._artifact_ref(kind="bot4vps", backup_id=backup_id)
            self.operations.set_result_backup_id(operation_id, backup_id)
            archive_path = self.storage.staging_archive_path(operation_id, backup_id, "create")
            limits = self.config["bot4vps"]["limits"]
            max_source_bytes = limits.get("max_source_bytes")
            max_archive_bytes = limits.get("max_archive_bytes")
            total_files = 0
            total_source_bytes = 0
            regular_inodes: set[tuple[int, int]] = set()
            source_entries: list[tuple[dict, Path, str, os.stat_result]] = []

            self.operations.update_stage(operation_id, "scanning_sources")
            for index, source in enumerate(policy.sources):
                source_path = Path(source["path"])
                for path, relative, metadata in iter_source_entries(
                    source_path,
                    install_source=index == 0,
                ):
                    if stat.S_ISREG(metadata.st_mode):
                        inode_key = (metadata.st_dev, metadata.st_ino)
                        if metadata.st_nlink > 1 or inode_key in regular_inodes:
                            raise BackupError(
                                ErrorCode.ARCHIVE_SPECIAL_FILE_UNSUPPORTED,
                                "Hardlinks запрещены в archive v1",
                            )
                        regular_inodes.add(inode_key)
                        total_files += 1
                        total_source_bytes += metadata.st_size
                        if max_source_bytes is not None and total_source_bytes > int(max_source_bytes):
                            raise BackupError(ErrorCode.SOURCE_LIMIT_EXCEEDED, "Источник превышает допустимый размер")
                    elif not (
                        stat.S_ISDIR(metadata.st_mode)
                        or stat.S_ISLNK(metadata.st_mode)
                    ):
                        raise BackupError(
                            ErrorCode.ARCHIVE_SPECIAL_FILE_UNSUPPORTED,
                            "Special files запрещены в archive v1",
                        )
                    source_entries.append((source, path, relative, metadata))

            archive_progress = _ArchiveProgress(
                self.operations,
                operation_id,
                total_source_bytes,
            )
            # Как в create(): секрет резолвится максимально поздно (см. там).
            encrypt_password = self._resolve_encryption_password(
                password, encrypt, missing_ok=derived_encrypt
            )
            source_utc_offset = local_utc_offset(operation["created_at"])
            manifest = {
                "manifest_version": 2,
                "backup_id": backup_id,
                "type": "bot4vps",
                "purpose": purpose,
                "mode": mode,
                "label": label,
                "created_at": operation["created_at"],
                "completed_at": utc_timestamp(),
                "archive": {"format": "tar.gz", "encrypted": encrypt_password is not None},
                "producer": {"name": "bot4vps", "version": APP_VERSION},
                "source": {
                    "kind": "bot4vps",
                    "install_path": policy.install_path.as_posix(),
                    "systemd_unit": policy.systemd_unit.as_posix(),
                    "utc_offset": source_utc_offset,
                },
                "sources": [
                    {
                        "path": source["path"],
                        "payload_prefix": "payload/" + source["path"].lstrip("/"),
                        "exclusions": list(source["exclusions"]),
                    }
                    for source in policy.sources
                ],
                "content": {
                    "metadata": {"hardlinks": False},
                    "file_count": total_files,
                    "source_bytes": total_source_bytes,
                },
                "bot4vps": {
                    "version": APP_VERSION,
                    "install_path": policy.install_path.as_posix(),
                    "systemd_unit": policy.systemd_unit.as_posix(),
                },
            }

            self.operations.update_stage(operation_id, "creating_archive")
            self.disk.require_creation_allowed()
            with tarfile.open(archive_path, "w:gz", dereference=False) as archive:
                raw = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                info = tarfile.TarInfo("manifest.json")
                info.mode = 0o600
                info.size = len(raw)
                archive.addfile(info, io.BytesIO(raw))
                for source, path, relative, metadata in source_entries:
                    self.disk.require_creation_allowed()
                    current = path.lstat()
                    if (
                        current.st_dev != metadata.st_dev
                        or current.st_ino != metadata.st_ino
                        or stat.S_IFMT(current.st_mode) != stat.S_IFMT(metadata.st_mode)
                    ):
                        raise BackupError(ErrorCode.SOURCE_PERMISSION_DENIED, "Source Bot4VPS изменился во время backup")
                    prefix = "payload/" + source["path"].lstrip("/")
                    source_root_name = Path(source["path"]).name
                    relative_inside = relative[len(source_root_name):].lstrip("/")
                    arcname = prefix + ("/" + relative_inside if relative_inside else "")
                    tar_info = archive.gettarinfo(str(path), arcname=arcname)
                    if tar_info.isfile():
                        file_descriptor = None
                        try:
                            open_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                            file_descriptor = os.open(path, open_flags)
                            opened = os.fstat(file_descriptor)
                            if (
                                opened.st_dev != metadata.st_dev
                                or opened.st_ino != metadata.st_ino
                                or stat.S_IFMT(opened.st_mode) != stat.S_IFMT(metadata.st_mode)
                            ):
                                raise BackupError(
                                    ErrorCode.SOURCE_PERMISSION_DENIED,
                                    "Source Bot4VPS изменился во время backup",
                                )
                            with os.fdopen(file_descriptor, "rb") as source_stream:
                                file_descriptor = None
                                archive.addfile(
                                    tar_info,
                                    archive_progress.reader(source_stream),
                                )
                        except BackupError:
                            raise
                        except (PermissionError, OSError) as exc:
                            raise BackupError(
                                ErrorCode.SOURCE_PERMISSION_DENIED,
                                "Не удалось прочитать source Bot4VPS",
                            ) from exc
                        finally:
                            if file_descriptor is not None:
                                os.close(file_descriptor)
                        archive_progress.finish_file()
                    else:
                        archive.addfile(tar_info)
                    if max_archive_bytes is not None:
                        try:
                            position = archive.fileobj.tell()
                        except (AttributeError, OSError):
                            position = archive_path.stat().st_size if archive_path.exists() else 0
                        if position > int(max_archive_bytes):
                            raise BackupError(ErrorCode.ARCHIVE_LIMIT_EXCEEDED, "Итоговый archive превышает допустимый размер")

            archive_size = archive_path.stat().st_size
            if max_archive_bytes is not None and archive_size > int(max_archive_bytes):
                raise BackupError(ErrorCode.ARCHIVE_LIMIT_EXCEEDED, "Итоговый archive превышает допустимый размер")
            archive_progress.finish(archive_bytes=archive_size)
            self.operations.transition(operation_id, OperationStatus.VERIFYING.value, stage="verifying_staging")
            checksum = self.storage.calculate_checksum(archive_path)
            inspection = verify_archive_with_members(
                archive_path,
                expected_backup_id=backup_id,
                expected_type="bot4vps",
            )
            validated = inspection["manifest"]
            if encrypt_password is not None:
                # См. create(): plain-инспекция → шифрование на месте →
                # checksum/size по зашифрованным байтам.
                encrypt_in_place(archive_path, encrypt_password)
                encrypt_password = None
                archive_size = archive_path.stat().st_size
                checksum = self.storage.calculate_checksum(archive_path)
            staging_checksum = self.storage.write_checksum(archive_path, checksum)
            inventory_source, inventory_archive = self._managed_inventory_binding(
                backup_id=backup_id,
                backup_type="bot4vps",
                server_id=None,
                checksum=checksum,
                archive_bytes=archive_size,
            )
            staging_inventory = self._stage_native_archive_inventory(
                archive_path=archive_path,
                inspection=inspection,
                source=inventory_source,
                archive=inventory_archive,
            )
            if staging_inventory is None:
                self.operations.add_warnings(operation_id, [{
                    "code": "inventory_pending",
                    "message": "Индекс содержимого Backup будет построен в фоне",
                }])
            self.operations.update_stage(operation_id, "publishing_artifact")
            with self.coordinator.acquire_artifact_publish(artifact_ref):
                with self.coordinator.destination_lock(None):
                    with self.operations.records.locked():
                        current = self.operations.get(operation_id)
                        if current["cancellation"]["requested"]:
                            raise BackupError(ErrorCode.CANCELLED_BY_USER, "Backup отменён пользователем")
                        filename = self._available_native_archive_filename(
                            "Bot4VPS",
                            validated["created_at"],
                            server_id=None,
                        )
                        self._assert_filename_available(
                            filename,
                            server_id=None,
                        )
                        with self.coordinator.catalog_lock():
                            final_archive, final_checksum = self.storage.publish_pair(
                                archive_path,
                                staging_checksum,
                                backup_id=backup_id,
                                backup_type="bot4vps",
                            )
                            record = self._catalog_record(
                                manifest=validated,
                                operation_id=operation_id,
                                archive_path=final_archive,
                                checksum_path=final_checksum,
                                checksum=checksum,
                                filename=filename,
                            )
                            self.catalog.commit_published(record, lock_held=True)
                        completed = self.operations.complete_create_locked(operation_id, result_backup_id=backup_id)
            self._install_or_queue_managed_inventory(
                staging_inventory=staging_inventory,
                archive_path=final_archive,
                checksum_path=final_checksum,
                source=inventory_source,
                archive=inventory_archive,
            )
            self._emit_backup_event(
                operation=completed,
                notifications=self.config["bot4vps"].get("notifications", {}),
                success=True,
                backup_id=backup_id,
                backup_filename=record["filename"],
                backup_bytes=(record.get("archive") or {}).get("bytes"),
                server_name="Bot4VPS",
            )
            return {"operation": completed, "catalog": record}
        except BackupError as exc:
            current = self.operations.get(operation_id)
            if current["status"] not in TERMINAL_STATUSES:
                status = OperationStatus.CANCELLED.value if exc.code == ErrorCode.CANCELLED_BY_USER.value else OperationStatus.FAILED.value
                if status == OperationStatus.CANCELLED.value:
                    cancelled = self.operations.transition(
                        operation_id,
                        status,
                        stage="cancelled",
                    )
                    self._emit_backup_event(
                        operation=cancelled,
                        notifications=self.config["bot4vps"].get("notifications", {}),
                        success=False,
                        cancelled=True,
                        backup_id=cancelled.get("result_backup_id"),
                        backup_filename=filename,
                        server_name="Bot4VPS",
                    )
                else:
                    failed = self.operations.transition(
                        operation_id,
                        status,
                        stage=current.get("stage") or "failed",
                        error=exc.to_safe_error(),
                    )
                    self._emit_backup_event(
                        operation=failed,
                        notifications=self.config["bot4vps"].get("notifications", {}),
                        success=False,
                        error=exc.to_safe_error().to_dict(),
                        backup_filename=filename,
                        server_name="Bot4VPS",
                    )
            raise
        except Exception as exc:
            safe = BackupError(ErrorCode.ARCHIVE_CREATE_FAILED, "Не удалось создать backup Bot4VPS", retryable=True)
            current = self.operations.get(operation_id)
            if current["status"] not in TERMINAL_STATUSES:
                self.operations.transition(operation_id, OperationStatus.FAILED.value, stage=current.get("stage") or "failed", error=safe.to_safe_error())
                self._emit_backup_event(
                    operation=self.operations.get(operation_id),
                    notifications=self.config["bot4vps"].get("notifications", {}),
                    success=False,
                    error=safe.to_safe_error().to_dict(),
                    backup_filename=filename,
                    server_name="Bot4VPS",
                )
            raise safe from exc
        finally:
            if staging_created:
                self.storage.remove_staging(operation_id, "create")
            if backup_permit is not None:
                backup_permit.release()
            owner.release()

    def submit_create(
        self,
        *,
        server_id: str | None = None,
        bot4vps: bool = False,
        request_id: str | None = None,
        label: str | None = None,
        initiated_from_telegram: bool = False,
        password: str | None = None,
        encrypt: bool | None = None,
    ) -> dict:
        """Start a native create workflow in a daemon thread for Web clients."""
        if bot4vps == (server_id is not None):
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Нужно выбрать ровно один target backup",
            )
        if encrypt is True:
            # Синхронная проверка: run() глушит исключения фонового потока, а
            # отказ «защита выбрана, но пароля нет» пользователь должен
            # увидеть сразу, а не в истории операций.
            self._resolve_encryption_password(password, True)
        request_id = request_id or f"web-create-{uuid4().hex}"
        if not bot4vps:
            # Проверка профиля обязана быть синхронной: run() глушит исключения
            # фонового потока, а Operation при отказе не создаётся — иначе клиент
            # получил бы «Не удалось зарегистрировать Backup Operation» вместо
            # настоящей причины (нет источников / профиль не настроен).
            self._require_backup_profile(str(server_id))

        def run() -> None:
            try:
                if bot4vps:
                    self.create_bot4vps(
                        request_id=request_id,
                        label=label,
                        initiated_from_telegram=initiated_from_telegram,
                        password=password,
                        encrypt=encrypt,
                    )
                else:
                    self.create(
                        str(server_id),
                        request_id=request_id,
                        label=label,
                        initiated_from_telegram=initiated_from_telegram,
                        password=password,
                        encrypt=encrypt,
                    )
            except Exception:
                # The native workflow persists its own safe terminal state.
                return

        worker = threading.Thread(
            target=run,
            name=f"backup-create-{request_id[-12:]}",
            daemon=True,
        )
        worker.start()
        deadline = time.monotonic() + 2.0
        operation = None
        while time.monotonic() < deadline:
            operation = self.operations.find_by_request_id(request_id)
            if operation is not None:
                break
            if not worker.is_alive():
                break
            time.sleep(0.01)
        if operation is None:
            raise BackupError(
                ErrorCode.OPERATION_CONFLICT,
                "Не удалось зарегистрировать Backup Operation",
                retryable=True,
            )
        return operation

    def _replay_import_ref(self, operation: dict, backup_id: str) -> ArtifactRef | str:
        """Namespace завершённого import для идемпотентного повтора.

        Destination-import хранит server_id в target, поэтому namespace известен
        точно. Import без destination сохраняет исходный namespace архива, и он
        восстанавливается по Catalog.
        """
        target = operation.get("target") or {}
        server_id = target.get("server_id")
        if isinstance(server_id, str) and server_id:
            return self._artifact_ref(kind="server", backup_id=backup_id, server_id=server_id)
        if target.get("kind") == "bot4vps":
            return self._artifact_ref(kind="bot4vps", backup_id=backup_id)
        return backup_id

    def _protective_backup(
        self,
        *,
        operation_id: str,
        server_id: str | None,
        display_name: str,
        sources: list[str],
        source_ref: ArtifactRef | None,
    ) -> dict:
        """Создать копию затрагиваемых данных; прежнюю копию target удалить.

        Это обычный backup: тот же pipeline, тот же Catalog, тот же тип артефакта.
        Отличий ровно два — источники ограничены тем, что затронет Restore, и
        видимое имя строится как ``<имя установки>_before.restore_<дата>``.

        Защитная копия у target ровно одна. Дата в имени — видимая метка, а не
        разрешение копиям накапливаться: после публикации новой копии удаляются
        **все** прежние ``_before.restore_*`` этого namespace, включая копии
        прошлых дней и историческое `_before.restore_data`. Порядок именно такой —
        сначала публикация, потом удаление: обратный при неудачном backup оставил
        бы установку вообще без «копии до восстановления». Удаление и
        переименование берут те же локи, что и замена при import.
        """
        # Имя нужно до создания копии: конфликт по имени обязан вскрыться раньше,
        # чем начнётся работа. Поэтому дата берётся из текущего момента, а не из
        # created_at ещё не созданного архива — расхождение возможно только при
        # переходе через полночь между этими двумя точками.
        naming_stamp = utc_timestamp()
        filename = self._protective_backup_filename(
            display_name,
            naming_stamp,
        )
        with self.coordinator.destination_lock(server_id):
            occupied = self._find_filename_conflict(filename, server_id=server_id)
            previous = self._managed_protective_copies(
                display_name,
                server_id=server_id,
            )
        if occupied is not None and occupied.get("kind") != "managed":
            raise BackupError(
                ErrorCode.RESTORE_PRECHECK_FAILED,
                f"Имя `{filename}` занято импортированным архивом: "
                "переименуйте его или откажитесь от защитной копии",
            )
        if source_ref is not None and any(
            candidate["ref"] == source_ref for candidate in previous
        ):
            # Восстановление из прежней защитной копии: удалять её нельзя, это и
            # есть источник восстанавливаемых данных, и он держит shared read lock.
            # Переименование архива выводит его из-под `_before.restore_*`, после
            # чего он остаётся обычным backup и новая копия создаётся штатно.
            raise BackupError(
                ErrorCode.RESTORE_PRECHECK_FAILED,
                "Восстановление идёт из прежней защитной копии: "
                "переименуйте архив или откажитесь от защитной копии",
            )

        request_id = f"restore-protective-{operation_id}"
        if server_id is None:
            created = self.create_bot4vps(request_id=request_id, locks_held=True)
        else:
            created = self.create(
                server_id,
                request_id=request_id,
                sources_override=[{"path": path, "exclusions": []} for path in sources],
                locks_held=True,
            )
        record = created["catalog"]
        backup_id = str(record["backup_id"])
        created_ref = self._record_ref(record)

        replaced_backup_ids: list[str] = []
        for candidate in previous:
            with ExitStack() as stack:
                stack.enter_context(self.coordinator.acquire_artifact_delete(candidate["ref"]))
                stack.enter_context(self.coordinator.destination_lock(server_id))
                current = self._find_filename_conflict(
                    candidate["filename"],
                    server_id=server_id,
                    exclude_ref=created_ref,
                )
                if not self._same_filename_conflict(current, candidate):
                    # Запись уже удалили или переименовали: под этим именем теперь
                    # другой артефакт, и удалять его за компанию нельзя.
                    continue
                self._delete_managed_for_replacement(candidate, operation_id=operation_id)
                replaced_backup_ids.append(str(candidate["backup_id"]))
        try:
            renamed = self.rename_managed_archive(created_ref, filename)
        except BackupError as exc:
            raise BackupError(
                ErrorCode.RESTORE_PRECHECK_FAILED,
                f"Защитная копия создана как `{record['filename']}`, "
                f"но имя `{filename}` занять не удалось: {exc.safe_message}",
                details={"protective_backup_id": backup_id},
            ) from exc
        saved_sources = [
            str(path)
            for path in (renamed.get("manifest") or {}).get("source_paths") or ()
            if isinstance(path, str)
        ]
        return {
            "backup_id": backup_id,
            "filename": renamed["filename"],
            "record": renamed,
            # Что реально попало в копию, а не что было запрошено: для Bot4VPS
            # источники задаёт политика установки, и они могут отличаться от плана.
            "sources": saved_sources or list(sources),
            "replaced_backup_ids": replaced_backup_ids,
        }

    @staticmethod
    def _protective_backup_view(protective_result: dict | None) -> dict | None:
        """Что показать о защитной копии: только то, чем можно воспользоваться."""
        if protective_result is None:
            return None
        return {
            "backup_id": protective_result["backup_id"],
            "filename": protective_result["filename"],
            "sources": protective_result["sources"],
            "replaced_backup_ids": protective_result["replaced_backup_ids"],
        }

    @staticmethod
    def _assert_restore_consent(
        *,
        apply: bool,
        protective: bool,
        confirm: bool,
        confirm_without_protective: bool,
    ) -> None:
        """Применение возможно только с явного согласия пользователя.

        Два разных согласия, а не одно: первое — на изменение данных вообще,
        второе — на изменение без защитной копии. Второе никогда не выводится из
        первого: отказ от копии пользователь подтверждает отдельно, иначе
        «применить» молча означало бы «применить без страховки».
        """
        if not apply:
            return
        if not confirm:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Применение восстановления выполняется только после подтверждения",
            )
        if not protective and not confirm_without_protective:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Восстановление без защитной копии требует отдельного подтверждения",
            )

    @staticmethod
    def _restore_selection_contract(
        plan: dict,
        *,
        source: dict,
        mode: str,
        removals: dict | None,
        protective: bool,
    ) -> dict:
        roots = [str(item["root"]) for item in plan.get("roots") or ()]
        contract = {
            "version": RESTORE_SELECTION_VERSION,
            "source": copy.deepcopy(source),
            "selection_mode": str(plan.get("selection_mode")),
            "selected_paths": list(plan.get("selected_paths") or ()),
            "restore_mode": mode,
            "target_root": plan.get("target_root"),
            "effective_plan_digest": effective_restore_plan_digest(plan),
            "delete_set_digest": restore_delete_set_digest(removals),
            "protective_backup": protective,
            "effective_roots": roots[:RESTORE_SELECTION_ROOTS_LIMIT],
            "effective_root_count": len(roots),
            "effective_roots_truncated": len(roots) > RESTORE_SELECTION_ROOTS_LIMIT,
        }
        try:
            validate_restore_selection(contract)
        except ValueError as exc:
            raise BackupError(
                ErrorCode.RESTORE_PRECHECK_FAILED,
                "Не удалось зафиксировать selection восстановления",
            ) from exc
        return contract

    def _prepared_restore_contract(self, operation_id: str | None) -> tuple[dict, dict]:
        if not isinstance(operation_id, str) or not operation_id:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Применение Restore требует prepared_operation_id",
            )
        prepared = self.operations.get(operation_id)
        restore = prepared.get("restore") or {}
        contract = restore.get("selection")
        if (
            prepared.get("type") != "restore"
            or prepared.get("status") != OperationStatus.COMPLETED.value
            or prepared.get("stage") != "prepared"
            or restore.get("mutation_started")
            or not isinstance(contract, dict)
            or contract.get("version") != RESTORE_SELECTION_VERSION
            or not isinstance(contract.get("source"), dict)
        ):
            raise BackupError(
                ErrorCode.RESTORE_PRECHECK_FAILED,
                "Prepared Restore устарел или не содержит selection contract: "
                "выполните подготовку заново",
            )
        try:
            validate_restore_selection(contract)
        except ValueError as exc:
            raise BackupError(
                ErrorCode.RESTORE_PRECHECK_FAILED,
                "Prepared Restore содержит некорректный selection contract: "
                "выполните подготовку заново",
            ) from exc
        return prepared, copy.deepcopy(contract)

    @staticmethod
    def _assert_effective_restore_scope(plan: dict) -> None:
        try:
            assert_online_restore_scope_safe(plan)
        except BackupError as exc:
            if plan.get("selection_mode") != SELECTION_MODE_FULL:
                raise
            details = dict(exc.details)
            details.update({
                "reason": "full_restore_unavailable",
                "full_restore_unavailable": True,
            })
            raise BackupError(
                ErrorCode.RESTORE_PRECHECK_FAILED,
                "Полное восстановление этого бэкапа недоступно: архив содержит "
                "системные файлы, изменение которых может нарушить работу "
                "работающей системы. Пользователю предлагается выбрать "
                "разрешённые элементы для восстановления.",
                details=details,
            ) from exc

    @staticmethod
    def _imported_restore_request_key(entry_key: str, request_id: str) -> str:
        """Scope one imported caller request to its bundle without schema changes."""
        if not isinstance(request_id, str) or not request_id or len(request_id) > 256:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Некорректный request_id Restore",
            )
        digest = hashlib.sha256()
        digest.update(b"bot4vps:imported-restore-request:v1\0")
        digest.update(entry_key.encode("utf-8"))
        digest.update(b"\0")
        digest.update(request_id.encode("utf-8"))
        return f"restore-imported-{digest.hexdigest()}"

    def restore(
        self,
        backup_id: ArtifactRef | str,
        *,
        server_id: str | None = None,
        target_root: str | None = None,
        restore_mode: str = RESTORE_MODE_MERGE,
        protective_backup: bool = True,
        selection_mode: str = SELECTION_MODE_FULL,
        selected_paths=None,
        prepared_operation_id: str | None = None,
        apply: bool = False,
        confirm: bool = False,
        confirm_without_protective: bool = False,
        initiated_from_telegram: bool = False,
        request_id: str | None = None,
        password: str | None = None,
    ) -> dict:
        """Restore a managed Catalog backup through the shared lifecycle."""
        return self._restore_source(
            "managed",
            backup_id,
            server_id=server_id,
            target_root=target_root,
            restore_mode=restore_mode,
            protective_backup=protective_backup,
            selection_mode=selection_mode,
            selected_paths=selected_paths,
            prepared_operation_id=prepared_operation_id,
            apply=apply,
            confirm=confirm,
            confirm_without_protective=confirm_without_protective,
            initiated_from_telegram=initiated_from_telegram,
            request_id=request_id or f"restore-{uuid4().hex}",
            password=password,
        )

    def restore_imported_archive(
        self,
        entry_key: str,
        *,
        server_id: str | None = None,
        target_root: str | None = None,
        restore_mode: str = RESTORE_MODE_MERGE,
        protective_backup: bool = True,
        selection_mode: str = SELECTION_MODE_FULL,
        selected_paths=None,
        prepared_operation_id: str | None = None,
        apply: bool = False,
        confirm: bool = False,
        confirm_without_protective: bool = False,
        initiated_from_telegram: bool = False,
        request_id: str | None = None,
        password: str | None = None,
    ) -> dict:
        """Restore one import addressed only by its existing bundle entry key."""
        caller_request_id = request_id or f"restore-imported-{uuid4().hex}"
        operation_request_id = self._imported_restore_request_key(
            entry_key,
            caller_request_id,
        )
        return self._restore_source(
            "imported",
            entry_key,
            server_id=server_id,
            target_root=target_root,
            restore_mode=restore_mode,
            protective_backup=protective_backup,
            selection_mode=selection_mode,
            selected_paths=selected_paths,
            prepared_operation_id=prepared_operation_id,
            apply=apply,
            confirm=confirm,
            confirm_without_protective=confirm_without_protective,
            initiated_from_telegram=initiated_from_telegram,
            request_id=operation_request_id,
            password=password,
        )

    def _restore_source(
        self,
        source_kind: str,
        source_id: ArtifactRef | str,
        *,
        server_id: str | None = None,
        target_root: str | None = None,
        restore_mode: str = RESTORE_MODE_MERGE,
        protective_backup: bool = True,
        selection_mode: str = SELECTION_MODE_FULL,
        selected_paths=None,
        prepared_operation_id: str | None = None,
        apply: bool = False,
        confirm: bool = False,
        confirm_without_protective: bool = False,
        initiated_from_telegram: bool = False,
        request_id: str,
        password: str | None = None,
    ) -> dict:
        """Подготовить восстановление resolved source и, если разрешено, применить его.

        Порядок подготовки: precheck → план по содержимому архива → чтение target
        (состав замен всегда, инвентаризация корней — только для «чистого»
        режима) → защитная копия.

        При ``apply=False`` подготовка на этом и заканчивается: операция
        завершается ``completed`` со stage ``prepared`` и
        ``restore.mutation_started = false`` — ни один файл на target не переписан
        и не удалён.

        При ``apply=True`` та же подготовка становится preflight применения. К ней
        добавляются проверки, которые нужны только распаковке (возможности tar,
        свободное место, отсутствие symlink в компонентах путей), затем архив
        доставляется на target. Всё это — до mutation boundary: доставка самая
        вероятная точка отказа, и она обязана падать, пока target не изменён.
        Дальше ``mark_restore_mutation_started`` (отмена запрещена), удаление
        рассчитанного delete-set для ``clean``, распаковка, проверка результата и
        ``completed`` со stage ``applied``.

        Restore адресует установку, а не «куда-нибудь»: серверный архив
        восстанавливается на тот сервер, в namespace которого он лежит.
        Перенос в другое место — это migrate, отдельная операция.
        """
        from core.ssh import create_ssh_client, detect_tar_capability, exec_sudo

        apply_changes = bool(apply)
        prepared_operation = None
        prepared_contract = None
        if apply_changes:
            prepared_operation, prepared_contract = self._prepared_restore_contract(
                prepared_operation_id
            )
            mode = prepared_contract["restore_mode"]
            protective = prepared_contract["protective_backup"]
            target_root = prepared_contract["target_root"]
            selection_mode = prepared_contract["selection_mode"]
            selected_paths = list(
                prepared_contract["selected_paths"]
            )
        else:
            if prepared_operation_id is not None:
                raise BackupError(
                    ErrorCode.INVALID_REQUEST,
                    "prepared_operation_id используется только при применении Restore",
                )
            mode = normalize_restore_mode(restore_mode)
            protective = bool(protective_backup)
            selection_mode = normalize_selection_mode(selection_mode)
        request_id = request_id or f"restore-{uuid4().hex}"

        # Согласие проверяется до регистрации операции: запрос без подтверждения
        # не должен оставлять в истории ни одной записи.
        self._assert_restore_consent(
            apply=apply_changes,
            protective=protective,
            confirm=confirm,
            confirm_without_protective=confirm_without_protective,
        )

        # Идемпотентность запроса: повторный request_id не должен запускать вторую
        # Restore-операцию — ни рядом с активной, ни после её терминального
        # состояния. Дедупликация Operation store срабатывает только на активных
        # записях, поэтому проверка стоит здесь и покрывает историю.
        existing = self.operations.find_by_request_id(
            request_id,
            operation_type="restore",
        )
        if existing is not None:
            return {"operation": existing, "duplicate": True}

        import_permit = None
        resolved_import = None
        artifact_ref = None
        decrypted_archive: Path | None = None
        try:
            if source_kind == "managed":
                ref = self._requested_ref(source_id, server_id)
                record = self.catalog.get(ref)
                artifact_ref = self._record_ref(record)
                artifact_contract = {
                    "kind": artifact_ref.kind,
                    "backup_id": artifact_ref.backup_id,
                }
                if artifact_ref.kind == "server":
                    artifact_contract["server_id"] = artifact_ref.server_id
                source_contract = {
                    "kind": "managed",
                    "artifact": artifact_contract,
                }
                if artifact_ref.kind == "bot4vps":
                    target_server_id = None
                else:
                    target_server_id = str(artifact_ref.server_id)
                if record.get("archive", {}).get("encrypted"):
                    if initiated_from_telegram:
                        # ТЗ: TG-restore зашифрованного — чистая ошибка с
                        # подсказкой; ввод пароля в Telegram не делаем.
                        raise BackupError(
                            ErrorCode.ENCRYPTION_PASSWORD_REQUIRED,
                            "Архив зашифрован: восстановление зашифрованных "
                            "резервных копий доступно через Web-интерфейс",
                        )
                    encrypted_file = self.storage.resolve_key(record["storage"]["key"])
                    if not encrypted_file.is_file():
                        raise BackupError(
                            ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE,
                            "Опубликованный archive не найден",
                            retryable=True,
                        )
                    # Расшифровка ДО регистрации операции и границы мутаций:
                    # неверный пароль — чистый отказ без записи в истории.
                    decrypted_archive = self._decrypt_restore_archive(
                        encrypted_file, password
                    )
            elif source_kind == "imported":
                if not isinstance(source_id, str):
                    raise BackupError(
                        ErrorCode.INVALID_REQUEST,
                        "Некорректный entry_key импортированного архива",
                    )
                import_permit = self.coordinator.acquire_import_read(
                    source_id,
                    server_id=server_id,
                )
                resolved_import = self.storage.resolve_import_bundle(
                    source_id,
                    server_id=server_id,
                )
                record = resolved_import["publication"]
                destination = record.get("destination") or {}
                if destination.get("scope") == "bot4vps":
                    target_server_id = None
                    destination_contract = {"scope": "bot4vps"}
                elif destination.get("scope") == "server" and isinstance(
                    destination.get("server_id"), str
                ):
                    target_server_id = destination["server_id"]
                    destination_contract = {
                        "scope": "server",
                        "server_id": target_server_id,
                    }
                else:
                    raise BackupError(
                        ErrorCode.STORAGE_BACKEND_ERROR,
                        "Import bundle содержит некорректный destination",
                    )
                source_contract = {
                    "kind": "imported",
                    "entry_key": resolved_import["entry_key"],
                    "destination": destination_contract,
                }
                if record.get("encrypted"):
                    if initiated_from_telegram:
                        # ТЗ: TG-restore зашифрованного — чистая ошибка с
                        # подсказкой; ввод пароля в Telegram не делаем.
                        raise BackupError(
                            ErrorCode.ENCRYPTION_PASSWORD_REQUIRED,
                            "Архив зашифрован: восстановление зашифрованных "
                            "резервных копий доступно через Web-интерфейс",
                        )
                    encrypted_file = resolved_import["archive"]
                    if not encrypted_file.is_file():
                        raise BackupError(
                            ErrorCode.ARTIFACT_NOT_FOUND,
                            "Импортированный архив не найден",
                        )
                    # Расшифровка ДО регистрации операции и границы мутаций:
                    # неверный пароль — чистый отказ без записи в истории.
                    decrypted_archive = self._decrypt_restore_archive(
                        encrypted_file, password
                    )
            else:
                raise BackupError(
                    ErrorCode.INVALID_REQUEST,
                    "Некорректный источник Restore",
                )

            if (
                prepared_contract is not None
                and prepared_contract["source"] != source_contract
            ):
                raise BackupError(
                    ErrorCode.RESTORE_PRECHECK_FAILED,
                    "Prepared Restore относится к другому source: "
                    "выполните подготовку заново",
                )

            if target_server_id is None:
                if mode == RESTORE_MODE_CLEAN:
                    raise BackupError(
                        ErrorCode.RESTORE_PRECHECK_FAILED,
                        "Для Bot4VPS доступно только обычное восстановление: "
                        "«чистое» удалило бы файлы работающей установки",
                    )
                target = {"kind": "bot4vps"}
                target_key = "bot4vps"
                target_server = None
                display_name = "Bot4VPS"
            else:
                target_server = find_server(target_server_id)
                if target_server is None:
                    raise BackupError(
                        ErrorCode.SOURCE_NOT_FOUND,
                        "Сервер восстановления не найден",
                    )
                target = {"kind": "server", "server_id": target_server_id}
                target_key = f"server:{target_server_id}"
                display_name = str(target_server.get("name") or target_server_id)

            if (
                prepared_operation is not None
                and prepared_operation.get("target") != target
            ):
                raise BackupError(
                    ErrorCode.RESTORE_PRECHECK_FAILED,
                    "Prepared Restore относится к другому target: "
                    "выполните подготовку заново",
                )

            # Настройки push для Restore берём прямо из сырого профиля целевого
            # сервера и нормализуем только notifications. Historical Manifest
            # metadata импортированного архива здесь намеренно не участвует.
            restore_notifications = (
                normalize_notifications(
                    (target_server.get("backup") or {}).get("notifications")
                )
                if target_server is not None
                else {}
            )
        except Exception:
            if import_permit is not None:
                import_permit.release()
            self._discard_decrypted_restore_archive(decrypted_archive)
            raise

        operation_id = new_operation_id()
        owner = self.coordinator.acquire_operation_owner(operation_id)
        try:
            operation = self.operations.create(
                operation_type="restore",
                target=target,
                request_id=request_id,
                mode="manual",
                operation_id=operation_id,
                initiated_from_telegram=initiated_from_telegram,
            )
        except Exception:
            if import_permit is not None:
                import_permit.release()
            self._discard_decrypted_restore_archive(decrypted_archive)
            owner.release()
            raise
        if operation["operation_id"] != operation_id:
            # Активная операция с тем же логическим запросом уже идёт.
            if import_permit is not None:
                import_permit.release()
            self._discard_decrypted_restore_archive(decrypted_archive)
            owner.release()
            return {"operation": operation, "duplicate": True}

        permit = None
        ssh = None
        warnings: list[str] = []
        roots: list[str] = []
        clean_roots: list[str] = []
        member_list_path: Path | None = None
        remote_archive: str | None = None
        remote_member_list: str | None = None
        protective_result = None
        preflight_conflicts = None
        extraction_result = None
        verification = None

        def mutation_failure(exc: BackupError | None = None) -> BackupError:
            """Отказ после mutation boundary — никогда не precheck и не успех.

            К ошибке прикладывается состояние target: после mutation откат
            автоматически не делается, и пользователю нужны корни, режим и имя
            защитной копии, из которой он может вернуться.
            """
            details = dict(exc.details) if exc is not None else {}
            details.setdefault("target_state", "partially_modified_or_unknown")
            details.setdefault("roots", list(roots))
            details.setdefault("mode", mode)
            details.setdefault(
                "protective_backup",
                None if protective_result is None else protective_result["filename"],
            )
            code = ErrorCode.RESTORE_APPLY_FAILED.value
            if exc is not None and exc.code in {
                ErrorCode.RESTORE_APPLY_FAILED.value,
                ErrorCode.RESTORE_METADATA_FAILED.value,
            }:
                code = exc.code
            return BackupError(
                code,
                (
                    "Восстановление прервано после начала изменения target"
                    if exc is None
                    else exc.safe_message
                ),
                correlation_id=None if exc is None else exc.correlation_id,
                details=details,
            )

        try:
            permit = self.coordinator.begin_maintenance(
                operation_id,
                "restore",
                target_key=target_key,
            )
            self.operations.transition(
                operation_id,
                OperationStatus.RUNNING.value,
                stage="preflight",
            )
            if source_kind == "imported":
                planned = self._plan_imported_restore_resolved(
                    resolved_import,
                    target_root=target_root,
                    # Расшифрованный в начале операции temp: план строится по
                    # plain-байтам, тот же файл позже доставляется на target.
                    archive_override=decrypted_archive,
                )
            else:
                planned = self._plan_managed_restore_resolved(
                    record,
                    artifact_ref,
                    target_root=target_root,
                    # Расшифрованный в начале операции temp: план строится по
                    # plain-байтам, тот же файл позже доставляется на target.
                    archive_override=decrypted_archive,
                )
            full_plan = planned["plan"]
            plan = build_effective_restore_plan(
                full_plan,
                selection_mode=selection_mode,
                selected_paths=selected_paths,
            )
            self._assert_effective_restore_scope(plan)
            if target_server_id is None:
                # Локальный apply не перезаписывает живое координационное
                # состояние машины (maintenance/indexer-jobs). Фильтр стоит
                # ДО digest и применяется одинаково на prepare и на apply —
                # иначе prepared-контракт разошёлся бы между фазами.
                plan = filter_self_restore_live_state(plan, self.data_root)
            plan_digest = effective_restore_plan_digest(plan)
            if (
                prepared_contract is not None
                and plan_digest != prepared_contract["effective_plan_digest"]
            ):
                raise BackupError(
                    ErrorCode.RESTORE_PRECHECK_FAILED,
                    "Содержимое Restore отличается от prepared plan: "
                    "выполните подготовку заново",
                )
            roots = [item["root"] for item in plan["roots"]]
            clean_roots = list(plan["clean_roots"])
            effective_preview = build_preview_tree(plan["entries"], roots=roots)
            selection = protective_sources(plan, mode=mode)
            protective_paths = list(selection["paths"])
            removals = None
            archive_bytes = 0
            if apply_changes:
                # Размер тех же bytes нужен до мутации для проверки места. Imported
                # archive уже разрешён под непрерывным shared import lock; managed
                # остаётся неизменяемым опубликованным Catalog artifact.
                archive_file = (
                    (decrypted_archive or resolved_import["archive"])
                    if source_kind == "imported"
                    else (decrypted_archive or self.storage.resolve_key(record["storage"]["key"]))
                )
                if not archive_file.is_file():
                    raise BackupError(
                        (
                            ErrorCode.ARTIFACT_NOT_FOUND
                            if source_kind == "imported"
                            else ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE
                        ),
                        (
                            "Импортированный архив не найден"
                            if source_kind == "imported"
                            else "Опубликованный archive не найден"
                        ),
                        retryable=source_kind == "managed",
                    )
                archive_bytes = archive_file.stat().st_size
            # Что из архива на target уже есть: без этого «будут заменены» обещало
            # бы замену и там, где файл только появится. Каталоги не спрашиваем —
            # в сводку они не попадают.
            archive_paths = [
                str(entry["path"])
                for entry in plan.get("entries") or ()
                if entry.get("type") != "directory"
            ]

            if target_server is not None:
                self.operations.update_stage(operation_id, "reading_target")
                ssh = create_ssh_client(target_server)
                if mode == RESTORE_MODE_CLEAN:
                    inventory = (
                        read_target_inventory(
                            ssh,
                            target_server,
                            clean_roots,
                            exec_sudo=exec_sudo,
                        )
                        if clean_roots
                        else []
                    )
                    removals = planned_removals(plan, inventory, mode=mode)
                    assert_online_restore_scope_safe(
                        plan,
                        delete_paths=removals.get("delete") or (),
                    )
                if prepared_contract is not None and restore_delete_set_digest(
                    removals
                ) != prepared_contract["delete_set_digest"]:
                    raise BackupError(
                        ErrorCode.RESTORE_PRECHECK_FAILED,
                        "Состояние target отличается от prepared delete-set: "
                        "выполните подготовку заново",
                    )
                existing = existing_archive_paths(
                    ssh,
                    target_server,
                    archive_paths,
                    exec_sudo=exec_sudo,
                )
                if protective:
                    protective_paths = existing_target_paths(
                        ssh,
                        target_server,
                        protective_paths,
                        exec_sudo=exec_sudo,
                    )
                if apply_changes:
                    # Границы, которые нужны только распаковке. Стоят здесь, на
                    # уже открытом соединении и ДО защитной копии: отказ по
                    # возможностям tar или по свободному месту обходится дешевле,
                    # чем тот же отказ после создания копии.
                    assert_restore_capability(detect_tar_capability(ssh, target_server))
                    assert_no_symlink_components(
                        ssh,
                        target_server,
                        roots,
                        exec_sudo=exec_sudo,
                    )
                    # Корней недостаточно: symlink на промежуточном компоненте
                    # ВНУТРИ корня tar проходит насквозь и пишет за пределы
                    # корня молча, с кодом 0.
                    assert_no_symlink_ancestors(
                        ssh,
                        target_server,
                        plan,
                        exec_sudo=exec_sudo,
                    )
                    assert_free_space(
                        ssh,
                        target_server,
                        restore_space_requirements(plan, archive_bytes=archive_bytes),
                        exec_sudo=exec_sudo,
                    )

                # Process preflight is an advisory snapshot for both phases:
                # preparation shows it to the user, while apply obtains a fresh
                # snapshot before the mutation boundary.  It is intentionally
                # not treated as a prediction of actual tar skips.
                self.operations.update_stage(operation_id, "process_preflight")
                preflight_conflicts = {
                    "at": utc_timestamp(),
                    **preflight_restore_processes(
                        ssh,
                        target_server,
                        plan=plan,
                        exec_sudo=exec_sudo,
                    ),
                    "race_disclaimer": (
                        "Это снимок состояния: target может измениться до extraction"
                    ),
                }
                self.operations.attach_restore_metadata(
                    operation_id,
                    "preflight_conflicts",
                    preflight_conflicts,
                )
                if preflight_conflicts.get("match_count"):
                    warnings.append(
                        "Preflight обнаружил executable, используемый работающим "
                        "процессом; состояние может измениться до Restore"
                    )
                if apply_changes:
                    if not clear_stale_remote_archives(
                        ssh,
                        target_server,
                        exec_sudo=exec_sudo,
                    ):
                        warnings.append(
                            "Временные архивы прошлых восстановлений на сервере "
                            "не удалены"
                        )
                ssh.close()
                ssh = None
            else:
                # Bot4VPS восстанавливается в собственную установку: target локален.
                if apply_changes:
                    # Те же границы, что у SSH-пути, но без транспорта — и,
                    # как там, ДО защитной копии: отказ по symlink или месту
                    # обходится дешевле самой копии. Возможности tar не
                    # проверяются: команда та же, что создала архив.
                    assert_no_symlink_components_local(roots)
                    assert_no_symlink_ancestors_local(plan)
                    assert_free_space_local(
                        restore_space_requirements_local(plan)
                    )
                else:
                    # Предупреждения prepare: понижение/повышение версии кода,
                    # смена режима юнита (web+tg ↔ tg-only) и порта.
                    warnings.extend(
                        prepare_warnings_for(
                            self,
                            source_kind=source_kind,
                            record=record,
                            resolved_import=resolved_import,
                            decrypted_archive=decrypted_archive,
                            plan=plan,
                        )
                    )
                existing = existing_local_paths(archive_paths)

            # Сводка плана сохраняется в самой Operation, иначе она не выживет:
            # подготовка идёт в фоновом потоке, и её результат нигде больше не
            # персистится. Это только информация — ни разрешением на применение,
            # ни признаком его начала сводка не является.
            summary = restore_plan_summary(plan, removals, mode=mode, existing=existing)
            self.operations.attach_restore_plan(operation_id, summary)
            selection_contract = self._restore_selection_contract(
                plan,
                source=source_contract,
                mode=mode,
                removals=removals,
                protective=protective,
            )
            if (
                prepared_contract is not None
                and selection_contract != prepared_contract
            ):
                raise BackupError(
                    ErrorCode.RESTORE_PRECHECK_FAILED,
                    "Prepared Restore больше не соответствует effective plan: "
                    "выполните подготовку заново",
                )
            self.operations.attach_restore_selection(
                operation_id,
                prepared_contract or selection_contract,
            )

            if protective:
                if target_server is not None and not protective_paths:
                    warnings.append(
                        "Защитная копия не создана: ни один из затрагиваемых "
                        "путей на сервере не найден"
                    )
                else:
                    self.operations.update_stage(operation_id, "protective_backup")
                    protective_result = self._protective_backup(
                        operation_id=operation_id,
                        server_id=target_server_id,
                        display_name=display_name,
                        sources=protective_paths,
                        source_ref=artifact_ref if source_kind == "managed" else None,
                    )
                    self.operations.attach_protective_backup(
                        operation_id,
                        protective_result["backup_id"],
                    )
            if selection["widened"]:
                warnings.append(
                    "Защитная копия расширена до корней восстановления: "
                    "затронутых объектов верхнего уровня слишком много"
                )

            if not apply_changes:
                if warnings:
                    self.operations.add_warnings(
                        operation_id,
                        [
                            {"code": "restore_warning", "message": message}
                            for message in warnings
                        ],
                    )
                completed = self.operations.transition(
                    operation_id,
                    OperationStatus.COMPLETED.value,
                    stage="prepared",
                )
                return {
                    "operation": completed,
                    "archive": record,
                    "mode": mode,
                    "plan": plan,
                    "preview": effective_preview,
                    "delete": removals,
                    "protective_backup": self._protective_backup_view(protective_result),
                    "applied": False,
                    "warnings": warnings,
                    "notice": (
                        "Restore подготовлен: план построен, защитная копия обработана, "
                        "данные на target не изменялись."
                    ),
                }

            if target_server is None:
                # Локальное применение self-restore: раннер вне процесса
                # (переживает остановку сервиса) + финализация по его
                # state.json. Единый путь для Web и CLI.
                return apply_self_restore(
                    self,
                    operation_id=operation_id,
                    plan=plan,
                    roots=roots,
                    archive_file=archive_file,
                    decrypted_archive=decrypted_archive,
                    mode=mode,
                    warnings=warnings,
                    protective_result=protective_result,
                    backup_filename=record.get("filename"),
                )

            # ── доставка архива: последний шаг, который ещё можно отменить ──
            self.operations.update_stage(operation_id, "uploading_archive")
            self.operations.update_progress(
                operation_id,
                percent=30.0,
                estimated_total_bytes=archive_bytes,
            )
            remote_archive = remote_archive_path(operation_id)
            remote_member_list = remote_member_list_path(operation_id)
            member_list_path, _ = create_restore_member_list(plan, operation_id)
            ssh = create_ssh_client(target_server)
            delivered = {"bytes": 0}

            def upload_progress(transferred: int, total: int) -> None:
                # Реже, чем раз в мегабайт, запись прогресса не имеет смысла:
                # каждая запись — атомарная перезапись файла операции.
                if transferred < total and transferred - delivered["bytes"] < 1024 * 1024:
                    return
                delivered["bytes"] = transferred
                fraction = 0.0 if not total else min(1.0, transferred / total)
                self.operations.update_progress(
                    operation_id,
                    processed_bytes=int(transferred),
                    percent=30.0 + 20.0 * fraction,
                )

            try:
                if source_kind == "imported":
                    # The permit was acquired before physical validation and stays
                    # held through transfer, so replacement cannot swap the bytes.
                    archive_file = decrypted_archive or resolved_import["archive"]
                    if not archive_file.is_file():
                        raise BackupError(
                            ErrorCode.ARTIFACT_NOT_FOUND,
                            "Импортированный архив не найден",
                        )
                    upload_restore_archive(
                        ssh,
                        archive_file,
                        remote_archive,
                        progress_cb=upload_progress,
                    )
                    import_permit.release()
                    import_permit = None
                else:
                    with self.coordinator.acquire_artifact_read(artifact_ref):
                        archive_file = (
                            decrypted_archive
                            or self.storage.resolve_key(record["storage"]["key"])
                        )
                        if not archive_file.is_file():
                            raise BackupError(
                                ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE,
                                "Опубликованный archive не найден",
                                retryable=True,
                            )
                        upload_restore_archive(
                            ssh,
                            archive_file,
                            remote_archive,
                            progress_cb=upload_progress,
                        )
                upload_restore_member_list(
                    ssh,
                    member_list_path,
                    remote_member_list,
                )
            except Exception:
                discard_remote_restore_inputs(
                    ssh,
                    target_server,
                    [remote_archive, remote_member_list],
                    exec_sudo=exec_sudo,
                )
                raise
            self.operations.update_progress(operation_id, percent=50.0)

            # ─────────────── DESTRUCTIVE BOUNDARY ───────────────
            # Отмена проверяется внутри mark_restore_mutation_started: проверка и
            # постановка признака мутации обязаны быть атомарными, иначе
            # request_cancel мог бы встать между ними и остаться «принятой
            # отменой» уже во время изменения target. Отсюда и до конца операции
            # отмена запрещена.
            self.operations.mark_restore_mutation_started(operation_id)

            try:
                removed = 0
                if removals is not None:
                    planned_delete = [str(path) for path in removals.get("delete") or ()]
                    if planned_delete:
                        removed = delete_target_paths(
                            ssh,
                            target_server,
                            planned_delete,
                            roots=clean_roots,
                            exec_sudo=exec_sudo,
                            progress_cb=lambda done, total: self.operations.update_progress(
                                operation_id,
                                percent=50.0 + 10.0 * (done / total if total else 1.0),
                            ),
                        )
                self.operations.update_progress(operation_id, percent=60.0)
                extraction_result = extract_restore_archive(
                    ssh,
                    target_server,
                    remote_archive=remote_archive,
                    remote_member_list=remote_member_list,
                    roots=roots,
                    plan=plan,
                    exec_sudo=exec_sudo,
                )
                skipped_members = list(extraction_result.get("skipped") or [])
                verification_plan = filtered_restore_verification_plan(
                    plan,
                    skipped_members,
                )
                extraction_projection = {
                    "tar_exit_code": int(extraction_result.get("tar_exit_code") or 0),
                    "skipped_count": len(skipped_members),
                    "diagnostics": list(extraction_result.get("diagnostics") or [])[:256],
                }
                self.operations.attach_restore_metadata(
                    operation_id,
                    "skipped_members",
                    verification_plan.get("verification_skips") or skipped_members,
                )
                self.operations.attach_restore_metadata(
                    operation_id,
                    "extraction",
                    extraction_projection,
                )
                for skipped in skipped_members:
                    warnings.append(
                        f"{skipped['path']} используется работающим процессом; "
                        "остановите соответствующий сервис вручную и повторите Restore"
                    )
                self.operations.update_progress(operation_id, percent=90.0)
                self.operations.transition(
                    operation_id,
                    OperationStatus.VERIFYING.value,
                    stage="post_restore_verify",
                )
                verification = verify_applied_restore(
                    ssh,
                    target_server,
                    plan=verification_plan,
                    removals=removals,
                    exec_sudo=exec_sudo,
                )
                self.operations.attach_restore_metadata(
                    operation_id,
                    "verification",
                    verification,
                )
                if verification["missing_count"] or verification["leftover_count"]:
                    raise BackupError(
                        ErrorCode.RESTORE_APPLY_FAILED,
                        "Восстановление применено не полностью: результат на "
                        "сервере не совпал с планом",
                        details={"phase": "verify", **verification},
                    )
                self.operations.update_progress(operation_id, percent=95.0)
            except BackupError as exc:
                raise mutation_failure(exc) from exc
            except Exception as exc:
                raise mutation_failure() from exc

            # Уборка после восстановления: данные target уже на месте, поэтому
            # оставшийся временный архив — предупреждение, а не отказ.
            if not discard_remote_restore_inputs(
                ssh,
                target_server,
                [remote_archive, remote_member_list],
                exec_sudo=exec_sudo,
            ):
                warnings.append(
                    "Временный архив или trusted member list на сервере не удалён"
                )

            if warnings:
                self.operations.add_warnings(
                    operation_id,
                    [
                        {"code": "restore_warning", "message": message}
                        for message in warnings
                    ],
                )
            completed = self.operations.transition(
                operation_id,
                OperationStatus.COMPLETED.value,
                stage="applied",
            )
            self._emit_restore_event(
                operation=completed,
                notifications=restore_notifications,
                success=True,
                mutation_started=True,
                backup_filename=record.get("filename"),
                server_name=display_name,
                server_id=target_server_id,
                mode=mode,
                protective_backup=protective_result["filename"] if protective_result else None,
            )
            return {
                "operation": completed,
                "archive": record,
                "mode": mode,
                "plan": plan,
                "preview": effective_preview,
                "delete": removals,
                "protective_backup": self._protective_backup_view(protective_result),
                "applied": True,
                "removed": removed,
                "verification": verification,
                "warnings": warnings,
                "notice": (
                    "Restore применён: файлы из backup записаны на target, "
                    "результат проверен."
                ),
            }
        except BackupError as exc:
            current = self.operations.get(operation_id)
            if current["status"] not in TERMINAL_STATUSES:
                status = (
                    OperationStatus.CANCELLED.value
                    if exc.code == ErrorCode.CANCELLED_BY_USER.value
                    else OperationStatus.FAILED.value
                )
                if status == OperationStatus.CANCELLED.value:
                    cancelled = self.operations.transition(
                        operation_id,
                        status,
                        stage="cancelled",
                    )
                    self._emit_restore_event(
                        operation=cancelled,
                        notifications=restore_notifications,
                        success=False,
                        cancelled=True,
                        mutation_started=bool((cancelled.get("restore") or {}).get("mutation_started")),
                        backup_filename=record.get("filename"),
                        server_name=display_name,
                        server_id=target_server_id,
                        mode=mode,
                        protective_backup=protective_result["filename"] if protective_result else None,
                    )
                else:
                    failed = self.operations.transition(
                        operation_id,
                        status,
                        stage=current.get("stage") or "failed",
                        error=exc.to_safe_error(),
                    )
                    # Провал подготовки обычно не рассылается: Telegram-origin
                    # должен получить его так же, как apply и terminal cancel.
                    if apply_changes or bool(failed.get("initiated_from_telegram")):
                        self._emit_restore_event(
                            operation=failed,
                            notifications=restore_notifications,
                            success=False,
                            mutation_started=bool((failed.get("restore") or {}).get("mutation_started")),
                            error=exc.to_safe_error().to_dict(),
                            backup_filename=record.get("filename"),
                            server_name=display_name,
                            server_id=target_server_id,
                            mode=mode,
                            protective_backup=protective_result["filename"] if protective_result else None,
                        )
            raise
        except Exception as exc:
            # После mutation boundary «не удалось подготовить» — ложь: target уже
            # изменён, и operation обязана это назвать.
            current = self.operations.get(operation_id)
            if (current.get("restore") or {}).get("mutation_started"):
                safe = mutation_failure()
            else:
                safe = BackupError(
                    ErrorCode.RESTORE_PRECHECK_FAILED,
                    "Не удалось подготовить восстановление",
                    retryable=True,
                )
            if current["status"] not in TERMINAL_STATUSES:
                failed = self.operations.transition(
                    operation_id,
                    OperationStatus.FAILED.value,
                    stage=current.get("stage") or "failed",
                    error=safe.to_safe_error(),
                )
                if apply_changes or bool(failed.get("initiated_from_telegram")):
                    self._emit_restore_event(
                        operation=failed,
                        notifications=restore_notifications,
                        success=False,
                        mutation_started=bool((failed.get("restore") or {}).get("mutation_started")),
                        error=safe.to_safe_error().to_dict(),
                        backup_filename=record.get("filename"),
                        server_name=display_name,
                        server_id=target_server_id,
                        mode=mode,
                        protective_backup=protective_result["filename"] if protective_result else None,
                    )
            raise safe from exc
        finally:
            if (
                ssh is not None
                and target_server is not None
                and (remote_archive or remote_member_list)
            ):
                discard_remote_restore_inputs(
                    ssh,
                    target_server,
                    [remote_archive, remote_member_list],
                    exec_sudo=exec_sudo,
                )
            if ssh is not None:
                try:
                    ssh.close()
                except Exception:
                    pass
            if member_list_path is not None:
                try:
                    member_list_path.unlink(missing_ok=True)
                except OSError:
                    pass
            # Расшифрованные байты не переживают операцию — временный
            # staging-каталог удаляется при любом исходе.
            self._discard_decrypted_restore_archive(decrypted_archive)
            if permit is not None:
                permit.release()
            if import_permit is not None:
                import_permit.release()
            owner.release()

    def submit_restore(
        self,
        backup_id: ArtifactRef | str,
        *,
        server_id: str | None = None,
        target_root: str | None = None,
        restore_mode: str = RESTORE_MODE_MERGE,
        protective_backup: bool = True,
        selection_mode: str = SELECTION_MODE_FULL,
        selected_paths=None,
        prepared_operation_id: str | None = None,
        apply: bool = False,
        confirm: bool = False,
        confirm_without_protective: bool = False,
        initiated_from_telegram: bool = False,
        request_id: str | None = None,
        password: str | None = None,
    ) -> dict:
        """Запустить Restore в фоне и вернуть зарегистрированную Operation.

        Отказы, которые видны без SSH (неизвестный режим, отсутствующий архив,
        «чистый» режим для Bot4VPS, отсутствие подтверждения), проверяются
        синхронно: фоновый поток глушит исключения, и иначе клиент получил бы
        «операция не зарегистрирована» вместо настоящей причины.
        """
        apply_changes = bool(apply)
        if apply_changes:
            _, prepared_contract = self._prepared_restore_contract(
                prepared_operation_id
            )
            mode = prepared_contract["restore_mode"]
            consent_protective = prepared_contract["protective_backup"]
        else:
            mode = normalize_restore_mode(restore_mode)
            selection_mode = normalize_selection_mode(selection_mode)
            consent_protective = bool(protective_backup)
        self._assert_restore_consent(
            apply=apply_changes,
            protective=consent_protective,
            confirm=confirm,
            confirm_without_protective=confirm_without_protective,
        )
        request_id = request_id or f"web-restore-{uuid4().hex}"
        ref = self._requested_ref(backup_id, server_id)
        record = self.catalog.get(ref)
        if record.get("type") == "bot4vps":
            if mode == RESTORE_MODE_CLEAN:
                raise BackupError(
                    ErrorCode.RESTORE_PRECHECK_FAILED,
                    "Для Bot4VPS доступно только обычное восстановление: "
                    "«чистое» удалило бы файлы работающей установки",
                )

        def run() -> None:
            try:
                self.restore(
                    ref,
                    target_root=target_root,
                    restore_mode=mode,
                    protective_backup=protective_backup,
                    selection_mode=selection_mode,
                    selected_paths=selected_paths,
                    prepared_operation_id=prepared_operation_id,
                    apply=apply_changes,
                    confirm=confirm,
                    confirm_without_protective=confirm_without_protective,
                    initiated_from_telegram=initiated_from_telegram,
                    request_id=request_id,
                    password=password,
                )
            except Exception:
                # Terminal state Operation уже сохранён самим restore().
                return

        worker = threading.Thread(
            target=run,
            name=f"backup-restore-{request_id[-12:]}",
            daemon=True,
        )
        worker.start()
        deadline = time.monotonic() + 2.0
        operation = None
        while time.monotonic() < deadline:
            operation = self.operations.find_by_request_id(
                request_id,
                operation_type="restore",
            )
            if operation is not None:
                break
            if not worker.is_alive():
                break
            time.sleep(0.01)
        if operation is None:
            raise BackupError(
                ErrorCode.OPERATION_CONFLICT,
                "Не удалось зарегистрировать Restore Operation",
                retryable=True,
            )
        return operation

    def submit_imported_restore(
        self,
        entry_key: str,
        *,
        server_id: str | None = None,
        target_root: str | None = None,
        restore_mode: str = RESTORE_MODE_MERGE,
        protective_backup: bool = True,
        selection_mode: str = SELECTION_MODE_FULL,
        selected_paths=None,
        prepared_operation_id: str | None = None,
        apply: bool = False,
        confirm: bool = False,
        confirm_without_protective: bool = False,
        initiated_from_telegram: bool = False,
        request_id: str | None = None,
        password: str | None = None,
    ) -> dict:
        """Start imported Restore and poll by its scoped opaque request key."""
        apply_changes = bool(apply)
        if apply_changes:
            _, prepared_contract = self._prepared_restore_contract(
                prepared_operation_id
            )
            mode = prepared_contract["restore_mode"]
            consent_protective = prepared_contract["protective_backup"]
        else:
            mode = normalize_restore_mode(restore_mode)
            selection_mode = normalize_selection_mode(selection_mode)
            consent_protective = bool(protective_backup)
        self._assert_restore_consent(
            apply=apply_changes,
            protective=consent_protective,
            confirm=confirm,
            confirm_without_protective=confirm_without_protective,
        )
        caller_request_id = request_id or f"web-restore-imported-{uuid4().hex}"
        operation_request_id = self._imported_restore_request_key(
            entry_key,
            caller_request_id,
        )

        # Resolve synchronously so namespace, destination and Bot4VPS restrictions
        # are reported directly instead of becoming an unregistered worker error.
        with self.coordinator.acquire_import_read(entry_key, server_id=server_id):
            resolved = self.storage.resolve_import_bundle(
                entry_key,
                server_id=server_id,
            )
            destination = resolved["publication"].get("destination") or {}
            if destination.get("scope") == "bot4vps":
                if mode == RESTORE_MODE_CLEAN:
                    raise BackupError(
                        ErrorCode.RESTORE_PRECHECK_FAILED,
                        "Для Bot4VPS доступно только обычное восстановление: "
                        "«чистое» удалило бы файлы работающей установки",
                    )
            elif destination.get("scope") == "server":
                destination_server_id = destination.get("server_id")
                if not isinstance(destination_server_id, str) or find_server(
                    destination_server_id
                ) is None:
                    raise BackupError(
                        ErrorCode.SOURCE_NOT_FOUND,
                        "Сервер восстановления не найден",
                    )
            else:
                raise BackupError(
                    ErrorCode.STORAGE_BACKEND_ERROR,
                    "Import bundle содержит некорректный destination",
                )

        def run() -> None:
            try:
                self.restore_imported_archive(
                    entry_key,
                    server_id=server_id,
                    target_root=target_root,
                    restore_mode=mode,
                    protective_backup=protective_backup,
                    selection_mode=selection_mode,
                    selected_paths=selected_paths,
                    prepared_operation_id=prepared_operation_id,
                    apply=apply_changes,
                    confirm=confirm,
                    confirm_without_protective=confirm_without_protective,
                    initiated_from_telegram=initiated_from_telegram,
                    request_id=caller_request_id,
                    password=password,
                )
            except Exception:
                return

        worker = threading.Thread(
            target=run,
            name=f"backup-restore-import-{operation_request_id[-12:]}",
            daemon=True,
        )
        worker.start()
        deadline = time.monotonic() + 2.0
        operation = None
        while time.monotonic() < deadline:
            operation = self.operations.find_by_request_id(
                operation_request_id,
                operation_type="restore",
            )
            if operation is not None:
                break
            if not worker.is_alive():
                break
            time.sleep(0.01)
        if operation is None:
            raise BackupError(
                ErrorCode.OPERATION_CONFLICT,
                "Не удалось зарегистрировать Restore Operation",
                retryable=True,
            )
        return operation

    def migrate(self, *args, **kwargs):
        raise BackupError(ErrorCode.INVALID_REQUEST, "Migrate будет подключён на следующем этапе")

    @staticmethod
    def _legacy_import_archive_inventory(
        inspected: dict,
        publication: dict,
        checksum: str,
    ) -> dict:
        """Retain a non-lazy v1 sidecar for readable, unindexable imports."""
        members = inspected["members"]
        if members and isinstance(members[0], list):
            members = expand_archive_inventory_members(
                {"members": members},
                validate=False,
                consume_members=True,
            )
        else:
            members = [dict(member) for member in members]
        return {
            "schema_version": LEGACY_ARCHIVE_INVENTORY_SCHEMA_VERSION,
            "archive": {
                "sha256": checksum,
                "bytes": publication["bytes"],
                "format": publication["format"],
            },
            "manifest": copy.deepcopy(inspected.get("manifest")),
            "members": members,
        }

    @staticmethod
    def _import_origin_metadata(manifest: object) -> dict | None:
        """Retain only validated, bounded origin-time presentation metadata."""
        if not isinstance(manifest, dict):
            return None
        try:
            validated = validate_manifest(copy.deepcopy(manifest))
        except BackupError:
            return None
        source = validated.get("source")
        if (
            not isinstance(source, dict)
            or source.get("kind") != validated.get("type")
            or source.get("utc_offset") is None
        ):
            return None
        return {
            "created_at": validated["created_at"],
            "utc_offset": source["utc_offset"],
        }

    @staticmethod
    def _import_restore_metadata(manifest: object) -> dict:
        """Persist a bounded navigation hint, never a Restore authorization result."""
        usable_manifest = False
        if isinstance(manifest, dict):
            try:
                validate_manifest(copy.deepcopy(manifest))
                usable_manifest = True
            except BackupError:
                pass
        return {"requires_target_root": not usable_manifest}

    @staticmethod
    def _import_archive_inventory(
        inspected: dict,
        publication: dict,
        checksum: str,
        *,
        consume_members: bool = False,
    ) -> dict:
        """Build v2 from one already-read imported TAR member graph."""
        source = {
            "kind": "imported",
            "entry_key": publication["entry_key"],
            "destination": publication["destination"],
        }
        archive = {
            "sha256": checksum,
            "bytes": publication["bytes"],
            "format": publication["format"],
        }
        return build_archive_inventory(
            members=inspected["members"],
            manifest=inspected.get("manifest"),
            source=source,
            archive=archive,
            consume_members=consume_members,
        )

    def import_backup(
        self,
        source_archive: str | Path,
        *,
        filename: str | None = None,
        request_id: str | None = None,
        expected_type: str | None = None,
        destination_server_id: str | None = None,
        replace: bool = False,
        confirm_bot4vps_replace: bool = False,
        password: str | None = None,
    ) -> dict:
        """Publish an ordinary TAR/TAR.GZ as a self-contained import bundle.

        Operation records execution history only. Once the bundle directory is
        atomically renamed into ``imports/``, all reads address its ``entry_key``
        and ``publication.json`` directly. Managed Catalog and ArtifactRef are
        deliberately not involved in this lifecycle.

        ``password`` — пароль зашифрованного (B4VE) импорта. С ним архив
        расшифровывается на время инспекции и публикуется с настоящей
        инвентаризацией (древо файлов → выборочное восстановление и просмотр).
        Неверный пароль отбивается до создания Operation. Без пароля — прежнее
        поведение: legacy-сайдкар без членов, состав читается только на Restore.
        """
        # Keep the argument for API compatibility. Ordinary import is intentionally
        # not classified by Manifest or by a caller-supplied expected type.
        del expected_type
        if password:
            if len(password) > MAX_PASSWORD_LEN:
                raise BackupError(
                    ErrorCode.INVALID_REQUEST,
                    f"Пароль резервных копий — строка до {MAX_PASSWORD_LEN} символов",
                )
            # Ранняя проверка до создания Operation: неверный пароль — чистый
            # отказ без мусорной записи в журнале операций.
            if is_encrypted_file(source_archive) and not verify_password(
                source_archive, password
            ):
                raise BackupError(
                    ErrorCode.ENCRYPTION_PASSWORD_INVALID,
                    "Неверный пароль резервных копий для этого архива",
                )
        publication_filename = self._import_archive_filename(
            source_archive,
            filename,
        )
        if destination_server_id is not None:
            destination_server_id = str(destination_server_id)
            if find_server(destination_server_id) is None:
                raise BackupError(ErrorCode.INVALID_REQUEST, "Destination server не найден")

        request_id = request_id or f"import-{uuid4().hex}"
        operation_id = new_operation_id()
        entry_key = uuid4().hex
        owner_permit = self.coordinator.acquire_operation_owner(operation_id)
        try:
            operation = self.operations.create(
                operation_type="import",
                target=(
                    {"kind": "server", "server_id": destination_server_id}
                    if destination_server_id is not None
                    else {"kind": "bot4vps"}
                ),
                request_id=request_id,
                mode="manual",
                operation_id=operation_id,
            )
        except Exception:
            owner_permit.release()
            raise
        if operation["operation_id"] != operation_id:
            owner_permit.release()
            raise BackupError(
                ErrorCode.OPERATION_CONFLICT,
                "Import Operation уже выполняется",
                retryable=True,
            )

        staging_created = False
        try:
            self.operations.transition(
                operation_id,
                OperationStatus.RUNNING.value,
                stage="receiving_upload",
            )
            self.disk.require_creation_allowed()
            paths = self.storage.create_import_bundle_staging(
                operation_id,
                entry_key,
                publication_filename,
            )
            staging_created = True
            source = Path(source_archive)
            if source.is_symlink():
                raise BackupError(ErrorCode.INVALID_REQUEST, "Symlink import source запрещён")
            if not source.is_file():
                raise BackupError(ErrorCode.ARCHIVE_INVALID, "Файл import archive не найден")
            max_archive_bytes = self.config["bot4vps"]["limits"].get("max_archive_bytes")
            self._copy_secure(source, paths["archive"], max_bytes=max_archive_bytes)

            self.operations.transition(
                operation_id,
                OperationStatus.VERIFYING.value,
                stage="inspecting_staging",
            )
            # B4VE (зашифрованный паролем tar.gz): без пароля публикуется как есть
            # (сайдкар без членов, состав читается только на Restore с паролем).
            # С паролем — расшифровывается во временный staging-файл на время
            # инспекции, и публикация получает настоящую инвентаризацию.
            encrypted_import = is_encrypted_file(paths["archive"])
            decrypted_plain: Path | None = None
            try:
                if encrypted_import and password:
                    decrypted_plain = self._decrypt_restore_archive(
                        paths["archive"],
                        password,
                    )
                    inspected = inspect_archive(decrypted_plain)
                elif encrypted_import:
                    inspected = {"manifest": None, "members": []}
                else:
                    inspected = inspect_archive(paths["archive"])

                self.operations.update_stage(operation_id, "computing_checksum")
                checksum = self.storage.calculate_checksum(paths["archive"])
                imported_at = utc_timestamp()
                if encrypted_import:
                    with paths["archive"].open("rb") as stream:
                        raw_bytes = stream.read(4)
                    detected_format = (
                        "tar.gz"
                        if raw_bytes[:4] == b"B4VE" or raw_bytes[:2] == bytes.fromhex("1f8b")
                        else "tar"
                    )
                else:
                    with paths["archive"].open("rb") as stream:
                        raw_bytes = stream.read(2)
                    detected_format = "tar.gz" if raw_bytes == bytes.fromhex("1f8b") else "tar"
                # Инспекция зашифрованного импорта с паролем — настоящая (из
                # расшифрованного TAR); без пароля — консервативно пустая.
                inspection_real = encrypted_import and bool(password)
                publication = {
                    "schema_version": 2,
                    "entry_key": entry_key,
                    "filename": publication_filename,
                    "destination": (
                        {"scope": "server", "server_id": destination_server_id}
                        if destination_server_id is not None
                        else {"scope": "bot4vps"}
                    ),
                    "format": detected_format,
                    "bytes": paths["archive"].stat().st_size,
                    "checksum": {"algorithm": "sha256", "value": checksum},
                    "imported_at": imported_at,
                    "inspection": {
                        "status": "encrypted" if encrypted_import else "readable",
                        "manifest_status": (
                            "absent"
                            if inspected.get("manifest") is None
                            else "present"
                        ),
                        "member_count": len(inspected["members"]),
                    },
                    "origin": self._import_origin_metadata(inspected.get("manifest")),
                    "restore": (
                        # Манифест зашифрованного архива без пароля недоступен на
                        # импорте: консервативная подсказка, сам план на Restore
                        # расшифрует архив и разрешит scope по настоящему манифесту.
                        {"requires_target_root": True}
                        if encrypted_import and not inspection_real
                        else self._import_restore_metadata(inspected.get("manifest"))
                    ),
                }
                if encrypted_import:
                    publication["encrypted"] = True
                if encrypted_import and not password:
                    inventory = self._legacy_import_archive_inventory(
                        inspected,
                        publication,
                        checksum,
                    )
                else:
                    try:
                        inventory = self._import_archive_inventory(
                            inspected,
                            publication,
                            checksum,
                            consume_members=True,
                        )
                    except BackupError:
                        # Ordinary imports may be readable but physically non-restorable.
                        # Keep them publishable with a strict v1 compatibility sidecar;
                        # lazy inventory remains non-ready until an indexable v2 exists.
                        inventory = self._legacy_import_archive_inventory(
                            inspected,
                            publication,
                            checksum,
                        )
                self.storage.write_import_bundle_control(
                    paths,
                    publication,
                    checksum,
                    inventory,
                )
            finally:
                if decrypted_plain is not None:
                    self._discard_decrypted_restore_archive(decrypted_plain)

            self.operations.update_stage(operation_id, "publishing_import_bundle")
            replacement: dict | None = None
            with ExitStack() as lock_stack:
                # Every object-specific lock is acquired before the shared
                # destination lock. Native create/delete and rename use the
                # same order, so the namespace scan cannot deadlock with them.
                lock_stack.enter_context(
                    self.coordinator.acquire_import_publish(
                        entry_key,
                        server_id=destination_server_id,
                    )
                )
                initial_conflict = self._find_filename_conflict(
                    publication_filename,
                    server_id=destination_server_id,
                )
                if initial_conflict is not None and not replace:
                    raise self._filename_conflict_error(initial_conflict)
                if initial_conflict is not None:
                    if (
                        initial_conflict.get("requires_confirmation")
                        and not confirm_bot4vps_replace
                    ):
                        raise self._replace_confirmation_error(initial_conflict)
                    if initial_conflict["kind"] == "managed":
                        lock_stack.enter_context(
                            self.coordinator.acquire_artifact_delete(
                                initial_conflict["ref"]
                            )
                        )
                    else:
                        lock_stack.enter_context(
                            self.coordinator.acquire_import_delete(
                                initial_conflict["entry_key"],
                                server_id=destination_server_id,
                            )
                        )
                with self.coordinator.destination_lock(destination_server_id):
                    current_conflict = self._find_filename_conflict(
                        publication_filename,
                        server_id=destination_server_id,
                    )
                    if initial_conflict is not None and not self._same_filename_conflict(
                        initial_conflict,
                        current_conflict,
                    ):
                        if current_conflict is None:
                            # The original owner disappeared while its object
                            # lock was being acquired; continue as a normal
                            # import under the destination lock.
                            replacement = None
                        else:
                            raise self._filename_conflict_error(current_conflict)
                    else:
                        replacement = current_conflict
                    if initial_conflict is None and current_conflict is not None:
                        # A new owner appeared after the optimistic scan. It
                        # was not locked by this operation; retry explicitly.
                        raise self._filename_conflict_error(current_conflict)
                    if replacement is not None and not replace:
                        raise self._filename_conflict_error(replacement)
                    if (
                        replacement is not None
                        and replacement.get("requires_confirmation")
                        and not confirm_bot4vps_replace
                    ):
                        raise self._replace_confirmation_error(replacement)

                    self.storage.publish_import_bundle(
                        paths,
                        entry_key=entry_key,
                        server_id=destination_server_id,
                    )
                    try:
                        if replacement is not None:
                            if replacement["kind"] == "managed":
                                self._delete_managed_for_replacement(
                                    replacement,
                                    operation_id=operation_id,
                                )
                            else:
                                self.storage.delete_import_bundle(
                                    replacement["entry_key"],
                                    server_id=destination_server_id,
                                )
                    except Exception:
                        # The incoming bundle is already durable, so remove it
                        # while its import lock is still held if replacement of
                        # the old owner did not complete.
                        try:
                            self.storage.delete_import_bundle(
                                entry_key,
                                server_id=destination_server_id,
                            )
                        except BackupError:
                            pass
                        raise
            completed = self.operations.transition(
                operation_id,
                OperationStatus.COMPLETED.value,
                stage="completed",
            )
            return {"operation": completed, "archive": publication}
        except BackupError as exc:
            current = self.operations.get(operation_id)
            if current.get("status") not in TERMINAL_STATUSES:
                self.operations.transition(
                    operation_id,
                    OperationStatus.FAILED.value,
                    stage=current.get("stage") or "failed",
                    error=exc.to_safe_error(),
                )
            raise
        except Exception as exc:
            safe = BackupError(ErrorCode.INTERNAL_ERROR, "Внутренняя ошибка import")
            current = self.operations.get(operation_id)
            if current.get("status") not in TERMINAL_STATUSES:
                self.operations.transition(
                    operation_id,
                    OperationStatus.FAILED.value,
                    stage="failed",
                    error=safe.to_safe_error(),
                )
            raise safe from exc
        finally:
            try:
                if staging_created:
                    self.storage.remove_staging(operation_id, "import")
            finally:
                owner_permit.release()

    def verify(
        self,
        backup_id: ArtifactRef | str,
        *,
        server_id: str | None = None,
        request_id: str | None = None,
    ) -> dict:
        backup_id = self._requested_ref(backup_id, server_id)
        request_id = request_id or f"verify-{uuid4().hex}"
        target, artifact_ref, artifact_id = self._artifact_target(
            target=backup_id,
        )
        lookup: ArtifactRef | str = artifact_ref if artifact_ref is not None else artifact_id
        operation_id = new_operation_id()
        owner_permit = self.coordinator.acquire_operation_owner(operation_id)
        try:
            operation = self.operations.create(
                operation_type="verify",
                target=target,
                request_id=request_id,
                operation_id=operation_id,
            )
        except Exception:
            owner_permit.release()
            raise
        if operation["operation_id"] != operation_id:
            owner_permit.release()
            if operation["status"] == OperationStatus.COMPLETED.value:
                record = self.catalog.get(lookup)
                return {
                    "operation": operation,
                    "record": record,
                    "manifest": record["manifest"],
                    "checksum": record["archive"]["checksum"],
                }
            error = operation.get("error") or {}
            raise BackupError(
                error.get("code", ErrorCode.OPERATION_CONFLICT.value),
                error.get("message", "Verify Operation уже существует"),
                retryable=bool(error.get("retryable", True)),
                correlation_id=error.get("correlation_id"),
            )
        try:
            self.operations.transition(
                operation_id,
                OperationStatus.RUNNING.value,
                stage="waiting_for_artifact_read",
            )
            record = self.catalog.get(lookup)
            artifact_ref = self._record_ref(record)
            with self.coordinator.acquire_artifact_read(artifact_ref):
                self.operations.transition(
                    operation_id,
                    OperationStatus.VERIFYING.value,
                    stage="checking_pair",
                )
                archive_path = self.storage.resolve_key(record["storage"]["key"])
                checksum_path = self.storage.resolve_key(record["storage"]["checksum_key"])
                if not archive_path.is_file() or not checksum_path.is_file():
                    raise BackupError(ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE, "Опубликованная pair неполна", retryable=True)
                self.operations.update_stage(operation_id, "checking_checksum")
                expected = checksum_path.read_text(encoding="ascii")
                if len(expected) != 65 or not expected.endswith("\n") or any(ch not in "0123456789abcdef" for ch in expected[:-1]):
                    raise BackupError(ErrorCode.CHECKSUM_MISMATCH, "Checksum file имеет неверный формат")
                actual = self.storage.calculate_checksum(archive_path)
                if actual != expected[:-1] or actual != record["archive"]["checksum"]:
                    raise BackupError(ErrorCode.CHECKSUM_MISMATCH, "SHA-256 archive не совпадает")
                self.operations.update_stage(operation_id, "opening_archive")
                if record.get("archive", {}).get("encrypted"):
                    # Зашифрованный архив: целостность подтверждена SHA-256 по
                    # шифротексту (AES-GCM дополнительно проверяется при
                    # расшифровке). Открывать B4VE как TAR без пароля нельзя.
                    manifest = record["manifest"]
                else:
                    inspected = validate_archive_physical(archive_path)
                    manifest = inspected["manifest"]
                self.operations.update_stage(operation_id, "validating_members")
                record = self.catalog.update_verification(
                    artifact_ref,
                    {"status": "verified", "verified_at": utc_timestamp()},
                    expected_version=int(record["artifact_version"]),
                )
            completed = self.operations.transition(
                operation_id,
                OperationStatus.COMPLETED.value,
                stage="completed",
                result_backup_id=artifact_id,
            )
            return {"operation": completed, "record": record, "manifest": manifest, "checksum": actual}
        except BackupError as exc:
            current = self.operations.get(operation_id)
            if current["status"] not in TERMINAL_STATUSES:
                self.operations.transition(operation_id, OperationStatus.FAILED.value, stage=current["stage"], error=exc.to_safe_error())
            raise
        except Exception as exc:
            safe = BackupError(ErrorCode.VERIFY_FAILED, "Не удалось проверить backup")
            current = self.operations.get(operation_id)
            if current["status"] not in TERMINAL_STATUSES:
                self.operations.transition(operation_id, OperationStatus.FAILED.value, stage=current["stage"], error=safe.to_safe_error())
            raise safe from exc
        finally:
            owner_permit.release()

    def delete(
        self,
        backup_id: ArtifactRef | str,
        *,
        server_id: str | None = None,
        request_id: str | None = None,
    ) -> dict:
        backup_id = self._requested_ref(backup_id, server_id)
        request_id = request_id or f"delete-{uuid4().hex}"
        target, artifact_ref, artifact_id = self._artifact_target(
            target=backup_id,
        )
        operation_id = new_operation_id()
        owner_permit = self.coordinator.acquire_operation_owner(operation_id)
        try:
            operation = self.operations.create(
                operation_type="delete",
                target=target,
                request_id=request_id,
                operation_id=operation_id,
            )
        except Exception:
            owner_permit.release()
            raise
        if operation["operation_id"] != operation_id:
            owner_permit.release()
            if operation["status"] == OperationStatus.COMPLETED.value:
                return {"operation": operation, "deleted_backup_id": artifact_id}
            error = operation.get("error") or {}
            raise BackupError(
                error.get("code", ErrorCode.OPERATION_CONFLICT.value),
                error.get("message", "Delete Operation уже существует"),
                retryable=bool(error.get("retryable", True)),
                correlation_id=error.get("correlation_id"),
            )
        try:
            self.operations.transition(operation_id, OperationStatus.RUNNING.value, stage="waiting_for_artifact_delete")
            if artifact_ref is None:
                # Namespace обязателен для artifact lock: без записи Catalog
                # удалять нечего, и это диагностируется до захвата лока.
                raise BackupError(ErrorCode.ARTIFACT_NOT_FOUND, "Опубликованный backup не найден")
            with self.coordinator.acquire_artifact_delete(artifact_ref):
                with self.coordinator.destination_lock(
                    self._destination_server_id(artifact_ref)
                ):
                    self.operations.update_stage(operation_id, "claiming_delete")
                    intent = self.catalog.begin_delete(
                        artifact_ref,
                        owner_operation_id=operation_id,
                        ttl_seconds=int(self.config["safety"]["claim_ttl_seconds"]),
                    )
                    claim = intent["retention"]["claim"]
                    expected_version = int(intent["artifact_version"])
                    try:
                        self.operations.update_stage(operation_id, "deleting_pair")
                        archive_path = self.storage.resolve_key(intent["storage"]["key"])
                        checksum_path = self.storage.resolve_key(intent["storage"]["checksum_key"])
                        self.storage.delete_pair(archive_path, checksum_path)
                    except Exception as exc:
                        try:
                            self.catalog.mark_delete_failed(artifact_ref, expected_version=expected_version, expected_claim_id=claim["claim_id"])
                        except BackupError:
                            pass
                        if isinstance(exc, BackupError):
                            raise
                        raise BackupError(ErrorCode.STORAGE_BACKEND_ERROR, "Не удалось удалить backup", retryable=True) from exc
                    self.operations.update_stage(operation_id, "removing_catalog")
                    self.catalog.finish_delete(artifact_ref, expected_version=expected_version, expected_claim_id=claim["claim_id"])
            completed = self.operations.transition(
                operation_id,
                OperationStatus.COMPLETED.value,
                stage="completed",
                result_backup_id=artifact_id,
            )
            return {"operation": completed, "deleted_backup_id": artifact_id}
        except BackupError as exc:
            current = self.operations.get(operation_id)
            if current["status"] not in TERMINAL_STATUSES:
                self.operations.transition(operation_id, OperationStatus.FAILED.value, stage=current["stage"], error=exc.to_safe_error())
            raise
        except Exception as exc:
            safe = BackupError(ErrorCode.INTERNAL_ERROR, "Внутренняя ошибка delete")
            current = self.operations.get(operation_id)
            if current["status"] not in TERMINAL_STATUSES:
                self.operations.transition(operation_id, OperationStatus.FAILED.value, stage=current["stage"], error=safe.to_safe_error())
            raise safe from exc
        finally:
            owner_permit.release()

    def apply_retention(
        self,
        scope: str,
        *,
        keep_last: int,
        request_id: str | None = None,
    ) -> dict:
        """Claim и удалить automatic backup в одном retention lifecycle."""
        operation_id = new_operation_id()
        owner_permit = self.coordinator.acquire_operation_owner(operation_id)
        target = {"kind": "retention_scope", "scope": scope}
        try:
            operation = self.operations.create(
                operation_type="retention",
                target=target,
                request_id=request_id or f"retention-{uuid4().hex}",
                mode="automatic",
                operation_id=operation_id,
            )
        except Exception:
            owner_permit.release()
            raise
        if operation["operation_id"] != operation_id:
            owner_permit.release()
            if operation["status"] == OperationStatus.COMPLETED.value:
                run = next(
                    (
                        item for item in self.retention_runs.list()
                        if item.get("operation_id") == operation["operation_id"]
                    ),
                    None,
                )
                return {"operation": operation, "run": run}
            raise BackupError(ErrorCode.OPERATION_CONFLICT, "Retention Operation уже существует", retryable=True)
        run_id = new_run_id()
        now = utc_timestamp()
        run = {
            "schema_version": 1,
            "run_id": run_id,
            "operation_id": operation_id,
            "scope": scope,
            "keep_last": keep_last,
            "status": "running",
            "created_at": now,
            "updated_at": now,
            "finished_at": None,
            "claimed_backup_ids": [],
            "deleted_backup_ids": [],
            "failed": [],
        }
        try:
            self.retention_runs.create(run_id, run)
            self.operations.transition(operation_id, OperationStatus.RUNNING.value, stage="selecting_candidates")
            claimed = self.catalog.claim_retention_scope(
                scope=scope,
                keep_last=keep_last,
                run_id=run_id,
                owner_operation_id=operation_id,
                ttl_seconds=int(self.config["safety"]["claim_ttl_seconds"]),
            )
            run["claimed_backup_ids"] = [record["backup_id"] for record in claimed]
            run["updated_at"] = utc_timestamp()
            self.retention_runs.mutate(run_id, lambda _: dict(run))
            self.operations.update_stage(operation_id, "deleting_claimed_artifacts")
            for snapshot in claimed:
                backup_id = snapshot["backup_id"]
                claim = snapshot["retention"]["claim"]
                try:
                    artifact_ref = self._record_ref(snapshot)
                    with self.coordinator.acquire_artifact_delete(artifact_ref):
                        with self.coordinator.destination_lock(
                            self._destination_server_id(artifact_ref)
                        ):
                            with self.coordinator.catalog_lock():
                                intent = self.catalog.begin_claimed_delete(
                                    artifact_ref,
                                    expected_version=int(snapshot["artifact_version"]),
                                    expected_claim_id=claim["claim_id"],
                                    owner_operation_id=operation_id,
                                    lock_held=True,
                                )
                            deleting_claim = intent["retention"]["claim"]
                            archive_path = self.storage.resolve_key(intent["storage"]["key"])
                            checksum_path = self.storage.resolve_key(intent["storage"]["checksum_key"])
                            try:
                                self.storage.delete_pair(archive_path, checksum_path)
                            except Exception:
                                try:
                                    self.catalog.mark_delete_failed(
                                        artifact_ref,
                                        expected_version=int(intent["artifact_version"]),
                                        expected_claim_id=deleting_claim["claim_id"],
                                    )
                                except BackupError:
                                    pass
                                raise
                            with self.coordinator.catalog_lock():
                                self.catalog.finish_delete(
                                    artifact_ref,
                                    expected_version=int(intent["artifact_version"]),
                                    expected_claim_id=deleting_claim["claim_id"],
                                    lock_held=True,
                                )
                    run["deleted_backup_ids"].append(backup_id)
                except BackupError as exc:
                    run["failed"].append({"backup_id": backup_id, "code": exc.code})
                except Exception:
                    run["failed"].append({
                        "backup_id": backup_id,
                        "code": ErrorCode.RETENTION_DELETE_FAILED.value,
                    })
                run["updated_at"] = utc_timestamp()
                self.retention_runs.mutate(run_id, lambda _: dict(run))
            run.update({"status": "completed", "finished_at": utc_timestamp(), "updated_at": utc_timestamp()})
            self.retention_runs.mutate(run_id, lambda _: dict(run))
            completed = self.operations.transition(
                operation_id,
                OperationStatus.COMPLETED.value,
                stage="completed",
            )
            return {"operation": completed, "run": run}
        except BackupError as exc:
            run.update({"status": "failed", "finished_at": utc_timestamp(), "updated_at": utc_timestamp()})
            if self.retention_runs.get(run_id) is not None:
                self.retention_runs.mutate(run_id, lambda _: dict(run))
            current = self.operations.get(operation_id)
            if current["status"] not in TERMINAL_STATUSES:
                self.operations.transition(operation_id, OperationStatus.FAILED.value, stage=current["stage"], error=exc.to_safe_error())
            raise
        finally:
            owner_permit.release()

    @staticmethod
    def _inventory_layout_name(layout: int) -> str:
        if layout == LAYOUT_FIXED_ABSOLUTE:
            return "fixed_absolute"
        if layout == LAYOUT_RELATIVE_TARGET_ROOT:
            return "relative_target_root"
        raise BackupError(
            ErrorCode.ARCHIVE_INVALID,
            "Archive inventory содержит неизвестный layout",
        )

    def _managed_restore_inventory_context(
        self,
        backup_id: ArtifactRef | str,
        *,
        server_id: str | None = None,
    ) -> dict:
        ref = self._requested_ref(backup_id, server_id)
        record = self.catalog.get(ref)
        artifact_ref = self._record_ref(record)
        storage = record.get("storage")
        archive_record = record.get("archive")
        canonical_key, canonical_checksum_key = self.storage.canonical_keys(
            artifact_ref.backup_id,
            artifact_ref.kind,
            artifact_ref.server_id,
        )
        if (
            not isinstance(storage, dict)
            or storage.get("key") != canonical_key
            or storage.get("checksum_key") != canonical_checksum_key
            or not isinstance(archive_record, dict)
        ):
            raise BackupError(
                ErrorCode.CATALOG_CONFLICT,
                "Catalog record не соответствует managed artifact",
            )
        source = {
            "kind": "managed",
            "backup_id": artifact_ref.backup_id,
            "type": artifact_ref.kind,
            "artifact_version": record.get("artifact_version"),
            "storage_key": canonical_key,
        }
        if artifact_ref.kind == "server":
            source["server_id"] = artifact_ref.server_id
        archive = {
            "sha256": archive_record.get("checksum"),
            "bytes": archive_record.get("bytes"),
            "format": archive_record.get("format"),
        }
        # Reuse the durable queue's closed schemas at this trust boundary. This
        # validates Catalog-derived values only; no filesystem path comes from UI.
        source = ArchiveInventoryIndexer._validate_managed_source(source)
        archive = ArchiveInventoryIndexer._validate_managed_archive(archive)
        return {
            "kind": "managed",
            "record": record,
            "artifact_ref": artifact_ref,
            "source": source,
            "archive": archive,
            "archive_path": self.storage.resolve_key(canonical_key),
            "checksum_path": self.storage.resolve_key(canonical_checksum_key),
            "local_target": artifact_ref.kind == "bot4vps",
        }

    def _imported_restore_inventory_context(
        self,
        entry_key: str,
        *,
        server_id: str | None = None,
    ) -> dict:
        with self.coordinator.acquire_import_read(entry_key, server_id=server_id):
            resolved = self.storage.resolve_import_bundle(
                entry_key,
                server_id=server_id,
            )
            source, archive = self.storage.import_inventory_bindings(resolved)
        source = ArchiveInventoryIndexer._validate_imported_source(source)
        archive = ArchiveInventoryIndexer._validate_archive(archive)
        destination = source["destination"]
        return {
            "kind": "imported",
            "publication": resolved["publication"],
            "entry_key": source["entry_key"],
            "server_id": destination.get("server_id"),
            "source": source,
            "archive": archive,
            "local_target": destination.get("scope") == "bot4vps",
        }

    def _load_restore_inventory_snapshot(self, context: dict):
        if context["kind"] == "managed":
            artifact_ref = context["artifact_ref"]
            with self.coordinator.acquire_artifact_read(artifact_ref):
                current = self._managed_restore_inventory_context(artifact_ref)
                if (
                    current["source"] != context["source"]
                    or current["archive"] != context["archive"]
                ):
                    raise BackupError(
                        ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE,
                        "Managed artifact изменился перед чтением inventory",
                        retryable=True,
                    )
                return self.storage.load_managed_archive_inventory_snapshot(
                    current["archive_path"],
                    current["checksum_path"],
                    expected_source=current["source"],
                    expected_archive=current["archive"],
                )

        entry_key = context["entry_key"]
        server_id = context["server_id"]
        with self.coordinator.acquire_import_read(entry_key, server_id=server_id):
            resolved = self.storage.resolve_import_bundle(
                entry_key,
                server_id=server_id,
            )
            source, archive = self.storage.import_inventory_bindings(resolved)
            if source != context["source"] or archive != context["archive"]:
                raise BackupError(
                    ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE,
                    "Import bundle изменился перед чтением inventory",
                    retryable=True,
                )
            return self.storage.load_import_archive_inventory_snapshot(resolved)

    def _project_restore_inventory(
        self,
        context: dict,
        snapshot,
        *,
        target_root: str | None,
    ):
        storage_root = str(self.storage.root) if context["local_target"] else None
        if snapshot.layout == LAYOUT_FIXED_ABSOLUTE:
            return project_archive_inventory(
                snapshot,
                target_root=target_root,
                storage_root=storage_root,
            )
        cache_key = (
            "archive-inventory-projection-v2",
            id(snapshot),
            target_root,
            storage_root,
        )
        return archive_inventory_query_cache.get_or_load(
            cache_key,
            lambda: project_archive_inventory(
                snapshot,
                target_root=target_root,
                storage_root=storage_root,
            ),
        )

    @staticmethod
    def _project_archive_inventory_view(snapshot):
        cache_key = ("archive-inventory-view-v2", id(snapshot))
        return archive_inventory_query_cache.get_or_load(
            cache_key,
            lambda: project_archive_inventory_view(snapshot),
        )

    @staticmethod
    def _archive_inventory_actions(status: dict) -> dict:
        state = status.get("status")
        error = status.get("error") if isinstance(status.get("error"), dict) else {}
        excluded = {
            "inventory_not_indexable",
            "inventory_source_obsolete",
            "inventory_resource_limit",
        }
        error_code = error.get("code")
        return {
            "prepare": state == "missing",
            "retry": (
                state == "failed"
                or (state == "unavailable" and error_code not in excluded)
            ),
            "rebuild": state == "ready",
        }

    def _with_archive_inventory_actions(self, status: dict) -> dict:
        result = dict(status)
        result["actions"] = self._archive_inventory_actions(result)
        return result

    def _ready_archive_inventory(self, view, *, job_id: str | None = None) -> dict:
        result = {
            "status": "ready",
            "retry_after_ms": None,
            "revision": view.revision,
            "layout": self._inventory_layout_name(view.snapshot.layout),
            "root_count": view.root_count,
        }
        if job_id is not None:
            result["job_id"] = job_id
        return self._with_archive_inventory_actions(result)

    def _ready_restore_inventory(self, projection) -> dict:
        result = {
            "status": "ready",
            "retry_after_ms": None,
            "revision": projection.revision,
            "layout": self._inventory_layout_name(projection.snapshot.layout),
            "policy_summary": archive_inventory_policy_summary(projection),
        }
        if projection.target_root is not None:
            result["target_root"] = projection.target_root
        return result

    @staticmethod
    def _inventory_retry_after_ms(job: dict) -> int:
        if job.get("status") != "retry_wait":
            return 1000
        try:
            remaining = (
                parse_utc_timestamp(job.get("next_attempt_at")) - utc_now()
            ).total_seconds()
        except (TypeError, ValueError):
            return 1000
        return max(500, min(int(max(remaining, 0) * 1000), 60_000))

    def _restore_inventory_job_status(
        self,
        context: dict,
        job: dict | None = None,
    ) -> dict:
        if job is None:
            job = self.inventory_indexer.get_job(
                source=context["source"],
                archive=context["archive"],
            )
        if job is None:
            return {"status": "missing", "retry_after_ms": None}

        status = job.get("status")
        if status in {"queued", "retry_wait"}:
            result = {
                "status": "queued",
                "retry_after_ms": self._inventory_retry_after_ms(job),
                "priority": int(job.get("priority") or 0),
                "position": job.get("position"),
            }
            return result
        if status in {"indexing", "running"}:
            return {"status": "indexing", "retry_after_ms": 1000}

        error = job.get("error") if isinstance(job.get("error"), dict) else None
        if status == "completed" and job.get("result") == "compatibility_only":
            return {
                "status": "unavailable",
                "retry_after_ms": None,
                "retryable": False,
                "error": {
                    "code": "inventory_not_indexable",
                    "message": "Структура этого импортированного архива недоступна для lazy navigation",
                },
            }
        if status == "obsolete":
            return {
                "status": "unavailable",
                "retry_after_ms": None,
                "retryable": False,
                "error": {
                    "code": "inventory_source_obsolete",
                    "message": "Источник archive inventory больше не существует",
                },
            }
        if status == "failed":
            unavailable_codes = {
                ErrorCode.ARCHIVE_INVALID.value,
                ErrorCode.ARCHIVE_PATH_UNSAFE.value,
                ErrorCode.ARCHIVE_SPECIAL_FILE_UNSUPPORTED.value,
                ErrorCode.CHECKSUM_MISMATCH.value,
                ErrorCode.MANIFEST_INVALID.value,
                ErrorCode.MANIFEST_MISSING.value,
                ErrorCode.MANIFEST_VERSION_UNSUPPORTED.value,
                ErrorCode.VERIFY_FAILED.value,
            }
            unavailable = bool(error and error.get("code") in unavailable_codes)
            return {
                "status": "unavailable" if unavailable else "failed",
                "retry_after_ms": None if unavailable else 0,
                "retryable": not unavailable,
                "error": error or {
                    "code": "inventory_index_failed",
                    "message": "Не удалось подготовить структуру backup",
                },
            }
        # A completed repair whose sidecar is no longer readable is missing again;
        # the next prepare call creates one new repair job for this binding.
        return {"status": "missing", "retry_after_ms": None}

    def _bound_inventory_job(self, context: dict, job_id: str) -> dict:
        job = self.inventory_indexer.get_job_by_id(job_id)
        if (
            job is None
            or job.get("status") == "obsolete"
            or job.get("source") != context["source"]
            or job.get("archive") != context["archive"]
            or job.get("identity")
            != ArchiveInventoryIndexer._identity(context["source"])
        ):
            raise BackupError(
                ErrorCode.OPERATION_CONFLICT,
                "Запрошенная инвентаризация не относится к этому архиву",
                details={"inventory_error": "watched_job_invalid"},
            )
        return job

    def _archive_inventory_job_status(
        self,
        context: dict,
        job: dict | None = None,
    ) -> dict:
        if job is None:
            job = self.inventory_indexer.get_job(
                source=context["source"],
                archive=context["archive"],
            )
        status = self._restore_inventory_job_status(context, job)
        if job is not None:
            status["job_id"] = job["job_id"]
            status["operation"] = job["operation"]
        return self._with_archive_inventory_actions(status)

    def _archive_inventory_status_context(
        self,
        context: dict,
        *,
        job_id: str | None = None,
    ) -> dict:
        watched = (
            self._bound_inventory_job(context, job_id)
            if job_id is not None
            else None
        )
        if watched is not None and not (
            watched.get("status") == "completed"
            and watched.get("result") != "compatibility_only"
        ):
            return self._archive_inventory_job_status(context, watched)

        try:
            snapshot = self._load_restore_inventory_snapshot(context)
        except BackupError as exc:
            unavailable = self._inventory_resource_status(exc)
            if unavailable is not None:
                if watched is not None:
                    unavailable["job_id"] = watched["job_id"]
                    unavailable["operation"] = watched["operation"]
                return self._with_archive_inventory_actions(unavailable)
            if watched is not None:
                return self._with_archive_inventory_actions({
                    "status": "failed",
                    "retry_after_ms": 0,
                    "retryable": True,
                    "job_id": watched["job_id"],
                    "operation": watched["operation"],
                    "error": {
                        "code": "inventory_result_unavailable",
                        "message": "Инвентаризация завершилась, но индекс недоступен",
                    },
                })
            return self._archive_inventory_job_status(context)

        view = self._project_archive_inventory_view(snapshot)
        return self._ready_archive_inventory(
            view,
            job_id=watched["job_id"] if watched is not None else None,
        )

    @staticmethod
    def _inventory_resource_status(exc: BackupError) -> dict | None:
        if exc.details.get("inventory_error") != "resource_limit":
            return None
        return {
            "status": "unavailable",
            "retry_after_ms": None,
            "retryable": False,
            "error": {
                "code": "inventory_resource_limit",
                "message": exc.safe_message,
            },
        }

    def _enqueue_restore_inventory(
        self,
        context: dict,
        *,
        reason: str,
        retry: bool,
        rebuild: bool = False,
    ) -> dict:
        enqueue = (
            self.inventory_indexer.enqueue_managed
            if context["kind"] == "managed"
            else self.inventory_indexer.enqueue_imported
        )
        return enqueue(
            source=context["source"],
            archive=context["archive"],
            reason=reason,
            priority=INVENTORY_PRIORITY_INTERACTIVE,
            retry=retry,
            rebuild=rebuild,
        )

    def _prepare_restore_inventory_context(
        self,
        context: dict,
        *,
        target_root: str | None,
        retry: bool,
    ) -> dict:
        if not isinstance(retry, bool):
            raise BackupError(ErrorCode.INVALID_REQUEST, "Некорректный retry inventory")
        try:
            snapshot = self._load_restore_inventory_snapshot(context)
        except BackupError as exc:
            unavailable = self._inventory_resource_status(exc)
            if unavailable is not None:
                return unavailable
            job = self._enqueue_restore_inventory(
                context,
                reason="interactive_prepare",
                retry=retry,
            )
            return self._restore_inventory_job_status(context, job)
        projection = self._project_restore_inventory(
            context,
            snapshot,
            target_root=target_root,
        )
        return self._ready_restore_inventory(projection)

    @staticmethod
    def _validate_inventory_view(view: str) -> str:
        if view not in {"restore", "archive"}:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Некорректный режим archive inventory",
            )
        return view

    @staticmethod
    def _validate_archive_view_target(target_root: str | None) -> None:
        if target_root is not None:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Archive view не принимает target_root",
            )

    def _prepare_archive_inventory_context(
        self,
        context: dict,
        *,
        retry: bool,
        rebuild: bool,
    ) -> dict:
        if not isinstance(retry, bool) or not isinstance(rebuild, bool):
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Некорректный режим подготовки archive inventory",
            )
        if retry and rebuild:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Retry и rebuild archive inventory несовместимы",
            )

        try:
            snapshot = self._load_restore_inventory_snapshot(context)
        except BackupError as exc:
            unavailable = self._inventory_resource_status(exc)
            if unavailable is not None:
                return self._with_archive_inventory_actions(unavailable)
            if rebuild:
                status = self._archive_inventory_job_status(context)
                raise BackupError(
                    ErrorCode.OPERATION_CONFLICT,
                    "Archive inventory недоступен для перестроения",
                    retryable=status.get("actions", {}).get("prepare", False)
                    or status.get("actions", {}).get("retry", False),
                    details={
                        "inventory_error": "rebuild_not_ready",
                        "inventory_status": status,
                    },
                ) from exc
            job = self._enqueue_restore_inventory(
                context,
                reason="interactive_archive_retry" if retry else "interactive_archive_prepare",
                retry=retry,
            )
            return self._archive_inventory_job_status(context, job)

        view = self._project_archive_inventory_view(snapshot)
        if not rebuild:
            return self._ready_archive_inventory(view)
        job = self._enqueue_restore_inventory(
            context,
            reason="interactive_archive_rebuild",
            retry=False,
            rebuild=True,
        )
        return self._archive_inventory_job_status(context, job)

    def _require_archive_inventory_view(self, context: dict):
        try:
            snapshot = self._load_restore_inventory_snapshot(context)
        except BackupError as exc:
            unavailable = self._inventory_resource_status(exc)
            status = (
                self._with_archive_inventory_actions(unavailable)
                if unavailable is not None
                else self._archive_inventory_job_status(context)
            )
            raise BackupError(
                ErrorCode.OPERATION_CONFLICT,
                "Archive inventory ещё не готов",
                retryable=status.get("status") in {"queued", "indexing", "failed"},
                details={
                    "inventory_error": "not_ready",
                    "inventory_status": status,
                },
            ) from exc
        return self._project_archive_inventory_view(snapshot)

    def _restore_inventory_status_context(
        self,
        context: dict,
        *,
        target_root: str | None,
    ) -> dict:
        try:
            snapshot = self._load_restore_inventory_snapshot(context)
        except BackupError as exc:
            unavailable = self._inventory_resource_status(exc)
            if unavailable is not None:
                return unavailable
            return self._restore_inventory_job_status(context)
        projection = self._project_restore_inventory(
            context,
            snapshot,
            target_root=target_root,
        )
        return self._ready_restore_inventory(projection)

    def _require_restore_inventory_projection(
        self,
        context: dict,
        *,
        target_root: str | None,
    ):
        try:
            snapshot = self._load_restore_inventory_snapshot(context)
        except BackupError as exc:
            unavailable = self._inventory_resource_status(exc)
            if unavailable is None:
                job = self._enqueue_restore_inventory(
                    context,
                    reason="interactive_query_repair",
                    retry=False,
                )
                status = self._restore_inventory_job_status(context, job)
            else:
                status = unavailable
            raise BackupError(
                ErrorCode.OPERATION_CONFLICT,
                "Archive inventory ещё не готов",
                retryable=status.get("status") in {"queued", "indexing", "failed"},
                details={
                    "inventory_error": "not_ready",
                    "inventory_status": status,
                },
            ) from exc
        return self._project_restore_inventory(
            context,
            snapshot,
            target_root=target_root,
        )

    def prepare_restore_inventory(
        self,
        backup_id: ArtifactRef | str,
        *,
        server_id: str | None = None,
        target_root: str | None = None,
        retry: bool = False,
        rebuild: bool = False,
        view: str = "restore",
    ) -> dict:
        view = self._validate_inventory_view(view)
        context = self._managed_restore_inventory_context(
            backup_id,
            server_id=server_id,
        )
        if view == "archive":
            self._validate_archive_view_target(target_root)
            return self._prepare_archive_inventory_context(
                context,
                retry=retry,
                rebuild=rebuild,
            )
        if rebuild:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Rebuild доступен только для archive view",
            )
        return self._prepare_restore_inventory_context(
            context,
            target_root=target_root,
            retry=retry,
        )

    def restore_inventory_status(
        self,
        backup_id: ArtifactRef | str,
        *,
        server_id: str | None = None,
        target_root: str | None = None,
        view: str = "restore",
        job_id: str | None = None,
    ) -> dict:
        view = self._validate_inventory_view(view)
        context = self._managed_restore_inventory_context(
            backup_id,
            server_id=server_id,
        )
        if view == "archive":
            self._validate_archive_view_target(target_root)
            return self._archive_inventory_status_context(
                context,
                job_id=job_id,
            )
        if job_id is not None:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Watched job доступен только для archive view",
            )
        return self._restore_inventory_status_context(
            context,
            target_root=target_root,
        )

    def restore_inventory_children(
        self,
        backup_id: ArtifactRef | str,
        *,
        server_id: str | None = None,
        target_root: str | None = None,
        parent: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        view: str = "restore",
    ) -> dict:
        view = self._validate_inventory_view(view)
        context = self._managed_restore_inventory_context(
            backup_id,
            server_id=server_id,
        )
        if view == "archive":
            self._validate_archive_view_target(target_root)
            archive_view = self._require_archive_inventory_view(context)
            return query_archive_inventory_view_children(
                archive_view,
                parent=parent,
                cursor=cursor,
                limit=limit,
            )
        projection = self._require_restore_inventory_projection(
            context,
            target_root=target_root,
        )
        return query_archive_inventory_children(
            projection,
            parent=parent,
            cursor=cursor,
            limit=limit,
        )

    def search_restore_inventory(
        self,
        backup_id: ArtifactRef | str,
        *,
        query: str,
        server_id: str | None = None,
        target_root: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> dict:
        context = self._managed_restore_inventory_context(
            backup_id,
            server_id=server_id,
        )
        projection = self._require_restore_inventory_projection(
            context,
            target_root=target_root,
        )
        return query_archive_inventory_search(
            projection,
            query=query,
            cursor=cursor,
            limit=limit,
        )

    def _imported_encrypted_inventory_buildable(self, context: dict) -> bool:
        """Зашифрованный импорт, у которого ещё нет готового v2-сайдкара.

        Такой сайдкар строится только с паролем (расшифровка + инспекция) —
        фоновый индексатор его построить не может и честно отказывает.
        """
        if context.get("kind") != "imported":
            return False
        if context["publication"].get("encrypted") is not True:
            return False
        try:
            self._load_restore_inventory_snapshot(context)
        except BackupError as exc:
            # resource_limit — не «сайдкара нет», а отдельный недоступный статус
            return self._inventory_resource_status(exc) is None
        return False

    def _build_imported_encrypted_inventory(
        self,
        context: dict,
        password: str | None,
        *,
        replace_existing: bool = False,
    ) -> None:
        """Синхронно построить v2-сайдкар зашифрованного импорта с паролем.

        Расшифровка во временный staging-файл (удаление сразу после инспекции),
        пароль в job-очередь не попадает — поэтому это делается синхронно,
        а не через фоновый индексатор.
        """
        entry_key = context["entry_key"]
        server_id = context["server_id"]
        with self.coordinator.acquire_import_publish(entry_key, server_id=server_id):
            resolved = self.storage.resolve_import_bundle(
                entry_key,
                server_id=server_id,
            )
            if (
                not replace_existing
                and self.storage.read_import_archive_inventory(resolved) is not None
            ):
                # Параллельный вызов уже построил сайдкар
                return
            archive = Path(resolved["archive"])
            if not archive.is_file():
                raise BackupError(
                    ErrorCode.ARTIFACT_NOT_FOUND,
                    "Импортированный архив не найден",
                )
            # Явный пароль приоритетнее сохранённого (enc1:); нет ни того, ни
            # другого — ENCRYPTION_PASSWORD_INVALID/REQUIRED из расшифровки.
            plain = self._decrypt_restore_archive(archive, password)
            try:
                inspected = inspect_archive(plain)
            finally:
                self._discard_decrypted_restore_archive(plain)
            publication = resolved["publication"]
            checksum = (publication.get("checksum") or {}).get("value")
            try:
                inventory = self._import_archive_inventory(
                    inspected,
                    publication,
                    checksum,
                    consume_members=True,
                )
            except BackupError:
                # Читаемый, но физически неиндексируемый состав: остаёмся без
                # v2-сайдкара (как и фоновый индексатор — compatibility_only).
                return
            self.storage.write_import_archive_inventory(
                resolved,
                inventory,
                verify_archive_checksum=False,
                replace_existing=replace_existing,
            )

    def prepare_imported_restore_inventory(
        self,
        entry_key: str,
        *,
        server_id: str | None = None,
        target_root: str | None = None,
        retry: bool = False,
        rebuild: bool = False,
        view: str = "restore",
        password: str | None = None,
    ) -> dict:
        view = self._validate_inventory_view(view)
        context = self._imported_restore_inventory_context(
            entry_key,
            server_id=server_id,
        )
        # Зашифрованный импорт без сайдкара: строим синхронно с паролем
        # (rebuild — перестроить существующий сайдкар заново).
        if self._imported_encrypted_inventory_buildable(context) or (
            rebuild and context["publication"].get("encrypted") is True
        ):
            self._build_imported_encrypted_inventory(
                context,
                password,
                replace_existing=rebuild,
            )
        if view == "archive":
            self._validate_archive_view_target(target_root)
            return self._prepare_archive_inventory_context(
                context,
                retry=retry,
                rebuild=rebuild,
            )
        if rebuild:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Rebuild доступен только для archive view",
            )
        return self._prepare_restore_inventory_context(
            context,
            target_root=target_root,
            retry=retry,
        )

    def imported_restore_inventory_status(
        self,
        entry_key: str,
        *,
        server_id: str | None = None,
        target_root: str | None = None,
        view: str = "restore",
        job_id: str | None = None,
    ) -> dict:
        view = self._validate_inventory_view(view)
        context = self._imported_restore_inventory_context(
            entry_key,
            server_id=server_id,
        )
        if view == "archive":
            self._validate_archive_view_target(target_root)
            return self._archive_inventory_status_context(
                context,
                job_id=job_id,
            )
        if job_id is not None:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Watched job доступен только для archive view",
            )
        return self._restore_inventory_status_context(
            context,
            target_root=target_root,
        )

    def imported_restore_inventory_children(
        self,
        entry_key: str,
        *,
        server_id: str | None = None,
        target_root: str | None = None,
        parent: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        view: str = "restore",
    ) -> dict:
        view = self._validate_inventory_view(view)
        context = self._imported_restore_inventory_context(
            entry_key,
            server_id=server_id,
        )
        if view == "archive":
            self._validate_archive_view_target(target_root)
            archive_view = self._require_archive_inventory_view(context)
            return query_archive_inventory_view_children(
                archive_view,
                parent=parent,
                cursor=cursor,
                limit=limit,
            )
        projection = self._require_restore_inventory_projection(
            context,
            target_root=target_root,
        )
        return query_archive_inventory_children(
            projection,
            parent=parent,
            cursor=cursor,
            limit=limit,
        )

    def search_imported_restore_inventory(
        self,
        entry_key: str,
        *,
        query: str,
        server_id: str | None = None,
        target_root: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> dict:
        context = self._imported_restore_inventory_context(
            entry_key,
            server_id=server_id,
        )
        projection = self._require_restore_inventory_projection(
            context,
            target_root=target_root,
        )
        return query_archive_inventory_search(
            projection,
            query=query,
            cursor=cursor,
            limit=limit,
        )

    def list_imported_archives(
        self,
        *,
        server_id: str | None = None,
    ) -> list[dict]:
        """List ordinary imports directly from their published bundle namespace."""
        return self.storage.list_import_bundles(server_id=server_id)

    def _inspect_imported_archive_for_ui(
        self,
        resolved: dict,
        *,
        _diagnostics: dict | None = None,
    ) -> tuple[dict, bool]:
        """Use bound JSON metadata for legacy UI, with a physical fallback."""
        started = time.perf_counter()
        cached = self.storage.read_import_archive_inventory(resolved)
        publication_inspection = resolved["publication"].get("inspection") or {}
        raw_manifest_not_represented = (
            cached is not None
            and cached["manifest"] is None
            and publication_inspection.get("manifest_status") == "present"
        )
        legacy = None
        if cached is None:
            legacy = self.storage.read_legacy_import_archive_inventory(resolved)
        inventory_hit = (cached is not None and not raw_manifest_not_represented) or legacy is not None
        if _diagnostics is not None:
            _diagnostics["inventory_lookup_validation_ms"] = round(
                (time.perf_counter() - started) * 1000,
                3,
            )
            _diagnostics["inventory_hit"] = inventory_hit
        if cached is not None and not raw_manifest_not_represented:
            members = expand_archive_inventory_members(cached, validate=False)
            if _diagnostics is not None:
                _diagnostics["archive_member_count"] = len(members)
            return {
                "manifest": cached["manifest"],
                "members": members,
            }, True
        if legacy is not None:
            if _diagnostics is not None:
                _diagnostics["archive_member_count"] = len(legacy["members"])
            return {
                "manifest": legacy["manifest"],
                "members": legacy["members"],
            }, True

        started = time.perf_counter()
        inspected = inspect_archive(resolved["archive"])
        if _diagnostics is not None:
            _diagnostics["tar_scan_ms"] = round(
                (time.perf_counter() - started) * 1000,
                3,
            )
            _diagnostics["archive_member_count"] = len(inspected["members"])
        started = time.perf_counter()
        try:
            inventory = self._import_archive_inventory(
                inspected,
                resolved["publication"],
                (resolved["publication"].get("checksum") or {}).get("value"),
                consume_members=True,
            )
            validated_members = expand_archive_inventory_members(
                inventory,
                validate=False,
            )
        except BackupError:
            if _diagnostics is not None:
                _diagnostics["member_validation_ms"] = round(
                    (time.perf_counter() - started) * 1000,
                    3,
                )
                _diagnostics["inventory_cache_write_ms"] = 0.0
            # Preview remains available for readable but non-restorable archives.
            return inspected, False
        if _diagnostics is not None:
            _diagnostics["member_validation_ms"] = round(
                (time.perf_counter() - started) * 1000,
                3,
            )

        started = time.perf_counter()
        try:
            self.storage.write_import_archive_inventory(resolved, inventory)
        except BackupError:
            # Cache persistence is never a prerequisite or authorization source.
            pass
        if _diagnostics is not None:
            _diagnostics["inventory_cache_write_ms"] = round(
                (time.perf_counter() - started) * 1000,
                3,
            )
        return {
            "manifest": inspected["manifest"],
            "members": validated_members,
        }, True

    def preview_imported_archive(
        self,
        entry_key: str,
        *,
        server_id: str | None = None,
        include_members: bool = True,
        include_diagnostics: bool = False,
    ) -> dict:
        """Return a bounded inventory-only descriptor for one import."""
        del include_members, include_diagnostics
        context = self._imported_restore_inventory_context(
            entry_key,
            server_id=server_id,
        )
        publication = context["publication"]
        origin = publication.get("origin")
        if not isinstance(origin, dict):
            origin = None
        return {
            "entry_key": context["entry_key"],
            "filename": publication["filename"],
            "destination": publication["destination"],
            "format": context["archive"]["format"],
            "bytes": context["archive"]["bytes"],
            "imported_at": publication.get("imported_at"),
            "origin": origin,
            "inventory": self._archive_inventory_status_context(context),
        }

    def imported_restore_readiness(
        self,
        entry_key: str,
        *,
        server_id: str | None = None,
    ) -> dict:
        """Return bounded Restore-UI hints without TAR or deep inventory reads."""
        with self.coordinator.acquire_import_read(entry_key, server_id=server_id):
            resolved = self.storage.resolve_import_bundle(
                entry_key,
                server_id=server_id,
            )
            if not resolved["archive"].is_file():
                raise BackupError(
                    ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE,
                    "Импортированный архив не найден",
                    retryable=True,
                )
            publication = resolved["publication"]
            restore = publication.get("restore")
            requires_target_root = True
            if isinstance(restore, dict):
                requires_target_root = restore.get("requires_target_root") is not False
            try:
                header = self.storage.read_import_archive_inventory_header(resolved)
            except BackupError:
                header = None
            if header is not None:
                requires_target_root = (
                    header["layout"] == LAYOUT_RELATIVE_TARGET_ROOT
                )
        return {
            "entry_key": entry_key,
            "eligible": True,
            "requires_target_root": requires_target_root,
            "encrypted": publication.get("encrypted") is True,
        }

    def imported_restore_password_probe(
        self,
        entry_key: str,
        *,
        server_id: str | None = None,
        password: str | None = None,
        use_stored: bool = False,
    ) -> dict:
        """Быстрая проверка пароля зашифрованного импорта (первый кусок B4VE).

        Пароль наружу не отдаётся: use_stored проверяет сохранённый (enc1:) на
        сервере, явный password — введённый пользователем. Ответ — только факт.
        """
        with self.coordinator.acquire_import_read(entry_key, server_id=server_id):
            resolved = self.storage.resolve_import_bundle(
                entry_key,
                server_id=server_id,
            )
            archive = Path(resolved["archive"])
        if not is_encrypted_file(archive):
            return {"ok": True}
        if use_stored:
            try:
                stored = get_stored_backup_password()
            except SecretBoxError:
                stored = None
            if not stored:
                return {"ok": False}
            return {"ok": verify_password(archive, stored)}
        if not password:
            return {"ok": False}
        if len(password) > MAX_PASSWORD_LEN:
            return {"ok": False}
        return {"ok": verify_password(archive, password)}

    def restore_password_probe(
        self,
        backup_id: ArtifactRef | str,
        *,
        server_id: str | None = None,
        password: str | None = None,
        use_stored: bool = False,
    ) -> dict:
        """Быстрая проверка пароля зашифрованного managed-архива (первый кусок)."""
        context = self._managed_restore_inventory_context(
            backup_id,
            server_id=server_id,
        )
        with self.coordinator.acquire_artifact_read(context["artifact_ref"]):
            archive = Path(context["archive_path"])
            if not archive.is_file():
                raise BackupError(
                    ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE,
                    "Опубликованный archive не найден",
                    retryable=True,
                )
        if not is_encrypted_file(archive):
            return {"ok": True}
        if use_stored:
            try:
                stored = get_stored_backup_password()
            except SecretBoxError:
                stored = None
            if not stored:
                return {"ok": False}
            return {"ok": verify_password(archive, stored)}
        if not password:
            return {"ok": False}
        if len(password) > MAX_PASSWORD_LEN:
            return {"ok": False}
        return {"ok": verify_password(archive, password)}

    def resolve_imported_download(
        self,
        entry_key: str,
        *,
        server_id: str | None = None,
    ) -> dict:
        """Resolve an ordinary import for download without Catalog or Operation lookup."""
        permit = self.coordinator.acquire_import_read(entry_key, server_id=server_id)
        try:
            resolved = self.storage.resolve_import_bundle(
                entry_key,
                server_id=server_id,
            )
            archive = resolved["archive"]
            if not archive.is_file():
                raise BackupError(
                    ErrorCode.ARTIFACT_NOT_FOUND,
                    "Импортированный архив не найден",
                )
            publication = resolved["publication"]
            return {
                "path": archive,
                "filename": publication["filename"],
                "format": publication["format"],
                "permit": permit,
            }
        except Exception:
            permit.release()
            raise

    def preview_managed_archive(
        self,
        backup_id: ArtifactRef | str,
        *,
        server_id: str | None = None,
    ) -> dict:
        """Return a bounded inventory-only descriptor for one managed archive."""
        context = self._managed_restore_inventory_context(
            backup_id,
            server_id=server_id,
        )
        with self.coordinator.acquire_artifact_read(context["artifact_ref"]):
            if not context["archive_path"].is_file():
                raise BackupError(
                    ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE,
                    "Опубликованный archive не найден",
                    retryable=True,
                )
        record = context["record"]
        return {
            "backup_id": context["source"]["backup_id"],
            "filename": record.get("filename"),
            "type": context["source"]["type"],
            "format": context["archive"]["format"],
            "bytes": context["archive"]["bytes"],
            "created_at": record.get("created_at"),
            "published_at": record.get("published_at"),
            "inventory": self._archive_inventory_status_context(context),
        }

    def _plan_managed_restore_resolved(
        self,
        record: dict,
        artifact_ref: ArtifactRef,
        *,
        target_root: str | None = None,
        password: str | None = None,
        archive_override: Path | None = None,
    ) -> dict:
        with self.coordinator.acquire_artifact_read(artifact_ref):
            archive = archive_override or self.storage.resolve_key(record["storage"]["key"])
            if not archive.is_file():
                raise BackupError(
                    ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE,
                    "Опубликованный archive не найден",
                    retryable=True,
                )
            # Зашифрованный архив расшифровывается во временный staging-файл,
            # который живёт ровно до построения плана. archive_override — уже
            # расшифрованный temp, принадлежащий вызывающему (apply-фаза
            # использует его же для доставки на target).
            cleanup_dir: str | None = None
            try:
                if is_encrypted_file(archive) and archive_override is None:
                    plain = self._decrypt_restore_archive(archive, password)
                    cleanup_dir = plain.parent.name
                    archive = plain
                inspected = validate_archive_physical(archive)
                plan = build_restore_plan(
                    members=inspected["members"],
                    catalog_record=record,
                    target_root=target_root,
                    storage_root=(
                        str(self.storage.root)
                        if record.get("type") == "bot4vps"
                        else None
                    ),
                )
            finally:
                if cleanup_dir is not None:
                    self.storage.remove_staging(cleanup_dir, "create")
        return {
            "archive": record,
            "plan": plan,
            "preview": build_preview_tree(
                plan["entries"],
                roots=[item["root"] for item in plan["roots"]],
            ),
            "delete": None,
            "notice": (
                "План построен по содержимому архива. Инвентаризация target и "
                "применение Restore подключаются отдельной фазой."
            ),
        }

    def _build_imported_restore_plan(
        self,
        resolved: dict,
        inspected: dict,
        *,
        target_root: str | None = None,
        _diagnostics: dict | None = None,
    ) -> dict:
        started = time.perf_counter()
        usable_manifest = None
        if isinstance(inspected.get("manifest"), dict):
            try:
                # validate_manifest normalizes exclusions in place. Imported
                # metadata remains the archive's untouched physical view.
                usable_manifest = validate_manifest(
                    copy.deepcopy(inspected["manifest"])
                )
            except BackupError:
                usable_manifest = None
        if _diagnostics is not None:
            _diagnostics["manifest_validation_ms"] = round(
                (time.perf_counter() - started) * 1000,
                3,
            )
        destination = resolved["publication"].get("destination") or {}
        started = time.perf_counter()
        plan = build_restore_plan(
            members=inspected["members"],
            manifest=usable_manifest,
            target_root=target_root,
            storage_root=(
                str(self.storage.root)
                if destination.get("scope") == "bot4vps"
                else None
            ),
        )
        if _diagnostics is not None:
            _diagnostics["restore_plan_ms"] = round(
                (time.perf_counter() - started) * 1000,
                3,
            )
        started = time.perf_counter()
        preview = build_preview_tree(
            plan["entries"],
            roots=[item["root"] for item in plan["roots"]],
        )
        if _diagnostics is not None:
            _diagnostics["full_preview_tree_ms"] = round(
                (time.perf_counter() - started) * 1000,
                3,
            )
        return {
            "archive": resolved["publication"],
            "plan": plan,
            "preview": preview,
            "delete": None,
            "notice": (
                "План построен по содержимому импортированного архива. "
                "Инвентаризация target и применение Restore подключаются "
                "отдельной фазой."
            ),
        }

    def _plan_imported_restore_resolved(
        self,
        resolved: dict,
        *,
        target_root: str | None = None,
        password: str | None = None,
        archive_override: Path | None = None,
    ) -> dict:
        """Physically validate already locked import bytes for Restore mutation."""
        archive = archive_override or resolved["archive"]
        if not archive.is_file():
            raise BackupError(
                ErrorCode.ARTIFACT_NOT_FOUND,
                "Импортированный архив не найден",
            )
        # Зашифрованный импорт расшифровывается во временный staging-файл
        # ровно на время физической валидации и построения плана.
        cleanup_dir: str | None = None
        try:
            if is_encrypted_file(archive) and archive_override is None:
                plain = self._decrypt_restore_archive(archive, password)
                cleanup_dir = plain.parent.name
                archive = plain
            inspected = validate_archive_physical(archive)
            return self._build_imported_restore_plan(
                resolved,
                inspected,
                target_root=target_root,
            )
        finally:
            if cleanup_dir is not None:
                self.storage.remove_staging(cleanup_dir, "create")

    def _plan_imported_restore_for_ui_resolved(
        self,
        resolved: dict,
        *,
        target_root: str | None = None,
        password: str | None = None,
        _diagnostics: dict | None = None,
    ) -> dict:
        """Plan read-only UI from a bound cache, falling back to the actual TAR."""
        archive = resolved["archive"]
        if not archive.is_file():
            raise BackupError(
                ErrorCode.ARTIFACT_NOT_FOUND,
                "Импортированный архив не найден",
            )
        cleanup_dir: str | None = None
        try:
            if is_encrypted_file(archive):
                plain = self._decrypt_restore_archive(archive, password)
                cleanup_dir = plain.parent.name
                # Инвентаризационный сайдкар зашифрованного импорта пуст
                # (члены недоступны без пароля) — читаем расшифрованный TAR.
                inspected = inspect_archive(plain)
                inspected = {
                    "manifest": inspected["manifest"],
                    "members": _validate_managed_members(list(inspected["members"])),
                }
            else:
                inspected, members_validated = self._inspect_imported_archive_for_ui(
                    resolved,
                    _diagnostics=_diagnostics,
                )
                if not members_validated:
                    started = time.perf_counter()
                    inspected = {
                        "manifest": inspected["manifest"],
                        "members": _validate_managed_members(list(inspected["members"])),
                    }
                    if _diagnostics is not None:
                        _diagnostics["member_validation_ms"] = round(
                            (time.perf_counter() - started) * 1000,
                            3,
                        )
            return self._build_imported_restore_plan(
                resolved,
                inspected,
                target_root=target_root,
                _diagnostics=_diagnostics,
            )
        finally:
            if cleanup_dir is not None:
                self.storage.remove_staging(cleanup_dir, "create")

    @staticmethod
    def _effective_restore_plan_response(
        planned: dict,
        *,
        selection_mode: str,
        selected_paths,
        include_directory_tree: bool = True,
        _diagnostics: dict | None = None,
    ) -> dict:
        full_plan = planned["plan"]
        mode = normalize_selection_mode(selection_mode)
        started = time.perf_counter()
        context = _build_restore_planning_context(full_plan)
        if _diagnostics is not None:
            _diagnostics["planning_context_ms"] = round(
                (time.perf_counter() - started) * 1000,
                3,
            )
        started = time.perf_counter()
        directory_tree = (
            build_restore_directory_tree(
                full_plan,
                include_files=True,
                _context=context,
            )
            if include_directory_tree
            else None
        )
        if _diagnostics is not None:
            _diagnostics["directory_tree_ms"] = round(
                (time.perf_counter() - started) * 1000,
                3,
            )
            _diagnostics["directory_tree_included"] = include_directory_tree
            _diagnostics["directory_tree_nodes"] = (
                int(directory_tree.get("node_count") or 0)
                if isinstance(directory_tree, dict)
                else 0
            )
        started = time.perf_counter()
        effective = build_effective_restore_plan(
            full_plan,
            selection_mode=mode,
            selected_paths=selected_paths,
            _context=context,
        )
        if _diagnostics is not None:
            _diagnostics["effective_plan_ms"] = round(
                (time.perf_counter() - started) * 1000,
                3,
            )
        started = time.perf_counter()
        try:
            assert_online_restore_scope_safe(effective)
        except BackupError as exc:
            if _diagnostics is not None:
                _diagnostics["effective_policy_ms"] = round(
                    (time.perf_counter() - started) * 1000,
                    3,
                )
            if mode != SELECTION_MODE_FULL:
                raise
            result = dict(planned)
            result.update({
                "plan": None,
                "preview": None,
                "directory_tree": directory_tree,
                "full_restore_unavailable": True,
                "policy": {
                    "reason": "full_restore_unavailable",
                    "blocked_paths": list(
                        exc.details.get("blocked_paths") or ()
                    ),
                    "message": (
                        "Полное восстановление этого бэкапа недоступно: архив "
                        "содержит системные файлы, изменение которых может "
                        "нарушить работу работающей системы. Пользователю "
                        "предлагается выбрать разрешённые элементы для восстановления."
                    ),
                },
            })
            if _diagnostics is not None:
                _diagnostics["effective_preview_tree_ms"] = 0.0
            return result
        if _diagnostics is not None:
            _diagnostics["effective_policy_ms"] = round(
                (time.perf_counter() - started) * 1000,
                3,
            )
        started = time.perf_counter()
        effective_preview = build_preview_tree(
            effective["entries"],
            roots=[item["root"] for item in effective["roots"]],
        )
        if _diagnostics is not None:
            _diagnostics["effective_preview_tree_ms"] = round(
                (time.perf_counter() - started) * 1000,
                3,
            )
        result = dict(planned)
        result.update({
            "plan": effective,
            "preview": effective_preview,
            "directory_tree": directory_tree,
            "full_restore_unavailable": False,
            "policy": None,
        })
        return result

    def plan_restore(
        self,
        backup_id: ArtifactRef | str,
        *,
        server_id: str | None = None,
        target_root: str | None = None,
        selection_mode: str = SELECTION_MODE_FULL,
        selected_paths=None,
        include_directory_tree: bool = True,
        password: str | None = None,
    ) -> dict:
        """Построить effective plan managed backup, ничего не изменяя."""
        ref = self._requested_ref(backup_id, server_id)
        record = self.catalog.get(ref)
        planned = self._plan_managed_restore_resolved(
            record,
            self._record_ref(record),
            target_root=target_root,
            password=password,
        )
        return self._effective_restore_plan_response(
            planned,
            selection_mode=selection_mode,
            selected_paths=selected_paths,
            include_directory_tree=include_directory_tree,
        )

    def plan_imported_restore(
        self,
        entry_key: str,
        *,
        server_id: str | None = None,
        target_root: str | None = None,
        selection_mode: str = SELECTION_MODE_FULL,
        selected_paths=None,
        include_directory_tree: bool = True,
        include_diagnostics: bool = False,
        password: str | None = None,
    ) -> dict:
        """Построить effective plan imported bundle под shared read lock."""
        total_started = time.perf_counter()
        diagnostics = (
            {
                "schema_version": 1,
                "inventory_hit": False,
                "tar_scan_ms": 0.0,
                "member_validation_ms": 0.0,
                "inventory_cache_write_ms": 0.0,
            }
            if include_diagnostics
            else None
        )
        started = time.perf_counter()
        permit = self.coordinator.acquire_import_read(entry_key, server_id=server_id)
        if diagnostics is not None:
            diagnostics["import_lock_wait_ms"] = round(
                (time.perf_counter() - started) * 1000,
                3,
            )
        with permit:
            started = time.perf_counter()
            resolved = self.storage.resolve_import_bundle(
                entry_key,
                server_id=server_id,
            )
            if diagnostics is not None:
                diagnostics["bundle_resolution_ms"] = round(
                    (time.perf_counter() - started) * 1000,
                    3,
                )
            planned = self._plan_imported_restore_for_ui_resolved(
                resolved,
                target_root=target_root,
                password=password,
                _diagnostics=diagnostics,
            )
            if diagnostics is not None:
                diagnostics["planned_member_count"] = len(planned["plan"]["entries"])
            result = self._effective_restore_plan_response(
                planned,
                selection_mode=selection_mode,
                selected_paths=selected_paths,
                include_directory_tree=include_directory_tree,
                _diagnostics=diagnostics,
            )
        if diagnostics is not None:
            diagnostics["manager_total_ms"] = round(
                (time.perf_counter() - total_started) * 1000,
                3,
            )
            result["diagnostics"] = diagnostics
        return result

    def rename_managed_archive(
        self,
        backup_id: ArtifactRef | str,
        filename: str,
        *,
        server_id: str | None = None,
    ) -> dict:
        filename = validate_archive_filename(filename)
        requested = self._requested_ref(backup_id, server_id)
        ref = self.catalog.resolve(requested)
        with self.coordinator.acquire_artifact_publish(ref):
            with self.coordinator.destination_lock(self._destination_server_id(ref)):
                self._assert_filename_available(
                    filename,
                    server_id=self._destination_server_id(ref),
                    exclude_ref=ref,
                )
                return self.catalog.update_filename(ref, filename)

    def rename_imported_archive(
        self,
        entry_key: str,
        filename: str,
        *,
        server_id: str | None = None,
    ) -> dict:
        filename = validate_archive_filename(filename)
        with self.coordinator.acquire_import_publish(entry_key, server_id=server_id):
            with self.coordinator.destination_lock(server_id):
                resolved = self.storage.resolve_import_bundle(entry_key, server_id=server_id)
                self._assert_filename_available(
                    filename,
                    server_id=server_id,
                    exclude_entry_key=entry_key,
                )
                return self.storage.update_import_filename(
                    resolved["publication_path"],
                    filename,
                )

    def delete_imported_archive(
        self,
        entry_key: str,
        *,
        server_id: str | None = None,
    ) -> dict:
        """Delete the complete ordinary-import bundle as one durable resource."""
        with self.coordinator.acquire_import_delete(entry_key, server_id=server_id):
            with self.coordinator.destination_lock(server_id):
                self.storage.delete_import_bundle(entry_key, server_id=server_id)
        return {"deleted_entry_key": entry_key}
    def list_catalog(self, **filters) -> list[dict]:
        return self.catalog.list(**filters)

    def get_catalog_record(
        self,
        backup_id: ArtifactRef | str,
        *,
        server_id: str | None = None,
    ) -> dict:
        """Return one validated committed Catalog record for read-only Web views."""
        return self.catalog.get(self._requested_ref(backup_id, server_id))

    def get_operation(self, operation_id: str) -> dict:
        # Для выполняемого self-restore в view добавляется живой прогресс
        # раннера (state.json) — единый watch для Web и поллинга CLI.
        return enrich_operation(self.operations.get(operation_id))

    def list_operations(
        self,
        *,
        operation_type: str | None = None,
        status: str | None = None,
        server_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        records = self.operations.list_all()
        if operation_type is not None:
            records = [item for item in records if item.get("type") == operation_type]
        if status is not None:
            records = [item for item in records if item.get("status") == status]
        if server_id is not None:
            records = [item for item in records if item.get("target", {}).get("server_id") == server_id]
        records = sorted(records, key=lambda item: (item["created_at"], item["operation_id"]), reverse=True)
        if limit is not None:
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
                raise BackupError(ErrorCode.INVALID_REQUEST, "limit должен быть integer >= 1")
            records = records[:limit]
        return records

    def clear_operation_history(self) -> dict:
        """Clear only terminal Operation history; active state is untouched."""
        return {"deleted": self.operations.clear_history()}

    def cancel_operation(self, operation_id: str) -> dict:
        return self.operations.request_cancel(operation_id)

    def resolve_download(
        self,
        backup_id: ArtifactRef | str,
        *,
        server_id: str | None = None,
    ) -> dict:
        """Resolve a committed artifact while holding its shared read lock."""
        record = self.catalog.get(self._requested_ref(backup_id, server_id))
        permit = self.coordinator.acquire_artifact_read(self._record_ref(record))
        try:
            archive_path = self.storage.resolve_key(record["storage"]["key"])
            checksum_path = self.storage.resolve_key(record["storage"]["checksum_key"])
            if not archive_path.is_file() or not checksum_path.is_file():
                raise BackupError(ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE, "Опубликованная pair неполна", retryable=True)
            return {
                "backup_id": record["backup_id"],
                "path": archive_path,
                "filename": record["filename"],
                "size": archive_path.stat().st_size,
                "permit": permit,
            }
        except Exception:
            permit.release()
            raise

    def reconcile_startup(self) -> dict:
        with self.coordinator.reconciliation_lock(timeout=30.0):
            maintenance_cleared = self.coordinator.reconcile_maintenance_state()
            abandoned, live_operation_ids = [], set()
            operation_snapshot = self.operations.list_active()
            recoverable_publications: dict[str, list[dict]] = {}
            for operation in operation_snapshot:
                result_backup_id = operation.get("result_backup_id")
                if (
                    operation.get("status") not in TERMINAL_STATUSES
                    and operation.get("type") in {"create", "import"}
                    and operation.get("stage")
                    in {"publishing_artifact", "updating_catalog"}
                    and isinstance(result_backup_id, str)
                ):
                    recoverable_publications.setdefault(
                        result_backup_id,
                        [],
                    ).append(operation)
                if operation.get("status") in TERMINAL_STATUSES:
                    continue
                permit = self.coordinator.try_acquire_operation_owner(operation["operation_id"])
                if permit is None:
                    live_operation_ids.add(operation["operation_id"])
                else:
                    try:
                        self.operations.mark_abandoned(operation["operation_id"])
                        abandoned.append(operation["operation_id"])
                    finally:
                        permit.release()
            now = time.time()
            staging_ttl = int(self.config["safety"]["staging_ttl_seconds"])
            stale_staging = []
            for kind in ("create", "import"):
                base = self.storage.root / "staging" / kind
                for staging in base.iterdir() if base.exists() else ():
                    if not staging.is_dir() or staging.name in live_operation_ids:
                        continue
                    try:
                        stale = now - staging.stat().st_mtime >= staging_ttl
                    except OSError:
                        stale = False
                    if stale:
                        shutil.rmtree(staging)
                        self.storage._fsync_dir(base)
                        stale_staging.append(str(staging.relative_to(self.storage.root)))
            invalid_catalog = []
            for item in self.catalog.scan_invalid():
                backup_id = item["backup_id"]
                ref = item.get("ref")
                if ref is None:
                    # Запись вне namespace (мусор или не перенесённый flat
                    # record): identity недоступна, изолируем по пути.
                    if self.catalog.isolate_path(item["path"], "invalid_filename"):
                        invalid_catalog.append(backup_id)
                    continue
                with self.coordinator.acquire_artifact_delete(ref):
                    if self.catalog.isolate(ref, "schema_invalid"):
                        invalid_catalog.append(backup_id)
            released_claims = []
            for record in self.catalog.list():
                claim = record.get("retention", {}).get("claim")
                if not isinstance(claim, dict):
                    continue
                try:
                    expired = parse_utc_timestamp(claim.get("expires_at")) <= utc_now()
                except (TypeError, ValueError):
                    expired = True
                owner_live = claim.get("owner_operation_id") in live_operation_ids
                if not owner_live and isinstance(claim.get("owner_operation_id"), str):
                    owner_probe = self.coordinator.try_acquire_operation_owner(claim["owner_operation_id"])
                    if owner_probe is None:
                        owner_live = True
                    elif owner_probe is not None:
                        owner_probe.release()
                if expired and not owner_live and isinstance(claim.get("claim_id"), str):
                    released = self.catalog.release_claim(self._record_ref(record), expected_version=int(record["artifact_version"]), expected_claim_id=claim["claim_id"])
                    released_claims.append({"backup_id": record["backup_id"], "artifact_version": released["artifact_version"]})
            missing_pairs = []
            for snapshot in self.catalog.list():
                backup_id = snapshot["backup_id"]
                artifact_ref = self._record_ref(snapshot)
                with self.coordinator.acquire_artifact_delete(artifact_ref):
                    with self.coordinator.catalog_lock():
                        try:
                            record = self.catalog.get(artifact_ref)
                        except BackupError as exc:
                            if exc.code == ErrorCode.ARTIFACT_NOT_FOUND.value:
                                continue
                            raise
                        archive = self.storage.resolve_key(record["storage"]["key"])
                        checksum = self.storage.resolve_key(record["storage"]["checksum_key"])
                        archive_exists = archive.is_file()
                        checksum_exists = checksum.is_file()
                        if not archive_exists or not checksum_exists:
                            claim = record.get("retention", {}).get("claim") or {}
                            if (
                                not archive_exists
                                and not checksum_exists
                                and claim.get("state") == "deleting"
                                and isinstance(claim.get("claim_id"), str)
                            ):
                                owner_live = False
                                owner_operation_id = claim.get("owner_operation_id")
                                if isinstance(owner_operation_id, str):
                                    owner_probe = self.coordinator.try_acquire_operation_owner(
                                        owner_operation_id
                                    )
                                    if owner_probe is None:
                                        owner_live = True
                                    else:
                                        owner_probe.release()
                                if not owner_live:
                                    self.catalog.finish_delete(
                                        artifact_ref,
                                        expected_version=int(record["artifact_version"]),
                                        expected_claim_id=claim["claim_id"],
                                        lock_held=True,
                                    )
                                    continue
                            missing_pairs.append(backup_id)
                            if self.catalog.isolate(
                                artifact_ref,
                                "storage_pair_missing",
                                lock_held=True,
                            ):
                                invalid_catalog.append(backup_id)
            quarantined = []
            recovered_publications = []
            operations_by_backup = recoverable_publications
            final_roots = (
                self.storage.root / "bot4vps",
                self.storage.root / "servers",
            )
            # Кандидаты группируются по artifact identity, а не по bare
            # backup_id: одинаковый backup_id в разных namespace — законное
            # состояние, и половины разных артефактов нельзя смешивать в одну
            # pair. Файлы вне канонического layout identity не имеют и
            # обрабатываются как orphan.
            grouped: dict[ArtifactRef, list[Path]] = {}
            unnamespaced: list[Path] = []
            for final_root in final_roots:
                if not final_root.exists():
                    continue
                for suffix in (".tar.gz", ".tar.gz.sha256"):
                    for path in final_root.rglob(f"*{suffix}"):
                        ref = self._storage_ref(path, path.name.removesuffix(suffix))
                        if ref is None:
                            unnamespaced.append(path)
                            continue
                        grouped.setdefault(ref, []).append(path)
            for artifact_ref in sorted(grouped, key=str):
                paths = grouped[artifact_ref]
                backup_id = artifact_ref.backup_id
                with self.coordinator.acquire_artifact_delete(artifact_ref):
                    # Catalog lock защищает только короткие visibility-проверки и
                    # commit. Чтение архива и SHA-256 выполняются без него.
                    with self.coordinator.catalog_lock():
                        if self.catalog.exists(artifact_ref):
                            continue

                    archives = [
                        path
                        for path in paths
                        if path.name.endswith(".tar.gz")
                    ]
                    checksums = [
                        path
                        for path in paths
                        if path.name.endswith(".tar.gz.sha256")
                    ]
                    linked_operations = [
                        operation
                        for operation in operations_by_backup.get(backup_id, [])
                        if self._publication_namespace_allows(operation, artifact_ref)
                    ]
                    recovered_record = None
                    if (
                        len(archives) == 1
                        and len(checksums) == 1
                        and len(linked_operations) == 1
                    ):
                        archive = archives[0]
                        checksum_path = checksums[0]
                        operation = linked_operations[0]
                        try:
                            expected = checksum_path.read_text(encoding="ascii")
                            if (
                                len(expected) != 65
                                or not expected.endswith("\n")
                                or any(
                                    char not in "0123456789abcdef"
                                    for char in expected[:-1]
                                )
                            ):
                                raise BackupError(
                                    ErrorCode.CHECKSUM_MISMATCH,
                                    "Checksum orphan archive некорректен",
                                )
                            actual = self.storage.calculate_checksum(archive)
                            if actual != expected[:-1]:
                                raise BackupError(
                                    ErrorCode.CHECKSUM_MISMATCH,
                                    "Checksum orphan archive не совпадает",
                                )
                            manifest = verify_archive(
                                archive,
                                expected_backup_id=backup_id,
                            )
                            source_info = manifest.get("source") or {}
                            target = operation.get("target") or {}
                            destination_server_id = (
                                str(target.get("server_id"))
                                if operation.get("type") == "import"
                                and target.get("kind") == "server"
                                and target.get("server_id")
                                else None
                            )
                            target_server_id = (
                                destination_server_id
                                or (
                                    source_info.get("server_id")
                                    if manifest["type"] == "server"
                                    else None
                                )
                            )
                            expected_archive, expected_checksum = self.storage.final_paths(
                                backup_id,
                                manifest["type"],
                                target_server_id,
                            )
                            if (
                                archive != expected_archive
                                or checksum_path != expected_checksum
                            ):
                                raise BackupError(
                                    ErrorCode.ARCHIVE_INVALID,
                                    "Orphan pair находится вне ожидаемого namespace",
                                )
                            target_kind = target.get("kind")
                            if (
                                target_kind not in {
                                    None,
                                    "unknown",
                                    manifest["type"],
                                    "server",
                                }
                                or (
                                    target_kind == "server"
                                    and manifest["type"] != "server"
                                )
                            ):
                                raise BackupError(
                                    ErrorCode.ARCHIVE_INVALID,
                                    "Operation и orphan archive имеют разные типы",
                                )
                            recovered_record = self._catalog_record(
                                manifest=manifest,
                                operation_id=operation["operation_id"],
                                archive_path=archive,
                                checksum_path=checksum_path,
                                checksum=actual,
                                target_server_id=target_server_id,
                                filename=archive.name,
                            )
                            # Восстановленная запись обязана принадлежать тому же
                            # namespace, что и найденная pair: иначе Catalog
                            # получил бы identity другого артефакта.
                            if ArtifactRef.from_record(recovered_record) != artifact_ref:
                                raise BackupError(
                                    ErrorCode.ARCHIVE_INVALID,
                                    "Orphan pair и восстановленная запись имеют разные namespace",
                                )
                        except (
                            BackupError,
                            OSError,
                            UnicodeError,
                            KeyError,
                            TypeError,
                            ValueError,
                        ):
                            recovered_record = None

                    if recovered_record is not None:
                        with self.coordinator.catalog_lock():
                            if self.catalog.exists(artifact_ref):
                                continue
                            self.catalog.commit_published(
                                recovered_record,
                                lock_held=True,
                            )
                        recovered_publications.append(backup_id)
                        continue

                    for path in paths:
                        if path.is_file():
                            quarantined.append(
                                str(self.storage.quarantine_path(path, "orphan"))
                            )
            for path in unnamespaced:
                if path.is_file():
                    quarantined.append(
                        str(self.storage.quarantine_path(path, "orphan"))
                    )
            return {"maintenance_cleared": maintenance_cleared, "abandoned_operations": abandoned, "live_operations": sorted(live_operation_ids), "stale_staging_removed": stale_staging, "released_claims": released_claims, "catalog_missing_pairs": missing_pairs, "invalid_catalog": sorted(set(invalid_catalog)), "recovered_publications": recovered_publications, "quarantined": quarantined}

    def _copy_secure(self, source: Path, target: Path, *, max_bytes: int | None = None) -> None:
        src_fd = None
        try:
            if source.is_symlink():
                raise BackupError(ErrorCode.INVALID_REQUEST, "Symlink import source запрещён")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            src_fd = os.open(source, flags)
            source_stat = os.fstat(src_fd)
            if not stat.S_ISREG(source_stat.st_mode):
                raise BackupError(ErrorCode.INVALID_REQUEST, "Import source должен быть regular file")
            if max_bytes is not None and source_stat.st_size > int(max_bytes):
                raise BackupError(ErrorCode.IMPORT_TOO_LARGE, "Import archive превышает допустимый размер")
            target_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            total = 0
            with os.fdopen(src_fd, "rb") as src, os.fdopen(target_fd, "wb") as dst:
                src_fd = None
                while chunk := src.read(1024 * 1024):
                    self.disk.require_creation_allowed()
                    total += len(chunk)
                    if max_bytes is not None and total > int(max_bytes):
                        raise BackupError(
                            ErrorCode.IMPORT_TOO_LARGE,
                            "Import archive превышает допустимый размер",
                        )
                    dst.write(chunk)
                self.disk.require_creation_allowed()
                dst.flush()
                os.fsync(dst.fileno())
        except BackupError:
            raise
        except OSError as exc:
            raise BackupError(ErrorCode.STAGING_IO_FAILED, "Не удалось принять import archive", retryable=True) from exc
        finally:
            if src_fd is not None:
                os.close(src_fd)
    def _catalog_record(
        self,
        *,
        manifest: dict,
        operation_id: str,
        archive_path: Path,
        checksum_path: Path,
        checksum: str,
        filename: str,
        target_server_id: str | None = None,
    ) -> dict:
        filename = validate_archive_filename(filename)
        source = dict(manifest["source"])
        source_projection = ({
            "server_id": target_server_id or source.get("server_id"),
            "server_name_snapshot": source.get("server_name"),
        } if manifest["type"] == "server" else {"install_path": source.get("install_path")})
        source_utc_offset = source.get("utc_offset")
        if source_utc_offset is not None:
            source_projection["utc_offset"] = normalize_utc_offset(source_utc_offset)
        file_count = int(manifest.get("content", {}).get("file_count") or 0)
        source_bytes = int(manifest.get("content", {}).get("source_bytes") or 0)
        published_at = utc_timestamp()
        return {
            "schema_version": 5 if source_utc_offset is not None else 4,
            "backup_id": manifest["backup_id"],
            "artifact_version": 1,
            "type": manifest["type"],
            "purpose": manifest["purpose"],
            "mode": manifest["mode"],
            "filename": filename,
            "source": source_projection,
            "created_at": manifest["created_at"],
            "published_at": published_at,
            "storage": {
                "backend": "local",
                "key": self.storage.relative_key(archive_path),
                "checksum_key": self.storage.relative_key(checksum_path),
            },
            "archive": {
                "format": "tar.gz",
                "bytes": archive_path.stat().st_size,
                "source_bytes": source_bytes,
                "file_count": file_count,
                "checksum_algorithm": "sha256",
                "checksum": checksum,
                "encrypted": bool(manifest.get("archive", {}).get("encrypted")),
            },
            "manifest": {
                "version": manifest["manifest_version"],
                "producer_version": manifest.get("producer", {}).get("version"),
                "source_paths": [item.get("path") for item in manifest.get("sources", [])],
            },
            "verification": {"status": "verified", "verified_at": published_at},
            "operation_id": operation_id,
            "retention": {
                "eligible": manifest["mode"] == "automatic" and manifest["purpose"] == "regular",
                "claim": None,
            },
        }
