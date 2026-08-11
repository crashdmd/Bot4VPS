"""Общий UI задач (Live Output + клавиатуры + task-маршруты)."""
import asyncio
import html as html_module
import re

from telegram import InlineKeyboardMarkup, InlineKeyboardButton

from core.task_manager import task_manager, STATUS_EMOJI, TaskStatus
from core.monitor import refresh_server_state
from core.storage import load_servers, find_server

LOG_VIEWS: dict[str, object] = {}


# --------------------------------------------------------------
# Клавиатуры
# --------------------------------------------------------------

def kb_started(server_id: str, task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 Смотреть лог", callback_data=f"task_log:{task_id}")],
        [InlineKeyboardButton("📋 Очередь сервера", callback_data=f"task_queue:{server_id}")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main")],
    ])


def kb_log(server_id: str, task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить лог", callback_data=f"task_log:{task_id}")],
        [InlineKeyboardButton("📋 Очередь сервера", callback_data=f"task_queue:{server_id}")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main")],
    ])


def kb_done_rows(server_id: str, nav_rows: list | None = None, task_id: str | None = None, task=None) -> list:
    rows = []
    is_scan = False
    if task is not None:
        is_scan = task.kind == "svc_scan" or (task.payload or {}).get("action") == "bulk_check"
    if task_id and not is_scan:
        rows.append([InlineKeyboardButton("📜 Журнал выполнения", callback_data=f"task_log:{task_id}")])
    st = task_manager.get_queue_state(server_id)
    q = task_manager.get_queue(server_id)
    if st.paused and q:
        rows.append([InlineKeyboardButton("▶ Продолжить очередь", callback_data=f"task_continue:{server_id}")])
        rows.append([
            InlineKeyboardButton("🔄 Повторить", callback_data=f"task_retry:{server_id}"),
            InlineKeyboardButton("⏹ Очистить", callback_data=f"task_clear:{server_id}"),
        ])
    elif st.paused:
        rows.append([InlineKeyboardButton("🔄 Повторить", callback_data=f"task_retry:{server_id}")])
    if (q or task_manager.get_running(server_id)) and not is_scan:
        rows.append([InlineKeyboardButton("📋 Очередь сервера", callback_data=f"task_queue:{server_id}")])
    if nav_rows:
        rows.extend(nav_rows)
    rows.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main")])
    return rows


def _nav_rows_for_task(task) -> list:
    if task.kind == "script":
        return [[
            InlineKeyboardButton("📜 Скрипты", callback_data="scripts"),
            InlineKeyboardButton("📋 Задачи", callback_data="tasks"),
        ]]
    if task.kind in ("svc", "svc_scan"):
        payload = task.payload or {}
        service_id = payload.get("service", "")
        action = payload.get("action", "")
        src = payload.get("src")
        if task.kind == "svc_scan" or action == "bulk_check":
            return [[InlineKeyboardButton("⬅️ Назад", callback_data=f"tasks_svc:{service_id}")]]
        if src == "tasks":
            cb = f"svc:view:{service_id}:{task.server_id}:tasks"
        else:
            cb = f"svc:view:{service_id}:{task.server_id}"
        return [[InlineKeyboardButton("⬅️ Назад", callback_data=cb)]]
    return []


# --------------------------------------------------------------
# Форматирование
# --------------------------------------------------------------

def format_log_text(task) -> str:
    emoji = STATUS_EMOJI.get(task.status, "•")
    body = "\n".join(task.output_lines[-40:]) or "…ожидание вывода…"
    return (
        f"{emoji} Лог · <code>{html_module.escape(task.id)}</code>\n\n"
        f"📜 {html_module.escape(task.name)}\n🖥 {html_module.escape(task.server_name)}\n"
        f"Статус: {_status_label(task)}\n\n{body}"
    )


def _status_label(task) -> str:
    labels = {
        TaskStatus.SUCCESS: "Успешно",
        TaskStatus.SUCCESS_WITH_WARNINGS: "Успешно с предупреждениями",
        TaskStatus.FAILED: "Ошибка",
        TaskStatus.CANCELLED: "Отменена",
        TaskStatus.RUNNING: "Выполняется",
        TaskStatus.QUEUED: "В очереди",
    }
    return labels.get(task.status, str(task.status.value))


def _human_error(err: str) -> str:
    err = (err or "").strip()
    err = re.sub(r"\s*\[[a-z0-9_]+\]\s*", " ", err)
    return re.sub(r"\s{2,}", " ", err).strip()


