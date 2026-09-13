import asyncio
import time
import uuid

from telegram import InlineKeyboardMarkup, InlineKeyboardButton

from core.notification_queue import (
    claim_notification,
    complete_notification,
    get_pending_notifications,
    release_notification,
)
from core.event_types import EventReason
from core.events import get_event, mark_as_read
from core.telegram_health import (
    record_delivery_result,
    send_telegram_message,
)


def _format_backup_size(value) -> str:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return ""
    units = ("Б", "КБ", "МБ", "ГБ", "ТБ")
    size = float(value)
    unit = units[0]
    for candidate in units:
        unit = candidate
        if size < 1024 or candidate == units[-1]:
            break
        size /= 1024
    return f"{int(size)} {unit}" if unit == "Б" else f"{size:.2f} {unit}"


def format_event_text(notification: dict) -> str:
    """
    Единая точка оформления текста уведомления.
    """
    title = notification.get("title", "Событие")
    message = notification.get("message", "")
    details = notification.get("details") or notification.get("data") or {}
    source = details.get("source", "")
    reason = details.get("reason")
    level = notification.get("level", "critical")

    if reason in (
        EventReason.BACKUP_COMPLETED.value,
        EventReason.BACKUP_FAILED.value,
        EventReason.BACKUP_CANCELLED.value,
    ):
        server_name = str(details.get("server_name") or "").strip()
        backup_filename = str(details.get("backup_filename") or "").strip()
        if backup_filename.lower().endswith(".tar.gz"):
            backup_filename = backup_filename[:-7]
        backup_size = _format_backup_size(details.get("backup_bytes"))
        launch_method = (
            "⏰ По расписанию"
            if details.get("mode") == "automatic"
            else "▶️ Вручную"
        )
        if reason == EventReason.BACKUP_COMPLETED.value:
            heading = "✅ Резервная копия создана"
        elif reason == EventReason.BACKUP_CANCELLED.value:
            heading = "⚠️ Создание резервной копии отменено"
        else:
            heading = "❌ Не удалось создать резервную копию"
        lines = [heading, ""]
        if server_name:
            lines.append(f"Сервер: {server_name}")
        if backup_filename:
            lines.append(f"Backup: {backup_filename}")
        if backup_size:
            lines.append(f"Размер: {backup_size}")
        lines.append(launch_method)
        if reason == EventReason.BACKUP_COMPLETED.value:
            lines.append(message or "Backup опубликован успешно.")
        elif reason == EventReason.BACKUP_CANCELLED.value:
            lines.append(message or "Создание резервной копии отменено.")
        else:
            error = details.get("error") or {}
            error_message = message or error.get("message") or "Не удалось создать backup."
            lines.extend(("Причина:", str(error_message)))
        return "\n".join(lines)

    if reason in (
        EventReason.RESTORE_COMPLETED.value,
        EventReason.RESTORE_FAILED.value,
        EventReason.RESTORE_CANCELLED.value,
    ):
        server_name = str(details.get("server_name") or "").strip()
        backup_filename = str(details.get("backup_filename") or "").strip()
        if backup_filename.lower().endswith(".tar.gz"):
            backup_filename = backup_filename[:-7]
        succeeded = reason == EventReason.RESTORE_COMPLETED.value
        cancelled = reason == EventReason.RESTORE_CANCELLED.value
        mode_line = (
            "Режим: чистое восстановление"
            if details.get("mode") == "clean"
            else "Режим: обычное восстановление"
        )
        if succeeded:
            heading = "✅ Восстановление завершено"
        elif cancelled:
            heading = "⚠️ Восстановление отменено"
        else:
            heading = "❌ Восстановление не выполнено"
        lines = [heading, ""]
        if server_name:
            lines.append(f"Сервер: {server_name}")
        if backup_filename:
            lines.append(f"Backup: {backup_filename}")
        lines.append(mode_line)
        if succeeded:
            lines.append(message or "Данные из backup записаны на сервер, результат проверен.")
        elif cancelled:
            lines.append(message or "Восстановление отменено пользователем.")
        else:
            error = details.get("error") or {}
            error_message = message or error.get("message") or "Не удалось выполнить восстановление."
            lines.extend(("Причина:", str(error_message)))
            if level == "critical":
                # Провал после начала изменения target: автоматический откат не
                # делается, поэтому явно называем защитную копию для ручного возврата.
                protective = str(details.get("protective_backup") or "").strip()
                if protective.lower().endswith(".tar.gz"):
                    protective = protective[:-7]
                lines.append(
                    "⚠️ Данные на сервере могли измениться частично — "
                    "автоматический откат не выполняется."
                )
                if protective:
                    lines.append(f"Защитная копия для ручного возврата: {protective}")
        return "\n".join(lines)

    task_emoji = {
        EventReason.TASK_QUEUED.value: "⏳",
        EventReason.TASK_FINISHED.value: "✅",
        EventReason.TASK_FAILED.value: "❌",
        EventReason.TASK_CANCELLED.value: "⚠️",
        EventReason.TASK_QUEUE_PAUSED.value: "⏸️",
    }
    if reason in task_emoji:
        emoji = task_emoji[reason]
    elif reason in (
        EventReason.SERVER_ONLINE.value,
        EventReason.SSL_RENEWED.value,
    ):
        emoji = "✅"
    elif level == "critical":
        emoji = "🚨"
    elif level == "warning":
        emoji = "⚠️"
    else:
        emoji = "ℹ️"

    text = f"{emoji} {title}\n\n{message}"
    if source:
        text += f"\nИсточник: {source}"
    return text


