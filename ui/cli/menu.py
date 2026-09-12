"""Главное меню CLI Bot4VPS: рендер, навигация, ввод.

Контракт модуля:
  - после действия возвращаемся в текущее меню, а не выходим;
  - «0. Назад» есть во всех подменю;
  - обычная ошибка операции не роняет CLI (✖ + Enter, без traceback);
  - Ctrl+C в живом журнале возвращает в меню, не завершая CLI;
  - Ctrl+C/EOF в главном меню — выход (эквивалент «0»);
  - секреты не печатаются: пароли/токен — getpass, имя бота без токена.
"""
from __future__ import annotations

import getpass
import os
import sys

from . import ops, systemd_ops

BOX_WIDTH = 38


# ==================================================================
# Рендер
# ==================================================================

def _box(title: str, items: list[str]) -> None:
    border = "═" * BOX_WIDTH
    print("╔" + border + "╗")
    print("║" + title.center(BOX_WIDTH) + "║")
    print("╠" + border + "╣")
    for item in items:
        print("║" + item.ljust(BOX_WIDTH)[:BOX_WIDTH] + "║")
    print("╚" + border + "╝")


def _header(title: str) -> None:
    print()
    print(title)
    print("─" * 36)


def _bullet(on: bool) -> str:
    return "●" if on else "○"


# ==================================================================
# Ввод
# ==================================================================

def ask(prompt: str) -> str:
    return input(prompt).strip()


def confirm(prompt: str, default: bool = False) -> bool:
    raw = input(prompt).strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "д", "да")


def pause() -> None:
    try:
        input("\nНажмите Enter для продолжения...")
    except (EOFError, KeyboardInterrupt):
        pass


def _clear_printed_secret() -> None:
    """Стереть выведенный в stdout секрет из скроллбэка терминала.

    ANSI-последовательность очистки экрана + скроллбэка (ESC[3J + ESC[2J
    + ESC[H): поддерживается современными терминалами (xterm, GNOME
    Terminal, kitty, tmux, Windows Terminal). В перенаправлённых/тупых
    терминалах последовательность просто не даст эффекта — не страшно.
    """
    sys.stdout.write("\x1b[3J\x1b[2J\x1b[H")
    sys.stdout.flush()


def ask_password(prompts: tuple[str, str] = ("Новый пароль: ", "Повторите пароль: ")) -> str:
    """Скрытый ввод пароля дважды; несовпадение/короткий — ошибка."""
    first = getpass.getpass(prompts[0])
    second = getpass.getpass(prompts[1])
    if first != second:
        raise ValueError("Пароли не совпадают")
    if len(first) < 6:
        raise ValueError("Пароль не короче 6 символов")
    return first


def action(title: str, fn, *args, **kwargs) -> bool:
    """Выполнить операцию меню. Ошибка → сообщение без traceback, CLI жив."""
    try:
        fn(*args, **kwargs)
        return True
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        message = message.splitlines()[0][:200]
        print(f"\n✖ {title}:\n  {message}")
        pause()
        return False


# ==================================================================
# Подменю
# ==================================================================

def status_menu() -> None:
    try:
        info = ops.collect_status()
    except Exception as exc:
        print(f"\n✖ Не удалось собрать статус: {exc}")
        pause()
        return

    web = info["web"]
    tg = info["telegram"]
    _header("Bot4VPS")
    print(f"Версия:       {info['version']}")
    print(f"Сервис:       {_bullet(info['service_active'])} "
          f"{'работает' if info['service_active'] else 'остановлен'}"
          + (f" (uptime {info['uptime']})" if info["uptime"] else ""))
    print(f"Web:          {_bullet(web['enabled'])} "
          f"{'включён' if web['enabled'] else 'выключен'}"
          + (f" :{web['port']}" if web["enabled"] and web["port"] else ""))
    if tg["enabled"]:
        state = "работает" if tg["running"] else f"не работает ({tg['note']})"
    else:
        state = "выключен"
    print(f"Telegram:     {_bullet(tg['enabled'] and tg['running'])} {state}")
    print("─" * 36)
    while True:
        if ask("0. Назад ") == "0":
            return


def web_menu() -> None:
    """Раздел «Безопасность»: Web-панель (порт, пароль, 2FA) и её режим."""
    while True:
        try:
            web = ops.web_status()
        except Exception as exc:
            print(f"\n✖ Не удалось получить состояние Web: {exc}")
            pause()
            return
        _header("Безопасность")
        print(f"Статус:       {_bullet(web['enabled'])} "
              f"{'включён' if web['enabled'] else 'выключен'}")
        print(f"Адрес:        {web['address']}")
        print("─" * 36)
        print("1. " + ("Выключить" if web["enabled"] else "Включить"))
        print("2. Сменить порт")
        # HTTPS управляет транспортом панели — только при включённом Web:
        # в tg-only пункту нечего настраивать, он бы только сбивал.
        if web["enabled"]:
            # «включён» = свой TLS (ssl) или работа за прокси (proxy):
            # scheme в proxy-режиме — http, панель слушает плоский сокет
            tls_on = web["tls"]["ssl"] or web["tls"]["proxy"]
            print("3. HTTPS сертификат" + (" (включён)" if tls_on else ""))
        print("4. Сменить пароль доступа")
        if ops.web_totp_enabled():
            print("5. Сбросить двухфакторную аутентификацию")
        print("6. Мастер-ключ")
        print("7. " + (
            "Очистить пароль резервных копий"
            if ops.backup_password_configured()
            else "Пароль резервных копий не задан"
        ))
        secrets_found = ops.plaintext_secrets_found()
        if secrets_found:
            print("8. Зашифровать все секреты")
        print()
        print("0. Назад")
        choice = ask("Выберите пункт: ")
        if choice == "0":
            return
        if choice == "1":
            if web["enabled"]:
                print("Выключаю Web...")
                if action("Не удалось выключить Web", ops.web_disable):
                    print("● Web выключен (Telegram и мониторинг работают)")
                    pause()
            else:
                _web_enable_flow(web)
        elif choice == "2":
            _web_change_port_flow(web)
        elif choice == "3" and web["enabled"]:
            _tls_menu(web)
            continue
        elif choice == "4":
            _web_change_password_flow()
        elif choice == "5":
            _web_reset_totp_flow()
        elif choice == "6":
            masterkey_menu()
            continue
        elif choice == "7":
            _backup_password_clear_flow()
            continue
        elif choice == "8" and secrets_found:
            _encrypt_all_secrets_flow()
            continue