def format_done_text(task) -> str:
    emoji = STATUS_EMOJI.get(task.status, "•")
    action = (task.payload or {}).get("action", "")

    if action == "bulk_check" or task.kind == "svc_scan":
        installed, missing, errors = [], [], []
        raw = (task.result.output if task.result else "") or ""
        candidates = []
        for line in (raw.splitlines() + list(task.output_lines or [])):
            s = (line or "").strip()
            if not s or s.startswith("Всего:"):
                continue
            candidates.append(s)
        seen = set()
        for s in candidates:
            name = s
            status_part = ""
            for sep in (" — ", " - ", " · "):
                if sep in s:
                    name, status_part = s.split(sep, 1)
                    break
            name = name.lstrip("•✅❌⚠️ ").strip()
            if not name or name in seen:
                continue
            if name.startswith("Всего"):
                continue
            seen.add(name)
            low = status_part.lower()
            if "установлен" in low and "не " not in low:
                installed.append(name)
            elif "ошиб" in low or "error" in low or "timeout" in low:
                errors.append((name, status_part.strip() if status_part else "ошибка"))
            elif "не установлен" in low or s.startswith("❌"):
                missing.append(name)
            elif s.startswith("✅") or "установлен" in low:
                installed.append(name)
            else:
                if s.startswith("✅"):
                    installed.append(name)
                elif s.startswith("⚠️") or s.startswith("⚠"):
                    errors.append((name, status_part or "ошибка"))
                else:
                    missing.append(name)

        n = len(installed) + len(missing) + len(errors)
        text = (
            f"{emoji} Полная проверка завершена\n\n"
            f"🖥 Проверено серверов: {n or '—'}\n"
            f"Длительность: {task.duration_human()}\n"
        )
        if installed:
            text += f"\n✅ Установлен ({len(installed)})\n"
            text += "".join(f"• {n}\n" for n in installed)
        if missing:
            text += f"\n❌ Не установлен ({len(missing)})\n"
            text += "".join(f"• {n}\n" for n in missing)
        if errors:
            text += f"\n⚠️ Ошибки ({len(errors)})\n"
            text += "".join(f"• {n} — {e}\n" for n, e in errors)
        if task.error:
            text += f"\nОшибка:\n{_human_error(task.error)}\n"
        return text

    if task.is_successful and action == "install":
        head = f"{emoji} Сервис успешно установлен"
    elif task.is_successful and action == "remove":
        head = f"{emoji} Сервис успешно удалён"
    elif task.is_successful:
        head = f"{emoji} Задача завершена"
    elif task.status == TaskStatus.FAILED:
        head = f"{emoji} Задача завершилась с ошибкой"
    else:
        head = f"{emoji} Задача завершена"

    text = (
        f"{head}\n\n"
        f"📜 {html_module.escape(task.name)}\n"
        f"🖥 {html_module.escape(task.server_name)}\n"
        f"Длительность: {task.duration_human()}\n"
    )
    # Выводим результат операции (например, "Профиль включён")
    if task.result and task.result.output:
        text += f"\n{html_module.escape(task.result.output)}\n"
    if task.attempt and task.attempt > 1:
        text += f"Попытка: {task.attempt}\n"
    if task.error:
        text += f"\nОшибка:\n{_human_error(task.error)}\n"
        detail_lines = []
        for line in (task.output_lines or [])[-15:]:
            s = (line or "").strip()
            if not s or s.startswith("•"):
                continue
            low = s.lower()
            if any(k in low for k in ("error", "fatal", "failed", "rtnetlink", "unknown", "not found", "не уда", "operation not")):
                detail_lines.append(s)
        if detail_lines:
            text += "\nПричина:\n" + "\n".join(detail_lines[-3:]) + "\n"
    return text


# --------------------------------------------------------------
# Live Output
# --------------------------------------------------------------

