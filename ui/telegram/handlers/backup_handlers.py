"""Compact Telegram client for the existing BackupManager workflows."""
from __future__ import annotations

import asyncio
import math
import secrets
import time
from typing import Any
from uuid import uuid4

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest

from core.backup.errors import BackupError, ErrorCode
from core.backup.manager import BackupManager
from core.backup.time_utils import local_timezone, parse_utc_timestamp
from core.config import get_backup_config
from core.event_types import EventReason
from core.events import get_events
from core.storage import find_server, load_servers
from state import BACKUP_CB_TOKENS, BACKUP_STATE, BACKUP_WATCHERS
from ui.telegram.backup_runtime import WEB_INSTALL_URL, web_ui_available
from ui.telegram.notifications import format_event_text

_TOKEN_TTL_SECONDS = 20 * 60
_CATALOG_PAGE_SIZE = 7
_POLL_SECONDS = 1.25
_EDIT_THROTTLE_SECONDS = 2.0
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_RESULT_TOKEN_KIND = "result_navigation"
_RESULT_REASONS = {
    EventReason.BACKUP_COMPLETED.value,
    EventReason.BACKUP_FAILED.value,
    EventReason.BACKUP_CANCELLED.value,
    EventReason.RESTORE_COMPLETED.value,
    EventReason.RESTORE_FAILED.value,
    EventReason.RESTORE_CANCELLED.value,
}
_ENTRY_POINTS = {"main_backup_menu", "server_card", "tasks_menu"}

_STAGE_LABELS = {
    "validate_request": "Проверка запроса",
    "preflight": "Предварительная проверка",
    "streaming_source": "Получение данных",
    "inspecting_streamed_sources": "Проверка источников",
    "repackaging_archive": "Формирование архива",
    "scanning_sources": "Проверка источников",
    "creating_archive": "Формирование архива",
    "verifying_staging": "Проверка архива",
    "publishing_artifact": "Сохранение резервной копии",
    "reading_target": "Проверка сервера",
    "process_preflight": "Проверка активных процессов",
    "protective_backup": "Создание защитной копии",
    "uploading_archive": "Передача архива",
    "applying": "Распаковка",
    "post_restore_verify": "Проверка результата",
    "prepared": "Подготовка завершена",
    "applied": "Проверка результата",
    "cancelled": "Отмена",
    "failed": "Завершение",
    "completed": "Завершение",
}


def _new_manager() -> BackupManager:
    return BackupManager(get_backup_config())


async def _manager() -> BackupManager:
    return await asyncio.to_thread(_new_manager)


def _token_alive(item: Any, now: float) -> bool:
    if not isinstance(item, dict):
        return False
    expires_at = item.get("expires_at")
    return bool(
        isinstance(expires_at, (int, float))
        and not isinstance(expires_at, bool)
        and math.isfinite(expires_at)
        and expires_at > now
    )


def _prune_tokens(user_id: int) -> None:
    now = time.monotonic()
    tokens = BACKUP_CB_TOKENS.get(user_id) or {}
    alive = {
        token: item
        for token, item in tokens.items()
        if _token_alive(item, now)
    }
    if alive:
        BACKUP_CB_TOKENS[user_id] = alive
    else:
        BACKUP_CB_TOKENS.pop(user_id, None)


def _mint_token(
    user_id: int,
    kind: str,
    value: Any,
    *,
    generation: int | None = None,
) -> str:
    """Mint a short user-scoped callback token without exposing identifiers."""
    _prune_tokens(user_id)
    token = secrets.token_urlsafe(8)
    while token in (BACKUP_CB_TOKENS.get(user_id) or {}):
        token = secrets.token_urlsafe(8)
    BACKUP_CB_TOKENS.setdefault(user_id, {})[token] = {
        "kind": kind,
        "value": value,
        "generation": generation,
        "expires_at": time.monotonic() + _TOKEN_TTL_SECONDS,
    }
    return token


def _resolve_token(
    user_id: int,
    token: str,
    kind: str,
    *,
    generation: int | None = None,
) -> Any | None:
    _prune_tokens(user_id)
    item = (BACKUP_CB_TOKENS.get(user_id) or {}).get(token)
    if not isinstance(item, dict) or item.get("kind") != kind:
        return None
    if generation is not None and item.get("generation") != generation:
        return None
    return item.get("value")


def _preserve_result_tokens(user_id: int) -> None:
    """Drop screen-bound callbacks without invalidating delivered result links."""
    _prune_tokens(user_id)
    tokens = BACKUP_CB_TOKENS.get(user_id) or {}
    preserved = {
        token: item
        for token, item in tokens.items()
        if item.get("kind") == _RESULT_TOKEN_KIND
    }
    if preserved:
        BACKUP_CB_TOKENS[user_id] = preserved
    else:
        BACKUP_CB_TOKENS.pop(user_id, None)


def _callback(action: str, token: str) -> str:
    value = f"bk:{action}:{token}"
    if len(value.encode("utf-8")) > 64:
        raise ValueError("Telegram Backup callback exceeds 64 bytes")
    return value


def backup_entry_callback(user_id: int, server_id: str) -> str:
    """Return an opaque service-card entry callback for one server."""
    token = _mint_token(user_id, "entry_server", str(server_id))
    return _callback("o", token)


def _result_navigation_callback(
    user_id: int,
    notification: dict,
    action: str,
) -> str | None:
    details = notification.get("details") or notification.get("data") or {}
    if (
        not isinstance(details, dict)
        or details.get("initiated_from_telegram") is not True
        or details.get("reason") not in _RESULT_REASONS
    ):
        return None

    operation_id = details.get("operation_id")
    target = details.get("target") or {}
    server_id = details.get("server_id") or (
        target.get("server_id") if isinstance(target, dict) else None
    )
    if not isinstance(operation_id, str) or not operation_id:
        return None
    if not isinstance(server_id, str) or not server_id:
        return None

    entry_point = "main_backup_menu"
    state = BACKUP_STATE.get(user_id)
    if (
        isinstance(state, dict)
        and state.get("server_id") == server_id
        and operation_id in {
            state.get("active_operation_id"),
            state.get("terminal_operation_id"),
        }
        and state.get("entry_point") in _ENTRY_POINTS
    ):
        entry_point = str(state["entry_point"])

    token = _mint_token(
        user_id,
        _RESULT_TOKEN_KIND,
        {
            "operation_id": operation_id,
            "server_id": server_id,
            "entry_point": entry_point,
        },
    )
    return _callback(action, token)