def _ask_port(default: int | None) -> int | None:
    shown = default or 8080
    raw = ask(f"Порт Web UI [{shown}]: ")
    if not raw:
        return shown
    try:
        port = int(raw)
    except ValueError:
        print("✖ Порт должен быть числом")
        return None
    if not 1 <= port <= 65535:
        print("✖ Порт — число от 1 до 65535")
        return None
    return port


def _web_enable_flow(web: dict) -> None:
    port = _ask_port(web["port"])
    if port is None:
        return
    print("Включаю Web...")
    try:
        result = ops.web_enable(port)
    except Exception as exc:
        message = str(exc).strip().splitlines()[0][:200]
        print(f"\n✖ Не удалось включить Web:\n  {message}")
        pause()
        return
    print("● Web включён")
    print(f"  Адрес: {result['address']}")
    if result["firewall"] == "failed":
        print("  ⚠ Не удалось открыть порт в firewall — проверьте правила вручную")
    pause()


def _web_change_port_flow(web: dict) -> None:
    port = _ask_port(web["port"])
    if port is None:
        return
    if action("Не удалось изменить порт Web", ops.web_change_port, port):
        print(f"● Порт изменён: http://{systemd_ops.detect_ip()}:{port}")
        pause()


_TLS_MODE_LABELS = {
    "off": "выключен (HTTP)",
    "letsencrypt": "Let's Encrypt",
    "self-signed": "самоподписанный",
    "custom": "свой сертификат",
    "proxy": "за реверс-прокси",
}


def _tls_menu(web: dict) -> None:
    """Подменю «HTTPS сертификат» (только при включённом Web).

    Показывает режим из config и фактическую схему из юнита — после
    неудачной операции они могут расходиться, и пользователь должен
    видеть правду. Раннер перезапускает панель; CLI ждёт вердикта.
    """
    while True:
        try:
            status = ops.tls_status()
        except Exception as exc:
            print(f"\n✖ Не удалось получить состояние HTTPS: {exc}")
            pause()
            return
        cfg = status["config"]
        unit = status["unit"]
        _header("HTTPS сертификат")
        mode_label = _TLS_MODE_LABELS.get(cfg["mode"], cfg["mode"])
        print(f"Режим:        {mode_label}")
        active_tls = unit["ssl"] or unit["proxy"]
        if cfg["mode"] != "off" and not active_tls:
            print("⚠ Режим задан, но панель сейчас работает без HTTPS —")
            print("  включите режим заново (после сбоя конфигурация откатывается)")
        if cfg["domain"]:
            print(f"Домен:        {cfg['domain']}")
        if cfg.get("trusted_proxies"):
            print(f"Прокси:       {', '.join(cfg['trusted_proxies'])}")
        cert = status.get("cert")
        if cert:
            print(f"Сертификат:   {cert['subject']}")
            print(f"Действителен: до {cert['not_after'][:10]} "
                  f"(осталось {cert['days_left']} дн.)")
        print("─" * 36)
        print("1. Let's Encrypt (бесплатный, с автопродлением)")
        print("2. Самоподписанный")
        print("3. Свой сертификат (пути на сервере)")
        print("4. За реверс-прокси (терминация TLS снаружи)")
        print("5. Перевыпустить")
        print("6. Выключить HTTPS")
        print()
        print("0. Назад")
        choice = ask("Выберите пункт: ")
        if choice == "0":
            return
        if choice == "1":
            _tls_letsencrypt_flow()
        elif choice == "2":
            _tls_self_signed_flow()
        elif choice == "3":
            _tls_custom_flow()
        elif choice == "4":
            _tls_proxy_flow()
        elif choice == "5":
            _tls_renew_flow()
        elif choice == "6":
            _tls_disable_flow()


def _tls_enabled_hint() -> None:
    print("Панель будет перезапущена — соединение оборвётся на несколько секунд.")
    if not confirm("Продолжить? [y/N]: "):
        print("Отменено.")
        raise _Cancelled()


class _Cancelled(Exception):
    """Пользователь передумал на подтверждении — вернуться в подменю."""


def _tls_run(title: str, fn, *args) -> None:
    try:
        fn(*args)
    except _Cancelled:
        return
    except Exception as exc:
        message = str(exc).strip()
        print(f"\n✖ {title}:\n  {message[:400]}")
        pause()
        return
    print("● Готово")
    pause()


def _tls_letsencrypt_flow() -> None:
    print()
    print("Let's Encrypt выпустит бесплатный сертификат на ваш домен.")
    print("Требования: A-запись домена указывает на этот сервер, порт 80 свободен")
    print("и достижим из интернета. Сертификат продлевается автоматически.")
    print()
    domain = ask("Домен (например panel.example.com): ").strip().lower()
    if not domain:
        print("✖ Домен обязателен")
        return
    email = ask("E-mail для Let's Encrypt (можно пропустить, Enter): ").strip() or None
    print()
    _tls_enabled_hint()
    _tls_run("Не удалось выпустить сертификат",
             ops.tls_enable_letsencrypt, domain, email)


def _tls_self_signed_flow() -> None:
    print()
    print("Самоподписанный сертификат: браузер будет предупреждать о нём,")
    print("но трафик шифруется. Подходит для локальной сети и тестов.")
    print()
    default_cn = systemd_ops.detect_ip()
    cn = ask(f"Имя в сертификате (домен или IP) [{default_cn}]: ").strip() or default_cn
    print()
    _tls_enabled_hint()
    _tls_run("Не удалось создать сертификат",
             ops.tls_enable_self_signed, cn)


