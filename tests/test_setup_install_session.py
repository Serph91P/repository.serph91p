"""Exact ongoing consent survives restart; completion is always live state."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from tests.test_setup_wizard import Surface
from resources.lib.setupwizard import state
from resources.lib.setupwizard.addons import KodiAddonAPI, REQUIREMENTS_BY_ID, check_requirement


class InstallationSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.surface=Surface(self.root);self.api=KodiAddonAPI(self.surface.modules['xbmc'])
        self.required=(REQUIREMENTS_BY_ID['skin.amber'],)
    def read(self, profile='amber', required=None):
        return state.installation_session(self.root, profile, self.required if required is None else required, self.api)
    def test_missing_active_paused_and_clear(self):
        self.assertIsNone(self.read())
        state.remember_installation(self.root, 'amber', self.required, self.api)
        self.assertEqual(self.read(), 'active')
        data=json.loads((self.root/state.INSTALL_PATH).read_text())
        self.assertEqual(set(data), {'schema','profile','scope','active'})
        self.assertNotIn('skin.amber',json.dumps(data))  # No arbitrary commands or per-addon ready flags.
        state.remember_installation(self.root, 'amber', self.required, self.api, active=False)
        self.assertEqual(self.read(), 'paused')
        state.clear_installation(self.root)
        self.assertIsNone(self.read())
    def test_changed_profile_or_scope_is_not_approved(self):
        state.remember_installation(self.root, 'amber', self.required, self.api)
        self.assertIsNone(self.read('arctic'))
        self.assertIsNone(self.read(required=self.required+(REQUIREMENTS_BY_ID['plugin.video.youtube'],)))
    def test_state_cannot_mark_a_missing_addon_ready(self):
        state.remember_installation(self.root, 'amber', self.required, self.api)
        del self.surface.items['skin.amber']
        self.assertEqual(self.read(), 'active')
        self.assertFalse(check_requirement(self.api, self.required[0])[0])
    def test_corrupt_unknown_huge_or_symlinked_record_refuses_actions(self):
        state.remember_installation(self.root, 'amber', self.required, self.api)
        path=self.root/state.INSTALL_PATH;valid=path.read_text()
        for text in ('{broken',valid.replace('"schema": 1','"schema": 99'),
                     valid.replace('"active": true','"active": 1'),'x'*4097):
            path.write_text(text)
            with self.assertRaises(ValueError):self.read()
        path.write_text(valid);other=path.with_name('other.json');path.rename(other);path.symlink_to(other)
        with self.assertRaises(ValueError):self.read()
        with self.assertRaises(ValueError):state.clear_installation(self.root)
        self.assertEqual(other.read_text(),valid)


if __name__=='__main__':unittest.main()
