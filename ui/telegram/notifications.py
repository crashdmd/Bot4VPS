import uuid

from telegram import InlineKeyboardMarkup, InlineKeyboardButton

from core.notification_queue import (
    claim_notification,
    complete_notification,
    get_pending_notifications,
    release_notification,
)
from core.event_types import EventReason
from core.events import get_event
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
    """
    from core.config import load_config

    owner = f"immediate:{uuid.uuid4().hex}"
    queue_id = None
    journal_only = notification.get("_journal_only") is True
    if event_id and not journal_only:
        claimed = claim_notification(owner, event_id=event_id)
        if claimed is None:
            return False
        queue_id = claimed.get("id")

    try:
        # Web UI мог отметить событие прочитанным до отправки — не дублируем.
        if event_id:
            event = get_event(event_id)
            if event is None or event.get("read") is True:
                if queue_id:
                    complete_notification(queue_id, owner)
                    queue_id = None
                return True

        text = format_event_text(notification)
        config = load_config()
        allowed = config.get("allowed_users", [])

        delivered = 0
        for user_id in allowed:
            keyboard = _event_keyboard(notification, user_id=user_id)
            try:
                await send_telegram_message(
                    bot,
                    chat_id=user_id,
                    text=text,
                    reply_markup=keyboard,
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


async def process_notifications(update, notification_handlers: dict):
    """Обработка очереди уведомлений"""
    pending = get_pending_notifications()
    if not pending:
        return

    for item in pending:
        handler = notification_handlers.get(item.get("type"))
        queue_id = item.get("id")
        if handler is None or not isinstance(queue_id, str) or not queue_id:
            continue

        owner = f"catchup:{uuid.uuid4().hex}"
        claimed = claim_notification(owner, queue_id=queue_id)
        if claimed is None:
            continue

        claimed_queue_id = str(claimed["id"])
        completed = False
        try:
            # Читаем журнал только после claim: Web UI мог отметить событие
            # прочитанным уже после загрузки snapshot очереди.
            event_id = claimed.get("event_id")
            event = get_event(event_id) if event_id else None
            if event is None or event.get("read") is True:
                completed = complete_notification(claimed_queue_id, owner)
                continue

            if update and hasattr(update, "effective_chat") and update.effective_chat:
                processed = await handler(update, claimed)
            else:
                processed = False

            if processed:
                completed = complete_notification(claimed_queue_id, owner)
        except Exception as e:
            print(f"[NOTIF ERROR] {claimed.get('type')}: {e}", flush=True)
        finally:
            if not completed:
                release_notification(claimed_queue_id, owner)


async def handle_critical_event(update, notification):
    """Обработчик событий из очереди.

    Возвращает True только при успешной отправке; при ошибке элемент
    остаётся в очереди и будет повторён при следующем drain.
    """
    text = format_event_text(notification)

    delivery_bot = None
    delivery_chat_id = None
    try:
        if update and hasattr(update, "effective_chat") and update.effective_chat:
            bot = update.get_bot()
            chat_id = update.effective_chat.id
            delivery_bot = bot
            delivery_chat_id = chat_id
            keyboard = _event_keyboard(notification, user_id=chat_id)
            await send_telegram_message(
                bot,
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
            )
            record_delivery_result(
                token=str(getattr(bot, "token", "") or ""),
                chat_id=chat_id,
            )

        elif update and hasattr(update, "message") and update.message:
            message_chat_id = getattr(update.message, "chat_id", None)
            if message_chat_id is None:
                message_chat_id = getattr(
                    getattr(update.message, "chat", None),
                    "id",
                    None,
                )
            keyboard = _event_keyboard(notification, user_id=message_chat_id)
            await update.message.reply_text(text, reply_markup=keyboard)

    except Exception as e:
        if delivery_bot is not None and delivery_chat_id is not None:
            record_delivery_result(
                token=str(getattr(delivery_bot, "token", "") or ""),
                chat_id=delivery_chat_id,
                error=e,
            )
        print(f"[NOTIF ERROR] Telegram delivery failed: {type(e).__name__}", flush=True)
        return False

    event_id = notification.get("event_id") or notification.get("id")
    if event_id:
        from core.events import mark_as_read
        mark_as_read(event_id)
        print(f"[NOTIF] Событие {event_id} отмечено как прочитанное", flush=True)

    return True