def _menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main")]
    ])


# --------------------------------------------------------------
# Аккумулирующее сообщение-уведомление
# --------------------------------------------------------------
# chat_id → {"message_id": int, "event_ids": [str]} — живое сообщение
# уведомления в чате. Пока оно не прочитано (не нажата кнопка на нём),
# новые события НЕ рассылаются отдельными сообщениями: живое сообщение
# редактируется в сводку и дополняется («первое пришло сообщением,
# второе превратило его в сводку, третье обновило сводку»).
#
# Кнопка «⬅️ Назад» / «🏠 Главное меню» / «🔄 Перезагрузить» / «✅ Прочитано»
# на сообщении помечает ВСЕ его события прочитанными и закрывает
# аккумулятор — следующее событие начнёт новое сообщение.
#
# Карта живёт в памяти: после рестарта теряется — события остаются
# непрочитанными и добираются через Web/сводку, ничего не теряется.
_ACCUMULATORS: dict = {}


def _event_unread(event_id) -> bool:
    event = get_event(event_id) if event_id else None
    return event is not None and event.get("read") is not True


def _accumulator_unread_ids(chat_id) -> list:
    """Непрочитанные события живого сообщения чата (с чисткой от прочитанных).

    Если всё прочитано/удалено — аккумулятор закрывается, возвращается [].
    """
    acc = _ACCUMULATORS.get(chat_id)
    if not acc:
        return []
    ids = [eid for eid in acc.get("event_ids", []) if _event_unread(eid)]
    if not ids:
        _ACCUMULATORS.pop(chat_id, None)
        return []
    acc["event_ids"] = ids
    return ids


def mark_message_event_read(chat_id, message_id, *, action: str = "") -> bool:
    """Кнопка нажата на живом сообщении-уведомлении — обработать прочтение.

    Аккумулятор закрывается любым нажатием: сообщение либо уходит в
    навигацию по сводке, либо заменяется видом меню — живым уведомлением
    оно быть перестало. Помечаются ли события прочитанными — зависит
    от кнопки:

    - навигация по сводке (notif:g / notif:e / notif:d) — нет: метки NEW
      должны дожить до журнала, события гасятся открытием карточек;
    - сводка из 2+ событий — только явное «✅ Прочитано» (notif:r) гасит
      всё разом; «Главное меню» под сводкой прочтением не считается —
      пользователь видел лишь счётчики, читать он пойдёт в журнал;
    - одиночное событие — любая кнопка («⬅️ Назад», «🏠 Главное меню»,
      «🔄 Перезагрузить») помечает его прочитанным.

    Возвращает True, если нажатие пришлось на живое сообщение-уведомление
    этого чата; кнопки на прочих сообщениях — no-op.
    """
    acc = _ACCUMULATORS.get(chat_id)
    if not acc or acc.get("message_id") != message_id:
        return False
    _ACCUMULATORS.pop(chat_id, None)
    if action.startswith(("notif:g:", "notif:e:", "notif:d:")):
        return True
    if len(acc.get("event_ids", [])) > 1 and not action.startswith("notif:r:"):
        return True
    for event_id in acc.get("event_ids", []):
        if _event_unread(event_id):
            mark_as_read(event_id)
    return True


