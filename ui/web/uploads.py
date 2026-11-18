"""Ограниченное чтение загруженного файла до прикладного лимита."""
from fastapi import HTTPException, UploadFile


async def read_limited_upload(upload: UploadFile, limit: int, message: str) -> bytes:
    chunks = []
    size = 0
    try:
        while True:
            chunk = await upload.read(min(64 * 1024, limit + 1 - size))
            if not chunk:
                return b"".join(chunks)
            size += len(chunk)
            if size > limit:
                raise HTTPException(400, message)
            chunks.append(chunk)
    finally:
        await upload.close()
