"""Profile policy and shared media add-on contract tests."""
import sys
import unittest
import tempfile
from pathlib import Path

ADDON = Path(__file__).resolve().parents[1] / 'script.serph91p.setup'
sys.path.insert(0, str(ADDON))
from resources.lib.setupwizard.addons import (MEDIA_REQUIREMENTS, PROFILE_REQUIREMENTS,
                                               REQUIREMENTS)
from resources.lib.setupwizard.profiles import PROFILES, requirements_for
from tests.test_setup_wizard import Surface

class ProfileTests(unittest.TestCase):
    def test_profile_versions_and_scoped_requirements(self):
        by_key = {p.key: p for p in PROFILES}
        self.assertEqual(by_key['amber'].minimum, (3, 99, 2))
        self.assertTrue(by_key['amber'].layout_supported)
        self.assertEqual(by_key['touch'].minimum, (4, 0, 0))
        self.assertTrue(by_key['touch'].layout_supported)
        self.assertIn('2024', by_key['touch'].warning)
        amber = requirements_for(by_key['amber'], REQUIREMENTS, PROFILE_REQUIREMENTS, MEDIA_REQUIREMENTS)
        self.assertEqual([r.addon_id for r in amber], ['skin.amber'] + [r.addon_id for r in MEDIA_REQUIREMENTS])
        touch = requirements_for(by_key['touch'], REQUIREMENTS, PROFILE_REQUIREMENTS, MEDIA_REQUIREMENTS)
        self.assertEqual([r.addon_id for r in touch], ['skin.estuary'] + [r.addon_id for r in MEDIA_REQUIREMENTS])
        self.assertNotIn('script.skinvariables', [r.addon_id for r in touch])

    def test_shared_media_addons_are_allowlisted(self):
        by_id = {r.addon_id: r.min_version for r in MEDIA_REQUIREMENTS}
        self.assertEqual(by_id['plugin.service.emby-next-gen'], (12, 4, 23))
        self.assertEqual(by_id['plugin.video.twitch'], (3, 1, 11))
        self.assertEqual(by_id['plugin.video.youtube'], (7,))
        self.assertEqual(by_id['plugin.video.gronkhtv'], (2, 3, 7))
        self.assertIn('script.tubecast', by_id)
        self.assertIn('pvr.iptvsimple', by_id)

    def test_amber_entrypoint_installs_only_amber_and_shared_addons(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Selection 1 chooses Amber; then install, exit. Parent Surface installs
            # only IDs the profile flow requests through supported Kodi builtins.
            surface = Surface(Path(tmp), [0, 6], ready=False, profile_index=1)
            surface.run()
            installed = set(surface.items)
            expected = {'skin.amber'} | {r.addon_id for r in MEDIA_REQUIREMENTS}
            self.assertEqual(installed, expected)
            self.assertNotIn('skin.arctic.fuse.3', installed)
            self.assertNotIn('script.skinvariables', installed)

if __name__ == '__main__':
    unittest.main()