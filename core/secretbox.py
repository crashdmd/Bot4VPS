"""Симметричное шифрование секретов конфигурации (Bot4VPS).

Шифруются только пароли управляемых серверов (servers.json) и Telegram
Bot Token (config.json). Прочие поля (host, user, port, key_path и т.д.)
остаются plaintext — по ТЗ.

Формат хранения: ``enc1:<fernet-token>`` (AES-128-CBC + HMAC-SHA256,
библиотека cryptography — уже в venv как зависимость paramiko).
Префикс ``enc1:`` делает ciphertext отличимым от plaintext и оставляет
место для версионирования схемы.

Ключ шифрования: ``keys/secret.key`` — отдельный файл (не в servers.json
и не в config.json, где лежит ciphertext), права 0600, генерируется
автоматически при первом обращении. Каталог keys/ не попадает в Git.

Граница значений (важно, см. decrypt):
  - plaintext без префикса          → принимается как есть (обратная
    совместимость со старыми установками);
  - ``enc1:`` + валидный токен      → расшифровывается;
  - ``enc1:`` + повреждённый токен  → SecretBoxError. Молча вернуть
    мусор как «пароль» нельзя: повреждение превратилось бы в непонятную
    ошибку SSH где-то в другом месте.

Потеря keys/secret.key делает зашифрованные секреты невосстановимыми —
файл необходимо включать в резервную копию Bot4VPS (см. README).

Инвариант мастер-ключа (см. _load_fernet): если secret.key отсутствует
и на диске есть хотя бы одно значение enc1: — НИ ОДИН вызов
encrypt/decrypt (прямой или косвенный, из любого места кода) не создаёт
новый ключ, а бросает MasterKeyMissingError. Иначе первый decrypt()
молча сгенерировал бы новый ключ и осиротил все старые ciphertext.
Авто-создание остаётся только для чистой системы без enc1: данных.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

# Относительный путь — как CONFIG_FILE/DATA_FILE (cwd = /opt/bot4vps
# через WorkingDirectory сервиса). Тесты патчат KEY_FILE на tmp.
KEY_FILE = Path("keys") / "secret.key"

# Префикс схемы шифрования: отличаем ciphertext от plaintext.
PREFIX = "enc1:"


class SecretBoxError(RuntimeError):
    """Ciphertext не удалось расшифровать: неверный ключ или повреждено значение."""


class MasterKeyMissingError(SecretBoxError):
    """secret.key отсутствует, но на диске есть данные enc1:.

    Новый ключ создаваться автоматически не имеет права (инвариант
    мастер-ключа): сначала владелец должен ввести существующий ключ
    (recovery-флоу) или осознанно создать новый с потерей данных.
    """


def is_encrypted(value) -> bool:
    """Значение зашифровано нашим механизмом (префикс enc1:)?"""
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt(value: str) -> str:
    """Зашифровать секрет для записи на диск.

    Пустая строка и уже зашифрованное значение возвращаются как есть
    (идемпотентность), поэтому вызов можно ставить в любую точку записи.
    """
    if not isinstance(value, str) or not value:
        return value
    if value.startswith(PREFIX):
        return value
    token = _load_fernet().encrypt(value.encode("utf-8")).decode("ascii")
    return PREFIX + token


def decrypt(value):
    """Расшифровать секрет, прочитанный с диска.

    plaintext (без префикса) проходит как есть — старые конфиги
    продолжают работать. ``enc1:`` расшифровывается; повреждённый
    токен или чужой ключ шифрования → SecretBoxError.
    """
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    token = value[len(PREFIX):]
    try:
        plaintext = _load_fernet().decrypt(token.encode("utf-8"))
    except InvalidToken as exc:
        raise SecretBoxError(
            "Не удалось расшифровать секрет (enc1:): неверный ключ "
            "шифрования keys/secret.key или повреждено значение в "
            "servers.json / config.json"
        ) from exc
    return plaintext.decode("utf-8")


# ------------------------------------------------------------------
# Ключ шифрования
# ------------------------------------------------------------------

def _read_key_bytes() -> bytes | None:
    try:
        data = KEY_FILE.read_bytes().strip()
    except FileNotFoundError:
        return None
    if not data:
        return None
    return data


def _create_key_exclusive() -> bytes:
    """Сгенерировать ключ и создать файл атомарно (O_CREAT|O_EXCL).

    Если файл уже создан параллельным потоком/процессом — читаем его:
    два разных ключа появиться не могут, иначе половина ciphertext
    стала бы недешифруемой.
    """
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    try:
        fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        existing = _read_key_bytes()
        if existing is None:
            raise SecretBoxError(
                f"Файл ключа {KEY_FILE} существует, но не читается"
            )
        return existing
    with os.fdopen(fd, "wb") as f:
        f.write(key)
        f.flush()
        os.fsync(f.fileno())
    return key


def _load_fernet() -> Fernet:
    key = _read_key_bytes()
    if key is None:
        # ИНВАРИАНТ МАСТЕР-КЛЮЧА: отсутствие файла ключа при наличии
        # enc1: данных на диске не даёт права создать новый ключ —
        # иначе первый же decrypt() молча осиротил бы все старые
        # ciphertext. Авто-создание остаётся только для чистой системы.
        if scan_encrypted()["found"]:
            raise MasterKeyMissingError(
                "Мастер-ключ keys/secret.key отсутствует, но обнаружены "
                "зашифрованные данные (enc1:) в servers.json / config.json. "
                "Автоматическое создание нового ключа запрещено: сначала "
                "введите существующий ключ или подтвердите создание нового "
                "(Настройки → Безопасность → Мастер-ключ либо консоль bot4vps)"
            )
        key = _create_key_exclusive()
    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:
        raise SecretBoxError(
            f"Файл ключа {KEY_FILE} повреждён (ожидается Fernet-ключ)"
        ) from exc


# ------------------------------------------------------------------
# Мастер-ключ: скан зашифрованных данных и восстановление
# ------------------------------------------------------------------

# Каталоги/файлы скана — отдельные константы, чтобы тесты патчили их
# (по образцу KEY_FILE), не трогая прод-конфиги.
SCAN_CONFIG_FILE = Path("config.json")
SCAN_SERVERS_FILE = Path("servers.json")
SCAN_BACKUP_DIR = Path("backup")

# Где искать enc1: (файл → путь к значению внутри JSON). Совпадает с
# реестром фактических полей: servers[].password, bot_token,
# web.totp_secret (см. docstring модуля и ТЗ этапа «мастер-ключ»);
# backup_password — пароль бэкапов (этап B4VE).
_ENC_FIELD_LABELS = {
    "server_passwords": "пароли серверов",
    "bot_token": "Telegram Bot Token",
    "totp_secret": "секрет 2FA",
    "backup_password": "пароль резервных копий",
}


def _iter_encrypted_values() -> list[tuple[str, str]]:
    """Собрать (метка поля, значение enc1:) без расшифровки.

    Чтение сырых JSON — load_data()/get_saved_bot_token() нельзя:
    они сами расшифровывают и падают/создают ключ. Ротации backup/
    не сканируем: там могут лежать значения ещё более старого ключа,
    решения о них recovery не принимает.
    """
    found: list[tuple[str, str]] = []

    # config.json: bot_token, web.totp_secret
    try:
        with open(SCAN_CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        cfg = {}
    if is_encrypted(cfg.get("bot_token")):
        found.append(("bot_token", cfg["bot_token"]))
    web = cfg.get("web")
    if isinstance(web, dict) and is_encrypted(web.get("totp_secret")):
        found.append(("totp_secret", web["totp_secret"]))

    # servers.json: servers[].password
    try:
        with open(SCAN_SERVERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    servers = data.get("servers")
    if isinstance(servers, list):
        for server in servers:
            if isinstance(server, dict) and is_encrypted(server.get("password")):
                found.append(("server_passwords", server["password"]))

    # Ротации backup/ (latest.json, servers_*.json): расшифровываются
    # только вручную через restore_backup, но если ключа нет — авто-
    # создание нового ключа сделало бы и их навсегда мёртвыми.
    for path in _backup_rotation_paths():
        try:
            with open(path, "r", encoding="utf-8") as f:
                rot = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
        rot_servers = rot.get("servers")
        if not isinstance(rot_servers, list):
            continue
        for server in rot_servers:
            if isinstance(server, dict) and is_encrypted(server.get("password")):
                found.append(("server_passwords", server["password"]))
    return found


def _backup_rotation_paths() -> list[Path]:
    """Файлы ротации servers.json (без рекурсии, пропуски молча)."""
    try:
        paths = list(SCAN_BACKUP_DIR.glob("servers_*.json"))
    except OSError:
        return []
    latest = SCAN_BACKUP_DIR / "latest.json"
    if latest.exists():
        paths.append(latest)
    return paths


def scan_encrypted() -> dict:
    """Есть ли на диске значения enc1: (без расшифровки и без ключа).

    Возвращает {"found": bool, "fields": [...]} где fields — метки
    фактических полей (bot_token/totp_secret/server_passwords).
    Вызывается ТОЛЬКО в ветке «файла ключа нет» (редкий случай),
    производительность горячего пути не затрагивает.
    """
    values = _iter_encrypted_values()
    fields = sorted({label for label, _ in values})
    return {"found": bool(values), "fields": fields, "values": values}


# ------------------------------------------------------------------
# Скан незашифрованных секретов и массовое шифрование
# ------------------------------------------------------------------

def _is_plaintext_secret(value) -> bool:
    """Секрет, лежащий открытым текстом: непустая строка без префикса enc1:."""
    return isinstance(value, str) and bool(value.strip()) and not is_encrypted(value)


def scan_plaintext_secrets() -> dict:
    """Найти секреты, хранящиеся незашифрованными (без ключа и расшифровки).

    Зеркально _iter_encrypted_values(): те же поля реестра, но ищем
    plaintext. Значения НЕ возвращаются — только метки и количества,
    поэтому результат безопасно показывать в UI/CLI/TG.

    Возвращает {"found": bool, "items": [{"key", "label", "count"}]}.
    Ротации backup/ не сканируем (снимки прошлого, см. _iter_encrypted_values).
    """
    try:
        with open(SCAN_CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        cfg = {}
    try:
        with open(SCAN_SERVERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    servers = data.get("servers") if isinstance(data.get("servers"), list) else []

    counts: dict[str, int] = {}
    if _is_plaintext_secret(cfg.get("bot_token")):
        counts["bot_token"] = 1
    web = cfg.get("web")
    if isinstance(web, dict) and _is_plaintext_secret(web.get("totp_secret")):
        counts["totp_secret"] = 1
    if _is_plaintext_secret(cfg.get("backup_encryption_password")):
        counts["backup_password"] = 1
    plain_passwords = sum(
        1 for s in servers
        if isinstance(s, dict) and _is_plaintext_secret(s.get("password"))
    )
    if plain_passwords:
        counts["server_passwords"] = plain_passwords

    items = [
        {"key": key, "label": _ENC_FIELD_LABELS.get(key, key), "count": count}
        for key, count in sorted(counts.items())
    ]
    return {"found": bool(items), "items": items}


def encrypt_all_plaintext_secrets() -> dict:
    """Зашифровать все найденные scan_plaintext_secrets() секреты.

    Единая функция ядра для Web/CLI/TG (не две реализации). Шаги — только
    для полей, найденных свежим сканом; каждый шаг атомарен, повторный
    запуск идемпотентен (см. инварианты ниже), исходные значения не
    теряются ни в какой точке (все записи — tempfile + fsync + os.replace).

    Шаги:
      1. servers.json: load_data() расшифровывает всё (повреждённый
         ciphertext → SecretBoxError ДО записи) → save_data() перешифрует
         все пароли (_encrypt_passwords_for_disk). Под data_lock(), как
         остальные писатели.
      2. config.json: все три поля ОДНИМ атомарным _patch_config_keys()
         (одна запись — все-или-ничего в пределах файла).

    Гейт мастер-ключа — в _load_fernet: ключа нет + есть enc1:-данные →
    MasterKeyMissingError (ничего не перезаписано); чистая система →
    ключ автосоздаётся (штатно, как при первом секрете).

    Инвариант: после успеха повторный скан показывает 0 находок —
    контрольный rescan возвращается в ответе ("plaintext").
    """
    scan = scan_plaintext_secrets()
    if not scan["found"]:
        return {"encrypted": {}, "plaintext": scan}

    found_keys = {item["key"] for item in scan["items"]}
    encrypted: dict[str, int] = {}

    # Шаг 1: пароли серверов. load_data() валидирует ВСЕ enc1:-значения
    # до записи; save_data() пишет атомарно и перешифровывает всё скопом.
    if "server_passwords" in found_keys:
        from core.storage import data_lock, load_data, save_data

        with data_lock():
            data = load_data()
            save_data(data)
        encrypted["server_passwords"] = next(
            item["count"] for item in scan["items"] if item["key"] == "server_passwords"
        )

    # Шаг 2: config.json — одна атомарная запись для всех полей.
    # Свежее чтение после шага 1; web берём сырым (без долива defaults),
    # чтобы перезаписать ровно то, что на диске.
    from core.config import BACKUP_PASSWORD_KEY, _patch_config_keys, _read_config_raw

    raw = _read_config_raw()
    updates: dict = {}
    if "bot_token" in found_keys and _is_plaintext_secret(raw.get("bot_token")):
        updates["bot_token"] = encrypt(raw["bot_token"])
        encrypted["bot_token"] = 1
    web = raw.get("web")
    if "totp_secret" in found_keys and isinstance(web, dict) \
            and _is_plaintext_secret(web.get("totp_secret")):
        web = dict(web)
        web["totp_secret"] = encrypt(web["totp_secret"])
        updates["web"] = web
        encrypted["totp_secret"] = 1
    if "backup_password" in found_keys \
            and _is_plaintext_secret(raw.get(BACKUP_PASSWORD_KEY)):
        updates[BACKUP_PASSWORD_KEY] = encrypt(raw[BACKUP_PASSWORD_KEY])
        encrypted["backup_password"] = 1
    if updates:
        _patch_config_keys(updates)

    return {"encrypted": encrypted, "plaintext": scan_plaintext_secrets()}


def master_key_state() -> dict:
    """Состояние мастер-ключа для UI/CLI (никогда не возвращает ключ).

    ok            — ключ есть и расшифровывает данные enc1:;
    missing_no_data — ключа нет, enc1: данных нет (штатная ситуация);
    missing_with_data — ключа нет, данные есть (нужно восстановление);
    mismatch      — ключ есть, но не подходит к текущим данным
    (тот же recovery-флоу, что и missing_with_data).
    """
    key = _read_key_bytes()
    scan = scan_encrypted()
    if key is None:
        return {
            "state": "missing_with_data" if scan["found"] else "missing_no_data",
            "encrypted_fields": scan["fields"],
        }
    if not scan["found"]:
        return {"state": "ok", "encrypted_fields": []}
    # Ключ есть и данные есть: пробуем расшифровать всё — mismatch
    # всплывает здесь, а не россыпью 500-х в разных API.
    try:
        for _, value in scan["values"]:
            decrypt(value)
    except SecretBoxError:
        return {"state": "mismatch", "encrypted_fields": scan["fields"]}
    return {"state": "ok", "encrypted_fields": scan["fields"]}


def read_master_key() -> str:
    """Прочитать мастер-ключ для операции «Показать» (клиент/CLI).

    Возвращает только при живом ключе; состояние mismatch/missing
    отдаётся ошибкой — показывать «какой-то» ключ нельзя.
    """
    key = _read_key_bytes()
    if key is None:
        scan = scan_encrypted()
        if scan["found"]:
            raise MasterKeyMissingError(
                "Мастер-ключ отсутствует, зашифрованные данные не "
                "восстановимы этим ключом — сначала восстановите ключ"
            )
        raise MasterKeyMissingError(
            "Мастер-ключ ещё не создан (зашифрованных данных нет)"
        )
    try:
        Fernet(key)
    except (ValueError, TypeError) as exc:
        raise SecretBoxError(
            f"Файл ключа {KEY_FILE} повреждён (ожидается Fernet-ключ)"
        ) from exc
    return key.decode("ascii").strip()


def restore_master_key(key_value: str) -> dict:
    """Ввести существующий мастер-ключ и проверить его по данным.

    Ключ обязан расшифровать ВСЕ enc1: значения из ТЕКУЩИХ
    config.json/servers.json. Успех → ключ записывается как
    keys/secret.key (0600); данные не изменяются. Провал → ничего
    не перезаписывается, возвращается понятная ошибка.
    """
    candidate = (key_value or "").strip()
    if not candidate:
        raise ValueError("Мастер-ключ не может быть пустым")
    try:
        fernet = Fernet(candidate.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise ValueError("Это не похоже на мастер-ключ (ожидается Fernet-ключ)") from exc

    scan = scan_encrypted()
    if not scan["found"]:
        raise ValueError(
            "Зашифрованных данных (enc1:) не обнаружено: восстанавливать "
            "нечего — ключ можно создать новый"
        )
    for label, value in scan["values"]:
        try:
            fernet.decrypt(value[len(PREFIX):].encode("utf-8"))
        except InvalidToken as exc:
            raise MasterKeyMissingError(
                "Неверный мастер-ключ или ключ не позволяет расшифровать "
                f"существующие данные ({_ENC_FIELD_LABELS.get(label, label)})"
            ) from exc

    # Запись: тот же атомарный эксклюзивный механизм, что и автосоздание.
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    encoded = candidate.encode("ascii")
    try:
        fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # Файл есть (mismatch-сценарий) — заменяем проверенным ключом.
        fd = os.open(KEY_FILE, os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(encoded + b"\n")
        f.flush()
        os.fsync(f.fileno())
    return master_key_state()
