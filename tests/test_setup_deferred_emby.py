"""Regression: a fresh profile must get its layout before personal Emby setup."""
import json
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
from tests.test_setup_wizard import Surface
from resources.lib.setupwizard.navigation import binding_path


class DeferredEmbyTests(unittest.TestCase):
    def test_fresh_profile_can_apply_every_skin_without_emby_sync(self):
        for index, profile in enumerate(('arctic', 'amber', 'touch')):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                surface = Surface(root, [1, 6], profile_index=index)
                surface.run()
                self.assertTrue((root / binding_path(profile)).is_file(), str(surface.dialogs))
                self.assertTrue(any('Medienmenü geschrieben' in str(x) for x in surface.dialogs))
                self.assertTrue(any('Emby' in str(x) and 'offen' in str(x) for x in surface.dialogs))
                self.assertFalse(any('ValueError' in str(x) for x in surface.dialogs))
                self.assertTrue(all(v is None for v in json.loads((root / binding_path(profile)).read_text()).values()))
                if profile != 'arctic':
                    prefix = 'skin.amber-' if profile == 'amber' else ''
                    sub = ET.parse(root / ('addon_data/script.skinshortcuts/' + prefix + 'series.DATA.xml')).getroot()
                    self.assertIn('Emby einrichten', sub[0].findtext('label'))
                    self.assertEqual(sub[0].findtext('action'), 'Addon.OpenSettings(plugin.service.emby-next-gen)')
                self.assertEqual(surface.commands, [])


    def test_deferred_adapters_emit_no_invalid_widget_uris(self):
        from resources.lib.setupwizard import navigation as n, config as c
        from resources.lib.setupwizard.common_layouts import common_payloads
        import ast
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for profile in n.PROFILE_IDS:
                payload = common_payloads(root, profile, n.empty_bindings())
                if profile == 'arctic':
                    widgets = [json.loads(v) for k, v in payload.items() if k.endswith('widgets.json')]
                    self.assertTrue(all(row['path'] is not None and row['target'] == 'videos' for rows in widgets for row in rows))
                    sub = json.loads(payload[c.SKIN_NODE + 'skinvariables-shortcut-1101submenu.json'])
                    self.assertEqual(sub[0]['target'], '')
                    self.assertEqual(sub[0]['path'], 'Addon.OpenSettings(plugin.service.emby-next-gen)')
                elif profile == 'touch':
                    main = ET.fromstring(payload['addon_data/script.skinshortcuts/mainmenu.DATA.xml'])
                    for group in list(main)[:4]:
                        props = dict(ast.literal_eval(group.findtext('additional-properties')))
                        for key, value in props.items():
                            if key.startswith('widgetPath.'):
                                self.assertIsInstance(value, str)
                                self.assertNotIn('None', value)
                                self.assertNotIn('Addon.OpenSettings', value)
                    series = dict(ast.literal_eval(main[1].findtext('additional-properties')))
                    self.assertEqual(series['widgetName.1'], 'Top Rated')
                    self.assertNotIn('widgetPath.2', series)

    def test_deferred_group_click_opens_emby_settings(self):
        from resources.lib.setupwizard import navigation as n
        from resources.lib.setupwizard.common_layouts import apply_common_layout
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'setupwizard-backups').mkdir()
            apply_common_layout(root, root/'setupwizard-backups'/'first', 'touch', n.empty_bindings())
            surface = Surface(root)
            surface.run(('group=series', 'profile=touch'))
            self.assertEqual(surface.commands, ['Addon.OpenSettings(plugin.service.emby-next-gen)'])
            self.assertEqual(surface.settings, ['plugin.service.emby-next-gen'])
            self.assertFalse(any('nicht geöffnet' in str(x) for x in surface.dialogs))

    def test_single_synced_library_does_not_require_twitch_vods(self):
        from tests.test_setup_wizard import seed_nodes
        from resources.lib.setupwizard import navigation as n
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); seed_nodes(root)
            for folder in (root/'library/video').iterdir():
                if folder.name.endswith('Twitch_VOD'):
                    shutil.rmtree(folder)
            bindings = n.library_bindings(root, lambda title, options: 0)
            self.assertTrue(all(bindings[k] is not None for k in ('series_resume','series_new','series_genres')))
            self.assertIsNone(bindings['twitch_resume'])
            self.assertIsNone(bindings['twitch_new'])

    def test_skip_existing_library_is_explicit_and_not_a_fake_binding(self):
        from tests.test_setup_wizard import seed_nodes
        from resources.lib.setupwizard import navigation as n
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); seed_nodes(root)
            seen = []
            def skip(title, options):
                seen.append(options[-1])
                return len(options) - 1
            self.assertEqual(n.library_bindings(root, skip), n.empty_bindings())
            self.assertEqual(len(seen), 2)
            self.assertTrue(all('Später' in x for x in seen))

    def test_link_after_sync_and_restore_to_deferred_state(self):
        from tests.test_setup_wizard import seed_nodes
        from resources.lib.setupwizard import navigation as n, config as c
        from resources.lib.setupwizard.common_layouts import apply_common_layout
        for profile in n.PROFILE_IDS:
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); (root/'setupwizard-backups').mkdir()
                first = root/'setupwizard-backups'/'first'
                second = root/'setupwizard-backups'/'second'
                apply_common_layout(root, first, profile, n.empty_bindings())
                pending = {p:(root/p).read_bytes() for p in c.POLICIES[profile+'-common']}
                seed_nodes(root)
                bindings = n.library_bindings(root, lambda title, options: options.index('Serien') if 'Serien' in options else 0)
                apply_common_layout(root, second, profile, bindings)
                self.assertTrue(all(v is not None for v in n.load_bindings(root, profile).values()))
                c.rollback(root, second)
                self.assertEqual(n.load_bindings(root, profile), n.empty_bindings())
                self.assertTrue(all((root/p).read_bytes() == data for p,data in pending.items()))
                c.rollback(root, first)
                self.assertFalse(any((root/p).exists() for p in c.POLICIES[profile+'-common']))


if __name__ == '__main__': unittest.main()