async def _deliver_to_chat(
    bot, chat_id, *, notification=None, event_ids=None
) -> bool:
    """Отправить или ОБНОВИТЬ сообщение-уведомление в чате.

    Аккумуляция: если в чате уже висит непрочитанное сообщение-уведомление,
    оно редактируется в сводку с добавлением новых событий; отдельное
    сообщение не рассылается. При провале правки (сообщение удалено и
    т.п.) — отправка нового сообщения. Возвращает True, когда в чате
    есть актуальное сообщение (или обновлять нечего — всё прочитано).
    """
    new_ids = [eid for eid in (event_ids or []) if eid]
    base_ids = _accumulator_unread_ids(chat_id)
    ids = base_ids + [eid for eid in new_ids if eid not in base_ids]
    if not ids:
        # Всё уже прочитано/удалено (например, через Web) — молча.
        return True

    if len(ids) == 1 and notification is not None:
        text = format_event_text(notification)
        kb = _event_keyboard(notification, user_id=chat_id)
    else:
        digest_id = _register_digest(ids)
        text, kb = _digest_summary(digest_id)

    acc = _ACCUMULATORS.get(chat_id)
    editor = getattr(bot, "edit_message_text", None)
    if acc is not None and base_ids and callable(editor):
        try:
            await editor(
                chat_id=chat_id,
                message_id=acc["message_id"],
                text=text,
                reply_markup=kb,
            )
        except Exception as e:
            if "message is not modified" in str(e).lower():
                # Текст не изменился (повторная доставка тех же событий).
                acc["event_ids"] = ids
                return True
            # Сообщение удалено/недоступно для правки — шлём новое.
            print(
                f"[NOTIF] аккумулирующая правка не удалась: {type(e).__name__}",
                flush=True,
            )
        else:
            acc["event_ids"] = ids
            return True

    sent = await send_telegram_message(bot, chat_id=chat_id, text=text, reply_markup=kb)
    message_id = getattr(sent, "message_id", None)
    if message_id is not None:
        _ACCUMULATORS[chat_id] = {"message_id": message_id, "event_ids": ids}
    return True


def _event_keyboard(notification=None, *, user_id=None):
    """Build a recipient-specific keyboard for an event notification."""
    details = (notification or {}).get("details") or (notification or {}).get("data") or {}
    reason = details.get("reason")

    callback_user_id = None
    if isinstance(user_id, int) and not isinstance(user_id, bool):
        callback_user_id = user_id
    elif isinstance(user_id, str):
        try:
            callback_user_id = int(user_id)
        except ValueError:
            pass

    if callback_user_id is not None:
        from ui.telegram.handlers.backup_handlers import (
            backup_result_callback,
            backup_result_reboot_callback,
        )

        back_callback = backup_result_callback(callback_user_id, notification or {})
        if back_callback:
            rows = []
            reboot_callback = backup_result_reboot_callback(
                callback_user_id,
                notification or {},
            )
            if reboot_callback:
                rows.append([
                    InlineKeyboardButton(
                        "🔄 Перезагрузить сервер",
                        callback_data=reboot_callback,
                    )
                ])
            rows.extend([
                [InlineKeyboardButton("⬅️ Назад", callback_data=back_callback)],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main")],
            ])
            return InlineKeyboardMarkup(rows)

    if details.get("initiated_from_telegram") is True and reason in (
        EventReason.BACKUP_COMPLETED.value,
        EventReason.BACKUP_FAILED.value,
        EventReason.BACKUP_CANCELLED.value,
        EventReason.RESTORE_COMPLETED.value,
        EventReason.RESTORE_FAILED.value,
        EventReason.RESTORE_CANCELLED.value,
    ):
        return _menu_keyboard()

    # Не-Telegram Restore-события сохраняют прежнюю общую навигацию.
    if reason in (
        EventReason.RESTORE_COMPLETED.value,
        EventReason.RESTORE_FAILED.value,
    ):
        server_id = details.get("server_id")
        if server_id:
            return InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Перезагрузить сервер", callback_data=f"reboot_confirm:{server_id}")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main")],
            ])
    return _menu_keyboard()


