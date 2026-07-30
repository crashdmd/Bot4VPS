import os
import asyncio
import shlex
import queue
import threading

from core.storage import find_server
from core.ssh import create_ssh_client
from core.script_utils import load_scripts, get_script_info, read_script, get_script_params


def log(server, text: str):
    if not server:
        print(f"[?] {text}", flush=True)
        return
    name = server.get("name") or server.get("host") or "?"
    print(f"[{name}] {text}", flush=True)


def _run_script_sync(
    script_name: str,
    server: dict,
    values: dict,
    line_queue: queue.Queue,
    cancel_flag: threading.Event,
) -> tuple:
    """
    Синхронное выполнение (вызывать из to_thread).
    Каждую строку кладёт в line_queue.
    В конце: line_queue.put(None)
    Возвращает (exit_code|None, output, error|None, warnings:bool)
    """
    ssh = None
    remote_script = f"/tmp/{script_name}"
    out_lines = []

    def emit(line: str):
        out_lines.append(line)
        try:
            line_queue.put(line)
        except Exception:
            pass

    try:
        if cancel_flag.is_set():
            return None, "", "Отменено", False

        emit("🔌 Подключаемся по SSH...")
        ssh = create_ssh_client(server)
        emit("✅ SSH подключен")

        local_script = os.path.join("scripts", script_name)
        emit("📤 Загружаем скрипт...")
        with ssh.open_sftp() as sftp:
            sftp.put(local_script, remote_script)
        emit("✅ Скрипт загружен")

        _, chmod_stdout, _ = ssh.exec_command(f"chmod +x {remote_script}")
        if chmod_stdout.channel.recv_exit_status() != 0:
            return None, "", "Не удалось сделать скрипт исполняемым.", False

        env = " ".join(
            f"{key}={shlex.quote(str(value))}"
            for key, value in values.items()
        )
        is_root = server.get("user", "").lower() == "root"

        if env:
            command = (
                f"{env} timeout 600 bash {remote_script}"
                if is_root
                else f"sudo -S -p '' env {env} timeout 600 bash {remote_script}"
            )
        else:
            command = (
                f"timeout 600 bash {remote_script}"
                if is_root
                else f"sudo -S -p '' timeout 600 bash {remote_script}"
            )

        emit("🚀 Запускаем скрипт...")
        stdin, stdout, stderr = ssh.exec_command(command)

        if not is_root:
            stdin.write(server.get("password", "") + "\n")
            stdin.flush()
            stdin.channel.shutdown_write()

        emit("⏳ Ожидаем завершения...")

        while True:
            if cancel_flag.is_set():
                try:
                    stdout.channel.close()
                except Exception:
                    pass
                output = "\n".join(out_lines)
                return None, output, "Отменено", False

            line = stdout.readline()
            if not line:
                if stdout.channel.exit_status_ready():
                    break
                continue

            line = line.rstrip("\n\r")
            if line.strip():
                log(server, line)
                emit(line)

        exit_code = stdout.channel.recv_exit_status()
        log(server, f"Скрипт завершён (код {exit_code})")

        err = stderr.read().decode("utf-8", errors="ignore")
        output = "\n".join(out_lines)
        if err.strip():
            output += "\n\nSTDERR:\n" + err.strip()

        if exit_code == 0:
            return 0, output, None, False
        if exit_code == 30:
            return 30, output, None, True
        if exit_code == 124:
            return 124, output, "Таймаут (600с)", False
        return exit_code, output, f"Код выхода {exit_code}", False

    except Exception as e:
        log(server, f"Ошибка: {e}")
        emit(f"❌ Ошибка: {e}")
        return None, "\n".join(out_lines), str(e), False

    finally:
        try:
            line_queue.put(None)  # сигнал конца потока строк
        except Exception:
            pass
        if ssh:
            try:
                ssh.exec_command(f"rm -f {remote_script}")
            except Exception:
                pass
            try:
                ssh.close()
            except Exception:
                pass


