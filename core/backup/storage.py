from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import stat
from contextlib import nullcontext
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from uuid import uuid4

from core.json_store import atomic_write_json

from .errors import BackupError, ErrorCode
from .ids import validate_id
from .inventory import (
    ARCHIVE_INVENTORY_HEAVY_OPERATION,
    HEAVY_ARCHIVE_INVENTORY_BYTES,
    MAX_ARCHIVE_INVENTORY_HEADER_BYTES,
    MAX_ARCHIVE_INVENTORY_V2_BYTES,
    archive_inventory_query_cache,
    build_archive_inventory_snapshot,
    parse_archive_inventory_header_prefix,
    validate_archive_inventory,
    write_archive_inventory as write_v2_archive_inventory,
)
from .manifest import validate_archive_inventory_members
from .time_utils import normalize_utc_offset, parse_utc_timestamp
from .validation import validate_archive_filename


LEGACY_ARCHIVE_INVENTORY_SCHEMA_VERSION = 1
MAX_ARCHIVE_INVENTORY_LEGACY_BYTES = 64 * 1024 * 1024


class LocalBackupStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self._prepare()

    def _prepare(self) -> None:
        for path in (
            self.root,
            self.root / "bot4vps",
            self.root / "servers",
            self.root / "imports" / "bot4vps",
            self.root / "imports" / "servers",
            self.root / "staging" / "create",
            self.root / "staging" / "import",
            self.root / "quarantine",
        ):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._chmod(path, 0o700)

    @staticmethod
    def _chmod(path: Path, mode: int) -> None:
        try:
            path.chmod(mode)
        except OSError as exc:
            raise BackupError(ErrorCode.STORAGE_BACKEND_ERROR, "Не удалось установить безопасные права storage") from exc

    @staticmethod
    def _id(value: str, field: str) -> str:
        try:
            return validate_id(value, field=field)
        except ValueError as exc:
            raise BackupError(ErrorCode.INVALID_REQUEST, str(exc)) from exc

    def create_staging(self, operation_id: str, kind: str = "create") -> Path:
        operation_id = self._id(operation_id, "operation_id")
        if kind not in {"create", "import"}:
            raise BackupError(ErrorCode.INVALID_REQUEST, "Некорректный вид staging")
        path = self.root / "staging" / kind / operation_id
        try:
            path.mkdir(mode=0o700)
            self._chmod(path, 0o700)
            return path
        except FileExistsError as exc:
            raise BackupError(ErrorCode.OPERATION_CONFLICT, "Staging операции уже существует", retryable=True) from exc
        except OSError as exc:
            raise BackupError(ErrorCode.STAGING_IO_FAILED, "Не удалось создать staging", retryable=True) from exc

    def remove_staging(self, operation_id: str, kind: str = "create") -> None:
        operation_id = self._id(operation_id, "operation_id")
        if kind not in {"create", "import"}:
            raise BackupError(ErrorCode.INVALID_REQUEST, "Некорректный вид staging")
        shutil.rmtree(self.root / "staging" / kind / operation_id, ignore_errors=True)

    def staging_archive_path(self, operation_id: str, backup_id: str, kind: str = "create") -> Path:
        operation_id = self._id(operation_id, "operation_id")
        backup_id = self._id(backup_id, "backup_id")
        if kind not in {"create", "import"}:
            raise BackupError(ErrorCode.INVALID_REQUEST, "Некорректный вид staging")
        return self.root / "staging" / kind / operation_id / f"{backup_id}.tar.gz"

    @staticmethod
    def checksum_path(archive_path: Path) -> Path:
        return archive_path.with_name(archive_path.name + ".sha256")

    @staticmethod
    def archive_inventory_path(archive_path: Path) -> Path:
        """Return the canonical v2 sidecar name for one archive path."""
        return archive_path.with_name(archive_path.name + ".inventory.json")

    def _secure_entry_path(self, path: str | Path, field: str) -> Path:
        """Validate a leaf path without resolving or following the leaf itself."""
        absolute = Path(os.path.abspath(os.fspath(path)))
        try:
            parent = absolute.parent.resolve(strict=True)
            parent.relative_to(self.root)
        except (OSError, ValueError) as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                f"{field} находится вне безопасного storage namespace",
            ) from exc
        if parent != absolute.parent:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                f"{field} содержит symlink в parent path",
            )
        return parent / absolute.name

    @staticmethod
    def _open_secure_directory(path: Path, field: str) -> int:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(path, flags)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) & 0o077
            ):
                raise OSError("unsafe directory metadata")
            return descriptor
        except OSError as exc:
            try:
                os.close(descriptor)
            except (NameError, OSError):
                pass
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                f"Не удалось безопасно открыть {field}",
            ) from exc

    @staticmethod
    def _open_secure_regular(
        directory_fd: int,
        name: str,
        field: str,
        *,
        maximum: int | None = None,
        missing_ok: bool = False,
    ) -> tuple[int, os.stat_result] | None:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(name, flags, dir_fd=directory_fd)
        except FileNotFoundError:
            if missing_ok:
                return None
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                f"Не найден {field}",
            )
        except OSError as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                f"Не удалось безопасно открыть {field}",
            ) from exc
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) & 0o077
                or metadata.st_size < 0
                or (maximum is not None and metadata.st_size > maximum)
            ):
                raise OSError("unsafe regular-file metadata")
            return descriptor, metadata
        except OSError as exc:
            os.close(descriptor)
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                f"Некорректный безопасный файл {field}",
            ) from exc

    @staticmethod
    def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
        return (
            left.st_dev,
            left.st_ino,
            left.st_size,
            left.st_mtime_ns,
        ) == (
            right.st_dev,
            right.st_ino,
            right.st_size,
            right.st_mtime_ns,
        )

    def _read_v2_archive_inventory_file(
        self,
        inventory_path: Path,
        *,
        expected_source: dict,
        expected_archive: dict,
    ) -> dict:
        inventory_path = self._secure_entry_path(
            inventory_path,
            "archive inventory",
        )
        directory_fd = self._open_secure_directory(
            inventory_path.parent,
            "archive inventory directory",
        )
        descriptor = None
        try:
            opened = self._open_secure_regular(
                directory_fd,
                inventory_path.name,
                "archive inventory",
                maximum=MAX_ARCHIVE_INVENTORY_V2_BYTES,
            )
            if opened is None:  # pragma: no cover - missing_ok is false
                raise BackupError(
                    ErrorCode.STORAGE_BACKEND_ERROR,
                    "Archive inventory не найден",
                )
            descriptor, before = opened
            gate = (
                ARCHIVE_INVENTORY_HEAVY_OPERATION
                if before.st_size > HEAVY_ARCHIVE_INVENTORY_BYTES
                else nullcontext()
            )
            with gate:
                with os.fdopen(descriptor, "rb", closefd=True) as stream:
                    descriptor = None
                    payload = stream.read(MAX_ARCHIVE_INVENTORY_V2_BYTES + 1)
                    after = os.fstat(stream.fileno())
                if (
                    len(payload) > MAX_ARCHIVE_INVENTORY_V2_BYTES
                    or len(payload) != before.st_size
                    or not self._same_file_identity(before, after)
                ):
                    raise BackupError(
                        ErrorCode.ARCHIVE_INVALID,
                        "Archive inventory изменился во время чтения",
                    )
                value = json.loads(payload)
                return validate_archive_inventory(
                    value,
                    expected_source=expected_source,
                    expected_archive=expected_archive,
                )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackupError(
                ErrorCode.ARCHIVE_INVALID,
                "Archive inventory не является корректным JSON",
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(directory_fd)

    def _archive_inventory_file_identity(self, inventory_path: Path) -> tuple:
        """Return one no-follow identity suitable for the process-local cache."""
        inventory_path = self._secure_entry_path(
            inventory_path,
            "archive inventory",
        )
        directory_fd = self._open_secure_directory(
            inventory_path.parent,
            "archive inventory directory",
        )
        descriptor = None
        try:
            opened = self._open_secure_regular(
                directory_fd,
                inventory_path.name,
                "archive inventory",
                maximum=MAX_ARCHIVE_INVENTORY_V2_BYTES,
            )
            if opened is None:  # pragma: no cover - missing_ok is false
                raise BackupError(
                    ErrorCode.STORAGE_BACKEND_ERROR,
                    "Archive inventory не найден",
                )
            descriptor, metadata = opened
            return (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_size,
                metadata.st_mtime_ns,
            )
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(directory_fd)

    def _read_v2_archive_inventory_snapshot_file(
        self,
        inventory_path: Path,
        *,
        expected_source: dict,
        expected_archive: dict,
    ):
        """Load one validated query snapshot, sharing parses by safe file identity."""
        inventory_path = self._secure_entry_path(
            inventory_path,
            "archive inventory",
        )
        identity = self._archive_inventory_file_identity(inventory_path)
        binding_token = hashlib.sha256(
            json.dumps(
                [expected_source, expected_archive],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        cache_key = (
            "archive-inventory-base-v2",
            str(inventory_path),
            identity,
            binding_token,
        )

        def load():
            directory_fd = self._open_secure_directory(
                inventory_path.parent,
                "archive inventory directory",
            )
            descriptor = None
            try:
                opened = self._open_secure_regular(
                    directory_fd,
                    inventory_path.name,
                    "archive inventory",
                    maximum=MAX_ARCHIVE_INVENTORY_V2_BYTES,
                )
                if opened is None:  # pragma: no cover - missing_ok is false
                    raise BackupError(
                        ErrorCode.STORAGE_BACKEND_ERROR,
                        "Archive inventory не найден",
                    )
                descriptor, before = opened
                before_identity = (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                )
                if before_identity != identity:
                    raise BackupError(
                        ErrorCode.ARCHIVE_INVALID,
                        "Archive inventory изменился перед чтением",
                    )
                gate = (
                    ARCHIVE_INVENTORY_HEAVY_OPERATION
                    if before.st_size > HEAVY_ARCHIVE_INVENTORY_BYTES
                    else nullcontext()
                )
                with gate:
                    with os.fdopen(descriptor, "rb", closefd=True) as stream:
                        descriptor = None
                        payload = stream.read(MAX_ARCHIVE_INVENTORY_V2_BYTES + 1)
                        after = os.fstat(stream.fileno())
                    if (
                        len(payload) > MAX_ARCHIVE_INVENTORY_V2_BYTES
                        or len(payload) != before.st_size
                        or not self._same_file_identity(before, after)
                    ):
                        raise BackupError(
                            ErrorCode.ARCHIVE_INVALID,
                            "Archive inventory изменился во время чтения",
                        )
                    value = json.loads(payload)
                    return build_archive_inventory_snapshot(
                        value,
                        expected_source=expected_source,
                        expected_archive=expected_archive,
                    )
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BackupError(
                    ErrorCode.ARCHIVE_INVALID,
                    "Archive inventory не является корректным JSON",
                ) from exc
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                os.close(directory_fd)

        snapshot = archive_inventory_query_cache.get_or_load(cache_key, load)
        if self._archive_inventory_file_identity(inventory_path) != identity:
            archive_inventory_query_cache.invalidate(lambda key, _value: key == cache_key)
            raise BackupError(
                ErrorCode.ARCHIVE_INVALID,
                "Archive inventory изменился после чтения",
            )
        return snapshot

    def _managed_archive_binding_identity(
        self,
        archive_path: Path,
        checksum_path: Path,
        *,
        expected_source: dict,
        expected_archive: dict,
    ) -> tuple:
        archive_path = self._secure_entry_path(archive_path, "managed archive")
        checksum_path = self._secure_entry_path(checksum_path, "managed checksum")
        if checksum_path != self.checksum_path(archive_path):
            raise BackupError(
                ErrorCode.ARCHIVE_INVALID,
                "Checksum path не соответствует managed archive",
            )
        try:
            storage_key = archive_path.relative_to(self.root).as_posix()
        except ValueError as exc:  # pragma: no cover - protected by _secure_entry_path
            raise BackupError(
                ErrorCode.ARCHIVE_INVALID,
                "Managed archive находится вне storage root",
            ) from exc
        if (
            not isinstance(expected_source, dict)
            or expected_source.get("kind") != "managed"
            or expected_source.get("storage_key") != storage_key
            or not isinstance(expected_archive, dict)
        ):
            raise BackupError(
                ErrorCode.ARCHIVE_INVALID,
                "Source binding archive inventory не соответствует managed archive",
            )

        directory_fd = self._open_secure_directory(
            archive_path.parent,
            "managed archive directory",
        )
        archive_fd = None
        checksum_fd = None
        try:
            archive_opened = self._open_secure_regular(
                directory_fd,
                archive_path.name,
                "managed archive",
            )
            checksum_opened = self._open_secure_regular(
                directory_fd,
                checksum_path.name,
                "managed checksum",
                maximum=65,
            )
            if archive_opened is None or checksum_opened is None:  # pragma: no cover
                raise BackupError(
                    ErrorCode.STORAGE_BACKEND_ERROR,
                    "Managed artifact неполон",
                )
            archive_fd, archive_stat = archive_opened
            checksum_fd, checksum_stat = checksum_opened
            expected_bytes = expected_archive.get("bytes")
            expected_format = expected_archive.get("format")
            expected_digest = expected_archive.get("sha256")
            prefix = os.pread(archive_fd, 4, 0)
            # format описывает содержимое архива (tar.gz), а не контейнер:
            # B4VE (archive_crypto) — это зашифрованный паролем tar.gz, поэтому
            # его магия легитимно проходит как "tar.gz". Настоящее сцепление
            # артефакта с inventory делает sha256 + bytes ниже.
            if prefix[:4] == b"B4VE" or prefix[:2] == bytes.fromhex("1f8b"):
                actual_format = "tar.gz"
            else:
                actual_format = "tar"
            checksum_payload = os.read(checksum_fd, 66)
            expected_checksum_payload = (
                (expected_digest + "\n").encode("ascii")
                if isinstance(expected_digest, str)
                else b""
            )
            if (
                isinstance(expected_bytes, bool)
                or not isinstance(expected_bytes, int)
                or expected_bytes < 0
                or archive_stat.st_size != expected_bytes
                or expected_format not in {"tar", "tar.gz"}
                or actual_format != expected_format
                or checksum_payload != expected_checksum_payload
            ):
                raise BackupError(
                    ErrorCode.ARCHIVE_INVALID,
                    "Managed artifact не соответствует archive inventory binding",
                )
            current_archive = os.stat(
                archive_path.name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
            current_checksum = os.stat(
                checksum_path.name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
            if (
                not self._same_file_identity(archive_stat, current_archive)
                or not self._same_file_identity(checksum_stat, current_checksum)
            ):
                raise BackupError(
                    ErrorCode.ARCHIVE_INVALID,
                    "Managed artifact изменился во время проверки binding",
                )
            return (
                archive_stat.st_dev,
                archive_stat.st_ino,
                archive_stat.st_size,
                archive_stat.st_mtime_ns,
                checksum_stat.st_dev,
                checksum_stat.st_ino,
                checksum_stat.st_size,
                checksum_stat.st_mtime_ns,
            )
        except (UnicodeEncodeError, ValueError) as exc:
            raise BackupError(
                ErrorCode.ARCHIVE_INVALID,
                "Некорректный checksum archive inventory binding",
            ) from exc
        finally:
            if archive_fd is not None:
                os.close(archive_fd)
            if checksum_fd is not None:
                os.close(checksum_fd)
            os.close(directory_fd)

    def write_archive_inventory_staging(
        self,
        staging_archive: Path,
        inventory: dict,
    ) -> Path:
        """Write a new v2 sidecar next to a controlled staging archive."""
        staging_archive = self._secure_entry_path(
            staging_archive,
            "staging archive",
        )
        try:
            staging_archive.relative_to(self.root / "staging")
        except ValueError as exc:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Archive inventory staging находится вне staging namespace",
            ) from exc
        directory_fd = self._open_secure_directory(
            staging_archive.parent,
            "archive inventory staging directory",
        )
        os.close(directory_fd)
        inventory_path = self.archive_inventory_path(staging_archive)
        try:
            write_v2_archive_inventory(inventory_path, inventory)
            self._fsync_dir(inventory_path.parent)
            return inventory_path
        except BackupError:
            raise
        except OSError as exc:
            raise BackupError(
                ErrorCode.STAGING_IO_FAILED,
                "Не удалось записать archive inventory staging",
                retryable=True,
            ) from exc

    def read_managed_archive_inventory(
        self,
        archive_path: Path,
        checksum_path: Path,
        *,
        expected_source: dict,
        expected_archive: dict,
    ) -> dict | None:
        """Return a deeply validated v2 sidecar bound to the current artifact."""
        try:
            before = self._managed_archive_binding_identity(
                archive_path,
                checksum_path,
                expected_source=expected_source,
                expected_archive=expected_archive,
            )
            value = self._read_v2_archive_inventory_file(
                self.archive_inventory_path(archive_path),
                expected_source=expected_source,
                expected_archive=expected_archive,
            )
            after = self._managed_archive_binding_identity(
                archive_path,
                checksum_path,
                expected_source=expected_source,
                expected_archive=expected_archive,
            )
            return value if before == after else None
        except (BackupError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    def load_managed_archive_inventory_snapshot(
        self,
        archive_path: Path,
        checksum_path: Path,
        *,
        expected_source: dict,
        expected_archive: dict,
    ):
        """Return a cached query snapshot bound to the current managed artifact."""
        before = self._managed_archive_binding_identity(
            archive_path,
            checksum_path,
            expected_source=expected_source,
            expected_archive=expected_archive,
        )
        snapshot = self._read_v2_archive_inventory_snapshot_file(
            self.archive_inventory_path(archive_path),
            expected_source=expected_source,
            expected_archive=expected_archive,
        )
        after = self._managed_archive_binding_identity(
            archive_path,
            checksum_path,
            expected_source=expected_source,
            expected_archive=expected_archive,
        )
        if before != after:
            raise BackupError(
                ErrorCode.ARCHIVE_INVALID,
                "Managed artifact изменился во время чтения inventory",
                retryable=True,
            )
        return snapshot

    def install_managed_archive_inventory(
        self,
        staging_inventory: Path,
        archive_path: Path,
        checksum_path: Path,
        *,
        expected_source: dict,
        expected_archive: dict,
        replace_existing: bool = False,
    ) -> bool:
        """Install a staged v2 sidecar if the published artifact is still current."""
        if not isinstance(replace_existing, bool):
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Некорректный режим замены archive inventory",
            )
        staging_inventory = self._secure_entry_path(
            staging_inventory,
            "archive inventory staging",
        )
        try:
            staging_inventory.relative_to(self.root / "staging")
        except ValueError as exc:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Archive inventory staging находится вне staging namespace",
            ) from exc
        archive_path = self._secure_entry_path(archive_path, "managed archive")
        checksum_path = self._secure_entry_path(checksum_path, "managed checksum")
        inventory_path = self.archive_inventory_path(archive_path)
        self._read_v2_archive_inventory_file(
            staging_inventory,
            expected_source=expected_source,
            expected_archive=expected_archive,
        )

        destination_fd = self._open_secure_directory(
            inventory_path.parent,
            "managed archive directory",
        )
        source_fd = None
        installed_identity: tuple[int, int] | None = None
        try:
            fcntl.flock(destination_fd, fcntl.LOCK_EX)
            try:
                binding_before = self._managed_archive_binding_identity(
                    archive_path,
                    checksum_path,
                    expected_source=expected_source,
                    expected_archive=expected_archive,
                )
            except BackupError:
                return False

            try:
                existing = self._read_v2_archive_inventory_file(
                    inventory_path,
                    expected_source=expected_source,
                    expected_archive=expected_archive,
                )
            except BackupError:
                existing = None
            if existing is not None and not replace_existing:
                try:
                    binding_after = self._managed_archive_binding_identity(
                        archive_path,
                        checksum_path,
                        expected_source=expected_source,
                        expected_archive=expected_archive,
                    )
                except BackupError:
                    return False
                return binding_before == binding_after

            try:
                current = os.stat(
                    inventory_path.name,
                    dir_fd=destination_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                current = None
            if current is not None and (
                not stat.S_ISREG(current.st_mode)
                or current.st_uid != os.geteuid()
                or stat.S_IMODE(current.st_mode) & 0o077
            ):
                return False

            source_fd = self._open_secure_directory(
                staging_inventory.parent,
                "archive inventory staging directory",
            )
            staged_opened = self._open_secure_regular(
                source_fd,
                staging_inventory.name,
                "archive inventory staging",
                maximum=MAX_ARCHIVE_INVENTORY_V2_BYTES,
            )
            if staged_opened is None:  # pragma: no cover - missing_ok is false
                return False
            staged_descriptor, staged_stat = staged_opened
            os.close(staged_descriptor)
            installed_identity = (staged_stat.st_dev, staged_stat.st_ino)

            if current is None:
                try:
                    os.link(
                        staging_inventory.name,
                        inventory_path.name,
                        src_dir_fd=source_fd,
                        dst_dir_fd=destination_fd,
                        follow_symlinks=False,
                    )
                except FileExistsError:
                    return False
                os.unlink(staging_inventory.name, dir_fd=source_fd)
            else:
                os.replace(
                    staging_inventory.name,
                    inventory_path.name,
                    src_dir_fd=source_fd,
                    dst_dir_fd=destination_fd,
                )
            self._fsync_dir(staging_inventory.parent)
            self._fsync_dir(inventory_path.parent)

            installed = os.stat(
                inventory_path.name,
                dir_fd=destination_fd,
                follow_symlinks=False,
            )
            if (installed.st_dev, installed.st_ino) != installed_identity:
                return False
            try:
                binding_after = self._managed_archive_binding_identity(
                    archive_path,
                    checksum_path,
                    expected_source=expected_source,
                    expected_archive=expected_archive,
                )
            except BackupError:
                binding_after = None
            if binding_after != binding_before:
                current_installed = os.stat(
                    inventory_path.name,
                    dir_fd=destination_fd,
                    follow_symlinks=False,
                )
                if (
                    current_installed.st_dev,
                    current_installed.st_ino,
                ) == installed_identity:
                    os.unlink(inventory_path.name, dir_fd=destination_fd)
                    self._fsync_dir(inventory_path.parent)
                archive_inventory_query_cache.invalidate()
                return False
            archive_inventory_query_cache.invalidate()
            return True
        except BackupError:
            raise
        except OSError as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Не удалось установить archive inventory",
            ) from exc
        finally:
            if source_fd is not None:
                os.close(source_fd)
            try:
                fcntl.flock(destination_fd, fcntl.LOCK_UN)
            finally:
                os.close(destination_fd)

    def calculate_checksum(self, archive_path: Path, *, chunk_size: int = 1024 * 1024) -> str:
        digest = hashlib.sha256()
        try:
            with archive_path.open("rb") as stream:
                while chunk := stream.read(chunk_size):
                    digest.update(chunk)
        except OSError as exc:
            raise BackupError(ErrorCode.STAGING_IO_FAILED, "Не удалось прочитать staging archive", retryable=True) from exc
        return digest.hexdigest()

    def write_checksum(self, archive_path: Path, checksum: str) -> Path:
        if len(checksum) != 64 or any(ch not in "0123456789abcdef" for ch in checksum):
            raise BackupError(ErrorCode.INVALID_REQUEST, "Некорректный SHA-256")
        path = self.checksum_path(archive_path)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as stream:
                stream.write(checksum + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._fsync_dir(path.parent)
            return path
        except OSError as exc:
            raise BackupError(ErrorCode.STAGING_IO_FAILED, "Не удалось записать checksum", retryable=True) from exc

    def _final_dir(self, backup_type: str, server_id: str | None) -> Path:
        if backup_type == "bot4vps":
            return self.root / "bot4vps"
        if backup_type == "server" and server_id:
            server_id = self._id(server_id, "server_id")
            path = self.root / "servers" / server_id
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._chmod(path, 0o700)
            return path
        raise BackupError(ErrorCode.INVALID_REQUEST, "Для server backup требуется server_id")

    def create_import_bundle_staging(
        self,
        operation_id: str,
        entry_key: str,
        filename: str,
    ) -> dict[str, Path]:
        """Create an unpublished self-contained import bundle layout."""
        from .validation import validate_archive_filename

        operation_id = self._id(operation_id, "operation_id")
        entry_key = self._id(entry_key, "entry_key")
        filename = validate_archive_filename(filename)
        staging = self.create_staging(operation_id, "import")
        bundle = staging / "bundle"
        content = bundle / "content"
        control = bundle / "control"
        try:
            content.mkdir(parents=True, mode=0o700)
            control.mkdir(mode=0o700)
            self._chmod(bundle, 0o700)
            self._chmod(content, 0o700)
            self._chmod(control, 0o700)
        except OSError as exc:
            raise BackupError(
                ErrorCode.STAGING_IO_FAILED,
                "Не удалось создать import bundle staging",
                retryable=True,
            ) from exc
        return {
            "entry_key": entry_key,
            "staging": staging,
            "bundle": bundle,
            "content": content,
            "control": control,
            "archive": content / filename,
            "checksum": control / "sha256",
            "publication": control / "publication.json",
            "inventory": control / "archive-inventory.json",
        }

    def _import_scope_dir(
        self,
        *,
        server_id: str | None,
        create: bool,
    ) -> Path:
        if server_id is None:
            path = self.root / "imports" / "bot4vps"
        else:
            path = self.root / "imports" / "servers" / self._id(server_id, "server_id")
        if create:
            try:
                path.mkdir(parents=True, exist_ok=True, mode=0o700)
                self._chmod(path, 0o700)
            except OSError as exc:
                raise BackupError(
                    ErrorCode.STORAGE_BACKEND_ERROR,
                    "Не удалось подготовить import namespace",
                ) from exc
        return path

    def import_bundle_dir(
        self,
        entry_key: str,
        *,
        server_id: str | None = None,
        create_scope: bool = False,
    ) -> Path:
        entry_key = self._id(entry_key, "entry_key")
        return self._import_scope_dir(
            server_id=server_id,
            create=create_scope,
        ) / entry_key

    @staticmethod
    def _write_json_file(path: Path, value: dict) -> None:
        try:
            payload = json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ).encode("utf-8") + b"\n"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise BackupError(
                ErrorCode.STAGING_IO_FAILED,
                "Не удалось записать publication metadata",
                retryable=True,
            ) from exc

    def write_import_bundle_control(
        self,
        bundle_paths: dict[str, Path],
        publication: dict,
        checksum: str,
        inventory: dict,
    ) -> None:
        checksum_path = bundle_paths["checksum"]
        publication_path = bundle_paths["publication"]
        inventory_path = bundle_paths["inventory"]
        if len(checksum) != 64 or any(ch not in "0123456789abcdef" for ch in checksum):
            raise BackupError(ErrorCode.INVALID_REQUEST, "Некорректный SHA-256")
        try:
            fd = os.open(checksum_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as stream:
                stream.write(checksum + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise BackupError(
                ErrorCode.STAGING_IO_FAILED,
                "Не удалось записать checksum",
                retryable=True,
            ) from exc
        self._write_json_file(publication_path, publication)
        if isinstance(inventory, dict) and set(inventory) == {
            "header",
            "manifest",
            "members",
            "view",
            "policy_projection",
        }:
            write_v2_archive_inventory(inventory_path, inventory)
        else:
            self._write_json_file(inventory_path, inventory)
        self._fsync_dir(bundle_paths["control"])
        self._fsync_dir(bundle_paths["content"])
        self._fsync_dir(bundle_paths["bundle"])

    @staticmethod
    def _read_import_checksum(path: Path) -> str:
        try:
            value = path.read_text(encoding="ascii")
        except (OSError, UnicodeDecodeError) as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Повреждён checksum import bundle",
            ) from exc
        checksum = value[:-1] if value.endswith("\n") else ""
        if (
            len(value) != 65
            or len(checksum) != 64
            or any(ch not in "0123456789abcdef" for ch in checksum)
        ):
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Повреждён checksum import bundle",
            )
        return checksum

    @staticmethod
    def _validate_legacy_import_inventory(
        value: object,
        *,
        publication: dict,
        archive_size: int,
        archive_format: str,
        checksum: str,
    ) -> dict:
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "archive",
            "manifest",
            "members",
        }:
            raise BackupError(ErrorCode.ARCHIVE_INVALID, "Повреждена schema archive inventory")
        schema_version = value.get("schema_version")
        if (
            isinstance(schema_version, bool)
            or schema_version != LEGACY_ARCHIVE_INVENTORY_SCHEMA_VERSION
        ):
            raise BackupError(ErrorCode.ARCHIVE_INVALID, "Версия archive inventory не поддерживается")
        archive = value.get("archive")
        if not isinstance(archive, dict) or set(archive) != {"sha256", "bytes", "format"}:
            raise BackupError(ErrorCode.ARCHIVE_INVALID, "Повреждена binding archive inventory")
        inventory_checksum = archive.get("sha256")
        if (
            not isinstance(inventory_checksum, str)
            or len(inventory_checksum) != 64
            or any(ch not in "0123456789abcdef" for ch in inventory_checksum)
        ):
            raise BackupError(ErrorCode.ARCHIVE_INVALID, "Некорректный SHA-256 archive inventory")
        size = archive.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise BackupError(ErrorCode.ARCHIVE_INVALID, "Некорректный размер archive inventory")
        if archive.get("format") not in {"tar", "tar.gz"}:
            raise BackupError(ErrorCode.ARCHIVE_INVALID, "Некорректный format archive inventory")
        manifest = value.get("manifest")
        if manifest is not None and not isinstance(manifest, dict):
            raise BackupError(ErrorCode.ARCHIVE_INVALID, "Некорректный manifest archive inventory")
        members = validate_archive_inventory_members(value.get("members"))

        publication_checksum = publication.get("checksum")
        publication_inspection = publication.get("inspection")
        expected_manifest_status = "present" if manifest is not None else "absent"
        if (
            not isinstance(publication_checksum, dict)
            or set(publication_checksum) != {"algorithm", "value"}
            or publication_checksum.get("algorithm") != "sha256"
            or inventory_checksum != checksum
            or inventory_checksum != publication_checksum.get("value")
            or size != archive_size
            or size != publication.get("bytes")
            or archive.get("format") != archive_format
            or archive.get("format") != publication.get("format")
            or not isinstance(publication_inspection, dict)
            or publication_inspection.get("member_count") != len(members)
            or publication_inspection.get("manifest_status") != expected_manifest_status
        ):
            raise BackupError(ErrorCode.ARCHIVE_INVALID, "Archive inventory не соответствует archive binding")
        return {
            "schema_version": LEGACY_ARCHIVE_INVENTORY_SCHEMA_VERSION,
            "archive": dict(archive),
            "manifest": dict(manifest) if isinstance(manifest, dict) else None,
            "members": members,
        }

    @staticmethod
    def _archive_format(path: Path) -> str:
        try:
            with path.open("rb") as stream:
                # B4VE — зашифрованный паролем tar.gz (archive_crypto):
                # format описывает содержимое, а не контейнер.
                prefix = stream.read(4)
                if prefix[:4] == b"B4VE" or prefix[:2] == bytes.fromhex("1f8b"):
                    return "tar.gz"
                return "tar"
        except OSError as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Не удалось проверить format import archive",
            ) from exc

    @staticmethod
    def _import_inventory_path(resolved: dict) -> Path:
        bundle = Path(resolved["bundle"])
        control = bundle / "control"
        inventory_path = Path(resolved["inventory_path"])
        if (
            bundle.is_symlink()
            or not bundle.is_dir()
            or control.is_symlink()
            or not control.is_dir()
            or inventory_path != control / "archive-inventory.json"
        ):
            raise BackupError(
                ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE,
                "Import bundle не содержит безопасный control directory",
                retryable=True,
            )
        return inventory_path

    @staticmethod
    def _import_inventory_bindings(resolved: dict) -> tuple[dict, dict]:
        publication = resolved.get("publication")
        if not isinstance(publication, dict):
            raise BackupError(
                ErrorCode.ARCHIVE_INVALID,
                "Import publication не содержит archive inventory binding",
            )
        checksum = publication.get("checksum")
        if (
            not isinstance(checksum, dict)
            or set(checksum) != {"algorithm", "value"}
            or checksum.get("algorithm") != "sha256"
        ):
            raise BackupError(
                ErrorCode.ARCHIVE_INVALID,
                "Import publication не содержит корректный checksum binding",
            )
        source = {
            "kind": "imported",
            "entry_key": resolved.get("entry_key"),
            "destination": publication.get("destination"),
        }
        archive = {
            "sha256": checksum.get("value"),
            "bytes": publication.get("bytes"),
            "format": publication.get("format"),
        }
        return source, archive

    def import_inventory_bindings(self, resolved: dict) -> tuple[dict, dict]:
        """Return detached v2 bindings for one resolved import."""
        source, archive = self._import_inventory_bindings(resolved)
        detached_source = dict(source)
        if isinstance(source.get("destination"), dict):
            detached_source["destination"] = dict(source["destination"])
        return detached_source, dict(archive)

    def _import_archive_binding_identity(
        self,
        resolved: dict,
        *,
        expected_source: dict,
        expected_archive: dict,
    ) -> tuple:
        archive_path = self._secure_entry_path(
            Path(resolved["archive"]),
            "import archive",
        )
        checksum_path = self._secure_entry_path(
            Path(resolved["checksum"]),
            "import checksum",
        )
        current_source, current_archive = self._import_inventory_bindings(resolved)
        if current_source != expected_source or current_archive != expected_archive:
            raise BackupError(
                ErrorCode.ARCHIVE_INVALID,
                "Import publication изменилась во время проверки inventory binding",
            )

        archive_directory_fd = self._open_secure_directory(
            archive_path.parent,
            "import content directory",
        )
        checksum_directory_fd = self._open_secure_directory(
            checksum_path.parent,
            "import control directory",
        )
        archive_fd = None
        checksum_fd = None
        try:
            archive_opened = self._open_secure_regular(
                archive_directory_fd,
                archive_path.name,
                "import archive",
            )
            checksum_opened = self._open_secure_regular(
                checksum_directory_fd,
                checksum_path.name,
                "import checksum",
                maximum=65,
            )
            if archive_opened is None or checksum_opened is None:  # pragma: no cover
                raise BackupError(
                    ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE,
                    "Import bundle неполон",
                )
            archive_fd, archive_stat = archive_opened
            checksum_fd, checksum_stat = checksum_opened
            expected_bytes = expected_archive.get("bytes")
            expected_format = expected_archive.get("format")
            expected_digest = expected_archive.get("sha256")
            # B4VE — зашифрованный паролем tar.gz: format описывает содержимое.
            import_prefix = os.pread(archive_fd, 4, 0)
            if (
                import_prefix[:4] == b"B4VE"
                or import_prefix[:2] == bytes.fromhex("1f8b")
            ):
                actual_format = "tar.gz"
            else:
                actual_format = "tar"
            expected_checksum_payload = (
                (expected_digest + "\n").encode("ascii")
                if isinstance(expected_digest, str)
                else b""
            )
            checksum_payload = os.read(checksum_fd, 66)
            if (
                isinstance(expected_bytes, bool)
                or not isinstance(expected_bytes, int)
                or expected_bytes < 0
                or archive_stat.st_size != expected_bytes
                or expected_format not in {"tar", "tar.gz"}
                or actual_format != expected_format
                or checksum_payload != expected_checksum_payload
            ):
                raise BackupError(
                    ErrorCode.ARCHIVE_INVALID,
                    "Import artifact не соответствует archive inventory binding",
                )
            current_archive_stat = os.stat(
                archive_path.name,
                dir_fd=archive_directory_fd,
                follow_symlinks=False,
            )
            current_checksum_stat = os.stat(
                checksum_path.name,
                dir_fd=checksum_directory_fd,
                follow_symlinks=False,
            )
            if (
                not self._same_file_identity(archive_stat, current_archive_stat)
                or not self._same_file_identity(checksum_stat, current_checksum_stat)
            ):
                raise BackupError(
                    ErrorCode.ARCHIVE_INVALID,
                    "Import artifact изменился во время проверки inventory binding",
                )
            return (
                archive_stat.st_dev,
                archive_stat.st_ino,
                archive_stat.st_size,
                archive_stat.st_mtime_ns,
                checksum_stat.st_dev,
                checksum_stat.st_ino,
                checksum_stat.st_size,
                checksum_stat.st_mtime_ns,
            )
        except (UnicodeEncodeError, ValueError) as exc:
            raise BackupError(
                ErrorCode.ARCHIVE_INVALID,
                "Некорректный checksum import inventory binding",
            ) from exc
        finally:
            if archive_fd is not None:
                os.close(archive_fd)
            if checksum_fd is not None:
                os.close(checksum_fd)
            os.close(archive_directory_fd)
            os.close(checksum_directory_fd)

    def read_import_archive_inventory_header(self, resolved: dict) -> dict | None:
        """Read one bound v2 header without loading the inventory body."""
        inventory_path = self._secure_entry_path(
            self._import_inventory_path(resolved),
            "import archive inventory",
        )
        expected_source, expected_archive = self._import_inventory_bindings(resolved)
        before_artifact = self._import_archive_binding_identity(
            resolved,
            expected_source=expected_source,
            expected_archive=expected_archive,
        )
        directory_fd = self._open_secure_directory(
            inventory_path.parent,
            "import inventory directory",
        )
        descriptor = None
        try:
            opened = self._open_secure_regular(
                directory_fd,
                inventory_path.name,
                "import archive inventory",
                maximum=MAX_ARCHIVE_INVENTORY_V2_BYTES,
                missing_ok=True,
            )
            if opened is None:
                return None
            descriptor, before_inventory = opened
            payload = os.read(descriptor, MAX_ARCHIVE_INVENTORY_HEADER_BYTES)
            after_inventory = os.fstat(descriptor)
            try:
                current_inventory = os.stat(
                    inventory_path.name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise BackupError(
                    ErrorCode.ARCHIVE_INVALID,
                    "Archive inventory изменился во время чтения header",
                ) from exc
            if (
                not self._same_file_identity(before_inventory, after_inventory)
                or not self._same_file_identity(before_inventory, current_inventory)
            ):
                raise BackupError(
                    ErrorCode.ARCHIVE_INVALID,
                    "Archive inventory изменился во время чтения header",
                )
        except OSError as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Не удалось прочитать header archive inventory",
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(directory_fd)

        after_artifact = self._import_archive_binding_identity(
            resolved,
            expected_source=expected_source,
            expected_archive=expected_archive,
        )
        if before_artifact != after_artifact:
            raise BackupError(
                ErrorCode.ARCHIVE_INVALID,
                "Import bundle изменился во время чтения inventory header",
                retryable=True,
            )
        header = parse_archive_inventory_header_prefix(payload)
        if (
            header.get("source") != expected_source
            or header.get("archive") != expected_archive
        ):
            raise BackupError(
                ErrorCode.ARCHIVE_INVALID,
                "Header archive inventory не соответствует import binding",
            )
        return header

    def read_import_archive_inventory(self, resolved: dict) -> dict | None:
        """Return a deeply validated v2 sidecar bound to the import artifact."""
        try:
            inventory_path = self._import_inventory_path(resolved)
            expected_source, expected_archive = self._import_inventory_bindings(resolved)
            before = self._import_archive_binding_identity(
                resolved,
                expected_source=expected_source,
                expected_archive=expected_archive,
            )
            value = self._read_v2_archive_inventory_file(
                inventory_path,
                expected_source=expected_source,
                expected_archive=expected_archive,
            )
            after = self._import_archive_binding_identity(
                resolved,
                expected_source=expected_source,
                expected_archive=expected_archive,
            )
            return value if before == after else None
        except (BackupError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    def load_import_archive_inventory_snapshot(self, resolved: dict):
        """Return a cached query snapshot bound to the current import bundle."""
        inventory_path = self._import_inventory_path(resolved)
        expected_source, expected_archive = self._import_inventory_bindings(resolved)
        before = self._import_archive_binding_identity(
            resolved,
            expected_source=expected_source,
            expected_archive=expected_archive,
        )
        snapshot = self._read_v2_archive_inventory_snapshot_file(
            inventory_path,
            expected_source=expected_source,
            expected_archive=expected_archive,
        )
        after = self._import_archive_binding_identity(
            resolved,
            expected_source=expected_source,
            expected_archive=expected_archive,
        )
        if before != after:
            raise BackupError(
                ErrorCode.ARCHIVE_INVALID,
                "Import bundle изменился во время чтения inventory",
                retryable=True,
            )
        return snapshot

    def read_legacy_import_archive_inventory(self, resolved: dict) -> dict | None:
        """Read strict v1 metadata for compatibility; it is never lazy-ready."""
        descriptor = None
        directory_fd = None
        try:
            inventory_path = self._secure_entry_path(
                self._import_inventory_path(resolved),
                "legacy import archive inventory",
            )
            expected_source, expected_archive = self._import_inventory_bindings(resolved)
            before_artifact = self._import_archive_binding_identity(
                resolved,
                expected_source=expected_source,
                expected_archive=expected_archive,
            )
            directory_fd = self._open_secure_directory(
                inventory_path.parent,
                "legacy import inventory directory",
            )
            opened = self._open_secure_regular(
                directory_fd,
                inventory_path.name,
                "legacy import archive inventory",
                maximum=MAX_ARCHIVE_INVENTORY_LEGACY_BYTES,
            )
            if opened is None:  # pragma: no cover - missing_ok is false
                return None
            descriptor, before_inventory = opened
            with os.fdopen(descriptor, "rb", closefd=True) as stream:
                descriptor = None
                payload = stream.read(MAX_ARCHIVE_INVENTORY_LEGACY_BYTES + 1)
                after_inventory = os.fstat(stream.fileno())
            if (
                len(payload) > MAX_ARCHIVE_INVENTORY_LEGACY_BYTES
                or len(payload) != before_inventory.st_size
                or not self._same_file_identity(before_inventory, after_inventory)
            ):
                return None
            value = json.loads(payload)
            validated = self._validate_legacy_import_inventory(
                value,
                publication=resolved["publication"],
                archive_size=expected_archive["bytes"],
                archive_format=expected_archive["format"],
                checksum=expected_archive["sha256"],
            )
            after_artifact = self._import_archive_binding_identity(
                resolved,
                expected_source=expected_source,
                expected_archive=expected_archive,
            )
            return validated if before_artifact == after_artifact else None
        except (BackupError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if directory_fd is not None:
                os.close(directory_fd)

    def write_import_archive_inventory(
        self,
        resolved: dict,
        inventory: dict,
        *,
        verify_archive_checksum: bool = True,
        replace_existing: bool = False,
    ) -> bool:
        """Atomically install or repair a bound v2 cache without following links.

        Disabling the checksum pass and replacing a valid sidecar are reserved for
        the inventory worker while it holds the import publish lock. Restore never
        treats this sidecar as physical archive authority.
        """
        if not isinstance(replace_existing, bool):
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Некорректный режим замены archive inventory",
            )
        inventory_path = self._import_inventory_path(resolved)
        control = inventory_path.parent
        archive = Path(resolved["archive"])
        expected_source, expected_archive = self._import_inventory_bindings(resolved)
        validate_archive_inventory(
            inventory,
            expected_source=expected_source,
            expected_archive=expected_archive,
        )
        try:
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_flags |= getattr(os, "O_NOFOLLOW", 0)
            directory_fd = os.open(control, directory_flags)
        except OSError as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Не удалось заблокировать control directory import bundle",
            ) from exc

        temporary_path: Path | None = None
        try:
            fcntl.flock(directory_fd, fcntl.LOCK_EX)
            # A concurrent repair may already have installed a valid v2 sidecar.
            if (
                not replace_existing
                and self.read_import_archive_inventory(resolved) is not None
            ):
                return True
            if inventory_path.is_symlink():
                return False
            if inventory_path.exists() and not inventory_path.is_file():
                return False

            before = self._import_archive_binding_identity(
                resolved,
                expected_source=expected_source,
                expected_archive=expected_archive,
            )
            if (
                verify_archive_checksum
                and self.calculate_checksum(archive) != expected_archive["sha256"]
            ):
                raise BackupError(
                    ErrorCode.CHECKSUM_MISMATCH,
                    "Checksum import archive не соответствует publication",
                )
            after = self._import_archive_binding_identity(
                resolved,
                expected_source=expected_source,
                expected_archive=expected_archive,
            )
            if before != after:
                return False

            temporary_path = control / f".archive-inventory-{uuid4().hex}.tmp"
            write_v2_archive_inventory(temporary_path, inventory)
            if inventory_path.exists():
                # Only an ordinary invalid cache reaches this branch. os.replace
                # swaps directory entries and never follows the replaced path.
                if inventory_path.is_symlink() or not inventory_path.is_file():
                    return False
                os.replace(temporary_path, inventory_path)
                temporary_path = None
            else:
                # link() gives the cache its final name without replacing a path
                # concurrently created outside the cooperative directory lock.
                try:
                    os.link(
                        temporary_path,
                        inventory_path,
                        follow_symlinks=False,
                    )
                except FileExistsError:
                    return self.read_import_archive_inventory(resolved) is not None
                temporary_path.unlink()
                temporary_path = None
            self._fsync_dir(control)
            archive_inventory_query_cache.invalidate()
            return True
        except BackupError:
            raise
        except OSError as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Не удалось записать archive inventory",
            ) from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                fcntl.flock(directory_fd, fcntl.LOCK_UN)
            finally:
                os.close(directory_fd)

    def publish_import_bundle(
        self,
        bundle_paths: dict[str, Path],
        *,
        entry_key: str,
        server_id: str | None = None,
    ) -> Path:
        entry_key = self._id(entry_key, "entry_key")
        bundle = self._require_within(
            bundle_paths["bundle"],
            self.root / "staging" / "import",
            "import bundle staging",
        )
        required = (
            bundle_paths["archive"],
            bundle_paths["checksum"],
            bundle_paths["publication"],
            bundle_paths["inventory"],
        )
        if not all(path.is_file() and not path.is_symlink() for path in required):
            raise BackupError(
                ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE,
                "Import bundle неполон",
                retryable=True,
            )
        final = self.import_bundle_dir(
            entry_key,
            server_id=server_id,
            create_scope=True,
        )
        if final.exists():
            raise BackupError(
                ErrorCode.ARTIFACT_ALREADY_EXISTS,
                "Import bundle уже существует",
            )
        try:
            os.replace(bundle, final)
            self._fsync_dir(final.parent)
            return final
        except OSError as exc:
            raise BackupError(
                ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE,
                "Не удалось атомарно опубликовать import bundle",
                retryable=True,
            ) from exc

    @staticmethod
    def _normalize_import_origin(value: object) -> dict | None:
        if not isinstance(value, dict) or set(value) != {"created_at", "utc_offset"}:
            return None
        created_at = value.get("created_at")
        try:
            parse_utc_timestamp(created_at)
            utc_offset = normalize_utc_offset(value.get("utc_offset"))
        except (BackupError, TypeError, ValueError):
            return None
        return {
            "created_at": created_at,
            "utc_offset": utc_offset,
        }

    @staticmethod
    def _normalize_import_restore(value: object) -> dict | None:
        if not isinstance(value, dict) or set(value) != {"requires_target_root"}:
            return None
        requires_target_root = value.get("requires_target_root")
        if not isinstance(requires_target_root, bool):
            return None
        return {"requires_target_root": requires_target_root}

    def _read_import_publication(self, bundle: Path) -> dict:
        publication_path = bundle / "control" / "publication.json"
        try:
            with publication_path.open("r", encoding="utf-8") as stream:
                value = json.load(stream)
        except FileNotFoundError as exc:
            raise BackupError(
                ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE,
                "Import bundle не содержит publication.json",
            ) from exc
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Повреждён publication.json import bundle",
            ) from exc
        if not isinstance(value, dict):
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Повреждён publication.json import bundle",
            )
        return value

    def resolve_import_bundle(
        self,
        entry_key: str,
        *,
        server_id: str | None = None,
    ) -> dict:
        entry_key = self._id(entry_key, "entry_key")
        bundle = self.import_bundle_dir(entry_key, server_id=server_id)
        if not bundle.is_dir() or bundle.is_symlink():
            raise BackupError(ErrorCode.ARTIFACT_NOT_FOUND, "Импортированный архив не найден")
        control = bundle / "control"
        if control.is_symlink() or not control.is_dir():
            raise BackupError(
                ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE,
                "Import bundle не содержит безопасный control directory",
                retryable=True,
            )
        control = self._require_within(control, bundle, "import control directory")
        publication = self._read_import_publication(bundle)
        schema_version = publication.get("schema_version")
        if schema_version not in {1, 2} or publication.get("entry_key") != entry_key:
            raise BackupError(ErrorCode.STORAGE_BACKEND_ERROR, "Повреждена metadata import bundle")
        destination = publication.get("destination")
        expected_destination = (
            {"scope": "server", "server_id": server_id}
            if server_id is not None
            else {"scope": "bot4vps"}
        )
        if destination != expected_destination:
            raise BackupError(ErrorCode.STORAGE_BACKEND_ERROR, "Import bundle находится не в своём namespace")

        migration_required = schema_version != 2 or "display_name" in publication
        filename_candidates = (
            publication.get("display_name") if schema_version == 1 else None,
            publication.get("filename"),
        )
        filename = None
        for candidate in filename_candidates:
            try:
                filename = validate_archive_filename(
                    candidate,
                    error_code=ErrorCode.STORAGE_BACKEND_ERROR,
                )
                break
            except BackupError:
                continue
        if filename is None:
            raise BackupError(ErrorCode.STORAGE_BACKEND_ERROR, "Некорректное имя import bundle")
        publication = dict(publication)
        publication.pop("display_name", None)
        publication["schema_version"] = 2
        publication["filename"] = filename
        if "origin" in publication:
            origin = self._normalize_import_origin(publication.get("origin"))
            if origin is None:
                publication.pop("origin", None)
            else:
                publication["origin"] = origin
        if "restore" in publication:
            restore = self._normalize_import_restore(publication.get("restore"))
            if restore is None:
                publication.pop("restore", None)
            else:
                publication["restore"] = restore

        content = bundle / "content"
        if content.is_symlink() or not content.is_dir():
            raise BackupError(
                ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE,
                "Import bundle не содержит безопасный content directory",
                retryable=True,
            )
        try:
            content_entries = list(content.iterdir())
        except OSError as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Не удалось прочитать content import bundle",
            ) from exc
        archive_candidates = [
            path for path in content_entries
            if not path.is_symlink() and path.is_file()
        ]
        if len(content_entries) != 1 or len(archive_candidates) != 1:
            raise BackupError(
                ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE,
                "Import bundle должен содержать ровно один archive file",
                retryable=True,
            )
        archive = archive_candidates[0]
        checksum = control / "sha256"
        publication_path = control / "publication.json"
        inventory_path = control / "archive-inventory.json"
        for path in (archive, checksum, publication_path):
            if path.is_symlink():
                raise BackupError(
                    ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE,
                    "Import bundle содержит symlink вместо файла",
                    retryable=True,
                )
            resolved = self._require_within(path, bundle, "import bundle path")
            if not resolved.is_file():
                raise BackupError(
                    ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE,
                    "Import bundle неполон",
                    retryable=True,
                )
        return {
            "entry_key": entry_key,
            "bundle": bundle,
            "archive": archive,
            "checksum": checksum,
            "inventory_path": inventory_path,
            "publication_path": publication_path,
            "publication": publication,
            "publication_migration_required": migration_required,
        }

    def iter_import_bundle_refs(self) -> list[tuple[str | None, str]]:
        """Return valid destination/entry identities for published import bundles."""
        scopes: list[tuple[str | None, Path]] = [
            (None, self.root / "imports" / "bot4vps"),
        ]
        servers_root = self.root / "imports" / "servers"
        try:
            server_scopes = list(servers_root.iterdir()) if servers_root.is_dir() else []
        except OSError as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Не удалось прочитать import namespaces",
            ) from exc
        for scope in server_scopes:
            if scope.is_symlink() or not scope.is_dir():
                continue
            try:
                server_id = self._id(scope.name, "server_id")
            except BackupError:
                continue
            scopes.append((server_id, scope))

        refs: list[tuple[str | None, str]] = []
        for server_id, scope in scopes:
            try:
                bundles = list(scope.iterdir()) if scope.is_dir() else []
            except OSError as exc:
                raise BackupError(
                    ErrorCode.STORAGE_BACKEND_ERROR,
                    "Не удалось прочитать import namespace",
                ) from exc
            for bundle in bundles:
                if bundle.is_symlink() or not bundle.is_dir():
                    continue
                try:
                    entry_key = self._id(bundle.name, "entry_key")
                except BackupError:
                    continue
                refs.append((server_id, entry_key))
        return refs

    def update_import_filename(
        self,
        publication_path: Path,
        filename: str,
    ) -> dict:
        """Atomically update only the canonical visible import filename."""
        filename = validate_archive_filename(filename)
        publication_path = Path(publication_path)
        if not publication_path.is_file() or publication_path.is_symlink():
            raise BackupError(ErrorCode.ARTIFACT_NOT_FOUND, "Импортированный архив не найден")
        try:
            with publication_path.open("r", encoding="utf-8") as stream:
                publication = json.load(stream)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackupError(ErrorCode.STORAGE_BACKEND_ERROR, "Повреждён publication.json import bundle") from exc
        if not isinstance(publication, dict):
            raise BackupError(ErrorCode.STORAGE_BACKEND_ERROR, "Повреждён publication.json import bundle")
        updated = dict(publication)
        updated.pop("display_name", None)
        updated["schema_version"] = 2
        updated["filename"] = filename
        atomic_write_json(publication_path, updated)
        self._fsync_dir(publication_path.parent)
        return updated

    def list_import_bundles(self, *, server_id: str | None = None) -> list[dict]:
        scope = self._import_scope_dir(server_id=server_id, create=False)
        if not scope.exists():
            return []
        records: list[dict] = []
        try:
            entries = sorted(scope.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            raise BackupError(
                ErrorCode.STORAGE_BACKEND_ERROR,
                "Не удалось прочитать import namespace",
            ) from exc
        for bundle in entries:
            if not bundle.is_dir() or bundle.is_symlink():
                continue
            try:
                records.append(
                    self.resolve_import_bundle(bundle.name, server_id=server_id)["publication"]
                )
            except BackupError:
                # Incomplete/corrupt bundles are never advertised as published.
                continue
        return sorted(
            records,
            key=lambda item: (str(item.get("imported_at") or ""), str(item.get("entry_key") or "")),
            reverse=True,
        )

    def delete_import_bundle(
        self,
        entry_key: str,
        *,
        server_id: str | None = None,
    ) -> None:
        resolved = self.resolve_import_bundle(entry_key, server_id=server_id)
        bundle = resolved["bundle"]
        trash = self.root / "staging" / "import" / f"delete-{uuid4().hex}"
        try:
            os.replace(bundle, trash)
            self._fsync_dir(bundle.parent)
            shutil.rmtree(trash)
            self._fsync_dir(trash.parent)
        except OSError as exc:
            raise BackupError(
                ErrorCode.RETENTION_DELETE_FAILED,
                "Не удалось удалить import bundle",
                retryable=True,
            ) from exc

    def final_paths(self, backup_id: str, backup_type: str, server_id: str | None = None) -> tuple[Path, Path]:
        backup_id = self._id(backup_id, "backup_id")
        archive = self._final_dir(backup_type, server_id) / f"{backup_id}.tar.gz"
        return archive, self.checksum_path(archive)

    def canonical_keys(
        self,
        backup_id: str,
        backup_type: str,
        server_id: str | None = None,
    ) -> tuple[str, str]:
        """Return the only storage keys valid for an artifact identity."""
        archive, checksum = self.final_paths(backup_id, backup_type, server_id)
        return self.relative_key(archive), self.relative_key(checksum)

    def _require_within(self, path: Path, parent: Path, field: str) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(parent.resolve())
        except ValueError as exc:
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                f"{field} находится вне разрешённого storage namespace",
            ) from exc
        return resolved

    def publish_pair(
        self,
        staging_archive: Path,
        staging_checksum: Path,
        *,
        backup_id: str,
        backup_type: str,
        server_id: str | None = None,
    ) -> tuple[Path, Path]:
        staging_archive = self._require_within(
            staging_archive,
            self.root / "staging",
            "staging archive",
        )
        staging_checksum = self._require_within(
            staging_checksum,
            self.root / "staging",
            "staging checksum",
        )
        if staging_checksum != self.checksum_path(staging_archive):
            raise BackupError(
                ErrorCode.INVALID_REQUEST,
                "Checksum path не соответствует staging archive",
            )
        final_archive, final_checksum = self.final_paths(backup_id, backup_type, server_id)
        final_inventory = self.archive_inventory_path(final_archive)
        if (
            final_archive.exists()
            or final_checksum.exists()
            or os.path.lexists(final_inventory)
        ):
            raise BackupError(ErrorCode.ARTIFACT_ALREADY_EXISTS, "Backup ID уже существует")
        if not staging_archive.is_file() or not staging_checksum.is_file():
            raise BackupError(ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE, "Staging pair неполна", retryable=True)
        try:
            self._chmod(staging_archive, 0o600)
            self._chmod(staging_checksum, 0o600)
            os.replace(staging_archive, final_archive)
            self._fsync_file(final_archive)
            os.replace(staging_checksum, final_checksum)
            self._fsync_file(final_checksum)
            self._fsync_dir(final_archive.parent)
            return final_archive, final_checksum
        except OSError as exc:
            raise BackupError(ErrorCode.ARTIFACT_PUBLISH_INCOMPLETE, "Не удалось опубликовать archive/checksum pair", retryable=True) from exc

    def delete_pair(self, archive_path: Path, checksum_path: Path) -> None:
        archive_path = self._require_within(archive_path, self.root, "archive path")
        checksum_path = self._require_within(checksum_path, self.root, "checksum path")
        if checksum_path != self.checksum_path(archive_path):
            raise BackupError(ErrorCode.INVALID_REQUEST, "Checksum path не соответствует archive")
        inventory_path = self.archive_inventory_path(archive_path)
        directory_fd = None
        try:
            directory_fd = self._open_secure_directory(
                archive_path.parent,
                "archive directory",
            )
            try:
                inventory_entry = os.stat(
                    inventory_path.name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                inventory_entry = None
            if inventory_entry is not None:
                if stat.S_ISDIR(inventory_entry.st_mode):
                    raise OSError("archive inventory path is a directory")
                os.unlink(inventory_path.name, dir_fd=directory_fd)
            archive_path.unlink(missing_ok=True)
            checksum_path.unlink(missing_ok=True)
            self._fsync_dir(archive_path.parent)
            archive_inventory_query_cache.invalidate()
        except BackupError:
            raise
        except OSError as exc:
            raise BackupError(ErrorCode.RETENTION_DELETE_FAILED, "Не удалось удалить archive/checksum pair", retryable=True) from exc
        finally:
            if directory_fd is not None:
                os.close(directory_fd)

    def quarantine_path(self, path: Path, reason: str) -> Path:
        path = self._require_within(path, self.root, "quarantine source")
        if not path.is_file():
            raise BackupError(ErrorCode.ARTIFACT_NOT_FOUND, "Файл для quarantine не найден")
        target = self.root / "quarantine" / f"{path.name}.{reason}"
        counter = 0
        while target.exists():
            counter += 1
            target = self.root / "quarantine" / f"{path.name}.{reason}.{counter}"
        try:
            os.replace(path, target)
            self._fsync_dir(path.parent)
            self._fsync_dir(target.parent)
            return target
        except OSError as exc:
            raise BackupError(ErrorCode.STORAGE_BACKEND_ERROR, "Не удалось переместить файл в quarantine") from exc

    def resolve_key(self, key: str) -> Path:
        from .validation import validate_storage_key
        validate_storage_key(key)
        path = (self.root / PurePosixPath(key)).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise BackupError(ErrorCode.INVALID_REQUEST, "Storage key выходит за storage root") from exc
        return path

    def relative_key(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError as exc:
            raise BackupError(ErrorCode.INVALID_REQUEST, "Path находится вне storage root") from exc

    @staticmethod
    def _fsync_file(path: Path) -> None:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
