import json
import uuid
import os
import shutil
import threading
from copy import deepcopy
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


def get_server_backup_profile(server_id: str):
    """Вернуть валидированный backup profile сервера либо None."""
    server = find_server(server_id)
    if server is None:
        raise ValueError("Сервер не найден")
    profile = server.get("backup")
    if profile is None:
        return None
    from core.backup.validation import normalize_server_profile
    return normalize_server_profile(profile)


def server_backup_configured(server) -> bool:
    """Backup сервера считается настроенным только при непустом sources.

    Пустой профиль — легальное состояние (пользователь убрал все адреса), но
    запускать по нему backup нечего: UI обязан показывать «Backup не настроен» и
    держать создание выключенным, иначе случайный клик создаст пустой архив.
    """
    if not isinstance(server, dict):
        return False
    profile = server.get("backup")
    if not isinstance(profile, dict):
        return False
    sources = profile.get("sources")
    return isinstance(sources, list) and bool(sources)


_BACKUP_CONNECTION_FIELDS = (
    "host",
    "port",
    "user",
    "auth_type",
    "password",
    "key_path",
)


class BackupProfileConflictError(ValueError):
    """Profile or SSH connection changed while remote validation was running."""


class ConnectionStateConflictError(ValueError):
    """SSH connection fields changed while a verified operation was running."""


def server_connection_snapshot(server: dict) -> dict:
    """Вернуть копию только полей, влияющих на SSH-подключение."""
    return {
        field: deepcopy(server.get(field))
        for field in _BACKUP_CONNECTION_FIELDS
        if field in server
    }


def get_server_connection_snapshot(server_id: str) -> dict:
    """Атомарно получить сервер и его SSH connection snapshot."""
    with data_lock():
        data = load_data()
        for server in data.get("servers", []):
            if server.get("id") == server_id:
                return {
                    "server": deepcopy(server),
                    "connection": server_connection_snapshot(server),
                }
    raise ValueError("Сервер не найден")


def record_server_host_key(
    server_id: str, record: dict, *, overwrite: bool = False
) -> bool:
    """Записать SSH host key сервера (host key verification, 5.1).

    Возвращает True, если запись создана/обновлена; False — запись уже
    существует и overwrite=False (TOFU не перезаписывает сохранённый
    ключ: гонка параллельных подключений или уже принятое решение).
    Поле host_key НЕ входит в _BACKUP_CONNECTION_FIELDS — CAS-потоки
    Quick Setup сверку не замечают.
    """
    with data_lock():
        data = load_data()
        for server in data.get("servers", []):
            if server.get("id") != server_id:
                continue
            if server.get("host_key") and not overwrite:
                return False
            server["host_key"] = deepcopy(record)
            save_data(data)
            return True
    raise ValueError("Сервер не найден")


def compare_and_set_server_connection(
    server_id: str,
    patch: dict,
    *,
    expected_connection: dict,
) -> dict:
    """Изменить только SSH-поля, если проверенный snapshot ещё актуален."""
    if not isinstance(patch, dict) or not patch:
        raise ValueError("Пустое изменение SSH-настроек")
    unsupported = set(patch) - set(_BACKUP_CONNECTION_FIELDS)
    if unsupported:
        raise ValueError("Недопустимые SSH-поля: " + ", ".join(sorted(unsupported)))
    with data_lock():
        data = load_data()
        for server in data.get("servers", []):
            if server.get("id") != server_id:
                continue
            if server_connection_snapshot(server) != expected_connection:
                raise ConnectionStateConflictError(
                    "SSH-настройки сервера изменились; обновите данные и повторите"
                )
            for field, value in patch.items():
                if value is None:
                    server.pop(field, None)
                else:
                    server[field] = deepcopy(value)
            save_data(data)
            return deepcopy(server)
    raise ValueError("Сервер не найден")


