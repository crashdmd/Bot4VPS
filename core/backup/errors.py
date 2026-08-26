from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import uuid4


class ErrorCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    PROFILE_INVALID = "PROFILE_INVALID"
    PROFILE_NO_SOURCES = "PROFILE_NO_SOURCES"
    MANIFEST_MISSING = "MANIFEST_MISSING"
    MANIFEST_DUPLICATE = "MANIFEST_DUPLICATE"
    MANIFEST_INVALID = "MANIFEST_INVALID"
    MANIFEST_VERSION_UNSUPPORTED = "MANIFEST_VERSION_UNSUPPORTED"
    ARCHIVE_TYPE_MISMATCH = "ARCHIVE_TYPE_MISMATCH"
    ARCHIVE_INVALID = "ARCHIVE_INVALID"
    ARCHIVE_PATH_UNSAFE = "ARCHIVE_PATH_UNSAFE"
    ARCHIVE_SPECIAL_FILE_UNSUPPORTED = "ARCHIVE_SPECIAL_FILE_UNSUPPORTED"
    CHECKSUM_MISSING = "CHECKSUM_MISSING"
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
    ARCHIVE_FILENAME_CONFLICT = "ARCHIVE_FILENAME_CONFLICT"
    ARCHIVE_REPLACE_CONFIRMATION_REQUIRED = "ARCHIVE_REPLACE_CONFIRMATION_REQUIRED"
    ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
    ARTIFACT_ALREADY_EXISTS = "ARTIFACT_ALREADY_EXISTS"
    ARTIFACT_IN_USE = "ARTIFACT_IN_USE"
    ARTIFACT_PUBLISH_INCOMPLETE = "ARTIFACT_PUBLISH_INCOMPLETE"
    CATALOG_CONFLICT = "CATALOG_CONFLICT"
    RETENTION_CLAIM_CONFLICT = "RETENTION_CLAIM_CONFLICT"
    RETENTION_DELETE_FAILED = "RETENTION_DELETE_FAILED"
    LOCK_TIMEOUT = "LOCK_TIMEOUT"
    MAINTENANCE_ACTIVE = "MAINTENANCE_ACTIVE"
    TARGET_BUSY = "TARGET_BUSY"
    LOCKING_UNAVAILABLE = "LOCKING_UNAVAILABLE"
    DISK_SPACE_WARNING = "DISK_SPACE_WARNING"
    DISK_SPACE_CRITICAL = "DISK_SPACE_CRITICAL"
    DISK_SPACE_EMERGENCY = "DISK_SPACE_EMERGENCY"
    SOURCE_LIMIT_EXCEEDED = "SOURCE_LIMIT_EXCEEDED"
    ARCHIVE_LIMIT_EXCEEDED = "ARCHIVE_LIMIT_EXCEEDED"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SOURCE_PERMISSION_DENIED = "SOURCE_PERMISSION_DENIED"
    SSH_UNREACHABLE = "SSH_UNREACHABLE"
    SSH_AUTH_FAILED = "SSH_AUTH_FAILED"
    SFTP_FAILED = "SFTP_FAILED"
    STAGING_IO_FAILED = "STAGING_IO_FAILED"
    ARCHIVE_CREATE_FAILED = "ARCHIVE_CREATE_FAILED"
    VERIFY_FAILED = "VERIFY_FAILED"
    PROTECTIVE_BACKUP_FAILED = "PROTECTIVE_BACKUP_FAILED"
    RESTORE_PRECHECK_FAILED = "RESTORE_PRECHECK_FAILED"
    RESTORE_APPLY_FAILED = "RESTORE_APPLY_FAILED"
    RESTORE_METADATA_FAILED = "RESTORE_METADATA_FAILED"
    RESTORE_CANCEL_FORBIDDEN = "RESTORE_CANCEL_FORBIDDEN"
    MIGRATION_FAILED = "MIGRATION_FAILED"
    UPDATE_MAINTENANCE_CONFLICT = "UPDATE_MAINTENANCE_CONFLICT"
    OPERATION_NOT_FOUND = "OPERATION_NOT_FOUND"
    OPERATION_CONFLICT = "OPERATION_CONFLICT"
    OPERATION_ABANDONED = "OPERATION_ABANDONED"
    CANCELLED_BY_USER = "CANCELLED_BY_USER"
    IMPORT_TOO_LARGE = "IMPORT_TOO_LARGE"
    STORAGE_BACKEND_ERROR = "STORAGE_BACKEND_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class SafeError:
    code: str
    message: str
    retryable: bool
    correlation_id: str
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        result = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "correlation_id": self.correlation_id,
        }
        if self.details:
            result["details"] = dict(self.details)
        return result


class BackupError(Exception):
    def __init__(
        self,
        code: ErrorCode | str,
        safe_message: str,
        *,
        retryable: bool = False,
        correlation_id: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        self.code = code.value if isinstance(code, ErrorCode) else str(code)
        self.safe_message = str(safe_message)
        self.retryable = bool(retryable)
        self.correlation_id = correlation_id or uuid4().hex
        self.details = dict(details or {})
        super().__init__(self.safe_message)

    def to_safe_error(self) -> SafeError:
        return SafeError(
            self.code,
            self.safe_message,
            self.retryable,
            self.correlation_id,
            dict(self.details),
        )