def backup_result_callback(user_id: int, notification: dict) -> str | None:
    """Return an opaque context-aware Back callback for a Telegram result."""
    return _result_navigation_callback(user_id, notification, "v")


def backup_result_reboot_callback(user_id: int, notification: dict) -> str | None:
    """Return an opaque reboot callback for a Telegram Restore result."""
    details = notification.get("details") or notification.get("data") or {}
    if not isinstance(details, dict) or details.get("reason") not in {
        EventReason.RESTORE_COMPLETED.value,
        EventReason.RESTORE_FAILED.value,
    }:
        return None
    return _result_navigation_callback(user_id, notification, "q")


def _terminal_keyboard(user_id: int, notification: dict) -> InlineKeyboardMarkup | None:
    """Build the compact keyboard for a watcher-owned terminal report."""
    back_callback = backup_result_callback(user_id, notification)
    if not back_callback:
        return None
    rows = []
    reboot_callback = backup_result_reboot_callback(user_id, notification)
    if reboot_callback:
        rows.append([
            InlineKeyboardButton(
                "↻ Перезагрузить сервер",
                callback_data=reboot_callback,
            )
        ])
    rows.append([
        InlineKeyboardButton("⬅️ Назад", callback_data=back_callback),
    ])
    return InlineKeyboardMarkup(rows)


def _journal_event_for_operation(operation_id: str) -> dict | None:
    """Find the terminal journal event without creating a delivery attempt."""
    if not operation_id:
        return None
    try:
        events = get_events(limit=200)
    except Exception:
        return None
    for event in events:
        if not isinstance(event, dict):
            continue
        details = event.get("details") or {}
        if isinstance(details, dict) and details.get("operation_id") == operation_id:
            return event
    return None


def _fallback_terminal_notification(
    state: dict,
    operation: dict,
    active_kind: str,
) -> dict:
    """Build a report if the journal write briefly trails Operation history."""
    status = str(operation.get("status") or "")
    cancelled = status == "cancelled"
    success = status == "completed"
    if active_kind == "create":
        if cancelled:
            reason = EventReason.BACKUP_CANCELLED.value
            title = "Резервная копия отменена"
            message = "Создание резервной копии отменено."
        else:
            reason = (
                EventReason.BACKUP_COMPLETED.value
                if success
                else EventReason.BACKUP_FAILED.value
            )
            title = "Backup завершён" if success else "Backup завершился с ошибкой"
            message = (
                "Backup опубликован успешно."
                if success
                else str((operation.get("error") or {}).get("message") or "Не удалось создать backup.")
            )
        target = operation.get("target") or {}
        details = {
            "reason": reason,
            "operation_id": operation.get("operation_id"),
            "target": target,
            "backup_id": operation.get("result_backup_id"),
            "backup_filename": None,
            "backup_bytes": (operation.get("progress") or {}).get("archive_bytes"),
            "server_name": _server_name(target.get("server_id")),
            "mode": operation.get("mode"),
            "initiated_from_telegram": True,
        }
    else:
        if cancelled:
            reason = EventReason.RESTORE_CANCELLED.value
            title = "Восстановление отменено"
            message = "Восстановление отменено пользователем."
        else:
            reason = (
                EventReason.RESTORE_COMPLETED.value
                if success
                else EventReason.RESTORE_FAILED.value
            )
            title = "Восстановление завершено" if success else "Восстановление завершилось с ошибкой"
            message = (
                "Данные из backup записаны на сервер, результат проверен."
                if success
                else str((operation.get("error") or {}).get("message") or "Не удалось выполнить восстановление.")
            )
        target = operation.get("target") or {}
        server_id = target.get("server_id")
        details = {
            "reason": reason,
            "operation_id": operation.get("operation_id"),
            "target": target,
            "server_name": _server_name(server_id),
            "server_id": server_id,
            "backup_filename": state.get("backup_name"),
            # Telegram currently exposes the merge/full-restore flow only.
            "mode": "merge",
            "mutation_started": bool((operation.get("restore") or {}).get("mutation_started")),
            "protective_backup": None,
            "initiated_from_telegram": True,
        }
    error = operation.get("error")
    if isinstance(error, dict):
        details["error"] = dict(error)
    level = "critical" if (
        not success
        and not cancelled
        and bool(details.get("mutation_started"))
    ) else ("info" if success else "warning")
    return {
        "type": "backup",
        "level": level,
        "title": title,
        "message": message,
        "details": details,
    }


async def _terminal_notification(
    state: dict,
    operation: dict,
    active_kind: str,
    manager: BackupManager,
) -> dict:
    """Return canonical terminal event data for the existing progress message."""
    operation_id = str(operation.get("operation_id") or "")
    event = await asyncio.to_thread(_journal_event_for_operation, operation_id)
    if isinstance(event, dict):
        return {
            "type": event.get("type", "backup"),
            "level": event.get("level", "warning"),
            "title": event.get("title", "Событие"),
            "message": event.get("message", ""),
            "details": dict(event.get("details") or {}),
        }

    notification = _fallback_terminal_notification(state, operation, active_kind)
    details = notification["details"]
    if active_kind == "create":
        target = operation.get("target") or {}
        backup_id = operation.get("result_backup_id")
        if isinstance(backup_id, str) and backup_id:
            try:
                record = await asyncio.to_thread(
                    manager.get_catalog_record,
                    backup_id,
                    server_id=target.get("server_id"),
                )
            except Exception:
                record = None
            if isinstance(record, dict):
                details["backup_filename"] = record.get("filename")
                archive = record.get("archive") or {}
                details["backup_bytes"] = archive.get("bytes")
    return notification


def _replace_state(user_id: int, *, entry_point: str, server_id: str | None) -> dict:
    _preserve_result_tokens(user_id)
    state = {
        "entry_point": entry_point,
        "server_id": server_id,
        "phase": "server_picker" if server_id is None else "opening",
        "generation": 1,
        "backup_id": None,
        "backup_ref": None,
        "backup_name": None,
        "protective_backup": None,
        "prepared_operation_id": None,
        "active_operation_id": None,
        "terminal_operation_id": None,
        "active_kind": None,
        "request_id": None,
        "operation_token": None,
        "cancel_requested": False,
    }
    BACKUP_STATE[user_id] = state
    return state


def _set_phase(user_id: int, state: dict, phase: str) -> None:
    state["phase"] = phase
    state["generation"] = int(state.get("generation") or 0) + 1
    _preserve_result_tokens(user_id)


