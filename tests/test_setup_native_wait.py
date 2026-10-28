"""Native UI wait state machine: no dialog closing is installation evidence."""
import unittest
from types import SimpleNamespace
from tests.test_setup_wizard import Surface  # Establish the addon import root.
from resources.lib.setupwizard.migration import await_native_change


class Timeline:
    def __init__(self, rows, *, abort=False):
        self.rows, self.index, self.elapsed, self.aborting = rows, 0, 0., abort
        self.gui = SimpleNamespace(getCurrentWindowId=lambda: self.row.get('window', 10040),
            getCurrentWindowDialogId=lambda: self.row.get('dialog', 9999))
        self.xbmc = SimpleNamespace(getCondVisibility=lambda condition:
            self.row.get('background', False) and condition == 'Window.IsVisible(10151)')
    @property
    def row(self): return self.rows[min(self.index, len(self.rows)-1)]
    def abortRequested(self): return self.aborting
    def waitForAbort(self, seconds):
        self.elapsed += seconds
        self.index += 1
        return self.aborting
    def run(self, timeout=8):
        return await_native_change(lambda: self.row.get('ready', False), self, self.gui, self.xbmc,
            timeout=timeout, clock=lambda: self.elapsed)


class NativeWaitTests(unittest.TestCase):
    def test_success_requires_live_state_and_no_modal_or_background_job(self):
        timeline = Timeline([{'dialog':10146}, {'dialog':12000},
            {'ready':True, 'background':True}, {'ready':True}])
        self.assertTrue(timeline.run())
        self.assertEqual(timeline.index, 3)

    def test_versions_or_dependency_cancel_pauses_without_infinite_wait(self):
        timeline = Timeline([{'dialog':12000}, {}])
        self.assertFalse(timeline.run(timeout=900))
        self.assertLess(timeline.elapsed, 3)

    def test_background_refresh_does_not_count_as_a_cancelled_user_dialog(self):
        timeline = Timeline([{'background':True}] + [{} for _ in range(18)] + [{'ready':True}])
        self.assertTrue(timeline.run())

    def test_back_from_native_list_pauses_with_no_success_claim(self):
        timeline = Timeline([{}, {'window':10000}])
        self.assertFalse(timeline.run())
        self.assertEqual(timeline.index, 1)

    def test_dialog_close_alone_is_not_success(self):
        timeline = Timeline([{'dialog':10146}, {}])
        self.assertFalse(timeline.run())

    def test_background_install_without_verified_state_can_only_timeout(self):
        timeline = Timeline([{'background':True}])
        self.assertFalse(timeline.run(timeout=1))
        self.assertLess(timeline.elapsed, 2)

    def test_shutdown_stops_without_wait_or_success(self):
        timeline = Timeline([{'ready':True}], abort=True)
        self.assertFalse(timeline.run())
        self.assertEqual(timeline.index, 0)

    def test_unopened_or_unknown_native_ui_fails_closed(self):
        timeline = Timeline([{'window':10000}])
        self.assertFalse(timeline.run(timeout=30))
        self.assertLess(timeline.elapsed, 11)
        invalid = Timeline([{'dialog':None, 'ready':True}])
        self.assertFalse(invalid.run())


if __name__=='__main__': unittest.main()