def _tls_custom_flow() -> None:
    print()
    print("Своя пара сертификат+ключ уже лежит на сервере (например, от")
    print("другого ACME-клиента). Файлы не копируются — сервис ссылается")
    print("на эти пути напрямую, обновляйте их на месте.")
    print()
    cert_path = ask("Путь к сертификату (PEM): ").strip()
    key_path = ask("Путь к закрытому ключу (PEM): ").strip()
    if not cert_path or not key_path:
        print("✖ Нужны оба пути")
        return
    print()
    _tls_enabled_hint()
    _tls_run("Не удалось использовать сертификат",
             ops.tls_enable_custom, cert_path, key_path)


def _tls_proxy_flow() -> None:
    print()
    print("TLS терминирует реверс-прокси (Nginx Proxy Manager, Traefik и т.п.),")
    print("панель остаётся по HTTP и доверяет заголовкам X-Forwarded-* только")
    print("от указанных адресов. Прокси может быть на другой машине сети.")
    print()
    raw = ask("Доверенные proxy через запятую (IP или подсеть): ").strip()
    proxies = [item.strip() for item in raw.split(",") if item.strip()]
    if not proxies:
        print("✖ Нужен хотя бы один адрес")
        return
    print()
    _tls_enabled_hint()
    _tls_run("Не удалось включить режим за прокси",
             ops.tls_enable_proxy, proxies)


def _tls_renew_flow() -> None:
    print()
    print("Осознанный перевыпуск: Let's Encrypt — принудительно (--force-renewal),")
    print("самоподписанный — новой генерацией, свой — перечиткой файлов.")
    print()
    if not confirm("Перевыпустить сертификат? [y/N]: "):
        print("Отменено.")
        return
    _tls_run("Не удалось перевыпустить сертификат", ops.tls_renew, True)


def _tls_disable_flow() -> None:
    print()
    print("Панель вернётся на чистый HTTP: пароль и кука будут ходить по сети")
    print("открытым текстом.")
    print()
    if not confirm("Выключить HTTPS? [y/N]: "):
        print("Отменено.")
        return
    _tls_run("Не удалось выключить HTTPS", ops.tls_disable)


def _web_change_password_flow() -> None:
    try:
        password = ask_password()
    except ValueError as exc:
        print(f"✖ {exc}")
        return
    if action("Не удалось сменить пароль", ops.web_change_password, password):
        print("● Пароль Web изменён")
        pause()


def _web_reset_totp_flow() -> None:
    """Аварийный сброс 2FA: путь при потере телефона (веб требует код)."""
    print()
    print("Двухфакторная аутентификация будет выключена:")
    print("вход в Web вернётся к паролю без кода из приложения.")
    print("Подходит, если приложение-аутентификатор потеряно.")
    print()
    if not confirm("Сбросить двухфакторную аутентификацию? [y/N]: "):
        print("Отменено.")
        return
    if action("Не удалось сбросить 2FA", ops.web_reset_totp):
        print("● Двухфакторная аутентификация выключена")


def _backup_password_clear_flow() -> None:
    """Очистить пароль резервных копий (B4VE) — аварийный путь «забыл пароль».

    Консоль — доверенный административный канал: текущий пароль резервных
    копий не спрашивается (Web-путь требует 2FA/TG-код, но пароль мог быть
    утерян). Новые архивы создаются без шифрования; старые остаются со своим
    (утерянным) паролем.
    """
    if not ops.backup_password_configured():
        print("\nПароль резервных копий не задан.")
        pause()
        return
    print()
    print("⚠️  Вы действительно хотите удалить пароль резервных копий?")
    print("После очистки новые архивы защищённых целей не смогут быть")
    print("зашифрованы, пока не будет задан новый пароль.")
    print("Старые зашифрованные архивы продолжат требовать свои пароли.")
    print()
    if not confirm("Удалить пароль резервных копий? [y/N]: "):
        print("Отменено.")
        return
    if action("Не удалось очистить пароль резервных копий", ops.backup_password_clear):
        print("● Пароль резервных копий удалён")
        print("  Новый пароль можно задать в Web: Настройки → Безопасность.")
        pause()


def _format_secret_counts(encrypted: dict) -> str:
    """«пароли серверов: 17, Telegram Bot Token» по счётчикам из ядра."""
    labels = {
        "server_passwords": "пароли серверов",
        "bot_token": "Telegram Bot Token",
        "totp_secret": "секрет 2FA",
        "backup_password": "пароль резервных копий",
    }
    parts = []
    for key, count in (encrypted or {}).items():
        label = labels.get(key, key)
        parts.append(f"{label}: {count}" if count > 1 else label)
    return ", ".join(parts)


def _encrypt_all_secrets_flow() -> None:
    """Зашифровать все незашифрованные секреты (единый сканер ядра).

    Пункт появляется в меню только при наличии находок. Действие
    усиливающее: значения не показываются, после успеха контрольный скан
    обязан показать 0 находок (инвариант ядра).
    """
    print()
    print("Незашифрованные секреты будут зашифрованы мастер-ключом")
    print("(пароли серверов, Telegram Bot Token, секрет 2FA, пароль")
    print("резервных копий — всё, что найдено сканером).")
    print()
    if not confirm("Зашифровать все секреты? [y/N]: "):
        print("Отменено.")
        return
    try:
        outcome = ops.encrypt_all_secrets()
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        print(f"\n✖ Не удалось зашифровать секреты:\n  {message.splitlines()[0][:200]}")
        pause()
        return
    if not outcome["plaintext"]["found"]:
        print("● Все секреты зашифрованы")
        detail = _format_secret_counts(outcome.get("encrypted"))
        if detail:
            print(f"  {detail}")
    else:
        # Инвариант ядра нарушен (например, конкурентная запись) — данные
        # не потеряны, повторный запуск добьёт остаток.
        print("● Зашифровано частично — повторите пункт позже (данные не потеряны)")
    pause()


# ==================================================================
# Мастер-ключ (enc1:) — состояние-зависимое меню
# ==================================================================

