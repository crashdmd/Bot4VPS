"""Download the bundled Android release or send it to the configured owner."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse

from ..security import require_auth

RELEASE_DIR = Path(__file__).resolve().parents[2] / "mobile"
router = APIRouter(prefix="/api/mobile-app", dependencies=[Depends(require_auth)], include_in_schema=False)
logger = logging.getLogger(__name__)
_send_lock = asyncio.Lock()
_last_send = 0.0


@dataclass(frozen=True)
class Release:
    path: Path
    version: str
    size: int
    sha256: str


def bundled_release() -> Release:
    """Only a contained, verified, fixed release can be delivered."""
    try:
        root = RELEASE_DIR.resolve()
        manifest = json.loads((root / "release.json").read_text(encoding="utf-8"))
        version = manifest["version"]
        if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?", version):
            raise ValueError()
        filename = f"Bot4VPS-Mobile-{version}-release.apk"
        if manifest["filename"] != filename:
            raise ValueError()
        path = root / filename
        if path.is_symlink() or path.resolve().parent != root:
            raise ValueError()
        size, digest = manifest["size"], manifest["sha256"]
        if type(size) is not int or not 0 < size < 49_000_000 or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError()
        with path.open("rb") as stream:
            checksum = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(chunk)
            if path.stat().st_size != size or checksum.hexdigest() != digest:
                raise ValueError()
        return Release(path, version, size, digest)
    except (OSError, ValueError, TypeError, KeyError):
        raise HTTPException(503, "Релиз приложения пока недоступен. Проверьте целостность установки Bot4VPS.") from None


def telegram_delivery():
    from core.config import get_telegram_config
    cfg = get_telegram_config()
    ready = bool(cfg.get("enabled") and cfg.get("token_set") and cfg.get("user_id") is not None)
    reason = "" if ready else "Telegram выключен" if not cfg.get("enabled") else "Сначала настройте бота и получателя в Telegram"
    return ready, reason


async def web_request(request: Request, response: Response):
    if request.scope.get("state", {}).get("mobile_device_id") or request.headers.get("x-bot4vps-mobile-session"):
        raise HTTPException(404, "Не найдено")
    response.headers["Cache-Control"] = "no-store"
    if request.method != "GET":
        expected = f"{request.url.scheme}://{request.url.netloc}"
        if (request.headers.get("origin") != expected
                or request.headers.get("sec-fetch-site", "") not in ("", "same-origin", "none")
                or request.headers.get("x-bot4vps-pairing-web") != "1"):
            raise HTTPException(403, "Откройте настройки в самой панели")


@router.get("", dependencies=[Depends(web_request)])
async def state():
    try:
        release = await asyncio.to_thread(bundled_release)
    except HTTPException as exc:
        return {"available": False, "message": exc.detail, "telegram_available": False, "telegram_hint": ""}
    try:
        ready, reason = await asyncio.to_thread(telegram_delivery)
    except Exception:
        logger.warning("Telegram availability could not be checked for APK delivery")
        ready, reason = False, "Не удалось проверить настройки Telegram"
    return {"available": True, "version": release.version, "size": release.size, "sha256": release.sha256,
            "download_url": "/api/mobile-app/download", "telegram_available": ready, "telegram_hint": reason}


@router.get("/download", dependencies=[Depends(web_request)])
async def download():
    release = await asyncio.to_thread(bundled_release)
    return FileResponse(release.path, filename=release.path.name, media_type="application/vnd.android.package-archive",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


async def send_release(release: Release):
    from core.config import get_saved_bot_token, get_telegram_config
    from core.telegram_health import classify_telegram_error
    cfg = await asyncio.to_thread(get_telegram_config)
    token = await asyncio.to_thread(get_saved_bot_token)
    if not cfg.get("enabled") or not token or cfg.get("user_id") is None:
        raise HTTPException(409, "Telegram выключен или не настроен. Скачайте APK в панели.")
    bot_obj = None
    owned = initialized = False
    try:
        try:
            from bot import get_application
            app = get_application()
        except Exception:
            app = None
        if app is not None and str(getattr(app.bot, "token", "") or "") == token:
            bot_obj = app.bot
            initialized = True
        else:
            from telegram import Bot
            bot_obj = Bot(token=token)
            owned = True
            await asyncio.wait_for(bot_obj.initialize(), timeout=10)
            initialized = True
        with release.path.open("rb") as document:
            await asyncio.wait_for(bot_obj.send_document(
                chat_id=cfg["user_id"], document=document, filename=release.path.name,
                caption=f"Bot4VPS Mobile {release.version} для Android. Подключение: Настройки → Мобильное приложение в Web-панели.",
                read_timeout=30, write_timeout=30, connect_timeout=10), timeout=45)
    except HTTPException:
        raise
    except Exception as exc:
        result = classify_telegram_error(exc, phase="send" if initialized else "token")
        raise HTTPException(502, f"Не удалось отправить APK в Telegram: {result.reason}") from None
    finally:
        if owned and bot_obj is not None:
            try:
                await asyncio.wait_for(bot_obj.shutdown(), timeout=5)
            except Exception:
                pass


@router.post("/send", dependencies=[Depends(web_request)])
async def send():
    global _last_send
    if _send_lock.locked():
        raise HTTPException(429, "APK уже отправляется. Дождитесь результата.")
    async with _send_lock:
        if _last_send and time.monotonic() - _last_send < 60:
            raise HTTPException(429, "Повторная отправка доступна через минуту.")
        ready, _ = await asyncio.to_thread(telegram_delivery)
        if not ready:
            raise HTTPException(409, "Telegram выключен или не настроен. Скачайте APK в панели.")
        release = await asyncio.to_thread(bundled_release)
        _last_send = time.monotonic()
        await send_release(release)
    return {"ok": True, "message": "APK отправлен настроенному получателю в Telegram"}
