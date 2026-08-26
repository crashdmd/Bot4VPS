from __future__ import annotations

import asyncio
import errno

from paramiko.sftp import SFTPError
from paramiko.ssh_exception import AuthenticationException, SSHException

from core.backup.manager import BackupManager
from core.backup.source_selection import (
    SourceSelectionError,
    list_source_tree,
    locate_source_path,
    source_path_signature,
    validate_sftp_sources,
)
from core.backup.validation import normalize_server_profile, parse_server_profile
from core.config import get_backup_config
from core.ssh import create_ssh_client
from core.storage import (
    compare_and_set_server_backup_profile,
    get_server_backup_snapshot,
)


class SftpBrowseError(ValueError):
    """Safe, user-facing error raised while inspecting remote Backup sources."""


def _classify_sftp_error(exc: Exception, path: str) -> SftpBrowseError:
    status = exc.args[0] if isinstance(exc, SFTPError) and exc.args else None
    error_number = getattr(exc, "errno", None)

    if (
        isinstance(exc, PermissionError)
        or status == 3
        or error_number in {errno.EACCES, errno.EPERM}
    ):
        return SftpBrowseError(
            "Нет доступа к пути. "
            "Пользователь, под которым выполнено SSH-подключение, "
            "не имеет прав на просмотр этого объекта."
        )

    if (
        isinstance(exc, FileNotFoundError)
        or status == 2
        or error_number == errno.ENOENT
    ):
        return SftpBrowseError(f"Путь не найден: {path}")

    if isinstance(exc, AuthenticationException):
        return SftpBrowseError(
            "Не удалось подключиться по SSH: проверьте данные доступа."
        )

    if isinstance(
        exc,
        (SSHException, ConnectionError, TimeoutError, EOFError),
    ):
        return SftpBrowseError(
            "Соединение с сервером потеряно. Проверьте подключение и повторите попытку."
        )

    return SftpBrowseError(
        "Не удалось проверить путь из-за ошибки SFTP. Повторите попытку."
    )


def manager() -> BackupManager:
    """Build the thin Web facade from the current validated configuration."""
    return BackupManager(get_backup_config())


async def call(method: str, *args, **kwargs):
    facade = manager()
    return await asyncio.to_thread(getattr(facade, method), *args, **kwargs)


def _close_sftp(sftp) -> None:
    close = getattr(sftp, "close", None)
    if callable(close):
        close()


def _with_sftp(server: dict, callback):
    ssh = create_ssh_client(server)
    try:
        sftp = ssh.open_sftp()
        try:
            return callback(sftp)
        finally:
            _close_sftp(sftp)
    finally:
        ssh.close()


def _source_tree_impl(server_id: str, path: str, *, cursor: int, limit: int) -> dict:
    snapshot = get_server_backup_snapshot(server_id)
    result = _with_sftp(
        snapshot["server"],
        lambda sftp: list_source_tree(sftp, path, cursor=cursor, limit=limit),
    )
    result["server_id"] = server_id
    return result


def _locate_source_impl(server_id: str, path: str) -> dict:
    snapshot = get_server_backup_snapshot(server_id)
    result = _with_sftp(
        snapshot["server"],
        lambda sftp: locate_source_path(sftp, path),
    )
    result["server_id"] = server_id
    return result


def _safe_remote_call(callback, *, path: str):
    try:
        return callback()
    except (SourceSelectionError, ValueError, TypeError):
        raise
    except Exception as exc:
        raise _classify_sftp_error(exc, path) from exc


def source_tree(server_id: str, path: str, *, cursor: int = 0, limit: int = 100) -> dict:
    return _safe_remote_call(
        lambda: _source_tree_impl(server_id, path, cursor=cursor, limit=limit),
        path=path,
    )


def locate_source(server_id: str, path: str) -> dict:
    return _safe_remote_call(
        lambda: _locate_source_impl(server_id, path),
        path=path,
    )


def _current_source_signature(raw_profile) -> tuple[str, ...] | None:
    if raw_profile is None:
        return ()
    try:
        return source_path_signature(parse_server_profile(raw_profile)["sources"])
    except Exception:
        # A malformed legacy profile cannot authorize skipping validation. The
        # submitted candidate still has to pass the current structural policy.
        return None


def save_server_backup_profile(server_id: str, submitted_profile: dict) -> dict:
    """Validate changed ordinary sources remotely, then commit through storage CAS."""
    snapshot = get_server_backup_snapshot(server_id)
    parsed = parse_server_profile(submitted_profile)
    candidate_signature = source_path_signature(parsed["sources"])
    current_signature = _current_source_signature(snapshot["profile"])
    sources_changed = candidate_signature != current_signature

    if sources_changed and parsed["sources"]:
        _safe_remote_call(
            lambda: _with_sftp(
                snapshot["server"],
                lambda sftp: validate_sftp_sources(sftp, parsed["sources"]),
            ),
            path=parsed["sources"][0]["path"],
        )

    canonical = normalize_server_profile(parsed)
    return compare_and_set_server_backup_profile(
        server_id,
        canonical,
        expected_profile=snapshot["profile"],
        expected_connection=snapshot["connection"],
    )


async def source_tree_async(
    server_id: str,
    path: str,
    *,
    cursor: int = 0,
    limit: int = 100,
) -> dict:
    return await asyncio.to_thread(source_tree, server_id, path, cursor=cursor, limit=limit)


async def locate_source_async(server_id: str, path: str) -> dict:
    return await asyncio.to_thread(locate_source, server_id, path)


async def save_server_backup_profile_async(server_id: str, profile: dict) -> dict:
    return await asyncio.to_thread(save_server_backup_profile, server_id, profile)