def _action_token(user_id: int, state: dict, action: str) -> str:
    token = _mint_token(
        user_id,
        "action",
        action,
        generation=int(state["generation"]),
    )
    return _callback(action, token)


def _valid_action(user_id: int, state: dict, token: str, action: str) -> bool:
    return _resolve_token(
        user_id,
        token,
        "action",
        generation=int(state.get("generation") or 0),
    ) == action


def _url_row() -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(
            "🌐 Web UI / инструкция установки",
            url=WEB_INSTALL_URL,
        )
    ]


def _web_unavailable_text() -> str:
    return (
        "💾 Работа с Backup\n\n"
        "Функция резервного копирования в Telegram недоступна, поскольку "
        "Web UI отключён.\n\n"
        "Полный функционал резервного копирования доступен в Web UI: импорт, "
        "расписание, выбор файлов для Backup, выборочное восстановление и "
        "настройка уведомлений.\n\n"
        "Для использования функции резервного копирования необходимо "
        "установить/использовать полную версию Bot4VPS с Web UI."
    )


async def _show_web_unavailable(query, user_id: int, state: dict) -> None:
    _set_phase(user_id, state, "web_unavailable")
    rows = [[
        InlineKeyboardButton(
            "⬅️ Назад",
            callback_data=_action_token(user_id, state, "x"),
        )
    ]]
    await query.edit_message_text(
        _web_unavailable_text(),
        reply_markup=InlineKeyboardMarkup(rows),
    )


def _human_bytes(value: Any) -> str:
    try:
        size = max(0, int(value))
    except (TypeError, ValueError):
        return "—"
    units = ("Б", "КБ", "МБ", "ГБ", "ТБ")
    number = float(size)
    unit = units[0]
    for candidate in units:
        unit = candidate
        if number < 1024 or candidate == units[-1]:
            break
        number /= 1024
    if unit == "Б":
        return f"{int(number)} {unit}"
    return f"{number:.2f} {unit}"


def _local_timestamp(value: Any) -> str:
    try:
        instant = parse_utc_timestamp(str(value)).astimezone(local_timezone())
    except (TypeError, ValueError, OSError):
        return "Дата неизвестна"
    return instant.strftime("%d.%m.%Y %H:%M")


def _server_name(server_id: str | None) -> str:
    server = find_server(server_id) if server_id else None
    return str((server or {}).get("name") or server_id or "—")


def _active_flow(user_id: int) -> bool:
    watcher = BACKUP_WATCHERS.get(user_id)
    state = BACKUP_STATE.get(user_id) or {}
    return bool(
        watcher is not None
        and not watcher.done()
        and state.get("active_operation_id")
    )


async def _stale_context(query, user_id: int) -> None:
    if _active_flow(user_id):
        try:
            await query.answer(
                "Эта кнопка больше не действует. Операция продолжает выполняться.",
                show_alert=True,
            )
        except Exception:
            pass
        return
    await query.edit_message_text(
        "⚠️ Контекст Backup устарел. Откройте раздел заново.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💾 Работа с Backup", callback_data="bk:entry")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main")],
        ]),
    )


async def _show_main_backup_entry(
    query,
    user_id: int,
    *,
    entry_point: str = "main_backup_menu",
) -> None:
    state = _replace_state(
        user_id,
        entry_point=entry_point,
        server_id=None,
    )
    _set_phase(user_id, state, "checking_web")
    await query.edit_message_text("⏳ Проверка доступности Web UI…")
    available = await web_ui_available()
    if BACKUP_STATE.get(user_id) is not state or state.get("phase") != "checking_web":
        return
    if not available:
        await _show_web_unavailable(query, user_id, state)
        return
    await _show_server_picker(query, user_id, reset=False)


async def _show_server_picker(query, user_id: int, *, reset: bool = True) -> None:
    if reset:
        state = _replace_state(
            user_id,
            entry_point="main_backup_menu",
            server_id=None,
        )
    else:
        state = BACKUP_STATE.get(user_id)
        if not state:
            state = _replace_state(
                user_id,
                entry_point="main_backup_menu",
                server_id=None,
            )
        else:
            _set_phase(user_id, state, "server_picker")
            state["server_id"] = None
    servers = await asyncio.to_thread(load_servers)
    rows = []
    server_buttons = []
    for server in servers:
        server_id = server.get("id") if isinstance(server, dict) else None
        if not isinstance(server_id, str) or not server_id:
            continue
        token = _mint_token(
            user_id,
            "server",
            server_id,
            generation=int(state["generation"]),
        )
        server_buttons.append(
            InlineKeyboardButton(
                str(server.get("name") or server_id),
                callback_data=_callback("s", token),
            )
        )
    rows.extend(
        server_buttons[index:index + 2]
        for index in range(0, len(server_buttons), 2)
    )
    back_callback = "tasks" if state.get("entry_point") == "tasks_menu" else "main"
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=back_callback)])
    text = "💾 Работа с Backup\n\nВыберите сервер:"
    if not rows[:-1]:
        text += "\n\nСерверы не добавлены."
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def _show_backup_menu(query, user_id: int, state: dict) -> None:
    server_id = state.get("server_id")
    server = await asyncio.to_thread(find_server, server_id)
    if not server:
        await _stale_context(query, user_id)
        return
    _set_phase(user_id, state, "checking_web")
    await query.edit_message_text("⏳ Проверка доступности Web UI…")
    available = await web_ui_available()
    if BACKUP_STATE.get(user_id) is not state or state.get("phase") != "checking_web":
        return
    _set_phase(user_id, state, "menu")
    name = str(server.get("name") or server_id)
    if available:
        text = (
            "💾 Работа с Backup\n"
            f"Сервер: {name}\n\n"
            "Функционал Telegram ограничен. Полный функционал доступен в Web UI: "
            "импорт, расписание, выбор файлов для Backup, выборочное восстановление "
            "и настройка уведомлений."
        )
        rows = [
            [InlineKeyboardButton(
                "➕ Создать резервную копию",
                callback_data=_action_token(user_id, state, "c"),
            )],
            [InlineKeyboardButton(
                "♻️ Восстановить из резервной копии",
                callback_data=_action_token(user_id, state, "r"),
            )],
            [InlineKeyboardButton(
                "⬅️ Назад",
                callback_data=_action_token(user_id, state, "x"),
            )],
        ]
    else:
        await _show_web_unavailable(query, user_id, state)
        return
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def _exit_flow(query, user_id: int, state: dict) -> None:
    entry_point = state.get("entry_point")
    if entry_point == "server_card":
        server_id = state.get("server_id")
        if not await asyncio.to_thread(find_server, server_id):
            await _stale_context(query, user_id)
            return
        from .service_handlers import _services_hub

        await _services_hub(query, str(server_id))
        return
    if entry_point == "tasks_menu":
        from ui.telegram.task_ui import show_tasks_menu

        await show_tasks_menu(query)
        return
    await _show_server_picker(query, user_id, reset=False)


