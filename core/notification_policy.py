"""Политика Telegram-уведомлений: категории и закрытие строк, которые больше
не должны доставляться.

Здесь только чистые таблицы и функции-помощники: их читают и слой доставки
(``ui/telegram/notifications.py``), и настройки (Web/Telegram). Само решение
о доставке конкретного события принимается в момент доставки — см.
``plans/TELEGRAM_NOTIFICATIONS_PLAN.md``, раздел 3.
"""
from typing import Dict, Optional

# --------------------------------------------------------------
# Категории уведомлений (план, §8)
# --------------------------------------------------------------
# Порядок — он же порядок переключателей в Web (Настройки → Общие →
# «Уведомления»). Онлайн/офлайн и SSL здесь СОЗНАТЕЛЬНО отсутствуют: у них нет
# отдельной галочки «присылать», их включает тумблер самой проверки в том же
# блоке — «проверять и сообщать» это одно решение, а не два
# (см. category_enabled).
CATEGORY_ORDER = ("tasks", "services", "updates", "system", "backups")

CATEGORY_LABELS = {
    "tasks": "Задачи",
    "services": "Сервисы",
    "updates": "Обновления",
    "system": "Система",
    "backups": "Резервные копии",
}

# Категории, которыми управляет не список уведомлений, а проверка мониторинга:
# ключ категории → имя секции config.json → monitor.
MANAGED_BY_MONITOR: Dict[str, str] = {
    "online": "online",
    "ssl": "ssl",
}

# Категория определяется по типу события. У резервных копий категория своя
# (``backups``) и она главнее пер-серверных галочек: тонкие настройки в разделе
# «Резервные копии» (создание/восстановление, успех/ошибка) решают, что
# присылать, но выключенная общая категория глушит всё — и журнал, и Telegram
# (решение 2026-09-25). Тип у создания копии и восстановления один
# (``EventType.BACKUP``), поэтому различать их здесь не нужно.
EVENT_TYPE_CATEGORY: Dict[str, str] = {
    "server": "online",
    "task": "tasks",
    "service": "services",
    "ssl": "ssl",
    "update": "updates",
    "backup": "backups",
    "database": "system",
    "general": "system",
    "ssh": "system",
    "key": "system",
    "script": "system",
}

# Причины, по которым событие считается событием доступности: только они
# участвуют в схлопывании «упал и поднялся» (план, §6).
AVAILABILITY_REASONS = frozenset({"server_offline", "server_online"})

# Исключений из выключателя категорий нет: выключенная категория глушит всё
# своего типа, включая аварии самой панели — несовпадение host key и
# восстановление повреждённой базы. Первоначально (§19.4 плана) у этих двух
# аварий был признак «always_notify», обходящий галочку; 2026-09-24 от него
# отказались: галочка должна значить ровно то, что обещает, а обещать в сноске
# настроек «вот это приходит всегда, хотя выключателя у него нет» — путаница.
# Не управляются категориями только коды восстановления доступа и проверка
# Telegram: это не события журнала, они уходят напрямую (ui/web/app.py).


def category_of(event_type: str) -> Optional[str]:
    """Категория события; None — у типа своей настройки (backup) или её нет."""
    if not isinstance(event_type, str):
        return None
    return EVENT_TYPE_CATEGORY.get(event_type)


def is_availability(event_type: str, details: Optional[dict]) -> bool:
    """Событие доступности сервера (участвует в схлопывании)."""
    if event_type != "server" or not isinstance(details, dict):
        return False
    return details.get("reason") in AVAILABILITY_REASONS


def availability_notification(
    state: str,
    *,
    server_name: str,
    server_id: str = "",
    error: str = "",
    details: Optional[dict] = None,
) -> dict:
    """Уведомление о ФАКТИЧЕСКОМ состоянии сервера (для схлопывания).

    Текст собирается по факту, а не по строке очереди: в очереди мог
    залежаться устаревший «online», пока сервер уже снова упал.
    """
    payload = dict(details) if isinstance(details, dict) else {}
    payload["server_id"] = server_id or payload.get("server_id", "")
    payload["server_name"] = server_name
    payload["state"] = state
    if state == "offline":
        payload["reason"] = "server_offline"
        payload["event"] = "offline"
        if error:
            payload["error"] = error
        message = f"Сервер «{server_name}» стал недоступен."
        if error:
            message += f"\nОшибка: {error}"
        return {
            "type": "server",
            "level": "critical",
            "title": "Сервер недоступен",
            "message": message,
            "details": payload,
        }
    payload["reason"] = "server_online"
    payload["event"] = "online"
    payload.pop("error", None)
    return {
        "type": "server",
        "level": "info",
        "title": "Сервер снова доступен",
        "message": f"Сервер «{server_name}» снова в сети.",
        "details": payload,
    }


# --------------------------------------------------------------
# Закрытие строк очереди (план, §10)
# --------------------------------------------------------------

def enabled_categories() -> dict:
    """Текущее состояние переключателей категорий (по умолчанию — включены)."""
    from core.config import get_notification_categories

    return get_notification_categories()


def category_enabled(category: str) -> bool:
    """Доставлять ли уведомления этой категории.

    Онлайн/офлайн и SSL решает тумблер их проверки (Настройки → Общие →
    «Уведомления»): выключенная проверка не присылает и не копит. Остальные
    категории — своя галочка.
    """
    from core.config import get_monitor_config

    section_name = MANAGED_BY_MONITOR.get(category)
    if section_name:
        try:
            section = (get_monitor_config() or {}).get(section_name) or {}
        except Exception:
            return True
        return bool(section.get("enabled", True))
    return bool(enabled_categories().get(category, True))


def suppress_event(event_type: str, details: Optional[dict]) -> bool:
    """Событие не считается уведомлением: его категория выключена целиком.

    Такое событие остаётся в журнале, но создаётся прочитанным и в очередь не
    встаёт — и в вебе, и в Telegram. Исключений по типу события нет; события
    без категории (резервные копии, live-отчёты задач) не подавляются.
    """
    category = category_of(event_type)
    if category is None:
        return False
    return not category_enabled(category)


def telegram_channel_enabled() -> bool:
    """Канал Telegram: присылать ли уведомления (бот при этом работает)."""
    from core.config import get_telegram_channel

    return get_telegram_channel()


def telegram_enabled() -> bool:
    """Мастер-выключатель Telegram: нет ключа — считаем включённым."""
    from core.config import load_config

    config = load_config() or {}
    return bool(config.get("telegram_enabled", True))


def purge_disabled_categories() -> int:
    """Закрыть строки выключенных категорий (и всю очередь, если ТГ выключен).

    Выключение уведомлений означает «закрыть уже накопившееся»: при повторном
    включении старые события не воскресают и не приходят залпом.
    """
    from core import notification_queue

    if not telegram_enabled() or not telegram_channel_enabled():
        return notification_queue.close_pending(lambda row: True)

    def _disabled(row: dict) -> bool:
        category = category_of(row.get("type"))
        return category is not None and not category_enabled(category)

    return notification_queue.close_pending(_disabled)


def purge_category(category: str) -> int:
    """Закрыть строки одной категории (выключили её проверку в «Уведомлениях»)."""
    from core import notification_queue

    return notification_queue.close_pending(
        lambda row: category_of(row.get("type")) == category
    )


def purge_all_pending() -> int:
    """Закрыть всю очередь доставки (переключение мастер-выключателя ТГ)."""
    from core import notification_queue

    return notification_queue.close_pending(lambda row: True)
