# Bot4VPS Backup Core — архитектура и модель безопасности

Документ описывает работу `core/backup/` в 7.0: модули, потоки данных, границы доверия и защитные механизмы. Предназначен для разработчиков и для сопровождения (в том числе «через полгода»).

Общая карта проекта — [architecture.md](architecture.md); здесь — глубокое погружение в backup.

Operation использует **schema_version = 1** (`models.py`). Новые записи Catalog
используют **v5**, а серверные копии без определённого UTC-offset — v4;
чтение прежних схем Catalog v1–v5 поддерживается (`catalog.py`). Inventory —
**v2**, с поддержкой прежнего индекса v1. Контракт выбора восстановления —
**v3** (`RESTORE_SELECTION_VERSION = 3`); прежние v1/v2 читаются как история.

Поддерживаются **manifest v1/v2/v3** (`manifest.py`). Новые серверные копии
создаются с v2, при неизвестном UTC-offset — с v1. **Manifest v3 предназначен
только для собственных копий сервиса Bot4VPS** и используется внутри B4VS.
Версия manifest, версия контейнера B4VS и версия приложения APP_VERSION —
отдельные значения; совместимость self-restore определяется по APP_VERSION
из фактического кода архива.

---

## 1. Назначение

Backup Manager — единый core для:

- создания архивов (сервер по SSH и локальный Bot4VPS);
- каталога, retention, verify, delete;
- import внешних архивов;
- планирования и применения Restore с жёсткими online-ограничениями;
- inventory (компактный индекс для UI) и фоновой индексации.

Публичный фасад: `BackupManager` (`manager.py`). Остальные модули — внутренние слои.

---

## 2. Карта модулей

| Модуль | Роль |
|--------|------|
| `manager.py` | Оркестрация: create / import / verify / delete / retention / restore |
| `models.py` | Operation, Catalog, DiskState, контракты selection/summary |
| `archive_crypto.py` | Шифрование B4VE (AES-256-GCM поверх архива), scrypt-ключ, `verify_password` |
| `archive_format.py` | Контейнер B4VS собственных копий, общий адаптер чтения TAR и staging раннера |
| `self_restore_version.py` | Совместимость self-restore по фактической строковой константе APP_VERSION из архива |
| `errors.py` | `ErrorCode`, `BackupError`, `SafeError` (безопасное сообщение наружу) |
| `validation.py` | Профили, schedule, limits, safety thresholds, имена/ключи |
| `source_selection.py` | Нормализация путей sources, SFTP-browse, probe |
| `full_root_sources.py` | Детерминированный набор top-level для «Full» (минус pseudo-FS) |
| `bot4vps_sources.py` | Sources/exclusions для self-backup установки Bot4VPS |
| `manifest.py` | Чтение/валидация manifest + members, verify archive |
| `inventory.py` | Компактный индекс архива, projection, policy, query API |
| `inventory_indexer.py` | Фоновая сборка/починка inventory |
| `storage.py` | Local backend: staging → publish, checksum, binding, import bundles |
| `catalog.py` | Каталог опубликованных backup, retention claims |
| `operations.py` | Журнал операций, статусы, mutation boundary |
| `locks.py` | flock-координатор (targets, artifacts, retention, imports, …) |
| `restore_plan.py` | **Чистое** планирование Restore (без SSH и мутаций) |
| `restore_apply.py` | Target: inventory, free space, symlink guards, upload, tar, verify; локальный apply |
| `state_snapshot.py` | Консистентный слепок state.db (VACUUM INTO) для self-backup; расчёт stale `-wal/-shm` sidecars |
| `self_restore.py` | Оркестратор self-restore установки (единый путь Web/CLI/Mobile API), reconcile на старте |
| `self_restore_runner.py` | Standalone-исполнитель self-restore на чистом stdlib, живёт вне процесса панели |
| `scheduler.py` | Расписание automatic backup |
| `disk.py` | Admission по свободному месту (warning/critical/emergency) |
| `record_store.py` | Общий atomic JSON-store для служебных записей |
| `ids.py`, `time_utils.py` | ID и UTC timestamps |

