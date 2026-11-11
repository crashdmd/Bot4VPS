"""Общий адаптер собственных копий: TAR → B4VS v1 → optional B4VE.

Имена и catalog.format описывают внутренний tar.gz, как для B4VE.
B4VS не является TAR/gzip; старые восстановители отказывают до extraction.
Это граница совместимости, а не защита от ручной пересборки архива.
"""
from __future__ import annotations

import io
import os
import shutil
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .errors import BackupError, ErrorCode

SELF_MAGIC = b"B4VS"
# magic, container version=1, payload=gzip TAR=1, десять reserved нулей.
SELF_HEADER = SELF_MAGIC + b"\x01\x01" + b"\x00" * 10


class _PayloadReader(io.BufferedIOBase):
    """Seekable view: gzip rewind must return to payload, not outer header."""

    def __init__(self, stream, offset):
        self.stream = stream
        self.offset = offset
        stream.seek(offset)

    def readable(self):
        return True

    def seekable(self):
        return True

    def read(self, size=-1):
        return self.stream.read(size)

    def tell(self):
        return self.stream.tell() - self.offset

    def seek(self, offset, whence=os.SEEK_SET):
        if whence == os.SEEK_SET:
            offset += self.offset
        result = self.stream.seek(offset, whence) - self.offset
        if result < 0:
            raise ValueError("Seek before archive payload")
        return result


def _payload_offset(stream) -> int:
    stream.seek(0)
    prefix = stream.read(len(SELF_HEADER))
    if prefix[:4] != SELF_MAGIC:
        stream.seek(0)
        return 0
    if prefix != SELF_HEADER:
        raise BackupError(
            ErrorCode.ARCHIVE_INVALID,
            "Повреждённый или неподдерживаемый заголовок собственной копии Bot4VPS",
        )
    if stream.read(2) != b"\x1f\x8b":
        raise BackupError(ErrorCode.ARCHIVE_INVALID, "Контейнер Bot4VPS не содержит tar.gz")
    stream.seek(len(SELF_HEADER))
    return len(SELF_HEADER)


@contextmanager
def open_backup_tar(path):
    """Read ordinary TAR or the inner TAR of B4VS without extracting files."""
    with open(path, "rb") as stream:
        offset = _payload_offset(stream)
        if offset:
            payload = _PayloadReader(stream, offset)
            with tarfile.open(name=os.fspath(path), fileobj=payload, mode="r:gz") as archive:
                archive.self_container = True
                yield archive
        else:
            with tarfile.open(name=os.fspath(path), fileobj=stream, mode="r:*") as archive:
                archive.self_container = False
                yield archive


def wrap_self_archive(path):
    """Atomically wrap a newly created tar.gz; no existing backups are converted."""
    path = Path(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".self-container-")
    try:
        with os.fdopen(fd, "wb") as output, path.open("rb") as source:
            if source.read(2) != b"\x1f\x8b":
                raise BackupError(ErrorCode.ARCHIVE_INVALID, "Собственная копия должна содержать tar.gz")
            source.seek(0)
            output.write(SELF_HEADER)
            shutil.copyfileobj(source, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def copy_tar_payload(source, output):
    """Materialize inner TAR for the existing detached runner/system tar."""
    with open(source, "rb") as stream:
        _payload_offset(stream)
        shutil.copyfileobj(stream, output)


def archive_format_from_prefix(prefix: bytes) -> str:
    """Projection format describes the payload; binding uses full digest/bytes."""
    return "tar.gz" if prefix[:4] in {SELF_MAGIC, b"B4VE"} or prefix[:2] == b"\x1f\x8b" else "tar"