async def execute_script(
    script_name: str,
    server_id: str,
    values: dict,
    progress_callback=None,
):
    """Старый API: возвращает строку для UI (обратная совместимость)."""
    from core.task_manager import TaskResult

    result = await execute_script_ex(
        script_name, server_id, values, progress_callback=progress_callback
    )
    server = find_server(server_id)
    name = server["name"] if server else server_id
    output = result.output or "Без вывода"
    lines = output.splitlines()
    if len(lines) > 60:
        output = "...\nВывод обрезан. Показаны последние 60 строк.\n\n" + "\n".join(lines[-60:])

    if result.error == "Отменено":
        return f"⛔ Отменено\n\nСервер: {name}\n\n{output}"
    if result.exit_code == 124:
        return f"⏱ Скрипт прерван по таймауту\n\nСервер: {name}\n\n{output}"
    if result.success and result.warnings:
        return f"⚠️ Выполнено с предупреждениями\n\nСервер: {name}\n\n{output}"
    if result.success:
        return f"✅ Скрипт выполнен успешно\n\nСервер: {name}\n\n{output}"
    return f"❌ Скрипт завершился с ошибкой\n\nСервер: {name}\n\n{result.error or ''}\n\n{output}"


async def execute_script_ex(
    script_name: str,
    server_id: str,
    values: dict,
    progress_callback=None,
    cancel_event=None,
):
    """Структурированный результат. SSH в отдельном потоке — event loop не блокируется."""
    from core.task_manager import TaskResult

    server = find_server(server_id)
    if not server:
        return TaskResult(success=False, error="Сервер не найден.")

    line_queue: queue.Queue = queue.Queue()
    cancel_flag = threading.Event()

    async def watch_cancel():
        if not cancel_event:
            return
        while not cancel_flag.is_set():
            if cancel_event.is_set():
                cancel_flag.set()
                return
            await asyncio.sleep(0.2)

    async def drain_lines():
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, line_queue.get)
            if line is None:
                break
            if progress_callback:
                try:
                    await progress_callback(line)
                except Exception as e:
                    print(f"[SCRIPT] progress cb: {e}", flush=True)

    cancel_task = asyncio.create_task(watch_cancel())
    drain_task = asyncio.create_task(drain_lines())

    try:
        exit_code, output, error, warnings = await asyncio.to_thread(
            _run_script_sync,
            script_name,
            server,
            values or {},
            line_queue,
            cancel_flag,
        )
    finally:
        cancel_flag.set()
        cancel_task.cancel()
        try:
            await drain_task
        except Exception:
            pass

    if error == "Отменено":
        return TaskResult(success=False, output=output, error="Отменено")
    if error and exit_code is None and not warnings:
        return TaskResult(success=False, output=output, error=error)
    if exit_code == 0:
        return TaskResult(success=True, exit_code=0, output=output)
    if exit_code == 30:
        return TaskResult(success=True, exit_code=30, output=output, warnings=True)
    return TaskResult(
        success=False,
        exit_code=exit_code,
        output=output,
        error=error or f"Код выхода {exit_code}",
    )


# --------------------------------------------------
# Task Manager
# --------------------------------------------------

from core.task_manager import Task, task_manager, register_executor, TaskResult


async def _script_executor(payload: dict, task: Task, progress_cb) -> TaskResult:
    return await execute_script_ex(
        script_name=payload["script_name"],
        server_id=task.server_id,
        values=payload.get("values") or {},
        progress_callback=progress_cb,
        cancel_event=task._cancel_event,
    )


register_executor("script", _script_executor)


async def enqueue_script(script_name: str, server_id: str, values=None):
    server = find_server(server_id)
    if not server:
        raise ValueError("Сервер не найден")

    return await task_manager.enqueue(
        name=script_name,
        server_id=server_id,
        server_name=server["name"],
        kind="script",
        payload={
            "script_name": script_name,
            "values": values or {},
        },
    )