async def watch_task_background(task_id: str, server_id: str, bot, chat_id: int):
    task = task_manager.get_task(task_id)
    if not task:
        return

    async def on_line(line: str):
        msg = LOG_VIEWS.get(task_id)
        if not msg:
            return
        t = task_manager.get_task(task_id)
        if not t:
            return
        try:
            await msg.edit_text(format_log_text(t), parse_mode="HTML", reply_markup=kb_log(server_id, task_id))
        except Exception:
            pass

    task_manager.subscribe_live(task_id, on_line)
    try:
        await task.wait()
    finally:
        task_manager.unsubscribe_live(task_id, on_line)

    t = task_manager.get_task(task_id) or task
    if t and t.is_successful:
        try:
            await asyncio.to_thread(refresh_server_state, server_id)
        except Exception as e:
            print(f"[BOT] refresh after task: {e}", flush=True)
    if not t:
        return

    final = format_done_text(t)
    kb = InlineKeyboardMarkup(kb_done_rows(server_id, _nav_rows_for_task(t), task_id=t.id, task=t))
    msg = LOG_VIEWS.pop(task_id, None)
    if msg:
        try:
            await msg.edit_text(final, reply_markup=kb, parse_mode="HTML")
            return
        except Exception:
            pass
    try:
        await bot.send_message(chat_id=chat_id, text=final, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        print(f"[BOT] finish notify failed: {e}", flush=True)


async def show_task_log(query, task_id: str, *, from_notifications: bool = False):
    """Показать лог задачи.

    from_notifications=True — пришли из «Просмотр уведомлений»; «Назад» ведёт
    в журнал, а не в меню Задачи.
    Если задачи нет в памяти — пробуем output из events.json.
    """
    task_id = (task_id or "").strip()
    task = task_manager.get_task(task_id) if task_id else None

    def _back_kb():
        rows = []
        if from_notifications:
            rows.append([InlineKeyboardButton("⬅️ К уведомлениям", callback_data="view_notifications")])
        else:
            rows.append([InlineKeyboardButton("⬅️ Задачи", callback_data="tasks")])
        rows.append([InlineKeyboardButton("🏠 Меню", callback_data="main")])
        return InlineKeyboardMarkup(rows)

    if not task:
        output = None
        title = None
        try:
            from core.events import load_events
            for e in reversed(load_events() or []):
                d = e.get("details") or {}
                if str(d.get("task_id") or "") == task_id:
                    output = d.get("output")
                    title = e.get("title") or d.get("task_name")
                    if output:
                        break
        except Exception:
            pass

        if output:
            body = str(output).strip()
            if len(body) > 3500:
                body = "…\n" + body[-3500:]
            text = f"📜 Журнал (из события)\n<code>{html_module.escape(task_id)}</code>\n"
            if title:
                text += f"{html_module.escape(str(title))}\n\n"
            text += (
                "<i>Задачи уже нет в памяти Task Manager "
                "(рестарт бота или история переполнена). "
                "Показан сохранённый вывод из журнала событий.</i>\n\n"
                f"<code>{html_module.escape(body)}</code>"
            )
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=_back_kb())
            return

        await query.edit_message_text(
            "Задача не найдена.\n\n"
            "Возможные причины:\n"
            "• бот перезапускался (история задач только в памяти);\n"
            "• задача вытеснена из истории;\n"
            "• неверный id.\n\n"
            f"id: <code>{html_module.escape(task_id or '—')}</code>",
            parse_mode="HTML",
            reply_markup=_back_kb(),
        )
        return

    if task.is_done:
        emoji = STATUS_EMOJI.get(task.status, "•")
        body = "\n".join(task.output_lines) or ((task.result.output if task.result else "") or "—")
        if len(body) > 3500:
            body = "…\n" + body[-3500:]
        text = (
            f"{emoji} Журнал · <code>{html_module.escape(task.id)}</code>\n\n"
            f"📜 {html_module.escape(task.name)}\n🖥 {html_module.escape(task.server_name)}\n"
            f"Статус: {_status_label(task)}\n"
            f"Длительность: {task.duration_human()}\n\n"
            f"{html_module.escape(body)}"
        )
        rows = kb_done_rows(task.server_id, _nav_rows_for_task(task), task_id=None, task=task)
        if from_notifications:
            rows = [[InlineKeyboardButton("⬅️ К уведомлениям", callback_data="view_notifications")]] + rows
        kb = InlineKeyboardMarkup(rows)
    else:
        text = format_log_text(task)
        base = kb_log(task.server_id, task_id)
        if from_notifications:
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ К уведомлениям", callback_data="view_notifications")]]
                + list(base.inline_keyboard)
            )
        else:
            kb = base
    try:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        LOG_VIEWS[task_id] = query.message
    except Exception:
        msg = await query.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
        LOG_VIEWS[task_id] = msg



async def show_tasks_menu(query):
    await query.edit_message_text(
        "📋 Задачи\n\nВыберите тип:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📜 Скрипты", callback_data="scripts")],
            [InlineKeyboardButton("🛡 WireGuard", callback_data="tasks_svc:wireguard")],
            # У Docker собственный хаб (owns_hub): проверка / установка /
            # Compose / серверы — диспетчер отдаст ему op "hub".
            [InlineKeyboardButton("🐳 Docker", callback_data="tasks_svc:docker")],
            [InlineKeyboardButton("📋 Очереди", callback_data="task_queues")],
            [InlineKeyboardButton("⬅️ Главное меню", callback_data="main")],
        ]),
    )


