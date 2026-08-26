# Bot4VPS Backup Core — архитектура и модель безопасности

Документ описывает работу `core/backup/` в v4.5: модули, потоки данных, границы доверия и защитные механизмы. Предназначен для разработчиков и для сопровождения (в том числе «через полгода»).

Схема версии данных: **schema_version = 1**.

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
| `restore_apply.py` | Target: inventory, free space, symlink guards, upload, tar, verify |
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

---

## 4. Catalog, Operations, Locks

### 4.1 Catalog

Запись на backup: type, purpose, mode, filename, source, timestamps, storage keys, projection manifest, verification, retention claim.

Purpose различает обычные копии и служебные (в т.ч. protective — не съедаются обычным retention как «старый automatic»).

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
3. Locks + Operation.
4. Сбор на target (SSH) или локально (bot4vps sources) → staging tar.gz.
5. Manifest + member validation.
6. Checksum, inventory staging, `publish_pair`, catalog.
7. Retention (если automatic / policy).

Full-root критерий: top-level каталоги `/` минус `/proc`, `/sys`, `/dev`, `/run` — тот же критерий, что SFTP-браузер профиля (только real dirs, не symlinks).

---

## 6. Restore — модель «не доверяй предыдущему слою»

Принцип: каждый этап заново проверяет входы предыдущего. UI selection никогда не становится аргументом tar напрямую.

### 6.1 Высокоуровневый pipeline

```
UI selection
    → normalize paths / selection_mode
    → scope (catalog | manifest | request target_root)
    → archive member validation (manifest.py)
    → restore_plan: mapped entries, effective plan, delete-set digests
    → online policy (blocked trees, hardlink graph)
    → target inventory (SSH)
    → delete-set + protected patterns
    → symlink guards (roots + ancestors inside roots)
    → tar capability (GNU + restore_supports)
    → free-space per root (+ archive on target)
    → protective backup (publish first)
    → re-validate prepared state (plan/delete/process/archive)
    → upload full archive + member list
    → mutation_started
    → exact member allowlist → tar --null --verbatim-files-from --no-recursion
    → post-extraction physical verification
    → cleanup remote staging (failure → warning, не FAIL операции)
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

**Tar:** только GNU + явный набор `restore_supports` (`--overwrite`, `--numeric-owner`, `--strip-components`, `-p`, `--null`, `--verbatim-files-from`, `--files-from`, `--no-recursion`).

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
- Публикуется как полноценный backup (отдельное имя с infix `_before.restore_`).
- Старая protective-копия того же контекста удаляется **только после** успешной публикации новой.
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

## 12. Что сознательно не делает v1

- Remote storage backends (только local).
- Инкрементальные/дельта-архивы.
- Шифрование архивов на стороне core.
- Online restore в blocked trees (даже «очень надо») — только смена selection / offline-сценарий вне этого API.
- Windows / не-GNU tar на target для restore.

---

## 13. Рекомендации по сопровождению

1. Любое расширение blocked trees — через `ONLINE_RESTORE_BLOCKED_TREES` + bump `online_restore_policy_revision()`.
2. Не смешивать pure plan и SSH: новый precheck target — в `restore_apply`, новая геометрия путей — в `restore_plan`.
3. Inventory всегда repairable; не делать publish зависимым от успеха sidecar.
4. Protective и regular retention — разные политики.
5. Changelog/README: коротко про online policy, protective, allowlist+post-verify (детали — этот документ).

---

*Документ соответствует коду `core/backup/` в дереве v4.5 (архив bot4vps). При изменении контрактов обновляйте schema_version и этот файл.*
