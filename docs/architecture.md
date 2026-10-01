# Архитектура Bot4VPS (для разработчика)

Документ описывает, **как устроен Bot4VPS изнутри и почему он работает именно так**.
Это не пользовательская документация (та — в [README](../README.md)) и не инструкции
«нажми сюда». Это карта кода для того, кто собирается менять ядро: где какой модуль
живёт, кто кем владеет, какие потоки данных существуют и какие решения приняты осознанно.

Документ написан по фактическому коду. Привязка: **версия 6.3.0** (`core/version.py`),
срез 2026-10-02. При заметных изменениях ядра обновляйте соответствующие разделы —
сильнее всего устаревают числа (интервалы, лимиты) и состав таблиц БД.

---

## 1. Карта системы

```text
Пользователь
│
├── Web UI (ui/web)          FastAPI + SPA без сборщика, REST /api/* + SSE;
│                            отдельный защищённый справочник GET /faq
├── Telegram (ui/telegram)   python-telegram-bot, кнопки + текст
└── CLI (ui/cli)             локальное меню, /usr/local/bin/bot4vps
        │
        ▼
┌───────────────────────────── core/ ──────────────────────────────┐
│  servers / ssh          модель сервера, paramiko, TOFU host keys │
│  task_manager           per-server очередь операций              │
│  jobs_runtime           ядерная JobQueue фоновых задач           │
│  monitor                доступность, SSL, целостность ключей     │
│  metrics                периодические ряды метрик                │
│  operation_metrics      пики нагрузки вокруг операций            │
│  audit (+ audit_*)      append-only журнал и проекция операций   │
│  event_service (+…)     события → журнал → уведомления           │
│  timeline               склейка метрик + меток для UI            │
│  backup/                создание/шифрование/restore/self-restore │
│  quick_setup/           SSH, firewall (ufw/firewalld/nftables),  │
│                         fail2ban, пакеты, система                │
│  update/                self-update с откатом                    │
│  secretbox/storage      enc1:-шифрование секретов, мастер-ключ   │
│  integrator             ядро сервисов (без знания о конкретных)  │
└──────────────────────────────────────────────────────────────────┘
        │                          │                       │
        ▼                          ▼                       ▼
  State DB (data/state.db)   JSON-хранилища           services/
  sqlite, WAL, схема v7      servers.json,            docker / wireguard / 3x-ui
  метрики, аудит,            monitor.json,            манифест service.json + impl/
  availability               logs/events/, logs/tasks/,
                             notification_queue.json
```

Три интерфейса — тонкие слои над одним `core/`. Ядро не знает ни про Telegram,
ни про Web: доставка уведомлений отвязана через реестр нотификаторов
(`core/event_service.py::register_notifier`), регистрируемый при старте бота.

---

## 2. Три входа, один lifecycle

| Вход | Что это | Кто поднимает |
|---|---|---|
| **uvicorn (основной)** | `ui.web.app:app`, FastAPI (`ui/web/app.py`): SPA на `/`, REST `/api/*`, SSE и отдельный защищённый справочник `GET /faq` (`ui/web/faq.html`, без загрузки SPA). Порт 8080 из systemd-юнита | `bot4vps.service`: `ExecStart=.../venv/bin/python -m uvicorn ui.web.app:app --host 0.0.0.0 --port 8080`. **Telegram-бот запускается внутри веб-процесса** (`bot.start_telegram()` в lifespan) |
| **bot.py (Telegram-only)** | чистый PTB `run_polling()`, для инсталляций без Web | свой юнит с `ExecStart=... python bot.py` (вариант в `install.sh`) |
| **CLI** | `python -m ui.cli` → меню | команда `/usr/local/bin/bot4vps`; самопроверяется при старте любого из входов (`ui/cli/bootstrap.py::ensure_cli_command`) |

Ключевой факт: **оба полноформатных входа проходят один и тот же startup-lifecycle** —
`ui/web/app.py::lifespan` (uvicorn) и `bot.py::_post_init` (чистый ТГ) поднимают:

1. `reconcile_self_restores` — разбор незавершённых self-restore;
2. `core.jobs_runtime.start_core_jobs()` — фоновые задачи ядра;
3. Telegram-бота (если включён) и дрейн уведомлений;
4. планировщик бэкапов, индексатор инвентарей, реестр ключей;
5. `masterkey-watchdog` — если бот/бэкапы не поднялись из-за отсутствия
   мастер-ключа, он поднимет их после ввода ключа **без рестарта сервиса**.

Правило «ядро владеет фоном» зафиксировано в `core/jobs_runtime.py`: фоновые задачи
не принадлежат Telegram (PTB JobQueue не работает standalone), поэтому в ядре есть
собственная лёгкая asyncio-обёртка `CoreJobQueue`. Выключение Telegram не останавливает
мониторинг.

Важно не путать: `CoreJobQueue` — **не** очередь пользовательских операций.
Пользовательские операции — `core/task_manager.py` (раздел 4).

---

## 3. Слои и направление зависимостей

```text
ui/web, ui/telegram, ui/cli   →   core   ←   services/* (docker, wireguard, 3x-ui)
```

- `core` **никогда не импортирует** `ui.*` и `services.*`. Обратная связь —
  реестры и колбэки (нотификаторы событий, `set_delivery_bot`).
- `services/<id>/` — самоописываемые модули: манифест `service.json` + класс сервиса,
  наследующий `core.integrator.Service`. Ядро находит их сканом каталога и импортирует
  лениво, при первом действии. Зависимости строго однонаправленные.
- Рудимент, о котором надо знать: корневой `state.py` — глобальные dict'ы FSM
  Telegram-визардов (`ADD_SERVER_STATE` и т.п.). Новые многошаговые TG-флоу
  традиционно заводят запись там.

---

## 4. Поток операции (главный поток продукта)

Пример: пользователь в Web жмёт «запустить скрипт».

```text
Пользователь
   │  кнопка в Web / Telegram
   ▼
Web: POST /api/tasks/enqueue (ui/web/routers/tasks.py)   │  TG: task_ui / handlers
   └───────────────────┬──────────────────────────────────┘
                       ▼
     core/task_manager.py :: enqueue()
     Task(id=uuid[:12], actor=снимок текущего Actor)
     пер-server очередь: одна running-задача на сервер
                       │  _pump() → runner()
                       ▼
     executor (реестр _EXECUTORS, регистрация сайд-эффектом импорта):
       "script"   core/scripts.py     — SFTP upload + bash по SSH
       "svc"      core/integrator.py  — действия сервисов (StepRunner)
       "svc_scan" core/integrator.py  — проверка сервисов по всем серверам
                       │  синхронный SSH в asyncio.to_thread,
                       │  asyncio.shield(work) — отмена не теряет результат
                       ▼
     core/ssh.py :: create_ssh_client (paramiko)
     ├── host key gate: TOFU / HostKeyMismatchError ДО аутентификации
     └── неудача → note_ssh_failure → backoff 60 c авто-проб (fail2ban)
                       │
                       ▼  параллельно с выполнением и в finally:
     ├── core/audit.py ───────► state_db.audit_records (+производные таблицы),
     │                          op_id = "task-<id>", актор — из снимка задачи
     ├── operation_metrics ───► сэмплы source="operation" + монотонный пик
     ├── events/task_history ► logs/events/<id>.json, logs/tasks/<id>.json
     └── live-вывод ──────────► подписчикам (TG live, Web-стрим)
```

Детали, которые чаще всего surprise'ят при чтении кода:

- **Актор — снимок, а не contextvar, в момент записи аудита.** Раннер живёт в
  отдельной asyncio-задаче, contextvar нажавшего туда не доходит. `Task.actor`
  фиксируется один раз в `enqueue()` — иначе в аудите оказался бы `system`.