def masterkey_menu() -> None:
    """Пункт 8: отражает реальное состояние системы, а не список всех
    возможных операций. Консоль — доверенный административный канал:
    Telegram-коды/2FA/пароль Web не требуются (п. 6 ТЗ)."""
    try:
        state = ops.masterkey_state()
    except Exception as exc:
        print(f"\n✖ Не удалось определить состояние мастер-ключа: {exc}")
        pause()
        return

    kind = state["state"]
    fields = ops.masterkey_field_labels(state.get("encrypted_fields"))

    if kind == "ok":
        _masterkey_ok_menu()
    elif kind == "missing_no_data":
        _masterkey_no_data_menu()
    else:
        # missing_with_data / mismatch
        _masterkey_recovery_menu(kind, fields)


def _masterkey_ok_menu() -> None:
    _header("Мастер-ключ")
    print("Состояние:   ● OK — ключ расшифровывает все данные")
    print("─" * 36)
    print("1. Показать мастер-ключ")
    print()
    print("0. Назад")
    while True:
        choice = ask("Выберите пункт: ")
        if choice == "0":
            return
        if choice == "1":
            _masterkey_show_flow()
            return


def _masterkey_no_data_menu() -> None:
    _header("Мастер-ключ")
    print("Состояние:   ○ Мастер-ключ отсутствует")
    print("             Зашифрованных данных нет — ключ создастся")
    print("             автоматически при первом сохранении секрета.")
    print("─" * 36)
    print("1. Создать мастер-ключ")
    print()
    print("0. Назад")
    while True:
        choice = ask("Выберите пункт: ")
        if choice == "0":
            return
        if choice == "1":
            from core import secretbox
            if action("Не удалось создать ключ", secretbox._create_key_exclusive):
                print("● Мастер-ключ создан (keys/secret.key)")
            pause()
            return


def _masterkey_recovery_menu(kind: str, fields: str) -> None:
    is_mismatch = kind == "mismatch"
    _header("Мастер-ключ")
    if is_mismatch:
        print("Состояние:   ✖ Мастер-ключ не совпадает с данными")
    else:
        print("Состояние:   ✖ Мастер-ключ отсутствует")
    print()
    print("⚠️ Обнаружены зашифрованные данные, для расшифровки")
    print("  которых требуется существующий мастер-ключ:")
    print(f"  {fields or 'не указаны'}")
    print()
    print("1. Ввести существующий мастер-ключ")
    print("2. Создать новый мастер-ключ")
    print()
    print("0. Назад")
    while True:
        choice = ask("Выберите пункт: ")
        if choice == "0":
            return
        if choice == "1":
            _masterkey_restore_flow()
            return
        if choice == "2":
            _masterkey_new_flow(fields)
            return


def _print_master_key() -> None:
    """Напечатать мастер-ключ и затереть его с экрана.

    Подтверждение делает вызывающий флоу (меню «Мастер-ключ» или
    предложение перед полным удалением). Ключ в логи/исключения
    не попадает (см. правила ops.py)."""
    try:
        key = ops.masterkey_read()
    except Exception as exc:
        message = str(exc).strip().splitlines()[0][:200]
        print(f"\n✖ Не удалось прочитать мастер-ключ:\n  {message}")
        return
    print()
    print(f"Мастер-ключ: {key}")
    try:
        input("\nНажмите Enter, чтобы стереть ключ с экрана...")
    except (EOFError, KeyboardInterrupt):
        pass
    # Затираем выведенный ключ, чтобы он не остался в скроллбэке
    # терминала и истории сессии (насколько это поддерживает терминал).
    _clear_printed_secret()
    print("Экран очищен — ключ удалён из истории терминала.")


def _masterkey_show_flow() -> None:
    """Показать ключ: предупреждение → явное y/N → значение.

    Ключ печатается только здесь; в логи/исключения не попадает
    (см. правила ops.py)."""
    print()
    print("⚠️  МАСТЕР-КЛЮЧ — КРИТИЧЕСКИ СЕКРЕТНЫЕ ДАННЫЕ")
    print()
    print("Никому не сообщайте этот ключ и не передавайте третьим лицам.")
    print("Мастер-ключ используется для расшифровки защищённых данных Bot4VPS.")
    print("Храните его в безопасном месте, недоступном для других людей.")
    print("Не сохраняйте ключ в открытом виде в чатах, тикетах, репозиториях")
    print("и других незащищённых местах.")
    print("Потеря мастер-ключа может привести к невозможности восстановить")
    print("зашифрованные данные из резервной копии.")
    print()
    if not confirm("Показать мастер-ключ? [y/N]: "):
        print("Отменено.")
        return
    _print_master_key()
    pause()


def _masterkey_restore_flow() -> None:
    """Ввести существующий ключ: проверка по всем enc1: данным."""
    print()
    key = getpass.getpass("Мастер-ключ: ").strip()
    if not key:
        print("Отменено.")
        return
    try:
        result = ops.masterkey_restore(key)
    except Exception as exc:
        message = str(exc).strip().splitlines()[0][:200]
        print(f"\n✖ {message}")
        print("  Существующие данные не изменены.")
        pause()
        return
    print("● Мастер-ключ восстановлен — данные снова расшифровываются.")
    print("  Если Telegram-бот не работает, перезапустите сервис (пункт 4).")
    pause()


def _masterkey_new_flow(fields: str) -> None:
    """Создать новый ключ: разрушающее подтверждение → очистка enc1:."""
    print()
    print("⚠️  ВНИМАНИЕ!")
    print()
    print("Обнаружены зашифрованные данные, для которых отсутствует")
    print("текущий мастер-ключ.")
    print()
    print("Создание нового мастер-ключа приведёт к потере доступа")
    print("к существующим зашифрованным данным.")
    print()
    print("После создания нового ключа может потребоваться заново указать:")
    print("  • пароли доступа к серверам;")
    print("  • Telegram Bot Token;")
    print("  • настройки двухфакторной аутентификации и другие")
    print("    зашифрованные данные.")
    print()
    print("Это действие нельзя отменить без восстановления старого")
    print("мастер-ключа.")
    print()
    if not confirm("Продолжить? [y/N]: "):
        print("Отменено.")
        return
    try:
        result = ops.masterkey_create_new()
    except Exception as exc:
        message = str(exc).strip().splitlines()[0][:200]
        print(f"\n✖ Не удалось создать новый ключ:\n  {message}")
        pause()
        return
    cleared = ", ".join(result.get("cleared") or [])
    print("● Создан новый мастер-ключ.")
    if cleared:
        print(f"  Очищено (требуется ввести заново): {cleared}")
    pause()


