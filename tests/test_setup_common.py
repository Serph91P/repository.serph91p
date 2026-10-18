"""Common-menu equivalence, local binding isolation and native repo contract."""
import ast
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from tests.test_setup_wizard import Surface, seed_nodes, ADDON
from resources.lib.setupwizard import navigation as n, config as c
from resources.lib.setupwizard.common_layouts import common_payloads, apply_common_layout
from tools.build_setup_repository import build as build_repo

ROOT = ADDON.parent


class CommonTests(unittest.TestCase):
    def fixture(self, root):
        seed_nodes(root)
        return n.library_bindings(root, lambda title, options: options.index('Serien') if 'Serien' in options else 0)

    def test_local_node_bindings_preserve_reference_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.fixture(Path(tmp))
            self.assertIn('dynamic_tvshows_Serien/resume_episode', b['series_resume'])
            self.assertIn('tvshows_Serien/recentlyadded', b['series_new'])
            self.assertIn('tvshows_Twitch_VOD/inprogressepisodes', b['twitch_resume'])
            self.assertIn('tvshows_Twitch_VOD/recentlyadded', b['twitch_new'])
            self.assertEqual([g.label for g in n.groups(b)], ['Movies', 'Series', 'Twitch', 'YouTube'])
            self.assertEqual([len(g.items) for g in n.groups(b)], [4, 4, 4, 3])

    def test_missing_sync_or_cancel_has_no_layout_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, 'Emby zuerst'):
                n.library_bindings(root, lambda *_: 0)
            self.assertEqual(list(root.iterdir()), [])
            seed_nodes(root)
            with self.assertRaisesRegex(ValueError, 'abgebrochen'):
                n.library_bindings(root, lambda *_: -1)
            self.assertFalse((root/'addon_data').exists())

    def test_symlink_library_root_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'library').symlink_to(root)
            with self.assertRaises(ValueError):
                n.library_bindings(root, lambda *_: 0)

    def test_binding_urls_cannot_escape_or_contact_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.fixture(Path(tmp))
            for path in ('https://example.org/', 'library://video/emby_%2e%2e/genres.xml/',
                         'library://video/emby_a%2fb/genres.xml/',
                         'library://video/emby_a%5cb/genres.xml/',
                         'library://video/emby_a%252fb/genres.xml/',
                         'library://video/emby_a/../../settings.xml'):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    n.validate_bindings(dict(b, series_new=path))

    def test_all_adapter_widget_and_submenu_content_is_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); bindings = self.fixture(root)
            expected = n.groups(bindings)
            af = common_payloads(root, 'arctic', bindings)
            amber = common_payloads(root, 'amber', bindings)
            mod = common_payloads(root, 'touch', bindings)
            mod_main = ET.fromstring(mod['addon_data/script.skinshortcuts/mainmenu.DATA.xml'])
            amber_main = ET.fromstring(amber[c.AMBER_MENU])
            for i, (slot, group) in enumerate(zip(('home', '1101', '1102', '1103'), expected)):
                rows = json.loads(af[c.SKIN_NODE+'skinvariables-shortcut-'+slot+'widgets.json'])
                self.assertEqual([(x['label'], x['path']) for x in rows], [(x.label,x.path) for x in group.items])
                for profile, payload, prefix, main in (
                    ('amber', amber, 'skin.amber-', amber_main), ('touch', mod, '', mod_main)):
                    self.assertEqual(main[i].findtext('label'), group.label)
                    self.assertEqual(main[i].findtext('action'), n.group_action(group, profile))
                    sub = ET.fromstring(payload['addon_data/script.skinshortcuts/'+prefix+group.key+'.DATA.xml'])
                    self.assertEqual([(x.findtext('label'),x.findtext('action')) for x in sub],
                                     [(x.label,n.action(x)) for x in group.items])
                props = dict(ast.literal_eval(mod_main[i].findtext('additional-properties')))
                self.assertEqual(props['widget'], 'PersonalWidgetList')
                for num, item in enumerate(group.items, 1):
                    self.assertEqual(props['widgetPath.'+str(num)], item.path)
                    self.assertEqual(props['widgetName.'+str(num)], item.label)
                    expected_aspect = ('135' if item.label == 'Genres' else
                                       '31338' if group.key in ('movies', 'series') else '31339')
                    self.assertEqual(props['widgetAspect.'+str(num)], expected_aspect)
                    self.assertIn(props['widgetAspect.'+str(num)], {'135','31338','31339'})
            touchsettings = ET.fromstring(mod['addon_data/skin.estuary.modv2/settings.xml'])
            self.assertEqual(touchsettings.find('setting').attrib, {'id':'touchmode','type':'bool'})
            self.assertEqual(touchsettings.findtext('setting'), 'true')
            self.assertEqual(list(root.glob('addon_data/**/*')), [])

    def test_all_profiles_backup_noop_restore_and_legacy_isolation(self):
        for profile in n.PROFILE_IDS:
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); b=self.fixture(root)
                (root/'setupwizard-backups').mkdir()
                backup=root/'setupwizard-backups'/'first'
                payload=common_payloads(root,profile,b)
                # Preserve an unrelated value in an inactive skin's settings.
                changed=apply_common_layout(root,backup,profile,b)
                self.assertEqual(set(changed), c.POLICIES[profile+'-common'])
                self.assertEqual(json.loads((backup/c.MANIFEST).read_text())['schema'],4)
                self.assertEqual(apply_common_layout(root,root/'setupwizard-backups'/'noop',profile,b),[])
                self.assertFalse((root/'setupwizard-backups'/'noop').exists())
                for path,data in payload.items(): self.assertEqual((root/path).read_bytes(),data)
                c.rollback(root,backup)
                self.assertFalse(any((root/path).exists() for path in payload))

    def test_common_restore_refuses_drift_and_cross_profile_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); b=self.fixture(root)
            (root/'setupwizard-backups').mkdir(); backup=root/'setupwizard-backups'/'x'
            apply_common_layout(root,backup,'touch',b)
            target=root/n.binding_path('touch'); target.write_text('user drift')
            with self.assertRaises(c.LayoutConflict): c.rollback(root,backup)
            data=json.loads((backup/c.MANIFEST).read_text()); data['profile']='amber-common'
            (backup/c.MANIFEST).write_text(json.dumps(data))
            with self.assertRaises(ValueError): c.rollback(root,backup)
            self.assertEqual(target.read_text(),'user drift')

    def test_common_partial_apply_can_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); b=self.fixture(root)
            (root/'setupwizard-backups').mkdir(); backup=root/'setupwizard-backups'/'x'
            original=c._atomic
            def fail(path,data):
                if path == root/'addon_data/script.skinshortcuts/mainmenu.DATA.xml': raise OSError('injected')
                original(path,data)
            with patch.object(c,'_atomic',side_effect=fail), self.assertRaises(OSError):
                apply_common_layout(root,backup,'touch',b)
            c.rollback(root,backup)
            self.assertFalse(any((root/path).exists() for path in c.POLICIES['touch-common']))

    def test_common_menu_actual_script_entrypoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); b=self.fixture(root)
            (root/'setupwizard-backups').mkdir()
            apply_common_layout(root,root/'setupwizard-backups'/'x','touch',b)
            s=Surface(root,profile_index=1)
            s.run(('group=twitch','profile=touch'))
            self.assertEqual(s.commands,[n.action(n.groups(b)[2].items[1])])

    def test_invalid_script_arguments_do_not_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Surface(Path(tmp)); s.run(('group=twitch','profile=../../x'))
            self.assertEqual(s.commands,[])
            self.assertTrue(any('nicht geöffnet' in str(x) for x in s.dialogs))

    def test_missing_repository_preflight_no_addon_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Surface(Path(tmp),[0,6],ready=False,repo_ready=False);s.run()
            self.assertEqual(s.commands,[])
            self.assertTrue(any('Setup-Quellen fehlen' in str(x) for x in s.dialogs))

    def test_all_skin_install_flows_are_profile_scoped(self):
        from resources.lib.setupwizard.addons import MEDIA_REQUIREMENTS
        for index,skin in enumerate(('skin.arctic.fuse.3','skin.amber','skin.estuary.modv2')):
            with self.subTest(skin=skin),tempfile.TemporaryDirectory() as tmp:
                s=Surface(Path(tmp),[0,6],ready=False,profile_index=index);s.run()
                self.assertIn(skin,s.items)
                self.assertTrue(all(r.addon_id in s.items for r in MEDIA_REQUIREMENTS))
                self.assertTrue(any('Alle benötigten Addons' in str(x) for x in s.dialogs))
                self.assertEqual(s.progress_events[-1],('close',))

    def test_repository_has_native_omega_only_sources_and_checksums(self):
        root=ET.parse(ROOT/'addon.xml').getroot()
        ext=[x for x in root.findall('extension') if x.get('point')!='xbmc.addon.metadata']
        self.assertEqual([x.get('point') for x in ext],['xbmc.addon.repository'])
        dirs=ext[0].findall('dir');self.assertEqual(len(dirs),5)
        for d in dirs:
            self.assertTrue(d.findtext('info').startswith('https://'))
            self.assertTrue(d.findtext('checksum').startswith('https://'))
            self.assertTrue(d.findtext('datadir').startswith('https://'))
        for d in dirs[1:]:
            self.assertEqual(d.get('minversion'),'21.0.0')
            self.assertEqual(d.get('maxversion'),'21.9.999')

    def test_repository_package_repeatable_and_requires_correct_version(self):
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=build_repo(root/'a');b=build_repo(root/'b')
            self.assertEqual(a.read_bytes(),b.read_bytes())
            with zipfile.ZipFile(a) as z:
                self.assertIsNone(z.testzip());self.assertEqual(len(z.namelist()),3)
                meta=ET.fromstring(z.read('repository.serph91p/addon.xml'))
                self.assertEqual(meta.get('version'),'1.0.1')
        wizard=ET.parse(ADDON/'addon.xml').getroot()
        self.assertIn({'addon':'repository.serph91p','version':'1.0.1'},
                      [x.attrib for x in wizard.findall('./requires/import')])


if __name__ == '__main__': unittest.main()
