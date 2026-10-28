"""Regressions for user-visible native handoff and refusal, no real installs."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock
from tests.test_setup_wizard import Surface
from tests.test_setup_migration import API
from resources.lib.setupwizard.addons import KodiAddonAPI, REQUIREMENTS_BY_ID, ensure_requirement
from resources.lib.setupwizard.migration import inspect_existing, guide_native_migration


class NativeContinuationTests(unittest.TestCase):
    def test_completed_native_migration_continues_without_relaunch(self):
        req = REQUIREMENTS_BY_ID['skin.amber']
        api = API(origin='', version='4.0')
        before = inspect_existing(api, req)
        dialog = Mock()
        dialog.yesno.return_value = True
        def native_selection(_command):
            # The native action finished before returning to Python.
            api.source = 'repository.xbmc.org'
        self.assertTrue(guide_native_migration(api, before, dialog,
            lambda _: ('4.0',), native_selection))

    def test_native_no_does_not_enter_wait_for_missing_addon(self):
        with TemporaryDirectory() as tmp:
            surface = Surface(Path(tmp), ready=False)
            calls = []
            # Simulate a native operation which returns after No without an install.
            surface.modules['xbmc'].executebuiltin = lambda command, wait=False: calls.append((command, wait))
            api = KodiAddonAPI(surface.modules['xbmc'])
            waiting = Mock(return_value=False)
            self.assertFalse(ensure_requirement(api, REQUIREMENTS_BY_ID['skin.amber'],
                lambda _: True, waiting, lambda _: None))
            waiting.assert_not_called()
            self.assertEqual(calls, [('InstallAddon(skin.amber)', True)])


if __name__ == '__main__':
    unittest.main()
