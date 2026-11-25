"""Router-side installation journal with compare-before-restore semantics."""
from __future__ import annotations

import base64
import hashlib
import json
import shlex
import stat


def drain(stdout, stderr, *, timeout=240, limit=1_000_000):
    """Drain both channel windows until exit; never wait on stdout before stderr."""
    import time
    channel = stdout.channel
    deadline = time.monotonic() + timeout
    output = bytearray(); error = bytearray(); overflow = False
    while True:
        progress = False
        for ready, recv, target, cap in ((channel.recv_ready, channel.recv, output, limit),
                                        (channel.recv_stderr_ready, channel.recv_stderr, error, 65536)):
            if ready():
                chunk = recv(32768); progress = True
                if len(target) + len(chunk) > cap: overflow = True
                target.extend(chunk[:max(0, cap - len(target))])
        if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
            status = channel.recv_exit_status()
            if overflow: raise ValueError('Вывод команды превышает допустимый размер')
            return bytes(output), bytes(error), status
        if time.monotonic() >= deadline:
            channel.close(); raise ValueError('Превышено время выполнения шага подключения')
        if not progress: time.sleep(.01)


class Transaction:
    def __init__(self, ssh, node_id, emit):
        self.ssh = ssh; self.node_id = node_id; self.emit = emit
        self.files = {}; self.packages_before = {}; self.packages_after = {}
        self.package_manager = None; self.account = 'bot4vps_' + node_id
        self.path = '/root/bot4vps-backup/' + node_id + '/transaction.json'
        self.finished = False

    def snapshot(self, path):
        if path in self.files: return
        target = shlex.quote(path)
        _, stdout, stderr = self.ssh.exec_command("if [ -L " + target + " ]; then printf '__LINK__\\n'; readlink " + target + "; elif [ -f " + target + " ]; then ls -ldn " + target + "; cat " + target + "; else printf '__ABSENT__\\n'; fi", timeout=20)
        output, error, status = drain(stdout, stderr)
        if status: raise ValueError('Не удалось сохранить снимок: ' + path)
        if output.strip() == b'__ABSENT__':
            self.files[path] = {'before': None, 'mode': 0o644, 'after': None}; return
        metadata, content = output.split(b'\n', 1)
        if metadata == b'__LINK__':
            link = content.decode().strip()
            self.files[path] = {'before': base64.b64encode(link.encode()).decode(), 'link': link, 'mode': 0o777, 'after': None}
            from core.openwrt.bootstrap import _read
            resolved = _read(self.ssh, 'readlink -f ' + target).strip()
            if resolved and resolved != path: self.snapshot(resolved)
            return
        permissions = metadata.split()[0].decode()
        if not permissions.startswith('-') or len(permissions) < 10: raise ValueError('Неподдерживаемый тип снимка: ' + path)
        mode = 0
        for i, char in enumerate(permissions[1:10]):
            if char in ('r','w','x','s','t'): mode |= 1 << (8-i)
        if len(content) > 512 * 1024: raise ValueError('Компонент слишком большой для снимка: ' + path)
        self.files[path] = {'before': base64.b64encode(content).decode(), 'mode': mode, 'after': None}

    def digest(self, path):
        from core.openwrt.bootstrap import _read
        target = shlex.quote(path)
        output = _read(self.ssh, 'if [ -L ' + target + " ]; then printf '__LINK__\\n'; readlink " + target + '; elif [ -f ' + target + ' ]; then sha256sum ' + target + '; fi')
        if output.startswith('__LINK__\n'): return 'link:' + hashlib.sha256(output.split('\n',1)[1].strip().encode()).hexdigest()
        return output.split()[0] if output.strip() else None

    def save(self, phase='running'):
        from core.openwrt.bootstrap import _write
        content = json.dumps({'version': 1, 'phase': phase, 'account': self.account,
            'files': self.files, 'packages_before': self.packages_before,
            'packages_after': self.packages_after, 'manager': self.package_manager}, separators=(',', ':'))
        _write(self.ssh, self.path, content, '600')

    def record(self, path):
        self.files[path]['after'] = self.digest(path)
        self.save()

    def write(self, path, content, mode='644'):
        from core.openwrt.bootstrap import _write
        self.snapshot(path)
        # Record intended bytes first: a lost SSH response must still be recoverable.
        self.files[path]['after'] = hashlib.sha256(content.encode()).hexdigest(); self.save()
        _write(self.ssh, path, content, mode)

    def inventory(self):
        from core.openwrt.bootstrap import _read
        text = _read(self.ssh, 'apk list -I --manifest' if self.package_manager == 'apk' else 'opkg list-installed')
        if self.package_manager == 'apk': return {line.split()[0]: line.split()[1] for line in text.splitlines() if len(line.split()) == 2}
        return dict(line.split(' - ', 1) for line in text.splitlines() if ' - ' in line)

    def rollback(self, *, revoke_account=True):
        from core.openwrt.bootstrap import _read, _write
        self.emit('Возвращаю изменения подключения по журналу установки…')
        # Revoke only our exact managed section; keep other accounts and UCI changes.
        if revoke_account:
            _read(self.ssh, 'if [ "$(uci -q get rpcd.' + self.account + '.bot4vps_id)" = ' + shlex.quote(self.node_id) + ' ]; then uci delete rpcd.' + self.account + '; uci commit rpcd; fi')
            revoke = '/usr/libexec/bot4vps-revoke.uc'
            try: _read(self.ssh, 'test ! -f ' + revoke + ' || /usr/bin/ucode ' + revoke + ' ' + self.account)
            except Exception: self.emit('Не удалось подтвердить завершение API-сеансов; rpcd будет перезапущен.')
        unresolved = []
        for path, record in reversed(list(self.files.items())):
            if path == '/etc/config/rpcd': continue
            try:
                current = self.digest(path)
                before = base64.b64decode(record['before']) if record['before'] is not None else None
                before_hash = (('link:' if record.get('link') else '') + hashlib.sha256(before).hexdigest()) if before is not None else None
                if current == before_hash: continue
                if current != record['after']: unresolved.append(path); continue
                if before is None: _read(self.ssh, 'rm -f ' + shlex.quote(path))
                elif record.get('link'):
                    temp = shlex.quote(path + '.bot4vps-restore-link')
                    _read(self.ssh, 'ln -s ' + shlex.quote(record['link']) + ' ' + temp + ' && mv -f ' + temp + ' ' + shlex.quote(path))
                else: _write(self.ssh, path, before, format(record['mode'], 'o'))
            except Exception: unresolved.append(path)
        # Package removals are limited to introduced versions; never --force-depends.
        current = self.inventory() if self.packages_after else {}
        introduced = [name for name, version in self.packages_after.items()
            if name not in self.packages_before and current.get(name) == version]
        if introduced:
            self.emit('Удаляю добавленные для подключения пакеты и зависимости, которые не нужны другим пакетам…')
            command = ('apk del --no-network ' if self.package_manager == 'apk' else 'opkg remove ')
            try: _read(self.ssh, command + ' '.join(shlex.quote(name) for name in introduced))
            except Exception: unresolved.append('пакеты: ' + ', '.join(introduced))
        for service in (('uhttpd', 'rpcd') if revoke_account else ('rpcd',)):
            try: _read(self.ssh, 'test ! -x /etc/init.d/' + service + ' || /etc/init.d/' + service + (' restart' if revoke_account else ' reload'))
            except Exception: unresolved.append(service)
        self.save('rolled_back' if not unresolved else 'rollback_incomplete')
        self.finished = True
        if unresolved: self.emit('Не перезаписываю параллельные изменения или используемые компоненты. Нужна проверка: ' + '; '.join(unresolved))
        else: self.emit('Созданный доступ, файлы компонентов и изменения HTTPS отменены.' if revoke_account else 'Компоненты интеграции восстановлены. Учётные записи и доступ сохранены.')
        return not unresolved

    def commit(self):
        self.save('committed'); self.finished = True