def _safe_error_text(exc: BaseException, *, action: str) -> str:
    if isinstance(exc, BackupError):
        reason = exc.safe_message
    else:
        reason = "Внутренняя ошибка Backup. Повторите попытку позже."
    return f"❌ {action}\n\nПричина: {reason}"


async def _show_operation_error(
    query,
    user_id: int,
    state: dict,
    exc: BaseException,
    *,
    action: str,
) -> None:
    _set_phase(user_id, state, "operation_error")
    rows = []
    if isinstance(exc, BackupError) and exc.code == ErrorCode.PROFILE_NO_SOURCES.value:
        text = (
            "⚠️ Для этого сервера не настроены источники резервного копирования.\n"
            "Настройте резервное копирование в Web UI."
        )
        rows = []
    else:
        text = _safe_error_text(exc, action=action)
    rows.append([
        InlineKeyboardButton(
            "⬅️ Назад",
            callback_data=_action_token(user_id, state, "m"),
        )
    ])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))


def _progress_bar(percent: Any) -> tuple[str, int]:
    try:
        normalized = min(100, max(0, int(float(percent))))
    except (TypeError, ValueError):
        normalized = 0
    filled = min(10, normalized // 10)
    return "█" * filled + "░" * (10 - filled), normalized


def _operation_can_cancel(operation: dict) -> bool:
    cancellation = operation.get("cancellation") or {}
    restore = operation.get("restore") or {}
    return bool(
        cancellation.get("allowed") is True
        and not cancellation.get("requested")
        and not restore.get("mutation_started")
        and operation.get("status") not in _TERMINAL_STATUSES
    )


def _progress_view(
    user_id: int,
    state: dict,
    operation: dict,
    *,
    allow_cancel: bool = True,
) -> tuple[str, InlineKeyboardMarkup | None]:
    progress = operation.get("progress") or {}
    bar, percent = _progress_bar(progress.get("percent"))
    title = (
        "💾 Создание резервной копии"
        if state.get("active_kind") == "create"
        else "♻️ Восстановление"
    )
    lines = [title, "", f"{bar} {percent}%"]
    processed = progress.get("processed_bytes")
    total = progress.get("estimated_total_bytes")
    if (
        isinstance(processed, int)
        and not isinstance(processed, bool)
        and isinstance(total, int)
        and not isinstance(total, bool)
        and total > 0
    ):
        lines.append(f"Размер: {_human_bytes(processed)} / {_human_bytes(total)}")
    stage = str(operation.get("stage") or "validate_request")
    lines.append(f"Этап: {_STAGE_LABELS.get(stage, 'Выполнение операции')}")
    if (operation.get("cancellation") or {}).get("requested") or state.get("cancel_requested"):
        lines.extend(("", "Запрос отмены принят. Ожидание безопасной остановки…"))
    elif state.get("cancel_notice"):
        lines.extend(("", str(state["cancel_notice"])))
    keyboard = None
    if allow_cancel and _operation_can_cancel(operation):
        token = state.get("operation_token")
        if token:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "❌ Отменить",
                    callback_data=_callback("k", str(token)),
                )
            ]])
    return "\n".join(lines), keyboard


async def _edit_message(message, text: str, keyboard) -> bool:
    try:
        await message.edit_text(text, reply_markup=keyboard)
        return True
    except BadRequest as exc:
        if "not modified" in str(exc).lower():
            return True
        return False
    except Exception:
        return False


def _bind_operation(user_id: int, state: dict, operation: dict, kind: str) -> None:
    _set_phase(user_id, state, f"{kind}_running")
    operation_id = str(operation["operation_id"])
    state["active_operation_id"] = operation_id
    state["terminal_operation_id"] = None
    state["active_kind"] = kind
    state["cancel_requested"] = False
    state.pop("cancel_notice", None)
    state["operation_token"] = _mint_token(
        user_id,
        "operation",
        operation_id,
        generation=int(state["generation"]),
    )


async def _show_prepared(message, user_id: int, state: dict, operation: dict) -> None:
    state["active_operation_id"] = None
    state["operation_token"] = None
    state["prepared_operation_id"] = operation.get("operation_id")
    protective = bool(state.get("protective_backup"))
    _set_phase(
        user_id,
        state,
        "confirm_apply" if protective else "confirm_without_protective",
    )
    server_name = _server_name(state.get("server_id"))
    backup_name = str(state.get("backup_name") or "выбранный backup")
    if protective:
        text = (
            "♻️ Восстановление подготовлено\n\n"
            f"Сервер: {server_name}\n"
            f"Backup: {backup_name}\n\n"
            "Защитная копия обработана, данные сервера ещё не изменялись.\n"
            "Подтвердите полное восстановление."
        )
        label = "✅ Начать восстановление"
    else:
        text = (
            "⚠️ Восстановление без защитной копии\n\n"
            f"Сервер: {server_name}\n"
            f"Backup: {backup_name}\n\n"
            "Защитная копия не создавалась. Это отдельное окончательное "
            "подтверждение восстановления без возможности возврата через неё."
        )
        label = "⚠️ Восстановить без защитной копии"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            label,
            callback_data=_action_token(user_id, state, "a"),
        )],
        [InlineKeyboardButton(
            "⬅️ Назад",
            callback_data=_action_token(user_id, state, "m"),
        )],
    ])
    await _edit_message(message, text, keyboard)