Точка экспорта пакета (`__init__.py`): `BackupManager`, `CatalogStore`, `OperationStore`, модели и ошибки.

---

## 3. Хранилище и публикация

### 3.1 Layout

- **Storage root** — абсолютный путь вне install_path Bot4VPS (`assert_storage_root_is_external`).
- Backend в v1 только `local`.
- Staging → final publish пары: `archive.tar.gz` + `.sha256`.
- Inventory — sidecar (repairable cache): сбой inventory **не** инвалидирует уже проверенный архив.

### 3.2 Publication protocol

Для управляемых копий, создаваемых Bot4VPS:

1. Сбор/загрузка в staging.
2. `verify_archive` / `verify_archive_with_members` (manifest + namespace members).
3. Checksum + staging inventory (по возможности).
4. `publish_pair`: `os.replace` archive и checksum, fsync file + parent dir, mode `0o600`.
5. Запись/очередь managed inventory; запись в Catalog.

Повторный publish того же `backup_id` → `ARTIFACT_ALREADY_EXISTS`.

### 3.3 Integrity binding

Inventory и import bundles привязаны к identity архива:

- `sha256`, `bytes`, `format`;
- при проверке — dev/ino/size/mtime (binding identity), чтобы не принять подмену файла с тем же именем.

Периодическая/точечная сверка checksum + binding до restore/verify.

### 3.4 Import

Отдельный import bundle + publication metadata. Read-lock на bundle на время restore, чтобы bytes не заменили между precheck и apply.

Обычный импортированный TAR может не иметь manifest: импорт сохраняет
доступные metadata, а область восстановления задаётся корректным manifest
или явным `target_root`. Контейнер B4VS требует корректный собственный
manifest v3 и не переходит к этому fallback при ошибке. При self-restore
любого импортированного архива в 7.0+ фактическая версия кода всё равно
должна быть подтверждена по всему архиву.

### 3.5 Шифрование архивов (B4VE)

- Потоковое **AES-256-GCM поверх готового архива** (`archive_crypto.py`): ключ выводится **scrypt** (N=2¹⁴, r=8, p=1, соль 16 байт), архив режется на чанки по 4 МиБ, nonce = случайный 8-байтовый префикс + счётчик, **AAD = заголовок + номер чанка + флаг «последний»** → защита от перестановки чанков, подмены из другого архива и обрезки хвоста. Магия заголовка — `B4VE`, версия формата 1.
- Пароль (приоритет): явный одноразовый → сохранённый (`enc1:` в config.json, расшифровывается мастер-ключом) → `None`. Автоматика без пароля (расписание) — plain-архив + warning-событие: отсутствующий бэкап хуже нешифрованного. Недоступность мастер-ключа при create — тоже plain + warning; при restore — отказ.
- **Ранняя проверка пароля**: при import и отдельной проверке пароля `verify_password` расшифровывает первый кусок. При restore выполняется полная расшифровка во временный staging-файл до регистрации Operation; неверный пароль даёт отказ без записи Restore в истории. В Telegram пароль не вводится: восстановление зашифрованных архивов доступно через Web.
- Коды ошибок: `ENCRYPTION_PASSWORD_INVALID`, `ENCRYPTION_PASSWORD_REQUIRED`, `ENCRYPTION_UNSUPPORTED`, `ENCRYPTION_FAILED`.

---

## 4. Catalog, Operations, Locks

### 4.1 Catalog

Запись на backup: type, purpose, mode, filename, source, timestamps, storage keys, projection manifest, verification, retention claim.

Purpose различает обычные копии и исторические служебные виды. Защитная копия перед Restore сейчас записывается как `purpose=regular`, `mode=manual`; automatic retention её не удаляет.

### 4.2 Operations

Статусы: `queued` → `running` → `verifying` → `completed` | `failed` | `cancelled`.

Критическая граница:

