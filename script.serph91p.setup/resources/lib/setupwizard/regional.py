"""Whitelisted native Kodi locale apply/restore with a persisted preimage journal.

Never edit an active guisettings.xml. A layout backup may carry a separate
locale journal; old file-only backups remain unchanged and fully restorable.
"""
import hashlib
import json
from pathlib import Path
from .config import _profile, _backup, _atomic, _no_symlink_ancestors, MANIFEST

JOURNAL = 'reference-locale.json'
ONLY_LOCALE = {'schema': 6, 'kind': 'reference-locale'}
KEYS = (
    'locale.language', 'locale.charset', 'locale.country',
    'locale.shortdateformat', 'locale.longdateformat',
    'locale.temperatureunit', 'locale.speedunit', 'locale.use24hourclock',
    'locale.timeformat',  # The 24-hour callback rewrites this; apply/restore last.

    'locale.audiolanguage', 'locale.subtitlelanguage',
    'locale.keyboardlayouts', 'locale.activekeyboardlayout',
)


def reference():
    data = json.loads((Path(__file__).resolve().parents[2] / 'templates/arctic-reference.json').read_text())['locale']
    _validate_values(data)
    return data


def _validate_values(values):
    if not isinstance(values, dict) or set(values) != set(KEYS):
        raise ValueError('locale keys differ from fixed allowlist')
    for key, value in values.items():
        if key == 'locale.keyboardlayouts':
            if not isinstance(value, list) or not 1 <= len(value) <= 3:
                raise ValueError('invalid keyboard layout list')
            parts = value
        else:
            parts = [value]
        if any(not isinstance(v, str) or len(v) > 512 or '\x00' in v for v in parts):
            raise ValueError('invalid locale value type')


def read(api):
    result = {}
    for key in KEYS:
        response = api.rpc('Settings.GetSettingValue', {'setting': key})
        if 'error' in response or not isinstance(response.get('result'), dict) or 'value' not in response['result']:
            raise RuntimeError('Kodi locale read failed: ' + key)
        result[key] = response['result']['value']
    _validate_values(result)
    return result


def _set(api, key, value):
    response = api.rpc('Settings.SetSettingValue', {'setting': key, 'value': value})
    if response.get('result') is not True or 'error' in response:
        raise RuntimeError('Kodi locale setting rejected: ' + key)
    check = api.rpc('Settings.GetSettingValue', {'setting': key})
    if 'error' in check or check.get('result', {}).get('value') != value:
        raise RuntimeError('Kodi locale readback mismatch: ' + key)


def _digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _journal_path(profile, backup):
    profile = _profile(profile)
    backup = _backup(backup, profile, must_exist=True)
    path = backup / JOURNAL
    _no_symlink_ancestors(path)
    return path


def preflight_restore(profile, backup, api):
    path = _journal_path(profile, backup)
    if not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError('missing or oversized locale journal')
    meta_path = path.parent / MANIFEST
    _no_symlink_ancestors(meta_path)
    if not meta_path.is_file() or meta_path.stat().st_size > 256 * 1024:
        raise ValueError('missing locale backup manifest')
    meta = json.loads(meta_path.read_text())
    if meta != ONLY_LOCALE:
        from .config import _validate_manifest
        _validate_manifest(profile, path.parent)
    record = json.loads(path.read_text())
    if not isinstance(record, dict) or set(record) != {'schema', 'before', 'after', 'sha256'}:
        raise ValueError('invalid locale journal shape')
    body = {k: record[k] for k in ('schema', 'before', 'after')}
    if record['schema'] != 1 or record['sha256'] != _digest(body):
        raise ValueError('invalid locale journal checksum')
    _validate_values(record['before'])
    _validate_values(record['after'])
    current = read(api)
    if any(current[k] != record['before'][k] and current[k] != record['after'][k] for k in KEYS):
        raise ValueError('locale changed by user; restore refused')
    return record


def _restore_values(api, before):
    changed = []
    # Earlier parent changes (language/country) may affect later regional defaults.
    for key in KEYS:
        if read(api)[key] != before[key]:
            _set(api, key, before[key])
            changed.append('runtime:' + key)
    if read(api) != before:
        raise RuntimeError('locale restore incomplete; journal preserved')
    return changed


def restore(profile, backup, api):
    record = preflight_restore(profile, backup, api)
    return _restore_values(api, record['before'])

def apply(profile, backup, api, *, approved=False):
    if approved is not True:
        raise ValueError('locale change not approved')
    profile = _profile(profile)
    backup = _backup(backup, profile)
    goal = reference()
    before = read(api)
    if before == goal:
        return []
    if not backup.parent.is_dir():
        raise ValueError('backup root must already exist')
    if not backup.exists():
        backup.mkdir(mode=0o700)
        _atomic(backup / MANIFEST, json.dumps(ONLY_LOCALE, sort_keys=True).encode())
    manifest_path = backup / MANIFEST
    _no_symlink_ancestors(manifest_path)
    if not manifest_path.is_file() or manifest_path.stat().st_size > 256 * 1024:
        raise ValueError('missing or oversized backup manifest')
    meta = json.loads(manifest_path.read_text())
    if meta != ONLY_LOCALE:
        from .config import _validate_manifest
        _validate_manifest(profile, backup)
    path = _journal_path(profile, backup)
    if path.exists():
        raise ValueError('locale journal must be new')
    record = {'schema': 1, 'before': before, 'after': goal}
    record['sha256'] = _digest(record)
    _atomic(path, (json.dumps(record, sort_keys=True, indent=2) + '\n').encode())
    if meta != ONLY_LOCALE:
        if meta.get('schema') not in (4, 5):
            raise ValueError('locale companion requires a current file-layout backup')
        meta['schema'] = 7 if meta['schema'] == 4 else 8
        meta['runtime'] = {'kind':'reference-locale', 'file':JOURNAL,
                           'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        _atomic(manifest_path, (json.dumps(meta,sort_keys=True,indent=2)+'\n').encode())
    persisted = preflight_restore(profile, backup, api)
    if persisted != record or read(api) != before:
        raise ValueError('locale changed while staging; no mutation performed')
    changed = []
    try:
        for key in KEYS:
            if read(api)[key] != goal[key]:
                _set(api, key, goal[key])
                changed.append('runtime:' + key)
        if read(api) != goal:
            raise RuntimeError('locale apply final readback mismatch')
        return changed
    except Exception:
        # Preserve journal even if rollback fails; never hide incomplete recovery.
        _restore_values(api, before)
        raise
