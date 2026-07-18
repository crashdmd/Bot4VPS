from pathlib import Path
from core.notification_queue import get_pending_notifications, mark_as_sent, clear_sent
from core.event_types import EventReason

async def process_notifications(update, notification_handlers: dict):
    """Обработка очереди уведомлений (новая версия)"""
    pending = get_pending_notifications()
    if not pending:
        return
    remaining = []
    for item in pending:
        handler = notification_handlers.get(item["type"])
        if not handler:
            remaining.append(item)
            continue
        try:
            if update and hasattr(update, 'effective_chat') and update.effective_chat:
                processed = await handler(update, item)   # ← await теперь работает
            else:
                processed = False

            if processed:
                mark_as_sent(item["id"])
            else:
                remaining.append(item)
        except Exception as e:
            print(f"[NOTIF ERROR] {item['type']}: {e}", flush=True)
            remaining.append(item)

    if not remaining:
        clear_sent()

async def handle_critical_event(update, notification):
    """Универсальный обработчик критических событий"""
    title = notification.get("title", "Критическое событие")
    message = notification.get("message", "")
    details = notification.get("details", {}) or notification.get("data", {})
    source = details.get("source", "")
    reason = details.get("reason")

    text = f"🚨 {title}\n\n{message}"
    if source:
        text += f"\nИсточник: {source}"

    try:
        if update and hasattr(update, "effective_chat") and update.effective_chat:
            bot = update.get_bot()

            # Отправляем уведомление
            await bot.send_message(
                chat_id=update.effective_chat.id,
                text=text
            )

            # После восстановления базы показываем главное меню
            if reason == EventReason.DATABASE_RESTORED.value:
                from ui.telegram.common import build_main_menu

                await bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="🏠 Bot4VPS\n\nВыберите действие:",
                    reply_markup=build_main_menu()
                )

        elif update and hasattr(update, "message") and update.message:
            await update.message.reply_text(text)

        # Отмечаем событие прочитанным
        event_id = notification.get("event_id") or notification.get("id")
        if event_id:
            from core.events import mark_as_read
            mark_as_read(event_id)
            print(f"[NOTIF] Событие {event_id} отмечено как прочитанное", flush=True)

    except Exception as e:
        print(f"[NOTIF ERROR] {e}", flush=True)

    return True