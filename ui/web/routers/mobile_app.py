"""Deliver the verified Android release from its independent public source."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from ..security import require_auth
from core import mobile_release

Release = mobile_release.Release

RELEASE_DIR = Path(__file__).resolve().parents[2] / "mobile"
router = APIRouter(prefix="/api/mobile-app", dependencies=[Depends(require_auth)], include_in_schema=False)
logger = logging.getLogger(__name__)
_send_lock = asyncio.Lock()
_last_send = 0.0


def bundled_release() -> Release:
    """Compatibility entry point for validating the supplied fallback APK."""
    try:
        return mobile_release.bundled_release(RELEASE_DIR)
    except (OSError, ValueError, TypeError, KeyError):
        raise HTTPException(503, "Релиз приложения пока недоступен. Проверьте целостность установки Bot4VPS.") from None


def available_release() -> Release:
    try:
        return mobile_release.selected_release(RELEASE_DIR)
    except (OSError, ValueError, TypeError, KeyError):
        raise HTTPException(503, "Релиз приложения пока недоступен. Проверьте источник APK в настройках.") from None


async def latest_release() -> Release:
    try:
        await asyncio.to_thread(mobile_release.refresh, directory=RELEASE_DIR)
    except Exception:
        logger.warning("Не удалось обновить локальную копию APK")
    return await asyncio.to_thread(available_release)


async def latest_document():
    await latest_release()
    return await asyncio.to_thread(mobile_release.open_selected, RELEASE_DIR)


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
        release = await asyncio.to_thread(available_release)
    except HTTPException as exc:
        try:
            release = await latest_release()
        except HTTPException:
            return {"available": False, "message": exc.detail, "telegram_available": False, "telegram_hint": ""}
    try:
        ready, reason = await asyncio.to_thread(telegram_delivery)
    except Exception:
        logger.warning("Telegram availability could not be checked for APK delivery")
        ready, reason = False, "Не удалось проверить настройки Telegram"
    return {"available": True, "version": release.version, "size": release.size, "sha256": release.sha256,
            "versionCode": release.version_code,
            "installation_note": release.installation_note,
            "download_url": "/api/mobile-app/download", "telegram_available": ready, "telegram_hint": reason}


@router.post("/check", dependencies=[Depends(web_request)])
async def check():
    try:
        return await asyncio.to_thread(mobile_release.refresh, force=True, directory=RELEASE_DIR)
    except Exception:
        return {"ok": False, "updated": False, "error": "Не удалось проверить APK приложения."}


@router.get("/download", dependencies=[Depends(web_request)])
async def download():
    release, document = await latest_document()
    def chunks():
        with document:
            yield from iter(lambda: document.read(64 * 1024), b"")
    filename = f"Bot4VPS-Mobile-{release.version}-release.apk"
    class DownloadResponse(StreamingResponse):
        async def __call__(self, scope, receive, send):
            try:
                await super().__call__(scope, receive, send)
            finally:
                document.close()
    return DownloadResponse(chunks(), media_type="application/vnd.android.package-archive", headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Content-Length": str(release.size), "Content-Disposition": f'attachment; filename="{filename}"'})


async def send_release(release: Release, document=None):
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
        with document if document is not None else release.path.open("rb") as document:
            await asyncio.wait_for(bot_obj.send_document(
                chat_id=cfg["user_id"], document=document, filename=f"Bot4VPS-Mobile-{release.version}-release.apk",
                caption=(f"Bot4VPS Mobile {release.version} для Android. Подключение: Настройки → Мобильное приложение в Web-панели."
                         + ("\n\n" + release.installation_note if release.installation_note else ""))[:1024],
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
        release, document = await latest_document()
        try:
            _last_send = time.monotonic()
            await send_release(release, document=document)
        finally:
            document.close()
    return {"ok": True, "message": "APK отправлен настроенному получателю в Telegram"}
