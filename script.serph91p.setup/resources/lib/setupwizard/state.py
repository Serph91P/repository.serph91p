"""Small resumable preference record; completion is always live readback.

No credentials, account flags or trusted completion booleans are persisted.
Unknown/corrupt records fail closed, never becoming a new-install instruction.
"""
from dataclasses import dataclass
import hashlib
import json
import re
from xml.etree import ElementTree as ET
from .config import _profile, _no_symlink_ancestors, _atomic, _target, MAX_FILE_BYTES
from .profiles import PROFILES, requirements_for
from .addons import REQUIREMENTS, PROFILE_REQUIREMENTS, MEDIA_REQUIREMENTS
from .origins import ordered_requirements, check_requirement_strict, repository_policy
from .activation import active_skin
from .navigation import load_bindings, binding_path
from .common_layouts import common_payloads
from . import regional

PATH = 'addon_data/script.serph91p.setup/setup-state.json'
INSTALL_PATH = 'addon_data/script.serph91p.setup/install-session.json'


def _install_path(profile):
    path = _profile(profile) / INSTALL_PATH
    _no_symlink_ancestors(path)
    if path.exists() and (not path.is_file() or path.stat().st_size > 4096):
        raise ValueError('invalid installation session file')
    return path


def _install_scope(profile_id, required, api):
    """Consent to public allowlisted work, never evidence that work is done."""
    from .addons import REQUIREMENTS_BY_ID
    from .origins import ORIGINS
    from .pvr import distribution
    if profile_id not in tuple(p.key for p in PROFILES if not p.retired):
        raise ValueError('unknown installation profile')
    rows = []
    for req in required:
        if req != REQUIREMENTS_BY_ID.get(req.addon_id):
            raise ValueError('installation requirement not allowlisted')
        repository = distribution(api).repository if req.addon_id == 'pvr.iptvsimple' else ORIGINS[req.addon_id]
        rows.append((req.addon_id, req.min_version, req.min_version_string, repository))
    if not rows or len(rows) > 128 or len({row[0] for row in rows}) != len(rows):
        raise ValueError('invalid installation scope')
    public_scope = {'schema': 1, 'profile': profile_id, 'kodi': 21, 'requirements': rows}
    return hashlib.sha256(json.dumps(public_scope, sort_keys=True).encode()).hexdigest()


def installation_session(profile, profile_id, required, api):
    """Return active/paused only for the exact previously approved batch."""
    path = _install_path(profile)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise ValueError('invalid installation session JSON') from exc
    if (not isinstance(data, dict) or set(data) != {'schema', 'profile', 'scope', 'active'}
            or type(data['schema']) is not int or data['schema'] != 1
            or data['profile'] not in tuple(p.key for p in PROFILES if not p.retired)
            or not isinstance(data['scope'], str) or not re.fullmatch(r'[a-f0-9]{64}', data['scope'])
            or type(data['active']) is not bool):
        raise ValueError('unknown installation session schema')
    if data['profile'] != profile_id or data['scope'] != _install_scope(profile_id, required, api):
        return None
    return 'active' if data['active'] else 'paused'


def remember_installation(profile, profile_id, required, api, *, active=True):
    if type(active) is not bool:
        raise ValueError('invalid installation activity')
    data = {'schema': 1, 'profile': profile_id,
            'scope': _install_scope(profile_id, required, api), 'active': active}
    _atomic(_install_path(profile), (json.dumps(data, sort_keys=True) + '\n').encode())


def clear_installation(profile):
    path = _install_path(profile)
    if path.exists():
        path.unlink()  # Only our bounded regular consent record, never addon data.

SKIN_SETTINGS = frozenset(('addon_data/skin.arctic.fuse.3/settings.xml',
                           'addon_data/skin.estuary.modv2/settings.xml',
                           'addon_data/skin.rotary/settings.xml','addon_data/skin.nimbus/settings.xml'))


def _settings_values(data):
    if len(data) > MAX_FILE_BYTES or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('unsafe skin settings XML')
    root = ET.fromstring(data)
    if root.tag != 'settings':
        raise ValueError('unexpected skin settings root')
    values = {}
    for node in root:
        key = node.get('id', '').lower()
        if node.tag != 'setting' or not key or key in values or len(node):
            raise ValueError('ambiguous skin settings')
        values[key] = (node.get('type', ''), node.text or '')
    return values


def _layout_matches(path, target, expected):
    if not target.exists() or target.stat().st_size > MAX_FILE_BYTES:
        return False
    actual = target.read_bytes()
    if path in SKIN_SETTINGS:
        # Native skin saves may reorder/reindent XML. Compare typed setting
        # values, not serialization. Rollback keeps its strict byte hashes.
        return _settings_values(actual) == _settings_values(expected)
    return actual == expected  # Generated menu/JSON files retain exact checks.


def _path(profile):
    path = _profile(profile) / PATH
    _no_symlink_ancestors(path)
    if path.exists() and (not path.is_file() or path.stat().st_size > 4096):
        raise ValueError('invalid setup state file')
    return path


