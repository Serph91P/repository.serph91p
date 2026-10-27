"""One wizard-owned consent for a fixed, profile-scoped installation batch."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from tests.test_setup_wizard import Surface
from resources.lib.setupwizard.addons import (REQUIREMENTS, PROFILE_REQUIREMENTS,
                                               MEDIA_REQUIREMENTS)
from resources.lib.setupwizard.profiles import PROFILES, requirements_for
from resources.lib.setupwizard.ui import install_with_progress


class BatchConsentTests(unittest.TestCase):
    def test_one_wizard_confirmation_lists_and_installs_every_profile_requirement(self):
        for index, profile in enumerate(p for p in PROFILES if not p.retired):
            with self.subTest(profile=profile.key), tempfile.TemporaryDirectory() as tmp:
                surface = Surface(Path(tmp), [0, 6], ready=False, profile_index=index)
                confirmations = []
                def yesno(_self, *args):
                    if 'Komplettsetup für' in str(args):confirmations.append(args)
                    return True
                surface.modules['xbmcgui'].Dialog.yesno = yesno
                surface.run()
                self.assertEqual(len(confirmations), 1)
                message = str(confirmations[0])
                required = requirements_for(profile, REQUIREMENTS, PROFILE_REQUIREMENTS, MEDIA_REQUIREMENTS)
                for req in required:
                    self.assertIn(req.label, message)
                    self.assertIn(req.addon_id, surface.items)
                self.assertIn('Kodi', message)
                self.assertTrue(any('Alle benötigten Addons' in str(x) for x in surface.dialogs))
                self.assertEqual(surface.progress_events[-1], ('close',))

    def test_declining_batch_does_not_refresh_install_or_enable(self):
        with tempfile.TemporaryDirectory() as tmp:
            surface = Surface(Path(tmp), [0, 6], ready=False)
            initial_items = dict(surface.items)
            confirmations = []
            def yesno(_self, *args):
                confirmations.append(args)
                return False
            surface.modules['xbmcgui'].Dialog.yesno = yesno
            surface.run()
            self.assertEqual(len(confirmations), 1)
            self.assertEqual(surface.commands, [])
            self.assertEqual(surface.progress_events, [])
            self.assertEqual(surface.items, initial_items)

    def test_unapproved_direct_batch_is_rejected_without_actions(self):
        api, dialog, monitor, progress = Mock(), Mock(), Mock(), Mock()
        okay, detail = install_with_progress(api, REQUIREMENTS, dialog, monitor, progress, lambda _: None)
        self.assertFalse(okay)
        self.assertIn('freigegeben', detail)
        self.assertEqual(api.mock_calls, [])
        self.assertEqual(dialog.mock_calls, [])
        self.assertEqual(progress.mock_calls, [])


if __name__ == '__main__': unittest.main()
