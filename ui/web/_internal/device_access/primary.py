"""One security authority per panel, independent of the chosen second factor."""
from core import config

KEY = 'mobile_primary_device_id'

def current(rows):
    value = config.get_web_config().get(KEY)
    return value if any(row.get('kind') == 'device' and row.get('id') == value for row in rows) else None

def migrate(rows):
    web = config.get_web_config()
    devices = [row for row in rows if row.get('kind') == 'device']
    identifiers = {row['id'] for row in devices}
    selected = web.get(KEY) if web.get(KEY) in identifiers else None
    managed_totp = bool(web.get('totp_secret') and web.get('two_factor_enabled', True) and web.get('totp_source') != 'external')
    # Preserve explicit ownership, including panels affected by the first
    # migration. A real unlink clears both the primary and TOTP owner.
    owner = web.get('totp_device_id')
    if selected is None and managed_totp and owner in identifiers:
        selected = owner
    if web.get('mobile_primary_policy') == 1:
        if selected is None and len(devices) == 1:
            selected = devices[0]['id']
        if selected != web.get(KEY):
            assign(selected)
        return selected
    if selected is None and len(devices) == 1:
        selected = devices[0]['id']
    patch = {KEY: selected, 'mobile_primary_policy': 1}
    # A single legacy phone already owns the panel code; retain the secret.
    if selected and managed_totp and owner not in identifiers:
        patch['totp_device_id'] = selected
    config.patch_web_config(patch)
    return selected

def assign(device_id, *, selection_pending=False):
    config.patch_web_config({KEY: device_id, 'mobile_primary_policy': 1,
                            'mobile_primary_selection_pending': bool(selection_pending)})

def require(rows, device_id):
    from fastapi import HTTPException
    if current(rows) != device_id:
        raise HTTPException(403, 'Это действие доступно только основному телефону')


def require_factor_authority(rows, device_id, flow):
    """Only the chief, or its explicit first-time 2FA candidate, may act."""
    from fastapi import HTTPException
    selected = current(rows)
    if not (flow.get('purpose') == 'two_factor_enable' and selected is None
            and flow.get('primary_before') is None and flow.get('device_id') == device_id):
        require(rows, device_id)
    if 'primary_before' in flow and flow['primary_before'] != selected:
        raise HTTPException(409, 'Основной телефон изменился — начните запрос заново')