def telegram_menu() -> None:
    # Имя бота — сетевая проба getMe; делаем один раз на вход в подменю,
    # а не при каждой перерисовке
    bot_name = "неизвестен"
    try:
        from core.config import get_saved_bot_token

        token = get_saved_bot_token()
        if token:
            fetched = ops.fetch_bot_username(token)
            if fetched:
                bot_name = fetched
    except Exception:
        pass

    while True:
        try:
            tg = ops.telegram_status()
        except Exception as exc:
            print(f"\n✖ Не удалось получить состояние Telegram: {exc}")
            pause()
            return
        user = tg["user_id"] if tg["user_id"] is not None else "не задан"
        _header("Telegram")
        print(f"Бот:          {bot_name}")
        if tg["enabled"]:
            state = "работает" if tg["running"] else f"не работает ({tg['note']})"
        else:
            state = "выключен"
        print(f"Статус:       {_bullet(tg['running'])} {state}")
        print(f"Пользователь: {user}")
        print("─" * 36)
        print("1. " + ("Выключить" if tg["enabled"] else "Включить"))
        print("2. Сменить токен")
        print("3. Сменить пользователя")
        print()
        print("0. Назад")
        choice = ask("Выберите пункт: ")
        if choice == "0":
            return
        if choice == "1":
            if tg["enabled"]:
                print("Выключаю Telegram...")
                if action("Не удалось выключить Telegram", ops.tg_disable):
                    print("● Telegram выключен")
                    pause()
            else:
                print("Включаю Telegram...")
                if action("Не удалось включить Telegram", ops.tg_enable):
                    print("● Telegram включён")
                    pause()
        elif choice == "2":
            token = getpass.getpass("Новый Telegram Bot Token: ")
            username = None

            def _set():
                nonlocal username
                username = ops.tg_set_token(token)

            if action("Не удалось сменить токен", _set):
                bot_name = username or bot_name
                print(f"● Токен изменён, бот: {bot_name}")
                pause()
        elif choice == "3":
            raw = ask("Новый Telegram User ID: ")
            if action("Не удалось сменить пользователя", ops.tg_set_user, raw):
                print("● Пользователь Telegram изменён")
                pause()


def restart_menu() -> None:
    if systemd_ops.is_active():
        print("Перезапуск Bot4VPS...")
        if action("Не удалось перезапустить Bot4VPS", ops.restart_or_start):
            print("● Bot4VPS успешно перезапущен.")
    else:
        print("Запуск Bot4VPS...")
        if action("Не удалось запустить Bot4VPS", ops.restart_or_start):
            print("● Bot4VPS успешно запущен.")
    pause()


def update_menu() -> None:
    print("Проверяю обновления...")
    try:
        result = ops.update_check()
    except Exception as exc:
        print(f"\n✖ Не удалось проверить обновления: {exc}")
        pause()
        return

    if result.get("error"):
        print(f"\n✖ Не удалось проверить обновления: {result['error']}")
        pause()
        return
    if not result.get("update_available"):
        print("Bot4VPS уже обновлён.")
        pause()
        return

    version = result.get("version")
    print(f"Текущая версия:   {ops.get_version()}")
    print(f"Доступная версия: {version}")
    if not confirm("Обновить Bot4VPS? [y/N]: "):
        return
    if action("Обновление не удалось", ops.update_install, version):
        print(f"● Bot4VPS обновлён до {version}.")
        if systemd_ops.is_active():
            print("● Сервис работает.")
        else:
            print("⚠ Сервис не поднялся — проверьте journalctl -u bot4vps")
    pause()


def journal_menu() -> None:
    """Живой журнал. Ctrl+C — назад в меню, CLI не завершается."""
    print()
    print("Bot4VPS journal (Ctrl+C — назад в меню)")
    print("─" * 36)
    proc = systemd_ops.journal_follow()
    try:
        proc.wait()
        # journalctl завершился сам (ошибка) — сообщаем и возвращаемся
        print("\n⚠ journalctl завершился. Проверьте: journalctl -u bot4vps")
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        print("\n● Возврат в меню")


def uninstall_menu() -> None:
    while True:
        _header("Удаление Bot4VPS")
        print("1. Полное удаление")
        print("2. Удалить сервис, сохранить данные")
        print()
        print("0. Назад")
        choice = ask("Выберите пункт: ")
        if choice == "0":
            return
        if choice == "1":
            if _uninstall_full_flow():
                # /opt/bot4vps удалён — продолжать работу меню невозможно
                sys.exit(0)
        elif choice == "2":
            _uninstall_service_flow()


def _uninstall_full_flow() -> bool:
    print()
    print("ВНИМАНИЕ!")
    print()
    print("Будут удалены все данные Bot4VPS,")
    print("включая конфигурацию, локальные SSH-ключи")
    print("и секретный ключ шифрования.")
    print()
    print("⚠️  Без сохранённого мастер-ключа вы не сможете расшифровать")
    print("защищённые данные и резервные копии после удаления Bot4VPS.")
    print("   Мастер-ключ можно посмотреть: Настройки → Безопасность →")
    print("   Мастер-ключ (Web) или пункт 2 этого меню CLI.")
    if not _offer_masterkey_before_full_uninstall():
        print("Отменено.")
        return False
    typed = ask("Для подтверждения введите: DELETE\n\n> ")
    if typed != "DELETE":
        print("Отменено.")
        return False
    if not action("Не удалось выполнить удаление", ops.uninstall_full):
        return False
    print()
    print("● Bot4VPS полностью удалён.")
    print("  Внешние архивы /var/backups/bot4vps не тронуты —")
    print("  удалите вручную, если они не нужны.")
    pause()
    return True


