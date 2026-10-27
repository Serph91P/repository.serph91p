"""Explicit native skin selection; Kodi's Keep dialog is never bypassed."""
import json
from uuid import uuid4
from .config import _profile, _backup, _atomic, _no_symlink_ancestors
from .profiles import PROFILES


def active_skin(api):
    if api.xbmc.getCondVisibility('Window.IsVisible(10100)'):
        raise RuntimeError('Native Keep/YesNo dialog still open; skin not verified')
    value = api.xbmc.getSkinDir()
    if not isinstance(value, str) or not value.startswith('skin.') or len(value) > 256:
        raise RuntimeError('Active native skin unavailable')
    return value


def request_activation(profile, profile_id, api, *, approved=False):
    selected = next((p for p in PROFILES if p.key == profile_id), None)
    if selected is None:
        raise ValueError('Unknown selected skin')
    before = active_skin(api)
    if before == selected.addon_id:
        return False
    if approved is not True:
        raise ValueError('Skin activation not approved')
    root = _profile(profile)
    backup_root = root / 'setupwizard-backups'
    _no_symlink_ancestors(backup_root)
    backup_root.mkdir(mode=0o700, exist_ok=True)
    backup = _backup(backup_root / uuid4().hex, root)
    backup.mkdir(mode=0o700)
    journal = backup / 'skin-activation.json'
    data = {'schema': 1, 'before': before, 'requested': selected.addon_id,
            'result': 'pending-native-confirmation'}
    # Persist the prior native value BEFORE the setter can reload Kodi's skin.
    _atomic(journal, (json.dumps(data, sort_keys=True) + '\n').encode())
    if active_skin(api) != before:
        raise RuntimeError('Native skin changed while preparing activation')
    response = api.rpc('Settings.SetSettingValue',
                       {'setting': 'lookandfeel.skin', 'value': selected.addon_id})
    if response.get('result') is not True or 'error' in response:
        raise RuntimeError('Kodi did not accept native skin selection; journal preserved')
    # Setter acceptance is NOT Keep confirmation. Return to Kodi and only use
    # getSkinDir on a subsequent wizard invocation as completion evidence.
    return True