- до mutation — отмена допустима;
- после `mutation_started` — `cancellation.allowed = false` (особенно важно для clean restore).

В Operation персистится усечённый restore plan summary + digests effective plan / delete-set (полный план не хранится в записи).

### 4.3 Locks (`LockCoordinator`)

`flock` + каталоги `0o700`:

- targets (один destructive restore на target);
- artifacts;
- retention;
- operations;
- imports / destinations;
- catalog.

Maintenance state — чтобы не пересечься с update/migration Bot4VPS.

---

## 5. Создание backup (кратко)

1. Валидация profile/sources (`validation` + `source_selection`).
2. Disk admission (`disk` safety thresholds).
3. Locks + Operation; разрешение пароля (`_resolve_encryption_password`).
4. Сбор на target (SSH) или локально (bot4vps sources) → staging tar.gz. Для bot4vps — консистентный слепок state.db (`state_snapshot`), см. §5.1.
5. Формат зависит от типа копии: для управляемого сервера — TAR с manifest v2 (v1 при неизвестном UTC-offset); для самой Bot4VPS — TAR с manifest v3 и обязательный контейнер B4VS v1. Проверка manifest/members выполняется через общий адаптер; затем при заданном пароле применяется B4VE (`encrypt_in_place`, до публикации).
6. Checksum, inventory staging, `publish_pair`, catalog.
7. Retention (если automatic / policy).

Full-root критерий: top-level каталоги `/` минус `/proc`, `/sys`, `/dev`, `/run` — тот же критерий, что SFTP-браузер профиля (только real dirs, не symlinks).

### 5.1 Self-backup: что входит и что нет

В архив установки входят каталог установки и живой systemd-юнит. Исключаются: `venv/`, `.git`, кэши, живая sqlite-тройка `state.db`/`-wal`/`-shm` (в архив кладётся слепок `snapshot_state_db`, а не живые файлы), mutable-runtime файлы самого бэкап-контура — и принципиально **мастер-ключ `keys/secret.key`**: ключ внутри архива размыкал бы все `enc1:`-секреты этого же архива, включая сохранённый пароль бэкапов из config.json. После restore панель поднимает баннер мастер-ключа и ждёт ручного ввода.

Новые собственные копии 7.0 используют обязательный контейнер **B4VS v1**
с внутренним tar.gz и manifest v3. Это относится также к автоматическим и
защитным копиям. Порядок: TAR → B4VS → опциональное прежнее шифрование B4VE.
Имя `.tar.gz` и поле `format` в Catalog/inventory описывают внутренний формат,
как для B4VE; SHA-256 и размер всегда относятся ко всему опубликованному файлу.
`archive_format.py` открывает контейнер для import/verify/inventory и выделяет
TAR в staging раннера. Заголовок — 16 байт: `B4VS`, байты версии `01` и
формата payload `01` (gzip TAR), десять нулевых reserved байт. Неизвестный,
повреждённый заголовок или контейнер без корректного собственного manifest v3
отвергаются. Старый восстановитель не может прочитать B4VS как TAR даже после
расшифровки или переименования файла.

Формат резервных копий управляемых серверов остаётся прежним (manifest v1/v2).
Ранее созданные обычные TAR-копии самой 7.0 с manifest v1/v2 поддерживаются при
подтверждённой версии кода; они не переписываются и не приобретают контейнер
автоматически. B4VS предотвращает случайное восстановление через границу
архитектур; ручное снятие обёртки или пересборка архива не входят в эту защиту.

---

## 6. Restore — модель «не доверяй предыдущему слою»

Принцип: каждый этап заново проверяет входы предыдущего. UI selection никогда не становится аргументом tar напрямую. Зашифрованный источник расшифровывается рано — до регистрации Operation и до любых мутаций (см. §3.5).

### Контракт подтверждённого восстановления

