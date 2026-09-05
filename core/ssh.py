import os
import re
import shlex
import threading
import time
from typing import Callable, Optional, Sequence, Tuple

import paramiko


class BinaryStreamCancelled(Exception):
    """Поток удалённой команды прерван до публикации результата."""


def create_ssh_client(server, timeout=8):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    auth_type = server.get("auth_type", "password")
    if auth_type == "key":
        ssh.connect(
            hostname=server["host"], port=server.get("port", 22),
            username=server["user"], key_filename=server["key_path"], timeout=timeout,
        )
    else:
        ssh.connect(
            hostname=server["host"], port=server.get("port", 22),
            username=server["user"], password=server["password"], timeout=timeout,
        )
    return ssh


def get_available_keys():
    return [f for f in os.listdir("/opt/bot4vps/keys") if not f.endswith(".pub")]


def test_connection(server):
    try:
        ssh = create_ssh_client(server)
        ssh.close()
        return True, "OK"
    except Exception as e:
        return False, str(e)


def _sudo_argv(server, argv: Sequence[str]) -> str:
    """Собрать shell wrapper только из безопасно quoted argv."""
    if not argv or any("\x00" in str(value) for value in argv):
        raise ValueError("Некорректный binary command argv")
    command = shlex.join([str(value) for value in argv])
    wrapped = f"bash -c {shlex.quote(command)}"
    if (server.get("user", "") or "").lower() != "root":
        wrapped = f"sudo -S -p '' {wrapped}"
    return wrapped


def exec_binary_stream(
    ssh,
    server,
    argv: Sequence[str],
    on_stdout: Callable[[bytes], None],
    *,
    timeout: float = 600,
    is_cancelled: Callable[[], bool] | None = None,
) -> tuple[int, bytes]:
    """Выполнить command и передать stdout неизменёнными binary chunks.

    stderr дренируется параллельно, чтобы он не заполнил SSH channel. stdout
    никогда не декодируется; stderr ограничен безопасным диагностическим буфером.
    """
    stdin, stdout, stderr = ssh.exec_command(_sudo_argv(server, argv), timeout=timeout)
    is_root = (server.get("user", "") or "").lower() == "root"
    if not is_root:
        stdin.write((server.get("password", "") or "") + "\n")
        stdin.flush()
        stdin.channel.shutdown_write()
    channel = stdout.channel
    stderr_chunks: list[bytes] = []
    stderr_size = 0
    stderr_limit = 1024 * 1024
    stderr_done = threading.Event()

    def drain_stderr() -> None:
        nonlocal stderr_size
        try:
            while True:
                if channel.recv_stderr_ready():
                    chunk = channel.recv_stderr(65536)
                    if chunk and stderr_size < stderr_limit:
                        piece = chunk[: stderr_limit - stderr_size]
                        stderr_chunks.append(piece)
                        stderr_size += len(piece)
                    continue
                if channel.exit_status_ready():
                    while channel.recv_stderr_ready():
                        chunk = channel.recv_stderr(65536)
                        if not chunk:
                            break
                        if stderr_size < stderr_limit:
                            piece = chunk[: stderr_limit - stderr_size]
                            stderr_chunks.append(piece)
                            stderr_size += len(piece)
                    return
                time.sleep(0.01)
        finally:
            stderr_done.set()

    stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
    stderr_thread.start()
    started = time.monotonic()
    try:
        while True:
            if is_cancelled and is_cancelled():
                channel.close()
                raise BinaryStreamCancelled()
            if time.monotonic() - started > timeout:
                channel.close()
                raise TimeoutError("SSH binary stream timeout")
            if channel.recv_ready():
                chunk = channel.recv(1024 * 1024)
                if chunk:
                    on_stdout(chunk)
                continue
            if channel.exit_status_ready():
                while channel.recv_ready():
                    chunk = channel.recv(1024 * 1024)
                    if chunk:
                        on_stdout(chunk)
                stderr_done.wait(timeout=2.0)
                return channel.recv_exit_status(), b"".join(stderr_chunks)
            time.sleep(0.01)
    except BaseException:
        channel.close()
        raise
    finally:
        stderr_done.wait(timeout=2.0)


def _mentions_option(text: str, option: str) -> bool:
    """Найти упоминание опции целиком, а не подстроку внутри другой опции.

    Без границ ``--overwrite`` совпало бы с ``--overwrite-dir``, а ``-p`` —
    с любым ``--no-same-permissions``.
    """
    pattern = rf"(?<![\w-]){re.escape(option)}(?![\w-])"
    return re.search(pattern, text) is not None