async def show_queues_overview(query):
    servers = load_servers()
    rows = []
    text_lines = ["📋 Очереди задач\n"]
    any_active = False
    for server in servers:
        sid = server["id"]
        running = task_manager.get_running(sid)
        queue = task_manager.get_queue(sid)
        st = task_manager.get_queue_state(sid)
        if not running and not queue and not st.paused:
            continue
        any_active = True
        parts = []
        if running:
            parts.append(f"▶ {running.name}")
        if queue:
            parts.append(f"⏳ +{len(queue)}")
        if st.paused:
            parts.append("⏸")
        label = f"{server['name']} · {' · '.join(parts)}"
        rows.append([InlineKeyboardButton(label, callback_data=f"task_queue:{sid}")])
        text_lines.append(f"• {label}")
    text_lines.append("\nСейчас ничего не выполняется." if not any_active else "\nВыберите сервер:")
    rows.append([InlineKeyboardButton("⬅️ Задачи", callback_data="tasks")])
    rows.append([InlineKeyboardButton("🏠 Меню", callback_data="main")])
    await query.edit_message_text("\n".join(text_lines), reply_markup=InlineKeyboardMarkup(rows))


async def show_server_queue(query, server_id: str):
    server = find_server(server_id)
    name = server["name"] if server else server_id
    running = task_manager.get_running(server_id)
    queue = task_manager.get_queue(server_id)
    st = task_manager.get_queue_state(server_id)
    text = f"📋 Очередь · {name}\n\n"
    if st.paused:
        text += f"⏸ На паузе\nПричина: «{st.failed_task_name or '?'}»\nПовторов: {st.retry_count}\n\n"
    text += (
        f"▶ Сейчас: {running.name}\n   id: `{running.id}` · попытка {running.attempt}\n\n"
        if running else "▶ Активной задачи нет\n\n"
    )
    if queue:
        text += "⏳ В очереди:\n" + "".join(f"  {i}. {t.name}\n" for i, t in enumerate(queue, 1))
    else:
        text += "⏳ Очередь пуста\n"
    kb = []
    if running:
        kb.append([InlineKeyboardButton("📜 Лог текущей задачи", callback_data=f"task_log:{running.id}")])
    if st.paused:
        kb.append([InlineKeyboardButton("▶ Продолжить", callback_data=f"task_continue:{server_id}")])
        kb.append([
            InlineKeyboardButton("🔄 Повторить", callback_data=f"task_retry:{server_id}"),
            InlineKeyboardButton("⏹ Очистить", callback_data=f"task_clear:{server_id}"),
        ])
    kb.append([InlineKeyboardButton("🔄 Обновить", callback_data=f"task_queue:{server_id}")])
    kb.append([InlineKeyboardButton("📋 Все очереди", callback_data="task_queues")])
    kb.append([InlineKeyboardButton("⬅️ Задачи", callback_data="tasks")])
    kb.append([InlineKeyboardButton("🏠 Меню", callback_data="main")])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))


async def process_task_callback(query, data: str) -> bool:
    if data == "tasks":
        await show_tasks_menu(query)
    elif data == "noop":
        await query.answer()
    elif data == "task_queues":
        await show_queues_overview(query)
    elif data.startswith("task_queue:"):
        await show_server_queue(query, data.split(":", 1)[1])
    elif data.startswith("task_log:"):
        # task_log:<id>  или  task_log:<id>:notif
        parts = data.split(":")
        tid = parts[1] if len(parts) > 1 else ""
        from_notif = len(parts) > 2 and parts[2] == "notif"
        await show_task_log(query, tid, from_notifications=from_notif)
    elif data.startswith("task_continue:"):
        sid = data.split(":", 1)[1]
        ok = await task_manager.continue_queue(sid)
        await query.answer("Очередь продолжена" if ok else "Очередь не на паузе")
        await show_server_queue(query, sid)
    elif data.startswith("task_retry:"):
        sid = data.split(":", 1)[1]
        t = await task_manager.retry_last_failed(sid)
        await query.answer(f"Повтор: {t.name}" if t else "Нечего повторять")
        await show_server_queue(query, sid)
    elif data.startswith("task_clear:"):
        sid = data.split(":", 1)[1]
        n = await task_manager.clear_queue(sid)
        await query.answer(f"Очищено задач: {n}")
        await show_server_queue(query, sid)
    else:
        return False
    return True