"""MOD V2 source-name contract: both native Shared-menu states must consume ours."""
import json
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
from tests.test_setup_wizard import ADDON
from resources.lib.setupwizard.common_layouts import common_payloads, apply_common_layout
from resources.lib.setupwizard.navigation import empty_bindings, groups
from resources.lib.setupwizard import config as c


class MenuStorageTests(unittest.TestCase):
    def test_both_native_storage_modes_get_same_custom_menu_not_packaged_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload=common_payloads(Path(tmp),'touch',empty_bindings())
            for shared in (True,False):
                # Actual Skin Shortcuts2.0.3 slugify/getSharedMenu contract.
                prefix='' if shared else 'skin.estuary.modv2-'
                for group in ('mainmenu','movies','series','twitch','youtube','livetv'):
                    path='addon_data/script.skinshortcuts/'+prefix+group+'.DATA.xml'
                    with self.subTest(shared=shared,group=group):
                        self.assertIn(path,payload)
                        other='addon_data/script.skinshortcuts/'+group+'.DATA.xml'
                        self.assertEqual(payload[path],payload[other])
                if not shared:
                    path='addon_data/script.skinshortcuts/'+prefix+'mainmenu.DATA.xml'
                    root=ET.fromstring(payload[path])
                    ids=[s.findtext('defaultID') for s in root.findall('shortcut')]
                    self.assertEqual(ids[:5],[g.key for g in groups(empty_bindings())])
                    self.assertTrue(set(ids).isdisjoint({'music','radio','games','pictures','video'}))
                    self.assertIn('settings',ids)

    def test_v4_legacy_backup_and_new_private_files_restore_without_widening_old_policy(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/setup-touch-common-v4.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); base=root/'setupwizard-backups';base.mkdir()
            old=base/'old'; new=base/'new'
            legacy={k:v.encode() for k,v in fixture.items()}
            self.assertEqual(set(legacy),c.POLICIES['touch-common'])
            c.apply_payloads(root,old,legacy,'touch-common')
            self.assertEqual(json.loads((old/c.MANIFEST).read_text())['schema'],4)
            before={k:(root/k).read_bytes() for k in legacy}
            apply_common_layout(root,new,'touch',empty_bindings())
            meta=json.loads((new/c.MANIFEST).read_text())
            self.assertEqual(meta['schema'],5)
            self.assertEqual(meta['profile'],'touch-common-v2')
            c.rollback(root,new)
            self.assertEqual(before,{k:(root/k).read_bytes() for k in legacy})
            self.assertFalse((root/'addon_data/script.skinshortcuts/skin.estuary.modv2-mainmenu.DATA.xml').exists())
            c.rollback(root,old)
            self.assertFalse(any((root/k).exists() for k in legacy))


if __name__ == '__main__': unittest.main()
