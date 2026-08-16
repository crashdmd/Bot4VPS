"""API встроенного updater'а (Web UI только дергает ядро, ТЗ п.19).

router       — рабочие эндпоинты за require_auth;
health_router — /api/upd/health без авторизации, но только с loopback:
                его опрашивает runner после перезапуска (все /api/*,
                включая /api/ping, закрыты require_auth).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..deps import err
from ..deps import VERSION

router = APIRouter(tags=["update"])
health_router = APIRouter(tags=["update"])


@router.get("/api/update/state")
async def api_update_state():
    try:
        from core.update import updater
        state = updater.read_state()
        state["current_version"] = VERSION
        return state
    except Exception as e:
        return err(e)


@router.post("/api/update/check")
async def api_update_check():
    try:
        from core.update import updater
        result = await updater.check_for_update(notify=True)
        if result.get("busy"):
            raise HTTPException(400, "Обновление уже выполняется")
        return result
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.get("/api/update/changelog")
async def api_update_changelog():
    """Changelog текущей установленной версии (локальный файл)."""
    try:
        from core.update import updater
        if not updater.CHANGELOG_FILE.exists():
            raise HTTPException(500, "Changelog не найден")
        text = updater.CHANGELOG_FILE.read_text(encoding="utf-8")
        return {"version": VERSION, "changelog": text.strip()}
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.get("/api/update/changelog_new")
async def api_update_changelog_new():
    """Changelog найденного обновления (changelog_new)."""
    try:
        from core.update import updater
        state = updater.read_state()
        available = state.get("available")
        if not available or not updater.CHANGELOG_NEW_FILE.exists():
            raise HTTPException(404, "Нет доступного обновления")
        text = updater.CHANGELOG_NEW_FILE.read_text(encoding="utf-8")
        return {"version": available["version"], "changelog": text.strip()}
    except HTTPException:
        raise
    except Exception as as_e:
        return err(as_e)


@router.post("/api/update/install")
async def api_update_install():
    try:
        from core.update import updater
        return await updater.start_install()
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        return err(e)


@router.get("/api/update/versions")
async def api_update_versions():
    """Версии ≥ 4.0.0 для отката (заголовки changelog.md в main)."""
    try:
        from core.update import updater
        import asyncio
        versions = await asyncio.to_thread(updater.list_rollback_versions)
        return {"versions": versions, "current": VERSION}
    except Exception as e:
        # Человекочитаемое описание (404 -> «changelog ещё не опубликован» и т.п.)
        try:
            from core.update.updater import _friendly_check_error
            return err(ValueError(_friendly_check_error(e)), code=502)
        except Exception:
            return err(e, code=502)


@router.post("/api/update/rollback")
async def api_update_rollback(body: dict):
    try:
        from core.update import updater
        version = str((body or {}).get("version") or "").strip()
        if not version:
            raise HTTPException(400, "Не указана версия")
        try:
            updater.parse_version(version)
        except ValueError:
            raise HTTPException(400, "Неверный формат версии")
        return await updater.start_rollback(version)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@health_router.get("/api/upd/health")
async def api_upd_health(request: Request):
    """Health-check раннера: без авторизации, но только с loopback."""
    host = (request.client.host if request.client else "") or ""
    if host not in ("127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost"):
        raise HTTPException(403, "Только локальные запросы")
    return {"ok": True, "version": VERSION}
