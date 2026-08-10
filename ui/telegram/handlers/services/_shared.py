# -*- coding: utf-8 -*-
"""Generic-инфраструктура сервисного Telegram-UI (без специфики конкретного сервиса).

Здесь живёт всё, что переиспользуется И тонким диспетчером (`service_handlers.py`),
И per-service UI-модулями (`wireguard.py` и будущими): callback-протокол `svc:`,
форматтеры статуса, generic install-wizard (по params_schema()), постановка задач
в очередь с live-выводом, и диспетчеризация отрисовки карточки сервиса.

Модуль НИЖНЕ-СРЕДНЕГО уровня: импортирует только `base` (реестр/контракт),
`core`/`state`/`task_ui`. НЕ импортирует `service_handlers` и per-service UI —
это держит граф импортов ацикличным и позволяет пакету `services` саморегистрироваться.
"""
from __future__ import annotations

import asyncio
import re

from telegram import InlineKeyboardMarkup, InlineKeyboardButton

from core import integrator
from core.integrator import get_manifest
from core.storage import find_server
from core.task_manager import task_manager, TaskStatus
from state import SERVICE_INSTALL_STATE
from ui.telegram import task_ui

from .base import CallbackCtx, get_service_ui

_SRC_TASKS = "tasks"


# --------------------------------------------------------------
# Callback-протокол  svc:<op>:<service_id>:<server_id>[:<name>][:<src>]
# --------------------------------------------------------------

def _svc_cb(op: str, service_id: str, server_id: str, name: str | None = None, src: str | None = None) -> str:
    parts = ["svc", op, service_id, server_id]
    if name:
        parts.append(name)
    if src:
        parts.append(src)
    return ":".join(parts)


def _parse_svc(data: str):
    parts = data.split(":")
    op = parts[1] if len(parts) > 1 else ""
    service_id = parts[2] if len(parts) > 2 else ""
    server_id = parts[3] if len(parts) > 3 else ""
    rest = parts[4:]
    src = None
    if rest and rest[-1] == _SRC_TASKS:
        src = rest.pop()
    name = rest[0] if rest else None
    return op, service_id, server_id, name, src


def _back_from_service(service_id: str, server_id: str, src: str | None) -> str:
    if src == _SRC_TASKS:
        return f"tasks_svc:{service_id}"
    return f"services:{server_id}"


# --------------------------------------------------------------
# Форматтеры статуса
# --------------------------------------------------------------

def _format_synced_at(raw) -> str:
    if not raw:
        return "—"
    s = str(raw).strip()
    try:
        s2 = s.replace("T", " ")[:16]
        from datetime import datetime
        dt = datetime.fromisoformat(s.replace("Z", "+00:00")[:19])
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return s2 if "s2" in dir() else s


def _map_systemd_state(state: str) -> tuple[str, str]:
    state = (state or "").strip().lower()
    if state == "active": return ("🟢", "активно")
    if state == "inactive": return ("⚪", "не запущен")
    if state == "failed": return ("🔴", "ошибка")
    return ("🟠", "неизвестно")


def _extract_version(raw: str) -> str:
    if not raw: return "неизвестна"
    m = re.search(r'v[0-9\.]+', raw)
    return m.group(0) if m else raw.split(" ")[0]


def _fmt_bytes(n) -> str:
    """Сырые байты → человекочитаемые единицы (ru): «17.5513 ГБ». Сервис отдаёт
    байты; UI только форматирует (ТЗ §19). В ГБ — 4 знака (ТЗ §5)."""
    n = int(n or 0)
    absn = abs(n)
    if absn >= 1e12:
        return f"{n / 1e12:.4f} ТБ"
    if absn >= 1e9:
        return f"{n / 1e9:.4f} ГБ"
    if absn >= 1e6:
        return f"{n / 1e6:.2f} МБ"
    if absn >= 1e3:
        return f"{n / 1e3:.2f} КБ"
    return f"{n} Б"


# --------------------------------------------------------------
# Прямой вызов (для тривиальных операций без очереди и логов)
# --------------------------------------------------------------

async def _noop_progress(text: str):
    """Заглушка для progress_cb, чтобы вызывать do_* методы напрямую."""
    pass


def _coerce_param(p, raw):
    if p.type == "bool":
        return str(raw).strip().lower() in ("true", "1", "yes", "on", "да")
    if p.type == "number":
        try:
            return int(raw)
        except (TypeError, ValueError):
            return raw
    if p.type == "select":
        try:
            return p.choices[int(raw)]
        except (ValueError, IndexError):
            return raw
    return raw


# --------------------------------------------------------------
# Generic install-wizard (по params_schema()). UI сервиса может подсунуть
# extra_params (напр. WireGuard — WG_ENDPOINT), они доезжают до do_install.
# --------------------------------------------------------------

