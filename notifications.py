import json
import uuid

from pathlib import Path
from datetime import datetime

NOTIFICATION_FILE = Path(
    "backup/notification.json"
)


def load_notifications():

    if not NOTIFICATION_FILE.exists():

        return []

    try:

        with open(
            NOTIFICATION_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except (
        json.JSONDecodeError,
        OSError
    ):

        if NOTIFICATION_FILE.exists():

            NOTIFICATION_FILE.unlink(
                missing_ok=True
            )

        return []

def save_notifications(items):

    NOTIFICATION_FILE.parent.mkdir(
        exist_ok=True
    )
    with open(
        NOTIFICATION_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            items,
            f,
            indent=4,
            ensure_ascii=False
        )

def add_notification(
    type_,
    data
):

    items = get_notifications()

    items.append(
        {
            "id": uuid.uuid4().hex,
            "type": type_,
            "time": datetime.now().isoformat(),
            "data": data
        }
    )

    save_notifications(
        items
    )

def get_notifications(
    max_age_seconds=120
):

    # Возвращает только актуальные уведомления
    # и автоматически удаляет устаревшие.

    from datetime import timedelta

    now = datetime.now()

    valid = []

    for notification in load_notifications():

        try:

            created = datetime.fromisoformat(
                notification["time"]
            )

        except (
            KeyError,
            ValueError
        ):

            continue

        if (
            now - created
        ) <= timedelta(
            seconds=max_age_seconds
        ):

            valid.append(
                notification
            )

    save_notifications(
        valid
    )

    return valid