async def send_event_notification(bot, notification: dict, event_id: str = None):
    """
    Отправляет уведомление всем allowed_users с кнопкой возврата в меню.

    Для обычного queue-first event сначала закрепляется durable claim. Для
    journal-only Telegram result event claim не нужен: queue появится только
    если dispatch_notifiers зафиксирует полный провал immediate-доставки.
    Возвращает True при доставке хотя бы одному получателю.

    При включённой агрегации (AGGREGATION_WINDOW > 0) событие сначала
    попадает в буфер: если за окно накопилось больше одного события, всем
    отправляется одна сводка (digest) вместо потока сообщений.
    """
    journal_only = notification.get("_journal_only") is True
    buffered = AGGREGATION_WINDOW > 0

    owner = f"immediate:{uuid.uuid4().hex}"
    queue_id = None
    if event_id:
        if journal_only and not buffered:
            # Синхронный путь: без queue-row; при провале вернём False и
            # dispatch_notifiers сам поставит fallback.
            return await _deliver_single(bot, {
                "queue_id": None,
                "owner": owner,
                "event_id": event_id,
                "notification": notification,
            })
        if journal_only:
            # Пока событие сидит в буфере, fallback-очередь должна существовать:
            # ставим сами (идемпотентно по event_id).
            from core.event_service import enqueue_event
            enqueue_event(
                event_id=event_id,
                event_type=notification.get("type", ""),
                level=notification.get("level", ""),
                title=notification.get("title", "Событие"),
                message=notification.get("message", ""),
                details=notification.get("details") or notification.get("data") or {},
            )
        claimed = claim_notification(owner, event_id=event_id)
        if claimed is None:
            return False
        queue_id = claimed.get("id")

    entry = {
        "queue_id": queue_id,
        "owner": owner,
        "event_id": event_id,
        "notification": notification,
    }
    if not buffered:
        return await _deliver_single(bot, entry)
    _buffer_entry(bot, entry)
    # Ответ «принято в доставку»: fallback лежит в очереди под нашим claim.
    return True


async def _deliver_single(bot, entry: dict) -> bool:
    """Доставка одного события — прежнее поведение send_event_notification."""
    queue_id = entry["queue_id"]
    owner = entry["owner"]
    event_id = entry["event_id"]
    notification = entry["notification"]

    from core.config import load_config

    try:
        # Web UI мог отметить событие прочитанным до отправки — не дублируем.
        if event_id:
            event = get_event(event_id)
            if event is None or event.get("read") is True:
                if queue_id:
                    complete_notification(queue_id, owner)
                    queue_id = None
                return True

        config = load_config()
        allowed = config.get("allowed_users", [])

        delivered = 0
        for user_id in allowed:
            try:
                # Отправка/обновление аккумулирующего сообщения: пока
                # предыдущее уведомление не прочитано, новые события
                # дополняют его правкой, а не новым сообщением.
                await _deliver_to_chat(
                    bot,
                    user_id,
                    notification=notification,
                    event_ids=[event_id] if event_id else [],
                )
                delivered += 1
                record_delivery_result(
                    token=str(getattr(bot, "token", "") or ""),
                    chat_id=user_id,
                )
            except Exception as e:
                record_delivery_result(
                    token=str(getattr(bot, "token", "") or ""),
                    chat_id=user_id,
                    error=e,
                )
                print(
                    f"[NOTIF] Telegram delivery failed: {type(e).__name__}",
                    flush=True,
                )

        # Не считаем доставленной при полном провале рассылки.
        if queue_id and delivered > 0:
            if complete_notification(queue_id, owner):
                queue_id = None
        return delivered > 0
    finally:
        if queue_id:
            release_notification(queue_id, owner)


# --------------------------------------------------------------
# Агрегация: пачка событий → одна сводка
# --------------------------------------------------------------

