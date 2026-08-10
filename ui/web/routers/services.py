# -*- coding: utf-8 -*-
"""Сервисы (WireGuard и др.) в Web UI.

Обобщённый тонкий роутер над ``core.integrator``: НЕ ветвится по id сервиса —
каждый эндпоинт маппится на метод контракта по ИМЕНИ (``call(sid, server, method,
…)`` / ``enqueue(sid, …)`` / ``sync(sid, …)``). Специфика конкретного сервиса
живёт за его контрактом. WireGuard — первый (и пока единственный) потребитель.
"""
from __future__ import annotations

import io
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..deps import err, task_brief

router = APIRouter(tags=["services"])


# do_* quick-ops вызываются напрямую (без очереди) и требуют async progress_cb.
async def _noop_progress(_line: str) -> None:
    return None


def _svc_do_result(res: Any) -> dict:
    """Сериализовать TaskResult от quick-op do_* в JSON."""
    return {
        "success": bool(getattr(res, "success", False)),
        "output": getattr(res, "output", None),
        "error": getattr(res, "error", None),
        "warnings": getattr(res, "warnings", False),
    }


# ------------------------------------------------------------------
# Метаданные (без сервера)
# ------------------------------------------------------------------

async def _sync_after(sid: str, server_id: str) -> dict:
    """Синхронизация кэша после мутации. Ошибку не глотаем — возвращаем в ответе.

    Мутация уже могла пройти успешно; UI видит live через get_state, но кэш
    должен либо обновиться, либо явно сообщить о сбое sync.
    """
    from core import integrator
    try:
        data = await integrator.sync(sid, server_id)
        return {"sync_ok": True, "status": data}
    except Exception as e:
        print(f"[WEB] sync failed after mutation {sid}/{server_id}: {e}", flush=True)
        return {"sync_ok": False, "sync_error": str(e)}



@router.get("/api/services")
async def api_services():
    """Список зарегистрированных сервисов (по манифестам)."""
    try:
        from core import integrator
        out = []
        for m in integrator.list_services():
            d = m.to_dict() if hasattr(m, "to_dict") else dict(
                id=getattr(m, "id", ""), name=getattr(m, "name", ""),
                icon=getattr(m, "icon", ""), extra=getattr(m, "extra", {}) or {},
            )
            out.append({
                "id": d.get("id"),
                "name": d.get("name"),
                "icon": d.get("icon"),
                # description не входит в именованные поля манифеста — лежит в extra
                "description": (d.get("extra") or {}).get("description")
                if isinstance(d.get("extra"), dict)
                else d.get("description"),
            })
        return {"services": out}
    except Exception as e:
        return err(e)


@router.get("/api/services/{sid}/params")
async def api_service_params(sid: str):
    """Схема параметров установки (для формы мастера)."""
    try:
        from core import integrator
        params = integrator.params_schema(sid)
        return {"params": [
            {
                "name": p.name, "type": p.type, "default": p.default,
                "required": p.required, "choices": list(p.choices or []),
                "min": p.min, "max": p.max, "pattern": p.pattern,
                "description": p.description,
            }
            for p in params
        ]}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


# ------------------------------------------------------------------
# Read-only (через call / кэш)
# ------------------------------------------------------------------

@router.get("/api/services/{sid}/status")
async def api_service_status(sid: str):
    """Статус сервиса по всем серверам (из кэша; быстро, без SSH)."""
    try:
        from core import integrator
        from core.storage import load_servers
        rows = []
        for s in load_servers():
            status = await integrator.call(sid, s["id"], "get_status") or {}
            rows.append({"id": s["id"], "name": s["name"], "host": s.get("host", ""), "status": status})
        return {"servers": rows}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.get("/api/services/{sid}/{server_id}/profiles")
async def api_service_profiles(sid: str, server_id: str):
    try:
        from core import integrator
        profiles = await integrator.call(sid, server_id, "get_profiles") or []
        return {"profiles": profiles}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.post("/api/services/{sid}/{server_id}/sync")
async def api_service_sync(sid: str, server_id: str):
    try:
        from core import integrator
        data = await integrator.sync(sid, server_id)
        return {"ok": True, "status": data}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.get("/api/services/{sid}/{server_id}/state")
