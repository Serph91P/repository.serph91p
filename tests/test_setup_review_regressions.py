"""Review regressions: all emitted actions must exist; native XML is semantic."""
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
from tests.test_setup_wizard import Surface
from resources.lib.setupwizard import state
from resources.lib.setupwizard.addons import KodiAddonAPI, REQUIREMENTS, PROFILE_REQUIREMENTS, MEDIA_REQUIREMENTS
from resources.lib.setupwizard.origins import SQLiteOriginReader, ordered_requirements
from resources.lib.setupwizard.catalog import SQLiteUpdateRuleReader
from resources.lib.setupwizard.common_layouts import apply_common_layout
from resources.lib.setupwizard.navigation import empty_bindings
from resources.lib.setupwizard.profiles import PROFILES, requirements_for


class ReviewRegressionTests(unittest.TestCase):
    def test_common_top_rated_has_original_repository_dependency_in_every_profile(self):
        for profile in PROFILES:
            leaves=requirements_for(profile,REQUIREMENTS,PROFILE_REQUIREMENTS,MEDIA_REQUIREMENTS)
            plan=ordered_requirements(leaves)
            ids=[r.addon_id for r in plan]
            self.assertIn('plugin.video.themoviedb.helper',ids,profile.key)
            self.assertIn('repository.jurialmunkey',ids,profile.key)
            self.assertLess(ids.index('repository.jurialmunkey'),ids.index('plugin.video.themoviedb.helper'))

    def test_missing_top_rated_dependency_never_reports_amber_or_touch_ready(self):
        for profile in PROFILES[1:]:
            with self.subTest(profile=profile.key),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                (root/'setupwizard-backups').mkdir()
                apply_common_layout(root,root/'setupwizard-backups/original',profile.key,empty_bindings())
                surface=Surface(root,skin=profile.addon_id)
                api=KodiAddonAPI(surface.modules['xbmc'],origin_read_fn=SQLiteOriginReader(surface.translate))
                del surface.items['plugin.video.themoviedb.helper']
                self.assertFalse(state.inspect(root,profile.key,api,SQLiteUpdateRuleReader(surface.translate)).ready)

    def test_touch_settings_reserialization_is_not_drift_but_value_change_is(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'setupwizard-backups').mkdir()
            apply_common_layout(root,root/'setupwizard-backups/original','touch',empty_bindings())
            surface=Surface(root,skin='skin.estuary.modv2')
            api=KodiAddonAPI(surface.modules['xbmc'],origin_read_fn=SQLiteOriginReader(surface.translate))
            reader=SQLiteUpdateRuleReader(surface.translate)
            target=root/'addon_data/skin.estuary.modv2/settings.xml'
            tree=ET.fromstring(target.read_bytes())
            ET.indent(tree,space='    ')
            target.write_bytes(ET.tostring(tree,encoding='utf-8'))
            before=target.read_bytes()
            self.assertTrue(state.inspect(root,'touch',api,reader).layout)
            self.assertEqual(target.read_bytes(),before)
            touchmode=tree.find("setting[@id='touchmode']")
            self.assertIsNotNone(touchmode)
            assert touchmode is not None
            touchmode.text='false'
            target.write_bytes(ET.tostring(tree,encoding='utf-8'))
            self.assertFalse(state.inspect(root,'touch',api,reader).layout)

    def test_generated_menu_remains_strict_byte_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'setupwizard-backups').mkdir()
            apply_common_layout(root,root/'setupwizard-backups/original','touch',empty_bindings())
            surface=Surface(root,skin='skin.estuary.modv2')
            api=KodiAddonAPI(surface.modules['xbmc'],origin_read_fn=SQLiteOriginReader(surface.translate))
            target=root/'addon_data/script.skinshortcuts/mainmenu.DATA.xml'
            target.write_bytes(target.read_bytes()+b'\n')
            self.assertFalse(state.inspect(root,'touch',api,SQLiteUpdateRuleReader(surface.translate)).layout)

    def test_ambiguous_or_malformed_settings_are_not_ready_and_never_rewritten(self):
        for bad in (b'<settings>',b'<settings><setting id="touchmode" type="bool">true</setting><setting id="TouchMode" type="bool">true</setting></settings>',
                    b'<!DOCTYPE settings [<!ENTITY x "true">]><settings><setting id="touchmode" type="bool">&x;</setting></settings>',
                    b'<settings><setting id="touchmode" type="string">true</setting></settings>'):
            with self.subTest(xml=bad),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                (root/'setupwizard-backups').mkdir()
                apply_common_layout(root,root/'setupwizard-backups/original','touch',empty_bindings())
                surface=Surface(root,skin='skin.estuary.modv2')
                api=KodiAddonAPI(surface.modules['xbmc'],origin_read_fn=SQLiteOriginReader(surface.translate))
                target=root/'addon_data/skin.estuary.modv2/settings.xml'
                target.write_bytes(bad)
                self.assertFalse(state.inspect(root,'touch',api,SQLiteUpdateRuleReader(surface.translate)).layout)
                self.assertEqual(target.read_bytes(),bad)


if __name__=='__main__':unittest.main()
