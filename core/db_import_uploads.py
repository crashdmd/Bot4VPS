"""Закрытые временные файлы импорта 3x-ui: повтор и срок хранения 24 часа."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import re
import stat
import tempfile
import time

TTL_SECONDS = 24 * 60 * 60
MAX_BYTES = 5 * 1024 * 1024
NAME_RE = re.compile(r"xui-db-import-[A-Za-z0-9_-]+\.(?:bin|db|dump)")


def upload_directory() -> Path:
    return Path.cwd() / "data" / "tmp"


def save_upload(data: bytes) -> Path:
    cleanup_expired()
    directory = upload_directory()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix="xui-db-import-", suffix=".bin", dir=directory)
    path = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


@contextmanager
def open_upload(raw_path):
    path = Path(raw_path)
    directory = upload_directory().resolve()
    if path.parent.resolve() != directory or not NAME_RE.fullmatch(path.name):
        raise ValueError("Файл импорта недоступен. Загрузите файл заново.")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise ValueError("Файл импорта не найден. Загрузите файл заново.") from exc
    with os.fdopen(fd, "rb") as stream:
        fcntl.flock(stream, fcntl.LOCK_SH)
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_BYTES:
            raise ValueError("Файл импорта некорректен или превышает 5 МБ.")
        if time.time() - metadata.st_mtime >= TTL_SECONDS:
            raise ValueError("Срок хранения файла импорта истёк (24 часа). Загрузите файл заново.")
        yield stream


def cleanup_expired() -> int:
    count = 0
    for path in upload_directory().glob("xui-db-import-*"):
        if not NAME_RE.fullmatch(path.name):
            continue
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as stream:
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                metadata = os.fstat(stream.fileno())
                if stat.S_ISREG(metadata.st_mode) and time.time() - metadata.st_mtime >= TTL_SECONDS:
                    current = path.lstat()
                    if (current.st_dev, current.st_ino) == (metadata.st_dev, metadata.st_ino):
                        path.unlink()
                        count += 1
        except FileNotFoundError:
            continue
    return count


async def cleanup_job(_context=None):
    import asyncio
    await asyncio.to_thread(cleanup_expired)
