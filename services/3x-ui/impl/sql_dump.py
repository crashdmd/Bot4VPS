"""SQL-дамп → отдельная база без команд CLI и доступа к другим файлам.

Обработка в процессе с лимитами памяти/CPU/файла совместима с Python 3.10.
"""
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time

MAX_DATABASE_BYTES = 64 * 1024 * 1024
MAX_VALUE_BYTES = 5 * 1024 * 1024
MAX_SECONDS = 10
SAFE_PRAGMAS = {"foreign_keys", "defer_foreign_keys", "user_version", "application_id", "encoding"}


def _worker(input_path: str, database_path: str) -> int:
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (MAX_SECONDS, MAX_SECONDS + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_DATABASE_BYTES, MAX_DATABASE_BYTES))
    denied = []
    connection = sqlite3.connect(database_path)
    try:
        text = Path(input_path).read_bytes().decode("utf-8-sig")
        connection.execute("PRAGMA page_size=4096")
        connection.execute(f"PRAGMA max_page_count={MAX_DATABASE_BYTES // 4096}")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.enable_load_extension(False)
        if hasattr(connection, "setlimit"):
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_VALUE_BYTES)
            connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, MAX_VALUE_BYTES)

        def authorize(action, first, second, database, trigger):
            forbidden = action in {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH,
                                   sqlite3.SQLITE_CREATE_VTABLE, sqlite3.SQLITE_DROP_VTABLE}
            if action == sqlite3.SQLITE_FUNCTION and (second or "").lower() in {
                "load_extension", "readfile", "writefile",
            }:
                forbidden = True
            if action == sqlite3.SQLITE_PRAGMA and (first or "").lower() not in SAFE_PRAGMAS:
                forbidden = True
            if database not in {None, "main"}:
                forbidden = True
            if forbidden:
                denied.append(True)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)
        connection.executescript(text)
        if connection.in_transaction:
            return 13
        connection.set_authorizer(None)
        if not connection.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone():
            return 14
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            return 15
        return 0
    except UnicodeDecodeError:
        return 10
    except (sqlite3.Error, ValueError):
        return 11 if denied else 12
    except MemoryError:
        return 16
    finally:
        connection.close()


def restore_sql_dump(data: bytes) -> bytes:
    from core.cancel_flags import current
    from core.db_import_uploads import upload_directory
    from core.integrator import OperationCancelled, StepError

    def fail(detail):
        raise StepError("db_dump_restore", -1, title="Импорт дампа SQLite", detail=detail)

    if len(data) > MAX_VALUE_BYTES:
        fail("Размер дампа превышает 5 МБ.")
    cancel_flag = current()
    if cancel_flag is not None and cancel_flag.is_set():
        raise OperationCancelled()
    directory = upload_directory()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="xui-sql-", dir=directory) as temporary:
        source, database = Path(temporary) / "input.dump", Path(temporary) / "restored.db"
        source.write_bytes(data)
        source.chmod(0o600)
        process = subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve()),
                                    str(source.resolve()), str(database.resolve())],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + MAX_SECONDS
        try:
            while process.poll() is None:
                if cancel_flag is not None and cancel_flag.is_set():
                    raise OperationCancelled()
                if time.monotonic() >= deadline:
                    fail("Обработка дампа превысила допустимое время. Загрузите файл базы .db.")
                try:
                    process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
        if cancel_flag is not None and cancel_flag.is_set():
            raise OperationCancelled()
        errors = {
            10: "Дамп должен содержать SQL в кодировке UTF-8.",
            11: "Дамп содержит недопустимые операции. Разрешён только SQL восстановления базы без доступа к внешним файлам.",
            12: "Не удалось восстановить SQL-дамп. Команды SQLite CLI (например .shell и .read) не поддерживаются. Проверьте SQL и лимит базы 64 МБ.",
            13: "В дампе не завершена транзакция.",
            14: "Дамп не содержит таблиц или других объектов базы.",
            15: "Восстановленная база не прошла integrity_check.",
        }
        if process.returncode != 0:
            fail(errors.get(process.returncode, "Обработка дампа остановлена: превышен лимит ресурсов или произошла ошибка SQLite. Загрузите файл базы .db."))
        if database.stat().st_size > MAX_DATABASE_BYTES:
            fail("Восстановленная база превышает 64 МБ.")
        return database.read_bytes()


if __name__ == "__main__":
    raise SystemExit(_worker(sys.argv[1], sys.argv[2]))