async def _watch_operation(
    user_id: int,
    state: dict,
    manager: BackupManager,
    message,
) -> None:
    operation_id = str(state.get("active_operation_id") or "")
    active_kind = str(state.get("active_kind") or "")
    last_text = None
    last_stage = None
    last_cancel = None
    last_edit_at = 0.0
    not_found_count = 0
    can_edit = True
    current_task = asyncio.current_task()
    try:
        while operation_id:
            try:
                operation = await asyncio.to_thread(manager.get_operation, operation_id)
                not_found_count = 0
            except BackupError as exc:
                if exc.code == ErrorCode.OPERATION_NOT_FOUND.value and not_found_count < 3:
                    not_found_count += 1
                    await asyncio.sleep(_POLL_SECONDS)
                    continue
                break
            except Exception:
                break

            if BACKUP_STATE.get(user_id) is not state:
                break
            if str(state.get("active_operation_id") or "") != operation_id:
                break

            status = str(operation.get("status") or "")
            stage = str(operation.get("stage") or "")
            terminal = status in _TERMINAL_STATUSES
            text, keyboard = _progress_view(
                user_id,
                state,
                operation,
                allow_cancel=not terminal,
            )

            if terminal:
                if (
                    active_kind == "prepare"
                    and status == "completed"
                    and stage == "prepared"
                    and can_edit
                ):
                    await _show_prepared(message, user_id, state, operation)
                else:
                    state["terminal_operation_id"] = operation_id
                    state["active_operation_id"] = None
                    state["operation_token"] = None
                    _set_phase(user_id, state, "terminal")
                    if can_edit:
                        notification = await _terminal_notification(
                            state,
                            operation,
                            active_kind,
                            manager,
                        )
                        await _edit_message(
                            message,
                            format_event_text(notification),
                            _terminal_keyboard(user_id, notification),
                        )
                break

            cancel_visible = keyboard is not None
            now = time.monotonic()
            visible_change = stage != last_stage or cancel_visible != last_cancel
            if can_edit and (
                visible_change
                or last_text is None
                or (text != last_text and now - last_edit_at >= _EDIT_THROTTLE_SECONDS)
            ):
                can_edit = await _edit_message(message, text, keyboard)
                last_text = text
                last_stage = stage
                last_cancel = cancel_visible
                last_edit_at = now

            await asyncio.sleep(_POLL_SECONDS)
    finally:
        if BACKUP_WATCHERS.get(user_id) is current_task:
            BACKUP_WATCHERS.pop(user_id, None)


def _start_watcher(
    user_id: int,
    state: dict,
    manager: BackupManager,
    message,
) -> None:
    existing = BACKUP_WATCHERS.get(user_id)
    if existing is not None and not existing.done():
        return
    task = asyncio.create_task(_watch_operation(user_id, state, manager, message))
    BACKUP_WATCHERS[user_id] = task


async def _start_create(query, user_id: int, state: dict) -> None:
    if state.get("phase") != "menu":
        await _stale_context(query, user_id)
        return
    _set_phase(user_id, state, "create_submitting")
    request_id = f"tg-create-{uuid4().hex}"
    state["request_id"] = request_id
    await query.edit_message_text("⏳ Регистрация операции Backup…")
    try:
        manager = await _manager()
        operation = await asyncio.to_thread(
            manager.submit_create,
            server_id=str(state["server_id"]),
            request_id=request_id,
            initiated_from_telegram=True,
        )
    except Exception as exc:
        await _show_operation_error(
            query,
            user_id,
            state,
            exc,
            action="Не удалось запустить создание резервной копии",
        )
        return
    _bind_operation(user_id, state, operation, "create")
    text, keyboard = _progress_view(user_id, state, operation)
    await query.edit_message_text(text, reply_markup=keyboard)
    _start_watcher(user_id, state, manager, query.message)


def _managed_server_records(records: Any, server_id: str) -> list[dict]:
    if not isinstance(records, list):
        return []
    return [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("type") == "server"
        and (record.get("source") or {}).get("server_id") == server_id
    ]


def _imported_server_records(records: Any, server_id: str) -> list[dict]:
    """Normalize published imports for the selected server UI namespace."""
    if not isinstance(records, list):
        return []
    normalized = []
    for record in records:
        if not isinstance(record, dict):
            continue
        entry_key = record.get("entry_key")
        destination = record.get("destination") or {}
        if (
            not isinstance(entry_key, str)
            or not entry_key
            or not isinstance(destination, dict)
            or destination.get("scope") != "server"
            or destination.get("server_id") != server_id
        ):
            continue
        normalized.append(record)
    return normalized


def _catalog_sort_key(record: dict) -> tuple[str, str]:
    return (
        str(record.get("created_at") or record.get("imported_at") or ""),
        str(record.get("backup_id") or record.get("entry_key") or ""),
    )


def _backup_ref_from_record(record: dict, server_id: str) -> dict | None:
    """Build an internal typed reference; never serialize it into callback data."""
    if record.get("_telegram_kind") == "imported":
        entry_key = record.get("entry_key")
        if not isinstance(entry_key, str) or not entry_key:
            return None
        return {
            "kind": "imported",
            "entry_key": entry_key,
            "server_id": server_id,
            "filename": record.get("filename"),
        }
    backup_id = record.get("backup_id")
    if not isinstance(backup_id, str) or not backup_id:
        return None
    return {
        "kind": "managed",
        "backup_id": backup_id,
        "server_id": server_id,
        "filename": record.get("filename"),
    }