def _offer_masterkey_before_full_uninstall() -> bool:
    """Предложить показать мастер-ключ перед полным удалением.

    Возвращает False, только если пользователь прервал флоу (Ctrl+C).
    Отказ показать ключ — не отмена удаления: дальше идёт явное
    подтверждение словом DELETE."""
    try:
        state = ops.masterkey_state().get("state")
    except KeyboardInterrupt:
        raise
    except Exception:
        # Состояние ключа определить не удалось — не блокируем удаление,
        # предупреждение о последствиях уже напечатано выше.
        return True
    if state == "ok":
        print()
        if confirm("Показать мастер-ключ перед удалением? [y/N]: "):
            _print_master_key()
            print()
    elif state in ("missing_with_data", "mismatch"):
        print()
        print("✖ Мастер-ключ уже отсутствует или не совпадает с данными.")
        print("  После удаления зашифрованные данные станет невозможно")
        print("  расшифровать — сохраните их копию, если они ещё нужны.")
    return True


def _uninstall_service_flow() -> None:
    print()
    print("Будет удалён сервис и команда bot4vps.")
    print("/opt/bot4vps и все данные (config.json, servers.json,")
    print("data/, keys/, secret.key) останутся на месте.")
    print()
    if not confirm("Удалить сервис, сохранив локальные данные? [y/N]: "):
        print("Отменено.")
        return
    if action("Не удалось удалить сервис", ops.uninstall_service_only):
        print("● Сервис удалён, локальные данные сохранены в /opt/bot4vps")


# ==================================================================
# Восстановление (раздел 3)
# ==================================================================

def _fmt_ts(ts: float) -> str:
    """mtime копии → «ДД.ММ.ГГГГ ЧЧ:ММ» по локальному времени."""
    from datetime import datetime

    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")


_MODE_LABELS = {
    "ok": "● OK (авторизация включена)",
    "open_admin": "○ открытая панель (авторизация выключена)",
    "open": "○ открытая панель (без авторизации)",
    "wizard": "● мастер первичной установки",
    "expired": "✖ код установки истёк",
    "stub": "✖ заглушка (вход невозможен)",
    "missing": "○ конфига нет (создастся по умолчанию)",
    "corrupt": "✖ конфиг повреждён (аварийный режим)",
    "unknown": "? не определён",
}

_MASTERKEY_LABELS = {
    "ok": "● OK",
    "missing_no_data": "○ отсутствует (нет зашифрованных данных)",
    "missing_with_data": "✖ отсутствует, данные зашифрованы",
    "mismatch": "✖ не совпадает с данными",
}


def recovery_menu() -> None:
    """Раздел 3: восстановление самого Bot4VPS.

    CLI — доверенный root-канал для починки панели (она может быть
    закрыта: мастер/заглушка/авария). Восстановление серверов из
    архивов — обычная пользовательская операция, она остаётся в Web."""
    while True:
        _header("Восстановление")
        print("1. Диагностика")
        print("2. Восстановить config из копии")
        print("3. Восстановить Bot4VPS из архива")
        print("4. Сбросить конфигурацию")
        print("5. Код первичной установки")
        print()
        print("0. Назад")
        choice = ask("Выберите пункт: ")
        if choice == "0":
            return
        if choice == "1":
            _recovery_diagnostics_flow()
        elif choice == "2":
            _recovery_config_flow()
        elif choice == "3":
            _recovery_archive_flow()
        elif choice == "4":
            _recovery_reset_flow()
        elif choice == "5":
            _recovery_setup_code_flow()


def _recovery_diagnostics_flow() -> None:
    try:
        info = ops.recovery_status()
    except Exception as exc:
        print(f"\n✖ Не удалось собрать диагностику: {exc}")
        pause()
        return

    valid = info["config_valid"]
    _header("Диагностика")
    if valid is None:
        print("Конфиг:      ○ отсутствует (создастся по умолчанию)")
    else:
        print("Конфиг:      " + ("● валиден" if valid else "✖ повреждён"))
    copies = info["copies"]
    if copies:
        latest = copies[0]
        invalid = sum(1 for c in copies if not c["valid"])
        note = f", ✖ {invalid} не проходят проверку" if invalid else ""
        print(f"Копии:       ● {len(copies)} шт.{note}")
        print(f"             последняя: {latest['name']} ({_fmt_ts(latest['mtime'])})")
    else:
        print("Копии:       ○ нет")
    servers = info["servers"]
    print(f"Серверы:     {servers if servers is not None else '? неизвестно'}")
    mk = info["masterkey"]
    print("Мастер-ключ: " + _MASTERKEY_LABELS.get(mk, f"? {mk}"))
    admin = info["admin"]
    print("Администратор: " + (
        "? неизвестно" if admin is None
        else ("● задан" if admin else "○ не задан")
    ))
    print("Режим Web:   " + _MODE_LABELS.get(info["mode"], info["mode"]))
    state = info["setup_code"]
    if state["code"]:
        left = int(state["ttl_left"] or 0) // 60
        print(f"Код установки: ● выдан (действует ещё ~{left} мин)")
    elif state["expired"]:
        print("Код установки: ✖ выдан, истёк (10 минут)")
    else:
        print("Код установки: ○ не выдан")

    # Висящая операция self-restore: случай «Web запустил восстановление,
    # сервис не поднялся». Истина — в state.json раннера; предлагаем
    # финализировать прямо здесь.
    try:
        pending = ops.self_restore_pending()
    except Exception:
        pending = None
    if pending is not None:
        print()
        print("⚠ Обнаружена незавершённая операция восстановления Bot4VPS:")
        print(f"  {pending.get('operation_id')}  (этап: {pending.get('stage')})")
        if confirm("Закрыть её по состоянию исполнителя? [Y/n]: ", default=True):
            if action(
                "Не удалось финализировать операцию",
                ops.self_restore_finalize,
                pending["operation_id"],
            ):
                print("● Операция закрыта (итог см. в истории операций Web).")
    pause()