# Окно тишины (сек): если за него пришло ещё событие, таймер сбрасывается.
AGGREGATION_WINDOW = 2.0
# Жёсткий потолок ожидания с первого события в буфере.
AGGREGATION_MAX_WAIT = 6.0
# При столько накопленных событиях сводка уходит не дожидаясь окна.
AGGREGATION_MAX_ITEMS = 60

_PENDING_DELIVERIES: list = []
_FLUSH_TASK = None
_FIRST_BUFFERED_AT: float | None = None


def _reschedule_flush(bot, delay: float) -> None:
    """(Пере)запустить таймер отправки буфера. Только внутри loop."""
    global _FLUSH_TASK
    if _FLUSH_TASK is not None and not _FLUSH_TASK.done():
        _FLUSH_TASK.cancel()
    _FLUSH_TASK = asyncio.ensure_future(_delayed_flush(bot, delay))


def _buffer_entry(bot, entry: dict) -> None:
    """Положить событие в буфер и (пере)запустить таймер отправки."""
    global _FIRST_BUFFERED_AT
    _PENDING_DELIVERIES.append(entry)
    now = time.time()
    if _FIRST_BUFFERED_AT is None:
        _FIRST_BUFFERED_AT = now
    if len(_PENDING_DELIVERIES) >= AGGREGATION_MAX_ITEMS:
        delay = 0.0
    else:
        delay = min(
            AGGREGATION_WINDOW,
            max(0.0, _FIRST_BUFFERED_AT + AGGREGATION_MAX_WAIT - now),
        )
    # Буфер агрегации живёт на основном loop панели. Источники из потоков
    # (например, завершение бэкапа: asyncio.run в worker-потоке) имеют
    # собственный недолговечный loop — ensure_future на нём умирал вместе
    # с loop'ом, и уведомление молча терялось, оставляя мёртвый claim.
    main = _MAIN_LOOP
    current = asyncio.get_running_loop()
    if main is not None and main is not current and main.is_running():
        main.call_soon_threadsafe(_reschedule_flush, bot, delay)
        return
    _reschedule_flush(bot, delay)


async def _delayed_flush(bot, delay: float) -> None:
    try:
        if delay > 0:
            await asyncio.sleep(delay)
        await flush_pending(bot)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        # Записи уже забраны из буфера и лежат под нашим claim —
        # после истечения TTL (5 мин) их подберёт catch-up дрейн.
        print(f"[NOTIF] digest flush failed: {e}", flush=True)


async def flush_pending(bot=None) -> bool:
    """Немедленно отправить всё накопленное: одно событие — как раньше,
    несколько — единой сводкой. Вызывается таймером агрегации."""
    global _FIRST_BUFFERED_AT, _FLUSH_TASK
    if _FLUSH_TASK is not None and not _FLUSH_TASK.done():
        _FLUSH_TASK.cancel()
    _FLUSH_TASK = None
    entries = list(_PENDING_DELIVERIES)
    _PENDING_DELIVERIES.clear()
    _FIRST_BUFFERED_AT = None
    if not entries:
        return True
    if len(entries) == 1:
        return await _deliver_single(bot, entries[0])
    return await _deliver_digest(bot, entries)


_DIGESTS: dict = {}
_DIGEST_TTL_SECONDS = 24 * 3600
_DIGEST_PAGE_SIZE = 8

_LEVEL_ORDER = ("critical", "warning", "info")
_LEVEL_LABELS = {
    "critical": "🔴 Критические",
    "warning": "⚠️ Обратить внимание",
    "info": "ℹ️ Информационные",
}


def _register_digest(event_ids) -> str:
    now = time.time()
    for stale in [k for k, v in _DIGESTS.items() if now - v["ts"] > _DIGEST_TTL_SECONDS]:
        del _DIGESTS[stale]
    digest_id = uuid.uuid4().hex[:12]
    _DIGESTS[digest_id] = {"events": list(event_ids), "ts": now}
    return digest_id


def _digest_events(digest_id: str):
    """События дайджеста из журнала; None, если сводка устарела."""
    info = _DIGESTS.get(digest_id)
    if not info:
        return None
    events = []
    for event_id in info["events"]:
        event = get_event(event_id)
        if event is not None:
            events.append(event)
    return events


