"""Guided default entry point; mocks are not on-device acceptance."""
from pathlib import Path
import tempfile
import unittest
from tests.test_setup_wizard import Surface, seed_nodes
from resources.lib.setupwizard import state


def guided(root, selections=(), **kwargs):
    surface = Surface(root, **kwargs)
    answers = iter(selections)
    surface.questions, surface.approvals = [], []
    def select(_self, title, labels):
        surface.questions.append((title, labels))
        return next(answers, -1)
    def yesno(_self, *args):
        surface.approvals.append(args)
        return True
    surface.modules['xbmcgui'].Dialog.select = select
    surface.modules['xbmcgui'].Dialog.yesno = yesno
    return surface


class FlowTests(unittest.TestCase):
    def test_fresh_guided_and_reopen_without_skin_or_setup_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = guided(root, [0, 0], ready=False)
            first.run()
            self.assertEqual(state.load(root), 'arctic')
            self.assertTrue(any('Medienmenü geschrieben' in str(d) for d in first.dialogs))
            again = guided(root, skin='skin.arctic.fuse.3')
            again.run()
            self.assertFalse(any('Skin-Profil wählen' in title for title, _ in again.questions))
            self.assertEqual(again.approvals, [])
            self.assertEqual(again.commands, [])
            self.assertTrue(any('zurückgelesen' in title for title, _ in again.questions))

    def test_partial_resume_does_not_repeat_addon_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = guided(root, [0, 0], ready=False)
            def approve(_self, *args):
                return 'Komplettsetup' in str(args)
            first.modules['xbmcgui'].Dialog.yesno = approve
            first.run()
            resumed = guided(root, [0])
            resumed.run()
            self.assertFalse(any('Skin-Profil wählen' in title for title, _ in resumed.questions))
            self.assertFalse(any('Komplettsetup' in str(a) for a in resumed.approvals))
            self.assertTrue(any('Medienmenü geschrieben' in str(d) for d in resumed.dialogs))

    def test_drift_refusal_preserves_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guided(root, [0, 0]).run()
            target = next(root.glob('addon_data/script.skinvariables/**/*.json'))
            target.write_text('[]')
            surface = guided(root, [0])
            surface.modules['xbmcgui'].Dialog.yesno = lambda *_: False
            surface.run()
            self.assertEqual(target.read_text(), '[]')
            self.assertEqual(surface.commands, [])

    def test_explicit_rerun_can_change_profile_without_touching_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guided(root, [0, 0]).run()
            private = root / 'addon_data/plugin.video.youtube/settings.xml'
            private.parent.mkdir(parents=True)
            private.write_text('device-local-placeholder')
            surface = guided(root, [3, 1], skin='skin.arctic.fuse.3')
            surface.run()
            self.assertEqual(state.load(root), 'amber')
            self.assertEqual(private.read_text(), 'device-local-placeholder')
            self.assertTrue(any('Skin-Profil wählen' in title for title, _ in surface.questions))

    def test_cancel_profile_and_shutdown_do_not_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guided(root, [-1]).run()
            self.assertIsNone(state.load(root))
            surface = guided(root, [0, 0], ready=False)
            surface.modules['xbmc'].Monitor.abortRequested = lambda _: True
            surface.run()
            self.assertFalse((root / 'setupwizard-backups').exists())
            self.assertEqual(surface.commands, [])

    def test_bad_state_is_reported_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state.save(root, 'arctic')
            target = root / state.PATH
            target.write_text('{broken')
            surface = guided(root)
            surface.run()
            self.assertEqual(target.read_text(), '{broken')
            self.assertEqual(surface.commands, [])
            self.assertTrue(any('Statusdatei' in str(d) for d in surface.dialogs))

    def test_missing_addon_on_reopen_requires_approval_and_is_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guided(root, [0, 0]).run()
            surface = guided(root, [0])
            del surface.items['plugin.video.youtube']
            surface.modules['xbmcgui'].Dialog.yesno = lambda *_: False
            surface.run()
            self.assertNotIn('plugin.video.youtube', surface.items)
            self.assertEqual(surface.commands, [])
            self.assertFalse(any('Setup zurückgelesen' in title for title, _ in surface.questions))
            self.assertEqual(state.load(root), 'arctic')

    def test_only_region_drift_does_not_rewrite_layout_or_ask_library_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guided(root, [0, 0]).run()
            target = next(root.glob('addon_data/script.skinvariables/**/*.json'))
            before = (target.read_bytes(), target.stat().st_mtime_ns)
            surface = guided(root, [0])
            surface.locale['locale.language'] = 'resource.language.de_de'
            surface.run()
            self.assertEqual((target.read_bytes(), target.stat().st_mtime_ns), before)
            self.assertFalse(any('Bibliothek' in title for title, _ in surface.questions))
            self.assertEqual(len(surface.approvals), 2)  # locale and explicit pending skin activation

    def test_library_cancel_preserves_partial_profile_without_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed_nodes(root)
            surface = guided(root, [0, 0, -1])
            surface.run()
            self.assertEqual(state.load(root), 'arctic')
            self.assertFalse((root / 'setupwizard-backups').exists())
            self.assertFalse(list(root.glob('addon_data/script.skinvariables/**/*.json')))
            self.assertTrue(any('nicht abgeschlossen' in str(d) for d in surface.dialogs))


if __name__ == '__main__': unittest.main()
