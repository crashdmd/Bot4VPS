import os
import asyncio
import shlex

from core.storage import find_server
from core.ssh import create_ssh_client
from core.script_utils import load_scripts, get_script_info, read_script, get_script_params


def log(server, text: str):
    """Безопасное логирование с именем сервера."""
    if not server:
        print(f"[?] {text}", flush=True)
        return

    name = server.get("name") or server.get("host") or "?"
    print(f"[{name}] {text}", flush=True)


async def execute_script(
    script_name: str,
    server_id: str,
    values: dict,
    progress_callback=None
):
    """Выполняет скрипт на сервере. progress_callback — опционально для live-выводa."""
    server = find_server(server_id)
    if not server:
        return "❌ Сервер не найден."

    ssh = None
    remote_script = f"/tmp/{script_name}"

    try:
        log(server, "Подключаемся по SSH")
        if progress_callback:
            await progress_callback("🔌 Подключаемся по SSH...")

        ssh = create_ssh_client(server)
        log(server, "SSH подключен")
        if progress_callback:
            await progress_callback("✅ SSH подключен")

        local_script = os.path.join("scripts", script_name)

        log(server, "Загружаем скрипт")
        if progress_callback:
            await progress_callback("📤 Загружаем скрипт...")

        with ssh.open_sftp() as sftp:
            sftp.put(local_script, remote_script)

        log(server, "Скрипт загружен")
        if progress_callback:
            await progress_callback("✅ Скрипт загружен")

        log(server, "Делаем скрипт исполняемым")
        if progress_callback:
            await progress_callback("🔧 Делаем скрипт исполняемым...")

        _, chmod_stdout, _ = ssh.exec_command(f"chmod +x {remote_script}")
        if chmod_stdout.channel.recv_exit_status() != 0:
            raise RuntimeError("Не удалось сделать скрипт исполняемым.")

        # Формируем переменные окружения
        env = " ".join(
            f"{key}={shlex.quote(str(value))}"
            for key, value in values.items()
        )

        is_root = server.get("user", "").lower() == "root"

        if env:
            if is_root:
                command = f"{env} timeout 600 bash {remote_script}"
            else:
                command = f"sudo -S -p '' env {env} timeout 600 bash {remote_script}"
        else:
            if is_root:
                command = f"timeout 600 bash {remote_script}"
            else:
                command = f"sudo -S -p '' timeout 600 bash {remote_script}"

        log(server, "Запускаем скрипт")
        if progress_callback:
            await progress_callback("🚀 Запускаем скрипт...")

        stdin, stdout, stderr = ssh.exec_command(command)

        if not is_root:
            stdin.write(server.get("password", "") + "\n")
            stdin.flush()
            stdin.channel.shutdown_write()

        log(server, "Команда отправлена")
        if progress_callback:
            await progress_callback("📡 Команда отправлена")

        log(server, "Ожидаем завершения...")
        if progress_callback:
            await progress_callback("⏳ Ожидаем завершения...")

        out_lines = []
        while True:
            line = stdout.readline()
            if not line:
                if stdout.channel.exit_status_ready():
                    break
                continue

            line = line.rstrip("\n\r")
            if line.strip():
                log(server, line)
                if progress_callback:
                    try:
                        await progress_callback(line)
                    except Exception as e:
                        log(server, f"Callback error: {e}")
            out_lines.append(line + "\n")

        exit_code = stdout.channel.recv_exit_status()
        log(server, f"Скрипт завершён (код {exit_code})")

        out = "".join(out_lines)
        err = stderr.read().decode("utf-8", errors="ignore")

        output = out.strip()
        if err.strip():
            output += "\n\nSTDERR:\n" + err.strip()

        # Обрезка
        lines = output.splitlines()
        if len(lines) > 60:
            output = "...\nВывод обрезан. Показаны последние 60 строк.\n\n" + "\n".join(lines[-60:])

        if exit_code == 124:
            return f"⏱ Скрипт прерван по таймауту\n\nСервер: {server['name']}\n\n{output or 'Без вывода'}"
        elif exit_code == 0:
            return f"✅ Скрипт выполнен успешно\n\nСервер: {server['name']}\n\n{output or 'Без вывода'}"
        elif exit_code == 30:
            return f"⚠️ Выполнено с предупреждениями\n\nСервер: {server['name']}\n\n{output or 'Без вывода'}"
        else:
            return f"❌ Скрипт завершился с ошибкой (код {exit_code})\n\nСервер: {server['name']}\n\n{output or 'Без вывода'}"

    except Exception as e:
        log(server, f"Ошибка: {e}")
        if progress_callback:
            await progress_callback(f"❌ Ошибка: {e}")
        return f"❌ Ошибка выполнения скрипта\n\n{e}"

    finally:
        if ssh:
            try:
                ssh.exec_command(f"rm -f {remote_script}")
            except Exception:
                pass
            try:
                ssh.close()
            except Exception:
                pass