def compare_and_set_nftables_input_chain(
    server_id: str,
    token: dict,
    *,
    expected_connection: dict,
) -> dict:
    """Сохранить validated chain, если SSH snapshot не изменился."""
    fields = {"family", "table", "chain"}
    if not isinstance(token, dict) or set(token) != fields:
        raise ValueError("Ожидаются family, table и chain")
    if not all(
        isinstance(token[field], str)
        and bool(token[field])
        and len(token[field]) <= 128
        and "\x00" not in token[field]
        for field in fields
    ):
        raise ValueError("Некорректный nftables chain token")
    normalized = {field: token[field] for field in ("family", "table", "chain")}

    with data_lock():
        data = load_data()
        for server in data.get("servers", []):
            if server.get("id") != server_id:
                continue
            if server_connection_snapshot(server) != expected_connection:
                raise ConnectionStateConflictError(
                    "SSH-настройки сервера изменились; обновите данные и повторите"
                )
            quick_setup = server.get("quick_setup")
            if quick_setup is None:
                quick_setup = {}
                server["quick_setup"] = quick_setup
            if not isinstance(quick_setup, dict):
                raise ValueError("Некорректные Quick Setup настройки сервера")
            firewall = quick_setup.get("firewall")
            if firewall is None:
                firewall = {}
                quick_setup["firewall"] = firewall
            if not isinstance(firewall, dict):
                raise ValueError("Некорректные firewall настройки сервера")
            firewall["nftables_input_chain"] = deepcopy(normalized)
            save_data(data)
            return deepcopy(normalized)
    raise ValueError("Сервер не найден")


def clear_nftables_input_chain(server_id: str) -> bool:
    """Удалить сохранённый выбор nftables input chain (если он был).

    Возвращает True, если выбор существовал и был удалён; False — если
    выбора не было. Используется при удалении nftables (Ч5): сохранённый
    выбор относится к конкретной установке и не должен переживать uninstall.
    """
    with data_lock():
        data = load_data()
        for server in data.get("servers", []):
            if server.get("id") != server_id:
                continue
            quick_setup = server.get("quick_setup")
            firewall = (
                quick_setup.get("firewall")
                if isinstance(quick_setup, dict)
                else None
            )
            if not isinstance(firewall, dict):
                return False
            if "nftables_input_chain" not in firewall:
                return False
            del firewall["nftables_input_chain"]
            save_data(data)
            return True
    raise ValueError("Сервер не найден")


def _backup_connection_snapshot(server: dict) -> dict:
    return server_connection_snapshot(server)


def get_server_backup_snapshot(server_id: str) -> dict:
    """Atomically capture profile and connection inputs without opening SSH."""
    with data_lock():
        data = load_data()
        for server in data.get("servers", []):
            if server.get("id") == server_id:
                return {
                    "server": deepcopy(server),
                    "profile": deepcopy(server.get("backup")),
                    "connection": _backup_connection_snapshot(server),
                }
    raise ValueError("Сервер не найден")


def compare_and_set_server_backup_profile(
    server_id: str,
    profile: dict,
    *,
    expected_profile,
    expected_connection: dict,
) -> dict:
    """Commit one canonical profile iff the captured profile/connection still match."""
    from core.backup.validation import normalize_server_profile

    normalized = normalize_server_profile(profile)
    with data_lock():
        data = load_data()
        for server in data.get("servers", []):
            if server.get("id") != server_id:
                continue
            if (
                server.get("backup") != expected_profile
                or _backup_connection_snapshot(server) != expected_connection
            ):
                raise BackupProfileConflictError(
                    "Профиль или SSH-настройки сервера изменились; обновите данные и повторите"
                )
            server["backup"] = normalized
            save_data(data)
            return normalized
    raise ValueError("Сервер не найден")


def set_server_backup_profile(server_id: str, profile: dict) -> dict:
    """Атомарно записать servers[].backup по стабильному server_id."""
    from core.backup.validation import normalize_server_profile
    normalized = normalize_server_profile(profile)
    with data_lock():
        data = load_data()
        for server in data.get("servers", []):
            if server.get("id") == server_id:
                server["backup"] = normalized
                save_data(data)
                return normalized
    raise ValueError("Сервер не найден")