def detect_tar_capability(ssh, server) -> dict:
    """Явно определить GNU tar или BusyBox tar и требуемые streaming options."""
    version_code, version_out, version_err = exec_sudo(ssh, server, "tar --version", timeout=20)
    help_code, help_out, help_err = exec_sudo(ssh, server, "tar --help", timeout=20)
    text = "\n".join((version_out, version_err, help_out, help_err))
    lowered = text.lower()
    if "gnu tar" in lowered:
        implementation = "gnu"
    elif "busybox" in lowered and "tar" in lowered:
        implementation = "busybox"
    else:
        implementation = "unknown"
    supports = {
        "gzip": "-z" in lowered or "--gzip" in lowered,
        "change_dir": "-C" in text or "--directory" in lowered,
        "exclude": "--exclude" in lowered or "exclude=" in lowered,
    }
    # Отдельное поле: опции нужны только распаковке. Подмешивать их в supports
    # нельзя — usable = all(supports.values()) проверяется перед созданием
    # ЛЮБОГО серверного backup, и любой недетект отнял бы у сервера бэкапы.
    restore_supports = {
        "overwrite": _mentions_option(lowered, "--overwrite"),
        "numeric_owner": _mentions_option(lowered, "--numeric-owner"),
        "strip_components": _mentions_option(lowered, "--strip-components"),
        "preserve_permissions": (
            _mentions_option(text, "-p")
            or _mentions_option(lowered, "--preserve-permissions")
            or _mentions_option(lowered, "--same-permissions")
        ),
        "null": _mentions_option(lowered, "--null"),
        "verbatim_files_from": _mentions_option(
            lowered,
            "--verbatim-files-from",
        ),
        "files_from": (
            _mentions_option(text, "-T")
            or _mentions_option(lowered, "--files-from")
        ),
        "no_recursion": _mentions_option(lowered, "--no-recursion"),
    }
    if version_code != 0 or help_code != 0:
        supports = {key: False for key in supports}
        restore_supports = {key: False for key in restore_supports}
    return {
        "implementation": implementation,
        "version_exit_code": version_code,
        "help_exit_code": help_code,
        "supports": supports,
        "restore_supports": restore_supports,
        "usable": implementation in {"gnu", "busybox"} and all(supports.values()),
    }


# Диагностика, которая НЕ означает, что source прочитан неполно по нашей вине:
# файл исчез или изменился под нами, специальный файл пропущен, имена
# нормализованы. На живой системе такие строки — норма, и считать их провалом
# значит запретить бэкап любого работающего сервера.
_TAR_BENIGN_PATTERNS = (
    r"socket ignored",
    r"file changed as we read it",
    r"file removed before we read it",
    r"removing leading .* from (member names|hard link targets)",
    r"unknown file type.*ignored",
    r"file is on a different filesystem",
)

# Диагностика, после которой архив источника заведомо неполон. Эти строки —
# провал независимо от кода возврата: GNU tar сообщает о них и завершается с 2,
# но полагаться только на код нельзя, а молча опубликовать урезанный source
# нельзя тем более.
_TAR_FAILURE_PATTERNS = (
    r"permission denied",
    r"cannot open",
    r"cannot read",
    r"cannot stat",
    r"cannot write",
    r"cannot add",
    r"can't open",
    r"can't stat",
    r"input/output error",
    r"read error",
    r"short read",
    r"unexpected eof",
    r"error is not recoverable",
    r"error exit delayed",
    r"exiting with failure status",
)

_TAR_DIAGNOSTIC_LINE_LIMIT = 20
_TAR_DIAGNOSTIC_LINE_CHARS = 512


def _tar_diagnostic_lines(diagnostics) -> list[str]:
    """Строки stderr в пригодном для хранения виде: без дублей и control chars.

    Диагностика попадает в warnings/error операции, а там запрещены управляющие
    символы и длина ограничена, поэтому чистка делается здесь, один раз.
    """
    if isinstance(diagnostics, (bytes, bytearray)):
        text = bytes(diagnostics).decode("utf-8", errors="replace")
    else:
        text = str(diagnostics or "")
    lines: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = "".join(char if char >= " " else " " for char in raw).strip()
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line[:_TAR_DIAGNOSTIC_LINE_CHARS])
    return lines


def _matches_any(line: str, patterns: Sequence[str]) -> bool:
    lowered = line.lower()
    return any(re.search(pattern, lowered) is not None for pattern in patterns)


