"""Readback, not saved approvals, determines setup readiness."""
import json
from pathlib import Path
import tempfile
import unittest
from tests.test_setup_wizard import Surface
from resources.lib.setupwizard import state
from resources.lib.setupwizard.addons import KodiAddonAPI
from resources.lib.setupwizard.origins import SQLiteOriginReader
from resources.lib.setupwizard.catalog import SQLiteUpdateRuleReader
from resources.lib.setupwizard.profiles import PROFILES
from resources.lib.setupwizard.common_layouts import apply_common_layout
from resources.lib.setupwizard.navigation import empty_bindings


class StateTests(unittest.TestCase):
    def test_fresh_then_atomic_profile_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(state.load(root))
            state.save(root, 'arctic')
            self.assertEqual(state.load(root), 'arctic')
            self.assertEqual(set(json.loads((root / state.PATH).read_text())), {'schema', 'profile'})
            self.assertFalse(state.inspect(root, 'arctic', KodiAddonAPI(Surface(root).modules['xbmc'])).ready)

    def test_live_readback_invalidates_missing_disabled_and_old_addons(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'setupwizard-backups').mkdir()
            apply_common_layout(root, root / 'setupwizard-backups/backup', 'arctic', empty_bindings())
            surface = Surface(root)
            api = KodiAddonAPI(surface.modules['xbmc'], origin_read_fn=SQLiteOriginReader(surface.translate))
            surface.skin = 'skin.arctic.fuse.3'
            self.assertTrue(state.inspect(root, 'arctic', api, SQLiteUpdateRuleReader(surface.translate)).ready)
            for alteration in ('missing', 'disabled', 'old'):
                original = dict(surface.items['skin.arctic.fuse.3'])
                if alteration == 'missing': del surface.items['skin.arctic.fuse.3']
                elif alteration == 'disabled': surface.items['skin.arctic.fuse.3']['enabled'] = False
                else: surface.items['skin.arctic.fuse.3']['version'] = '1.0'
                self.assertFalse(state.inspect(root, 'arctic', api, SQLiteUpdateRuleReader(surface.translate)).ready)
                surface.items['skin.arctic.fuse.3'] = original

    def test_drift_and_locale_are_read_only_and_login_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'setupwizard-backups').mkdir()
            apply_common_layout(root, root / 'setupwizard-backups/backup', 'arctic', empty_bindings())
            surface = Surface(root)
            api = KodiAddonAPI(surface.modules['xbmc'], origin_read_fn=SQLiteOriginReader(surface.translate))
            target = next(root.glob('addon_data/script.skinvariables/**/*.json'))
            target.write_text('[]')
            before = target.read_bytes()
            status = state.inspect(root, 'arctic', api, SQLiteUpdateRuleReader(surface.translate))
            self.assertFalse(status.layout)
            self.assertIn('geändert', status.layout_detail)
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(status.login, 'unknown')
            surface.locale['locale.language'] = 'resource.language.de_de'
            self.assertFalse(state.inspect(root, 'arctic', api, SQLiteUpdateRuleReader(surface.translate)).regional)
            self.assertEqual(surface.commands, [])

    def test_bad_state_and_symlink_are_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state.save(root, 'arctic')
            target = root / state.PATH
            for data in ('{', '{"schema":99,"profile":"arctic"}', '{"schema":1,"profile":"other"}'):
                target.write_text(data)
                with self.assertRaises(ValueError): state.load(root)
            other = root / 'untouched'
            other.write_text('safe')
            target.unlink()
            target.symlink_to(other)
            with self.assertRaises(ValueError): state.load(root)
            with self.assertRaises(ValueError): state.save(root, 'amber')
            self.assertEqual(other.read_text(), 'safe')

    def test_symlink_ancestor_and_api_error_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / 'outside'
            outside.mkdir()
            (root / 'addon_data').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError): state.save(root, 'arctic')
            self.assertEqual(list(outside.iterdir()), [])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            surface = Surface(root)
            surface.bad_response = True
            self.assertFalse(state.inspect(root, 'arctic', KodiAddonAPI(surface.modules['xbmc'], origin_read_fn=SQLiteOriginReader(surface.translate))).ready)

    def test_all_profiles_are_verified_from_generated_files(self):
        for key in ('arctic', 'amber', 'touch'):
            with self.subTest(profile=key), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'setupwizard-backups').mkdir()
                apply_common_layout(root, root / 'setupwizard-backups/backup', key, empty_bindings())
                surface = Surface(root)
                api = KodiAddonAPI(surface.modules['xbmc'], origin_read_fn=SQLiteOriginReader(surface.translate))
                surface.skin = next(p.addon_id for p in PROFILES if p.key == key)
                surface.touchmode = key == 'touch'
                self.assertTrue(state.inspect(root, key, api, SQLiteUpdateRuleReader(surface.translate)).ready)
                binding = root / ('addon_data/script.serph91p.setup/bindings-' + key + '.json')
                binding.write_text('{bad')
                self.assertFalse(state.inspect(root, key, api, SQLiteUpdateRuleReader(surface.translate)).ready)


if __name__ == '__main__': unittest.main()
