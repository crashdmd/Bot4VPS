"""Запись аудита для действий Quick Setup: один хук на операцию.

Действия QS живут в ``core/quick_setup/manager.py`` — это фасад, через
который к подсистеме приходят Web, Telegram и CLI. Хук здесь, а не в
каждом вызывающем: одна таблица «операция → код аудита» рядом с публичным
API, и ни один новый вход в QS не остаётся без следа по забывчивости.

Почему декоратор, а не вызовы ``audit.record`` в теле функций: у операций
разные имена и типы результата, а поведение обязано быть одинаковым —
маска параметров, снимок имени сервера, пара ``started`` → финал у длинных
операций (§16.3), запись причины отказа при исключении. Разъехавшись, эти
детали дают дыры, которые в истории не отличить от «ничего не делали».

Инвариант 4a сохраняется: аудит не имеет права сломать операцию. Ошибка
записи гасится внутри ``audit.record`` и печатается в stdout.
"""
from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, Mapping, Optional

from core import audit
from core.audit_actions import AuditAction, AuditResult

ParamsBuilder = Callable[[dict], dict]


def _bound(func: Callable, args: tuple, kwargs: dict) -> dict:
    """Аргументы вызова по именам, вместе с умолчаниями.

    Умолчания нужны: ``ssh_install_key(server_id, public_key)`` и
    ``ssh_install_key(server_id, public_key, switch_to_key=True)`` — это
    одно действие с разными параметрами, и в истории они должны читаться
    одинаково. Ошибка связывания (нештатный вызов) не должна мешать
    операции: параметры тогда просто не пишутся.
    """
    try:
        bound = inspect.signature(func).bind(*args, **kwargs)
        bound.apply_defaults()
        return dict(bound.arguments)
    except (TypeError, ValueError):
        return {}


def _server_snapshot(server_id: Any) -> tuple[Optional[str], Optional[str]]:
    """(id, имя) снимком. Имя приходит из servers.json на момент действия.

    Best-effort: недоступное хранилище серверов — не повод не записать
    действие, но и выдумывать имя нельзя (§6: снимок, а не ссылка; имя
    читается в истории после удаления сервера).
    """
    if not server_id:
        return None, None
    try:
        from core.storage import find_server

        server = find_server(str(server_id))
    except Exception:
        return str(server_id), None
    if not server:
        return str(server_id), None
    return str(server.get("id") or server_id), server.get("name")


def _error_text(result: Any, error: Any) -> Optional[str]:
    """Причина отказа: код операции, если он есть, иначе её сообщение."""
    for value in (error, getattr(result, "message", None)):
        if value:
            return str(value)
    if isinstance(result, dict):
        for key in ("error", "message"):
            if result.get(key):
                return str(result[key])
    return None


def _outcome(result: Any) -> tuple[AuditResult, Optional[str], Optional[str]]:
    """Итог по возвращённому значению и безопасная причина отказа.

    Quick Setup отдаёт ``OpResult``, часть входов — dict с ``ok`` (принятие
    host key), остальное означает лишь «не бросил исключения» — про такое
    значение больше ничего не известно, и врать в аудите нечем.

    Пояснение успешной операции («порт уже открыт», «все пакеты уже
    установлены») причиной отказа НЕ является: колонка ``error`` у неё
    остаётся пустой. Иначе фильтр «записи с ошибкой» показывал бы успешные
    нажатия как неудачи, а искать настоящие отказы стало бы дороже.
    """
    ok = getattr(result, "ok", None)
    if ok is None and isinstance(result, dict):
        ok = result.get("ok", True)
    if ok is None:
        ok = True
    if ok:
        return AuditResult.OK, None, None
    detail = getattr(result, "details", None)
    reason = detail.get("reason") if isinstance(detail, Mapping) else None
    failure_detail = reason if isinstance(reason, str) and reason.strip() else None
    return (
        AuditResult.FAILED,
        _error_text(result, getattr(result, "error", None)),
        failure_detail,
    )


def audited(
    action: AuditAction,
    *,
    params: Optional[ParamsBuilder] = None,
    paired: bool = False,
):
    """Обернуть операцию QS записью аудита.

    ``params`` — сборщик параметров из связанных аргументов (см. ``_bound``);
    секретов в нём быть не должно (§13): пароли и приватные ключи не
    передаются сюда вовсе, а не «прячутся» маской.

    ``paired`` — длинная операция (§16.3): установка пакета, смена
    конфигурации sshd или переход firewall между backend'ами. Пара
    ``started`` → финал связана ``op_id`` и даёт таймлайну длительность;
    у одношаговых действий (открыть порт, переключить jail) финал пишется
    один — «начал» у них неотличимо от «сделал».
    """

    def decorate(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            arguments = _bound(func, args, kwargs)
            server_id = arguments.get("server_id") or (args[0] if args else None)
            server_key, server_name = _server_snapshot(server_id)
            values: Optional[dict] = None
            if params is not None:
                try:
                    values = params(arguments)
                except Exception as exc:  # сбор параметров не ломает операцию
                    print(f"[AUDIT] параметры операции не собраны: {exc}", flush=True)
            op_id = audit.new_op_id() if paired else None
            metric_session = None
            try:
                from core.operation_metrics import begin, new_operation_id, quick_setup_identity

                candidate_id = op_id or new_operation_id()
                identity = quick_setup_identity(
                    action,
                    operation_id=candidate_id,
                    server_id=server_key,
                    server_name=server_name,
                )
                if identity is not None:
                    op_id = candidate_id
                    metric_session = begin(identity)
            except Exception:
                print("[OPERATION METRICS] Quick Setup session unavailable", flush=True)
            try:
                if paired:
                    audit.record(
                        action,
                        result=AuditResult.STARTED,
                        server_id=server_key,
                        server_name=server_name,
                        op_id=op_id,
                        params=values,
                    )
                if metric_session is not None:
                    metric_session.start()
                result = func(*args, **kwargs)
            except BaseException as exc:
                audit.record(
                    action,
                    result=AuditResult.FAILED,
                    server_id=server_key,
                    server_name=server_name,
                    op_id=op_id,
                    params=values,
                    error=f"{type(exc).__name__}: {exc}",
                )
                raise
            else:
                outcome, error, failure_detail = _outcome(result)
                audit.record(
                    action,
                    result=outcome,
                    server_id=server_key,
                    server_name=server_name,
                    op_id=op_id,
                    params=values,
                    error=error,
                    failure_detail=failure_detail,
                )
                return result
            finally:
                if metric_session is not None:
                    metric_session.stop()
                    metric_session.close()

        return wrapper

    return decorate
