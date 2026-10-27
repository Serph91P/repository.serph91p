"""Native Skin Shortcuts output, not just editable input files, must be current."""

from pathlib import Path
import tempfile

import unittest
from xml.etree import ElementTree as ET
from tests.test_setup_wizard import Surface
from resources.lib.setupwizard import menus,state
from resources.lib.setupwizard.common_layouts import apply_common_layout
from resources.lib.setupwizard.navigation import empty_bindings
from resources.lib.setupwizard.addons import KodiAddonAPI
from resources.lib.setupwizard.origins import SQLiteOriginReader
from resources.lib.setupwizard.catalog import SQLiteUpdateRuleReader


class MenuOutputTests(unittest.TestCase):
    def fixture(self,tmp,key='touch',answers=()):
        root=Path(tmp)
        (root/'setupwizard-backups').mkdir()
        apply_common_layout(root,root/'setupwizard-backups/first',key,empty_bindings())
        skin='skin.estuary.modv2' if key=='touch' else 'skin.amber'
        from tests.test_setup_flow import guided
        surface=guided(root,answers,skin=skin)
        api=KodiAddonAPI(surface.modules['xbmc'],origin_read_fn=SQLiteOriginReader(surface.translate))
        native=surface.native_skin_path(skin)
        return root,surface,api,native/'xml/script-skinshortcuts-includes.xml'

    def test_old_native_cache_blocks_ready_without_reapplying_userdata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,s,api,compiled=self.fixture(tmp)
            self.assertTrue(menus.current(root,'touch',api))
            compiled.write_text('<includes><include name="skinshortcuts-mainmenu"><item><label>Music</label></item></include></includes>')
            before=(root/'addon_data/script.skinshortcuts/mainmenu.DATA.xml').read_bytes()
            result=state.inspect(root,'touch',api,SQLiteUpdateRuleReader(s.translate))
            self.assertTrue(result.layout)
            self.assertFalse(result.menu)
            self.assertFalse(result.ready)
            self.assertEqual((root/'addon_data/script.skinshortcuts/mainmenu.DATA.xml').read_bytes(),before)

    def test_refresh_uses_native_builder_and_reads_output_for_both_profiles(self):
        for key in ('touch','amber'):
            with self.subTest(profile=key),tempfile.TemporaryDirectory() as tmp:
                root,s,api,compiled=self.fixture(tmp,key)
                compiled.write_text('<includes/>')
                menus.refresh(root,key,api,s.modules['xbmc'].Monitor(),approved=True)
                self.assertTrue(menus.current(root,key,api))
                self.assertIn('SetProperty(skinshortcuts-reloadmainmenu,True,home)',s.commands)
                self.assertIn('RunScript(script.skinshortcuts,type=buildxml&mainmenuID=9000&group=mainmenu)',s.commands)

    def test_no_mutation_without_approval_or_if_already_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,s,api,compiled=self.fixture(tmp)
            menus.refresh(root,'touch',api,s.modules['xbmc'].Monitor(),approved=True)
            self.assertEqual(s.commands,[])
            compiled.write_text('<includes/>')
            with self.assertRaises(ValueError):menus.refresh(root,'touch',api,s.modules['xbmc'].Monitor())
            self.assertEqual(s.commands,[])

    def test_wrong_skin_failure_and_timeout_never_claim_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,s,api,compiled=self.fixture(tmp)
            compiled.write_text('<includes/>')
            s.skin='skin.estuary'
            with self.assertRaises(ValueError):menus.refresh(root,'touch',api,s.modules['xbmc'].Monitor(),approved=True)
            self.assertEqual(s.commands,[])
            s.skin='skin.estuary.modv2'
            s.modules['xbmc'].executebuiltin=lambda *a,**kw:None
            ticks=[0]
            def sleep(n):ticks[0]+=n
            with self.assertRaises(RuntimeError):
                menus.refresh(root,'touch',api,s.modules['xbmc'].Monitor(),approved=True,
                              timeout=1,clock=lambda:ticks[0],sleep=sleep)
            self.assertFalse(menus.current(root,'touch',api))

    def test_changed_compiled_action_or_malformed_xml_is_not_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,s,api,compiled=self.fixture(tmp)
            tree=ET.fromstring(compiled.read_bytes())
            action=tree.find('include/item/onclick')
            assert action is not None
            action.text='ActivateWindow(Music)'
            compiled.write_bytes(ET.tostring(tree))
            self.assertFalse(menus.current(root,'touch',api))
            compiled.write_bytes(b'<!DOCTYPE includes [<!ENTITY x "bad">]><includes/>')
            self.assertFalse(menus.current(root,'touch',api))


    def test_guided_resume_repairs_cache_without_layout_or_login_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,s,api,compiled=self.fixture(tmp,answers=[0])
            compiled.write_text('<includes/>')
            s.run()
            self.assertTrue(menus.current(root,'touch',api))
            prompts=' '.join(str(row) for row in s.dialogs+s.approvals)
            self.assertIn('native Menüansicht',prompts)
            self.assertNotIn('Layout anwenden?',prompts)
            self.assertNotIn('Gewählten Skin jetzt aktivieren:',prompts)
            self.assertFalse(any(command.startswith('InstallAddon(') for command in s.commands))

    def test_active_touch_skin_with_disabled_runtime_touchmode_is_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,s,api,compiled=self.fixture(tmp)
            s.touchmode=False
            result=state.inspect(root,'touch',api,SQLiteUpdateRuleReader(s.translate))
            self.assertFalse(result.skin)
            self.assertFalse(result.ready)


if __name__=='__main__':unittest.main()
