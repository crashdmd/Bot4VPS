"""Remove our integration after revocation, without removing router services."""
import json
import re
import shlex

from core.openwrt.components import FILES, accepted_hashes


def removal_files(config, state):
    """Validate the whole inventory before deleting any shared component."""
    if state['accounts']:
        return []
    accepted = accepted_hashes(config, state.get('journal'))
    changed = [path for path, digest in state['files'].items()
               if path in FILES and digest is not None and
               (not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest) or digest not in accepted[path])]
    if changed:
        raise ValueError('Файлы Bot4VPS изменены после установки; очистка не завершена: ' + ', '.join(changed))
    return [(path, state['files'][path]) for path in FILES if state['files'].get(path) is not None]


def _config(node):
    config = node['openwrt']
    if not config.get('managed') or not re.fullmatch(r'bot4vps_[a-f0-9]{16}', config.get('username', '')):
        raise ValueError('Не подтверждена принадлежность интеграции Bot4VPS')
    if not config.get('ssh'):
        raise ValueError('Для проверки и удаления файлов интеграции Bot4VPS сохраните SSH-доступ')
    return config


def _inventory(ssh, config, *, require_revoked):
    from core.openwrt.bootstrap_transaction import drain
    account = config['username']
    journal_path = '/root/bot4vps-backup/' + account[8:] + '/transaction.json'
    # Inspect once; never return installer backups or credentials to the UI.
    script = """import { cursor } from 'uci';
import { readfile, lstat, popen, access } from 'fs';
let c = cursor(), accounts = [], files = {};
"""
    script += 'let account = ' + json.dumps(account) + ';\n'
    script += "if (c.get('rpcd', account) && c.get('rpcd', account, 'bot4vps_id') != substr(account, 8)) die('Не подтверждена принадлежность API-доступа');\n"
    if require_revoked:
        script += "if (c.get('rpcd', account) || access('/etc/bot4vps/keys/' + account + '.pub') || access('/usr/share/rpcd/acl.d/bot4vps-key-' + substr(account, 8) + '.json')) die('API-доступ ещё не отозван');\n"
    script += "c.foreach('rpcd', 'login', s => { if (s['.name'] != account && (s.bot4vps_id || match(s.username || '', /^bot4vps_[a-f0-9]+$/))) push(accounts, s['.name']); });\n"
    script += 'for (let path in ' + json.dumps(list(FILES)) + ") { let info = lstat(path); if (!info) files[path] = null; else if (info.type != 'file') files[path] = '__NOT_FILE__'; else { let p = popen('sha256sum ' + path); files[path] = trim(p.read('all')); p.close(); files[path] = split(files[path], ' ')[0]; } }\n"
    script += 'let text = readfile(' + json.dumps(journal_path) + "); let journal = text ? json(text) : null;\n"
    script += 'print(sprintf("%J", { accounts, files, journal, account_present: !!c.get("rpcd", account) }));\n'
    stdin, stdout, stderr = ssh.exec_command('ucode -', timeout=30)
    stdin.write(script); stdin.flush(); stdin.channel.shutdown_write()
    output, _, status = drain(stdout, stderr, timeout=60, limit=2_000_000)
    if status:
        raise ValueError('Не удалось проверить принадлежность доступа и файлы Bot4VPS через SSH')
    return json.loads(output)


def preflight(node):
    """Check cleanup without revoking access or changing files; persist only hashes."""
    from core.openwrt.console import target
    from core.ssh import create_ssh_client
    config = _config(node)
    ssh = None
    try:
        ssh = create_ssh_client(target(node))
        state = _inventory(ssh, config, require_revoked=False)
        removal_files(config, state)
        return {'accounts': sorted(state['accounts']), 'files': state['files']}
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError('Не удалось проверить возможность очистки интеграции через сохранённый SSH-доступ') from None
    finally:
        if ssh is not None:
            ssh.close()


def cleanup(node):
    from core.openwrt.bootstrap import _read
    from core.openwrt.console import target
    from core.ssh import create_ssh_client
    config = _config(node)
    account = config['username']
    ssh = create_ssh_client(target(node))
    try:
        state = _inventory(ssh, config, require_revoked=True)
        files = removal_files(config, state)
        if not state['accounts']:
            # Recheck every file and account before any unlink, including retries.
            check = "import { cursor } from 'uci'; let c = cursor(), found = false; c.foreach('rpcd', 'login', s => { if (s.bot4vps_id || match(s.username || '', /^bot4vps_[a-f0-9]+$/)) found = true; }); if (found) exit(1);"
            commands = ['ucode -e ' + shlex.quote(check)]
            for path, digest in files:
                if not re.fullmatch(r'[a-f0-9]{64}', digest):
                    raise ValueError('Не удалось проверить контрольную сумму компонента Bot4VPS')
                quoted = shlex.quote(path)
                commands.append('test ! -L ' + quoted + ' && test -f ' + quoted + ' && test "$(sha256sum ' + quoted + ' | cut -d " " -f 1)" = ' + shlex.quote(digest))
            if files:
                commands.append('rm -f ' + ' '.join(shlex.quote(path) for path, _ in files))
            _read(ssh, ' && '.join(commands))
            _read(ssh, '/etc/init.d/rpcd reload && rm -f /tmp/luci-indexcache && rm -rf /tmp/luci-modulecache')
            # Empty directories only; saved service configurations remain intact.
            _read(ssh, 'rmdir /etc/bot4vps/keys /etc/bot4vps /usr/share/bot4vps /www/luci-static/resources/view/bot4vps 2>/dev/null; true')
        # Installation snapshots belong to this account, not service backups.
        if (state.get('journal') or {}).get('account') == account:
            backup = '/root/bot4vps-backup/' + account[8:]
            _read(ssh, 'rm -f ' + ' '.join(shlex.quote(backup + '/' + name) for name in ('rpcd', 'uhttpd', 'transaction.json')) + ' && { rmdir ' + shlex.quote(backup) + ' /root/bot4vps-backup 2>/dev/null; true; }')
        return not state['accounts']
    except Exception as exc:
        if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError):
            raise
        raise ValueError('Не удалось завершить проверку и очистку файлов Bot4VPS через SSH') from None
    finally:
        ssh.close()
