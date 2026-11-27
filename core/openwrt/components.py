"""Files installed by the gateway integration, shared by its API accounts."""
import hashlib
import re
from pathlib import Path

ASSETS = Path(__file__).parent / 'assets'
FILES = {
    '/usr/share/bot4vps/contract.json': 'contract.json',
    '/usr/share/bot4vps/backup.uc': 'rpcd/backup.uc',
    '/usr/libexec/bot4vps-backup-worker.uc': 'rpcd/backup-worker.uc',
    '/usr/share/bot4vps/adguard.uc': 'rpcd/adguard.uc',
    '/usr/share/bot4vps/configuration.uc': 'rpcd/configuration.uc',
    '/usr/share/bot4vps/wireless.uc': 'rpcd/wireless.uc',
    '/usr/share/bot4vps/network.uc': 'rpcd/network.uc',
    '/usr/share/bot4vps/package-manager.uc': 'rpcd/package-manager.uc',
    '/usr/libexec/bot4vps-network-worker.uc': 'rpcd/network-worker.uc',
    '/usr/libexec/bot4vps-packages-worker.uc': 'rpcd/packages-worker.uc',
    '/usr/libexec/bot4vps-proxy-sessions.sh': 'rpcd/proxy-sessions.sh',
    '/usr/share/rpcd/ucode/bot4vps': 'rpcd/bot4vps',
    '/usr/share/rpcd/acl.d/bot4vps.json': 'acl/bot4vps.json',
    '/usr/share/luci/menu.d/bot4vps.json': 'menu/bot4vps.json',
    '/www/luci-static/resources/view/bot4vps/access.js': 'luci/access.js',
    '/usr/libexec/bot4vps-revoke.uc': 'rpcd/revoke.uc',
    '/usr/libexec/bot4vps-worker.uc': 'rpcd/worker.uc',
    '/usr/share/bot4vps/adguardhome.init': 'services/adguardhome.init',
    '/usr/share/bot4vps/ssclash.init': 'services/ssclash.init',
}


def hashes():
    return {path: hashlib.sha256((ASSETS / source).read_bytes()).hexdigest()
            for path, source in FILES.items()}


def accepted_hashes(config, journal=None):
    """Current assets plus manifests belonging to this exact managed account."""
    result = {path: {digest} for path, digest in hashes().items()}
    sources = [config.get('installed_components') or {}]
    journal = journal or {}
    if journal.get('account') == config.get('username'):
        sources.append({path: item.get('after') for path, item in (journal.get('files') or {}).items() if isinstance(item, dict)})
    for source in sources:
        for path, digest in source.items():
            if path in FILES and isinstance(digest, str) and re.fullmatch(r'[a-f0-9]{64}', digest):
                result[path].add(digest)
    return result
