"""Интерактивные SSH PTY-сессии.

Слой Core: не зависит от UI/веба — только paramiko через :func:`core.ssh.create_ssh_client`.
Используется веб-терминалом (WebSocket-мост в ``ui/web/routers/terminal.py``) и может
переиспользоваться любым другим потребителем (CLI, другой UI).

Синхронная (paramiko блокирующая); вызывающий код оборачивает долгие вызовы
(``open``/``recv``/``send``/``resize``) в ``asyncio.to_thread``.

Контракт по смертям сессии:
* ``recv`` различает ``socket.timeout`` (штатно — нет данных) и реальные ошибки
  (``EOFError``/``SSHException``/``OSError``). На фатальной — выставляет ``closed``
  и пробрасывает исключение, чтобы цикл чтения оборвался немедленно.
* ``send`` на дохлом канале тоже выставляет ``closed`` и пробрасывает исключение.
* ``resize`` — не data-path: смерть фиксирует (``closed``), но исключение не рвёт,
  т.к. неудача resize не должна убивать возможно-живую сессию.
"""
from __future__ import annotations

import os
import socket
import time

# Штатное ожидание баннера оболочки после invoke_shell (сбрасываем ниже).
BANNER_WAIT = 0.35


class ShellSession:
    """Одна интерактивная PTY-сессия поверх SSH.

    Каждая сессия владеет собственным SSH-соединением (не делит пул ``/exec``),
    чтобы избежать блокировок и модели «сбор буфера».
    """

    def __init__(
        self,
        server: dict,
        cols: int = 120,
        rows: int = 40,
        connect_timeout: float = 10.0,
        read_timeout: float = 0.2,
    ):
        self.server = server
        self.cols = int(cols)
        self.rows = int(rows)
        self.connect_timeout = connect_timeout
        # таймаут на recv: блокирует до появления данных, но не дольше — позволяет
        # стримить вывод и не виснуть вечно. Параметром — удобно крутить под нагрузку.
        self.read_timeout = read_timeout
        self._ssh = None
        self._chan = None
        self._closed = False
        # staged-скрипт (залит во временный файл для запуска в PTY):
        # путь + имя; чистится идемпотентно при close().
        self._staged = None
        self._staged_name = None

    # ---- lifecycle ----

    def open(self) -> None:
        """Открыть SSH + интерактивный шелл. Поднимает исключение при неудаче."""
        from core.ssh import create_ssh_client

        self._ssh = create_ssh_client(self.server, timeout=self.connect_timeout)
        chan = self._ssh.invoke_shell(width=self.cols, height=self.rows)
        chan.settimeout(self.read_timeout)
        self._chan = chan
        # сбрасываем приветственный баннер оболочки
        time.sleep(BANNER_WAIT)
        try:
            while chan.recv_ready():
                chan.recv(4096)
        except Exception:
            pass

    def close(self) -> None:
        """Закрыть канал и SSH-соединение. Идемпотентно."""
        # пока _ssh ещё жив — убрать staged-скрипт (идемпотентно, no-op если не было)
        self.cleanup_script()
        self._closed = True
        for obj in (self._chan, self._ssh):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        self._chan = None
        self._ssh = None

    @property
    def closed(self) -> bool:
        if self._closed or self._chan is None:
            return True
        return bool(getattr(self._chan, "closed", True))

    # ---- ввод/вывод ----

    def send(self, data: str) -> int:
        """Отправить строку (ввод пользователя) в PTY. Пробрасывает ошибку мёртвого канала."""
        if not self._chan or self._closed:
            raise EOFError("session closed")
        try:
            return self._chan.send(data)
        except Exception:
            self._closed = True  # канал умер — фиксируем и сигнализируем вызывающему
            raise

    def recv(self, n: int = 8192) -> bytes:
        """Прочитать порцию вывода.

        ``socket.timeout`` → ``b''`` (нет данных за ``read_timeout`` — штатно).
        Любая иная ошибка → ``closed=True`` и проброс (сессия умерла).
        """
        if not self._chan or self._closed:
            return b""
        try:
            return self._chan.recv(n)
        except socket.timeout:
            return b""
        except Exception:
            self._closed = True  # EOFError / SSHException / OSError
            raise

    def resize(self, cols: int, rows: int) -> None:
        """Изменить размер PTY (cols×rows). Не рвёт сессию при неудаче."""
        if not self._chan or self._closed:
            return
        try:
            self.cols, self.rows = int(cols), int(rows)
            self._chan.resize_pty(width=self.cols, height=self.rows)
        except Exception:
            # не data-path: фиксируем смерть, но не пробрасываем —
            # неудача resize не должна убивать возможно-живую сессию.
            self._closed = True

    # ---- staged script (заливка скрипта во временный файл для запуска в PTY) ----

    def stage_script(self, script_name: str) -> str:
        """Залить локальный ``scripts/<name>`` во временный файл на сервере,
        сделать ``chmod +x`` и вернуть remote-путь. Запоминает ``self._staged``
        для авто-уборки при :meth:`close`. Поднимает исключение при неудаче
        (mktemp/SFTP/chmod); если temp-файл уже создан, а дальше что-то не вышло —
        удаляет его, чтобы не оставить мусор.

        Синхронная (paramiko блокирующая) — вызывающий код оборачивает в
        ``asyncio.to_thread``, как и ``open``/``send``.
        """
        if not self._ssh:
            raise RuntimeError("session not open")
        # повторный run_script: убрать прежний staged-файл, иначе он утёчёт
        if self._staged:
            self.cleanup_script()
        # уникальный temp-путь (GNU coreutils; суффикс .sh сохраняется).
        _, stdout, _ = self._ssh.exec_command("mktemp /tmp/bot4vps.XXXXXX.sh")
        remote = stdout.read().decode("utf-8", errors="ignore").strip()
        if not remote:
            raise RuntimeError("mktemp вернул пустой путь")
        try:
            local = os.path.join("scripts", script_name)
            with self._ssh.open_sftp() as sftp:
                sftp.put(local, remote)
            _, chmod_out, _ = self._ssh.exec_command(f"chmod +x {remote}")
            if chmod_out.channel.recv_exit_status() != 0:
                raise RuntimeError("chmod +x завершился с ошибкой")
        except Exception:
            # staging не удался — не оставляем temp-файл
            try:
                self._ssh.exec_command(f"rm -f {remote}")
            except Exception:
                pass
            raise
        self._staged = remote
        self._staged_name = script_name
        return remote

    def cleanup_script(self, remote=None) -> None:
        """Идемпотентно удалить staged-скрипт с сервера.

        ``rm -f`` молча игнорирует отсутствие файла (юзер мог сделать ``mv``/``rm``
        во время работы). **Всегда** сбрасывает ``self._staged``/``self._staged_name``
        независимо от результата. Безопасен после :meth:`close` (guard на ``_ssh``).
        """
        path = remote or self._staged
        if path and self._ssh:
            try:
                self._ssh.exec_command(f"rm -f {path}")
            except Exception:
                pass
        self._staged = None
        self._staged_name = None
