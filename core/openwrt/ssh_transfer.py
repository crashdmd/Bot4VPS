"""Binary SSH upload into an existing signed, prepared router operation."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
from pathlib import Path
import re
import shlex
import time

from paramiko import SSHException


class SshUnavailable(OSError):
    """Only transport failures permit falling back to the constrained API."""


def connect_root(node):
    from core.openwrt.console import target
    from core.ssh import create_ssh_client
    config = node.get('openwrt', {}).get('ssh') or {}
    if config.get('user') != 'root' or not config.get('host_key'):
        return None
    ssh = None
    try:
        ssh = create_ssh_client(target(node))
        _, out, err = ssh.exec_command('id -u', timeout=8)
        uid = out.read(64).strip()
        if out.channel.recv_exit_status() != 0 or uid != b'0':
            ssh.close()
            return None
        return ssh
    except Exception:
        if ssh is not None:
            ssh.close()
        return None


_RECEIVER = Path(__file__).with_name('assets') / 'ssh-upload.uc'


def upload(ssh, username, nonce, name, data, report):
    """No SFTP subsystem or bash required; the receiver verifies before READY."""
    if not re.fullmatch(r'bot4vps_[a-f0-9]+', username) or not re.fullmatch(r'[a-f0-9]{32}', nonce):
        raise ValueError('Некорректная операция передачи')
    if not re.fullmatch(r'[a-zA-Z0-9_.+~-]+', name) or name in ('.', '..'):
        raise ValueError('Некорректное имя файла')
    total = len(data) if isinstance(data, bytes) else data.stat().st_size
    if not 0 < total <= 128 * 1024 * 1024:
        raise ValueError('Размер файла превышает лимит операции')
    digest = hashlib.sha256(data).hexdigest() if isinstance(data, bytes) else data.name
    if not re.fullmatch(r'[a-f0-9]{64}', digest):
        # Used by callers with a normal path, not just the content-addressed store.
        with data.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
    command = 'ucode -e ' + shlex.quote(_RECEIVER.read_text()) + ' -- ' + ' '.join(
        shlex.quote(str(value)) for value in (username, nonce, name, total, digest))
    channel = None
    try:
        stdin, stdout, stderr = ssh.exec_command(command, timeout=60)
        channel = stdout.channel
        ready = stdout.readline(64)
        if ready not in (b'READY\n', 'READY\n'):
            error = stderr.read(4096).decode(errors='replace').strip()
            if not ready and channel.recv_exit_status() == -1:
                raise SshUnavailable('Соединение root SSH прервалось до передачи')
            raise ValueError('Получатель SSH не подтвердил передачу: ' + error)
        done = 0
        started = time.monotonic()
        last_report = started
        source = io.BytesIO(data) if isinstance(data, bytes) else data.open('rb')
        with source:
            while True:
                try:
                    chunk = source.read(256 * 1024)
                except OSError as exc:
                    raise ValueError('Не удалось прочитать локальный комплект') from exc
                if not chunk:
                    break
                channel.sendall(chunk)
                done += len(chunk)
                now = time.monotonic()
                if now - last_report >= 1 or done == total:
                    report(done, total, done / 1024**2 / max(now - started, .001))
                    last_report = now
        channel.shutdown_write()
        reply = stdout.read(4096)
        error = stderr.read(4096)
        code = channel.recv_exit_status()
        if code == -1:
            raise SshUnavailable('Соединение root SSH прервалось до проверки файла')
        if code != 0:
            raise ValueError('Передача SSH отклонена: ' + error.decode(errors='replace').strip())
        result = json.loads(reply)
        if not result.get('ok') or result.get('sha256') != digest or result.get('size') != total:
            raise ValueError('Контрольная сумма переданного файла не совпала')
        return result
    except (OSError, EOFError, SSHException) as exc:
        raise SshUnavailable('Соединение root SSH прервалось') from exc
    finally:
        if channel is not None:
            channel.close()


async def upload_async(ssh, username, nonce, name, data, progress):
    loop = asyncio.get_running_loop()
    def report(done, total, speed):
        asyncio.run_coroutine_threadsafe(progress(
            f'Передаю по root SSH {name}: {done / 1024**2:.1f} / {total / 1024**2:.1f} МБ · {speed:.1f} МБ/с'), loop).result()
    await asyncio.to_thread(upload, ssh, username, nonce, name, data, report)
