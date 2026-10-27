"""Regressions for the actual AF3 sidebar placeholders reported by the user."""
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
from tests.test_setup_wizard import ADDON
from resources.lib.setupwizard.common_layouts import common_payloads
from resources.lib.setupwizard.navigation import empty_bindings
from resources.lib.setupwizard.config import SKIN_SETTINGS

# Verified portable icon choices from the supplied LibreELEC reference backup,
# consumed by AF3 3.3.12 Includes_Home.xml:9-27. No library/server IDs.
REFERENCE_ICONS = {
    'HomeSwitcher.Home.Icon': 'film.png',
    'HomeSwitcher.1101.Icon': 'director.png',
    'HomeSwitcher.1102.Icon': 'twitch.png',
    'HomeSwitcher.1103.Icon': 'youtube.png',
    'HomeSwitcher.1104.Icon': 'folder.png',
}


class ArcticIconTests(unittest.TestCase):
    def test_native_slots_receive_reference_icons_not_shape_fallbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = common_payloads(Path(tmp), 'arctic', empty_bindings())
            root = ET.fromstring(payload[SKIN_SETTINGS])
            settings = {s.get('id').lower(): s for s in root.findall('setting')}
            for key, filename in REFERENCE_ICONS.items():
                with self.subTest(setting=key):
                    self.assertIn(key.lower(), settings)
                    row = settings[key.lower()]
                    self.assertEqual(row.get('type'), 'string')
                    self.assertEqual(row.text, 'special://skin/extras/icons/' + filename)
            self.assertEqual(settings['homeswitcher.enableicons'].get('type'), 'bool')
            self.assertEqual(settings['homeswitcher.enableicons'].text, 'true')
            self.assertFalse(any(('homeswitcher.' + str(n) + '.icon') in settings
                                 for n in (1106, 1107, 1108, 1109)))

    def test_existing_placeholder_icons_are_replaced_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / SKIN_SETTINGS
            target.parent.mkdir(parents=True)
            target.write_text('<settings version="2"><setting id="homeswitcher.1101.icon" '
                'type="string">special://skin/extras/icons/shapes.png</setting>'
                '<setting id="unrelated.custom" type="string">preserve</setting></settings>')
            payload = common_payloads(root, 'arctic', empty_bindings())
            rows = ET.fromstring(payload[SKIN_SETTINGS]).findall('setting')
            selected = [s for s in rows if s.get('id').lower() == 'homeswitcher.1101.icon']
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0].text, 'special://skin/extras/icons/director.png')
            self.assertEqual(next(s.text for s in rows if s.get('id') == 'unrelated.custom'), 'preserve')
            self.assertIn('shapes.png', target.read_text())  # Generation did not edit the device.


if __name__ == '__main__': unittest.main()
