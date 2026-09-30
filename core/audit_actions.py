"""Словарь кодов действий аудита — одним модулем.

Зачем отдельный словарь, а не русские заголовки из обработчиков: фильтры и
агрегаты в API/UI должны опираться на машинный код (``packages.install``), а
не на свободный текст. Заголовки локализуются (i18n в планах), история —
нет: задним числом код не восстановить, поэтому словарь фиксируется до
внедрения эмиссии, а не после.

**Два словаря, не путать:**

* ``AuditAction`` (здесь) — что именно сделал человек: «установил пакет».
* ``EventReason`` (``core/event_types.py``) — почему появилось *событие*:
  «сервер недоступен», «бэкап упал». По нему работает политика уведомлений
  (``core/notification_policy.py``), и он же уезжает в карточку уведомления.

Одна операция может дать и то, и другое (действие + событие), поэтому
запись аудита хранит ``action``, а связанное событие — свой ``reason``.

**Гранулярность.** Код отвечает на вопрос «что за операция», а не «какие
параметры»: ``packages.install``, не ``packages.install.nginx``. Параметры
идут в ``params`` (маскируются при записи). Глагол — последним сегментом,
пространство имён домена — первым.

**Подписи.** Кроме кодов модуль держит ``ACTION_TITLES`` — человеческий
заголовок на каждый код (см. ниже). Он нужен и ядру: подпись уезжает в марку
таймлайна и в поиск по истории, а не рисуется фронтендом по коду.

**Статус.** Набор ниже — карта из §8.2 плана, а не список уже внедрённого:
эмиссия подключается этапами 4a («кто нажал» и «кто снёс сервер»), 4b
(Quick Setup, сервисы, секреты и HTTPS) и 4c (терминал). Коды, которых на
момент внедрения не окажется, удаляются здесь же — мёртвых строк в аудите
не бывает по построению (нечего эмитить), а вот врать словарю нельзя.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from core.actor import ActorType


class AuditAction(str, Enum):
    """Машинный код операции для записи аудита."""

    # --- Серверы (core/storage.py, ui/web/routers/servers.py) ---
    SERVER_ADD = "server.add"
    SERVER_UPDATE = "server.update"
    SERVER_DELETE = "server.delete"
    # Сервер, перезагруженный кнопкой («Перезагрузить» в Web и в Telegram,
    # а также шаг Quick Setup). В §8.2 кода не было — как и у групп, это
    # пробел карты, а не решение: нажатие меняет состояние машины и обязано
    # быть видно в истории.
    SERVER_REBOOT = "server.reboot"
    # ``server.check`` здесь нет: единственные входы — автопроба ``/probe``
    # (её дёргает карточка каждые 4 с) и три legacy-эндпоинта ``/test*``,
    # которых текущий UI не зовёт. Проверка доступности — не действие: она
    # ничего не меняет, а поток её нажатий вытеснил бы из истории сами
    # действия. Код вернётся вместе с кнопкой «проверить» с явным кликом.

    # --- Группы (core/storage.py) ---
    # Группы живут в том же servers.json, что и серверы, и меняют их те же
    # люди: переименование группы переносит серверы, удаление убирает
    # раздел. В §8.2 их не было — это пробел карты, а не решение.
    GROUP_ADD = "group.add"
    GROUP_RENAME = "group.rename"
    GROUP_DELETE = "group.delete"
    GROUP_SSL_TOGGLE = "group.ssl_toggle"

    # --- Задачи (core/task_manager.py — единая точка) ---
    TASK_START = "task.start"
    TASK_FINISH = "task.finish"
    TASK_FAIL = "task.fail"
    TASK_CANCEL = "task.cancel"

    # --- Скрипты (core/scripts.py) ---
    # ``script.run`` из карты §8.2 в словаре нет по той же причине, что и
    # ``service.sync`` у сервисов: запуск скрипта идёт задачей
    # (``enqueue_script`` → ``task_manager``), а у задачи свои коды —
    # ``task.start``/``task.finish`` с именем скрипта в ``params.task_name`` и
    # ``kind="script"``. Отдельный код дал бы вторую строку на то же нажатие.
    # Запуск скрипта из терминала отдельным кодом тоже не помечается: это
    # часть сессии, а сессия помечена (§16.4 — команд не пишем вовсе).

    # --- SSH-доступ (core/quick_setup/ssh_access.py) ---
    SSH_ACCESS_PORT_CHANGE = "ssh_access.port_change"
    SSH_ACCESS_ROOT_LOGIN = "ssh_access.root_login"
    SSH_ACCESS_PASSWORD_AUTH = "ssh_access.password_auth"
    SSH_ACCESS_USER_SWITCH = "ssh_access.user_switch"
    SSH_ACCESS_USER_PASSWORD = "ssh_access.user_password"
    # Смена пароля самого сервера в реестре панели (не пароля пользователя
    # на сервере): §8.2 такого действия не перечислял, а оно меняет то,
    # чем панель ходит на машину, — это не деталь, а доступ.
    SSH_ACCESS_SERVER_PASSWORD = "ssh_access.server_password"

    # --- Пользователи на сервере (core/quick_setup/ssh_access.py) ---
    # Создание и удаление учётной записи, выдача и снятие sudo: §8.2 знал
    # только про переключение и пароль пользователя, а это ровно тот случай,
    # когда «кто завёл рута» важнее всего остального в истории.
    SSH_USER_CREATE = "ssh_user.create"
    SSH_USER_DELETE = "ssh_user.delete"
    SSH_USER_GRANT_SUDO = "ssh_user.grant_sudo"
    SSH_USER_REVOKE_SUDO = "ssh_user.revoke_sudo"

    # --- Ключи и host key (core/quick_setup/ssh_access.py, core/host_keys.py) ---
    SSH_KEY_ADD = "ssh_key.add"
    SSH_KEY_REMOVE = "ssh_key.remove"
    # Выбор ключа, которым панель ходит под этим пользователем: ключ на
    # сервере не меняется, меняется маршрут панели — и это видно в истории.
    SSH_KEY_SELECT = "ssh_key.select"
    HOST_KEY_ACCEPT = "host_key.accept"

    # --- Firewall (core/quick_setup/firewall/) ---
    FIREWALL_ENABLE = "firewall.enable"
    FIREWALL_DISABLE = "firewall.disable"
    FIREWALL_PORT_OPEN = "firewall.port_open"
    FIREWALL_PORT_CLOSE = "firewall.port_close"
    FIREWALL_BACKEND_SWITCH = "firewall.backend_switch"
    FIREWALL_BACKEND_INSTALL = "firewall.backend_install"
    # Удаление пакета firewall'а (для nftables — ещё и сброс выбранной
    # input chain) и выбор самой chain: §8.2 перечислял только установку и
    # переключение, а удаление backend'а оставляет сервер без фильтра.
    FIREWALL_BACKEND_REMOVE = "firewall.backend_remove"
    FIREWALL_CHAIN_SELECT = "firewall.chain_select"

    # --- Пакеты, fail2ban и система (core/quick_setup/) ---
    PACKAGES_INSTALL = "packages.install"
    # Обновление всех пакетов машины: долгое, ломающее (может перезапустить
    # sshd и ядро), и в §8.2 его не было вовсе.
    SYSTEM_UPGRADE = "system.upgrade"
    FAIL2BAN_INSTALL = "fail2ban.install"
    FAIL2BAN_UNINSTALL = "fail2ban.uninstall"
    FAIL2BAN_SETTINGS = "fail2ban.settings"
    FAIL2BAN_JAIL_TOGGLE = "fail2ban.jail_toggle"
    FAIL2BAN_WHITELIST_ADD = "fail2ban.whitelist_add"
    FAIL2BAN_WHITELIST_REMOVE = "fail2ban.whitelist_remove"
    # Разбан адреса вручную — действие против политики автобана, и оно
    # обязано быть видно рядом с тем, кого бан задел.
    FAIL2BAN_UNBAN = "fail2ban.unban"
    # Правка файлов конфигурации fail2ban на сервере: содержимое не пишем
    # (§13 — фильтры и jail'ы легко содержат чужие адреса и токены уведомлений),
    # пишем, какой файл и сколько в нём байт.
    FAIL2BAN_CONFIG_WRITE = "fail2ban.config_write"
    FAIL2BAN_CONFIG_DELETE = "fail2ban.config_delete"

    # --- Сервисы (services/wireguard, docker, 3x-ui) ---
    SERVICE_INSTALL = "service.install"
    SERVICE_REMOVE = "service.remove"
    SERVICE_UPDATE = "service.update"
    # ``service.sync`` из карты §8.2 сюда не попал: синхронизация — проба
    # (читает состояние сервера и обновляет кэш панели), а не изменение
    # машины. Ровно по этой причине в 4a не появилось ``server.check``:
    # поток проб вытесняет из истории сами действия. Нажатие не теряется —
    # синхронизация идёт задачей, а у задачи есть актор, имя и время.
    # Управление демоном сервиса. Один семейный код на все сервисы:
    # какой именно — в ``params.service`` (как у ``settings.update``).
    SERVICE_START = "service.start"
    SERVICE_STOP = "service.stop"
    SERVICE_RESTART = "service.restart"
    SERVICE_CONFIG_UPDATE = "service.config_update"
    SERVICE_FILE_WRITE = "service.file_write"
    SERVICE_FILE_DELETE = "service.file_delete"

    # --- Резервные копии (core/backup/) ---
    BACKUP_CREATE = "backup.create"
    BACKUP_RESTORE = "backup.restore"
    BACKUP_DELETE = "backup.delete"
    BACKUP_RETENTION = "backup.retention"
    # Импорт (§8.2 его не перечислял, но операция существует и опасна не
    # меньше восстановления) и проверка архива — обе проходят через тот же
    # журнал операций, что создание и удаление.
    BACKUP_IMPORT = "backup.import"
    BACKUP_VERIFY = "backup.verify"

    # --- Обновление панели (core/update/) ---
    UPDATE_INSTALL = "update.install"
    UPDATE_ROLLBACK = "update.rollback"

    # --- Настройки и вход (ui/web/routers/settings.py, system.py) ---
    SETTINGS_UPDATE = "settings.update"
    WEB_PASSWORD_CHANGE = "web.password_change"
    WEB_AUTH_ENABLE = "web.auth_enable"
    WEB_AUTH_DISABLE = "web.auth_disable"
    WEB_LOGIN = "web.login"
    WEB_OPEN = "web.open"
    WEB_2FA_ENABLE = "web.2fa_enable"
    WEB_2FA_DISABLE = "web.2fa_disable"

    # --- Секреты (ui/web/routers/masterkey.py, core/secretbox.py) ---
    SECRET_MASTERKEY_CREATE = "secret.masterkey_create"
    SECRET_MASTERKEY_UNLOCK = "secret.masterkey_unlock"
    # ``secret.masterkey_rotate`` из карты §8.2 в словаре нет намеренно:
    # операции «перевыпустить ключ, перешифровав существующие данные» в коде
    # не существует — замена ключа не перешифровывает ничего, старые enc1:
    # значения становятся нечитаемыми. Это создание нового ключа, и оно
    # пишется кодом выше с ``via=replacement``. Мёртвый код в словаре
    # означал бы фильтр, который никогда не срабатывает.
    SECRET_ENCRYPT_ALL = "secret.encrypt_all"

    # --- TLS (ui/web/routers/tls.py) ---
    TLS_ENABLE = "tls.enable"
    TLS_RENEW = "tls.renew"
    TLS_DISABLE = "tls.disable"
    # Загрузка пары cert+key с компьютера в keys/web/: HTTPS ещё не включён,
    # но рабочая пара панели уже подменена. §8.2 знал только про
    # включение/перевыпуск/выключение, а это отдельный шаг перед «Применить».
    TLS_CERT_UPLOAD = "tls.cert_upload"

    # --- Терминал (ui/web/routers/terminal.py) ---
    # Только факт сессии, без команд (§16.4). Пара: ``terminal.open`` со
    # ``started`` на подключении → ``terminal.close`` с ``ok`` и длительностью
    # на закрытии, связаны ``op_id`` (§16.3) — длительность таймлайна берётся
    # из пары (§8.4). Неудачное подключение (SSH не пустил) — одиночный
    # ``terminal.open`` с ``failed`` и причиной в ``error``: сессии не было,
    # и пары у записи нет.
    TERMINAL_OPEN = "terminal.open"
    TERMINAL_CLOSE = "terminal.close"


class AuditResult(str, Enum):
    """Чем закончилась операция. Причина отказа — в поле ``error``.

    ``STARTED`` — начало длинной операции (§16.3): пара ``started`` →
    ``ok``/``failed``, связанная ``op_id``, даёт таймлайну длительность.
    Для мгновенных действий (переключатель настройки, удаление сервера)
    пишется только финал — «начал» у них неотличимо от «сделал».
    """

    STARTED = "started"
    AWAITING_RULE_SELECTION = "awaiting_rule_selection"
    OK = "ok"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ------------------------------------------------------------------
# Человеческие подписи кодов
# ------------------------------------------------------------------

# Подпись — не украшение, а часть контракта: она уезжает в марку таймлайна
# (§10.3) и в поиск по истории (§10.2, ``q``). Живёт рядом со словарём, а не
# в UI: два интерфейса (Web и Telegram) обязаны называть одно действие
# одинаково, а фронтенд не имеет права знать про коды больше, чем API.
#
# Русский текст здесь — ключ, как и договорено для будущего RU/EN: при
# появлении второго языка эта таблица станет парой таблиц, а не пометкой
# «надо перевести». Таблица обязана покрывать словарь целиком (это проверяет
# тест): код без подписи — пустая строка в истории.
ACTION_TITLES: dict[str, str] = {
    AuditAction.SERVER_ADD.value: "Добавление сервера",
    AuditAction.SERVER_UPDATE.value: "Изменение сервера",
    AuditAction.SERVER_DELETE.value: "Удаление сервера",
    AuditAction.SERVER_REBOOT.value: "Перезагрузка сервера",
    AuditAction.GROUP_ADD.value: "Создание группы",
    AuditAction.GROUP_RENAME.value: "Переименование группы",
    AuditAction.GROUP_DELETE.value: "Удаление группы",
    AuditAction.GROUP_SSL_TOGGLE.value: "Проверка сертификата группы",
    AuditAction.TASK_START.value: "Задача в очереди",
    AuditAction.TASK_FINISH.value: "Задача завершена",
    AuditAction.TASK_FAIL.value: "Задача с ошибкой",
    AuditAction.TASK_CANCEL.value: "Задача отменена",
    AuditAction.SSH_ACCESS_PORT_CHANGE.value: "Смена SSH-порта",
    AuditAction.SSH_ACCESS_ROOT_LOGIN.value: "Вход root по SSH",
    AuditAction.SSH_ACCESS_PASSWORD_AUTH.value: "Вход по паролю",
    AuditAction.SSH_ACCESS_USER_SWITCH.value: "Смена пользователя панели",
    AuditAction.SSH_ACCESS_USER_PASSWORD.value: "Пароль пользователя на сервере",
    AuditAction.SSH_ACCESS_SERVER_PASSWORD.value: "Пароль сервера в панели",
    AuditAction.SSH_USER_CREATE.value: "Создание пользователя",
    AuditAction.SSH_USER_DELETE.value: "Удаление пользователя",
    AuditAction.SSH_USER_GRANT_SUDO.value: "Выдача sudo",
    AuditAction.SSH_USER_REVOKE_SUDO.value: "Снятие sudo",
    AuditAction.SSH_KEY_ADD.value: "Добавление SSH-ключа",
    AuditAction.SSH_KEY_REMOVE.value: "Удаление SSH-ключа",
    AuditAction.SSH_KEY_SELECT.value: "Выбор ключа панели",
    AuditAction.HOST_KEY_ACCEPT.value: "Принятие host key",
    AuditAction.FIREWALL_ENABLE.value: "Включение firewall",
    AuditAction.FIREWALL_DISABLE.value: "Выключение firewall",
    AuditAction.FIREWALL_PORT_OPEN.value: "Открытие порта",
    AuditAction.FIREWALL_PORT_CLOSE.value: "Закрытие порта",
    AuditAction.FIREWALL_BACKEND_SWITCH.value: "Смена firewall",
    AuditAction.FIREWALL_BACKEND_INSTALL.value: "Установка firewall",
    AuditAction.FIREWALL_BACKEND_REMOVE.value: "Удаление firewall",
    AuditAction.FIREWALL_CHAIN_SELECT.value: "Выбор input chain",
    AuditAction.PACKAGES_INSTALL.value: "Установка пакетов",
    AuditAction.SYSTEM_UPGRADE.value: "Обновление пакетов системы",
    AuditAction.FAIL2BAN_INSTALL.value: "Установка fail2ban",
    AuditAction.FAIL2BAN_UNINSTALL.value: "Удаление fail2ban",
    AuditAction.FAIL2BAN_SETTINGS.value: "Настройки fail2ban",
    AuditAction.FAIL2BAN_JAIL_TOGGLE.value: "Переключение jail",
    AuditAction.FAIL2BAN_WHITELIST_ADD.value: "Добавление в белый список",
    AuditAction.FAIL2BAN_WHITELIST_REMOVE.value: "Удаление из белого списка",
    AuditAction.FAIL2BAN_UNBAN.value: "Разбан адреса",
    AuditAction.FAIL2BAN_CONFIG_WRITE.value: "Запись конфигурации fail2ban",
    AuditAction.FAIL2BAN_CONFIG_DELETE.value: "Удаление конфигурации fail2ban",
    AuditAction.SERVICE_INSTALL.value: "Установка сервиса",
    AuditAction.SERVICE_REMOVE.value: "Удаление сервиса",
    AuditAction.SERVICE_UPDATE.value: "Обновление сервиса",
    AuditAction.SERVICE_START.value: "Запуск сервиса",
    AuditAction.SERVICE_STOP.value: "Остановка сервиса",
    AuditAction.SERVICE_RESTART.value: "Перезапуск сервиса",
    AuditAction.SERVICE_CONFIG_UPDATE.value: "Изменение конфигурации сервиса",
    AuditAction.SERVICE_FILE_WRITE.value: "Запись файла сервиса",
    AuditAction.SERVICE_FILE_DELETE.value: "Удаление файла сервиса",
    AuditAction.BACKUP_CREATE.value: "Создание резервной копии",
    AuditAction.BACKUP_RESTORE.value: "Восстановление из копии",
    AuditAction.BACKUP_DELETE.value: "Удаление копии",
    AuditAction.BACKUP_RETENTION.value: "Чистка старых копий",
    AuditAction.BACKUP_IMPORT.value: "Импорт копии",
    AuditAction.BACKUP_VERIFY.value: "Проверка копии",
    AuditAction.UPDATE_INSTALL.value: "Обновление панели",
    AuditAction.UPDATE_ROLLBACK.value: "Откат обновления",
    AuditAction.SETTINGS_UPDATE.value: "Изменение настроек",
    AuditAction.WEB_PASSWORD_CHANGE.value: "Смена пароля панели",
    AuditAction.WEB_AUTH_ENABLE.value: "Включение защиты панели",
    AuditAction.WEB_AUTH_DISABLE.value: "Отключение защиты панели",
    AuditAction.WEB_LOGIN.value: "Вход в панель",
    AuditAction.WEB_OPEN.value: "Открытие панели",
    AuditAction.WEB_2FA_ENABLE.value: "Включение 2FA",
    AuditAction.WEB_2FA_DISABLE.value: "Выключение 2FA",
    AuditAction.SECRET_MASTERKEY_CREATE.value: "Создание мастер-ключа",
    AuditAction.SECRET_MASTERKEY_UNLOCK.value: "Восстановление мастер-ключа",
    AuditAction.SECRET_ENCRYPT_ALL.value: "Шифрование всех секретов",
    AuditAction.TLS_ENABLE.value: "Включение HTTPS",
    AuditAction.TLS_RENEW.value: "Перевыпуск сертификата",
    AuditAction.TLS_DISABLE.value: "Выключение HTTPS",
    AuditAction.TLS_CERT_UPLOAD.value: "Загрузка сертификата",
    AuditAction.TERMINAL_OPEN.value: "Открытие терминала",
    AuditAction.TERMINAL_CLOSE.value: "Закрытие терминала",
}


def title_of(code: Any) -> str:
    """Подпись действия по коду.

    Незнакомый код возвращается как есть, а не пустой строкой: БД переживает
    код (аудит append-only, схема миграции только вперёд), и запись, чей код
    из словаря убрали, обязана остаться читаемой — иначе история «потеряет»
    строку молча, а это хуже некрасивого заголовка. ``None`` — не код:
    подписи у него нет, и пустая строка здесь честная.
    """
    if code is None:
        return ""
    return ACTION_TITLES.get(str(code), str(code))


def codes_matching_title(query: str) -> list[str]:
    """Коды, в подписи которых встречается ``query`` (регистр не важен).

    Нужно поиску по истории (§10.2): заголовка в таблице нет — он выводится
    из кода, и «найти всё про firewall» обязано находить ``firewall.*``
    независимо от языка подписи.
    """
    needle = str(query or "").strip().lower()
    if not needle:
        return []
    return [code for code, title in ACTION_TITLES.items() if needle in title.lower()]


# Подписи результатов и типов акторов — того же рода, что ``ACTION_TITLES``:
# русский текст для фильтров, сводок и легенды обязан приходить из одного
# места, иначе Web скажет «успешно», а Telegram — «ок» про одну и ту же
# запись. Полнота проверяется тестом: у каждого результата и каждого типа
# актора есть подпись.
RESULT_TITLES: dict[str, str] = {
    AuditResult.STARTED.value: "Начато",
    AuditResult.AWAITING_RULE_SELECTION.value: "Ожидается выбор правил",
    AuditResult.OK.value: "Успешно",
    AuditResult.FAILED.value: "Ошибка",
    AuditResult.CANCELLED.value: "Отменено",
}

ACTOR_TYPE_TITLES: dict[str, str] = {
    ActorType.WEB.value: "Веб-панель",
    ActorType.TG.value: "Telegram",
    ActorType.CLI.value: "CLI",
    ActorType.SYSTEM.value: "Панель",
}


def actor_label(actor_type: Any, actor_id: Any) -> str:
    """Человеческая подпись актора: «admin · Веб-панель» / «Панель».

    Логин у ``system`` пуст по построению (§6.1), поэтому подпись берётся из
    типа; склеивать «None · Панель» нельзя — это выглядело бы как потерянный
    логин, а не как честное «действовала панель».
    """
    kind = ACTOR_TYPE_TITLES.get(str(actor_type), str(actor_type or ""))
    return f"{actor_id} · {kind}" if actor_id else kind