async def _show_catalog(query, user_id: int, state: dict, page: int = 0) -> None:
    _set_phase(user_id, state, "catalog_loading")
    await query.edit_message_text("⏳ Загрузка списка резервных копий…")
    server_id = str(state["server_id"])
    try:
        manager = await _manager()
        managed, imported = await asyncio.gather(
            asyncio.to_thread(manager.list_catalog, server_id=server_id),
            asyncio.to_thread(manager.list_imported_archives, server_id=server_id),
        )
        managed_records = _managed_server_records(managed, server_id)
        imported_records = _imported_server_records(imported, server_id)
        records = [
            dict(record, _telegram_kind="managed")
            for record in managed_records
        ] + [
            dict(record, _telegram_kind="imported")
            for record in imported_records
        ]
        records.sort(key=_catalog_sort_key, reverse=True)
    except Exception as exc:
        await _show_operation_error(
            query,
            user_id,
            state,
            exc,
            action="Не удалось получить список резервных копий",
        )
        return

    total_pages = max(1, (len(records) + _CATALOG_PAGE_SIZE - 1) // _CATALOG_PAGE_SIZE)
    page = min(max(0, int(page)), total_pages - 1)
    _set_phase(user_id, state, "catalog")
    state["catalog_page"] = page
    rows = []
    start = page * _CATALOG_PAGE_SIZE
    for record in records[start:start + _CATALOG_PAGE_SIZE]:
        backup_ref = _backup_ref_from_record(record, server_id)
        if backup_ref is None:
            continue
        token = _mint_token(
            user_id,
            "backup",
            backup_ref,
            generation=int(state["generation"]),
        )
        archive = record.get("archive") or {}
        filename = str(record.get("filename") or "backup")
        if filename.lower().endswith(".tar.gz"):
            filename = filename[:-7]
        if len(filename) > 28:
            filename = filename[:27] + "…"
        marker = "📥 Imported" if backup_ref["kind"] == "imported" else "💾 Managed"
        label = (
            f"{marker} · {_local_timestamp(record.get('created_at') or record.get('imported_at'))} · "
            f"{_human_bytes(archive.get('bytes') or record.get('bytes'))} · {filename}"
        )
        rows.append([
            InlineKeyboardButton(label, callback_data=_callback("b", token))
        ])
    navigation = []
    if page > 0:
        token = _mint_token(
            user_id,
            "page",
            page - 1,
            generation=int(state["generation"]),
        )
        navigation.append(InlineKeyboardButton("◀️", callback_data=_callback("p", token)))
    if page + 1 < total_pages:
        token = _mint_token(
            user_id,
            "page",
            page + 1,
            generation=int(state["generation"]),
        )
        navigation.append(InlineKeyboardButton("▶️", callback_data=_callback("p", token)))
    if navigation:
        rows.append(navigation)
    rows.append([
        InlineKeyboardButton(
            "⬅️ Назад",
            callback_data=_action_token(user_id, state, "m"),
        )
    ])
    text = "♻️ Выберите резервную копию"
    if not records:
        text += "\n\nДля этого сервера нет доступных резервных копий."
    elif total_pages > 1:
        text += f"\n\nСтраница {page + 1} из {total_pages}"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))