def load(profile):
    path = _path(profile)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise ValueError('invalid setup state JSON') from exc
    if (not isinstance(data, dict) or set(data) != {'schema', 'profile'}
            or type(data['schema']) is not int or data['schema'] != 1
            or data['profile'] not in tuple(p.key for p in PROFILES)):
        raise ValueError('unknown setup state schema or profile')
    return data['profile']


def save(profile, profile_id):
    if profile_id not in tuple(p.key for p in PROFILES):
        raise ValueError('unknown setup profile')
    path = _path(profile)
    _atomic(path, (json.dumps({'schema': 1, 'profile': profile_id}, sort_keys=True) + '\n').encode())


@dataclass(frozen=True)
class Status:
    addons: bool
    layout: bool
    regional: bool
    layout_detail: str
    regional_detail: str
    addon_details: tuple
    pending_bindings: int = 0
    login: str = 'unknown'
    updates: bool = False
    update_detail: str = 'Update-Regeln je Addon unbekannt'
    skin: bool = False
    skin_detail: str = 'Aktiver Skin nicht geprüft'
    menu: bool = False
    menu_detail: str = 'Native Menüansicht nicht geprüft'

    @property
    def configured(self):
        return self.addons and self.layout and self.regional

    @property
    def ready(self):
        return self.configured and self.skin and self.updates and self.menu


def inspect(profile, profile_id, api, update_rule_reader=None):
    """Read only: saved profile selects expectations, never supplies evidence."""
    selected = next(p for p in PROFILES if p.key == profile_id)
    required = ordered_requirements(requirements_for(selected, REQUIREMENTS, PROFILE_REQUIREMENTS, MEDIA_REQUIREMENTS), api=api)
    details = tuple((req.label, *check_requirement_strict(api, req)) for req in required)
    layout, pending = False, 0
    try:
        root = _profile(profile)
        binding = _target(root, binding_path(profile_id))
        if not binding.exists():
            layout_detail = 'Layout fehlt / Einrichtung offen'
        else:
            bindings = load_bindings(root, profile_id)
            pending = sum(value is None for value in bindings.values())
            payloads = common_payloads(root, profile_id, bindings)
            layout = True
            for rel, expected in payloads.items():
                target = _target(root, rel)
                if not _layout_matches(rel, target, expected):
                    layout = False
            layout_detail = ('Layout zurückgelesen' if layout else
                             'Layout geändert oder unvollständig — prüfen, nicht automatisch überschreiben')
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError):
        layout = False
        layout_detail = 'Layout nicht sicher prüfbar — prüfen'
    try:
        locale_ok = regional.read(api) == regional.reference()
        locale_detail = 'Region zurückgelesen' if locale_ok else 'Region geändert / Einrichtung offen — prüfen'
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        locale_ok, locale_detail = False, 'Region nicht prüfbar — prüfen'
    try:
        skin_ok = active_skin(api) == selected.addon_id
        skin_detail = ('Gewählter Skin aktiv zurückgelesen' if skin_ok else
                       'Gewählter Skin nicht aktiv — explizit aktivieren und Kodi Keep-Dialog bestätigen')
        if skin_ok and profile_id in ('touch','nimbus') and api.xbmc.getCondVisibility('Skin.HasSetting(touchmode)') is not True:
            skin_ok = False
            skin_detail = 'Touch-Skin ist aktiv, aber sein nativer Touchmodus ist aus oder nicht bestätigt'
    except (RuntimeError, AttributeError, TypeError):
        skin_ok, skin_detail = False, 'Aktiver Skin nicht prüfbar'
    from .menus import current as menu_current
    menu_ok = profile_id == 'arctic' or (layout and skin_ok and menu_current(profile, profile_id, api))
    menu_detail = ('Native Menüausgabe zurückgelesen' if menu_ok else
                   'Native Menüausgabe fehlt oder veraltet — nach Skinaktivierung nativ neu aufbauen')
    if profile_id == 'arctic':
        menu_detail = 'Arctic: Layoutdateien geprüft, tatsächliche Darstellung bleibt Geräteabnahme'
    update_rows = tuple((r.addon_id, update_rule_reader(r.addon_id) if update_rule_reader else 'unknown')
                        for r in required)
    blocked = tuple(addon + ': ' + rule for addon, rule in update_rows if rule != 'auto-updateable')
    policy = repository_policy(api)
    updates_ok = not blocked and policy.automatic_updates and policy.repository_mode == 1
    update_detail = ('Native Update-Regeln: keine Sperren zurückgelesen' if not blocked else
                     'Update-Regeln nicht bereit: ' + '; '.join(blocked))
    if not updates_ok:
        update_detail += '. Globale Updates sind keine Zusage für einzelne Addons. In Kodi Meine Addons → Repository-Information → Auto-update prüfen; ggf. neueste native Version neu installieren. Danach erneut öffnen. Keine automatische Änderung.'
    return Status(all(item[1] for item in details), layout, locale_ok,
                  layout_detail, locale_detail, details, pending,
                  skin=skin_ok, skin_detail=skin_detail, updates=updates_ok, update_detail=update_detail,
                  menu=menu_ok, menu_detail=menu_detail)
