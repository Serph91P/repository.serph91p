"""Back up and toggle Estuary's runtime touchmode through supported builtins.

Never edit the active skin's persisted XML or Kodi's cached favourites file.
"""
import json
from .config import _profile, _backup, _atomic, MANIFEST

STATE = {'schema': 3, 'kind': 'estuary-touchmode', 'before': False, 'after': True}


def _mode(xbmc):
    if xbmc.getSkinDir() != 'skin.estuary':
        raise ValueError('Estuary must be active for touchmode operations')
    value = xbmc.getCondVisibility('Skin.HasSetting(touchmode)')
    if not isinstance(value, bool):
        raise ValueError('invalid touchmode state')
    return value


def enable_touch(profile, backup, xbmc):
    profile = _profile(profile)
    backup = _backup(backup, profile)
    if _mode(xbmc):
        return []
    if backup.exists():
        raise ValueError('backup destination must be new')
    backup.parent.mkdir(mode=0o700, exist_ok=True)
    backup.mkdir(mode=0o700)
    _atomic(backup / MANIFEST, json.dumps(STATE, sort_keys=True).encode('utf-8'))
    if _mode(xbmc):
        raise ValueError('touchmode changed before mutation')
    xbmc.executebuiltin('Skin.SetBool(touchmode)', True)
    if not _mode(xbmc):
        raise RuntimeError('touchmode activation not verified; backup preserved')
    return ['runtime:skin.estuary/touchmode']


def restore_touch(profile, backup, xbmc):
    profile = _profile(profile)
    backup = _backup(backup, profile)
    path = backup / MANIFEST
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024:
        raise ValueError('unsafe touchmode manifest')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data != STATE or type(data.get('before')) is not bool or type(data.get('after')) is not bool:
        raise ValueError('invalid touchmode manifest')
    if not _mode(xbmc):
        return []
    xbmc.executebuiltin('Skin.Reset(touchmode)', True)
    if _mode(xbmc):
        raise RuntimeError('touchmode restore not verified')
    return ['runtime:skin.estuary/touchmode']


def restore_layout(profile, backup, xbmc):
    """Route fixed manifest types without permitting manifest-supplied actions."""
    from .config import rollback
    profile = _profile(profile)
    backup = _backup(backup, profile)
    path = backup / MANIFEST
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024:
        raise ValueError('unsafe backup manifest')
    data = json.loads(path.read_text(encoding='utf-8'))
    if isinstance(data, dict) and data.get('schema') == 3:
        return restore_touch(profile, backup, xbmc)
    from . import regional
    from .addons import KodiAddonAPI
    journal = backup / regional.JOURNAL
    if journal.exists() or journal.is_symlink():
        api = KodiAddonAPI(xbmc)
        regional.preflight_restore(profile, backup, api)
        changed = [] if data == regional.ONLY_LOCALE else rollback(profile, backup)
        return changed + regional.restore(profile, backup, api)
    if data == regional.ONLY_LOCALE:
        raise ValueError('locale-only backup journal missing')
    return rollback(profile, backup)