- **`op_id = f"task-{task.id}"` — производный ключ**, а не отдельный генератор:
  пара аудита «started → финал» сходится даже после рестарта панели, а аудит-строки
  сервисного слоя приклеиваются к той же операции.
- **Вставка аудита — не просто INSERT.** `state_db.insert_audit` в той же транзакции
  перестраивает производные таблицы операций (`audit_operations.incorporate`) —
  таймлайн и аудит-страницы читают именно эту проекцию, не raw-журнал.
- **Отмена — мост asyncio → потоки.** `core/cancel_flags.py`: contextvar c
  `threading.Event`; watcher переносит отмену каждые 0.2 с, синхронный цикл чтения
  SSH-вывода проверяет флаг построчно.
- **Регистрация executor'ов — сайд-эффект импорта модуля** (`core/scripts.py`
  регистрирует `"script"` на уровне модуля). Поэтому в коде встречаются
  `import core.scripts  # noqa: F401` — это не забытый импорт.
- **История задач — файлы, не БД**: `logs/tasks/<task_id>.json` через
  `TaskHistoryStore`/`JsonItemStore` (лимит из config, default 100). TaskManager
  перечитывает её при каждом запросе истории — так три процесса-писателя (uvicorn,
  чистый ТГ, CLI) видят согласованное состояние.
- Прямые операции без очереди тоже существуют: `integrator.call()` (диагностика)
  и reboot — они сами строят пару аудита и включают собственные метрики.

---

## 5. Фоновый контур

Все периодические задачи регистрируются в `core/jobs_runtime.start_core_jobs()`:

| Job | Интервал | Что делает | Куда пишет |
|---|---|---|---|
| `system_sync` | 15 мин (константа) | SSH-сбор `check_server_availability` → метрики + резолв доменов | `metric_samples`, `monitor.json` |
| `online_monitor` | `config.monitor.online.interval` мин (default 5) | лёгкие пробы ICMP → TCP(ssh-порт) → 80 → 443 параллельно | `monitor.json`, `availability_transitions`, события |
| `ssl_monitor` | сутки (default) | TLS-проверка сертификата | `monitor.json`, события |
| `keys_integrity` | 15 мин | локальная проверка существования key-файлов | CRITICAL-события |
| `update_check` | сутки, гейт `update_check.enabled` (default off) | проверка новой версии | `data/update/state.json` |
| `services_sync` | 15 мин, concurrency 5 | обновление кэшей сервисов по всем серверам | `data/services/<svc>/<server>.json` |
| `tls_renew` | 24 ч | продление LE-сертификата панели | `keys/web/` |
| `metrics_fold` | час | свёртка сырых метрик в часовые | `metric_hourly` |
| `state_retention` | сутки | строго **fold → prune** (иначе после простоя >90 дней потеряли бы несвёрнутые точки) | чистка sqlite |
| `notification_drain` | 5 c | дрейн очереди уведомлений в Telegram | `notification_queue.json` |

Принципы, важные для понимания:

- **Метрики «едут» на пробах доступности.** `core/metrics.py` сам никогда не ходит
  по SSH; единственный регулярный писатель ряда — job `system_sync` (SSH-раунд один).
  Живые пробы карточек сервера (раз в ~5 с) в ряд **не** пишутся — иначе сместили бы
  шкалу. `core/operation_metrics.py` — отдельная история: пиковая нагрузка вокруг
  операции, снимается попутно через SSH-клиент самой операции (троттлинг 60 с),
  фонового сборщика нет.
- **online/offline — чисто сетевой критерий** (ICMP или любой из портов);
  SSH-ошибка аутентификации статус не флипает, хранится отдельно в `ssh_error`.
  Переход пишет тройку: строку в `availability_transitions`, якорную метрику
  (полную при online, синтетический ноль при offline) и событие.
