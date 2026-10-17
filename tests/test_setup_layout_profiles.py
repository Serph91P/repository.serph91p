"""Portable layout/runtime policy tests. Kodi is emulated, not device-approved."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from unittest.mock import patch

ADDON = Path(__file__).resolve().parents[1] / 'script.serph91p.setup'
sys.path.insert(0, str(ADDON))
from resources.lib.setupwizard import config, layouts, touch
from tests.test_setup_wizard import Surface


class LayoutProfileTests(unittest.TestCase):
    def test_amber_apply_readback_and_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = root / 'setupwizard-backups' / 'amber'
            backup.parent.mkdir()
            path = root / config.AMBER_MENU
            path.parent.mkdir(parents=True)
            old = b'<shortcuts><shortcut><label>Existing custom entry</label></shortcut></shortcuts>'
            path.write_bytes(old)
            changed = layouts.apply_layout(root, backup, 'amber')
            self.assertEqual(changed, [config.AMBER_MENU])
            xml = ET.parse(path).getroot()
            actions = [n.findtext('action') for n in xml.findall('shortcut')]
            self.assertTrue(all(a in actions for _, a in layouts.NAVIGATION))
            self.assertFalse((root / config.SKIN_SETTINGS).exists())
            self.assertEqual(config.rollback(root, backup), [config.AMBER_MENU])
            self.assertEqual(path.read_bytes(), old)

    def test_amber_drift_and_profile_manifest_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = root / 'setupwizard-backups' / 'amber'
            backup.parent.mkdir()
            layouts.apply_layout(root, backup, 'amber')
            path = root / config.AMBER_MENU
            path.write_text('user edit')
            with self.assertRaises(config.LayoutConflict):
                config.rollback(root, backup)
            manifest = backup / config.MANIFEST
            data = json.loads(manifest.read_text())
            data['profile'] = 'touch'
            manifest.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                config.rollback(root, backup)
            self.assertEqual(path.read_text(), 'user edit')

    def test_profile_payload_policy_rejects_private_or_cross_skin_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for data in ({'favourites.xml': b'cached'}, {config.SKIN_SETTINGS: b'other-skin'}):
                with self.assertRaises(ValueError):
                    config.apply_payloads(root, root/'setupwizard-backups'/'x', data, 'amber')
            self.assertEqual(layouts.apply_layout(root, root/'setupwizard-backups'/'x', 'touch'), [])
            self.assertEqual(list(root.iterdir()), [])

    def test_smartplaylists_and_navigation_targets(self):
        for file, typ in [('continue-movies.xsp', 'movies'), ('continue-episodes.xsp', 'episodes')]:
            root = ET.parse(ADDON/'resources'/'playlists'/file).getroot()
            self.assertEqual(root.attrib['type'], typ)
            self.assertEqual(root.find('rule').attrib, {'field':'inprogress','operator':'true'})
        self.assertFalse(any('http' in a or 'password' in a for _, a in layouts.NAVIGATION))

    def test_amber_entrypoint_layout_and_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            surface = Surface(root, [1, 3, 0, 6], profile_index=1)
            surface.run()
            self.assertFalse((root/config.AMBER_MENU).exists())
            self.assertTrue(any('wiederhergestellt' in str(x) for x in surface.dialogs))
            self.assertEqual(surface.commands, [])

    def test_touch_entrypoint_apply_and_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            surface = Surface(Path(tmp), [1, 3, 0, 6], profile_index=2)
            surface.run()
            self.assertEqual(surface.commands, ['Skin.SetBool(touchmode)', 'Skin.Reset(touchmode)'])
            self.assertFalse(surface.touchmode)
            self.assertFalse((Path(tmp)/config.SKIN_SETTINGS).exists())

    def test_touch_mode_backup_noop_and_manifest_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            surface = Surface(root)
            xbmc = surface.modules['xbmc']
            backup = root/'setupwizard-backups'/'touch'
            self.assertTrue(touch.enable_touch(root, backup, xbmc))
            self.assertTrue(surface.touchmode)
            self.assertEqual(touch.enable_touch(root, root/'setupwizard-backups'/'noop', xbmc), [])
            self.assertFalse((root/'setupwizard-backups'/'noop').exists())
            data = dict(touch.STATE, after='true')
            (backup/config.MANIFEST).write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                touch.restore_touch(root, backup, xbmc)
            self.assertTrue(surface.touchmode)

    def test_touch_activation_failure_preserves_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            surface = Surface(root)
            xbmc = surface.modules['xbmc']
            backup = root/'setupwizard-backups'/'touch'
            with patch.object(xbmc, 'executebuiltin', return_value=None):
                with self.assertRaises(RuntimeError):
                    touch.enable_touch(root, backup, xbmc)
            self.assertTrue((backup/config.MANIFEST).exists())
            self.assertEqual(touch.restore_touch(root, backup, xbmc), [])

    def test_touch_requires_estuary_and_rejects_symlink_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            surface = Surface(root, skin='skin.amber')
            with self.assertRaises(ValueError):
                touch.enable_touch(root, root/'setupwizard-backups'/'bad', surface.modules['xbmc'])
            self.assertEqual(surface.commands, [])
            (root/'setupwizard-backups').symlink_to(root, target_is_directory=True)
            surface.skin = 'skin.estuary'
            with self.assertRaises(ValueError):
                touch.enable_touch(root, root/'setupwizard-backups'/'bad', surface.modules['xbmc'])

    def test_non_video_services_open_settings_not_fake_plugin_routes(self):
        for index, addon in [(4, 'script.tubecast'), (5, 'pvr.iptvsimple')]:
            with self.subTest(addon=addon), tempfile.TemporaryDirectory() as tmp:
                surface = Surface(Path(tmp), [2, index, 6])
                surface.run()
                self.assertEqual(surface.settings, [addon])
                self.assertEqual(surface.commands, [])

    def test_shared_navigation_entrypoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            surface = Surface(Path(tmp), [7, 0, 6], profile_index=2)
            surface.run()
            self.assertEqual(surface.commands, [layouts.NAVIGATION[0][1]])

if __name__ == '__main__':
    unittest.main()
