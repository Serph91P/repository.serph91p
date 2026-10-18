"""Skin-specific adapters for the single LibreELEC-reference media menu."""
import json
from xml.etree import ElementTree as ET
from .config import (SKIN_NODE, SKIN_SETTINGS, SAFE_SETTINGS, POLICIES,
                     _profile, _target, _merge_skin_settings, apply_payloads)
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


def common_payloads(profile, profile_id, bindings):
    profile = _profile(profile)
    media = groups(bindings)
    payload = {binding_path(profile_id): binding_bytes(bindings)}
    if profile_id == 'arctic':
        settings = dict(SAFE_SETTINGS)
        for slot, group in zip(('home', '1101', '1102', '1103'), media):
            rows = [{'label': item.label, 'icon': '', 'path': item.path, 'target': item.target}
                    for item in group.items]
            for kind in ('widgets', 'submenu'):
                payload[SKIN_NODE + 'skinvariables-shortcut-' + slot + kind + '.json'] = _json(rows)
            prefix = 'HomeSwitcher.' + ('Home' if slot == 'home' else slot)
            settings[prefix + '.Name'] = group.label
            if slot != 'home':
                settings[prefix + '.Shortcut.Path'] = group_action(group, profile_id)
                settings[prefix + '.Shortcut.Target'] = ''
        target = _target(profile, SKIN_SETTINGS)
        payload[SKIN_SETTINGS] = _merge_skin_settings(
            target.read_bytes() if target.exists() else None, settings)
    elif profile_id in ('amber', 'touch'):
        prefix = 'skin.amber-' if profile_id == 'amber' else ''
        root_path = 'addon_data/script.skinshortcuts/' + prefix
        main = ET.Element('shortcuts')
        for group in media:
            properties = []
            if profile_id == 'touch':
                properties.append(['widget', 'PersonalWidgetList'])
                for number, item in enumerate(group.items, 1):
                    aspect = ('135' if item.label == 'Genres' else
                              '31338' if group.key in ('movies', 'series') else '31339')
                    for key, value in (('widgetName', item.label), ('widgetPath', item.path),
                                       ('widgetTarget', item.target), ('widgetAspect', aspect),
                                       ('widgetSortBy', 'none'), ('widgetSortDirection', 'ascending')):
                        properties.append([key + '.' + str(number), value])
            _shortcut(main, group.label, group_action(group, profile_id), group.key, properties)
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
            rel = 'addon_data/skin.estuary.modv2/settings.xml'
            target = _target(profile, rel)
            settings = ET.fromstring(target.read_bytes()) if target.exists() else ET.Element('settings', {'version': '2'})
            if settings.tag != 'settings':
                raise ValueError('invalid MOD V2 settings root')
            for old in list(settings.findall('setting')):
                if old.get('id', '').lower() == 'touchmode':
                    settings.remove(old)
            ET.SubElement(settings, 'setting', {'id': 'touchmode', 'type': 'bool'}).text = 'true'
            payload[rel] = _xml(settings)
    else:
        raise ValueError('unknown skin profile')
    if set(payload) != POLICIES[profile_id + '-common']:
        raise ValueError('adapter payload does not match its exact policy')
    return payload


def apply_common_layout(profile, backup, profile_id, bindings):
    return apply_payloads(profile, backup, common_payloads(profile, profile_id, bindings),
                          profile_id + '-common')
