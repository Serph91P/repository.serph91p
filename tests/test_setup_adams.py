"""Adams original-source and replacement touch-profile contracts."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'script.serph91p.setup'))
from xml.etree import ElementTree as ET
from tools import build_setup_bootstrap as bootstrap
from resources.lib.setupwizard.addons import REQUIREMENTS_BY_ID,REQUIREMENTS,PROFILE_REQUIREMENTS,MEDIA_REQUIREMENTS
from resources.lib.setupwizard.origins import ORIGINS,ordered_requirements
from resources.lib.setupwizard.profiles import PROFILES,requirements_for


class AdamsTests(unittest.TestCase):
    def test_touch_choices_replace_modv2_but_keep_known_legacy_state(self):
        selectable=[p for p in PROFILES if not p.retired]
        self.assertEqual([p.key for p in selectable],['arctic','amber','rotary','nimbus'])
        self.assertEqual(next(p for p in PROFILES if p.key=='touch').retired,True)
        self.assertEqual(next(p for p in selectable if p.key=='rotary').addon_id,'skin.rotary')
        self.assertEqual(next(p for p in selectable if p.key=='nimbus').addon_id,'skin.nimbus')
    def test_adams_is_native_original_for_both_skins_and_helper(self):
        for key,minimum in [('skin.rotary',(0,0,1)),('skin.nimbus',(0,2,7)),('script.nimbus.helper',(0,0,98))]:
            self.assertEqual(REQUIREMENTS_BY_ID[key].min_version,minimum)
            self.assertEqual(ORIGINS[key],'repository.adamsbuilds')
        for key in ('rotary','nimbus'):
            profile=next(p for p in PROFILES if p.key==key)
            ids=[r.addon_id for r in ordered_requirements(requirements_for(profile,REQUIREMENTS,PROFILE_REQUIREMENTS,MEDIA_REQUIREMENTS))]
            self.assertLess(ids.index('repository.adamsbuilds'),ids.index(profile.addon_id))
            self.assertNotIn('skin.estuary.modv2',ids)
            self.assertNotIn('repository.kodinerds',ids)
            self.assertNotIn('script.skinshortcuts',ids)
    def test_adams_bootstrap_only_original_repository_zip_never_leaf_catalog(self):
        source=next(s for s in bootstrap.SOURCES if s['id']=='repository.adamsbuilds')
        self.assertEqual(bootstrap.source_url(source),'https://adamsbuilds.github.io/repo/repository.adamsbuilds-1.0.zip')
        self.assertEqual(source['sha256'],'915fc41dd3f45c4a6ae32441626f2234a8e201b372eb1da29cddbdc6e3b77334')
        files=bootstrap.local_files()
        outer=ET.fromstring(files['repository.adamsbuilds/addons.xml'])
        self.assertEqual([e.get('id') for e in outer],['repository.adamsbuilds'])
        self.assertEqual(outer[0].findtext("extension[@point='xbmc.addon.metadata']/path"),'repository.adamsbuilds-1.0.zip')
        self.assertEqual(outer[0].findtext("extension[@point='xbmc.addon.repository']/dir/info"),'https://raw.githubusercontent.com/adamsbuilds/repo/master/zips/addons.xml')


if __name__=='__main__':unittest.main()