async def _show_install_menu(target, user_id, service_id, server_id, src, extra_params=None):
    params = dict(extra_params or {})
    schema = integrator.params_schema(service_id)
    if not schema:
        if hasattr(target, "edit_message_text"):
            await _enqueue_watch_query(target, service_id, server_id, "install", params, src=src)
        else:
            await _enqueue_watch_message(target, target.get_bot(), service_id, server_id, "install", params, src=src)
        return
    defaults = "\n".join(f"• {p.name} = {p.default}" for p in schema)
    manifest = get_manifest(service_id)
    text = (
        f"{manifest.icon or '🛠'} Установка {manifest.name}\n\n"
        f"Параметры по умолчанию:\n{defaults}"
    )
    SERVICE_INSTALL_STATE[user_id] = {
        "service": service_id, "server": server_id, "src": src,
        "endpoint_params": params, "params": schema, "index": 0, "values": {},
    }
    rows = [
        [InlineKeyboardButton("🟢 Установить (по умолчанию)", callback_data=_svc_cb("install_run", service_id, server_id, src=src))],
        [InlineKeyboardButton("⚙️ Свои параметры", callback_data=_svc_cb("install_cfg", service_id, server_id, src=src))],
        [InlineKeyboardButton("⬅️ Назад", callback_data=_svc_cb("view", service_id, server_id, src=src))],
    ]
    kb = InlineKeyboardMarkup(rows)
    if hasattr(target, "edit_message_text"):
        try:
            await target.edit_message_text(text, reply_markup=kb)
        except Exception:
            await target.message.reply_text(text, reply_markup=kb)
    else:
        await target.reply_text(text, reply_markup=kb)


async def _show_install_param(target, user_id: int):
    state = SERVICE_INSTALL_STATE.get(user_id)
    if not state:
        return
    if state["index"] >= len(state["params"]):
        await _install_summary(target, user_id)
        return
    p = state["params"][state["index"]]
    svc, sid = state["service"], state["server"]
    src = state.get("src")

    rows = []
    if p.type == "bool":
        rows.append([
            InlineKeyboardButton("✅ Да", callback_data=_svc_cb("install_val", svc, sid, "true", src=src)),
            InlineKeyboardButton("❌ Нет", callback_data=_svc_cb("install_val", svc, sid, "false", src=src)),
        ])
    elif p.type == "select":
        for i, choice in enumerate(p.choices):
            rows.append([InlineKeyboardButton(str(choice), callback_data=_svc_cb("install_val", svc, sid, str(i), src=src))])

    ctrl = []
    if not p.required:
        ctrl.append(InlineKeyboardButton("⏭ По умолчанию", callback_data=_svc_cb("install_skip", svc, sid, src=src)))
    ctrl.append(InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("install_cancel", svc, sid, src=src)))
    rows.append(ctrl)

    default = "" if p.default is None else f"\nПо умолчанию: {p.default}"
    hint = "\nВведите значение сообщением." if p.type in ("text", "number") else ""
    desc = f"\n{p.description}" if p.description else ""
    text = (
        f"⚙️ Параметр {state['index'] + 1}/{len(state['params'])}: {p.name}\n"
        f"Тип: {p.type}{default}{desc}{hint}"
    )
    kb = InlineKeyboardMarkup(rows)
    if hasattr(target, "edit_message_text"):
        try:
            await target.edit_message_text(text, reply_markup=kb)
        except Exception:
            await target.message.reply_text(text, reply_markup=kb)
    else:
        await target.reply_text(text, reply_markup=kb)


async def _install_summary(target, user_id: int):
    state = SERVICE_INSTALL_STATE.get(user_id)
    if not state:
        return
    manifest = get_manifest(state["service"])
    lines = [f"📋 {manifest.name} — проверьте параметры:"]
    for p in state["params"]:
        v = state["values"].get(p.name, p.default)
        lines.append(f"• {p.name} = {v}")
    rows = [
        [InlineKeyboardButton("🚀 Установить", callback_data=_svc_cb("install_run", state["service"], state["server"], src=state.get("src")))],
        [InlineKeyboardButton("❌ Отмена", callback_data=_svc_cb("install_cancel", state["service"], state["server"], src=state.get("src")))],
    ]
    kb = InlineKeyboardMarkup(rows)
    if hasattr(target, "edit_message_text"):
        try:
            await target.edit_message_text("\n".join(lines), reply_markup=kb)
        except Exception:
            await target.message.reply_text("\n".join(lines), reply_markup=kb)
    else:
        await target.reply_text("\n".join(lines), reply_markup=kb)


async def _install_handle_text(message, user_id: int, text: str):
    state = SERVICE_INSTALL_STATE.get(user_id)
    if not state:
        return
    if state["index"] >= len(state["params"]):
        await _install_summary(message, user_id)
    p = state["params"][state["index"]]
    state["values"][p.name] = _coerce_param(p, text)
    state["index"] += 1
    await _show_install_param(message, user_id)