Выбор хранится в Operation как версионированный контракт v3: режим, canonical
selected paths, effective roots и digest плана; для clean-режима также digest
delete-set. Пути сортируются и сворачиваются без вложенных дублей. Подтверждение
защитного backup и параметры target привязаны к этому же контракту. Перед
применением повторно проверяются архив, состав плана и файловая система цели;
старый preview не является разрешением на изменившийся target.

Self-restore распаковывает рабочие данные от `bot4vps`, без применения
численных UID/GID из архива. Код устанавливается только из защищённого
снимка помощника с совпадающими SHA-256, а unit реконструируется с
`User=bot4vps`. При изменении доверенного requirements lock помощник
устанавливает зависимости с `--require-hashes` и обновляет собственную
копию. Код, зависимости и unit имеют журнал отката до завершения health.
Выбор данных из чужого кода допускается при подтверждённой версии Bot4VPS
7.0+; установка такого кода требует подписанного релиза. Временный расшифрованный архив
копируется в shared state до сохранения metadata, поэтому PrivateTmp
основной службы не мешает отдельному раннеру и повторной попытке.
См. [root-separation.md](root-separation.md).

Перед prepare и повторно перед apply self-restore проверяет фактический
`core/version.py` по раскладке **всего** архива, независимо от selection.
`APP_VERSION` читается как единственная строковая константа через AST, без
импорта/исполнения кода, с ограничением 64 КиБ и запретом ссылок и неоднозначных
значений. В установке 7.0+ версия ниже 7.0 или неизвестная версия приводят к
общему SafeError до защитной копии, запуска раннера и остановки службы.
Подсказка предлагает штатный откат до совместимой версии, затем restore.
Версия 7.0+ не отменяет проверки доверенного кода и прав помощником.
Self-restore берёт приватный снимок под read-lock источника, проверяет SHA-256
публикации и связывает prepared-операцию с digest/размером полного содержимого.
Apply заново проверяет снимок и привязку; раннер получает TAR из этих же байтов.

CLI, Web и Mobile API запускают prepare/apply через общие методы
`BackupManager.submit_restore` / `submit_imported_restore`, поэтому проверку
совместимости нельзя обойти выбором интерфейса. Mobile API после проверки
сессии устройства передаёт запросы тем же маршрутам `/api/backups/...`, что Web.
CLI и мобильное приложение показывают полную безопасную причину отказа.
В Telegram доступно восстановление копий выбранного сервера через тот же
BackupManager; self-restore Bot4VPS в Telegram не представлен. Серверные
копии проходят прежние проверки восстановления без ограничения APP_VERSION 7.0.

### 6.1 Высокоуровневый pipeline

Операция Restore сохраняет прежние фазы prepare/apply. Новые собственные
копии имеют внешний контейнер и дополнительную проверку совместимости;
серверный путь восстановления сохраняется.

| Архив | Формат и manifest | Восстановление |
|---|---|---|
| Управляемого сервера | TAR, manifest v1/v2; опциональное B4VE | По SSH; merge или clean в разрешённой области, прежняя совместимость |
| Новая собственная копия Bot4VPS | B4VS v1 с внутренним TAR и manifest v3; опциональное B4VE снаружи | Локальный self-restore; только merge, фактическая версия архива 7.0+ |
| Прежняя собственная копия Bot4VPS | Обычный TAR, manifest v1/v2; опциональное B4VE | В установке 7.0+ допускается при фактической версии архива 7.0+; ниже 7.0 или неизвестная версия запрещены даже при выборе данных |

Общие проверки выполняются до защитной копии:

```
UI selection
    → normalize paths / selection_mode
    → consent, разрешение источника и read-lock
    → для self-restore: приватный снимок со сверкой checksum публикации
    → расшифровка B4VE при необходимости
    → чтение TAR через archive_format (обычный архив или внутренний TAR B4VS)
    → физическая проверка members
    → scope (catalog | manifest | request target_root)
    → полный mapped plan
    → для self-restore в 7.0+: APP_VERSION всего архива ≥ 7.0, иначе отказ
    → effective selection, policy, plan/delete-set digests
    → сверка prepared contract; для self-restore также digest/bytes всего архива
    → preflight цели (SSH для сервера, локальные пути для Bot4VPS)
    → protective backup (publish first)
    → apply=False: COMPLETED / prepared; файлы цели не изменены
    → apply=True: соответствующий путь применения ниже
```

