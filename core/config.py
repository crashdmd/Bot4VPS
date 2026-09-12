import copy
import json
import os
import re

from datetime import datetime
from pathlib import Path

CONFIG_FILE = Path("config.json")
TEMP_FILE = Path("config.json.tmp")

# ==========================================================
# Стойкость config.json (образец — ротация servers.json
# в core/storage.py). Одна точка: все записи идут через
# _write_config_atomic, восстановление — _restore_config_backup.
# ==========================================================

# Каталог страховки общий с servers.json, но имена не пересекаются:
# история конфига — config_<ts>.json, страховка — config_latest.json,
# повреждённые файлы — corrupt_config_<ts>.json (glob истории их не
# видит и кандидатами восстановления они быть не могут).
CONFIG_BACKUP_DIR = Path("backup")
CONFIG_LATEST = CONFIG_BACKUP_DIR / "config_latest.json"
MAX_CONFIG_BACKUPS = 5    # как MAX_BACKUPS у servers.json
CORRUPT_CONFIG_KEEP = 3   # сколько повреждённых файлов хранить для разбора


class ConfigCorruptedError(RuntimeError):
    """config.json повреждён и ни одной валидной копии не найдено.

    Единственная причина аварийного режима Web: отсутствие файла
    аварией не является (тихо создаётся DEFAULT_CONFIG, как всегда).
    """


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
    },
    # Лимиты хранения (число файлов): logs/tasks/<id>.json и logs/events/<id>.json.
    # Правятся через Настройки → История и данные (горячая смена + перезапуск не нужен).
    "logs": {
        "tasks": 100,
        "events": 200
    },
    # Backup Manager v1. Runtime state хранится отдельно в data/backup/.
    "backup": {
        "schema_version": 1,
        "storage": {
            "backend": "local",
            "root": "/var/backups/bot4vps"
        },
        "bot4vps": {
            "automatic": {
                "enabled": True,
                "daily_time": "02:30",
                "keep_last": 7
            },
            "limits": {
                "max_source_bytes": None,
                "max_archive_bytes": 10737418240
            },
            "notifications": {
                "backup": {"enabled": False, "success": False, "error": True},
                "restore": {"enabled": True, "success": False, "error": True}
            }
        },
        "safety": {
            "warning_free_bytes": 5368709120,
            "critical_free_bytes": 2147483648,
            "emergency_free_bytes": 524288000,
            "recovery_free_bytes": 1073741824,
            "staging_ttl_seconds": 86400,
            "claim_ttl_seconds": 3600
        }
    }
}


