# -*- coding: utf-8 -*-
"""Тонкий диспетчер раздела «Сервисы» в карточке сервера.

Знает ТОЛЬКО: есть сервис (service_id), есть операция (op), есть зарегистрированный
обработчик (ServiceUI). Ничего не знает про WireGuard (и любой другой конкретный
сервис) — вся специфика живёт в `services/<id>.py`.

Маршрутизация:
  • prefix-маршруты (tasks_svc_*, services:, tasks_svc:) — общие хабы;
  • generic install-wizard (op: install_cfg/val/skip/run/cancel) — по params_schema();
  • generic sync / confirm_remove / remove;
  • делегирование остальных op в ServiceUI через реестр (claims/handle_callback);
  • generic-fallback: карточка из manifest+get_status+get_actions (для сервисов
    без своего UI) и generic install.

Точки входа `process_service_callback` / `process_service_message` (сигнатуры
неизменны) вызываются из `bot_handlers.button()` и `bot.py::text_handler`.
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from core import integrator
from core.integrator import get_manifest, list_services
from core.storage import find_server, load_servers
from state import SERVICE_INSTALL_STATE
from ui.telegram import task_ui

from .services._shared import (
    _coerce_param,
    _enqueue_watch_query,
    _install_handle_text,
    _parse_svc,
    _render_service_card,
    _show_install_menu,
    _show_install_param,
    _svc_cb,
    _SRC_TASKS,
)
from .services.base import (
    CallbackCtx,
    DocumentCtx,
    MessageCtx,
    all_service_uis,
    get_service_ui,
)

# Больше файла в Telegram-документе не ждём: Compose-проект в ZIP столько не
# занимает, а ограничение защищает от случайной загрузки образа/дампа.
_MAX_DOCUMENT_SIZE = 20 * 1024 * 1024

# install-wizard оперирует общим state-диктом и params_schema() — не per-service.
_WIZARD_OPS = {"install_cfg", "install_val", "install_skip", "install_run", "install_cancel"}


# --------------------------------------------------------------
# Хабы (общие, только по manifest + get_status)
# --------------------------------------------------------------

async def _services_hub(query, server_id: str):
    server = find_server(server_id)
    server_name = server["name"] if server else server_id
    rows = []
    text = f"🛠 Сервисы · {server_name}\n\nСтатусы — по последней синхронизации."
    for manifest in list_services():
        try:
            status = await integrator.call(manifest.id, server_id, "get_status") or {}
        except Exception:
            status = {}
        installed = status.get("installed")
        if installed is True:
            mark = f"🟢 {manifest.name}"
        elif installed is False:
            mark = f"⚪ {manifest.name}"
        else:
            mark = f"❔ {manifest.name}"
        rows.append([InlineKeyboardButton(mark, callback_data=_svc_cb("view", manifest.id, server_id))])

    rows.append([InlineKeyboardButton("🔄 Перезагрузить сервер", callback_data=f"reboot_confirm:{server_id}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"server:{server_id}")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def _tasks_service_hub(query, service_id: str):
    manifest = get_manifest(service_id)
    icon = (manifest.icon + " ") if manifest and manifest.icon else "🛠 "
    name = manifest.name if manifest else service_id
    text = (
        f"{icon}{name}\n\n"
        f"🔎 Полная проверка — обновить состояние на всех серверах\n"
        f"🟢 Установить — серверы без {name}\n"
        f"⚙️ Управление — серверы, где {name} уже установлен"
    )
    rows = [
        [InlineKeyboardButton("🔎 Полная проверка", callback_data=f"tasks_svc_check:{service_id}")],
        [InlineKeyboardButton("🟢 Установить", callback_data=f"tasks_svc_install:{service_id}")],
        [InlineKeyboardButton(f"⚙️ Управление {name}", callback_data=f"tasks_svc_manage:{service_id}")],
        [InlineKeyboardButton("⬅️ Задачи", callback_data="tasks")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def _tasks_full_check(query, service_id: str):
    await query.edit_message_text("⏳ Идёт полная проверка сервисов на всех серверах...")

    # Пустой список — нормальный результат Telegram-сценария. Не создаём
    # задачу и не оставляем пользователя ждать Task Manager: сразу заменяем
    # временное сообщение финальным ответом.
    servers = load_servers()
    if not servers:
        manifest = get_manifest(service_id)
        service_name = manifest.name if manifest else service_id
        text = (
            f"✅ Полная проверка {service_name} завершена\n\n"
            "Серверов для проверки нет.\n"
            "Добавьте серверы в Bot4VPS, чтобы выполнить проверку."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"tasks_svc:{service_id}")]
        ])
        try:
            await query.edit_message_text(text, reply_markup=kb)
        except Exception:
            await query.message.reply_text(text, reply_markup=kb)
        return

    try:
        task = await integrator.enqueue_bulk_check(service_id)
        await task.wait()
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка проверки:\n{e}")
        return

    text = task_ui.format_done_text(task)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"tasks_svc:{service_id}")]
    ])
    try:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def _tasks_server_list(query, service_id: str, mode: str):
    manifest = get_manifest(service_id)
    title = (manifest.icon + " ") if manifest and manifest.icon else ""
    title += (manifest.name if manifest else service_id)
    servers = load_servers()
    rows = []
    shown = 0
    for s in servers:
        sid = s["id"]
        try:
            status = await integrator.call(service_id, sid, "get_status") or {}
        except Exception:
            status = {}
        installed = status.get("installed")
        synced = bool(status.get("synced_at"))

        if mode == "install":
            if installed is True:
                continue
            label = s["name"]
            if not synced and installed is not False:
                label += " · нет данных"
            rows.append([InlineKeyboardButton(label, callback_data=_svc_cb("view", service_id, sid, src=_SRC_TASKS))])
            shown += 1
        else:
            if installed is True:
                rows.append([InlineKeyboardButton(s["name"], callback_data=_svc_cb("view", service_id, sid, src=_SRC_TASKS))])
                shown += 1

    if mode == "install":
        head = f"{title}\n\n🟢 Установка — серверы без сервиса:"
        empty = "Все серверы уже с установленным сервисом (или нужна проверка)."
    else:
        head = f"{title}\n\n⚙️ Управление — серверы с установленным сервисом:"
        empty = "Нет серверов с установленным сервисом. Сначала «Полная проверка» или «Установить»."

    text = head if shown else head + "\n\n" + empty
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"tasks_svc:{service_id}")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))


# --------------------------------------------------------------
# Generic-операции (синхронизация, удаление, install-wizard)
# --------------------------------------------------------------

async def _do_sync(query, service_id: str, server_id: str, src: str | None = None):
    manifest = get_manifest(service_id)
    await query.edit_message_text(f"🔄 Синхронизация {manifest.name}…")
    try:
        await integrator.sync(service_id, server_id)
    except Exception as e:
        try:
            await query.message.reply_text(f"❌ Ошибка синхронизации:\n{e}")
        except Exception:
            pass
    await _render_service_card(query, service_id, server_id, src=src)


async def _confirm_remove(query, service_id: str, server_id: str, src: str | None = None):
    manifest = get_manifest(service_id)
    text = f"⚠️ Удалить {manifest.name}?\nБудут удалены пакеты и конфиги сервиса."

    # Куда возвращает отказ. Дефолт "settings" — как было; сервис может указать
    # свой op через ServiceUI.cancel_remove_op. Если указанный op не заявлен
    # (или UI нет вовсе) — падаем на "view": generic-карточка есть всегда.
    ui = get_service_ui(service_id)
    cancel_op = getattr(ui, "cancel_remove_op", "settings") if ui is not None else "view"
    if cancel_op != "view" and (ui is None or not ui.claims(cancel_op)):
        cancel_op = "view"

    rows = [
        [InlineKeyboardButton("✅ Да", callback_data=_svc_cb("remove", service_id, server_id, src=src))],
        [InlineKeyboardButton("❌ Нет", callback_data=_svc_cb(cancel_op, service_id, server_id, src=src))],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def _dispatch_install_wizard(op, query, user_id, service_id, server_id, name, src):
    """Generic install-wizard: state в SERVICE_INSTALL_STATE, схема — params_schema()."""
    if op == "install_cfg":
        state = SERVICE_INSTALL_STATE.get(user_id) or {}
        SERVICE_INSTALL_STATE[user_id] = {
            "service": service_id, "server": server_id, "src": state.get("src") or src,
            "endpoint_params": state.get("endpoint_params") or {}, "params": integrator.params_schema(service_id),
            "index": 0, "values": {},
        }
        await _show_install_param(query, user_id)
    elif op == "install_val":
        state = SERVICE_INSTALL_STATE.get(user_id)
        if state and state["index"] < len(state["params"]):
            p = state["params"][state["index"]]
            state["values"][p.name] = _coerce_param(p, name)
            state["index"] += 1
        await _show_install_param(query, user_id)
    elif op == "install_skip":
        state = SERVICE_INSTALL_STATE.get(user_id)
        if state and state["index"] < len(state["params"]):
            p = state["params"][state["index"]]
            state["values"][p.name] = p.default
            state["index"] += 1
        await _show_install_param(query, user_id)
    elif op == "install_run":
        state = SERVICE_INSTALL_STATE.pop(user_id, None) or {}
        values = dict(state.get("endpoint_params") or {})
        values.update(state.get("values") or {})
        for p in state.get("params") or []:
            if p.name not in values:
                values[p.name] = p.default
        src_s = state.get("src") or src
        await _enqueue_watch_query(query, service_id, server_id, "install", values, src=src_s)
    elif op == "install_cancel":
        SERVICE_INSTALL_STATE.pop(user_id, None)
        await _render_service_card(query, service_id, server_id, src=src)


# --------------------------------------------------------------
# Маршрутизация
# --------------------------------------------------------------

async def process_service_callback(query, data: str) -> bool:
    # --- prefix-маршруты (хабы) ---
    if data.startswith("tasks_svc_check:"):
        await _tasks_full_check(query, data.split(":", 1)[1])
        return True
    if data.startswith("tasks_svc_install:"):
        await _tasks_server_list(query, data.split(":", 1)[1], "install")
        return True
    if data.startswith("tasks_svc_manage:"):
        await _tasks_server_list(query, data.split(":", 1)[1], "manage")
        return True
    if data.startswith("tasks_svc:"):
        svc_id = data.split(":", 1)[1]
        # Сервис может рисовать хаб раздела сам (owns_hub) — тогда generic-хаб
        # с «Полная проверка / Установить / Управление» не показываем.
        ui = get_service_ui(svc_id)
        if ui is not None and getattr(ui, "owns_hub", False):
            ctx = CallbackCtx(op="hub", query=query, user_id=query.from_user.id,
                              service_id=svc_id, server_id="-", name=None, src=None)
            if await ui.handle_callback(ctx):
                return True
        await _tasks_service_hub(query, svc_id)
        return True
    if data.startswith("services:"):
        await _services_hub(query, data.split(":", 1)[1])
        return True
    if not data.startswith("svc:"):
        return False

    op, service_id, server_id, name, src = _parse_svc(data)
    user_id = query.from_user.id

    # --- generic install-wizard (state-driven, не перехватывается UI) ---
    if op in _WIZARD_OPS:
        await _dispatch_install_wizard(op, query, user_id, service_id, server_id, name, src)
        return True

    # --- generic sync ---
    if op == "sync":
        await _do_sync(query, service_id, server_id, src=src)
        return True

    # --- generic remove flow ---
    if op == "confirm_remove":
        await _confirm_remove(query, service_id, server_id, src=src)
        return True
    if op == "remove":
        await _enqueue_watch_query(query, service_id, server_id, "remove", {}, src=src)
        return True

    # --- делегирование в ServiceUI ---
    ui = get_service_ui(service_id)
    if ui is not None and ui.claims(op):
        ctx = CallbackCtx(op=op, query=query, user_id=user_id, service_id=service_id,
                          server_id=server_id, name=name, src=src)
        handled = await ui.handle_callback(ctx)
        if handled:
            return True
        print(f"[SVC] ServiceUI '{service_id}' заявил op '{op}', но вернул False — generic-fallback")

    # --- generic fallback (сервис без UI / незаявленный op) ---
    if op == "view":
        await _render_service_card(query, service_id, server_id, src=src)
        return True
    if op == "install":
        await _show_install_menu(query, user_id, service_id, server_id, src)
        return True

    # неизвестный op — не падаем
    try:
        await query.message.reply_text(f"⚠️ Операция «{op}» недоступна для сервиса «{service_id}».")
    except Exception:
        pass
    return True


async def process_service_message(update, context):
    user_id = update.effective_user.id

    # generic install-wizard: ввод значений параметров
    if user_id in SERVICE_INSTALL_STATE:
        await _install_handle_text(update.message, user_id, update.message.text.strip())
        return True

    # делегирование текстовых flow в зарегистрированные ServiceUI
    ctx = MessageCtx(update=update, context=context, user_id=user_id)
    for ui in all_service_uis():
        if ui.owns_message(user_id):
            if await ui.handle_message(ctx):
                return True
    return False


async def process_service_document(update, context) -> bool:
    """Документ → ServiceUI, который его ждёт.

    Transport-слой: сам скачивает файл из Telegram и отдаёт сервисному UI готовые
    байты (DocumentCtx). Так ни один ServiceUI не обращается к Telegram API за
    загрузкой — иначе транспорт растёк бы по сервисам.
    """
    message = getattr(update, "message", None)
    doc = getattr(message, "document", None) if message else None
    if not doc:
        return False
    user_id = update.effective_user.id

    ui = next((u for u in all_service_uis() if u.owns_document(user_id)), None)
    if ui is None:
        return False

    filename = doc.file_name or "upload"
    size = getattr(doc, "file_size", None) or 0
    if size > _MAX_DOCUMENT_SIZE:
        await message.reply_text(
            f"❌ Файл слишком большой ({size // 1024} КБ).\n"
            f"Лимит: {_MAX_DOCUMENT_SIZE // (1024 * 1024)} МБ."
        )
        return True

    try:
        tg_file = await context.bot.get_file(doc.file_id)
        data = bytes(await tg_file.download_as_bytearray())
    except Exception as e:
        await message.reply_text(f"❌ Не удалось скачать файл:\n{e}")
        return True

    ctx = DocumentCtx(
        update=update, context=context, user_id=user_id,
        filename=filename, data=data,
    )
    return await ui.handle_document(ctx)
