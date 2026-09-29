"""sqlite-хранилище рядов метрик и записей аудита (``data/state.db``).

Владелец схемы и соединений — по роли аналог ``core/json_store.py``, но для
sqlite. Причина существования: метрики и аудит — это поток записей с
выборками по диапазону времени, а не конфиг и не документ; формат «один
json-файл на запись» (как в ``logs/events``) для рядов не годится.

Писателей три процесса: uvicorn (``ui.web.app``), чистый ТГ-вход
(``bot.py``) и CLI (``ui/cli``). Их одновременную запись разводят WAL и
``busy_timeout`` — то есть настройки соединения, а не автоматика: без них
будет «database is locked» ровно тогда, когда два интерфейса пишут вместе.
Ради этого в проекте и появился sidecar flock у json-хранилищ; здесь его
роль занимает sqlite — но только при явно выставленных PRAGMA.

Инварианты (нарушение = баг, см. §3 ТЗ ``plans/AUDIT_AND_METRICS_PLAN.md``):

- **время — epoch UTC (секунды)**, никаких локальных naive-строк;
- **отсутствие данных ≠ 0**: пропущенная проба не пишет строку вообще,
  поэтому дыра в ряду видна как дыра, а не как простой сервера;
- **аудит append-only**: записи не редактируются и не удаляются каскадно
  вместе с задачами и логами. Ретенция аудита не трогает — см. ``prune()``;
- **старый код должен переживать новую схему** (self-restore откатывает код
  к срезу архива, а БД может оказаться новее): миграции только вперёд и
  только аддитивные, в коде — явные списки колонок, никаких ``SELECT *``;
- **БД не критична для работы панели**: повреждение уводит файл в карантин,
  а не роняет панель; ошибка записи уходит в stdout, а не наружу.

БД локальная (не NFS): WAL этого требует.
"""
from __future__ import annotations

import math
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from core.json_store import quarantine

NAME = "STATE DB"

DB_NAME = "state.db"

DB_PATH = Path("data") / DB_NAME

# Версия схемы, которую знает этот код. Поднимается вместе с новой миграцией.
SCHEMA_VERSION = 7

# Метрики не входят в архив Bot4VPS (§16.1 ТЗ). Список имён, а не «всё,
# кроме audit_records»: новая таблица по умолчанию остаётся в слепке, чтобы не
# потерять данные из-за пропущенного исключения.
METRIC_TABLES: tuple[str, ...] = (
    "metric_samples",
    "metric_disks",
    "metric_hourly",
    "operation_metric_peaks",
    "operation_metric_peak_disks",
)


# Спутники sqlite-файла. Рядом с восстановленной БД чужой WAL — это либо
# отказ открытия, либо, хуже, молча чужие страницы в кэше.
SIDECAR_SUFFIXES: tuple[str, ...] = ("-wal", "-shm", "-journal")

# Обязательные PRAGMA (порядок не важен, кроме journal_mode: его выставляет
# первый, кто открыл БД, — на существующем файле это no-op).
_PRAGMAS = (
    "journal_mode=WAL",
    "busy_timeout=5000",
    "synchronous=NORMAL",
    "foreign_keys=ON",
)

# Ретенция (§9 ТЗ). Обрезаются только ряды метрик; аудит — бессрочно.
RAW_METRICS_DAYS = 90
HOURLY_METRICS_MONTHS = 24


# ------------------------------------------------------------------
# Схема. Только аддитивные шаги: CREATE TABLE/INDEX IF NOT EXISTS и новые
# колонки с дефолтом. Никаких DROP/ALTER ... RENAME — по ним ломается
# инвариант «старый код + новая БД».
# ------------------------------------------------------------------