def _recovery_config_flow() -> None:
    try:
        copies = ops.config_backups()
    except Exception as exc:
        print(f"\n✖ Не удалось прочитать копии: {exc}")
        pause()
        return
    if not copies:
        print("\nКопий config не найдено (backup/config_latest.json,")
        print("backup/config_*.json).")
        pause()
        return

    print()
    print("Доступные копии (свежие первыми):")
    for i, item in enumerate(copies, 1):
        mark = "" if item["valid"] else "  ✖ не проходит проверку"
        print(f"  {i}. {item['name']}  {_fmt_ts(item['mtime'])}{mark}")
    raw = ask("\nНомер копии (Enter — отмена): ")
    if not raw:
        return
    try:
        index = int(raw)
    except ValueError:
        print("✖ Номер — число")
        return
    if not 1 <= index <= len(copies):
        print("✖ Нет такого номера")
        return
    chosen = copies[index - 1]
    if not chosen["valid"]:
        print("✖ Эта копия повреждена — выберите другую")
        return

    # Работающий сервис может перезаписать восстановленный конфиг своим
    # состоянием — предлагаем остановить его на время восстановления.
    stopped = False
    if systemd_ops.is_active():
        print()
        print("Рекомендуется остановить сервис на время восстановления:")
        print("работающий процесс держит конфиг в памяти и может")
        print("перезаписать его после записи.")
        if confirm("Остановить bot4vps перед восстановлением? [Y/n]: ", default=True):
            ok, err = systemd_ops.stop_service()
            if not ok:
                print(f"\n✖ Не удалось остановить сервис: {err}")
                return
            stopped = True

    print()
    print(f"Текущий config.json будет заменён копией {chosen['name']}.")
    if not confirm("Восстановить? [y/N]: "):
        print("Отменено.")
        if stopped:
            _start_service_back()
        return

    if action("Не удалось восстановить config", ops.restore_config_from, chosen["path"]):
        print(f"● config.json восстановлен из {chosen['name']}.")
        print("  Повреждённый прежний конфиг (если был) сохранён")
        print("  как backup/corrupt_config_<ts>.json.")
        if stopped:
            _start_service_back()
    elif stopped:
        _start_service_back()
    pause()


def _start_service_back() -> None:
    """Запустить сервис обратно после восстановления (останавливали)."""
    print("Запускаю bot4vps...")
    ok, err = systemd_ops.start_service()
    if ok:
        print("● Сервис запущен.")
    else:
        print(f"⚠ Сервис не запустился: {err}")
        print("  Проверьте journalctl -u bot4vps")


def _fmt_size(size) -> str:
    """Байты → «12,3 МБ» / «456 КБ» (для списка архивов)."""
    try:
        value = float(size)
    except (TypeError, ValueError):
        return "—"
    for unit, factor in (("ГБ", 1024 ** 3), ("МБ", 1024 ** 2), ("КБ", 1024)):
        if value >= factor:
            return f"{value / factor:.1f}".replace(".", ",") + f" {unit}"
    return f"{int(value)} Б"


_RESTORE_STAGE_LABELS = {
    "preflight": "проверки перед восстановлением",
    "reading_target": "чтение текущего состояния",
    "protective_backup": "защитная копия",
    "self_restore_launch": "запуск исполнителя восстановления",
    "stopping_service": "остановка сервиса",
    "extracting": "распаковка архива",
    "daemon_reload": "перезагрузка юнитов systemd",
    "installing_dependencies": "зависимости (pip)",
    "starting_service": "запуск сервиса",
    "health_check": "проверка работоспособности",
    "post_restore_verify": "проверка результата",
    "applied": "применено",
    "prepared": "подготовлено",
}


def _print_restore_stage(operation: dict) -> None:
    """Прогресс операции восстановления одной строкой (без очистки экрана)."""
    stage = operation.get("stage") or ""
    label = _RESTORE_STAGE_LABELS.get(stage, stage)
    status = operation.get("status")
    if status in ("completed", "failed", "cancelled"):
        return
    print(f"  … {label}")


def _print_operation_failure(operation: dict) -> None:
    status = operation.get("status")
    if status == "cancelled":
        print("\n✖ Операция отменена.")
        return
    error = operation.get("error") or {}
    message = error.get("message") if isinstance(error, dict) else None
    print(f"\n✖ Восстановление не завершено (статус: {status}).")
    if message:
        print(f"  {str(message).splitlines()[0][:300]}")
    restore = operation.get("restore") or {}
    protective = restore.get("protective_backup_id")
    if protective:
        print(f"  Защитная копия: {protective}")
        print("  Возвращение к ней — тот же пункт 3 с выбором этой копии.")


def _recovery_archive_flow() -> None:
    """Восстановление Bot4VPS из архива (self-backup / импорт bot4vps).

    Механизм — core/backup/self_restore, тот же, что у Web: prepare (план +
    защитная копия) → подтверждение → apply (остановка сервиса → распаковка
    → pip при изменении requirements → запуск → health-check)."""
    try:
        archives = ops.self_restore_archives()
    except Exception as exc:
        print(f"\n✖ Не удалось прочитать каталог архивов: {exc}")
        pause()
        return
    if not archives:
        print("\nАрхивы Bot4VPS не найдены.")
        print("Управляемые копии: Web → Проверка → копии Bot4VPS;")
        print("импорт архива: Web → Установить (без выбора сервера).")
        pause()
        return

    print()
    print("Архивы Bot4VPS (свежие первыми):")
    for i, item in enumerate(archives, 1):
        mark = "  🔒 зашифрован" if item["encrypted"] else ""
        print(f"  {i}. {item['filename']}  {_fmt_size(item['bytes'])}{mark}")
    raw = ask("\nНомер архива (Enter — отмена): ")
    if not raw:
        return
    try:
        index = int(raw)
    except ValueError:
        print("✖ Номер — число")
        return
    if not 1 <= index <= len(archives):
        print("✖ Нет такого номера")
        return
    chosen = archives[index - 1]

    password = None
    if chosen["encrypted"]:
        from getpass import getpass

        print()
        password = getpass("Пароль архива (ввод не отображается): ")
        if not password:
            print("Отменено.")
            return

    print("\nПодготавливаю восстановление (план, защитная копия)...")
    try:
        prepared = ops.self_restore_prepare(chosen, password)
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        print(f"\n✖ Подготовка не удалась:\n  {message.splitlines()[0][:200]}")
        pause()
        return
    prepared_id = prepared["operation_id"]
    operation = ops.wait_operation(prepared_id, timeout=600.0, on_update=_print_restore_stage)
    if operation.get("status") != "completed":
        _print_operation_failure(operation)
        pause()
        return

    restore = operation.get("restore") or {}
    plan = restore.get("plan") or {}
    for warning in operation.get("warnings") or []:
        message = warning.get("message") if isinstance(warning, dict) else str(warning)
        print(f"⚠ {message}")
    print()
    print("План восстановления (обычный режим, ничего не удаляется):")
    counts = plan.get("counts") or {}
    replaced = counts.get("replace")
    added = counts.get("add")
    print(
        "  будет перезаписано: "
        + (f"{replaced}" if replaced is not None else "?")
        + ", появится нового: "
        + (f"{added}" if added is not None else "?")
    )
    protective = restore.get("protective_backup_id")
    if protective:
        print(f"Защитная копия создана: {protective}")

    print()
    print("Сервис будет ОСТАНОВЛЕН на время применения и запущен обратно.")
    print("Мастер-ключ не входит в архив никогда: после восстановления")
    print("он потребуется заново (красный баннер в Web — это нормально).")
    if not confirm("Применить восстановление? [y/N]: "):
        print("Отменено (подготовка и защитная копия сохранены).")
        return

    try:
        applied = ops.self_restore_apply(chosen, prepared_id, password)
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        print(f"\n✖ Применение не удалось:\n  {message.splitlines()[0][:200]}")
        print("  Состояние операции — пункт «Диагностика» этого раздела.")
        pause()
        return
    operation = ops.wait_operation(applied["operation_id"], on_update=_print_restore_stage)
    if operation.get("status") == "completed":
        print("\n● Восстановление применено: файлы записаны, сервис")
        print("  перезапущен и проверен.")
    else:
        _print_operation_failure(operation)
    pause()


