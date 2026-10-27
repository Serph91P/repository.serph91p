import json
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
from tests.test_setup_wizard import ADDON
from resources.lib.setupwizard.common_layouts import common_payloads
from resources.lib.setupwizard.navigation import empty_bindings
from resources.lib.setupwizard import config as c

REFERENCE = Path(ADDON) / 'resources/templates/arctic-reference.json'


class ArcticReferenceTests(unittest.TestCase):
    def test_full_portable_style_and_native_types_not_just_sidebar_are_applied(self):
        expected = json.loads(REFERENCE.read_text())['settings']
        self.assertGreater(len(expected), 200)
        with tempfile.TemporaryDirectory() as tmp:
            rows = ET.fromstring(common_payloads(Path(tmp), 'arctic', empty_bindings())[c.SKIN_SETTINGS]).findall('setting')
            actual = {s.get('id').lower(): s for s in rows}
            self.assertEqual(len(actual), len(rows))
            for key, setting in expected.items():
                # Navigation is rebound per target, not blindly copied from source.
                if key.lower().endswith(('.shortcut.path', '.shortcut.target', '.name')):
                    continue
                with self.subTest(key=key):
                    self.assertIn(key.lower(), actual)
                    self.assertEqual(actual[key.lower()].get('type'), setting['type'])
                    self.assertEqual(actual[key.lower()].text or '', setting['value'])
            self.assertEqual(actual['skin.settingslevel'].text, '3')
            self.assertEqual(actual['optionstiles.02.include'].text, 'Settings')
            self.assertEqual(actual['focuscolor.name'].text, 'fff4511e')
            self.assertEqual(actual['homeswitcher.1101.toggle'].get('type'), 'string')

    def test_reference_empty_toggles_clear_old_extra_slots_without_false_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); target=root/c.SKIN_SETTINGS; target.parent.mkdir(parents=True)
            target.write_text('<settings version="2">' + ''.join(
                '<setting id="HomeSwitcher.'+slot+'.Toggle" type="string">true</setting>'
                for slot in ('1104','1106','1108')) + '</settings>')
            rows=ET.fromstring(common_payloads(root,'arctic',empty_bindings())[c.SKIN_SETTINGS]).findall('setting')
            values={s.get('id').lower():(s.text or '') for s in rows}
            for slot in ('1104','1106','1108'):
                self.assertEqual(values['homeswitcher.'+slot+'.toggle'],'')

    def test_snapshot_excludes_credentials_instance_nodes_and_generated_caches(self):
        data=json.loads(REFERENCE.read_text())
        for key, row in data['settings'].items():
            self.assertFalse(key.startswith(('SkinConstant.','script-','Shortcuts.')))
            self.assertNotIn('emby_',row['value'])
            self.assertNotIn('http://',row['value'])
            self.assertNotIn('https://',row['value'])
            self.assertNotIn('plugin://',row['value'])
        self.assertEqual(data['locale']['locale.language'],'resource.language.en_gb')
        self.assertEqual(data['locale']['locale.country'],'Central Europe')


if __name__ == '__main__': unittest.main()