_SCHEMA_V1: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS metric_samples (
        server_id     TEXT    NOT NULL,
        ts            INTEGER NOT NULL,
        source        TEXT    NOT NULL DEFAULT 'system_sync',
        load1         REAL,
        load5         REAL,
        load15        REAL,
        cpu_count     INTEGER,
        ram_used_kb   INTEGER,
        ram_total_kb  INTEGER,
        swap_used_kb  INTEGER,
        swap_total_kb INTEGER,
        uptime_sec    INTEGER,
        PRIMARY KEY (server_id, ts)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS metric_disks (
        server_id TEXT    NOT NULL,
        ts        INTEGER NOT NULL,
        mount     TEXT    NOT NULL,
        fs        TEXT,
        used_kb   INTEGER,
        total_kb  INTEGER,
        used_pct  REAL,
        PRIMARY KEY (server_id, ts, mount)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS metric_hourly (
        server_id     TEXT    NOT NULL,
        hour_ts       INTEGER NOT NULL,
        load1_avg     REAL,
        load1_max     REAL,
        ram_pct_avg   REAL,
        ram_pct_max   REAL,
        disk_max_pct  REAL,
        disk_max_mount TEXT,
        samples       INTEGER NOT NULL,
        PRIMARY KEY (server_id, hour_ts)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_records (
        id          TEXT PRIMARY KEY,
        ts          INTEGER NOT NULL,
        actor_type  TEXT NOT NULL,
        actor_id    TEXT,
        actor_role  TEXT,
        actor_ip    TEXT,
        server_id   TEXT,
        server_name TEXT,
        action      TEXT NOT NULL,
        result      TEXT NOT NULL,
        error       TEXT,
        op_id       TEXT,
        event_id    TEXT,
        task_id     TEXT,
        params      TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_metric_samples_ts ON metric_samples(ts)",
    "CREATE INDEX IF NOT EXISTS idx_metric_disks_ts ON metric_disks(ts)",
    "CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_records(ts)",
    "CREATE INDEX IF NOT EXISTS idx_audit_server_ts ON audit_records(server_id, ts)",
    "CREATE INDEX IF NOT EXISTS idx_audit_actor_ts ON audit_records(actor_id, ts)",
    "CREATE INDEX IF NOT EXISTS idx_audit_action_ts ON audit_records(action, ts)",
    "CREATE INDEX IF NOT EXISTS idx_audit_result_ts ON audit_records(result, ts)",
    "CREATE INDEX IF NOT EXISTS idx_audit_op ON audit_records(op_id)",
)


def _migration_001(conn: sqlite3.Connection) -> None:
    for statement in _SCHEMA_V1:
        conn.execute(statement)


_SCHEMA_V2: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS audit_operations (
        operation_id TEXT PRIMARY KEY,
        started_ts   INTEGER NOT NULL,
        sort_id      TEXT NOT NULL,
        anchor_id    TEXT NOT NULL,
        final_id     TEXT,
        ended_ts     INTEGER,
        action       TEXT NOT NULL,
        title        TEXT NOT NULL,
        result       TEXT NOT NULL,
        status       TEXT NOT NULL,
        error        TEXT,
        actor_type   TEXT,
        actor_id     TEXT,
        actor_role   TEXT,
        actor_ip     TEXT,
        server_id    TEXT,
        server_name  TEXT,
        op_id        TEXT,
        task_id      TEXT,
        event_id     TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_operation_members (
        record_id    TEXT PRIMARY KEY,
        operation_id TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_operation_keys (
        kind         TEXT NOT NULL,
        value        TEXT NOT NULL,
        operation_id TEXT NOT NULL,
        PRIMARY KEY (kind, value)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_records(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_operation_members_operation ON audit_operation_members(operation_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_operation_keys_operation ON audit_operation_keys(operation_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_operations_start ON audit_operations(started_ts, sort_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_operations_server_start ON audit_operations(server_id, started_ts)",
    "CREATE INDEX IF NOT EXISTS idx_audit_operations_actor_start ON audit_operations(actor_type, actor_id, started_ts)",
    "CREATE INDEX IF NOT EXISTS idx_audit_operations_action_start ON audit_operations(action, started_ts)",
    "CREATE INDEX IF NOT EXISTS idx_audit_operations_result_start ON audit_operations(result, started_ts)",
)


def _migration_002(conn: sqlite3.Connection) -> None:
    for statement in _SCHEMA_V2:
        conn.execute(statement)
    from core.audit_operations import rebuild

    rebuild(conn)


_SCHEMA_V3: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS availability_transitions (
        id          TEXT PRIMARY KEY,
        server_id   TEXT NOT NULL,
        server_name TEXT,
        ts          INTEGER NOT NULL,
        online      INTEGER NOT NULL CHECK (online IN (0, 1)),
        error       TEXT
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_availability_transition_key "
    "ON availability_transitions(server_id, ts, online)",
    "CREATE INDEX IF NOT EXISTS idx_availability_transition_server_ts "
    "ON availability_transitions(server_id, ts)",
)


def _migration_003(conn: sqlite3.Connection) -> None:
    for statement in _SCHEMA_V3:
        conn.execute(statement)


_SCHEMA_V5: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS operation_metric_peaks (
        operation_id  TEXT    PRIMARY KEY,
        server_id     TEXT    NOT NULL,
        server_name   TEXT,
        scope         TEXT    NOT NULL,
        captured_ts   INTEGER NOT NULL,
        severity      REAL    NOT NULL,
        load1         REAL,
        load5         REAL,
        load15        REAL,
        cpu_count     INTEGER,
        ram_used_kb   INTEGER,
        ram_total_kb  INTEGER,
        swap_used_kb  INTEGER,
        swap_total_kb INTEGER,
        uptime_sec    INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS operation_metric_peak_disks (
        operation_id TEXT    NOT NULL,
        mount        TEXT    NOT NULL,
        fs           TEXT,
        used_kb      INTEGER,
        total_kb     INTEGER,
        used_pct     REAL,
        PRIMARY KEY (operation_id, mount),
        FOREIGN KEY (operation_id)
            REFERENCES operation_metric_peaks(operation_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_operation_metric_peaks_server_captured "
    "ON operation_metric_peaks(server_id, captured_ts)",
)


def _migration_005(conn: sqlite3.Connection) -> None:
    for statement in _SCHEMA_V5:
        conn.execute(statement)


def _migration_006(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(audit_records)").fetchall()
    }
    if "failure_detail" not in columns:
        conn.execute("ALTER TABLE audit_records ADD COLUMN failure_detail TEXT")


def _migration_007(conn: sqlite3.Connection) -> None:
    # v4 создавала operation_metric_observations/operation_metric_disks —
    # границы операций (before/after), которые так и не получили ни писателя
    # в проде, ни читателя: единственные строки в боевых базах остались от
    # live-валидации. Модель opération-метрик осталась одной таблицей —
    # монотонный пик (operation_metric_peaks); шаг v4 убран из истории,
    # свежие базы эти таблицы не создают, а v7 вычищает их у существующих.
    # DROP — осознанное исключение из «только аддитивных» миграций: таблицы
    # не читаются никаким кодом, и «старый код + новая БД» их тоже не
    # трогает (SELECT к отсутствующей таблице в старом коде не появился —
    # читателей не было и там).
    conn.execute("DROP TABLE IF EXISTS operation_metric_disks")
    conn.execute("DROP TABLE IF EXISTS operation_metric_observations")


# (версия, шаг). Применяются по возрастанию, по одной транзакции на шаг.
MIGRATIONS: tuple[tuple[int, Callable[[sqlite3.Connection], None]], ...] = (
    (1, _migration_001),
    (2, _migration_002),
    (3, _migration_003),
    (5, _migration_005),
    (6, _migration_006),
    (7, _migration_007),
)


# ------------------------------------------------------------------
# Соединение
# ------------------------------------------------------------------

# Соединение на поток: sqlite3.Connection не потокобезопасен. Потоки в
# проекте — это пулы проб (ThreadPoolExecutor) и asyncio.to_thread; они
# переиспользуются, поэтому словарь на потоке остаётся маленьким и умирает
# вместе с потоком. Ключ — путь: тесты и restore-путь подменяют DB_PATH.
_local = threading.local()

# Защита от рекурсии: восстановление пишет событие в журнал, а тот не
# должен снова открывать БД.
_recovering = False


def _thread_connections() -> dict[str, sqlite3.Connection]:
    conns = getattr(_local, "connections", None)
    if conns is None:
        conns = {}
        _local.connections = conns
    return conns


def _raw_connect(path: Path) -> sqlite3.Connection:
    """Открыть соединение с обязательными PRAGMA и явными транзакциями."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # Недоступный каталог — та же категория отказа, что и недоступная
        # БД: наружу из хранилища уходит только sqlite3.Error, иначе один
        # тип сбоя придётся ловить в каждом вызывающем.
        raise sqlite3.OperationalError(str(exc)) from exc
    # isolation_level=None — транзакциями управляем сами (BEGIN/COMMIT):
    # неявные транзакции pysqlite не покрывают DDL и плохо ложатся на
    # WAL + busy_timeout.
    conn = sqlite3.connect(path, timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    for pragma in _PRAGMAS:
        conn.execute(f"PRAGMA {pragma}")
    return conn


def _looks_corrupt(exc: BaseException) -> bool:
    """Отличить повреждённый файл от недоступного.

    «unable to open database file» (права, нет каталога) — не повод
    уводить файл в карантин: он, скорее всего, целый.
    """
    text = str(exc).lower()
    return "not a database" in text or "malformed" in text


def _quarantine_db(path: Path) -> None:
    """Увести БД вместе с WAL/SHM в карантин (по образцу json_store)."""
    for suffix in ("", "-wal", "-shm"):
        candidate = path.with_name(path.name + suffix)
        if candidate.exists():
            moved = quarantine(candidate)
            if moved is not None:
                print(f"[{NAME}] Повреждённый файл уведён в {moved}", flush=True)


def _report_recovery(path: Path, exc: BaseException) -> None:
    """CRITICAL-событие о потере БД. Метрики и аудит не критичны для панели."""
    global _recovering
    if _recovering:
        return
    _recovering = True
    try:
        from core.event_service import create_event
        from core.event_types import EventLevel, EventType

        create_event(
            EventType.DATABASE,
            EventLevel.CRITICAL,
            "Хранилище метрик и аудита создано заново",
            f"Файл {path} повреждён ({exc}); старый уведён в карантин, "
            "заведён пустой. История метрик и аудита за прошлый период "
            "осталась в файле карантина.",
            notify=False,
        )
    except Exception as report_error:  # noqa: BLE001 — диагностика не должна мешать
        print(f"[{NAME}] не удалось записать событие: {report_error}", flush=True)
    finally:
        _recovering = False


def get_connection(path: Optional[Path] = None) -> sqlite3.Connection:
    """Соединение текущего потока к БД, со схемой актуальной версии."""
    target = Path(path) if path is not None else DB_PATH
    key = str(target)
    conns = _thread_connections()
    conn = conns.get(key)
    if conn is not None:
        return conn

    try:
        conn = _raw_connect(target)
        ensure_schema(conn)
    except sqlite3.DatabaseError as exc:
        if not target.exists() or not _looks_corrupt(exc):
            raise
        _quarantine_db(target)
        conn = _raw_connect(target)
        ensure_schema(conn)
        conns[key] = conn
        _report_recovery(target, exc)
        return conn

    conns[key] = conn
    return conn


def close_connections(path: Optional[Path] = None) -> None:
    """Закрыть соединения текущего потока (тесты, смена пути)."""
    conns = _thread_connections()
    if path is None:
        keys = list(conns)
    else:
        keys = [str(Path(path))]
    for key in keys:
        conn = conns.pop(key, None)
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass


def reset() -> None:
    """Полный сброс состояния модуля (тесты): соединения + флаг восстановления."""
    global _recovering
    close_connections()
    _recovering = False


def resolved_path(path: Optional[Path] = None) -> Path:
    """Путь БД так, как его откроет sqlite: относительный — от рабочего каталога.

    Бэкапу нужен именно он: сравнение с деревом установки (что вообще
    класть в архив) обязано считаться по фактическому файлу, а не по
    константе, которая в тестах и dev-запусках подменена.
    """
    return Path(path if path is not None else DB_PATH).resolve()


def sidecar_paths(path: str | Path) -> tuple[Path, ...]:
    """Спутники файла БД (``-wal``, ``-shm``, ``-journal``)."""
    target = Path(path)
    return tuple(target.with_name(target.name + suffix) for suffix in SIDECAR_SUFFIXES)


# ------------------------------------------------------------------
# Версия схемы
# ------------------------------------------------------------------

def schema_version(conn: Optional[sqlite3.Connection] = None) -> int:
    """Версия схемы на диске (``PRAGMA user_version``)."""
    conn = conn or get_connection()
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def ensure_schema(conn: sqlite3.Connection) -> int:
    """Донакатить миграции до ``SCHEMA_VERSION``. Идемпотентно.

    БД новее кода — не ошибка: self-restore может вернуть старый код к
    новой БД, и панель обязана подняться. Работаем с тем, что знаем
    (инвариант «старый код переживает новую схему»).
    """
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if current > SCHEMA_VERSION:
        print(
            f"[{NAME}] Схема на диске (v{current}) новее, чем знает код "
            f"(v{SCHEMA_VERSION}) — работаем с известными таблицами",
            flush=True,
        )
        return current

    for version, step in MIGRATIONS:
        if version <= current:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            step(conn)
            # user_version не принимает параметр: подставляется литералом,
            # значение своё целочисленное, не из данных.
            conn.execute(f"PRAGMA user_version = {int(version)}")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        print(f"[{NAME}] Миграция v{version} применена", flush=True)

    return SCHEMA_VERSION


# ------------------------------------------------------------------
# Запись
# ------------------------------------------------------------------

# Явные списки колонок: новая колонка, добавленная миграцией, не должна
# менять смысл старых вставок (никаких SELECT * и позиционных значений).
SAMPLE_COLUMNS: tuple[str, ...] = (
    "server_id", "ts", "source", "load1", "load5", "load15", "cpu_count",
    "ram_used_kb", "ram_total_kb", "swap_used_kb", "swap_total_kb", "uptime_sec",
)
DISK_COLUMNS: tuple[str, ...] = (
    "server_id", "ts", "mount", "fs", "used_kb", "total_kb", "used_pct",
)
HOURLY_COLUMNS: tuple[str, ...] = (
    "server_id", "hour_ts", "load1_avg", "load1_max", "ram_pct_avg",
    "ram_pct_max", "disk_max_pct", "disk_max_mount", "samples",
)
AUDIT_COLUMNS: tuple[str, ...] = (
    "id", "ts", "actor_type", "actor_id", "actor_role", "actor_ip",
    "server_id", "server_name", "action", "result", "error", "failure_detail",
    "op_id", "event_id", "task_id", "params",
)
OPERATION_METRIC_PEAK_COLUMNS: tuple[str, ...] = (
    "operation_id", "server_id", "server_name", "scope", "captured_ts", "severity",
    "load1", "load5", "load15", "cpu_count", "ram_used_kb", "ram_total_kb",
    "swap_used_kb", "swap_total_kb", "uptime_sec",
)
OPERATION_METRIC_PEAK_DISK_COLUMNS: tuple[str, ...] = (
    "operation_id", "mount", "fs", "used_kb", "total_kb", "used_pct",
)


def _write(
    work: Callable[[sqlite3.Connection], Any],
    default: Any,
    path: Optional[Path] = None,
) -> Any:
    """Транзакция с проглатыванием ошибок: сбор не ломает мониторинг."""
    conn = None
    try:
        conn = get_connection(path)
        conn.execute("BEGIN IMMEDIATE")
        result = work(conn)
        conn.execute("COMMIT")
        return result
    except sqlite3.Error as exc:
        print(f"[{NAME}] запись не удалась: {exc}", flush=True)
        if conn is not None:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        return default

def _insert_sql(table: str, columns: Sequence[str], *, replace: bool) -> str:
    verb = "INSERT OR REPLACE" if replace else "INSERT"
    placeholders = ", ".join("?" for _ in columns)
    return f"{verb} INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"


def _row(item: dict, columns: Sequence[str]) -> tuple:
    return tuple(item.get(column) for column in columns)


def _operation_metric_number(value: Any, *, integer: bool = False) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if integer:
        if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
            return None
        number = int(value)
        return number if -(2 ** 63) <= number < 2 ** 63 else None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def insert_sample(sample: dict, *, disks: Optional[Sequence[dict]] = None) -> bool:
    """Записать пробу сервера и её монтирования одной транзакцией.

    ``INSERT OR REPLACE`` по (server_id, ts): повторная проба в ту же
    секунду обновляет точку, а не роняет проход. Пропущенная проба сюда
    не попадает вовсе — дыра в ряду обязана остаться дырой (§7.4).
    """
    def work(conn: sqlite3.Connection) -> bool:
        conn.execute(_insert_sql("metric_samples", SAMPLE_COLUMNS, replace=True), _row(sample, SAMPLE_COLUMNS))
        for disk in disks or ():
            conn.execute(_insert_sql("metric_disks", DISK_COLUMNS, replace=True), _row(disk, DISK_COLUMNS))
        return True

    return bool(_write(work, False))


def insert_operation_metric_peak(
    peak: dict,
    *,
    disks: Optional[Sequence[dict]] = None,
) -> bool:
    """Сохранить только строго более высокий фактический snapshot операции.

    Сравнение и замена дочерних mount rows происходят в одной транзакции. Равный
    score сохраняет первый снимок, поэтому каждый peak остаётся одной реально
    захваченной точкой, а не набором максимумов разных проб.
    """
    if not (
        peak.get("operation_id")
        and peak.get("server_id")
        and peak.get("scope")
    ):
        return False

    record = {column: peak.get(column) for column in OPERATION_METRIC_PEAK_COLUMNS}
    record["captured_ts"] = _operation_metric_number(record["captured_ts"], integer=True)
    record["severity"] = _operation_metric_number(record["severity"])
    if (
        record["captured_ts"] is None
        or record["severity"] is None
        or record["severity"] < 0
    ):
        return False

    for column in ("load1", "load5", "load15"):
        record[column] = _operation_metric_number(record[column])
    for column in (
        "cpu_count", "ram_used_kb", "ram_total_kb", "swap_used_kb",
        "swap_total_kb", "uptime_sec",
    ):
        record[column] = _operation_metric_number(record[column], integer=True)
    if (
        record["load1"] is None
        or record["ram_used_kb"] is None
        or record["ram_total_kb"] is None
        or record["ram_used_kb"] < 0
        or record["ram_total_kb"] <= 0
    ):
        return False

    peak_disks: dict[str, dict] = {}
    for disk in disks or ():
        mount = str(disk.get("mount") or "")
        if not mount or mount in peak_disks:
            continue
        peak_disks[mount] = {
            "operation_id": record["operation_id"],
            "mount": mount,
            "fs": disk.get("fs"),
            "used_kb": _operation_metric_number(disk.get("used_kb"), integer=True),
            "total_kb": _operation_metric_number(disk.get("total_kb"), integer=True),
            "used_pct": _operation_metric_number(disk.get("used_pct")),
        }

    def work(conn: sqlite3.Connection) -> bool:
        previous = conn.execute(
            "SELECT severity FROM operation_metric_peaks WHERE operation_id = ?",
            (record["operation_id"],),
        ).fetchone()
        if previous is not None and record["severity"] <= float(previous["severity"]):
            return False
        if previous is None:
            conn.execute(
                _insert_sql("operation_metric_peaks", OPERATION_METRIC_PEAK_COLUMNS, replace=False),
                _row(record, OPERATION_METRIC_PEAK_COLUMNS),
            )
        else:
            assignments = ", ".join(
                f"{column} = ?" for column in OPERATION_METRIC_PEAK_COLUMNS[1:]
            )
            conn.execute(
                "UPDATE operation_metric_peaks SET " + assignments + " WHERE operation_id = ?",
                _row(record, OPERATION_METRIC_PEAK_COLUMNS[1:]) + (record["operation_id"],),
            )
            conn.execute(
                "DELETE FROM operation_metric_peak_disks WHERE operation_id = ?",
                (record["operation_id"],),
            )
        for item in peak_disks.values():
            conn.execute(
                _insert_sql(
                    "operation_metric_peak_disks",
                    OPERATION_METRIC_PEAK_DISK_COLUMNS,
                    replace=False,
                ),
                _row(item, OPERATION_METRIC_PEAK_DISK_COLUMNS),
            )
        return True

    return bool(_write(work, False))


def insert_hourly(rows: Sequence[dict]) -> int:
    """Записать часовые свёртки. ``samples`` — сколько сырых точек легло.

    Свёртку считает этап 2 (§7.6); здесь только запись: без ``samples``
    час с одной точкой неотличим от часа без данных, и график на длинном
    диапазоне начинает врать.
    """
    rows = list(rows)
    if not rows:
        return 0

    def work(conn: sqlite3.Connection) -> int:
        sql = _insert_sql("metric_hourly", HOURLY_COLUMNS, replace=True)
        for row in rows:
            conn.execute(sql, _row(row, HOURLY_COLUMNS))
        return len(rows)

    return int(_write(work, 0))


def insert_audit(record: dict) -> bool:
    """Записать raw-пометку и обновить её производную operation-проекцию."""
    def work(conn: sqlite3.Connection) -> bool:
        conn.execute(_insert_sql("audit_records", AUDIT_COLUMNS, replace=False), _row(record, AUDIT_COLUMNS))
        from core.audit_operations import incorporate

        incorporate(conn, record)
        return True

    return bool(_write(work, False))


def insert_availability_transition(
    server_id: str,
    server_name: str | None,
    online: bool,
    *,
    error: str = "",
    ts: int | None = None,
) -> dict | None:
    """Идемпотентно сохранить фактический переход доступности.

    Ключ содержит сервер, секунду и новое состояние: два разных перехода в
    одну секунду не перезаписывают друг друга, а повторная доставка того же
    факта возвращает уже существующую строку.
    """
    moment = int(ts if ts is not None else time.time())
    event = "online" if online else "offline"
    transition_id = f"availability:{server_id}:{moment}:{event}"
    record = {
        "id": transition_id,
        "server_id": server_id,
        "server_name": server_name,
        "ts": moment,
        "online": 1 if online else 0,
        "error": str(error or "")[:2000] or None,
    }

    def work(conn: sqlite3.Connection) -> dict:
        conn.execute(
            """INSERT OR IGNORE INTO availability_transitions
               (id, server_id, server_name, ts, online, error)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (record["id"], record["server_id"], record["server_name"],
             record["ts"], record["online"], record["error"]),
        )
        row = conn.execute(
            "SELECT id, server_id, server_name, ts, online, error "
            "FROM availability_transitions WHERE id = ?",
            (transition_id,),
        ).fetchone()
        return dict(row) if row else record

    return _write(work, None)


# ------------------------------------------------------------------
# Чтение
# ------------------------------------------------------------------

def _query(
    sql: str,
    params: Sequence[Any] = (),
    path: Optional[Path] = None,
) -> list[dict]:
    """Чтение с проглатыванием ошибок (пустой список = «данных нет»)."""
    try:
        conn = get_connection(path)
        cursor = conn.execute(sql, tuple(params))
        return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as exc:
        print(f"[{NAME}] чтение не удалось: {exc}", flush=True)
        return []


def query(
    sql: str,
    params: Sequence[Any] = (),
    path: Optional[Path] = None,
) -> list[dict]:
    """Публичное чтение произвольным запросом (агрегаты свёртки, §7.6).

    Нужно там, где выборка — агрегат, а не ряд: свёртка считает AVG/MAX
    по часу, и оборачивать это в отдельную функцию на каждый запрос
    смысла нет. Ошибки гасятся так же, как в остальных чтениях: пустой
    список вместо исключения (сборщик метрик не должен падать).
    """
    return _query(sql, params, path)


def iter_samples(
    server_id: str,
    since: Optional[int] = None,
    until: Optional[int] = None,
    path: Optional[Path] = None,
) -> list[dict]:
    """Точки сервера за диапазон (epoch UTC), по возрастанию времени."""
    sql = f"SELECT {', '.join(SAMPLE_COLUMNS)} FROM metric_samples WHERE server_id = ?"
    params: list[Any] = [server_id]
    if since is not None:
        sql += " AND ts >= ?"
        params.append(int(since))
    if until is not None:
        sql += " AND ts <= ?"
        params.append(int(until))
    sql += " ORDER BY ts"
    return _query(sql, params, path)


def _one(sql: str, params: Sequence[Any], path: Optional[Path] = None) -> Optional[dict]:
    rows = _query(sql, params, path)
    return rows[0] if rows else None


def sample_predecessor(
    server_id: str,
    *,
    lower: int,
    before: int,
    path: Optional[Path] = None,
) -> Optional[dict]:
    """Ближайшая regular-проба слева от логического окна."""
    return _one(
        f"SELECT {', '.join(SAMPLE_COLUMNS)} FROM metric_samples "
        "WHERE server_id = ? AND ts >= ? AND ts < ? ORDER BY ts DESC LIMIT 1",
        (server_id, int(lower), int(before)),
        path,
    )


def sample_successor(
    server_id: str,
    *,
    after: int,
    upper: int,
    path: Optional[Path] = None,
) -> Optional[dict]:
    """Ближайшая regular-проба справа от логического окна."""
    return _one(
        f"SELECT {', '.join(SAMPLE_COLUMNS)} FROM metric_samples "
        "WHERE server_id = ? AND ts > ? AND ts <= ? ORDER BY ts ASC LIMIT 1",
        (server_id, int(after), int(upper)),
        path,
    )


def hourly_predecessor(
    server_id: str,
    *,
    lower: int,
    before: int,
    path: Optional[Path] = None,
) -> Optional[dict]:
    """Ближайший часовой агрегат слева от логического окна."""
    return _one(
        f"SELECT {', '.join(HOURLY_COLUMNS)} FROM metric_hourly "
        "WHERE server_id = ? AND hour_ts >= ? AND hour_ts < ? "
        "ORDER BY hour_ts DESC LIMIT 1",
        (server_id, int(lower), int(before)),
        path,
    )


def hourly_successor(
    server_id: str,
    *,
    after: int,
    upper: int,
    path: Optional[Path] = None,
) -> Optional[dict]:
    """Ближайший часовой агрегат справа от логического окна."""
    return _one(
        f"SELECT {', '.join(HOURLY_COLUMNS)} FROM metric_hourly "
        "WHERE server_id = ? AND hour_ts > ? AND hour_ts <= ? "
        "ORDER BY hour_ts ASC LIMIT 1",
        (server_id, int(after), int(upper)),
        path,
    )


def iter_availability_transitions(
    server_id: str,
    since: Optional[int] = None,
    until: Optional[int] = None,
    path: Optional[Path] = None,
) -> list[dict]:
    """Переходы доступности сервера за диапазон, по времени."""
    sql = """SELECT id, server_id, server_name, ts, online, error
             FROM availability_transitions WHERE server_id = ?"""
    params: list[Any] = [server_id]
    if since is not None:
        sql += " AND ts >= ?"
        params.append(int(since))
    if until is not None:
        sql += " AND ts <= ?"
        params.append(int(until))
    sql += " ORDER BY ts, id"
    return _query(sql, params, path)


def iter_disks(
    server_id: str,
    since: Optional[int] = None,
    until: Optional[int] = None,
    path: Optional[Path] = None,
) -> list[dict]:
    """Монтирования сервера за диапазон; ключ ряда — (mount, ts)."""
    sql = f"SELECT {', '.join(DISK_COLUMNS)} FROM metric_disks WHERE server_id = ?"
    params: list[Any] = [server_id]
    if since is not None:
        sql += " AND ts >= ?"
        params.append(int(since))
    if until is not None:
        sql += " AND ts <= ?"
        params.append(int(until))
    sql += " ORDER BY ts, mount"
    return _query(sql, params, path)


def operation_metric_peaks(operation_ids: Sequence[str]) -> dict[str, dict]:
    """Пики по producer operation ID, включая mount rows."""
    ids = list(dict.fromkeys(str(value) for value in operation_ids if value))
    result: dict[str, dict] = {}
    for start in range(0, len(ids), 900):
        batch = ids[start:start + 900]
        placeholders = ", ".join("?" for _ in batch)
        rows = _query(
            "SELECT " + ", ".join(OPERATION_METRIC_PEAK_COLUMNS)
            + " FROM operation_metric_peaks WHERE operation_id IN ("
            + placeholders + ") ORDER BY operation_id",
            batch,
        )
        disks = _query(
            "SELECT " + ", ".join(OPERATION_METRIC_PEAK_DISK_COLUMNS)
            + " FROM operation_metric_peak_disks WHERE operation_id IN ("
            + placeholders + ") ORDER BY operation_id, mount",
            batch,
        )
        for row in rows:
            row["disks"] = []
            result[str(row["operation_id"])] = row
        for disk in disks:
            peak = result.get(str(disk["operation_id"]))
            if peak is not None:
                peak["disks"].append({
                    column: disk.get(column)
                    for column in OPERATION_METRIC_PEAK_DISK_COLUMNS[1:]
                })
    return result


def operation_metric_peaks_for_audit_operations(
    audit_operation_ids: Sequence[str],
) -> dict[str, dict]:
    """Найти peak через точные producer ``op_id`` operation-проекции."""
    ids = list(dict.fromkeys(str(value) for value in audit_operation_ids if value))
    result: dict[str, dict] = {}
    for start in range(0, len(ids), 900):
        batch = ids[start:start + 900]
        placeholders = ", ".join("?" for _ in batch)
        keys = _query(
            "SELECT operation_id, value FROM audit_operation_keys "
            "WHERE kind = 'op_id' AND operation_id IN (" + placeholders + ") "
            "ORDER BY operation_id, value",
            batch,
        )
        values_by_operation: dict[str, list[str]] = {}
        for key in keys:
            values_by_operation.setdefault(str(key["operation_id"]), []).append(str(key["value"]))
        peaks = operation_metric_peaks(
            [value for values in values_by_operation.values() for value in values]
        )
        for operation_id, values in values_by_operation.items():
            for value in values:
                peak = peaks.get(value)
                if peak is not None:
                    result[operation_id] = peak
                    break
    return result


def operation_metric_peak_disks(
    operation_id: str,
    path: Optional[Path] = None,
) -> list[dict]:
    """Mount rows одного уже выбранного peak snapshot."""
    return _query(
        "SELECT " + ", ".join(OPERATION_METRIC_PEAK_DISK_COLUMNS)
        + " FROM operation_metric_peak_disks WHERE operation_id = ? ORDER BY mount",
        (operation_id,),
        path,
    )


def operation_metric_peak_predecessor(
    server_id: str,
    *,
    lower: int,
    before: int,
    path: Optional[Path] = None,
) -> Optional[dict]:
    """Ближайший operation peak слева от логического окна."""
    return _one(
        "SELECT " + ", ".join(OPERATION_METRIC_PEAK_COLUMNS)
        + " FROM operation_metric_peaks WHERE server_id = ? AND captured_ts >= ? "
        "AND captured_ts < ? ORDER BY captured_ts DESC, operation_id ASC LIMIT 1",
        (server_id, int(lower), int(before)),
        path,
    )


def operation_metric_peak_successor(
    server_id: str,
    *,
    after: int,
    upper: int,
    path: Optional[Path] = None,
) -> Optional[dict]:
    """Ближайший operation peak справа от логического окна."""
    return _one(
        "SELECT " + ", ".join(OPERATION_METRIC_PEAK_COLUMNS)
        + " FROM operation_metric_peaks WHERE server_id = ? AND captured_ts > ? "
        "AND captured_ts <= ? ORDER BY captured_ts ASC, operation_id ASC LIMIT 1",
        (server_id, int(after), int(upper)),
        path,
    )


def iter_operation_metric_peaks(
    server_id: str,
    since: Optional[int] = None,
    until: Optional[int] = None,
    path: Optional[Path] = None,
) -> list[dict]:
    """Peak snapshots сервера за диапазон, по времени."""
    sql = (
        "SELECT " + ", ".join(OPERATION_METRIC_PEAK_COLUMNS)
        + " FROM operation_metric_peaks WHERE server_id = ?"
    )
    params: list[Any] = [server_id]
    if since is not None:
        sql += " AND captured_ts >= ?"
        params.append(int(since))
    if until is not None:
        sql += " AND captured_ts <= ?"
        params.append(int(until))
    sql += " ORDER BY captured_ts, operation_id"
    rows = _query(sql, params, path)
    if not rows:
        return []
    peaks = {str(row["operation_id"]): row for row in rows}
    for row in peaks.values():
        row["disks"] = []
    operation_ids = list(peaks)
    for start in range(0, len(operation_ids), 900):
        batch = operation_ids[start:start + 900]
        placeholders = ", ".join("?" for _ in batch)
        disks = _query(
            "SELECT " + ", ".join(OPERATION_METRIC_PEAK_DISK_COLUMNS)
            + " FROM operation_metric_peak_disks WHERE operation_id IN ("
            + placeholders + ") ORDER BY operation_id, mount",
            batch,
            path,
        )
        for disk in disks:
            peak = peaks.get(str(disk["operation_id"]))
            if peak is not None:
                peak["disks"].append({
                    column: disk.get(column)
                    for column in OPERATION_METRIC_PEAK_DISK_COLUMNS[1:]
                })
    return rows


def iter_audit(
    since: Optional[int] = None,
    until: Optional[int] = None,
    server_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    action: Optional[str] = None,
    op_id: Optional[str] = None,
    limit: int = 200,
    path: Optional[Path] = None,
) -> list[dict]:
    """Пометки аудита, свежие сверху. Пагинация курсором — на этапе API."""
    sql = f"SELECT {', '.join(AUDIT_COLUMNS)} FROM audit_records WHERE 1=1"
    params: list[Any] = []
    if since is not None:
        sql += " AND ts >= ?"
        params.append(int(since))
    if until is not None:
        sql += " AND ts <= ?"
        params.append(int(until))
    if server_id:
        sql += " AND server_id = ?"
        params.append(server_id)
    if actor_id:
        sql += " AND actor_id = ?"
        params.append(actor_id)
    if action:
        sql += " AND action = ?"
        params.append(action)
    if op_id:
        sql += " AND op_id = ?"
        params.append(op_id)
    sql += " ORDER BY ts DESC, id DESC LIMIT ?"
    params.append(max(1, int(limit)))
    return _query(sql, params, path)


def counts(path: Optional[Path] = None) -> dict:
    """Сколько строк в таблицах (диагностика, пустое состояние в UI)."""
    result = {}
    for table in (
        "metric_samples",
        "metric_disks",
        "metric_hourly",
        "operation_metric_peaks",
        "operation_metric_peak_disks",
        "audit_records",
    ):
        rows = _query(f"SELECT COUNT(*) AS n FROM {table}", (), path)
        result[table] = int(rows[0]["n"]) if rows else 0
    return result


# ------------------------------------------------------------------
# Ретенция
# ------------------------------------------------------------------

def _days_ago(days: int, now: Optional[int] = None) -> int:
    return int(now if now is not None else time.time()) - int(days) * 86400


def prune_metrics(
    *,
    raw_days: int = RAW_METRICS_DAYS,
    hourly_months: int = HOURLY_METRICS_MONTHS,
    now: Optional[int] = None,
    path: Optional[Path] = None,
) -> dict:
    """Обрезать ряды метрик: сырые за ``raw_days``, часовые за ``hourly_months``.

    Идемпотентно: повторный запуск на тех же данных удаляет ноль строк.
    """
    raw_cutoff = _days_ago(raw_days, now)
    hourly_cutoff = _days_ago(hourly_months * 30, now)

    def work(conn: sqlite3.Connection) -> dict:
        samples = conn.execute("DELETE FROM metric_samples WHERE ts < ?", (raw_cutoff,)).rowcount
        disks = conn.execute("DELETE FROM metric_disks WHERE ts < ?", (raw_cutoff,)).rowcount
        peak_disks = conn.execute(
            "DELETE FROM operation_metric_peak_disks WHERE operation_id IN ("
            "SELECT operation_id FROM operation_metric_peaks WHERE captured_ts < ?)",
            (raw_cutoff,),
        ).rowcount
        peaks = conn.execute(
            "DELETE FROM operation_metric_peaks WHERE captured_ts < ?", (raw_cutoff,)
        ).rowcount
        hourly = conn.execute("DELETE FROM metric_hourly WHERE hour_ts < ?", (hourly_cutoff,)).rowcount
        return {
            "metric_samples": max(0, samples),
            "metric_disks": max(0, disks),
            "operation_metric_peaks": max(0, peaks),
            "operation_metric_peak_disks": max(0, peak_disks),
            "metric_hourly": max(0, hourly),
        }

    return _write(
        work,
        {
            "metric_samples": 0,
            "metric_disks": 0,
            "operation_metric_peaks": 0,
            "operation_metric_peak_disks": 0,
            "metric_hourly": 0,
        },
        path,
    )


def prune(now: Optional[int] = None, path: Optional[Path] = None) -> dict:
    """Фоновая обрезка по ретенции. Аудит не трогает — никогда.

    Пометка аудита — сотни байт, и она обязана пережить всё, ради чего её
    писали (§9, §16.2). Объёмные приложения — задача, лог, событие — живут
    в своих хранилищах со своими лимитами и удаляются там, а не здесь:
    каскадное удаление тут означало бы, что разбор инцидента стирает сам
    инцидент.
    """
    result = prune_metrics(now=now, path=path)
    total = sum(result.values())
    if total:
        print(
            f"[{NAME}] Обрезка метрик: "
            + ", ".join(f"{table}={count}" for table, count in result.items()),
            flush=True,
        )
    return result


# ------------------------------------------------------------------
# Резервное копирование
# ------------------------------------------------------------------

def export_consistent(dest: str | Path, path: Optional[Path] = None) -> bool:
    """Консистентная копия живой БД одним запросом (``VACUUM INTO``).

    Копировать ``.db`` вместе с ``-wal`` и ``-shm`` нельзя: получится
    рассогласованный слепок, который «иногда открывается». ``VACUUM INTO``
    (sqlite ≥ 3.27) снимает копию, не останавливая писателей, поэтому один
    и тот же помощник годится и сборочному пути бэкапа (включая защитную
    копию перед восстановлением), и слепку для архива.

    Соединение берётся прямым ``_raw_connect``, а не из кэша
    ``get_connection``: тот заводит БД при отсутствии и уводит повреждённую
    в карантин — со стороны бэкапа оба побочных эффекта недопустимы (копия
    обязана быть копией, а не лечением источника).
    """
    target = Path(dest)
    source = resolved_path(path)
    conn = None
    try:
        if not source.exists():
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        target.unlink(missing_ok=True)
        conn = _raw_connect(source)
        conn.execute("VACUUM INTO ?", (str(target),))
        return True
    except sqlite3.Error as exc:
        print(f"[{NAME}] не удалось снять копию в {target}: {exc}", flush=True)
        return False
    except OSError as exc:
        print(f"[{NAME}] не удалось подготовить {target}: {exc}", flush=True)
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass


def export_audit_snapshot(dest: str | Path, path: Optional[Path] = None) -> bool:
    """Слепок БД: аудит и operation evidence есть, periodic-ряды удалены (§16.1).

    Порядок шагов не случаен. Сначала ``VACUUM INTO`` (см.
    ``export_consistent``) — это и есть снятие копии при активных писателях.
    Затем копия переводится в ``journal_mode=DELETE`` **до** правок: файл
    архива обязан быть самодостаточным, а WAL оставил бы рядом спутник с
    неприменёнными изменениями — и в архив поехало бы состояние до чистки.
    И только потом вырезаются метрики с ``VACUUM``, чтобы файл не остался
    раздутым дырами от удалённых строк.

    ``quick_check`` в конце — не ритуал: слепок уезжает в архив как
    доказательство, и «читаемая копия» из DoD становится свойством кода, а
    не одной удачной проверкой. Нечитаемая копия удаляется: лучше архив без
    аудита с явным замечанием, чем архив с битой БД, которую обнаружат при
    восстановлении.
    """
    target = Path(dest)
    if not export_consistent(target, path):
        return False
    conn = None
    try:
        conn = _raw_connect(target)
        conn.execute("PRAGMA journal_mode=DELETE")
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        # Имена таблиц — из константы модуля, не из данных: параметризовать
        # идентификатор sqlite не умеет.
        for table in METRIC_TABLES:
            if table in tables:
                conn.execute(f"DELETE FROM {table}")
        conn.execute("VACUUM")
        check = conn.execute("PRAGMA quick_check").fetchone()
        readable = check is not None and str(check[0]).lower() == "ok"
    except sqlite3.Error as exc:
        print(f"[{NAME}] слепок {target} не подготовлен: {exc}", flush=True)
        readable = False
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
    if not readable:
        print(f"[{NAME}] слепок {target} не читается — в архив не пойдёт", flush=True)
        target.unlink(missing_ok=True)
    return readable
