"""Curated Adams userdata, preserving unrelated settings and helper rows."""
import sys,tempfile,sqlite3,unittest
from pathlib import Path
from xml.etree import ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'script.serph91p.setup'))
from resources.lib.setupwizard.navigation import empty_bindings
from resources.lib.setupwizard.common_layouts import common_payloads,apply_common_layout
from resources.lib.setupwizard.config import rollback


class AdamsLayoutTests(unittest.TestCase):
    def test_rotary_six_contiguous_shortcuts_no_fake_widgets_and_preserved_other_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'addon_data/skin.rotary/settings.xml';p.parent.mkdir(parents=True)
            p.write_text('<settings version="2"><setting id="private.preference" type="string">untouched</setting><setting id="rotary.home.7.action" type="string">OldAction</setting></settings>')
            before=p.read_bytes();payload=common_payloads(root,'rotary',empty_bindings())
            settings={n.get('id'):n.text or '' for n in ET.fromstring(payload['addon_data/skin.rotary/settings.xml'])}
            self.assertEqual(settings['private.preference'],'untouched')
            self.assertEqual([settings['rotary.home.%d.label'%i] for i in range(1,7)],['Movies','Series','Twitch','YouTube','Live TV','Setup'])
            self.assertNotIn('rotary.home.7.action',settings)
            self.assertFalse(any('widget' in s.lower() for s in settings))
            backup=root/'setupwizard-backups/new';backup.parent.mkdir();apply_common_layout(root,backup,'rotary',empty_bindings());rollback(root,backup)
            self.assertEqual(p.read_bytes(),before)
    def test_rotary_native_empty_unused_slot_is_not_endless_layout_drift(self):
        from resources.lib.setupwizard.state import _layout_matches
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rel='addon_data/skin.rotary/settings.xml';target=root/rel
            target.parent.mkdir(parents=True)
            target.write_bytes(common_payloads(root,'rotary',empty_bindings())[rel])
            tree=ET.fromstring(target.read_bytes())
            tail=ET.SubElement(tree,'setting',{'id':'rotary.home.7.action','type':'string'})
            target.write_bytes(ET.tostring(tree))
            # Kodi persists a missing Skin.String lookup as an empty setting.
            self.assertTrue(_layout_matches(rel,target,common_payloads(root,'rotary',empty_bindings())[rel]))
            tail.text='UnexpectedSeventhAction'
            target.write_bytes(ET.tostring(tree))
            self.assertFalse(_layout_matches(rel,target,common_payloads(root,'rotary',empty_bindings())[rel]))
            tail.text=None;tail.set('type','bool')
            target.write_bytes(ET.tostring(tree))
            self.assertFalse(_layout_matches(rel,target,common_payloads(root,'rotary',empty_bindings())[rel]))

    def test_nimbus_existing_rows_and_settings_are_preserved_and_snapshot_is_reproducible(self):
        from resources.lib.setupwizard.adams import DATABASE
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/DATABASE;p.parent.mkdir(parents=True)
            with sqlite3.connect(p) as db:
                db.execute('CREATE TABLE custom_paths(cpath_setting text unique,cpath_path text,cpath_header text,cpath_type text,cpath_label text)')
                db.execute('INSERT INTO custom_paths VALUES (?,?,?,?,?)',('custom10.main_menu','UserTarget','UserLabel','Videos','Keep'))
            before=p.read_bytes();payload=common_payloads(root,'nimbus',empty_bindings())
            self.assertEqual(p.read_bytes(),before)  # Pure plan/inspection.
            memory=sqlite3.connect(':memory:');memory.deserialize(payload[DATABASE])
            self.assertEqual(memory.execute('SELECT cpath_path FROM custom_paths WHERE cpath_setting="custom10.main_menu"').fetchone(),('UserTarget',))
            self.assertEqual(memory.execute('SELECT COUNT(*) FROM custom_paths WHERE cpath_setting LIKE "%.main_menu"').fetchone()[0],7)
            memory.close()
            backup=root/'setupwizard-backups/nimbus';backup.parent.mkdir();apply_common_layout(root,backup,'nimbus',empty_bindings())
            self.assertEqual(common_payloads(root,'nimbus',empty_bindings())[DATABASE],p.read_bytes())
            rollback(root,backup);self.assertEqual(p.read_bytes(),before)
    def test_foreign_helper_schema_or_sidecar_does_not_get_overwritten(self):
        from resources.lib.setupwizard.adams import DATABASE
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/DATABASE;p.parent.mkdir(parents=True)
            with sqlite3.connect(p) as db:db.execute('CREATE TABLE custom_paths(unknown TEXT)')
            before=p.read_bytes()
            with self.assertRaises(ValueError):common_payloads(root,'nimbus',empty_bindings())
            self.assertEqual(p.read_bytes(),before)
    def test_legacy_modv2_data_untouched_by_both_new_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'addon_data/skin.estuary.modv2/settings.xml';old.parent.mkdir(parents=True);old.write_bytes(b'legacy-data')
            (root/'setupwizard-backups').mkdir()
            for key in ('rotary','nimbus'):
                apply_common_layout(root,root/'setupwizard-backups'/key,key,empty_bindings())
                self.assertEqual(old.read_bytes(),b'legacy-data')


if __name__=='__main__':unittest.main()
