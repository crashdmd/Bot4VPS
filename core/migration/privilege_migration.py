"""Legacy updater bridge, before application/config/UI initialization.

An updater already shipped to users cannot learn a new pre-start hook. If it
starts this release with its old root unit, the entry point hands migration
to a fixed detached installer and exits without serving requests.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from core.install_paths import get_install_path

APP = Path('/opt/bot4vps')
STATE = Path('/var/lib/bot4vps-helper/migration.json')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}


def migration_state():
    if STATE.exists():
        from .privileged.daemon import protected
        state = json.loads(protected(STATE).read_text()).get('status')
        return {'preparing': 'migration_in_progress', 'switched': 'migration_in_progress',
                'complete': 'privilege_separated', 'rolled_back': 'migration_failed'}.get(state, 'migration_failed')
    return 'legacy_root'


def _systemd_command(args, timeout):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=ENV, cwd='/')
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit('Не удалось проверить или запустить systemd: %s. Интерфейсы от root заблокированы.' % exc) from None


def enforce_application_user():
    # Isolated development/test source copies are not installed services.
    if get_install_path() != APP or os.geteuid() != 0:
        return
    result = _systemd_command(['/usr/bin/systemctl', 'show', 'bot4vps', '--property=User', '--property=MainPID'], 10)
    settings = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if result.returncode or settings.get('User') not in ('', 'root') or settings.get('MainPID') != str(os.getpid()):
        raise SystemExit('Bot4VPS 7.0 запускается от bot4vps. Используйте установленную службу; интерфейсы от root не запускаются.')
    state = migration_state()
    if state == 'migration_failed':
        raise SystemExit('Миграция привилегий не завершилась. Установщик обновления должен восстановить предыдущую версию; детали в journalctl -u bot4vps-privilege-migration.')
    installer = APP / 'core/migration/privileged/install.py'
    from .privileged.daemon import protected
    protected(installer)
    result = _systemd_command(['/usr/bin/systemd-run', '--collect', '--service-type=exec',
                             '--unit=bot4vps-privilege-migration', '/usr/bin/python3', '-I', str(installer), '--automatic'],
                             15)
    # A second root start may race the already-running fixed transient unit.
    if result.returncode:
        active = _systemd_command(['/usr/bin/systemctl', 'is-active', '--quiet', 'bot4vps-privilege-migration'], 5)
        if active.returncode:
            raise SystemExit('Не удалось запустить отдельный установщик миграции. Интерфейсы от root заблокированы.')
    raise SystemExit('Обновление 7.0: миграция привилегий выполняется отдельным установщиком. Интерфейсы запустятся от bot4vps после переключения службы.')
