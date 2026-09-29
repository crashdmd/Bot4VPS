"""API аудита и таймлайна (§10.2 и §10.3 ТЗ): чтение журнала, без SSH.

Границы этого роутера — ровно те же, что у метрик (§10.4): он ничего не
делает с серверами. Открытие «Истории» не поднимает ни одного SSH-сеанса —
иначе разбор вчерашнего отказа сам создавал бы нагрузку и попадал в
журнал (проверка доступности пишет события). Смысл данных живёт в
``core.audit_query`` (что значит «пара операции», «где лог недоступен») и
``core.timeline`` (что значит «марка»): роутер разбирает параметры и
отвечает, а не толкует записи.

Порядок объявления эндпоинтов здесь не косметика: ``/api/audit/facets`` и
``/api/audit/stats`` — статические пути, а ``/api/audit/{record_id}``
совпадает с ними шаблоном. FastAPI разбирает маршруты в порядке
регистрации, поэтому статические идут первыми; поменяй их местами —
``facets`` превратится в «запись не найдена».

Валидация параметров (``limit``, ``actor_type``, ``cursor``, ``step``)
живёт в ядре и прилетает сюда ``ValueError``: одно место решает, что
считать корректным окном, — иначе история и таймлайн разойдутся в том,
какие запросы они принимают.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..deps import err, parse_ts

router = APIRouter(tags=["audit"])


@router.get("/api/audit")
async def api_audit_list(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None, alias="to"),
    actor_type: Optional[str] = None,
    actor_id: Optional[str] = None,
    server_id: Optional[str] = None,
    action: Optional[str] = None,
    action_prefix: Optional[str] = None,
    result: Optional[str] = None,
    q: Optional[str] = None,
    limit: Optional[int] = None,
    cursor: Optional[str] = None,
):
    """Одна страница журнала (§10.2).

    Пагинация — по стабильной паре ``(started_ts, sort_id)`` логической
    операции, а не ``offset``: журнал растёт сверху, и страница по номеру
    строки на следующем шаге сдвинулась бы, показав одни операции дважды,
    а другие — ни разу. Приход финальной технической записи не меняет
    позицию уже начатой операции.

    Пределы ``limit`` не повторяются здесь числами: их держит ядро, и
    второй экземпляр границы однажды разошёлся бы с первым.

    ``HTTPException`` уходит наружу первой ветвью: ``parse_ts`` отвергает
    нечитаемое время именно ею, и без этой ветви отказ клиента прилетел бы
    ему как 500 — «ошибка сервера» на то, что целиком лежит в запросе, — а
    в лог панели за этим ушёл бы разбор несуществующей поломки.
    """
    try:
        from core.audit_query import DEFAULT_LIMIT, list_records

        return await asyncio.to_thread(
            list_records,
            since=parse_ts(from_, None),
            until=parse_ts(to, None),
            actor_type=actor_type,
            actor_id=actor_id,
            server_id=server_id,
            action=action,
            action_prefix=action_prefix,
            result=result,
            q=q,
            limit=DEFAULT_LIMIT if limit is None else limit,
            cursor=cursor,
        )
    except HTTPException:
        raise
    except ValueError as e:
        return err(e, code=400)
    except Exception as e:
        return err(e)


@router.get("/api/audit/facets")
async def api_audit_facets():
    """Значения для фильтров с количеством (§10.2).

    Списки приходят из журнала, а не выдумываются UI: фильтр по актору,
    которого в журнале нет, всегда даёт пустую страницу, и предлагать его
    — обман.
    """
    try:
        from core.audit_query import facets

        return await asyncio.to_thread(facets)
    except Exception as e:
        return err(e)


@router.get("/api/audit/stats")
async def api_audit_stats(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None, alias="to"),
    group_by: str = "action",
):
    """Агрегаты за период (§10.2): кто, что, где, чем кончилось, когда."""
    try:
        from core.audit_query import stats

        return await asyncio.to_thread(
            stats,
            since=parse_ts(from_, None),
            until=parse_ts(to, None),
            group_by=group_by,
        )
    except HTTPException:
        raise
    except ValueError as e:
        return err(e, code=400)
    except Exception as e:
        return err(e)


@router.get("/api/audit/{record_id}")
async def api_audit_record(record_id: str):
    """Логическая операция и её техническая raw-хронология (§10.2).

    ``record_id`` может быть canonical id операции или id любой её raw-записи,
    поэтому старые deep-link'и и марки таймлайна остаются рабочими. Отсутствие
    приложения — не ошибка: ``log.available=false`` с причиной честнее, чем
    пустое поле без объяснения.
    """
    try:
        from core.audit_query import record_detail

        detail = await asyncio.to_thread(record_detail, record_id)
        if detail is None:
            raise HTTPException(404, "Запись аудита не найдена")
        return detail
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.get("/api/timeline/{server_id}")
async def api_timeline(
    server_id: str,
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None, alias="to"),
    step: str = "auto",
    line_context: Optional[str] = None,
):
    """Ряд, марки действий и разрывы одного сервера (§10.3).

    Границы ответа — фактические; марки читаются ровно по ним, поэтому
    график и аннотации не могут разойтись. Существование сервера
    проверяется по реестру панели: таймлайн удалённого сервера — это 404, а
    не пустой график (пустой означал бы «данных за это окно нет», а не
    «сервера нет»).
    """
    try:
        from core.storage import find_server
        from core.timeline import timeline

        if not find_server(server_id):
            raise HTTPException(404, "Сервер не найден")
        if line_context not in (None, "true", "false"):
            raise ValueError("line_context: ожидается true или false")
        return await asyncio.to_thread(
            timeline,
            server_id,
            since=parse_ts(from_, None),
            until=parse_ts(to, None),
            step=step,
            line_context=line_context == "true",
        )
    except HTTPException:
        raise
    except ValueError as e:
        return err(e, code=400)
    except Exception as e:
        return err(e)
