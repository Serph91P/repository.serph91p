"""Infer preferences from an existing known skin, never infer completion."""
from pathlib import Path
import tempfile
import unittest
from tests.test_setup_flow import guided
from resources.lib.setupwizard import state


class ExistingSetupTests(unittest.TestCase):
    def test_known_active_skin_skips_profile_question_but_not_state_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            surface=guided(root,[-1],skin='skin.arctic.fuse.3')
            surface.run()
            self.assertEqual(state.load(root),'arctic')
            self.assertFalse(any('Skin-Profil wählen' in title for title,_ in surface.questions))
            self.assertTrue(any('Einrichtung fortsetzen' in title for title,_ in surface.questions))
            self.assertFalse(any('Setup zurückgelesen' in title for title,_ in surface.questions))
            self.assertEqual(surface.approvals,[])
            self.assertEqual(surface.commands,[])

    def test_corrupt_saved_state_is_not_overridden_from_active_skin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            state.save(root,'arctic')
            path=root/state.PATH
            path.write_text('{broken')
            surface=guided(root,[-1],skin='skin.arctic.fuse.3')
            surface.run()
            self.assertEqual(path.read_text(),'{broken')
            self.assertEqual(surface.questions,[])
            self.assertEqual(surface.commands,[])


if __name__=='__main__':unittest.main()
