"""Prepare every WG change before writing; restore all files after any failure."""
from __future__ import annotations

import ipaddress
import re
import shlex
import uuid

from core.cancel_flags import recovery_scope
from core.integrator import StepError
from core.ssh import exec_binary_stream, exec_sudo, private_remote_upload
from .validation import validate_profile_name

ROOT = '/etc/wireguard'


def run(ssh, server, command, step='configuration', title='Изменение конфигурации WireGuard'):
    code, out, err = exec_sudo(ssh, server, command)
    if code != 0:
        raise StepError(step, code, title=title, detail=err[:500] or 'Сервер не подтвердил выполнение команды')
    return out.strip()


def read_files(ssh, server):
    names = run(ssh, server,
        "for d in /etc/wireguard/clients /etc/wireguard/peers /etc/wireguard/peers.disabled; do "
        '[ -d "$d" ] || continue; find "$d" -maxdepth 1 -name "*.conf" -print || exit $?; done',
        title='Проверка полного списка конфигураций')
    paths = [ROOT + '/wg0.conf']
    for path in names.splitlines():
        if path.rsplit('/', 1)[0] not in {ROOT + '/clients', ROOT + '/peers', ROOT + '/peers.disabled'}:
            raise StepError('configuration_path', -1, detail='Сервер вернул неожиданный путь конфигурации')
        validate_profile_name(path.rsplit('/', 1)[1][:-5])
        paths.append(path)
    files = {}
    for path in sorted(set(paths)):
        run(ssh, server, f'test -f {shlex.quote(path)} && test ! -L {shlex.quote(path)}',
            title='Проверка файла конфигурации')
        chunks = []
        size = 0
        def receive(chunk):
            nonlocal size
            size += len(chunk)
            if size > 1024 * 1024:
                raise StepError('configuration_size', -1, detail='Файл конфигурации превышает 1 МБ')
            chunks.append(chunk)
        code, err = exec_binary_stream(ssh, server, ['cat', '--', path], receive, timeout=30)
        if code != 0:
            raise StepError('configuration_read', code, title='Чтение всех конфигураций',
                            detail=err.decode('utf-8', errors='replace')[:500] or 'Не удалось прочитать конфигурацию')
        raw = b''.join(chunks)
        try:
            if not raw: raise ValueError()
            raw.decode('utf-8')
        except (ValueError, UnicodeDecodeError):
            raise StepError('configuration_read', -1, detail='Пустой или некорректный файл конфигурации') from None
        files[path] = raw
    return files


def value(text, key):
    for line in text.splitlines():
        head, sep, tail = line.partition('=')
        if sep and head.strip().lower() == key.lower():
            return tail.strip()
    return None


def replace(text, key, replacement):
    lines = text.splitlines()
    found = False
    for index, line in enumerate(lines):
        head, sep, _tail = line.partition('=')
        if sep and head.strip().lower() == key.lower():
            lines[index] = f'{key} = {replacement}'
            found = True
    if not found:
        position = next((i for i, line in enumerate(lines) if line.strip().lower() == '[peer]'), len(lines))
        lines.insert(position, f'{key} = {replacement}')
    return '\n'.join(lines) + '\n'


def prepare(files, *, endpoint=None, port=None, address=None, dns=None):
    original = files[ROOT + '/wg0.conf'].decode('utf-8')
    listen_port = str(port or value(original, 'ListenPort') or '')
    if (endpoint or port is not None) and (not listen_port.isdigit() or not 1 <= int(listen_port) <= 65535):
        raise StepError('configuration_port', -1, detail='В wg0.conf не указан корректный ListenPort')
    old_network = new_network = None
    if address is not None:
        try:
            old = ipaddress.ip_interface(value(original, 'Address'))
            new = ipaddress.ip_interface(address)
            if old.version != new.version: raise ValueError()
            old_network, new_network = old.network, new.network
        except (ValueError, TypeError):
            raise StepError('configuration_address', -1, detail='Нельзя согласованно перенести адреса между указанными подсетями') from None
    def map_addresses(raw):
        result = []
        for item in raw.split(','):
            try:
                iface = ipaddress.ip_interface(item.strip())
            except ValueError:
                raise StepError('configuration_address', -1, detail='В конфигурации найден некорректный адрес') from None
            ip = iface.ip
            if old_network is not None and ip.version == old_network.version and ip in old_network:
                offset = int(ip) - int(old_network.network_address)
                if offset >= new_network.num_addresses:
                    raise StepError('configuration_address', -1, detail='Новая подсеть не вмещает все существующие адреса клиентов. Выберите более широкую подсеть.')
                ip = ipaddress.ip_address(int(new_network.network_address) + offset)
            result.append(f'{ip}/{iface.network.prefixlen}')
        return ', '.join(result)
    changes = {}
    for path, raw in files.items():
        text = raw.decode('utf-8')
        if path == ROOT + '/wg0.conf':
            if port is not None: text = replace(text, 'ListenPort', str(port))
            if address is not None: text = replace(text, 'Address', address)
        is_client = path.startswith(ROOT + '/clients/')
        if is_client:
            if endpoint:
                text = replace(text, 'Endpoint', endpoint + ':' + listen_port)
            elif port is not None:
                previous = value(text, 'Endpoint')
                match = re.fullmatch(r'(.+):[0-9]+', previous or '')
                if not match:
                    raise StepError('configuration_endpoint', -1, detail='В одном из клиентских профилей нет корректного Endpoint')
                text = replace(text, 'Endpoint', match.group(1) + ':' + listen_port)
            if dns is not None: text = replace(text, 'DNS', dns)
        if address is not None:
            mapped_lines = []
            for line in text.splitlines():
                head, sep, tail = line.partition('=')
                key = head.strip().lower()
                if sep and (key == 'allowedips' and not is_client or key == 'address' and is_client):
                    line = head.rstrip() + ' = ' + map_addresses(tail)
                mapped_lines.append(line)
            text = '\n'.join(mapped_lines) + '\n'
        changed = text.encode('utf-8')
        if changed != raw:
            changes[path] = changed
    return changes