Управляемый сервер:

```
preflight: target inventory / delete-set / protected patterns
    → symlink guards / GNU tar capability / free-space
    → после защитной копии:
    → upload full archive + member list
    → mutation_started
    → exact member allowlist → tar --null --verbatim-files-from --no-recursion
    → post-extraction physical verification
    → cleanup remote staging (failure → warning, не FAIL операции)
    → COMPLETED / FAILED
```

Сама Bot4VPS:

```
preflight: локальные symlink guards / free-space
    → после защитной копии:
    → TAR из проверенного снимка в shared staging раннера
    → повторная проверка APP_VERSION по полному плану и входным байтам раннера
    → helper проверяет выбранный код и unit, прежние границы доверия сохраняются
    → отдельный runner ждёт go-файл
    → mutation_started + go-файл
    → stop → удаление stale SQLite sidecars → восстановление данных от bot4vps
    → доверенный код/unit/зависимости через helper → start → health
    → физическая проверка и финализация; reconcile после перезапуска
    → COMPLETED / FAILED
```

### 6.2 `restore_plan.py` — pure planning

Нет SSH, нет мутаций. Отвечает только:

- куда лёг бы каждый member (scope, layout, абсолютные пути);
- что на target есть, но нет в архиве (вход для delete-set — по уже прочитанной inventory).

**Layout:**

- A: `manifest.json` + `payload/<absolute without leading slash>`;
- B: чужой tar + явный `target_root`.

**Scope roots:**

- абсолютные, depth ≥ 1, **`/` запрещён**;
- без дублей и вложенности;
- без collision payload-prefix;
- без пересечения с local storage root (в обе стороны).

**Online blocked trees** (`ONLINE_RESTORE_BLOCKED_TREES`):

`/boot`, `/proc`, `/sys`, `/dev`, `/run`,  
`/bin`, `/sbin`, `/lib*`,  
`/usr/bin`, `/usr/sbin`, `/usr/lib*`, `/usr/libexec`.

Проверка двусторонняя (path↔tree). Hardlink на blocked target блокирует owning directory и selectable ancestors.  
При `selection_mode=full` и пересечении → `full_restore_unavailable` + `blocked_paths` (UI предлагает только safe subset).

**Secret paths:** тот же предикат, что при записи manifest (`.ssh`, `id_*`, `authorized_keys`, `.pem`, `.key`) — restore root не может быть secret.

**Selection → effective plan:**  
mapped members → validated entries → digest.  
Tar позже получает **только** allowlist из effective plan.

### 6.3 `restore_apply.py` — target side

**Режимы:** `merge` (только наложение) / `clean` (точное совпадение scope, с delete-set).

**Protective sources:**  
- clean — корни целиком;  
- merge — first-level children, затронутые архивом (с widen при раздувании).  
Лимиты на число sources.

**Symlink protection:**

1. `assert_no_symlink_components` — root и все parent-компоненты не symlink.
2. `assert_no_symlink_ancestors` — промежуточные пути **внутри** root (GNU tar 1.35 проходит существующие symlink’и насквозь с exit 0).

**Tar на управляемом сервере:** только GNU + явный набор `restore_supports` (`--overwrite`, `--numeric-owner`, `--strip-components`, `-p`, `--null`, `--verbatim-files-from`, `--files-from`, `--no-recursion`). Локальный self-restore использует отдельный путь раннера и помощника, описанный в §6.1.

**Free space:** оценка по корням + место под архив на target; отказ до mutation.

**Upload:** архив целиком на target, проверка размера; partial transfer → mutation не начинается.

**Delete:** только проверенные пути строго внутри roots; никогда сам root «целиком одной командой»; `rm -rf --` пакетами; повторная проверка границ.