def _stale_digest_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 Журнал событий", callback_data="view_notifications")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main")],
    ])


def _digest_summary(digest_id: str):
    """Текст и клавиатура сводки."""
    events = _digest_events(digest_id)
    if events is None:
        return (
            "📭 Сводка устарела (бот перезапускался).\n\n"
            "Последние события доступны в журнале.",
            _stale_digest_kb(),
        )

    counts = {level: 0 for level in _LEVEL_ORDER}
    for event in events:
        counts[event.get("level") if event.get("level") in _LEVEL_ORDER else "info"] += 1
    unread = sum(1 for event in events if not event.get("read"))

    lines = [f"📬 Уведомления: {len(events)}", ""]
    for level in _LEVEL_ORDER:
        lines.append(f"{_LEVEL_LABELS[level]}: {counts[level]}")
    if unread and unread != len(events):
        lines.append("")
        lines.append(f"Не прочитано: {unread}")

    rows = [[
        InlineKeyboardButton(
            "📜 Посмотреть все",
            callback_data=f"notif:g:{digest_id}:all:0",
        ),
        InlineKeyboardButton(
            "✅ Прочитано",
            callback_data=f"notif:r:{digest_id}",
        ),
    ]]
    for level in _LEVEL_ORDER:
        if counts[level]:
            rows.append([InlineKeyboardButton(
                f"{_LEVEL_LABELS[level]} · {counts[level]}",
                callback_data=f"notif:g:{digest_id}:{level}:0",
            )])
    rows.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def _digest_group(digest_id: str, level: str, page: int):
    """Список событий одной группы (или всех) с постраничной навигацией."""
    events = _digest_events(digest_id)
    if events is None:
        return (
            "📭 Сводка устарела (бот перезапускался).\n\n"
            "Последние события доступны в журнале.",
            _stale_digest_kb(),
        )

    # Свежие сверху
    events = [e for e in reversed(events) if level == "all" or e.get("level") == level]
    total = len(events)
    pages = max(1, (total + _DIGEST_PAGE_SIZE - 1) // _DIGEST_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = events[page * _DIGEST_PAGE_SIZE:(page + 1) * _DIGEST_PAGE_SIZE]

    # Подписи событий — те же хелперы, что и в журнале админки
    from ui.telegram.handlers.admin_handlers import _list_button_label

    rows = []
    for index, event in enumerate(chunk):
        button = InlineKeyboardButton(
            _list_button_label(event),
            callback_data=(
                f"notif:e:{digest_id}:{level}:{page}:{str(event.get('id', ''))[:16]}"
            ),
        )
        # Чётное число — два столбика; непарная последняя запись
        # растягивается на всю ширину ряда — без пустых ячеек.
        if index % 2 == 0:
            rows.append([button])
        else:
            rows[-1].append(button)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"notif:g:{digest_id}:{level}:{page - 1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"notif:g:{digest_id}:{level}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([
        InlineKeyboardButton("⬅️ К сводке", callback_data=f"notif:d:{digest_id}"),
        InlineKeyboardButton("🏠 Меню", callback_data="main"),
    ])

    if not events:
        text = "📭 В этой группе событий нет."
    else:
        title = "Все уведомления" if level == "all" else _LEVEL_LABELS.get(level, level)
        text = f"{title} · {total}"
        if any(not e.get("read") for e in chunk):
            text += "\n\nNEW — не прочитано"
    return text, InlineKeyboardMarkup(rows)


async def _digest_event_view(query, digest_id: str, level: str, page: int, prefix: str):
    """Карточка события из сводки: полный текст + кнопки действия."""
    events = _digest_events(digest_id) or []
    event = next(
        (e for e in events if str(e.get("id", "")).startswith(prefix)),
        None,
    )
    if event is None:
        await query.answer("Событие не найдено", show_alert=True)
        return

    # Открыл карточку — значит прочитал: помечаем, чтобы при возврате к
    # списку событие потеряло метку 🆕 (и выпало из «Не прочитано»).
    if not event.get("read"):
        await asyncio.to_thread(mark_as_read, event["id"])

    text = format_event_text(event)
    back = f"notif:g:{digest_id}:{level}:{page}"

    rows = []
    for row in _event_keyboard(event, user_id=query.from_user.id).inline_keyboard:
        # Своё «Назад/Меню» добавляем ниже — от общей клавиатуры
        # оставляем только специфичные кнопки (перезагрузка, backup-навигация)
        if all(button.callback_data == "main" for button in row):
            continue
        rows.append(list(row))
    rows.append([
        InlineKeyboardButton("⬅️ Назад", callback_data=back),
        InlineKeyboardButton("🏠 Главное меню", callback_data="main"),
    ])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def _digest_read_all(query, digest_id: str):
    """Отметить все события сводки прочитанными."""
    from core.events import mark_as_read

    events = _digest_events(digest_id)
    if events is None:
        await query.edit_message_text(
            "📭 Сводка устарела (бот перезапускался).",
            reply_markup=_stale_digest_kb(),
        )
        return

    marked = 0
    for event in events:
        if not event.get("read"):
            await asyncio.to_thread(mark_as_read, event["id"])
            marked += 1

    await query.answer(
        f"Отмечено прочитанными: {marked}" if marked else "Уже прочитаны"
    )
    await query.edit_message_text(
        f"✅ Все уведомления ({len(events)}) отмечены прочитанными.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📜 Журнал событий", callback_data="view_notifications")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main")],
        ]),
    )


