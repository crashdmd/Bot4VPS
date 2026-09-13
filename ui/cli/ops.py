"""Операции CLI: тонкий слой над Core (config / web_port / update / security).

Правила:
  - настройки меняются только существующими функциями Core;
  - subprocess — только через systemd_ops;
  - секреты (токен, пароль) не печатаются и не попадают в исключения;
  - операции бросают исключения с человекочитаемым сообщением —
    menu.py превращает их в «✖ …» без traceback.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime

from . import systemd_ops


# ==================================================================
# Статус
# ==================================================================

def get_version() -> str:
    from core.version import APP_VERSION

    return APP_VERSION


def format_duration(seconds: float) -> str:
    total = int(seconds)
    days, total = divmod(total, 86400)
    hours, total = divmod(total, 3600)
    minutes, seconds = divmod(total, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m {seconds}s"


def service_uptime() -> str | None:
    """Uptime сервиса: обе величины — wall-clock (один источник времени).

    В LXC /proc/uptime подменяется lxcfs и несравним с monotonic-метками
    systemd, поэтому считаем от ActiveEnterTimestamp.
    """
    if not systemd_ops.is_active():
        return None
    started = systemd_ops.service_started_at()
    if started is None:
        return None
    return format_duration(max((datetime.now() - started).total_seconds(), 0))


def web_status() -> dict:
    """Состояние Web. Включён = юнит в режиме web+tg (факт, не конфиг).

    Порт — из юнита; при выключенном Web юнит порта не содержит, тогда
    берём последний известный из транзитного состояния смены порта
    (data/web_port.json), если процедура когда-либо выполнялась.
    Нового хранилища ради CLI не заводим.
    """
    from core.web_port import read_state
    from core.web_tls import unit_tls_state

    enabled = systemd_ops.unit_mode() == "web+tg"
    port = None
    if enabled:
        from core.web_port import current_port_from_unit

        port = current_port_from_unit()
    if port is None:
        state = read_state()
        port = state.get("new_port") or state.get("old_port")
    tls = unit_tls_state()
    # Адрес — прямой доступ к сокету панели: в proxy-режиме панель слушает
    # плоский http (TLS терминирует прокси, панель про его домен не знает)
    scheme = "https" if (port and tls["ssl"]) else "http"
    address = f"{scheme}://{systemd_ops.detect_ip()}:{port}" if port else "—"
    return {
        "enabled": enabled,
        "port": port,
        "address": address,
        "tls": tls,
    }


def telegram_running() -> tuple[bool, str | None]:
    """Фактическое состояние Telegram из core/telegram_state (межпроцессно).

    Файл пишет сам процесс сервиса на каждом переходе lifecycle.
    Свежесть: updated_at должен быть не раньше старта текущего запуска
    сервиса — состояние от предыдущего запуска (до рестарта) протухло.
    """
    if not systemd_ops.is_active():
        return False, "сервис остановлен"
    from core.telegram_state import read_state

    state = read_state()
    status = state.get("status")
    if not status:
        return False, "статус не определён"

    # свежесть: состояние принадлежит текущему запуску сервиса?
    try:
        updated = datetime.fromisoformat(str(state.get("updated_at") or ""))
    except ValueError:
        return False, "статус не определён"
    started = systemd_ops.service_started_at()
    if started is not None and updated < started:
        return False, "статус не определён"

    if status == "running":
        return True, None
    if status == "failed":
        return False, state.get("error") or "ошибка запуска"
    if status == "disabled":
        return False, "выключен в настройках"
    if status == "no_token":
        return False, "token не задан"
    if status == "stopped":
        return False, "остановлен"
    return False, "статус не определён"


def _wait_telegram_state(timeout: float = 30.0) -> tuple[bool, str | None]:
    """Дождаться свежего состояния TG после рестарта.

    Новый процесс пишет state при старте бота; пока не написал,
    telegram_running видит протухшее («статус не определён»). Опрашиваем
    пару секунд — иначе tg_enable ложно ругался бы сразу после рестарта.
    """
    deadline = time.monotonic() + timeout
    while True:
        running, note = telegram_running()
        if note != "статус не определён" or time.monotonic() >= deadline:
            return running, note
        time.sleep(1)


def telegram_status() -> dict:
    from core.config import get_telegram_config

    cfg = get_telegram_config()
    running, note = telegram_running()
    return {
        "enabled": bool(cfg.get("enabled")),
        "token_set": bool(cfg.get("token_set")),
        "user_id": cfg.get("user_id"),
        "running": running,
        "note": note,
    }


def collect_status() -> dict:
    return {
        "version": get_version(),
        "service_active": systemd_ops.is_active(),
        "uptime": service_uptime(),
        "web": web_status(),
        "telegram": telegram_status(),
    }


# ==================================================================
# Telegram API (проба одноразовым Bot — как восстановление пароля)
# ==================================================================

def fetch_bot_username(token: str, timeout: float = 15.0) -> str | None:
    """getMe по токену. None — токен не проверен (сеть/невалиден)."""
    from telegram import Bot

    async def _probe() -> str:
        bot = Bot(token=token)
        try:
            await bot.initialize()
            me = await bot.get_me()
            return f"@{me.username}" if me.username else me.first_name
        finally:
            await bot.shutdown()

    try:
        return asyncio.run(asyncio.wait_for(_probe(), timeout))
    except Exception:
        return None


# ==================================================================
# Web
# ==================================================================

def _restart_and_verify() -> None:
    ok, err = systemd_ops.restart_service()
    if not ok:
        raise RuntimeError(f"сервис не поднялся после перезапуска: {err}")


def web_enable(port: int) -> dict:
    """Включить Web: авторизация + firewall + юнит web+tg + restart.

    Тот же состав действий, что install.sh enable-web (reference), кроме
    pip install — зависимости ставятся при установке, CLI не установщик.
    """
    from core.config import set_web_auth
    from ui.web.security import ensure_web_secrets

    if not 1 <= port <= 65535:
        raise ValueError("Порт — число от 1 до 65535")

    set_web_auth(True)
    # Печатает логин и, если пароль не задан, одноразовый пароль
    ensure_web_secrets()

    firewall = systemd_ops.firewall_open_port(port)
    systemd_ops.write_web_unit(port)
    systemd_ops.daemon_reload()
    systemd_ops.systemctl("enable", systemd_ops.SERVICE)
    _restart_and_verify()
    return {
        "port": port,
        "address": f"http://{systemd_ops.detect_ip()}:{port}",
        "firewall": firewall,
    }


def web_disable() -> None:
    """Выключить Web: закрыть порт, юнит tg-only, restart.

    /opt/bot4vps и настройки (включая auth) не трогаем — только режим
    сервиса. Мониторинг и Telegram продолжают работать (bot.py-вход
    поднимает те же core jobs).
    """
    from core.web_port import current_port_from_unit

    port = current_port_from_unit()
    if port:
        systemd_ops.firewall_close_port(port)
    systemd_ops.write_tg_unit()
    systemd_ops.daemon_reload()
    _restart_and_verify()


def web_change_port(new_port: int) -> dict:
    """Смена порта через существующий механизм core/web_port.

    Пишет pending-состояние и запускает detached-раннер (systemd-run
    --scope), который сам переживает restart, правит юнит, проверяет
    health и откатывает при сбое. CLI только ждёт результат.
    """
    from core import web_port

    if isinstance(new_port, bool) or not isinstance(new_port, int):
        raise ValueError("Порт — число от 1 до 65535")
    if not 1 <= new_port <= 65535:
        raise ValueError("Порт — число от 1 до 65535")

    current = web_port.current_port_from_unit()
    if current is None:
        raise ValueError("порт Web UI не найден в systemd-юните (Web выключен?)")
    if new_port == current:
        raise ValueError(f"порт уже используется: {current}")

    changeable, reason = web_port.changeable()
    if not changeable:
        raise ValueError(reason or "смена порта недоступна")
    if web_port.busy():
        raise ValueError("смена порта уже выполняется")

    web_port.write_state(
        status="pending",
        old_port=current,
        new_port=new_port,
        started_at=datetime.now().isoformat(),
        finished_at=None,
        pid=None,
        error=None,
        log=[],
    )
    web_port.launch(new_port)

    # Раннер перезапускает сервис (включая сам web-процесс) — ждём вердикта
    print(f"Смена порта {current} → {new_port} (перезапуск сервиса)...")
    deadline = time.monotonic() + 120
    state = {}
    while time.monotonic() < deadline:
        time.sleep(2)
        state = web_port.read_state()
        if state.get("status") in ("done", "failed"):
            break
    if state.get("status") != "done":
        error = state.get("error") or "превышено время ожидания"
        raise RuntimeError(f"не удалось изменить порт Web: {error}")
    return {"old_port": current, "new_port": new_port}


# ==================================================================
# HTTPS (core/web_tls: раннер + отложенный config)
# ==================================================================

def tls_status() -> dict:
    """Режим HTTPS (config + факт из юнита) и метаданные сертификата."""
    from core.config import get_tls_config
    from core.web_tls import cert_info, changeable, unit_tls_state

    ok, reason = changeable()
    unit = unit_tls_state()
    cert = cert_info(unit["cert_path"]) if unit.get("cert_path") else None
    return {
        "config": get_tls_config(),
        "unit": unit,
        "cert": cert,
        "changeable": ok,
        "reason": reason,
    }


def _tls_wait() -> None:
    """Ждать вердикта раннера (он перезапускает web-процесс — не нас)."""
    from core import web_tls

    deadline = time.monotonic() + 300
    state = {}
    while time.monotonic() < deadline:
        time.sleep(2)
        state = web_tls.read_state()
        if state.get("status") in ("done", "failed"):
            break
    web_tls.finalize_config()
    if state.get("status") != "done":
        error = state.get("error") or {}
        if isinstance(error, dict):
            raise RuntimeError(
                "%s\n  %s" % (error.get("title", "ошибка"), error.get("hint", "")))
        raise RuntimeError(f"не удалось: {error or 'превышено время ожидания'}")


def tls_enable_self_signed(common_name: str | None = None) -> None:
    from core import web_tls

    web_tls.launch(
        {"mode": "self-signed", "common_name": common_name},
        "enable", {"mode": "self-signed", "common_name": common_name})
    print("Генерирую сертификат и перезапускаю панель...")
    _tls_wait()


def tls_enable_letsencrypt(domain: str, email: str | None = None) -> None:
    from core import web_tls

    web_tls.launch(
        {"mode": "letsencrypt", "domain": domain, "email": email},
        "enable", {"mode": "letsencrypt", "domain": domain})
    print("Выпускаю сертификат Let's Encrypt (порт 80)...")
    _tls_wait()


def tls_enable_custom(cert_path: str, key_path: str) -> None:
    from core import web_tls

    web_tls.launch(
        {"mode": "custom", "cert_path": cert_path, "key_path": key_path},
        "enable", {"mode": "custom", "cert_path": cert_path, "key_path": key_path})
    print("Проверяю пару и перезапускаю панель...")
    _tls_wait()


def tls_enable_proxy(trusted_proxies: list) -> None:
    from core import web_tls

    web_tls.launch(
        {"mode": "proxy", "trusted_proxies": trusted_proxies},
        "enable", {"mode": "proxy", "trusted_proxies": trusted_proxies})
    print("Настраиваю режим за прокси...")
    _tls_wait()


def tls_disable() -> None:
    from core import web_tls

    web_tls.launch({}, "disable", {"mode": "off"})
    print("Выключаю HTTPS (возврат на HTTP)...")
    _tls_wait()


def tls_renew(force: bool = False) -> None:
    """Перевыпуск: force=true — кнопочный осознанный перевыпуск LE."""
    from core.config import get_tls_config
    from core import web_tls

    cfg = get_tls_config()
    mode = cfg.get("mode")
    if mode not in ("letsencrypt", "self-signed", "custom"):
        raise ValueError("Перевыпуск имеет смысл при включённом HTTPS-режиме")
    if not web_tls.unit_tls_state()["ssl"] and mode != "custom":
        raise ValueError("Панель сейчас работает без TLS — сначала включите режим")
    params = {
        "mode": mode,
        "domain": cfg.get("domain"),
        "email": None,          # renew не перерегистрирует аккаунт LE
        "cert_path": cfg.get("cert_path"),
        "key_path": cfg.get("key_path"),
        "common_name": cfg.get("common_name"),
        "trusted_proxies": cfg.get("trusted_proxies"),
        "force": force,
    }
    web_tls.launch(params, "renew", None)
    print("Перевыпускаю сертификат...")
    _tls_wait()


def web_change_password(new_password: str) -> None:
    from ui.web.security import MIN_WEB_PASSWORD_LEN, set_web_password

    if len(new_password) < MIN_WEB_PASSWORD_LEN:
        raise ValueError(f"Пароль не короче {MIN_WEB_PASSWORD_LEN} символов")
    set_web_password(new_password)


def web_totp_enabled() -> bool:
    from ui.web.security import totp_enabled

    return totp_enabled()


def web_reset_totp() -> None:
    """Аварийный сброс 2FA из консоли: единственный путь при потере
    телефона (веб-отключение требует код из приложения)."""
    from ui.web.security import clear_totp_secret

    clear_totp_secret()


# ==================================================================
# Пароль резервных копий (B4VE)
# ==================================================================

def backup_password_configured() -> bool:
    """Задан ли пароль резервных копий (без расшифровки)."""
    from core.config import backup_password_configured as _configured

    return _configured()


def backup_password_clear() -> None:
    """Очистить пароль резервных копий из консоли (аварийный путь
    «забыл пароль»: Web требует подтверждения 2FA/TG-кодом, консоль —
    доверенный административный канал). Новые архивы создаются без
    шифрования; старые остаются со своим (утерянным) паролем."""
    from core.config import set_stored_backup_password

    set_stored_backup_password(None)


# ==================================================================
# Мастер-ключ (enc1:)
# ==================================================================

def masterkey_state() -> dict:
    """Состояние мастер-ключа (см. core.secretbox.master_key_state)."""
    from core import secretbox

    return secretbox.master_key_state()


def masterkey_read() -> str:
    """Значение мастер-ключа — только для консольного «Показать»."""
    from core import secretbox

    return secretbox.read_master_key()


def masterkey_restore(key: str) -> dict:
    """Ввести существующий ключ: проверка по всем enc1: данным."""
    from core import secretbox

    return secretbox.restore_master_key(key)


def plaintext_secrets_found() -> bool:
    """Есть ли незашифрованные секреты (сканер ядра, без расшифровки)."""
    from core.secretbox import scan_plaintext_secrets

    return scan_plaintext_secrets()["found"]


def encrypt_all_secrets() -> dict:
    """Зашифровать все найденные plaintext-секреты (единая функция ядра).

    Возвращает {"encrypted": {метка: count}, "plaintext": контрольный
    rescan} — сами значения наружу не выходят.
    """
    from core.secretbox import encrypt_all_plaintext_secrets

    return encrypt_all_plaintext_secrets()


def masterkey_create_new() -> dict:
    """Создать новый ключ при потерянном: старые enc1: очищаются.

    Возвращает {state, cleared}. Вызывается только после явного
    подтверждения в menu.py.
    """
    from core import secretbox
    from core.config import _patch_config_keys, _read_config_raw
    from core import storage

    scan = secretbox.scan_encrypted()
    if not scan["found"]:
        raise ValueError(
            "Зашифрованных данных нет — новый ключ не требуется "
            "(создастся автоматически при первом секрете)"
        )

    cleared: list[str] = []
    secretbox._create_key_exclusive()

    # config.json: bot_token, web.totp_secret
    raw = _read_config_raw()
    updates = {}
    if raw.get("bot_token"):
        updates["bot_token"] = ""
    if isinstance(raw.get("web"), dict) and raw["web"].get("totp_secret"):
        web = dict(raw["web"])
        web.pop("totp_secret", None)
        updates["web"] = web
        cleared.append("2FA")
    if updates:
        _patch_config_keys(updates)
        if "bot_token" in updates:
            cleared.append("Telegram Bot Token")

    # servers.json: пароли серверов
    with storage.data_lock():
        data = storage.load_data()
        count = 0
        for server in data.get("servers", []):
            if isinstance(server, dict) and server.get("password"):
                server["password"] = ""
                count += 1
        if count:
            storage.save_data(data)
            cleared.append(f"пароли {count} серверов")

    return {"state": secretbox.master_key_state()["state"], "cleared": cleared}


def masterkey_field_labels(fields: list[str]) -> str:
    """Человекочитаемые названия зашифрованных полей."""
    labels = {
        "server_passwords": "пароли серверов",
        "bot_token": "Telegram Bot Token",
        "totp_secret": "секрет 2FA",
    }
    return ", ".join(labels.get(f, f) for f in (fields or []))


# ==================================================================
# Telegram
# ==================================================================

def tg_enable() -> None:
    from core.config import get_telegram_config, set_telegram_enabled

    cfg = get_telegram_config()
    if not cfg.get("token_set"):
        raise ValueError("Сначала задайте Bot Token (пункт 2)")
    if cfg.get("user_id") is None:
        raise ValueError("Сначала задайте Telegram User ID (пункт 3)")
    set_telegram_enabled(True)
    _restart_and_verify()
    running, note = _wait_telegram_state()
    if not running:
        raise RuntimeError(f"бот не поднялся: {note or 'см. journalctl -u bot4vps'}")


def tg_disable() -> None:
    from core.config import set_telegram_enabled

    set_telegram_enabled(False)
    _restart_and_verify()


def tg_set_token(token: str) -> str:
    """Сменить токен: проверка getMe → сохранение (enc1:) → restart.

    При ошибке проверки старый токен не меняем. Токен не печатаем —
    возвращаем только имя бота.
    """
    from core.config import _is_bot_token_configured, set_telegram_credentials

    token = (token or "").strip()
    if not _is_bot_token_configured(token):
        raise ValueError("Токен не похож на Bot Token (получите у @BotFather)")

    username = fetch_bot_username(token)
    if username is None:
        raise ValueError(
            "Не удалось проверить токен через Telegram API — сохранение отменено"
        )

    set_telegram_credentials(bot_token=token)
    _restart_and_verify()
    return username


def tg_set_user(user_id: str) -> int:
    """Сменить allowed-пользователя Telegram.

    Рестарт не нужен: core/auth.py читает config.json на каждом сообщении.
    """
    from core.config import set_telegram_credentials

    raw = str(user_id or "").strip()
    if not raw.isdigit():
        raise ValueError("Telegram User ID должен быть числом")
    set_telegram_credentials(user_id=raw)
    return int(raw)


# ==================================================================
# Restart / Start
# ==================================================================

def restart_or_start() -> str:
    """Динамический пункт 4: работающий — restart, остановленный — start.
    Возвращает 'restarted' | 'started'."""
    if systemd_ops.is_active():
        _restart_and_verify()
        return "restarted"
    ok, err = systemd_ops.start_service()
    if not ok:
        raise RuntimeError(f"сервис не запустился: {err}")
    return "started"


# ==================================================================
# Update (встроенный updater, тот же что в Web UI)
# ==================================================================

def update_check() -> dict:
    from core.update import updater

    return asyncio.run(updater.check_for_update(notify=False))


def update_install(target_version: str) -> None:
    """Запустить обновление и дождаться результата.

    Раннер качает релиз, ставит и перезапускает сервис; итог фиксируется
    уже перезапущенным процессом (init_on_startup сравнивает версии).
    """
    from core.update import updater

    result = asyncio.run(updater.start_install())
    if not result.get("ok"):
        raise RuntimeError("не удалось запустить обновление")

    print("Обновление Bot4VPS...")
    deadline = time.monotonic() + 600
    state = {}
    busy = ("checking", "downloading", "installing", "rolling_back")
    while time.monotonic() < deadline:
        time.sleep(3)
        state = updater.read_state()
        if state.get("status") not in busy:
            break
    ok = state.get("status") == "idle" and state.get("current_version") == target_version
    if not ok:
        error = state.get("last_error") or "обновление не завершилось успешно"
        raise RuntimeError(error)


# ==================================================================
# Удаление
# ==================================================================

def uninstall_service_only() -> None:
    """Удалить сервис, сохранив данные.

    /opt/bot4vps (код, config.json, servers.json, data/, keys/, secret.key)
    не трогаем — после этого возможна переустановка с сохранением данных.
    """
    from core.web_port import current_port_from_unit

    port = current_port_from_unit()
    if port:
        systemd_ops.firewall_close_port(port)
    systemd_ops.systemctl("disable", "--now", systemd_ops.SERVICE)
    systemd_ops.remove_unit()
    systemd_ops.daemon_reload()
    systemd_ops.remove_wrapper()


def uninstall_full() -> None:
    """Полное удаление: сервис + команда + весь /opt/bot4vps.

    Внешние архивы /var/backups/bot4vps не трогаем (как и install.sh
    remove): это данные пользователя, возможно, единственная копия.
    Каталог удаляется строго последним шагом.
    """
    from core.web_port import current_port_from_unit

    port = current_port_from_unit()
    if port:
        systemd_ops.firewall_close_port(port)
    systemd_ops.systemctl("disable", "--now", systemd_ops.SERVICE)
    systemd_ops.remove_unit()
    systemd_ops.daemon_reload()
    systemd_ops.remove_wrapper()
    systemd_ops.delete_install_dir()


# ==================================================================
# Восстановление (раздел 3 главного меню)
# ==================================================================

def recovery_status() -> dict:
    """Диагностика для пункта «Восстановление»: только факты, без секретов.

    config_valid: None = файла нет (НЕ авария, создастся DEFAULT_CONFIG),
    True/False = валиден/повреждён. mode — зеркало логики
    ui/web/security.py (wizard/expired/stub/open/ok), вычисленное по
    сырому состоянию, чтобы диагностика работала и в сломанных
    конфигурациях. setup_code несёт сам код — меню печатает только
    факт его наличия и срок.
    """
    from core import config as cfg
    from core.setup_code import setup_code_state

    try:
        raw = cfg.CONFIG_FILE.read_bytes()
        config_valid = bool(cfg._is_valid_config(raw))
    except OSError:
        config_valid = None

    copies: list = []
    admin = None
    auth = None
    if config_valid:
        try:
            copies = cfg.list_config_backups()
        except Exception:
            copies = []
        try:
            web = cfg.get_web_config()
            admin = bool(web.get("password_hash"))
            auth = bool(web.get("auth_enabled"))
        except Exception:
            admin = None

    state = setup_code_state()

    if config_valid is False:
        mode = "corrupt"
    elif config_valid is None:
        mode = "missing"
    elif admin is None:
        mode = "unknown"
    elif not admin:
        if state["code"]:
            mode = "wizard"
        elif state["expired"]:
            mode = "expired"
        elif auth:
            mode = "stub"
        else:
            mode = "open"
    else:
        mode = "ok" if auth else "open_admin"

    try:
        from core.storage import load_data

        servers = len(load_data().get("servers") or [])
    except Exception:
        servers = None

    try:
        from core import secretbox

        masterkey = secretbox.master_key_state().get("state")
    except Exception:
        masterkey = None

    return {
        "config_valid": config_valid,
        "copies": copies,
        "servers": servers,
        "masterkey": masterkey,
        "admin": admin,
        "auth": auth,
        "mode": mode,
        "setup_code": state,
    }


def config_backups() -> list:
    """Копии config для восстановления (свежие первыми)."""
    from core.config import list_config_backups

    return list_config_backups()


def restore_config_from(path: str) -> dict:
    """Восстановить config.json из указанной копии (ядро core/config)."""
    from core.config import restore_config_backup_file

    return restore_config_backup_file(path)


def reset_config() -> dict:
    """Сбросить конфигурацию к DEFAULT_CONFIG (ядро core/config)."""
    from core.config import reset_config as _reset

    return _reset()


def setup_code_state() -> dict:
    """Состояние кода первичной установки (core/setup_code)."""
    from core.setup_code import setup_code_state as _state

    return _state()


def web_admin_exists() -> bool:
    """Задан ли администратор Web (password_hash непуст; определение —
    ui/web/security.admin_exists, ядро одно и то же)."""
    from ui.web.security import admin_exists

    return admin_exists()


def setup_code_issue() -> str:
    """Перевыпустить код установки (drop-in + daemon-reload)."""
    from core.setup_code import issue_setup_code

    return issue_setup_code()


def setup_code_dropin_exists() -> bool:
    """Есть ли физически drop-in с кодом (копилка: остаток после
    существующего админа)."""
    from core.setup_code import DROPIN_FILE

    return DROPIN_FILE.exists()


def setup_code_dropin_remove() -> None:
    from core.setup_code import remove_setup_code

    remove_setup_code()


# ==================================================================
# Self-restore: восстановление самого Bot4VPS из архива (раздел 3)
# ==================================================================
# CLI не содержит restore-логики: выбор архива, пароль (getpass),
# вызов ядра и поллинг операции. Механизм — core/backup/self_restore,
# тот же, что у Web.

_TERMINAL_OPERATION_STATUSES = ("completed", "failed", "cancelled")


def _restore_manager():
    from core.backup.manager import BackupManager
    from core.config import get_backup_config

    return BackupManager(get_backup_config())


def self_restore_archives() -> list:
    """Архивы для восстановления самого бота.

    Управляемые bot4vps-копии каталога + импортированные со scope bot4vps
    (импорт «без выбора сервера» из Web). Секретов нет — только имена,
    размеры и факт шифрования.
    """
    manager = _restore_manager()
    items: list[dict] = []
    for record in manager.list_catalog():
        if record.get("type") != "bot4vps":
            continue
        archive = record.get("archive") or {}
        items.append({
            "kind": "managed",
            "id": record["backup_id"],
            "filename": record.get("filename"),
            "created_at": record.get("created_at") or record.get("published_at"),
            "bytes": archive.get("bytes"),
            "encrypted": bool(archive.get("encrypted")),
        })
    for publication in manager.list_imported_archives():
        destination = publication.get("destination") or {}
        if destination.get("scope") != "bot4vps":
            continue
        items.append({
            "kind": "imported",
            "id": publication.get("entry_key"),
            "filename": publication.get("filename"),
            "created_at": publication.get("imported_at"),
            "bytes": publication.get("bytes"),
            "encrypted": bool(publication.get("encrypted")),
        })
    items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return items


def self_restore_prepare(archive: dict, password: str | None) -> dict:
    """Подготовка восстановления через ядро (план + защитная копия)."""
    manager = _restore_manager()
    common = {
        "restore_mode": "merge",
        "protective_backup": True,
        "apply": False,
        "password": password,
    }
    if archive["kind"] == "managed":
        return manager.submit_restore(archive["id"], **common)
    return manager.submit_imported_restore(archive["id"], **common)


def self_restore_apply(archive: dict, prepared_operation_id: str, password: str | None) -> dict:
    """Применение подготовленного восстановления (тот же механизм, что у Web)."""
    manager = _restore_manager()
    common = {
        "prepared_operation_id": prepared_operation_id,
        "apply": True,
        "confirm": True,
        "password": password,
    }
    if archive["kind"] == "managed":
        return manager.submit_restore(archive["id"], **common)
    return manager.submit_imported_restore(archive["id"], **common)


def wait_operation(operation_id: str, *, timeout: float = 3700.0, on_update=None) -> dict:
    """Поллинг операции (с живым прогрессом self-restore из state.json)."""
    manager = _restore_manager()
    deadline = time.monotonic() + timeout
    last_key = None
    while True:
        operation = manager.get_operation(operation_id)
        key = (
            operation.get("status"),
            operation.get("stage"),
            (operation.get("self_restore") or {}).get("stage"),
        )
        if key != last_key:
            if on_update is not None:
                on_update(operation)
            last_key = key
        if operation.get("status") in _TERMINAL_OPERATION_STATUSES:
            return operation
        if time.monotonic() >= deadline:
            return operation
        time.sleep(1.0)


def self_restore_pending() -> dict | None:
    """Висящая (незакрытая) операция self-restore, если есть."""
    for operation in _restore_manager().list_operations(operation_type="restore"):
        if operation.get("status") in _TERMINAL_OPERATION_STATUSES:
            continue
        if (operation.get("restore") or {}).get("self_restore") is not None:
            return operation
    return None


def self_restore_finalize(operation_id: str) -> dict:
    """Закрыть висящую операцию self-restore по state.json раннера."""
    from core.backup.self_restore import finalize_self_restore

    return finalize_self_restore(
        _restore_manager(),
        operation_id,
        runner_finished=False,
    )
