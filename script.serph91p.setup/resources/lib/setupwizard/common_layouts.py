"""Skin-specific adapters for the single LibreELEC-reference media menu."""
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from .config import (SKIN_NODE, SKIN_SETTINGS, SAFE_SETTINGS, ARCTIC_REFERENCE_ICONS, POLICIES, COMMON_POLICY_IDS,
                     _profile, _target, _merge_skin_settings, apply_payloads, MAX_FILE_BYTES)
from .navigation import groups, action, group_action, binding_path, binding_bytes


def _json(rows):
    return (json.dumps(rows, ensure_ascii=False, indent=2) + '\n').encode()


def _shortcut(root, label, builtin, identity, properties=()):
    node = ET.SubElement(root, 'shortcut')
    for key, value in (('label', label), ('label2', 'Serph91P Setup'),
                       ('defaultID', identity), ('icon', 'DefaultVideo.png'),
                       ('action', builtin)):
        ET.SubElement(node, key).text = value
    ET.SubElement(node, 'additional-properties').text = repr(list(properties))
    return node


def _xml(root):
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def _existing_skin_settings(target):
    if not target.exists():
        return None
    if target.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('skin settings exceed safe size limit')
    data = target.read_bytes()
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('skin settings declarations are not supported')
    return data


def common_payloads(profile, profile_id, bindings):
    profile = _profile(profile)
    media = groups(bindings)
    payload = {binding_path(profile_id): binding_bytes(bindings)}
    if profile_id == 'arctic':
        reference = json.loads((Path(__file__).resolve().parents[2] / 'templates/arctic-reference.json').read_text())
        if reference.get('schema') != 1 or reference.get('skin') != 'skin.arctic.fuse.3':
            raise ValueError('invalid Arctic reference')
        settings = {key: row['value'] for key, row in reference['settings'].items()}
        types = {key.lower(): row['type'] for key, row in reference['settings'].items()}
        settings.update(SAFE_SETTINGS)
        settings.update(ARCTIC_REFERENCE_ICONS)
        # Reference LibreELEC has native PVR slot1107 enabled; Kodi hides it until channels exist.
        settings['HomeSwitcher.1107.Toggle'] = 'true'
        for slot, group in zip(('home', '1101', '1102', '1103'), media):
            widgets = [{'label': item.label, 'icon': '', 'path': item.path, 'target': item.target}
                       for item in group.items if item.target == 'videos' and item.path is not None]
            submenu = [{'label': item.label, 'icon': '',
                        'path': item.path if item.target == 'videos' else action(item),
                        'target': 'videos' if item.target == 'videos' else ''}
                       for item in group.items]
            payload[SKIN_NODE + 'skinvariables-shortcut-' + slot + 'widgets.json'] = _json(widgets)
            payload[SKIN_NODE + 'skinvariables-shortcut-' + slot + 'submenu.json'] = _json(submenu)
            prefix = 'HomeSwitcher.' + ('Home' if slot == 'home' else slot)
            settings[prefix + '.Name'] = group.label
            if slot != 'home':
                settings[prefix + '.Shortcut.Path'] = group_action(group, profile_id)
                settings[prefix + '.Shortcut.Target'] = ''
        target = _target(profile, SKIN_SETTINGS)
        payload[SKIN_SETTINGS] = _merge_skin_settings(
            _existing_skin_settings(target), settings, types)
    elif profile_id in ('amber', 'touch'):
        prefix = 'skin.amber-' if profile_id == 'amber' else ''
        root_path = 'addon_data/script.skinshortcuts/' + prefix
        main = ET.Element('shortcuts')
        for group in media:
            properties = []
            if profile_id == 'amber':
                # Amber's six native shelf families start unnumbered, then .2–.6.
                # Explicitly disable unused slots, including movie preset defaults.
                items = [item for item in group.items if item.target == 'videos' and item.path is not None]
                for number in range(1, 7):
                    suffix = '' if number == 1 else '.' + str(number)
                    if number > len(items):
                        fields = (('widget', 'None'), ('widgetType', 'none'),
                                  ('widgetTarget', 'false'), ('widgetPath', ''))
                    else:
                        item = items[number - 1]
                        kind = ('movies' if group.key == 'movies' else
                                'episodes' if group.key == 'series' and item.label in ('Fortsetzen', 'Neu')
                                else 'tvshows' if group.key == 'series' else 'videos')
                        artwork = ('Square' if item.label == 'Genres' else
                                   'Poster' if kind in ('movies', 'tvshows') else 'Thumb')
                        source = ('Addon' if item.path.startswith('plugin://') else
                                  'Playlist' if item.path.endswith('.xsp') else 'Library')
                        fields = (('widget', source), ('widgetName', item.label),
                                  ('widgetType', kind), ('widgetTarget', 'video'),
                                  ('widgetPath', item.path), ('widgetArtwork', artwork),
                                  ('widgetLimit', '$NUMBER[25]'))
                    properties.extend([key + suffix, value] for key, value in fields)
            if profile_id == 'touch':
                properties.append(['widget', 'LiveTVWidget' if group.key == 'livetv' else 'PersonalWidgetList'])
                widget_items = [item for item in group.items if item.target == 'videos' and item.path is not None]
                for number, item in enumerate(widget_items if group.key != 'livetv' else (), 1):
                    aspect = ('135' if item.label == 'Genres' else
                              '31338' if group.key in ('movies', 'series') else '31339')
                    for key, value in (('widgetName', item.label), ('widgetPath', item.path),
                                       ('widgetTarget', item.target), ('widgetAspect', aspect),
                                       ('widgetSortBy', 'none'), ('widgetSortDirection', 'ascending')):
                        properties.append([key + '.' + str(number), value])
            node = _shortcut(main, group.label, group_action(group, profile_id), group.key, properties)
            if group.key == 'livetv':
                ET.SubElement(node, 'visible').text = 'System.HasPVRAddon + PVR.HasTVChannels'
            submenu = ET.Element('shortcuts')
            for index, item in enumerate(group.items):
                _shortcut(submenu, item.label, action(item), group.key + '-' + str(index))
            payload[root_path + group.key + '.DATA.xml'] = _xml(submenu)
        for label, builtin, identity in (
            ('Setup-Assistent', 'RunScript(script.serph91p.setup)', 'setup'),
            ('Einstellungen', 'ActivateWindow(Settings)', 'settings')):
            _shortcut(main, label, builtin, identity)
        payload[root_path + 'mainmenu.DATA.xml'] = _xml(main)
        if profile_id == 'touch':
            # Honor either existing Shared-menu preference without changing it.
            for path, content in list(payload.items()):
                if path.startswith(root_path):
                    payload[root_path + 'skin.estuary.modv2-' + path[len(root_path):]] = content
            rel = 'addon_data/skin.estuary.modv2/settings.xml'
            target = _target(profile, rel)
            existing = _existing_skin_settings(target)
            settings = ET.fromstring(existing) if existing is not None else ET.Element('settings', {'version': '2'})
            if settings.tag != 'settings':
                raise ValueError('invalid MOD V2 settings root')
            for old in list(settings.findall('setting')):
                if old.get('id', '').lower() == 'touchmode':
                    settings.remove(old)
            ET.SubElement(settings, 'setting', {'id': 'touchmode', 'type': 'bool'}).text = 'true'
            payload[rel] = _xml(settings)
    elif profile_id in ('rotary','nimbus'):
        from .adams import payloads
        payload.update(payloads(profile,profile_id,bindings))
    else:
        raise ValueError('unknown skin profile')
    if set(payload) != POLICIES[COMMON_POLICY_IDS[profile_id]]:
        raise ValueError('adapter payload does not match its exact policy')
    return payload


def apply_common_layout(profile, backup, profile_id, bindings):
    return apply_payloads(profile, backup, common_payloads(profile, profile_id, bindings),
                          COMMON_POLICY_IDS[profile_id])
