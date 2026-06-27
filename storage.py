import json
import uuid
import os
import shutil
from notifications import (
    add_notification
)

from pathlib import Path
from datetime import datetime

DATA_FILE = Path(
    "servers.json"
)

TEMP_FILE = Path(
    "servers.json.tmp"
)

BACKUP_DIR = Path(
    "backup"
)

LATEST_BACKUP = (
    BACKUP_DIR /
    "latest.json"
)


MAX_BACKUPS = 5

def load_servers():
    return load_data().get("servers", [])


def load_groups():
    data = load_data()

    groups = data.get("groups", [])

    # Старый формат:
    # ["home", "vps"]
    if groups and isinstance(groups[0], str):

        groups = [
            {
                "name": name,
                "ssl_monitor": name == "vps"
            }
            for name in groups
        ]

        data["groups"] = groups
        save_data(data)

    return groups

def get_group(group_name):
    for group in load_groups():
        if group["name"] == group_name:
            return group
    return None

def save_servers(servers):
    data = load_data()
    data["servers"] = servers
    save_data(data)


def save_groups(groups):
    data = load_data()
    data["groups"] = groups
    save_data(data)


def find_server(server_id):
    servers = load_servers()

    return next(
        (
            s for s in servers
            if s.get("id") == server_id
        ),
        None
    )

def cleanup_backups():

    backups = sorted(
        BACKUP_DIR.glob(
            "servers_*.json"
        )
    )

    while len(backups) > MAX_BACKUPS:

        backups[0].unlink()

        backups.pop(0)


def create_backup():

    if not DATA_FILE.exists():

        return

    BACKUP_DIR.mkdir(
        exist_ok=True
    )

    if LATEST_BACKUP.exists():

        if (
            DATA_FILE.read_bytes()
            ==
            LATEST_BACKUP.read_bytes()
        ):

            return

    backup_name = (
        "servers_"
        +
        datetime.now().strftime(
            "%Y-%m-%d_%H-%M-%S"
        )
        +
        ".json"
    )

    backup_file = (
        BACKUP_DIR /
        backup_name
    )

    shutil.copy2(
        DATA_FILE,
        backup_file
    )

    shutil.copy2(
        DATA_FILE,
        LATEST_BACKUP
    )

    cleanup_backups()

    create_backup_readme()

def restore_backup():

    if not BACKUP_DIR.exists():

        raise FileNotFoundError(
            "Папка backup не найдена."
        )

    if LATEST_BACKUP.exists():

        try:

            with open(
                LATEST_BACKUP,
                "r",
                encoding="utf-8"
            ) as f:

                data = json.load(f)

            shutil.copy2(
                LATEST_BACKUP,
                DATA_FILE
            )

            print(
                "✔ Восстановлено из latest.json"
            )
            add_notification(
                type_="restore",
                data={
                    "source": "latest.json"
                }
            )
            return data

        except (
            json.JSONDecodeError,
            OSError
        ):

            print(
                "⚠ latest.json поврежден."
            )

    backups = sorted(
        BACKUP_DIR.glob(
            "servers_*.json"
        ),
        reverse=True
    )

    for backup in backups:

        try:

            with open(
                backup,
                "r",
                encoding="utf-8"
            ) as f:

                data = json.load(f)

            shutil.copy2(
                backup,
                DATA_FILE
            )

            shutil.copy2(
                backup,
                LATEST_BACKUP
            )

            print(
                f"✔ Восстановлено из {backup.name}"
            )
            add_notification(
                type_="restore",
                data={
                    "source": backup.name
                }
            )
            return data

        except (
            json.JSONDecodeError,
            OSError
        ):

            continue

    raise RuntimeError(
        "Не удалось восстановить servers.json."
    )

def load_data():

    if not DATA_FILE.exists():

        data = {
            "servers": [],
            "groups": [
                {
                    "name": "home",
                    "ssl_monitor": False
                },
                {
                    "name": "vps",
                    "ssl_monitor": True
                }
            ]
        }

        save_data(data)

        return data

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except json.JSONDecodeError:

        print(
            "⚠ servers.json поврежден."
        )

        return restore_backup()

def save_data(data):

    with open(
        TEMP_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            indent=4,
            ensure_ascii=False
        )

        f.flush()

        os.fsync(
            f.fileno()
        )

    os.replace(
        TEMP_FILE,
        DATA_FILE
    )

    create_backup()

def ensure_server_ids():
    data = load_data()

    changed = False

    for server in data.get("servers", []):
        if "id" not in server:
            server["id"] = uuid.uuid4().hex[:8]
            changed = True

    if changed:
        save_data(data)

def is_group_ssl_enabled(group_name):

    groups = load_groups()

    for group in groups:

        if group["name"] == group_name:

            return group.get(
                "ssl_monitor",
                False
            )

    return False

def create_backup_readme():

    BACKUP_DIR.mkdir(
        exist_ok=True
    )

    backups = sorted(
        BACKUP_DIR.glob(
            "servers_*.json"
        ),
        reverse=True
    )

    latest = (
        backups[0].name
        if backups
        else "нет"
    )

    readme = (
        BACKUP_DIR /
        "README.txt"
    )

    readme.write_text(
        (
            "Bot4VPS Backup\n"
            "=========================\n\n"

            f"Последнее обновление:\n"
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

            f"Всего резервных копий: {len(backups)}\n"

            f"Последний backup:\n"
            f"{latest}\n\n"

            "-------------------------\n\n"

            "Ручное восстановление:\n\n"

            "cp latest.json ../servers.json\n"

            "systemctl restart bot4vps\n\n"

            "Если latest.json поврежден,\n"
            "используйте любой файл\n"
            "servers_YYYY-MM-DD_HH-MM-SS.json\n"
            "и также перезапустите бота.\n"
        ),
        encoding="utf-8"
    )