async def api_service_state(sid: str, server_id: str):
    """Живое чтение состояния (без записи кэша) — для открытия/рефреша экрана
    сервиса: актуальная статистика, профили, поля конфига. Generic по sid."""
    try:
        from core import integrator
        data = await integrator.call(sid, server_id, "get_state") or {}
        return {"state": data}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.get("/api/services/{sid}/{server_id}/config/{name}")
async def api_service_config(sid: str, server_id: str, name: str):
    """Скачать клиентский конфиг (.conf). Данные — через сервис."""
    try:
        from core import integrator
        data = await integrator.call(sid, server_id, "fetch_profile_config", name)
        if not isinstance(data, (bytes, bytearray)):
            raise HTTPException(500, "Сервис вернул неожиданный тип данных конфига")
        return Response(
            content=bytes(data),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{name}.conf"'},
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.get("/api/services/{sid}/{server_id}/qr/{name}")
async def api_service_qr(sid: str, server_id: str, name: str):
    """QR-код клиентского конфига. Данные — через сервис (fetch_profile_config),
    PNG-рендер — представление роутера."""
    try:
        from core import integrator
        data = await integrator.call(sid, server_id, "fetch_profile_config", name)
        if not isinstance(data, (bytes, bytearray)):
            raise HTTPException(500, "Сервис вернул неожиданный тип данных конфига")
        try:
            config_text = bytes(data).decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(400, "Конфиг содержит недопустимые символы для QR")
        try:
            import qrcode
        except ImportError:
            raise HTTPException(
                500, "На сервере не установлена библиотека qrcode. "
                     "Установите: pip install 'qrcode[pil]'"
            )
        img = qrcode.make(config_text)
        bio = io.BytesIO()
        img.save(bio, "PNG")
        return Response(content=bio.getvalue(), media_type="image/png")
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        return err(e)


# ------------------------------------------------------------------
# Действия: быстрые (через call + _noop_progress)
# ------------------------------------------------------------------

class EndpointBody(BaseModel):
    endpoint: Optional[str] = None  # None/пусто = сброс


class ProfileAddBody(BaseModel):
    name: str


class ProfileToggleBody(BaseModel):
    """enabled=True → включить, False → выключить; None → инверт live-состояния."""
    enabled: Optional[bool] = None


class ProfileRenameBody(BaseModel):
    new_name: str


@router.post("/api/services/{sid}/{server_id}/endpoint")
async def api_service_endpoint(sid: str, server_id: str, body: EndpointBody):
    try:
        from core import integrator
        endpoint = (body.endpoint or "").strip() or None
        updated = await integrator.call(sid, server_id, "set_endpoint", endpoint)
        sync_info = await _sync_after(sid, server_id)
        return {"ok": True, "updated": updated, **sync_info}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


class UpdateConfigBody(BaseModel):
    # Все поля Optional: None = не менять (частичный patch, ТЗ §13).
    # endpoint: "" = явный сброс; port/address/dns передаются только при изменении.
    endpoint: Optional[str] = None
    port: Optional[int] = None
    address: Optional[str] = None
    dns: Optional[str] = None


def _step_error_message(e) -> str:
    """StepError → человекочитаемое сообщение для 400 (title + detail)."""
    detail = getattr(e, "detail", "") or ""
    title = getattr(e, "title", "") or ""
    if detail:
        return f"{title}: {detail}" if title else detail
    return str(e)


@router.post("/api/services/{sid}/{server_id}/config")
async def api_service_config_update(sid: str, server_id: str, body: UpdateConfigBody):
    """Частичное изменение конфигурации сервиса (endpoint/port/address/dns).
    Generic по sid: вызывает update_config контракта, затем обновляет кэш через
    sync. StepError (валидация/провал apply) → 400, прочее → err()."""
    try:
        from core import integrator
        from core.integrator import StepError
        try:
            await integrator.call(
                sid, server_id, "update_config",
                body.endpoint, body.port, body.address, body.dns,
            )
        except StepError as e:
            raise HTTPException(400, _step_error_message(e))
        data = await integrator.sync(sid, server_id)  # обновить кэш после apply
        return {"ok": True, "status": data}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.post("/api/services/{sid}/{server_id}/profiles")
async def api_service_profile_add(sid: str, server_id: str, body: ProfileAddBody):
    try:
        from core import integrator
        res = await integrator.call(sid, server_id, "do_add_profile", {"name": body.name}, _noop_progress)
        sync_info = await _sync_after(sid, server_id)
        out = _svc_do_result(res)
        if isinstance(out, dict):
            out.update(sync_info)
        return out
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.delete("/api/services/{sid}/{server_id}/profiles/{name}")
async def api_service_profile_delete(sid: str, server_id: str, name: str):
    try:
        from core import integrator
        res = await integrator.call(sid, server_id, "do_remove_profile", {"name": name}, _noop_progress)
        sync_info = await _sync_after(sid, server_id)
        out = _svc_do_result(res)
        if isinstance(out, dict):
            out.update(sync_info)
        return out
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.post("/api/services/{sid}/{server_id}/profiles/{name}/toggle")
async def api_service_profile_toggle(
    sid: str, server_id: str, name: str, body: ProfileToggleBody | None = None,
):
    """Вкл/выкл профиля через do_toggle_profile.

    Предпочтительно body.enabled явно (как в Telegram).
    Иначе — live get_state, не кэш get_profiles (иначе enable ломался).
    После успеха — sync кэша.
    """
    try:
        from core import integrator
        from core.integrator import StepError
        if body is not None and body.enabled is not None:
            enabled = bool(body.enabled)
        else:
            state = await integrator.call(sid, server_id, "get_state") or {}
            profiles = state.get("profiles") or []
            cur = True
            for p in profiles:
                if p.get("name") == name:
                    cur = bool(p.get("enabled", True))
                    break
            enabled = not cur
        try:
            res = await integrator.call(
                sid, server_id, "do_toggle_profile",
                {"name": name, "enabled": enabled}, _noop_progress,
            )
        except StepError as e:
            raise HTTPException(400, _step_error_message(e))
        sync_info = await _sync_after(sid, server_id)
        out = _svc_do_result(res)
        if isinstance(out, dict):
            out.update(sync_info)
        return out
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.post("/api/services/{sid}/{server_id}/profiles/{name}/rename")
async def api_service_profile_rename(sid: str, server_id: str, name: str, body: ProfileRenameBody):
    try:
        from core import integrator
        res = await integrator.call(
            sid, server_id, "do_rename_profile",
            {"old_name": name, "new_name": body.new_name}, _noop_progress,
        )
        sync_info = await _sync_after(sid, server_id)
        out = _svc_do_result(res)
        if isinstance(out, dict):
            out.update(sync_info)
        return out
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.post("/api/services/{sid}/{server_id}/profiles/{name}/reissue")
async def api_service_profile_reissue(sid: str, server_id: str, name: str):
    try:
        from core import integrator
        res = await integrator.call(sid, server_id, "do_reissue_profile", {"name": name}, _noop_progress)
        sync_info = await _sync_after(sid, server_id)
        out = _svc_do_result(res)
        if isinstance(out, dict):
            out.update(sync_info)
        return out
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


# ------------------------------------------------------------------
# Действия: тяжёлые (через очередь → polling GET /api/tasks/{id})
# ------------------------------------------------------------------

class ActionBody(BaseModel):
    params: Optional[dict] = None


@router.post("/api/services/{sid}/{server_id}/enqueue/{action}")
async def api_service_enqueue(sid: str, server_id: str, action: str, body: ActionBody):
    """Поставить в очередь do_<action> (install/remove/migrate/reissue_all/…).
    Любой do_* сервиса становится действием по контракту."""
    try:
        from core import integrator
        from core.task_manager import task_manager
        task = await integrator.enqueue(sid, server_id, action, body.params or {}, src="web")
        return {
            "ok": True,
            "task": task_brief(task),
            "position": task_manager.queue_position(task.id),
            "ahead": task_manager.tasks_ahead(task.id),
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.post("/api/services/{sid}/bulk-check")
async def api_service_bulk_check(sid: str):
    try:
        from core import integrator
        task = await integrator.enqueue_bulk_check(sid)
        return {"ok": True, "task": task_brief(task)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        return err(e)