- **SSE-петля — часть контура.** Пока открыт хоть один `/api/stream`, web гоняет
  лёгкие проверки stale-серверов (TTL 4 c) и регистрирует «панель открыта»
  (`web_presence`, TTL 12 c) — а то в свою очередь откладывает Telegram-уведомления.
  То есть открытая панель меняет поведение фоновых проверок и доставки.
- **DNS-резолв идёт собственным клиентом** (`core/dns_resolve.py`, цепочка
  9.9.9.9 → 77.88.8.8) — чтобы не получать некорректный IP при проверке,
  если на шлюзе используется FakeIP;
  резолвится только отображаемый IP, пробы идут по домену через системный резолвер.
- **60-секундный SSH-backoff** (`core/monitor.py::_SSH_BACKOFF_INTERVAL`): после
  неудачного подключения авто-пробы молчат минуту, иначе при неверном пароле панель
  забанила бы сама себя fail2ban'ом (~20 неудачных аутентификаций в минуту).
  Явные действия пользователя backoff'ом не ограничиваются. Крючок встроен в
  единственную точку подключения: `core/ssh.py` сообщает слою мониторинга об
  успехе/неудаче — редкий случай обратной зависимости ssh → monitor.

---

## 6. Хранилища: что где лежит

| Хранилище | Формат | Содержимое / ретенция |
|---|---|---|
| `data/state.db` | sqlite, WAL, `SCHEMA_VERSION = 7`, миграции только вперёд/аддитивные | `metric_samples` (90 дней), `metric_disks`, `metric_hourly` (24 мес), `operation_metric_peaks(+_disks)`, `audit_records` (append-only, бессрочно), `audit_operations/members/keys` (проекция), `availability_transitions`. Писателей **три процесса** — WAL + busy_timeout 5000 |
| `servers.json` | JSON-документ под flock (`core/storage.py`), 0600 | записи серверов: подключение, `password` в `enc1:`, `host_key` (TOFU), SSL-настройки, профиль бэкапа. Ротации `backup/servers_*.json` |
| `monitor.json` | JSON под threading-локом | последний статус сервера: availability, certificate, system |
| `logs/events/<id>.json` | JsonItemStore (файл на запись) | журнал событий, лимит default 200 |
| `logs/tasks/<id>.json` | JsonItemStore | терминальная история задач, лимит default 100 |
| `logs/notification_queue.json` | JsonDocumentStore | pendings доставки, lease TTL 5 мин; `notification_state.json` — last_reported по серверам, live-сообщения |
| `config.json` | атомарный патч-запись | настройки; секреты (`bot_token`, `totp_secret`, пароль бэкапов) в `enc1:` |
| `data/services/<svc>/<server>.json` | кэш сервисов | результат `services_sync`; читают UI, пишут integrator |
| `data/update/state.json`, `data/web_tls.json`, `data/web_port.json` | state-файлы раннеров | статус долгих переходных операций (см. раздел 12) |
| `/var/backups/bot4vps` | архивы | бэкапы (manifest v2, B4VE-шифрование); не может лежать внутри каталога установки |

Общая механика JSON-сторов — `core/json_store.py`: sidecar flock + атомарная запись
(tmp + `os.replace` + fsync файла и каталога), повреждённый файл уходит в карантин
`<name>.corrupt-<ts>.json`. Повреждение state.db аналогично карантинится с созданием
пустой БД и CRITICAL-событием — мониторинг от БД не зависит.

---

## 7. Секреты: enc1: и мастер-ключ

- Единственный механизм — `core/secretbox.py`: формат `enc1:<fernet-token>`
  (Fernet, AES-128-CBC + HMAC), ключ `keys/secret.key` (0600, создание
  эксклюзивно через O_CREAT|O_EXCL).
- Шифруются только пароли/токены (реестр полей фиксирован): `servers[].password`,
  `bot_token`, `totp_secret`, пароль бэкапов. Хосты, порты и пути — plaintext by design.
- **Гейт мастер-ключа** (`_load_fernet`): если ключа нет, а на диске есть хотя бы
  одно `enc1:` (сканируются и ротации `backup/servers_*.json`) — `MasterKeyMissingError`,
  авто-создание ключа запрещено. Иначе первый же decrypt молча осиротил бы все шифротексты.
