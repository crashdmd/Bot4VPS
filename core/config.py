import json
import os
import re

from pathlib import Path

CONFIG_FILE = Path("config.json")
TEMP_FILE = Path("config.json.tmp")


DEFAULT_CONFIG = {
    "bot_token": "YOUR_BOT_TOKEN_HERE",
    "allowed_users": [],
    "telegram_enabled": True,
    "monitor": {
        "online": {
            "enabled": True,
            "interval": 5
        },
        "ssl": {
            "enabled": True,
            "interval": 1440
        }
    },
    "web": {
        "auth_enabled": False,
        "username": "admin",
        "password_hash": "",
        "secret_key": ""
    },
    # Проверка обновлений Bot4VPS (встроенный updater, 4.0+).
    # Top-level: _patch_config_keys патчит только ключи верхнего уровня.
    "update_check": {
        "enabled": False
    }
}


def load_config():

    if not CONFIG_FILE.exists():

        save_config(DEFAULT_CONFIG)

        return DEFAULT_CONFIG.copy()

    with open(
        CONFIG_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        config = json.load(f)

    changed = False
    for key, value in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = value
            changed = True
    monitor = config.setdefault("monitor", {})
    for name, settings in DEFAULT_CONFIG["monitor"].items():
        if name not in monitor:
            monitor[name] = settings
            changed = True
    if changed:
        save_config(config)
    return config


def save_config(config):

    with open(
        TEMP_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            config,
            f,
            indent=4,
            ensure_ascii=False
        )

        f.flush()
        os.fsync(f.fileno())

    os.replace(
        TEMP_FILE,
        CONFIG_FILE
    )


def get_monitor_config():

    return load_config()["monitor"]


def set_monitor_enabled(name, enabled):

    config = load_config()

    config["monitor"][name]["enabled"] = enabled

    save_config(config)


def set_monitor_interval(name, interval):

    config = load_config()

    config["monitor"][name]["interval"] = interval

    save_config(config)


# ==========================================================
# Проверка обновлений (встроенный updater, 4.0+)
# ==========================================================

def get_update_check_config():
    """Секция config.json -> update_check (флаг «Проверять обновления»)."""

    return _read_config_raw().get("update_check", {"enabled": False})


def set_update_check_enabled(enabled):
    """Только флаг update_check.enabled — точечный патч config.json.

    Полная пересборка файла запрещена (ТЗ): остальные настройки и порядок
    ключей остаются нетронутыми.
    """

    _patch_config_keys({"update_check": {"enabled": bool(enabled)}})


# ==========================================================
# Web UI
# ==========================================================

def get_web_config():
    """Секция config.json -> web (авторизация веб-слоя)."""

    return load_config().get("web", {})


def set_web_config(web):

    config = load_config()

    config["web"] = web

    save_config(config)


def set_web_auth(enabled):
    """Включить/выключить авторизацию веб-слоя одним флагом."""

    config = load_config()

    web = config.setdefault("web", {})
    web["auth_enabled"] = bool(enabled)

    save_config(config)


# ==========================================================
# Telegram
# ==========================================================

def _read_config_raw() -> dict:
    """Прочитать config.json без merge defaults и без save_config."""
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)



def _is_bot_token_configured(token) -> bool:
    """Token считается заданным только если это не пусто и не placeholder."""
    t = (token or "").strip()
    if not t:
        return False
    upper = t.upper()
    if upper.startswith("YOUR_"):
        return False
    if "YOUR_BOT_TOKEN" in upper:
        return False
    return True


def _first_allowed_user_id(users):
    """Первый корректный numeric User ID из allowed_users, иначе None."""
    if not users:
        return None
    for u in users:
        try:
            return int(u)
        except (TypeError, ValueError):
            continue
    return None


def get_telegram_config():
    """Точечное чтение настроек Telegram из config.json (без перезаписи файла)."""
    cfg = _read_config_raw()
    users = cfg.get("allowed_users") or []
    token = (cfg.get("bot_token") or "").strip()
    token_set = _is_bot_token_configured(token)
    user_id = _first_allowed_user_id(users)
    # Нет ключа telegram_enabled → считаем включённым, файл не трогаем
    enabled = bool(cfg["telegram_enabled"]) if "telegram_enabled" in cfg else True
    needs_setup = bool(enabled) and (not token_set or user_id is None)
    return {
        "enabled": enabled,
        "user_id": user_id,
        "allowed_users": list(users),
        "token_set": token_set,
        "needs_setup": needs_setup,
    }

def _patch_config_keys(updates: dict) -> None:
    """Точечно заменить значения top-level ключей в config.json.

    Читает файл как текст, через JSONDecoder.raw_decode находит границы
    текущего значения ключа и подменяет только этот фрагмент. Остальной
    текст файла (порядок ключей, отступы соседних блоков, прочие секции)
    не пересериализуется.

    Если ключа ещё нет — вставляет одну строку перед закрывающей } корневого
    объекта. Запись атомарна через tempfile + os.replace.
    """
    if not updates:
        return

    if not CONFIG_FILE.exists():
        cfg = DEFAULT_CONFIG.copy()
        cfg.update(updates)
        save_config(cfg)
        return

    text = CONFIG_FILE.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()

    for key, value in updates.items():
        lit = json.dumps(value, ensure_ascii=False)
        # Верхний уровень: ключ в начале строки с небольшим отступом
        m = re.search(
            r'(?m)^([ \t]{0,4})"' + re.escape(key) + r'"(\s*:\s*)',
            text,
        )
        if m:
            val_start = m.end()
            try:
                _, val_end = decoder.raw_decode(text, val_start)
            except json.JSONDecodeError as e:
                raise ValueError(
                    "config.json: не разобрать значение ключа «%s»: %s" % (key, e)
                ) from e
            text = text[:val_start] + lit + text[val_end:]
            continue

        close = text.rfind("}")
        if close < 0:
            raise ValueError("config.json: нет закрывающей }")
        before = text[:close].rstrip()
        if before.endswith("{"):
            insert = '\n    "%s": %s\n' % (key, lit)
        else:
            insert = ',\n    "%s": %s\n' % (key, lit)
        text = before + insert + text[close:]

    with open(TEMP_FILE, "w", encoding="utf-8") as f:
        f.write(text)
        if not text.endswith("\n"):
            f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(TEMP_FILE, CONFIG_FILE)


def set_telegram_enabled(enabled: bool) -> None:
    """Только флаг telegram_enabled — точечный патч config.json."""
    _patch_config_keys({"telegram_enabled": bool(enabled)})


def set_telegram_credentials(*, user_id=None, bot_token=None) -> dict:
    """Обновить allowed_users / bot_token точечным патчем config.json.

    bot_token=None — поле не передавали, токен не менять.
    bot_token="" / пробелы / YOUR_* — ошибка (нельзя сохранить фиктивный токен).
    user_id=None — не менять пользователей; int/str — записать [user_id].
    """
    updates = {}
    if user_id is not None:
        uid = str(user_id).strip()
        if not uid:
            updates["allowed_users"] = []
        else:
            try:
                updates["allowed_users"] = [int(uid)]
            except ValueError:
                raise ValueError("Telegram User ID должен быть числом")
    if bot_token is not None:
        tok = str(bot_token).strip()
        if not tok:
            raise ValueError("Bot Token не может быть пустым")
        if not _is_bot_token_configured(tok):
            raise ValueError(
                "Укажите действительный Bot Token (не placeholder YOUR_…)"
            )
        updates["bot_token"] = tok
    if updates:
        _patch_config_keys(updates)
    return get_telegram_config()