async def process_notification_digest_callback(query, data: str) -> bool:
    """Маршрутизация кнопок сводки: notif:d|g|e|r:<digest>..."""
    if not data.startswith("notif:"):
        return False
    parts = data.split(":")
    kind = parts[1] if len(parts) > 1 else ""

    if kind == "d" and len(parts) == 3:
        text, kb = _digest_summary(parts[2])
        await query.edit_message_text(text, reply_markup=kb)
        return True

    if kind == "g" and len(parts) == 5:
        try:
            page = int(parts[4])
        except ValueError:
            page = 0
        text, kb = _digest_group(parts[2], parts[3], page)
        await query.edit_message_text(text, reply_markup=kb)
        return True

    if kind == "e" and len(parts) == 6:
        try:
            page = int(parts[4])
        except ValueError:
            page = 0
        await _digest_event_view(query, parts[2], parts[3], page, parts[5])
        return True

    if kind == "r" and len(parts) == 3:
        await _digest_read_all(query, parts[2])
        return True

    return False


async def _deliver_digest(bot, entries: list, chat_ids=None) -> bool:
    """Отправить сводку по пачке событий и закрыть их queue-claims.

    chat_ids=None — всем allowed_users (push-путь); иначе конкретному чату
    (catch-up дрейн отвечает в чат нажавшего кнопку).
    """
    live = []
    for entry in entries:
        event_id = entry.get("event_id")
        event = get_event(event_id) if event_id else None
        if event is None or event.get("read") is True:
            # Уже прочитано/удалено через Web — тихо закрываем
            print(
                f"[NOTIF] событие {event_id} "
                f"({'отсутствует в журнале' if event is None else 'уже прочитано'})"
                " — доставка пропущена",
                flush=True,
            )
            if entry.get("queue_id"):
                complete_notification(entry["queue_id"], entry["owner"])
        else:
            live.append(entry)

    if not live:
        return True
    if len(live) == 1:
        return await _deliver_single(bot, live[0])

    new_ids = [entry["event_id"] for entry in live if entry.get("event_id")]

    if chat_ids is None:
        from core.config import load_config
        chat_ids = load_config().get("allowed_users", [])

    delivered = 0
    for chat_id in chat_ids:
        try:
            # Сводка тоже доставляется через аккумулятор: если в чате уже
            # висит непрочитанное сообщение-уведомление, пачка дополняет
            # его правкой, а не создаёт новое сообщение.
            await _deliver_to_chat(bot, chat_id, event_ids=new_ids)
            delivered += 1
            record_delivery_result(
                token=str(getattr(bot, "token", "") or ""),
                chat_id=chat_id,
            )
        except Exception as e:
            record_delivery_result(
                token=str(getattr(bot, "token", "") or ""),
                chat_id=chat_id,
                error=e,
            )
            print(
                f"[NOTIF] Telegram digest delivery failed: {type(e).__name__}",
                flush=True,
            )

    for entry in live:
        if entry.get("queue_id"):
            if delivered > 0:
                complete_notification(entry["queue_id"], entry["owner"])
            else:
                release_notification(entry["queue_id"], entry["owner"])
    return delivered > 0