def _full_restore_unavailable(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    policy = result.get("policy") or {}
    return bool(
        result.get("full_restore_unavailable") is True
        or policy.get("reason") == "full_restore_unavailable"
    )


async def _show_full_restore_block(query, user_id: int, state: dict) -> None:
    _set_phase(user_id, state, "full_restore_unavailable")
    text = (
        "⚠️ Восстановление через Telegram невозможно\n\n"
        "В выбранном backup обнаружены файлы, которые нельзя изменять при "
        "онлайн-восстановлении, поскольку они используются системой.\n\n"
        "Для выборочного восстановления воспользуйтесь Web UI."
    )
    rows = [
        _url_row(),
        [InlineKeyboardButton(
            "⬅️ Назад",
            callback_data=_action_token(user_id, state, "r"),
        )],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def _select_backup(
    query,
    user_id: int,
    state: dict,
    backup_ref: dict | str,
) -> None:
    """Plan a full restore for either a managed or imported archive."""
    if isinstance(backup_ref, str):
        # Compatibility for callers that still pass a managed backup id.
        backup_ref = {
            "kind": "managed",
            "backup_id": backup_ref,
            "server_id": state.get("server_id"),
        }
    if not isinstance(backup_ref, dict):
        await _stale_context(query, user_id)
        return
    kind = backup_ref.get("kind")
    server_id = str(state.get("server_id") or "")
    if backup_ref.get("server_id") != server_id or kind not in {"managed", "imported"}:
        await _stale_context(query, user_id)
        return
    if kind == "managed":
        backup_id = backup_ref.get("backup_id")
        if not isinstance(backup_id, str) or not backup_id:
            await _stale_context(query, user_id)
            return
    else:
        entry_key = backup_ref.get("entry_key")
        if not isinstance(entry_key, str) or not entry_key:
            await _stale_context(query, user_id)
            return

    _set_phase(user_id, state, "planning")
    state["backup_ref"] = dict(backup_ref)
    state["backup_id"] = backup_ref.get("backup_id") if kind == "managed" else None
    await query.edit_message_text("⏳ Проверка возможности полного восстановления…")
    try:
        manager = await _manager()
        if kind == "managed":
            record = await asyncio.to_thread(
                manager.get_catalog_record,
                backup_id,
                server_id=server_id,
            )
            if (
                record.get("type") != "server"
                or (record.get("source") or {}).get("server_id") != server_id
            ):
                raise BackupError(
                    ErrorCode.ARTIFACT_NOT_FOUND,
                    "Резервная копия выбранного сервера не найдена",
                )
            plan = await asyncio.to_thread(
                manager.plan_restore,
                backup_id,
                server_id=server_id,
                selection_mode="full",
                selected_paths=[],
                include_directory_tree=False,
            )
        else:
            record = dict(backup_ref)
            plan = await asyncio.to_thread(
                manager.plan_imported_restore,
                entry_key,
                server_id=server_id,
                selection_mode="full",
                selected_paths=[],
                include_directory_tree=False,
            )
    except BackupError as exc:
        if (
            exc.details.get("full_restore_unavailable") is True
            or exc.details.get("reason") == "full_restore_unavailable"
        ):
            await _show_full_restore_block(query, user_id, state)
            return
        await _show_operation_error(
            query,
            user_id,
            state,
            exc,
            action="Не удалось проверить резервную копию",
        )
        return
    except Exception as exc:
        await _show_operation_error(
            query,
            user_id,
            state,
            exc,
            action="Не удалось проверить резервную копию",
        )
        return
    if _full_restore_unavailable(plan):
        await _show_full_restore_block(query, user_id, state)
        return

    filename = str(record.get("filename") or (
        backup_id if kind == "managed" else entry_key
    ))
    if filename.lower().endswith(".tar.gz"):
        filename = filename[:-7]
    state["backup_name"] = filename
    _set_phase(user_id, state, "protective_choice")
    text = (
        "♻️ Полное восстановление\n\n"
        f"Сервер: {_server_name(state.get('server_id'))}\n"
        f"Backup: {filename}\n\n"
        "Сделать backup перед восстановлением?\n\n"
        "Да — будет создан обычный backup только затрагиваемых данных. "
        "Прежняя защитная копия с таким именем заменяется.\n\n"
        "Нет — подготовка продолжится без защитной копии; перед применением "
        "потребуется отдельное подтверждение."
    )
    rows = [[
        InlineKeyboardButton(
            "✅ Да",
            callback_data=_action_token(user_id, state, "y"),
        ),
        InlineKeyboardButton(
            "❌ Нет",
            callback_data=_action_token(user_id, state, "n"),
        ),
    ], [
        InlineKeyboardButton(
            "⬅️ Назад",
            callback_data=_action_token(user_id, state, "r"),
        )
    ]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def _start_prepare(
    query,
    user_id: int,
    state: dict,
    *,
    protective: bool,
) -> None:
    if state.get("phase") != "protective_choice":
        await _stale_context(query, user_id)
        return
    backup_ref = state.get("backup_ref")
    if not isinstance(backup_ref, dict):
        backup_id = state.get("backup_id")
        if isinstance(backup_id, str) and backup_id:
            backup_ref = {
                "kind": "managed",
                "backup_id": backup_id,
                "server_id": state.get("server_id"),
            }
        else:
            await _stale_context(query, user_id)
            return
    kind = backup_ref.get("kind")
    server_id = str(state.get("server_id") or "")
    if backup_ref.get("server_id") != server_id:
        await _stale_context(query, user_id)
        return
    _set_phase(user_id, state, "prepare_submitting")
    state["protective_backup"] = bool(protective)
    request_id = f"tg-restore-prepare-{uuid4().hex}"
    state["request_id"] = request_id
    await query.edit_message_text("⏳ Регистрация подготовки восстановления…")
    try:
        manager = await _manager()
        common = dict(
            server_id=server_id,
            restore_mode="merge",
            protective_backup=bool(protective),
            selection_mode="full",
            selected_paths=[],
            apply=False,
            initiated_from_telegram=True,
            request_id=request_id,
        )
        if kind == "imported":
            entry_key = backup_ref.get("entry_key")
            if not isinstance(entry_key, str) or not entry_key:
                raise BackupError(
                    ErrorCode.ARTIFACT_NOT_FOUND,
                    "Импортированный backup не найден",
                )
            operation = await asyncio.to_thread(
                manager.submit_imported_restore,
                entry_key,
                **common,
            )
        elif kind == "managed":
            backup_id = backup_ref.get("backup_id")
            if not isinstance(backup_id, str) or not backup_id:
                raise BackupError(
                    ErrorCode.ARTIFACT_NOT_FOUND,
                    "Резервная копия не найдена",
                )
            operation = await asyncio.to_thread(
                manager.submit_restore,
                backup_id,
                **common,
            )
        else:
            raise BackupError(
                ErrorCode.ARTIFACT_NOT_FOUND,
                "Резервная копия не найдена",
            )
    except Exception as exc:
        await _show_operation_error(
            query,
            user_id,
            state,
            exc,
            action="Не удалось подготовить восстановление",
        )
        return
    _bind_operation(user_id, state, operation, "prepare")
    text, keyboard = _progress_view(user_id, state, operation)
    await query.edit_message_text(text, reply_markup=keyboard)
    _start_watcher(user_id, state, manager, query.message)


async def _start_apply(query, user_id: int, state: dict) -> None:
    if state.get("phase") not in {"confirm_apply", "confirm_without_protective"}:
        await _stale_context(query, user_id)
        return
    prepared_operation_id = state.get("prepared_operation_id")
    if not isinstance(prepared_operation_id, str) or not prepared_operation_id:
        await _stale_context(query, user_id)
        return
    backup_ref = state.get("backup_ref")
    if not isinstance(backup_ref, dict):
        backup_id = state.get("backup_id")
        if isinstance(backup_id, str) and backup_id:
            backup_ref = {
                "kind": "managed",
                "backup_id": backup_id,
                "server_id": state.get("server_id"),
            }
        else:
            await _stale_context(query, user_id)
            return
    kind = backup_ref.get("kind")
    server_id = str(state.get("server_id") or "")
    if backup_ref.get("server_id") != server_id:
        await _stale_context(query, user_id)
        return
    _set_phase(user_id, state, "apply_submitting")
    request_id = f"tg-restore-apply-{uuid4().hex}"
    state["request_id"] = request_id
    await query.edit_message_text("⏳ Регистрация восстановления…")
    try:
        manager = await _manager()
        common = dict(
            server_id=server_id,
            apply=True,
            prepared_operation_id=prepared_operation_id,
            confirm=True,
            confirm_without_protective=not bool(state.get("protective_backup")),
            initiated_from_telegram=True,
            request_id=request_id,
        )
        if kind == "imported":
            entry_key = backup_ref.get("entry_key")
            if not isinstance(entry_key, str) or not entry_key:
                raise BackupError(
                    ErrorCode.ARTIFACT_NOT_FOUND,
                    "Импортированный backup не найден",
                )
            operation = await asyncio.to_thread(
                manager.submit_imported_restore,
                entry_key,
                **common,
            )
        elif kind == "managed":
            backup_id = backup_ref.get("backup_id")
            if not isinstance(backup_id, str) or not backup_id:
                raise BackupError(
                    ErrorCode.ARTIFACT_NOT_FOUND,
                    "Резервная копия не найдена",
                )
            operation = await asyncio.to_thread(
                manager.submit_restore,
                backup_id,
                **common,
            )
        else:
            raise BackupError(
                ErrorCode.ARTIFACT_NOT_FOUND,
                "Резервная копия не найдена",
            )
    except Exception as exc:
        await _show_operation_error(
            query,
            user_id,
            state,
            exc,
            action="Не удалось запустить восстановление",
        )
        return
    _bind_operation(user_id, state, operation, "apply")
    text, keyboard = _progress_view(user_id, state, operation)
    await query.edit_message_text(text, reply_markup=keyboard)
    _start_watcher(user_id, state, manager, query.message)


async def _cancel_operation(
    query,
    user_id: int,
    state: dict,
    operation_id: str,
) -> None:
    if operation_id != state.get("active_operation_id"):
        await _stale_context(query, user_id)
        return
    if state.get("cancel_requested"):
        return
    try:
        manager = await _manager()
        operation = await asyncio.to_thread(manager.get_operation, operation_id)
        if not _operation_can_cancel(operation):
            if (operation.get("restore") or {}).get("mutation_started") or not (
                operation.get("cancellation") or {}
            ).get("allowed", True):
                state["cancel_notice"] = (
                    "⚠️ Изменение данных уже началось, отмена больше недоступна."
                )
                text, keyboard = _progress_view(user_id, state, operation)
                await query.edit_message_text(text, reply_markup=keyboard)
                return
            await _stale_context(query, user_id)
            return
        accepted = await asyncio.to_thread(manager.cancel_operation, operation_id)
        state["cancel_requested"] = True
        text, _ = _progress_view(user_id, state, accepted, allow_cancel=False)
        await query.edit_message_text(text)
    except BackupError as exc:
        if exc.code == ErrorCode.RESTORE_CANCEL_FORBIDDEN.value:
            state["cancel_notice"] = (
                "⚠️ Изменение данных уже началось, отмена больше недоступна."
            )
            try:
                operation = await asyncio.to_thread(manager.get_operation, operation_id)
                text, keyboard = _progress_view(user_id, state, operation)
                await query.edit_message_text(text, reply_markup=keyboard)
            except Exception:
                pass
            return
        await _stale_context(query, user_id)


async def process_backup_callback(query, data: str, context) -> bool:
    """Route the isolated ``bk:`` namespace and use BackupManager directly."""
    if not isinstance(data, str) or not data.startswith("bk:"):
        return False
    user_id = int(query.from_user.id)

    if data == "bk:entry" or data == "bk:entry:tasks":
        if _active_flow(user_id):
            await _stale_context(query, user_id)
        else:
            entry_point = (
                "tasks_menu" if data == "bk:entry:tasks" else "main_backup_menu"
            )
            await _show_main_backup_entry(
                query,
                user_id,
                entry_point=entry_point,
            )
        return True

    parts = data.split(":", 2)
    if len(parts) != 3 or not parts[1] or not parts[2]:
        await _stale_context(query, user_id)
        return True
    action, token = parts[1], parts[2]

    if action == "o":
        server_id = _resolve_token(user_id, token, "entry_server")
        if not isinstance(server_id, str) or not await asyncio.to_thread(find_server, server_id):
            await _stale_context(query, user_id)
            return True
        if _active_flow(user_id):
            await _stale_context(query, user_id)
            return True
        state = _replace_state(
            user_id,
            entry_point="server_card",
            server_id=server_id,
        )
        await _show_backup_menu(query, user_id, state)
        return True

    if action == "q":
        navigation = _resolve_token(user_id, token, _RESULT_TOKEN_KIND)
        if not isinstance(navigation, dict):
            await _stale_context(query, user_id)
            return True
        operation_id = navigation.get("operation_id")
        server_id = navigation.get("server_id")
        if (
            not isinstance(operation_id, str)
            or not operation_id
            or not isinstance(server_id, str)
            or not server_id
            or not await asyncio.to_thread(find_server, server_id)
        ):
            await _stale_context(query, user_id)
            return True
        from ui.telegram.servers import reboot_confirm

        await reboot_confirm(query, server_id)
        return True

    if action == "v":
        navigation = _resolve_token(user_id, token, _RESULT_TOKEN_KIND)
        if not isinstance(navigation, dict):
            await _stale_context(query, user_id)
            return True
        operation_id = navigation.get("operation_id")
        server_id = navigation.get("server_id")
        entry_point = navigation.get("entry_point")
        current = BACKUP_STATE.get(user_id)
        if (
            not isinstance(operation_id, str)
            or not operation_id
            or not isinstance(server_id, str)
            or not server_id
            or entry_point not in _ENTRY_POINTS
            or not await asyncio.to_thread(find_server, server_id)
            or (
                _active_flow(user_id)
                and isinstance(current, dict)
                and current.get("active_operation_id") != operation_id
            )
        ):
            await _stale_context(query, user_id)
            return True
        state = _replace_state(
            user_id,
            entry_point=str(entry_point),
            server_id=server_id,
        )
        await _show_backup_menu(query, user_id, state)
        return True

    state = BACKUP_STATE.get(user_id)
    if not isinstance(state, dict):
        await _stale_context(query, user_id)
        return True

    if action == "s":
        server_id = _resolve_token(
            user_id,
            token,
            "server",
            generation=int(state.get("generation") or 0),
        )
        if (
            state.get("phase") != "server_picker"
            or not isinstance(server_id, str)
            or not await asyncio.to_thread(find_server, server_id)
        ):
            await _stale_context(query, user_id)
            return True
        state["server_id"] = server_id
        await _show_backup_menu(query, user_id, state)
        return True

    if action == "p":
        page = _resolve_token(
            user_id,
            token,
            "page",
            generation=int(state.get("generation") or 0),
        )
        if state.get("phase") != "catalog" or not isinstance(page, int):
            await _stale_context(query, user_id)
            return True
        await _show_catalog(query, user_id, state, page)
        return True

    if action == "b":
        backup_ref = _resolve_token(
            user_id,
            token,
            "backup",
            generation=int(state.get("generation") or 0),
        )
        if (
            state.get("phase") != "catalog"
            or not isinstance(backup_ref, dict)
            or backup_ref.get("server_id") != state.get("server_id")
            or backup_ref.get("kind") not in {"managed", "imported"}
        ):
            await _stale_context(query, user_id)
            return True
        await _select_backup(query, user_id, state, backup_ref)
        return True

    if action == "k":
        operation_id = _resolve_token(
            user_id,
            token,
            "operation",
            generation=int(state.get("generation") or 0),
        )
        if not isinstance(operation_id, str) or state.get("phase") not in {
            "create_running",
            "prepare_running",
            "apply_running",
        }:
            await _stale_context(query, user_id)
            return True
        await _cancel_operation(query, user_id, state, operation_id)
        return True

    if not _valid_action(user_id, state, token, action):
        await _stale_context(query, user_id)
        return True

    if action == "c" and state.get("phase") == "menu":
        await _start_create(query, user_id, state)
    elif action == "r" and state.get("phase") in {
        "menu",
        "protective_choice",
        "full_restore_unavailable",
    }:
        await _show_catalog(query, user_id, state)
    elif action == "m" and state.get("phase") in {
        "catalog",
        "operation_error",
        "confirm_apply",
        "confirm_without_protective",
        "terminal",
    }:
        await _show_backup_menu(query, user_id, state)
    elif action == "x" and state.get("phase") in {"menu", "web_unavailable"}:
        await _exit_flow(query, user_id, state)
        return True
    elif action == "y" and state.get("phase") == "protective_choice":
        await _start_prepare(query, user_id, state, protective=True)
    elif action == "n" and state.get("phase") == "protective_choice":
        await _start_prepare(query, user_id, state, protective=False)
    elif action == "a" and state.get("phase") in {
        "confirm_apply",
        "confirm_without_protective",
    }:
        await _start_apply(query, user_id, state)
    else:
        await _stale_context(query, user_id)
    return True


__all__ = [
    "backup_entry_callback",
    "backup_result_callback",
    "backup_result_reboot_callback",
    "process_backup_callback",
]
