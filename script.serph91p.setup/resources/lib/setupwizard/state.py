"""Small resumable preference record; completion is always live readback.

No credentials, account flags or trusted completion booleans are persisted.
Unknown/corrupt records fail closed, never becoming a new-install instruction.
"""
from dataclasses import dataclass
import json
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
