#!/usr/bin/env python3
"""Standalone remote pre/post hook for acme.sh HTTP-01 (standard library only).

Installed root-owned under /etc/x-ui. Owns only tagged runtime firewall
rules and a separately restartable service. A watcher recovers the lease
when the acme.sh process exits without running its post hook.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


class HttpGuard:
    def __init__(self, directory=Path('/run/bot4vps-acme-http'), execute=None):
        self.directory = Path(directory)
        self.state_path = self.directory / 'lease.json'
        self.execute = execute or self._execute

    @staticmethod
    def _execute(argv):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        return result.returncode, result.stdout, result.stderr

    def checked(self, argv):
        code, out, err = self.execute(argv)
        if code:
            raise RuntimeError((err or out or f'Команда {argv[0]} не выполнена').strip()[:500])
        return out

    @staticmethod
    def process_start(pid):
        try:
            return Path(f'/proc/{int(pid)}/stat').read_text().rsplit(') ', 1)[1].split()[19]
        except (OSError, ValueError, IndexError):
            return None

    def save(self, state):
        with tempfile.NamedTemporaryFile(mode='w', dir=self.directory, delete=False) as file:
            temp = Path(file.name)
            try:
                os.fchmod(file.fileno(), 0o600)
                json.dump(state, file)
                file.flush()
                os.fsync(file.fileno())
            except BaseException:
                temp.unlink(missing_ok=True)
                raise
        try:
            os.replace(temp, self.state_path)
        finally:
            temp.unlink(missing_ok=True)

    def load(self):
        return json.loads(self.state_path.read_text()) if self.state_path.exists() else None

    def lock(self):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        file = (self.directory / 'lock').open('a')
        os.chmod(file.name, 0o600)
        fcntl.flock(file, fcntl.LOCK_EX)
        return file

    @staticmethod
    def spec(state):
        port, tag = int(state['port']), str(state['tag'])
        if not 1 <= port <= 65535 or not re.fullmatch(r'bot4vps-acme-[0-9a-f]{32}', tag):
            raise RuntimeError('Неверный token временного доступа')
        return ['-p', 'tcp', '-m', 'tcp', '--dport', str(port), '-m', 'comment', '--comment', tag, '-j', 'ACCEPT']

    def runtime_rules(self, binary):
        out = self.checked([binary, '-w', '5', '-S', 'ufw-user-input'])
        return [shlex.split(line) for line in out.splitlines() if line.startswith('-A ')]

    def restore(self, state):
        errors = []
        unit = state.get('unit')
        if unit:
            if not re.fullmatch(r'[A-Za-z0-9_.@:-]+\.service', unit) or unit.startswith('user@'):
                errors.append('Неверный token systemd-сервиса')
            else:
                try:
                    self.checked(['systemctl', 'start', unit])
                except Exception as exc:
                    errors.append(f'{unit}: {exc}')
        spec = self.spec(state)
        expected = ['-A', 'ufw-user-input'] + spec
        for binary in reversed(state.get('binaries', [])):
            try:
                if binary not in ('iptables', 'ip6tables'):
                    raise RuntimeError('Неверный token firewall')
                tagged = [rule for rule in self.runtime_rules(binary) if state['tag'] in rule]
                if not tagged:
                    continue
                if tagged != [expected]:
                    raise RuntimeError('Временное правило изменилось; удаление остановлено')
                self.checked([binary, '-w', '5', '-D', 'ufw-user-input'] + spec)
                if any(state['tag'] in rule for rule in self.runtime_rules(binary)):
                    raise RuntimeError('Удаление временного правила не подтверждено')
            except Exception as exc:
                errors.append(f'{binary}: {exc}')
        if errors:
            raise RuntimeError('; '.join(errors))
        self.state_path.unlink(missing_ok=True)
        print('Bot4VPS: временный доступ убран, сервис и firewall восстановлены', flush=True)

    def firewall_binaries(self):
        if shutil.which('firewall-cmd'):
            code, out, _ = self.execute(['firewall-cmd', '--state'])
            if code == 0 and out.strip() == 'running':
                raise RuntimeError('Автопродление HTTP-01: firewalld требует отдельной настройки хуков')
        active_ufw = False
        if shutil.which('ufw'):
            out = self.checked(['ufw', 'status'])
            active_ufw = bool(re.search(r'^Status: active$', out, re.M))
            if not active_ufw and not re.search(r'^Status: inactive$', out, re.M):
                raise RuntimeError('Состояние UFW не определено')
        if active_ufw:
            self.runtime_rules('iptables')
            code, _, _ = self.execute(['ip6tables', '-w', '5', '-S', 'ufw-user-input'])
            return ['iptables'] + (['ip6tables'] if code == 0 else [])
        # Не объявляем порт открытым при неизвестном активном firewall.
        if shutil.which('nft'):
            ruleset = json.loads(self.checked(['nft', '-j', 'list', 'ruleset']))
            if any('rule' in entry or entry.get('chain', {}).get('policy') == 'drop'
                   for entry in ruleset.get('nftables', [])):
                raise RuntimeError('Автопродление HTTP-01: активный nftables требует отдельной настройки хуков')
        for binary in ('iptables', 'ip6tables'):
            if shutil.which(binary):
                out = self.checked([binary, '-w', '5', '-S'])
                if any(line.startswith('-A ') or line.startswith('-P ') and not line.endswith(' ACCEPT')
                       for line in out.splitlines()):
                    raise RuntimeError('Автопродление HTTP-01: неизвестные правила firewall')
        return []

    def prepare(self, pid, domain, port):
        with self.lock():
            old = self.load()
            if old:
                if self.process_start(old['pid']) == old['start']:
                    raise RuntimeError('HTTP-порт уже подготовлен другой задачей acme.sh')
                self.restore(old)
            start = self.process_start(pid)
            if start is None:
                raise RuntimeError('Процесс acme.sh уже завершился')
            state = {'pid': pid, 'start': start, 'domain': domain, 'port': port,
                     'tag': 'bot4vps-acme-' + uuid.uuid4().hex, 'binaries': [], 'unit': None}
            binaries = self.firewall_binaries()
            self.save(state)
            try:
                # Watcher работает независимо от SSH и восстанавливает состояние
                # даже после kill acme.sh, когда post-hook уже не запустится.
                self.checked(['systemd-run', '--quiet', '--collect',
                              '--unit=bot4vps-acme-watch-' + state['tag'][len('bot4vps-acme-'):],
                              sys.executable, str(Path(__file__).resolve()), 'watch', str(pid), domain,
                              '--port', str(port)])
                for binary in binaries:
                    state['binaries'].append(binary)
                    self.save(state)
                    spec = self.spec(state)
                    self.checked([binary, '-w', '5', '-I', 'ufw-user-input', '1'] + spec)
                    if self.runtime_rules(binary)[:1] != [['-A', 'ufw-user-input'] + spec]:
                        raise RuntimeError('Временный allow не подтверждён перед запретами UFW')
                listeners = self.checked(['ss', '-tlnpH', f'sport = :{port}'])
                if listeners.strip():
                    holders = re.findall(r'\("([^"]+)",pid=(\d+)', listeners)
                    if not holders or any(name in ('x-ui', 'xray') for name, _ in holders):
                        raise RuntimeError('Нельзя безопасно освободить HTTP-порт: владелец не определён или это 3x-ui')
                    units = set(self.checked(['ps', '-o', 'unit=', '-p', ','.join(pid for _, pid in holders)]).split())
                    if len(units) != 1:
                        raise RuntimeError('HTTP-порт занят несколькими сервисами')
                    unit = units.pop()
                    if not re.fullmatch(r'[A-Za-z0-9_.@:-]+\.service', unit) or unit.startswith('user@') or unit == 'x-ui.service':
                        raise RuntimeError('Владелец HTTP-порта не является отдельно перезапускаемым сервисом')
                    properties = self.checked(['systemctl', 'show', unit, '-p', 'LoadState', '-p', 'CanStart', '-p', 'Transient'])
                    values = dict(line.split('=', 1) for line in properties.splitlines() if '=' in line)
                    if values.get('LoadState') != 'loaded' or values.get('CanStart') != 'yes' or values.get('Transient') != 'no':
                        raise RuntimeError('Сервис HTTP-порта нельзя надёжно восстановить')
                    state['unit'] = unit
                    self.save(state)
                    self.checked(['systemctl', 'stop', unit])
                print(f'Bot4VPS: HTTP-порт {port} подготовлен для acme.sh', flush=True)
            except BaseException as original:
                try:
                    self.restore(state)
                except Exception as restore_error:
                    raise RuntimeError(f'{original}; восстановление HTTP-порта: {restore_error}') from original
                raise

    def release(self, pid, domain):
        with self.lock():
            state = self.load()
            if (state and state['pid'] == pid and state['domain'] == domain
                    and self.process_start(pid) == state['start']):
                self.restore(state)

    def watch(self, pid, domain):
        while True:
            with self.lock():
                state = self.load()
                if not state or state['pid'] != pid or state['domain'] != domain:
                    return
                if self.process_start(pid) != state['start']:
                    self.restore(state)
                    return
            time.sleep(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('pre', 'post', 'watch'))
    parser.add_argument('pid', type=int)
    parser.add_argument('domain')
    parser.add_argument('--port', type=int, default=80)
    args = parser.parse_args()
    if os.geteuid() != 0 or not 1 <= args.port <= 65535 or args.pid <= 1:
        parser.error('Хук требует root, действительный PID и порт 1–65535')
    guard = HttpGuard()
    try:
        if args.action == 'pre':
            guard.prepare(args.pid, args.domain, args.port)
        elif args.action == 'post':
            guard.release(args.pid, args.domain)
        else:
            guard.watch(args.pid, args.domain)
    except Exception as exc:
        print(f'Bot4VPS: ошибка HTTP-хука: {exc}', file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