- `master_key_state()` → ok / missing_no_data / missing_with_data; при missing_with_data
  панель живёт (мониторинг, Web), но поднимает баннер и не пускает бэкапы/бота до ввода
  ключа — их поднимает watchdog после восстановления.
- **Мастер-ключ никогда не входит в self-backup** (`bot4vps_sources.py`): ключ в архиве
  размыкал бы все `enc1:`-секреты этого же архива, включая пароль бэкапов. После
  restore панель сознательно ждёт ручной ввод ключа.

---

## 8. Backup / Restore

```text
создание (расписание 02:30 / ручное / защитное перед restore / pre_update)
   → admission: место на диске, лимит архива, источники (корень минус /proc /sys /dev /run)
   → пароль: явный → сохранённый (enc1: из config) → None
       автоматика без пароля → plain-архив + warning (отсутствующий бэкап хуже)
   → snapshot state.db консистентным VACUUM INTO (метрики в архив НЕ входят)
   → tar.gz → B4VE: AES-256-GCM, ключ scrypt (N=2^14), чанки 4 МиБ,
     AAD = заголовок + номер чанка + last-флаг (защита от склейки/обрезки)
   → /var/backups/bot4vps + manifest v2 + инвентаризация (фоновый индексатор)

restore
   → ранний verify_password: расшифровка только первого куска,
     ДО регистрации Operation → неверный пароль не оставляет следов в истории
   → идемпотентность по request_id, consent-проверка
   → защитная копия затрагиваемых путей (purpose=protective)
   → apply=False: стадия prepared, мутаций нет
   → apply=True: preflight → mutation boundary (отмена запрещена) →
     tar apply (удалённо по SSH или локально) → verify

self-restore (восстановление самой панели)
   → раннер вне процесса: systemd-run --scope (иначе KillMode=mixed убьёт его
     при stop сервиса) + go-файл как атомарная граница мутации
   → runner на чистом stdlib: stop → уборка -wal/-shm спутников БД →
     extract → pip install (если requirements изменился) → start → health
   → на старте панели reconcile_self_restores усыновляет/финализирует брошенное
```

- Координация — `core/backup/locks.py`: обязательные flock в `/run/lock/bot4vps`
  (targets/artifacts/retention/operations/imports), ни одно действие без Permit.
- Имена БД и её спутников backup-слой берёт у владельца схемы (`core/state_db`),
  не дублирует строки.
- Telegram — read-only клиент бэкапов: зашифрованные архивы и merge/full-restore
  в TG недоступны by design (пароль в чат не вводим); проба Web делается локальным
  HTTP-запросом к порту из systemd-юнита.
- Планировщик (`AutomaticBackupScheduler`): poll 30 c, claim-записи гарантируют
  ровно один запуск на суточный occurrence, воркеры сериализованы.
- Глубокое погружение в backup — модель безопасности, границы доверия, полный
  pipeline restore: [backup-core.md](backup-core.md).

---

## 9. Quick Setup

`core/quick_setup/` настраивает **уже подключённые по SSH серверы** (создание VPS
у провайдера в продукте нет).

- `manager.get_overview()` собирает страницу параллельно (пул на 5) — wall-clock
  равен самому медленному разделу, а не сумме.
- `ssh_access.py` — самый большой модуль: смена SSH-порта с верификацией и
  авто-откатом (включая socket-activated sshd), пользователи/sudo/switch_user,
  ключи и их реестр (`keys/registry.json`), тумблеры sshd.
- `firewall/` — контракт `FirewallBackend` и три бэкенда: **ufw / firewalld /
  nftables**. Переключение бэкенда (`switch_backend`) — не «снести и создать»,
  а exact reconciliation: логический скан правил всех сторон → деактивация
  источника → активация цели с гарантированным bypass для SSH-порта → сверка.
  Неоднозначные правила разрешаются пользователем через continuation-токены
  (HMAC, TTL 15 мин). `source_keeps_access` — защита от само-лока.