# --------------------------------------------------------------
# Очередь (только для тяжёлых задач: install, remove, migrate)
# --------------------------------------------------------------

def _start_text(task, server_name: str) -> str:
    pos = task_manager.queue_position(task.id)
    ahead = task_manager.tasks_ahead(task.id)
    if task.status == TaskStatus.QUEUED and pos is not None:
        w = "задача" if ahead == 1 else ("задачи" if 2 <= ahead <= 4 else "задач")
        status_line = f"⏳ В очереди · позиция {pos} (перед вами: {ahead} {w})"
    else:
        status_line = "▶ Выполнение запущено"
    return (
        f"🚀 {status_line}\n\n"
        f"🛠 {task.name}\n🖥 {server_name}\nid: {task.id}\n\n"
        f"Можете пользоваться ботом дальше\nили открыть лог выполнения."
    )


async def _enqueue_watch_query(query, service_id, server_id, action, params, src=None):
    server = find_server(server_id)
    server_name = server["name"] if server else server_id
    try:
        task = await integrator.enqueue(service_id, server_id, action, params, src=src)
    except Exception as e:
        try:
            await query.message.reply_text(f"❌ Не удалось поставить задачу:\n{e}")
        except Exception:
            pass
        return None
    text = _start_text(task, server_name)
    kb = task_ui.kb_started(server_id, task.id)
    try:
        await query.edit_message_text(text, reply_markup=kb)
    except Exception:
        await query.message.reply_text(text, reply_markup=kb)
    asyncio.create_task(task_ui.watch_task_background(task.id, server_id, query.get_bot(), query.message.chat_id))
    return task


async def _enqueue_watch_message(message, bot, service_id, server_id, action, params, src=None):
    server = find_server(server_id)
    server_name = server["name"] if server else server_id
    try:
        task = await integrator.enqueue(service_id, server_id, action, params, src=src)
    except Exception as e:
        try:
            await message.reply_text(f"❌ Не удалось поставить задачу:\n{e}")
        except Exception:
            pass
        return None
    text = _start_text(task, server_name)
    kb = task_ui.kb_started(server_id, task.id)
    await message.reply_text(text, reply_markup=kb)
    asyncio.create_task(task_ui.watch_task_background(task.id, server_id, bot, message.chat_id))
    return task


# --------------------------------------------------------------
# Отрисовка карточки сервиса (единая точка после sync / install_cancel / view)
# --------------------------------------------------------------

async def _render_service_card(query, service_id, server_id, src=None):
    """Карточка сервиса: делегирует view в ServiceUI, если он его заявляет;
    иначе — generic-карточку. Вызов после sync/install_cancel даёт нужную
    (богатую для WG, generic для прочих) карточку без знания о сервисе."""
    ui = get_service_ui(service_id)
    if ui is not None and ui.claims("view"):
        ctx = CallbackCtx(op="view", query=query, user_id=query.from_user.id,
                          service_id=service_id, server_id=server_id, name=None, src=src)
        await ui.handle_callback(ctx)
    else:
        await _generic_service_card(query, service_id, server_id, src=src)


async def _generic_service_card(query, service_id: str, server_id: str, src: str | None = None):
    """Fallback-карточка: только из manifest + get_status(installed/synced_at)
    + get_actions(). Никакого знания о полях конкретного сервиса."""
    manifest = get_manifest(service_id)
    if not manifest:
        await query.edit_message_text("❌ Сервис не найден.")
        return
    server = find_server(server_id)
    server_name = server["name"] if server else server_id

    try:
        status = await integrator.call(service_id, server_id, "get_status") or {}
    except Exception as e:
        status = {}
        try:
            await query.message.reply_text(f"⚠️ Не удалось получить статус: {e}")
        except Exception:
            pass

    installed = bool(status.get("installed"))
    synced_at = _format_synced_at(status.get("synced_at"))
    icon = manifest.icon or "🛠"
    desc = (manifest.extra or {}).get("description") or ""

    lines = [f"{icon} {manifest.name}", f"🖥 {server_name}"]
    if desc:
        lines.append(desc)
    lines.append("")
    lines.append("✅ Статус: установлен" if installed else "⚪ Статус: не установлен")
    if synced_at != "—":
        lines.append(f"🕒 Синхронизация: {synced_at}")
    else:
        lines.append("🕒 Синхронизация: ещё не было")
    text = "\n".join(lines)

    try:
        menu = await integrator.call(service_id, server_id, "get_actions") or []
    except Exception:
        menu = []
    rows = []
    for item in menu:
        op_id = getattr(item, "id", None) or (item.get("id") if isinstance(item, dict) else None)
        label = getattr(item, "label", None) or (item.get("label", "") if isinstance(item, dict) else "")
        if op_id:
            rows.append([InlineKeyboardButton(label, callback_data=_svc_cb(op_id, service_id, server_id, src=src))])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=_back_from_service(service_id, server_id, src))])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))
