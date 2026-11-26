"""Protect uploads before form parsing, and enforce individual file limits."""
import shutil
import tempfile

from fastapi import HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from starlette.routing import compile_path, get_route_path

from .security import auth_enabled, browser_origin_matches, require_auth, verified_mobile_device_id


_MIB = 1024 * 1024
_MULTIPART_OVERHEAD = 256 * 1024
_BACKUP_UPLOAD = "/api/backups/import"
_UPLOAD_LIMITS = {
    _BACKUP_UPLOAD: None,
    "/api/files/upload": 5 * _MIB,
    "/api/files/docker/upload": 5 * _MIB,
    "/api/files/docker/projects/upload": 50 * _MIB,
    "/api/upload/script": _MIB,
    "/api/gateways/{node_id}/backups/upload": 32 * _MIB,
    "/api/services/{sid}/{server_id}/stacks/{name}/zip": 50 * _MIB,
    "/api/services/{sid}/{server_id}/db-import": 5 * _MIB,
    "/api/settings/web/tls/upload": 2 * _MIB,
}
_UPLOAD_ROUTES = [(path, compile_path(path)[0]) for path in _UPLOAD_LIMITS]
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_TOO_LARGE = "Размер запроса превышает допустимый для этой загрузки"


def _upload_body_limit(path: str) -> int:
    if path == _BACKUP_UPLOAD:
        from core.config import get_backup_config

        configured = get_backup_config()["bot4vps"]["limits"].get("max_archive_bytes")
        spool_capacity = shutil.disk_usage(tempfile.gettempdir()).free
        if configured is None:
            return spool_capacity
        return min(spool_capacity, int(configured) + _MULTIPART_OVERHEAD)
    return _UPLOAD_LIMITS[path] + _MULTIPART_OVERHEAD


class WebRequestGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in _SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        path = get_route_path(scope)
        if not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        mobile = verified_mobile_device_id(request)
        if not mobile and request.session.get("user") and auth_enabled() and not browser_origin_matches(request):
            await JSONResponse({"detail": "Откройте действие в самой панели"}, status_code=403)(scope, receive, send)
            return

        route = next((name for name, pattern in _UPLOAD_ROUTES if pattern.fullmatch(path)), None)
        if route is None:
            await self.app(scope, receive, send)
            return

        try:
            await require_auth(request)
        except HTTPException as exc:
            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)(scope, receive, send)
            return

        limit = _upload_body_limit(route)
        declared = request.headers.get("content-length")
        if declared is not None:
            if not declared.isascii() or not declared.isdecimal() or len(declared) > 20:
                await JSONResponse({"detail": "Некорректный размер запроса"}, status_code=400)(scope, receive, send)
                return
            if int(declared) > limit:
                await JSONResponse({"detail": _TOO_LARGE}, status_code=413)(scope, receive, send)
                return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise HTTPException(413, _TOO_LARGE)
            return message

        await self.app(scope, limited_receive, send)


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