- `fail2ban.py`, `packages.py` (каталог пакетов + детект apt/dnf/…+алиасы),
  `system.py` (upgrade/reboot с ожиданием готовности).
- Аудит QS-действий — декоратор `@audited` с единой таблицей «операция → код аудита».
- Смена SSH-порта/пользователя идёт через compare-and-set в `storage.py` — защита
  от гонки «настройки изменились между проверкой и записью».

---

## 10. Сервисы (docker / wireguard / 3x-ui)

- `core/integrator.py` — обобщённое ядро: манифесты, параметры, действия, кэш.
  Ничего не знает о конкретных сервисах; `services/<id>/service.json` декларирует
  установку (apt/package/custom), иконку, поддержку обновлений.
- Все действия сервисов идут через общий `task_manager` (очередь/отмена/live-вывод);
  SSH-шаги — `StepRunner`: проверка отмены перед каждым шагом + попутный замер
  `operation_metrics.measure(ssh)`. После действия — одна аудит-строка с тем же
  `op_id`, что и задача, и обновление кэша **под** `operation_metrics.paused()`
  (SSH синхронизации не должен засчитываться как нагрузка операции).
- Свежесть кэшей обеспечивает `services_sync` (15 мин), а не кнопки UI.
- 3x-ui (`services/3x-ui/impl/`): каталог релизов MHSanaei/3x-ui с локальным кэшем
  тарболлов; **ownership-aware cert lifecycle** (`certs.py`) — зеркало SSL-меню
  x-ui: перед standalone-выпуском порт 80 берётся в аренду (открывается в firewall,
  systemd-заниматель временно останавливается, чужой процесс — честный отказ),
  после выпуска всё откатывается; параллельный движок — certbot.
- SelfSNI-заглушка (`fakesite.py`): один публичный шаблон сайта на установку;
  nginx-блок `listen 127.0.0.1:9000 ssl proxy_protocol` — наружу портов нет.

---

## 11. Updates и HTTPS панели

**Updates (`core/update/`).** main-ветка — единственный источник проверки и обычного
обновления; GitHub Releases — только источник конкретной версии при откате
(rollback ≥ 3.0.0). Установка: main- tarball → раннер **вне процесса**
(`systemd-run --scope`) → бэкап кода → swap → pip при изменении requirements →
restart → health по ожидаемой версии → при провале health **авто-откат кода**.
Аудит-пара started→finished переживает рестарт через снимок `audit_op` в
`data/update/state.json`; `init_on_startup` закрывает брошенные состояния.

**HTTPS панели (`core/web_tls.py`).** Режимы: off / letsencrypt / self-signed /
custom / proxy (терминация на реверс-прокси, доверие X-Forwarded-* только
`trusted_proxies`). Владение разделено: **systemd-юнит владеет транспортом**
(флаги ExecStart), config — происхождением; при расхождении (после restore/отката)
правдой считается юнит. Включение — тем же паттерном отсоединённого раннера с
откатом юнита на сбое; продление — суточная задача CoreJobQueue. Порт Web —
`core/web_port.py` (тоже раннер + health + откат).

---

## 12. Сквозные паттерны (почему оно так устроено)

Это самый важный раздел для понимания кодовой базы — решения повторяются в разных
подсистемах.

1. **Отсоединённый раннер: `systemd-run --scope` + state.json + startup-reconcile.**
   Используют `update/updater.py`, `web_tls.py`, `web_port.py`,
   `backup/self_restore.py`. Причина: `KillMode=mixed` юнита убивает дочерние
   процессы при stop — раннер должен переживать рестарт сервиса, которому меняет
   код/порт/самого себя. Все раннеры stdlib-only. Брошенные состояния закрывает
   reconcile на старте.