def load_config():

    if not CONFIG_FILE.exists():

        save_config(DEFAULT_CONFIG)

        return DEFAULT_CONFIG.copy()

    try:

        with open(
            CONFIG_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            config = json.load(f)

    except json.JSONDecodeError:

        # Битый JSON → авто-восстановление из страховки.
        # Ни одной валидной копии → ConfigCorruptedError (аварийный режим).

        config = _restore_config_backup()

    else:

        # Валидный JSON, но не объект (массив/строка/число) — тот же
        # путь восстановления: приложению нужен dict.

        if not isinstance(config, dict):

            config = _restore_config_backup()

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
    logs = config.setdefault("logs", {})
    for name, default in DEFAULT_CONFIG["logs"].items():
        value = logs.get(name)
        if name not in logs:
            logs[name] = default
            changed = True
        elif not isinstance(value, int) or isinstance(value, bool) or value < 1:
            logs[name] = default
            changed = True
    if changed:
        save_config(config)
    return config


def save_config(config):

    _write_config_atomic(
        json.dumps(
            config,
            indent=4,
            ensure_ascii=False
        )
    )


# ==========================================================
# Запись/ротация/восстановление config.json (стойкость).
# Образец — ротация servers.json в core/storage.py; единая точка:
# все записи идут через _write_config_atomic, восстановление —
# _restore_config_backup.
# ==========================================================

def _is_valid_config(data) -> bool:
    """Минимальная проверка: парсится как JSON и является объектом.

    Граница recovery — ровно эта проверка. «JSON валиден, но значение
    плохое» — обычная логика приложения (defaults-долив в load_config,
    валидация секций в геттерах); новая система валидации не создаётся.
    """
    try:
        parsed = json.loads(data)
    except (ValueError, TypeError):
        return False
    return isinstance(parsed, dict)


def _config_history_files() -> list:
    """Ротационные копии config_*.json, от старых к новым.

    config_latest.json в историю не входит (страховка, не история);
    corrupt_config_*.json не попадает — имя не матчится по префиксу
    и кандидатами восстановления быть не может.
    """
    return [
        p for p in sorted(CONFIG_BACKUP_DIR.glob("config_*.json"))
        if p != CONFIG_LATEST
    ]


def _next_rotated_path(prefix: str) -> Path:
    """Свободное имя <prefix>_<ts>.json; при коллизии секунды — суффикс _N.

    Суффикс «_2» лексикографически больше точки «.json» и меньше
    следующей секунды — сортировка имён остаётся хронологической.
    """
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = CONFIG_BACKUP_DIR / ("%s_%s.json" % (prefix, ts))
    n = 2
    while path.exists():
        path = CONFIG_BACKUP_DIR / ("%s_%s_%d.json" % (prefix, ts, n))
        n += 1
    return path


def _write_insurance_file(path: Path, data: bytes) -> None:
    """Атомарно записать копию страховки с правами 0600.

    В config.json секреты (enc1:-токен, totp_secret, password_hash) —
    права строже, чем у обычных файлов каталога backup/.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    path.chmod(0o600)


def _update_config_insurance(candidate: bytes | None) -> None:
    """Обновить страховку после успешной записи config.json.

    config_latest.json = новая записанная версия; кандидат (прежний
    валидный config) уходит в историю config_<ts>.json. Копия не
    пишется, если байт-в-байт равна уже лежащей (идемпотентность).
    """
    CONFIG_BACKUP_DIR.mkdir(exist_ok=True)

    new_bytes = CONFIG_FILE.read_bytes()

    try:
        latest_bytes = CONFIG_LATEST.read_bytes()
    except OSError:
        latest_bytes = None
    if new_bytes != latest_bytes:
        _write_insurance_file(CONFIG_LATEST, new_bytes)

    if candidate is not None:
        history = _config_history_files()
        last = history[-1] if history else None
        if last is None or last.read_bytes() != candidate:
            _write_insurance_file(_next_rotated_path("config"), candidate)

    # Чистка истории (страховку и corrupt-файлы не трогаем)
    history = _config_history_files()
    while len(history) > MAX_CONFIG_BACKUPS:
        history.pop(0).unlink(missing_ok=True)


def _write_config_atomic(text: str) -> None:
    """Атомарная запись config.json с проверкой до и после replace.

    Зафиксированный порядок (не менять):
      1. текущий config.json читается и проверяется — валидный становится
         кандидатом в историю (config_*.json);
      2. новый контент пишется во временный файл и проверяется парсом
         ДО replace — битый новый конфиг никогда не попадёт на диск;
      3. os.replace;
      4. config.json перечитывается и парсится;
      5. только теперь обновляется страховка (config_latest.json = новый,
         кандидат → история). Ошибка на этом шаге НЕ откатывает записанный
         валидный config.json: логируем, страховка остаётся прежней —
         при будущем восстановлении поднимется чуть более старая копия.
    """
    # 1. Кандидат в историю — текущий файл, если он валиден
    candidate = None
    if CONFIG_FILE.exists():
        try:
            data = CONFIG_FILE.read_bytes()
        except OSError:
            data = None
        if data is not None and _is_valid_config(data):
            candidate = data

    # 2. Временный файл + проверка нового контента ДО replace
    with open(TEMP_FILE, "w", encoding="utf-8") as f:
        f.write(text)
        if not text.endswith("\n"):
            f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    if not _is_valid_config(text):
        TEMP_FILE.unlink(missing_ok=True)
        raise ValueError(
            "config.json: новый контент не парсится как JSON-объект"
        )

    # 3. replace
    os.replace(TEMP_FILE, CONFIG_FILE)
    # Секреты (secret_key — подпись сессионных кук, password_hash,
    # enc1:-блоки) не должны быть читаемы локальными пользователями:
    # с secret_key подделывается сессионная кука в обход пароля.
    # 0600 как у страховки (_write_insurance_file); tmp создаётся
    # open() с umask-режимом, поэтому права ставим явно после replace.
    CONFIG_FILE.chmod(0o600)

    # 4. Перечитка (replace атомарен — по сути формальность)
    try:
        ok = _is_valid_config(CONFIG_FILE.read_bytes())
    except OSError:
        ok = False
    if not ok:
        print(
            "[CONFIG] config.json записан, но не перечитывается — "
            "страховка не обновлена",
            flush=True,
        )
        return

    # 5. Страховка: сбой не откатывает валидный config.json
    try:
        _update_config_insurance(candidate)
    except OSError as e:
        print(
            "[CONFIG] config.json записан, но страховка не обновлена: %s" % e,
            flush=True,
        )


def _cleanup_corrupt_config() -> None:
    """Держим последние CORRUPT_CONFIG_KEEP повреждённых файлов."""
    corrupt = sorted(CONFIG_BACKUP_DIR.glob("corrupt_config_*.json"))
    while len(corrupt) > CORRUPT_CONFIG_KEEP:
        corrupt.pop(0).unlink(missing_ok=True)


def _restore_config_backup() -> dict:
    """Восстановить config.json после повреждения.

    Зеркало restore_backup() из core/storage.py:
      - битый файл сохраняется как corrupt_config_<ts>.json (0600) —
        материал для ручного разбора, в поиск копий не попадает;
      - кандидаты: config_latest.json, затем config_*.json от свежей
        к старой, КАЖДАЯ проверяется (парсится + dict);
      - найденная копия пишется и в config.json, и снова в
        config_latest.json — восстановленная версия становится рабочей;
      - ни одной валидной копии → ConfigCorruptedError.
    """
    # Битый файл не уничтожаем (права 0600: в нём могут быть секреты)
    try:
        raw = CONFIG_FILE.read_bytes()
        CONFIG_BACKUP_DIR.mkdir(exist_ok=True)
        _write_insurance_file(_next_rotated_path("corrupt_config"), raw)
        _cleanup_corrupt_config()
    except OSError as e:
        print(
            "[CONFIG] повреждённый config.json не сохранён для разбора: %s" % e,
            flush=True,
        )

    candidates = [CONFIG_LATEST] + list(reversed(_config_history_files()))
    for source in candidates:
        try:
            data = source.read_bytes()
        except OSError:
            continue
        if not _is_valid_config(data):
            continue

        # Копия валидна: она и в config.json, и снова в config_latest
        try:
            CONFIG_FILE.write_bytes(data)
        except OSError as e:
            print(
                "[CONFIG] не удалось записать восстановленный config.json: %s" % e,
                flush=True,
            )
            break
        try:
            if not CONFIG_LATEST.exists() or CONFIG_LATEST.read_bytes() != data:
                _write_insurance_file(CONFIG_LATEST, data)
        except OSError:
            pass

        # Событие в журнал Web (существующий механизм; не в config.json,
        # чтобы не создавать петлю «восстановился → записал статус → …»)
        try:
            from core.event_service import create_event
            from core.event_types import (
                EventLevel,
                EventReason,
                EventType,
            )

            create_event(
                event_type=EventType.GENERAL,
                level=EventLevel.CRITICAL,
                title="Восстановлен повреждённый config.json",
                message="Автоматически восстановлено из %s" % source.name,
                details={
                    "source": source.name,
                    "reason": EventReason.CONFIG_RESTORED.value,
                },
            )
        except Exception as e:
            print(
                "[CONFIG] событие восстановления не записано: %s" % e,
                flush=True,
            )

        print(
            "[CONFIG] config.json повреждён — восстановлено из %s" % source.name,
            flush=True,
        )
        return json.loads(data)

    raise ConfigCorruptedError(
        "config.json повреждён, валидных копий не найдено "
        "(backup/config_latest.json, backup/config_*.json)"
    )


def list_config_backups() -> list:
    """Копии config для ручного восстановления (CLI «Восстановление»).

    Свежие первыми: config_latest.json, затем история config_*.json от
    новой к старой. Каждая копия проверяется индивидуально (valid),
    отсутствующие файлы молча пропускаются. Только факты — без секретов.
    """
    items = []
    for path in [CONFIG_LATEST] + list(reversed(_config_history_files())):
        try:
            data = path.read_bytes()
            mtime = path.stat().st_mtime
        except OSError:
            continue
        items.append({
            "name": path.name,
            "path": str(path),
            "mtime": mtime,
            "valid": _is_valid_config(data),
        })
    return items


def restore_config_backup_file(source) -> dict:
    """Восстановить config.json из указанной копии (явный выбор CLI).

    Отличие от _restore_config_backup(): копию выбирает пользователь, а
    не автопоиск. Семантика та же: копия проверяется ДО записи; битый
    текущий config сохраняется как corrupt_config_<ts>.json (0600,
    материал для разбора); запись идёт через общий путь
    _write_config_atomic — валидный прежний конфиг уйдёт в историю,
    восстановленная версия станет config_latest. Возвращает
    {"source": имя копии}.
    """
    source = Path(source)
    try:
        data = source.read_bytes()
    except OSError as e:
        raise ValueError("Не удалось прочитать копию: %s" % e) from e
    if not _is_valid_config(data):
        raise ValueError("Копия не проходит проверку (битый JSON или не объект)")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError("Копия в неожиданной кодировке (ожидается UTF-8)") from e

    # Битый текущий — не уничтожаем (в нём могут быть секреты)
    try:
        raw = CONFIG_FILE.read_bytes()
        if not _is_valid_config(raw):
            CONFIG_BACKUP_DIR.mkdir(exist_ok=True)
            _write_insurance_file(_next_rotated_path("corrupt_config"), raw)
            _cleanup_corrupt_config()
    except OSError as e:
        print(
            "[CONFIG] повреждённый config.json не сохранён для разбора: %s" % e,
            flush=True,
        )

    _write_config_atomic(text)

    # Событие в журнал Web (существующий механизм; не в config.json)
    try:
        from core.event_service import create_event
        from core.event_types import (
            EventLevel,
            EventReason,
            EventType,
        )

        create_event(
            event_type=EventType.GENERAL,
            level=EventLevel.WARNING,
            title="config.json восстановлен из копии",
            message="Восстановлено из %s (вручную, CLI «Восстановление»)" % source.name,
            details={
                "source": source.name,
                "reason": EventReason.CONFIG_RESTORED.value,
            },
        )
    except Exception as e:
        print(
            "[CONFIG] событие восстановления не записано: %s" % e,
            flush=True,
        )

    print(
        "[CONFIG] config.json восстановлен из %s (вручную)" % source.name,
        flush=True,
    )
    return {"source": source.name}


def reset_config() -> dict:
    """Сброс к DEFAULT_CONFIG (CLI «Восстановление»).

    Мастер первичной установки при этом НЕ открывается автоматически:
    код установки выдаётся отдельной командой CLI. Данные серверов
    (servers.json) и backup-файлы не затрагиваются. Валидный прежний
    конфиг уходит в историю штатным крючком _write_config_atomic.
    deepcopy обязателен: DEFAULT_CONFIG — модульный объект, отдавать
    его изменяемую копию в save_config нельзя.
    """
    config = copy.deepcopy(DEFAULT_CONFIG)
    save_config(config)
    return config


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
# Лимиты хранения истории (Настройки → История и данные)
# ==========================================================

def get_logs_limits():
    """Секция config.json -> logs: лимиты задач и событий (число файлов)."""
    logs = load_config().get("logs") or DEFAULT_CONFIG["logs"]
    return {
        "tasks": logs.get("tasks", DEFAULT_CONFIG["logs"]["tasks"]),
        "events": logs.get("events", DEFAULT_CONFIG["logs"]["events"]),
    }


def set_logs_limits(tasks=None, events=None):
    """Точечно заменить изменённые ключи секции logs.

    ``_patch_config_keys`` заменяет top-level ключ целиком, поэтому секция
    читается нормализованной (load_config доливает дефолты), объединяется
    с изменениями и записывается целиком — соседний лимит не сбрасывается.
    """
    merged = get_logs_limits()
    if tasks is not None:
        merged["tasks"] = int(tasks)
    if events is not None:
        merged["events"] = int(events)
    _patch_config_keys({"logs": merged})


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
# Web UI: HTTPS (web.tls)
# ==========================================================

# Порядок фиксирован: используется в Web/CLI для списков выбора.
TLS_MODES = ("off", "letsencrypt", "self-signed", "custom", "proxy")


def normalize_trusted_proxies(value) -> list[str]:
    """IP и/или CIDR (IPv4/IPv6), без дублей. Ошибка — ValueError с текстом."""
    import ipaddress

    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError("trusted_proxies: ожидается список IP/подсетей")
    out = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("trusted_proxies: пустое значение")
        item = item.strip()
        try:
            if "/" in item:
                ipaddress.ip_network(item, strict=False)
            else:
                ipaddress.ip_address(item)
        except ValueError:
            raise ValueError(
                "trusted_proxies: «%s» — не IP-адрес и не подсеть "
                "(примеры: 192.168.1.10, 192.168.1.0/24)" % item
            )
        if item not in out:
            out.append(item)
    return out


def get_tls_config() -> dict:
    """Секция config.json -> web.tls. Толерантна к старым конфигам без tls.

    Это *намерение и происхождение* сертификата (для UI, CLI и перевыпуска).
    Фактический транспорт панель определяет по systemd-юниту — см.
    core/web_tls.py::unit_tls_state.
    """
    raw = get_web_config().get("tls")
    if not isinstance(raw, dict):
        raw = {}
    mode = raw.get("mode")
    if mode not in TLS_MODES:
        mode = "off"
    try:
        proxies = normalize_trusted_proxies(raw.get("trusted_proxies"))
    except ValueError:
        proxies = []
    domain = raw.get("domain")
    cert_path = raw.get("cert_path")
    key_path = raw.get("key_path")
    common_name = raw.get("common_name")
    return {
        "mode": mode,
        "domain": domain if isinstance(domain, str) and domain else None,
        "cert_path": cert_path if isinstance(cert_path, str) and cert_path else None,
        "key_path": key_path if isinstance(key_path, str) and key_path else None,
        # CN self-signed сертификата: renew без него молча генерирует
        # сертификат с IP вместо выбранного имени.
        "common_name": (
            common_name if isinstance(common_name, str) and common_name else None
        ),
        "trusted_proxies": proxies,
    }


def _validate_and_write_tls(merged: dict) -> dict:
    """Общая проверка + запись web.tls (хвост set/apply)."""
    if merged["mode"] == "proxy" and not merged["trusted_proxies"]:
        raise ValueError(
            "Для режима «за прокси» укажите хотя бы один доверенный proxy "
            "(IP или подсеть, например 192.168.1.10 или 192.168.1.0/24)"
        )
    if merged["mode"] == "letsencrypt" and not merged["domain"]:
        raise ValueError("Для Let's Encrypt укажите домен")
    web = load_config().get("web") or {}
    web["tls"] = merged
    _patch_config_keys({"web": web})
    return merged


def set_tls_config(
    mode: str | None = None,
    domain: str | None = None,
    cert_path: str | None = None,
    key_path: str | None = None,
    common_name: str | None = None,
    trusted_proxies: list | None = None,
) -> dict:
    """Точечно обновить web.tls (merge с текущим значением) с валидацией.

    Меняет только метаданные HTTPS: юнит/рестарт — зона ответственности
    core/web_tls.py (detached-раннер).
    """
    if mode is not None and mode not in TLS_MODES:
        raise ValueError("tls.mode: неизвестный режим «%s»" % mode)
    current = get_tls_config()
    merged = {
        "mode": mode if mode is not None else current["mode"],
        "domain": domain if domain is not None else current["domain"],
        "cert_path": cert_path if cert_path is not None else current["cert_path"],
        "key_path": key_path if key_path is not None else current["key_path"],
        "common_name": (
            common_name if common_name is not None else current["common_name"]
        ),
        "trusted_proxies": (
            normalize_trusted_proxies(trusted_proxies)
            if trusted_proxies is not None
            else current["trusted_proxies"]
        ),
    }
    return _validate_and_write_tls(merged)


def apply_tls_config(cfg: dict) -> dict:
    """Заменить web.tls ЦЕЛИКОМ (без merge) с валидацией.

    Вызов — финализация успешной HTTPS-операции (core/web_tls.py::
    finalize_config): словарь задаёт все ключи разом, поэтому смена режима
    не тащит за собой домен/пути предыдущего.
    """
    mode = cfg.get("mode") or "off"
    if mode not in TLS_MODES:
        raise ValueError("tls.mode: неизвестный режим «%s»" % mode)
    domain = cfg.get("domain")
    cert_path = cfg.get("cert_path")
    key_path = cfg.get("key_path")
    common_name = cfg.get("common_name")
    merged = {
        "mode": mode,
        "domain": domain if isinstance(domain, str) and domain else None,
        "cert_path": cert_path if isinstance(cert_path, str) and cert_path else None,
        "key_path": key_path if isinstance(key_path, str) and key_path else None,
        "common_name": (
            common_name if isinstance(common_name, str) and common_name else None
        ),
        "trusted_proxies": normalize_trusted_proxies(cfg.get("trusted_proxies")),
    }
    return _validate_and_write_tls(merged)


# ==========================================================
# Тема Web UI
# ==========================================================

UI_THEMES = ("dark", "light", "glass")


def get_ui_theme() -> str:
    """Тема Web UI (config.json -> ui_theme). По умолчанию dark, файл не трогаем."""
    value = _read_config_raw().get("ui_theme")
    return value if value in UI_THEMES else "dark"


def set_ui_theme(theme: str) -> str:
    """Точечно сохранить тему Web UI — переживает сброс кеша браузера."""
    if theme not in UI_THEMES:
        raise ValueError("ui_theme: неизвестная тема «%s»" % theme)
    _patch_config_keys({"ui_theme": theme})
    return theme


# ==========================================================
# Backup Manager
# ==========================================================

def get_backup_config() -> dict:
    """Вернуть валидированную секцию config.json -> backup."""
    from core.backup.validation import normalize_backup_config

    raw = load_config().get("backup", DEFAULT_CONFIG["backup"])
    return normalize_backup_config(raw)


def set_backup_config(backup: dict) -> dict:
    """Атомарно заменить только top-level секцию backup после валидации."""
    from core.backup.validation import normalize_backup_config

    normalized = normalize_backup_config(backup)
    _patch_config_keys({"backup": normalized})
    return normalized


def patch_backup_config(patch: dict) -> dict:
    """Рекурсивно обновить секцию backup, не затрагивая другие настройки."""
    if not isinstance(patch, dict):
        raise ValueError("backup patch должен быть объектом")

    def merge(target: dict, updates: dict) -> dict:
        result = dict(target)
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = merge(result[key], value)
            else:
                result[key] = value
        return result

    return set_backup_config(merge(get_backup_config(), patch))


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


def get_saved_bot_token() -> str:
    """Прочитать bot_token из config.json, расшифровав при необходимости.

    Единственная точка чтения токена внутри backend (bot.py, статусы,
    восстановление пароля). Наружу токен не отдаётся — API получают
    только ``token_set`` bool. plaintext-токен (старые установки)
    читается как есть; повреждённый ciphertext → SecretBoxError.
    """
    from core.secretbox import decrypt

    return decrypt(str(_read_config_raw().get("bot_token") or "").strip())


# Пароль шифрования backup-архивов (B4VE). Хранится top-level рядом с
# bot_token (секреты не смешиваются с секцией backup: normalize_backup_config
# строит строгий словарь и отдаёт его в BackupManager и Web-настройки —
# enc1:-значение не должно утекать через эти пути). Человеко-читаемый,
# задаётся/меняется/убирается владельцем; расшифровывается только в памяти
# на время операции шифрования.
BACKUP_PASSWORD_KEY = "backup_encryption_password"
BACKUP_PASSWORD_MAX_LEN = 256


def backup_password_configured() -> bool:
    """Задан ли пароль бэкапов (без расшифровки — безопасно для статусов)."""
    return bool(str(_read_config_raw().get(BACKUP_PASSWORD_KEY) or "").strip())


def get_stored_backup_password() -> str:
    """Прочитать пароль бэкапов, расшифровав enc1:.

    Пустая строка — пароль не задан. При недоступном мастер-ключе
    бросает SecretBoxError: вызывающий решает, что делать (плановый
    бэкап → создать plain-архив с записью в журнал).
    """
    from core.secretbox import decrypt

    return decrypt(str(_read_config_raw().get(BACKUP_PASSWORD_KEY) or "").strip())


def set_stored_backup_password(password: str | None) -> None:
    """Сохранить пароль бэкапов (enc1:) или убрать его (None/'')."""
    from core.secretbox import encrypt

    if password is None or password == "":
        _patch_config_keys({BACKUP_PASSWORD_KEY: ""})
        return
    if not isinstance(password, str) or len(password) > BACKUP_PASSWORD_MAX_LEN:
        raise ValueError(f"Пароль бэкапов — непустая строка до {BACKUP_PASSWORD_MAX_LEN} символов")
    _patch_config_keys({BACKUP_PASSWORD_KEY: encrypt(password)})


def get_telegram_config():
    """Точечное чтение настроек Telegram из config.json (без перезаписи файла)."""
    cfg = _read_config_raw()
    users = cfg.get("allowed_users") or []
    token = get_saved_bot_token()
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

    # Запись — через общий атомарный путь (проверка нового контента
    # ДО replace + перечитка + обновление страховки после)
    if not text.endswith("\n"):
        text += "\n"
    _write_config_atomic(text)


# ==========================================================
# Часовой пояс локального хоста Bot4VPS
# ==========================================================

def get_host_timezone_config() -> str | None:
    """Последняя подтверждённая UI-сменой IANA timezone (не source of truth)."""
    value = _read_config_raw().get("host_timezone")
    return value if isinstance(value, str) and value else None


def set_host_timezone_config(timezone_name: str) -> str:
    """Атомарно сохранить только подтверждённый IANA ID без UTC offset."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    if (
        not isinstance(timezone_name, str)
        or not timezone_name
        or timezone_name != timezone_name.strip()
    ):
        raise ValueError("host_timezone должен быть непустым IANA ID")
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("host_timezone должен быть IANA ID") from exc
    _patch_config_keys({"host_timezone": timezone_name})
    return timezone_name



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
        # На диск токен пишем зашифрованным (core/secretbox); валидация
        # выше идёт по plaintext, введённому пользователем.
        from core.secretbox import encrypt

        updates["bot_token"] = encrypt(tok)
    if updates:
        _patch_config_keys(updates)
    return get_telegram_config()