# --------------------------------------------------------------
# Фоновый дрейн очереди: доставка без действия пользователя
# --------------------------------------------------------------

_DELIVERY_BOT = None
_MAIN_LOOP: "asyncio.AbstractEventLoop | None" = None
_DRAIN_JOB_NAME = "notification_drain"
_DRAIN_INTERVAL = 5.0


def set_delivery_bot(bot) -> None:
    """Запомнить бот-инстанс для фоновой доставки (оба входа: uvicorn и
    чистый ТГ). Вызывается при старте Telegram, сбрасывается при остановке.

    Вызов изнутри работающего loop фиксирует и сам loop: источники из
    потоков (завершение бэкапа) диспетчеризуются через asyncio.run на
    временном loop — их буферизованные flush-таски должны жить на loop
    панели, иначе умирают вместе с временным.
    """
    global _DELIVERY_BOT, _MAIN_LOOP
    _DELIVERY_BOT = bot
    if bot is not None:
        try:
            _MAIN_LOOP = asyncio.get_running_loop()
        except RuntimeError:
            _MAIN_LOOP = None
    else:
        _MAIN_LOOP = None
        # Живые сообщения-аккумуляторы привязаны к сессии бота; после
        # остановки ТГ правки невозможны — начинаем с чистого листа.
        _ACCUMULATORS.clear()


async def drain_pending_notifications() -> bool:
    """Фоновый дрейн очереди уведомлений.

    Раньше накопленные события доставались только нажатием кнопки в ТГ.
    Теперь их забирает periodic-job самого процесса панели: одно событие
    уходит обычным сообщением, пачка — единой сводкой. Пуш-путь
    (notify_event → dispatch_notifiers) уже закрепил свои строки claim'ом,
    поэтому здесь остаются только queue-first события (create_event) и
    backlog, накопленный пока Telegram был выключен.
    """
    bot = _DELIVERY_BOT
    if bot is None:
        return False

    pending = get_pending_notifications()
    if not pending:
        return True

    entries = []
    for item in pending:
        queue_id = item.get("id")
        if not isinstance(queue_id, str) or not queue_id:
            continue
        owner = f"drain:{uuid.uuid4().hex}"
        claimed = claim_notification(owner, queue_id=queue_id)
        if claimed is None:
            continue
        entries.append({
            "queue_id": str(claimed["id"]),
            "owner": owner,
            "event_id": claimed.get("event_id"),
            "notification": claimed,
        })
    if not entries:
        return True
    print(f"[NOTIF] фоновый дрейн: доставляю {len(entries)} событий", flush=True)

    try:
        return await _deliver_digest(bot, entries)
    except Exception as e:
        print(f"[NOTIF ERROR] background drain: {e}", flush=True)
        for entry in entries:
            if entry.get("queue_id"):
                release_notification(entry["queue_id"], entry["owner"])
        return False


async def _notification_drain_job(_context) -> None:
    await drain_pending_notifications()


def start_notification_drain_job() -> None:
    """Поднять periodic-дрейн в ядерной JobQueue (идемпотентно).

    Вызывается после успешного старта Telegram: пока бота нет, дрейну
    некому доставлять — backlog подберёт первый же запуск job'ы.
    """
    from core.jobs_runtime import get_core_queue

    queue = get_core_queue()
    if queue is None:
        return
    if queue.get_jobs_by_name(_DRAIN_JOB_NAME):
        return
    queue.run_repeating(
        _notification_drain_job,
        interval=_DRAIN_INTERVAL,
        first=2.0,
        name=_DRAIN_JOB_NAME,
    )
    print(
        f"[NOTIF] фоновый дрейн уведомлений запущен (раз в {_DRAIN_INTERVAL:.0f}с)",
        flush=True,
    )


def stop_notification_drain_job() -> None:
    from core.jobs_runtime import get_core_queue

    queue = get_core_queue()
    if queue is None:
        return
    for job in queue.get_jobs_by_name(_DRAIN_JOB_NAME):
        job.schedule_removal()
