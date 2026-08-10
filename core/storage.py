import json
import uuid
import os
import shutil
import threading
from contextlib import contextmanager
from core.event_service import create_event
from core.event_types import EventType, EventLevel, EventReason

from pathlib import Path
from datetime import datetime

# Глобальная блокировка для атомарных read-modify-write над servers.json.
# RLock — допускает повторный вход (save_servers -> load_data/save_data и т.п.).
_DATA_LOCK = threading.RLock()


@contextmanager
def data_lock():
    """
    Контекст для атомарного RMW над servers.json.

        with data_lock():
            servers = load_servers()
            servers.append(new)
            save_servers(servers)

    Защищает от потери апдейтов при конкурентной записи из обработчиков,
    потоков мониторинга (asyncio.to_thread) и выполнения скриптов.
    """
    with _DATA_LOCK:
        yield

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
    """Всегда возвращает list[dict]: {name, ssl_monitor}."""
    data = load_data()
    groups = data.get("groups", [])
    normalized = _normalize_groups(groups)
    needs_migrate = bool(groups) and (
        isinstance(groups[0], str)
        or any(not isinstance(g, dict) for g in groups)
    )
    if needs_migrate:
        with data_lock():
            data = load_data()
            data["groups"] = _normalize_groups(data.get("groups", []))
            save_data(data)
            return list(data["groups"])
    return normalized


def get_group(group_name):
    group_name = (group_name or "").strip()
    for group in load_groups():
        if isinstance(group, dict) and group.get("name") == group_name:
            return group
    return None

def save_servers(servers):
    with data_lock():
        data = load_data()
        data["servers"] = servers
        save_data(data)


def save_groups(groups):
    with data_lock():
        data = load_data()
        data["groups"] = groups
        save_data(data)


def _normalize_groups(groups):
    out = []
    for g in groups or []:
        if isinstance(g, str):
            out.append({"name": g, "ssl_monitor": g == "vps"})
        else:
            out.append({
                "name": g.get("name"),
                "ssl_monitor": bool(g.get("ssl_monitor")),
            })
    return out


def create_group(name: str, ssl_monitor: bool = False) -> dict:
    """Создать группу. name — непустое, уникальное."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Название группы не может быть пустым")
    if any(ch in name for ch in "/\\0"):
        raise ValueError("Недопустимые символы в названии группы")
    with data_lock():
        data = load_data()
        groups = _normalize_groups(data.get("groups", []))
        if any(g["name"] == name for g in groups):
            raise ValueError(f"Группа «{name}» уже существует")
        group = {"name": name, "ssl_monitor": bool(ssl_monitor)}
        groups.append(group)
        data["groups"] = groups
        save_data(data)
        return group


def rename_group(old_name: str, new_name: str) -> dict:
    """Переименовать группу и обновить group у всех серверов."""
    old_name = (old_name or "").strip()
    new_name = (new_name or "").strip()
    if not old_name or not new_name:
        raise ValueError("Название группы не может быть пустым")
    if old_name == new_name:
        return get_group(old_name) or {"name": old_name}
    with data_lock():
        data = load_data()
        groups = _normalize_groups(data.get("groups", []))
        if not any(g["name"] == old_name for g in groups):
            raise ValueError(f"Группа «{old_name}» не найдена")
        if any(g["name"] == new_name for g in groups):
            raise ValueError(f"Группа «{new_name}» уже существует")
        for g in groups:
            if g["name"] == old_name:
                g["name"] = new_name
                updated = g
                break
        servers = data.get("servers", [])
        for s in servers:
            if s.get("group") == old_name:
                s["group"] = new_name
        data["groups"] = groups
        data["servers"] = servers
        save_data(data)
        return updated


def set_group_ssl(name: str, ssl_monitor: bool) -> dict:
    """Изменить ssl_monitor у группы."""
    name = (name or "").strip()
    with data_lock():
        data = load_data()
        groups = _normalize_groups(data.get("groups", []))
        for g in groups:
            if g["name"] == name:
                g["ssl_monitor"] = bool(ssl_monitor)
                data["groups"] = groups
                save_data(data)
                return g
        raise ValueError(f"Группа «{name}» не найдена")


def delete_group(name: str) -> None:
    """Удалить пустую группу. Если есть серверы — ValueError со списком."""
    name = (name or "").strip()
    with data_lock():
        data = load_data()
        groups = _normalize_groups(data.get("groups", []))
        if not any(g["name"] == name for g in groups):
            raise ValueError(f"Группа «{name}» не найдена")
        servers_in = [
            s.get("name") or s.get("id")
            for s in data.get("servers", [])
            if s.get("group") == name
        ]
        if servers_in:
            listing = "\n".join(f"• {n}" for n in servers_in[:20])
            more = f"\n… и ещё {len(servers_in) - 20}" if len(servers_in) > 20 else ""
            raise ValueError(
                f"Нельзя удалить группу «{name}».\n"
                f"В группе находятся серверы:\n{listing}{more}"
            )
        data["groups"] = [g for g in groups if g["name"] != name]
        save_data(data)


def group_server_names(name: str) -> list:
    """Имена серверов в группе (для UI)."""
    return [
        s.get("name") or s.get("id")
        for s in load_servers()
        if s.get("group") == name
    ]



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

            create_event(
                event_type=EventType.DATABASE,
                level=EventLevel.CRITICAL,
                title="Восстановлена повреждённая база servers.json",
                message="Автоматически восстановлено из latest.json",
                details={
                    "source": "latest.json",  
                    "reason": EventReason.DATABASE_RESTORED.value
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

            print(f"✔ Восстановлено из {backup.name}")
            
            create_event(
                event_type=EventType.DATABASE,
                level=EventLevel.CRITICAL,
                title="Восстановлена повреждённая база servers.json",
                message=f"Автоматически восстановлено из {backup.name}",
                details={
                    "source": backup.name,  # или "latest.json"
                    "reason": EventReason.DATABASE_RESTORED.value
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
    with data_lock():
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