def update_server_backup_profile(server_id: str, patch: dict) -> dict:
    if not isinstance(patch, dict):
        raise ValueError("Backup profile patch должен быть объектом")

    def merge(target: dict, updates: dict) -> dict:
        result = dict(target)
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = merge(result[key], value)
            else:
                result[key] = value
        return result

    current = get_server_backup_profile(server_id)
    if current is None:
        raise ValueError("Backup profile сервера ещё не настроен")
    return set_server_backup_profile(server_id, merge(current, patch))

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

            # Бэкап мог быть снят до перевода на 0600 — восстановление
            # не должно возвращать мир-читаемые права рабочей базе.
            DATA_FILE.chmod(0o600)

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

            DATA_FILE.chmod(0o600)

            shutil.copy2(
                backup,
                LATEST_BACKUP
            )

            LATEST_BACKUP.chmod(0o600)

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

def _encrypt_passwords_for_disk(data):
    """Копия данных с зашифрованными servers[].password (для записи).

    Входной dict не мутируем: вызывающий код продолжает работать
    с plaintext-копиями в памяти (compare-and-set циклы, wizard).
    Функция — единственная точка преобразования перед save_data,
    поэтому все ~15 путей записи покрываются без рефакторинга.
    """
    from core.secretbox import encrypt

    servers = data.get("servers")
    if not isinstance(servers, list):
        return data
    out = deepcopy(data)
    for server in out.get("servers", []):
        if isinstance(server, dict):
            password = server.get("password")
            if isinstance(password, str) and password:
                server["password"] = encrypt(password)
    return out


def _decrypt_passwords(data):
    """Расшифровать servers[].password после чтения с диска.

    plaintext (старые установки) проходит как есть; повреждённый
    ciphertext → SecretBoxError (см. core/secretbox.decrypt).
    """
    from core.secretbox import decrypt

    servers = data.get("servers")
    if isinstance(servers, list):
        for server in servers:
            if isinstance(server, dict):
                password = server.get("password")
                if isinstance(password, str) and password:
                    server["password"] = decrypt(password)
    return data


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

            return _decrypt_passwords(json.load(f))

    except json.JSONDecodeError:

        print(
            "⚠ servers.json поврежден."
        )

        return _decrypt_passwords(restore_backup())

def save_data(data):

    # Пароли серверов пишем на диск зашифрованными (core/secretbox).
    with open(
        TEMP_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            _encrypt_passwords_for_disk(data),
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

    # Топология и SSH-пользователи управляемых серверов — не мир-читаемые
    # (пароли и так enc1:, но метаданные тоже персданные). Точка та же,
    # что у config.json (_write_config_atomic): chmod после replace.
    DATA_FILE.chmod(0o600)

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

            "Ручное восстановление servers.json\n"
            "(latest.json — последняя сохранённая копия):\n\n"

            "cp latest.json ../servers.json\n"

            "systemctl restart bot4vps\n\n"

            "Если latest.json поврежден,\n"
            "используйте любой файл\n"
            "servers_YYYY-MM-DD_HH-MM-SS.json\n"
            "и также перезапустите бота.\n\n"

            "-------------------------\n\n"

            "Ручное восстановление config.json\n"
            "(config_latest.json — последняя проверенная\n"
            "рабочая копия; config_YYYY-MM-DD_HH-MM-SS.json —\n"
            "история изменений):\n\n"

            "cp config_latest.json ../config.json\n"

            "systemctl restart bot4vps\n\n"

            "Поврежденный config.json приложение\n"
            "спасает как corrupt_config_*.json — это\n"
            "материал для разбора, НЕ копия для\n"
            "восстановления.\n\n"

            "Обычно config.json восстанавливается\n"
            "автоматически из config_latest.json при\n"
            "повреждении; ручной рецепт нужен, только\n"
            "если автоматика не справилась.\n"
        ),
        encoding="utf-8"
    )