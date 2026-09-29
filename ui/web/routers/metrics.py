"""API метрик (§10.1 ТЗ): только чтение базы, без единого SSH.

Главное свойство этого роутера — чего он **не** делает. Он не подключается
к серверам: открытие исторического раздела не должно создавать нагрузку
(§10.4), поэтому здесь нет ни ``exec_command``, ни проб доступности. Числа
берутся из ``state.db``, статус — из уже собранного ``monitor.json``, а
живые значения остаются за ``/api/servers/{id}/metrics`` и ``/probe``
(их не трогаем, §10.4).

Смысл данных («что такое разрыв», «где точки усреднены по часу», «чем
отличается отсутствие данных от нуля») живёт в ``core.metrics``: роутер
только разбирает параметры и отвечает. Разложи это по эндпоинтам — UI и
SSE начнут толковать одни и те же точки по-разному и разойдутся молча.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..deps import err, parse_ts

router = APIRouter(tags=["metrics"])


def _availability() -> dict:
    """Доступность серверов из ``monitor.json`` — файла, который уже есть.

    Читается здесь, а не в ``core.metrics``: тот владеет таблицами, а не
    файлами панели. Ошибка чтения — не ошибка запроса: без доступности
    статус считается по свежести точек, и это честный ответ, а не пятьсот.
    """
    try:
        from core.monitor import load_monitor

        monitor = load_monitor() or {}
    except Exception as e:
        print(f"[WEB] метрики: monitor.json не прочитан: {e}", flush=True)
        return {}
    return {
        server_id: (entry.get("availability") or {})
        for server_id, entry in monitor.items()
        if isinstance(entry, dict)
    }


@router.get("/api/metrics/overview")
async def api_metrics_overview(
    range_: Optional[str] = Query(None, alias="range"),
    sparkline_points: Optional[int] = Query(None, ge=1),
):
    """Список серверов со спарклайнами (§10.1): один запрос на весь экран.

    По умолчанию — 24 часа и 48 точек; неизвестный ``range`` отвергается,
    а не подменяется молча на сутки: «показали не то, что просили» хуже
    честной ошибки.
    """
    try:
        from core.metrics import DEFAULT_RANGE, RANGES, overview
        from core.storage import load_servers

        if range_ is not None and range_ not in RANGES:
            raise HTTPException(400, f"range: ожидается {'|'.join(RANGES)}")
        return await asyncio.to_thread(
            overview,
            load_servers() or [],
            _availability(),
            range_key=range_ or DEFAULT_RANGE,
            points=sparkline_points,
        )
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.get("/api/metrics/servers/{server_id}/latest")
async def api_metrics_latest(server_id: str):
    """Последняя проба из базы (§10.1) — историческая опора карточки.

    Живое значение берётся из существующего ``/api/servers/{id}/metrics``,
    этот эндпоинт SSH не трогает и потому безопасен на открытии карточки.
    """
    try:
        from core.metrics import latest
        from core.storage import find_server

        if not find_server(server_id):
            raise HTTPException(404, "Сервер не найден")
        return await asyncio.to_thread(latest, server_id)
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.get("/api/metrics/servers/{server_id}")
async def api_metrics_series(
    server_id: str,
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None, alias="to"),
    step: str = "auto",
):
    """Ряд одного сервера за окно (§10.1). Чтение базы, без SSH.

    Границы принимаются epoch-секундами или ISO, отдаются всегда epoch
    UTC. Фактические границы ответа могут быть у́же запрошенных: сырых
    проб старше ретенции в базе нет, и ответ говорит об этом полями
    ``from``/``to``, а не пустотой в начале ряда.
    """
    try:
        from core.metrics import series
        from core.storage import find_server

        if not find_server(server_id):
            raise HTTPException(404, "Сервер не найден")
        if step not in ("auto", "raw", "hour"):
            raise HTTPException(400, "step: ожидается auto|raw|hour")
        return await asyncio.to_thread(
            series,
            server_id,
            since=parse_ts(from_, None),
            until=parse_ts(to, None),
            step=step,
        )
    except HTTPException:
        raise
    except ValueError as e:
        # Проверки окна живут в ядре («from больше to», неизвестный шаг) —
        # здесь они превращаются в 400, чтобы таймлайн (§10.3) отвечал так
        # же и клиенту не приходилось разбирать два разных поведения.
        return err(e, code=400)
    except Exception as e:
        return err(e)