**Post-verify:** физическая сверка ожидаемых files/symlinks и отсутствия лишнего после clean.  
Diagnostics tar: известный controlled skip (например ETXTBSY) vs любая неизвестная/смешанная ошибка → fatal. Нет «exit≠0, но SUCCESS».

**Cancel:** после `mutation_started` запрещён.

---

## 7. Inventory

- Пишется при create (и по возможности при import).
- Компактное представление members + policy projection для UI (дерево, selectable/blocked, search, cursors).
- Web UI **не** парсит tar на каждый клик — читает inventory / projection.
- Repairable: битый/отсутствующий inventory чинится indexer’ом; архив при этом остаётся валидным после physical verify.

---

## 8. Protective backup

- Создаётся **до** mutation restore.
- Публикуется как полноценный обычный backup: `purpose=regular`, `mode=manual`, отдельное имя с infix `_before.restore_`.
- Для сервера содержит затрагиваемые источники с учётом merge/clean. Для самой Bot4VPS создаётся полная собственная копия по фиксированной политике источников: B4VS v1 + TAR/manifest v3, с текущей настройкой шифрования.
- Предыдущая защитная копия того же контекста удаляется **только после** успешной публикации новой; исторические записи `purpose=protective` остаются допустимыми для чтения.
- Не должна съедаться обычным automatic retention как «просто старая копия».
- Если protective не удался — restore не продолжает destructive-фазу (кроме явного confirm без protective, если API это допускает).

---

## 9. Disk safety

Пороги в config `safety` (строго убывающий порядок):

`warning_free_bytes` > `critical_free_bytes` > `recovery_free_bytes` > `emergency_free_bytes`

Плюс TTL staging/claim. Create/import/restore учитывают admission до тяжёлой работы.

---

## 10. Ошибки

- `RESTORE_PRECHECK_FAILED` — target ещё не меняли.
- `RESTORE_APPLY_FAILED` — mutation уже могла начаться.
- `PROTECTIVE_BACKUP_FAILED`, `CHECKSUM_MISMATCH`, `ARCHIVE_PATH_UNSAFE`, `TARGET_BUSY`, `LOCK_TIMEOUT`, …
- Наружу — `SafeError` (code, message, retryable, correlation_id, details без лишней внутренности).

---

## 11. Границы доверия (сводка)

| Источник | Доверие |
|----------|---------|
| UI selection | Нет — только вход в normalize/plan |
| Пути в TAR | Нет — normalize, scope, member validation |
| Manifest (в т.ч. import) | Частично — schema + secret reject + scope |
| Prepared plan (старый preview) | Нет — re-check перед apply |
| Effective allowlist | Да — единственный вход в tar |
| Inventory sidecar | Cache — при сомнении rebuild, истина = archive+checksum |
| Target FS | Проверяется (inventory, symlinks, space, processes) |

---

## 12. Текущие ограничения

- Remote storage backends (только local).
- Инкрементальные/дельта-архивы.
- Online restore в blocked trees (даже «очень надо») — только смена selection / offline-сценарий вне этого API.
- Windows / не-GNU tar на target для restore.

Шифрование архивов, отсутствовавшее на момент первой версии документа, реализовано в `archive_crypto.py` (§3.5).

---

## 13. Рекомендации по сопровождению

1. Любое расширение blocked trees — через `ONLINE_RESTORE_BLOCKED_TREES` + bump `online_restore_policy_revision()`.
2. Не смешивать pure plan и SSH: новый precheck target — в `restore_apply`, новая геометрия путей — в `restore_plan`.
3. Inventory всегда repairable; не делать publish зависимым от успеха sidecar.
4. Protective и regular retention — разные политики.
5. Changelog/README: коротко про online policy, protective, allowlist+post-verify (детали — этот документ).

---

*Описание форматов и путей backup/self-restore сверено с `core/backup/` 2026-11-11. При изменении контрактов обновляйте соответствующие версии схем и этот файл.*