def verify_live(ssh, server, files, changes):
    wanted = {**files, **changes}
    main = wanted[ROOT + '/wg0.conf'].decode()
    run(ssh, server, 'systemctl is-active --quiet wg-quick@wg0 && wg show wg0 >/dev/null', title='Подтверждение работающего интерфейса')
    if run(ssh, server, 'wg show wg0 listen-port') != value(main, 'ListenPort'):
        raise StepError('configuration_live', -1, detail='Работающий интерфейс не подтвердил новый порт')
    addresses = run(ssh, server, 'ip -o addr show dev wg0')
    for item in (value(main, 'Address') or '').split(','):
        wanted_address = str(ipaddress.ip_interface(item.strip()))
        if wanted_address not in addresses.split():
            raise StepError('configuration_live', -1, detail='Работающий интерфейс не подтвердил новый адрес')
    peers = {}
    for line in run(ssh, server, 'wg show wg0 allowed-ips').splitlines():
        fields = line.split()
        if fields:
            items = ' '.join(fields[1:]).replace(',', ' ').split()
            peers[fields[0]] = {str(ipaddress.ip_network(item, strict=False)) for item in items if item != '(none)'}
    for path, raw in wanted.items():
        if not path.startswith(ROOT + '/peers/'):
            continue
        text = raw.decode()
        public = value(text, 'PublicKey')
        allowed = {str(ipaddress.ip_network(item.strip(), strict=False)) for item in (value(text, 'AllowedIPs') or '').split(',') if item.strip()}
        if not public or peers.get(public) != allowed:
            raise StepError('configuration_live', -1, detail='Не все активные пиры подтвердили новую конфигурацию')
    for path, raw in wanted.items():
        if path.startswith(ROOT + '/peers.disabled/') and value(raw.decode(), 'PublicKey') in peers:
            raise StepError('configuration_live', -1, detail='Отключённый пир остался в работающем интерфейсе')
    preshared = {value(raw.decode(), 'PublicKey'): value(raw.decode(), 'PresharedKey')
                 for path, raw in wanted.items() if path.startswith(ROOT + '/peers/') and value(raw.decode(), 'PresharedKey')}
    if preshared:
        live_keys = dict(line.split()[:2] for line in run(ssh, server, 'wg show wg0 preshared-keys').splitlines() if len(line.split()) >= 2)
        if any(live_keys.get(public) != key for public, key in preshared.items()):
            raise StepError('configuration_live', -1, detail='Не все активные пиры подтвердили PresharedKey')


def apply(ssh, server, files, changes, *, restart=False, publish=lambda: None):
    if not changes:
        publish()
        return 0
    attempt = ROOT + '/.bot4vps-config-' + uuid.uuid4().hex
    previous_state = None
    if restart:
        previous_state = run(ssh, server, 'systemctl show wg-quick@wg0 -p ActiveState --value')
        if previous_state not in {'active', 'inactive', 'failed'}:
            raise StepError('configuration_state', -1, detail='Не удалось определить стабильное состояние WireGuard')
    run(ssh, server, f'install -d -m 700 {shlex.quote(attempt)}', title='Защитная копия всех изменяемых конфигураций')
    paths = sorted(changes)
    ready = wrote = restarted = False
    try:
        for index, path in enumerate(paths):
            run(ssh, server, f'cp -a -- {shlex.quote(path)} {attempt}/old-{index}')
            with private_remote_upload(ssh, server, changes[path]) as uploaded:
                run(ssh, server, f'install -m 600 -o root -g root {shlex.quote(uploaded)} {attempt}/new-{index}')
        ready = True
        for index, path in enumerate(paths):
            wrote = True
            run(ssh, server, f'mv -fT -- {attempt}/new-{index} {shlex.quote(path)}')
        if restart:
            restarted = True
            run(ssh, server, 'systemctl restart wg-quick@wg0', title='Применение полной конфигурации')
            verify_live(ssh, server, files, changes)
        publish()
    except Exception as failure:
        try:
            with recovery_scope():
                if ready and wrote:
                    for index, path in enumerate(paths):
                        run(ssh, server, f'cp -a -- {attempt}/old-{index} {shlex.quote(path)}', title='Восстановление всех конфигураций')
                if restarted:
                    action = 'restart' if previous_state == 'active' else 'stop'
                    run(ssh, server, f'systemctl {action} wg-quick@wg0', title='Восстановление исходного состояния WireGuard')
                    if previous_state == 'active':
                        verify_live(ssh, server, files, {})
                run(ssh, server, f'rm -rf -- {shlex.quote(attempt)}')
        except Exception as recovery:
            raise StepError('configuration_recovery', -1, title='Изменение и восстановление WireGuard',
                detail=f'Защитные копии сохранены в {attempt}. Восстановление не завершено: {recovery}. Исходная ошибка: {failure}') from failure
        raise
    try:
        with recovery_scope():
            run(ssh, server, f'rm -rf -- {shlex.quote(attempt)}', title='Очистка подтверждённой защитной копии')
    except Exception:
        # Применение завершено; оставшаяся закрытая копия не меняет его результат.
        import logging
        logging.getLogger(__name__).warning('WG config applied; backup retained at %s', attempt)
    return sum(path.startswith(ROOT + '/clients/') for path in changes)