def _recovery_reset_flow() -> None:
    print()
    print("Будет создан новый конфиг.")
    print("Текущие настройки Bot4VPS будут потеряны.")
    print("Данные серверов и backup-файлы не удаляются.")
    print()
    typed = ask("Для подтверждения введите: DELETE\n\n> ")
    if typed != "DELETE":
        print("Отменено.")
        return
    if action("Не удалось сбросить конфигурацию", ops.reset_config):
        print("● Конфигурация сброшена к значениям по умолчанию.")
        print("  Мастер первичной установки НЕ открывается автоматически:")
        print("  код установки выдаётся отдельно (пункт 5 этого раздела).")
        print("  Пока администратор не задан, Web-панель открыта без")
        print("  авторизации (значение по умолчанию).")
        if confirm("\nВыдать код первичной установки сейчас? [Y/n]: ", default=True):
            _recovery_setup_code_flow()
            return
    pause()


def _recovery_setup_code_flow() -> None:
    """Код первичной установки: только пока администратора нет.

    Код подхватывается работающим Web через drop-in БЕЗ рестарта —
    предложений перезапустить сервис здесь быть не должно."""
    try:
        state = ops.setup_code_state()
        admin = ops.web_admin_exists()
    except Exception as exc:
        print(f"\n✖ Не удалось определить состояние: {exc}")
        pause()
        return

    if admin:
        print()
        print("✖ Администратор уже задан — код первичной установки")
        print("  не нужен (второго «первого запуска» не бывает).")
        if ops.setup_code_dropin_exists():
            print()
            print("Обнаружен неиспользованный drop-in с кодом установки.")
            if confirm("Удалить его? [y/N]: "):
                if action("Не удалось удалить drop-in", ops.setup_code_dropin_remove):
                    print("● Drop-in удалён.")
        pause()
        return

    if state["code"]:
        left = int(state["ttl_left"] or 0) // 60
        print()
        print(f"Код первичной установки (действует ещё ~{left} мин):")
        print(f"  {state['code']}")
        print("Код подхватывается работающим Web без рестарта сервиса.")
        if not confirm("\nПеревыпустить код? [y/N]: "):
            return
    elif state["expired"]:
        print()
        print("Код первичной установки выдан, но истёк (действует 10 минут).")
        if not confirm("Перевыпустить? [Y/n]: ", default=True):
            return
    else:
        print()
        print("Код первичной установки не выдан.")
        if not confirm("Выдать код? [Y/n]: ", default=True):
            return

    try:
        code = ops.setup_code_issue()
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        print(f"\n✖ Не удалось выдать код:\n  {message.splitlines()[0][:200]}")
        pause()
        return
    print("● Новый код первичной установки (действует 10 минут):")
    print(f"  {code}")
    print("Откройте Web-панель и введите код в течение 10 минут,")
    print("затем задайте свой логин и пароль администратора.")
    pause()


# ==================================================================
# Главное меню
# ==================================================================

def main_menu() -> None:
    while True:
        item5 = "5. Restart" if systemd_ops.is_active() else "5. Start"
        _box("Bot4VPS", [
            "1. Статус",
            "2. Безопасность",
            "3. Восстановление",
            "4. Telegram",
            item5,
            "6. Update",
            "7. Журнал",
            "8. Удалить сервис",
            "",
            "0. Выход",
        ])
        choice = ask("Выберите пункт: ")
        if choice == "0":
            return
        if choice == "1":
            status_menu()
        elif choice == "2":
            web_menu()
        elif choice == "3":
            recovery_menu()
        elif choice == "4":
            telegram_menu()
        elif choice == "5":
            restart_menu()
        elif choice == "6":
            update_menu()
        elif choice == "7":
            journal_menu()
        elif choice == "8":
            uninstall_menu()


def main() -> int:
    # Self-heal: команда bot4vps — часть ui/cli, при запуске меню
    # гарантируем её наличие (не-фатально: под не-root просто пропускаем).
    try:
        from .bootstrap import ensure_cli_command
        ensure_cli_command()
    except Exception:
        pass
    if os.geteuid() != 0:
        print("Требуются права root. Запустите: sudo bot4vps")
        return 1
    try:
        main_menu()
        return 0
    except (KeyboardInterrupt, EOFError):
        # Ctrl+C / Ctrl+D в главном меню — выход (как «0»)
        print()
        return 0
