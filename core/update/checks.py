"""Service update discovery and Android APK refresh have independent results."""
import asyncio


async def check_updates(*, notify: bool) -> dict:
    from core import mobile_release
    from core.update import updater

    service, mobile = await asyncio.gather(
        updater.check_for_update(notify=notify),
        asyncio.to_thread(mobile_release.refresh, force=True),
        return_exceptions=True,
    )
    if isinstance(service, BaseException):
        raise service
    if isinstance(mobile, BaseException):
        mobile = {"ok": False, "updated": False, "error": "Не удалось проверить APK приложения."}
    return {**service, "mobile_app": mobile}