def classify_tar_stream(
    exit_code: int,
    diagnostics,
    *,
    implementation: str = "gnu",
) -> dict:
    """Развести диагностику потокового tar на предупреждения и провалы.

    Прежняя проверка «любой stderr — провал» неверна в обе стороны: она валит
    бэкап живого сервера из-за исчезнувшего временного файла и при этом ничего
    не говорит о том, что именно случилось. Разбор идёт по коду возврата и по
    самим строкам:

    * GNU tar: 0 — успех, 1 — «часть файлов изменилась под нами» (само по себе
      не провал, но нераспознанная строка при непустом коде трактуется как
      провал), 2 — фатальная ошибка;
    * BusyBox tar: свой набор сообщений и никакого разделения 1/2, поэтому любой
      ненулевой код считается провалом;
    * строки из :data:`_TAR_FAILURE_PATTERNS` — провал при любом коде возврата:
      неполный source нельзя опубликовать как полный.

    Возвращает ``{"ok", "exit_code", "warnings", "failures"}``; списки уже
    пригодны для warnings операции.
    """
    lines = _tar_diagnostic_lines(diagnostics)
    code = int(exit_code)
    warnings: list[str] = []
    failures: list[str] = []
    unknown: list[str] = []
    for line in lines:
        # Явный allowlist проверяется первым: у безобидных сообщений своя
        # формулировка, и подводить их под общие слова об ошибках незачем.
        if _matches_any(line, _TAR_BENIGN_PATTERNS):
            warnings.append(line)
        elif _matches_any(line, _TAR_FAILURE_PATTERNS):
            failures.append(line)
        else:
            unknown.append(line)
    if code == 0:
        # Успешный код возврата: нераспознанная болтовня tar/gzip — не повод
        # выбрасывать уже полученный архив источника.
        warnings.extend(unknown)
    else:
        failures.extend(unknown)
        if not failures and not (implementation == "gnu" and code == 1):
            # GNU 1 без нераспознанных строк — это ровно «файлы менялись под
            # нами», уже разобранное выше. Любой другой ненулевой код без
            # понятной диагностики трактуется как провал: догадываться о
            # причине на стороне клиента нечем.
            failures.append(f"tar завершился с кодом {code} без диагностики")
    return {
        "ok": not failures,
        "exit_code": code,
        "warnings": warnings[:_TAR_DIAGNOSTIC_LINE_LIMIT],
        "failures": failures[:_TAR_DIAGNOSTIC_LINE_LIMIT],
    }


def _exec_remote(
    ssh,
    full_command: str,
    timeout: int,
    emit: Optional[Callable[[str], None]] = None,
    stdin_data: Optional[str] = None,
) -> Tuple[int, str, str]:
    """Общий прогон команды: чтение stdout/stderr и exit status."""
    stdin, stdout, stderr = ssh.exec_command(full_command, timeout=timeout)
    if stdin_data is not None:
        stdin.write(stdin_data)
        stdin.flush()
        stdin.channel.shutdown_write()
    out_lines = []
    chan = stdout.channel
    while True:
        line = stdout.readline()
        if not line:
            if chan.exit_status_ready():
                break
            continue
        line = line.rstrip("\r\n")
        if line:
            out_lines.append(line)
            if emit:
                try:
                    emit(line)
                except Exception:
                    pass
    exit_code = chan.recv_exit_status()
    err = stderr.read().decode("utf-8", errors="ignore")
    return exit_code, "\n".join(out_lines), err


def exec_sudo(
    ssh,
    server,
    command: str,
    emit: Optional[Callable[[str], None]] = None,
    timeout: int = 600,
) -> Tuple[int, str, str]:
    """Выполнить текстовую команду на SSH с учётом sudo для не-root."""
    is_root = (server.get("user", "") or "").lower() == "root"
    quoted = shlex.quote(command)
    full = f"bash -c {quoted}" if is_root else f"sudo -S -p '' bash -c {quoted}"
    stdin_data = None if is_root else (server.get("password", "") or "") + "\n"
    return _exec_remote(ssh, full, timeout, emit=emit, stdin_data=stdin_data)


def exec_plain(
    ssh,
    server,
    command: str,
    emit: Optional[Callable[[str], None]] = None,
    timeout: int = 600,
) -> Tuple[int, str, str]:
    """Выполнить команду без sudo — операции с собственными файлами пользователя.

    server не используется и оставлен для совместимости сигнатуры с exec_sudo
    (условный выбор исполнителя: sudo подтверждён → exec_sudo, иначе → здесь).
    """
    return _exec_remote(ssh, f"bash -c {shlex.quote(command)}", timeout, emit=emit)
