"""Current original Nimbus helper and side-effect-free compatibility feedback."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'script.serph91p.setup'))
from resources.lib.setupwizard import adams, state
from tests.test_setup_flow import guided


class AdamsRuntimeTests(unittest.TestCase):
    def test_current_original_helper99_and_previous98_are_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            for version in ('0.0.98', '0.0.99'):
                with self.subTest(version=version):
                    api = SimpleNamespace(details=lambda _id: {'version': version})
                    adams.validate_runtime(api, 'nimbus', lambda _path: tmp)

    def test_unknown_or_unreadable_helper_is_not_wildcard_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            for details in (None, {}, {'version': '0.0.100'}, {'version': '0.1.0'},
                            {'version': '0.0.99+unverified'}, {'version': ['0.0.99']}):
                with self.subTest(details=details):
                    api = SimpleNamespace(details=lambda _id: details)
                    with self.assertRaises(ValueError):
                        adams.validate_runtime(api, 'nimbus', lambda _path: tmp)

    def test_rotary_has_no_nimbus_helper_requirement(self):
        def details(_id):
            self.fail('Rotary must not inspect the Nimbus helper')
        adams.validate_runtime(SimpleNamespace(details=details), 'rotary', None)

    def test_current_helper_still_cannot_write_keymap_in_another_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = SimpleNamespace(details=lambda _id: {'version': '0.0.99'})
            with self.assertRaisesRegex(ValueError, 'Standardprofil'):
                adams.validate_runtime(api, 'nimbus',
                    lambda path: str(Path(tmp) / ('master' if path == 'special://userdata' else 'other')))

    def test_unsupported_helper_explained_before_asking_to_leave_active_skin(self):
        self._unsupported_flow('skin.nimbus')

    def test_unsupported_helper_in_estuary_is_not_a_userdata_restore_failure(self):
        self._unsupported_flow('skin.estuary')

    def _unsupported_flow(self, active):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state.save(root, 'nimbus')
            private = root / 'addon_data/plugin.video.youtube/settings.xml'
            private.parent.mkdir(parents=True)
            private.write_bytes(b'synthetic-device-local-placeholder')
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            surface = guided(root, [0], skin=active)
            surface.items['script.nimbus.helper']['version'] = '0.0.100'
            surface.run()
            message = '\n'.join(str(item) for item in surface.dialogs)
            self.assertIn('0.0.100', message)
            self.assertIn('Nimbus', message)
            self.assertNotIn('Restore', message)
            self.assertNotIn('Details: ValueError', message)
            self.assertNotIn('zuerst manuell Estuary', message)
            self.assertEqual(surface.commands, [])
            self.assertFalse((root / 'setupwizard-backups').exists())
            self.assertEqual({str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}, before)


if __name__ == '__main__':
    unittest.main()
