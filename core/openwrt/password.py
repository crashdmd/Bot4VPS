"""Root password administration through the gateway's pinned SSH connection."""
from __future__ import annotations

import json
import shlex
import threading

from paramiko import AuthenticationException, SSHException

from core.host_keys import HostKeyMismatchError
from core.openwrt.bootstrap_transaction import drain
from core.openwrt.console import target
from core.ssh import create_ssh_client


_changes: dict[str, threading.Lock] = {}
_read_status = """awk -F: '$1 == "root" { print ($2 == "" ? "unset" : "set"); exit }' /etc/shadow"""
_check_shadow_password = """
import { stdin } from 'fs';
import { cursor } from 'uci';
import { connect } from 'ubus';
let logins = [];
cursor().foreach('rpcd', 'login', s => { if (s.username == 'root') push(logins, s.password); });
if (length(logins) != 1 || logins[0] != '$p$root') exit(2);
let bus = connect();
if (!bus) exit(2);
let password = json(stdin.read('all'));
let session = bus.call('session', 'login', { username: 'root', password, timeout: 1 });
if (!session?.ubus_rpc_session) exit(1);
bus.call('session', 'destroy', { ubus_rpc_session: session.ubus_rpc_session });
"""


def password_configured(ssh) -> bool | None:
    _, stdout, stderr = ssh.exec_command(_read_status, timeout=8)
    output, _, status = drain(stdout, stderr, timeout=8)
    if status == 0:
        return {b"unset": False, b"set": True}.get(output.strip())
    return None


def read(node) -> bool | None:
    if (node['openwrt'].get('ssh') or {}).get('user') != 'root':
        return None
    try:
        with create_ssh_client(target(node)) as ssh:
            return password_configured(ssh)
    except (OSError, ValueError, EOFError, SSHException, HostKeyMismatchError):
        return None


def changing(node_id):
    lock = _changes.get(node_id)
    return bool(lock and lock.locked())


def _run(ssh, command, data=None):
    stdin, stdout, stderr = ssh.exec_command(command, timeout=15)
    if data is not None:
        stdin.write(data)
        stdin.flush()
    stdin.channel.shutdown_write()
    return drain(stdout, stderr, timeout=15)[2]


def _passwd(ssh, password):
    command = 'passwd -d root' if password is None else 'passwd root'
    if _run(ssh, command, None if password is None else f'{password}\n{password}\n') != 0:
        raise ValueError('OpenWrt не принял изменение пароля root')


def _verify_current(ssh, connection, current_password):
    if not current_password:
        raise ValueError('Введите текущий пароль root')
    status = _run(ssh, 'ucode -e ' + shlex.quote(_check_shadow_password), json.dumps(current_password))
    if status == 0:
        return
    if status == 1:
        raise ValueError('Текущий пароль root неверен')
    # A router without a shadow-backed LuCI login can still validate via Dropbear.
    try:
        with create_ssh_client({**connection, 'auth_type': 'password', 'password': current_password}):
            pass
    except AuthenticationException:
        raise ValueError('Текущий пароль root неверен или роутер запретил вход по паролю') from None


def change(node, current_password, password, confirmation):
    from core.storage import commit_server, data_lock, find_server

    if password != confirmation:
        raise ValueError('Пароли не совпадают')
    if not password.strip() or len(password.encode()) > 128 or any(ord(char) < 32 or ord(char) == 127 for char in password):
        raise ValueError('Введите новый пароль до 128 байт без управляющих символов')
    if len(current_password.encode()) > 4096 or '\0' in current_password:
        raise ValueError('Некорректный текущий пароль root')
    connection = target(node)
    if connection.get('user') != 'root':
        raise ValueError('Для смены пароля сначала настройте SSH-доступ под root')
    node_id = node['id']
    lock = _changes.setdefault(node_id, threading.Lock())
    if not lock.acquire(blocking=False):
        raise ValueError('Пароль root уже меняется')

    def current_node():
        current = find_server(node_id)
        if not current or current.get('host') != node['host'] or current.get('node_type') != 'openwrt' or current['openwrt'].get('ssh') != node['openwrt'].get('ssh'):
            raise ValueError('SSH-доступ изменился. Откройте вкладку «Доступ» заново.')
        return current

    try:
        current_node()
        auth_type = connection.get('auth_type', 'password')
        supplied_for_ssh = auth_type == 'password' and bool(current_password)
        try:
            ssh = create_ssh_client({**connection, 'password': current_password} if supplied_for_ssh else connection)
        except AuthenticationException:
            if supplied_for_ssh:
                raise ValueError('Текущий пароль root неверен или роутер запретил вход по паролю') from None
            raise ValueError('Сохранённый SSH-доступ root не работает. Проверьте данные доступа.') from None
        except HostKeyMismatchError as exc:
            raise ValueError(str(exc)) from None
        except (OSError, ValueError, EOFError, SSHException):
            raise ValueError('Сохранённый SSH-доступ root не работает. Проверьте данные доступа.') from None
        with ssh:
            previous = password_configured(ssh)
            if previous is None:
                raise ValueError('Не удалось проверить состояние пароля root на OpenWrt')
            if previous and not supplied_for_ssh:
                _verify_current(ssh, connection, current_password)
            current_node()
            _passwd(ssh, password)
            current = None
            try:
                if auth_type != 'key':
                    with create_ssh_client({**connection, 'auth_type': 'password', 'password': password}):
                        pass
                with data_lock():
                    current = current_node()
                    if auth_type != 'key':
                        current['openwrt']['ssh'].update(auth_type='password', password=password)
                    current['root_password_configured'] = True
                    if not commit_server(current):
                        raise ValueError('Не удалось сохранить реквизиты')
                return current
            except Exception:
                if current is not None:
                    # A write can finish before the audit entry or disk sync fails.
                    try:
                        saved = find_server(node_id)
                        if (saved and saved.get('host') == node['host'] and saved.get('root_password_configured') is True
                                and saved.get('openwrt', {}).get('ssh') == current['openwrt']['ssh']):
                            return saved
                    except (OSError, RuntimeError, ValueError):
                        pass
                if auth_type == 'key':
                    return {**node, 'root_password_configured': True}
                try:
                    _passwd(ssh, current_password if previous else None)
                except Exception:
                    raise ValueError('Пароль на роутере мог измениться. Проверьте вход с новым паролем и сохраните его в SSH-доступе.') from None
                raise ValueError('Не удалось проверить или сохранить новый SSH-пароль. Прежний пароль восстановлен.') from None
    finally:
        lock.release()