2. **Systemd-юнит — источник истины о транспорте.** updater (порт/схема health),
   web_tls, web_port, TG-бэкапы читают фактические флаги из юнита, а не из config —
   config может опережать реальность после отката/restore.
3. **Три процесса-писателя одних файлов** (uvicorn, чистый ТГ, CLI). Следствия:
   sqlite WAL + busy_timeout; все RMW под flock; SSE отдаёт хвосты по
   **водяным знакам таблиц** (`metrics.tail_since`, `audit_query.tail_after`),
   а не через внутрипроцессную шину — половину событий шина бы не увидела.
   Водяной знак аудита — пара `(rowid, ts)`: ts теряет вторую запись в ту же секунду,
   чистый rowid переиспользуется после чистки.
4. **Двойная запись событий**: `logs/events/*.json` (лимит записей, человеческий
   журнал) и sqlite-аудит (бессрочный, append-only, с маскированием секретов) —
   это два разных хранилища с разными ролями, а не дублирование по недосмотру.
5. **Actor через contextvars + ловушка пулов.** `core/actor.py`: contextvars
   пробрасываются в `asyncio.to_thread`, но НЕ в `loop.run_in_executor`/
   `ThreadPoolExecutor.submit` — обёртка `in_thread_context` копирует контекст
   вручную (используют мониторинг и Quick Setup). CLI-актор сознательно без роли:
   «маппить локального root в admin значило бы записать неправду».
6. **Ранние проверки до границы мутаций.** Пароль бэкапа проверяется до регистрации
   Operation (неверный пароль = чистый отказ без следов); consent и идемпотентность
   — до protective copy; в restore есть явная mutation boundary, после которой
   отмена запрещена.
7. **Владение артефактом определяет место кода** (см. также дизайн-правила проекта):
   cert-lifecycle 3x-ui живёт в `services/3x-ui/`, а не в ядре; формат БД и её
   спутников определяет `state_db`, а бэкап только спрашивает; Telegram — «лишь
   канал уведомлений», не владелец жизненного цикла ядра.

---

## 13. Куда смотреть первым делом

| Задача | Файлы |
|---|---|
| Добавить API-эндпоинт | `ui/web/routers/<область>.py` (19 роутеров), авторизация — зависимость `_AUTH` в `app.py` |
| Изменить пользовательский справочник | `ui/web/faq.html`, `ui/web/static/js/faq.js`; маршрут `GET /faq` в `ui/web/app.py`. Это отдельный аутентифицированный `FileResponse`, не страница SPA и не файл в `/static`; контекстные ссылки используют якорь раздела и `returnTo` с возвратом только на `/` того же origin |
| Добавить TG-обработчик | `ui/telegram/handlers/…`, регистрация в цепочке `bot_handlers.py::button()`; состояние визарда — `state.py` |
| Новая фоновая задача | `core/jobs_runtime.py` (CoreJobQueue) |
| Новое событие | тип/причина — `core/event_types.py`; создание — `core/event_service.py`; категория уведомления — `core/notification_policy.py` |
| Новое действие аудита | коды — `core/audit_actions.py`; запись — `core/audit.py` (маскировка секретов уже внутри) |
| Новая колонка в sqlite | `core/state_db.py` (миграция, только вперёд, `SCHEMA_VERSION`) |
| Новый сервис | `services/<id>/service.json` + класс `Service`; ядро подхватит сканом |
| Новый firewall-бэкенд | контракт `core/quick_setup/firewall/base.py` |
| Изменить шифрование секретов | только `core/secretbox.py` + точки входа-выхода в `storage.py`/`config.py` |

---

## 14. Проверка документа

Документ привязан к версии в `core/version.py`. Чек-лист при правках ядра:

- изменились интервалы/лимиты → таблицы в разделах 5–6;
- новая таблица sqlite или миграция → раздел 6 и `SCHEMA_VERSION`;
- новый job → таблица в разделе 5;
- новый отсоединённый раннер → раздел 12.1;
- изменился поток операции → диаграмма в разделе 4.
