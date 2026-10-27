"""Safety contracts for the default wizard, with real read-only SQLite fixtures."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from tests.test_setup_flow import guided
from tests.test_setup_wizard import Surface
from resources.lib.setupwizard import state
from resources.lib.setupwizard.addons import KodiAddonAPI


class IntegrationTests(unittest.TestCase):
    def test_catalog_reads_checksum_and_never_creates_missing_database(self):
        from resources.lib.setupwizard.catalog import SQLiteCatalogReader
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reader = SQLiteCatalogReader(lambda _: str(root))
            self.assertFalse(reader('repository.serph91p'))
            self.assertEqual(list(root.iterdir()), [])
            db = root / 'Addons33.db'
            with sqlite3.connect(db) as conn:
                conn.execute('CREATE TABLE repo (id INTEGER, addonID TEXT, checksum TEXT, lastcheck TEXT, version TEXT, nextcheck TEXT)')
                conn.execute('INSERT INTO repo VALUES (1, ?, ?, ?, ?, ?)', ('repository.serph91p', '', '', '1.0.2', ''))
            before = db.read_bytes()
            self.assertFalse(reader('repository.serph91p'))
            self.assertEqual(db.read_bytes(), before)
            with sqlite3.connect(db) as conn:
                conn.execute("UPDATE repo SET checksum='indexed'")
            before = db.read_bytes()
            self.assertTrue(reader('repository.serph91p'))
            self.assertEqual(db.read_bytes(), before)

    def test_legacy_api_without_origin_is_never_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            surface = Surface(root)
            self.assertFalse(state.inspect(root, 'arctic', KodiAddonAPI(surface.modules['xbmc'])).addons)

    def test_policy_refusal_has_zero_native_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            surface = guided(Path(tmp), [0, 0], ready=False)
            surface.policy = 0
            surface.modules['xbmcgui'].Dialog.yesno = lambda _self, *args: 'Komplettsetup' in str(args)
            surface.run()
            self.assertEqual(surface.commands, [])
            self.assertEqual(state.load(Path(tmp)), 'arctic')

    def test_policy_settings_exits_without_install_or_same_frame_recheck(self):
        with tempfile.TemporaryDirectory() as tmp:
            surface = guided(Path(tmp), [0, 0], ready=False)
            surface.policy = 0
            surface.run()
            self.assertEqual(surface.commands, ['ActivateWindow(systemsettings)'])
            self.assertEqual(state.load(Path(tmp)), 'arctic')

    def test_catalog_timeout_never_installs_leaves(self):
        from resources.lib.setupwizard import catalog
        with tempfile.TemporaryDirectory() as tmp:
            surface = guided(Path(tmp), [0, 0], ready=False)
            with patch.object(catalog, 'wait_for_catalog', return_value=False):
                surface.run()
            self.assertFalse(any(c.startswith('InstallAddon(') for c in surface.commands))
            self.assertTrue(any('Katalog' in str(d) for d in surface.dialogs))

    def test_missing_official_repository_is_not_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            surface = guided(Path(tmp), [0, 0], ready=False)
            surface.items.pop('repository.xbmc.org')
            surface.run()
            self.assertEqual(surface.commands, [])

    def test_activation_pending_until_subsequent_native_readback(self):
        from resources.lib.setupwizard.activation import request_activation
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            surface = Surface(root)
            api = KodiAddonAPI(surface.modules['xbmc'])
            self.assertTrue(request_activation(root, 'touch', api, approved=True))
            self.assertEqual(surface.skin, 'skin.estuary')
            journals = list(root.glob('setupwizard-backups/*/skin-activation.json'))
            self.assertEqual(len(journals), 1)
            journal = json.loads(journals[0].read_text())
            self.assertEqual(journal['before'], 'skin.estuary')
            self.assertEqual(journal['requested'], 'skin.estuary.modv2')
            self.assertNotIn('verified', journal)

    def test_activation_already_selected_noop(self):
        from resources.lib.setupwizard.activation import request_activation
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            surface = Surface(root, skin='skin.estuary.modv2')
            self.assertFalse(request_activation(root, 'touch', KodiAddonAPI(surface.modules['xbmc']), approved=True))
            self.assertEqual(surface.commands, [])
            self.assertFalse((root / 'setupwizard-backups').exists())


    def test_update_rules_are_readonly_and_all_entries_block_even_any(self):
        from resources.lib.setupwizard.catalog import SQLiteUpdateRuleReader
        surface = Surface(Path('.'))
        reader = SQLiteUpdateRuleReader(surface.translate)
        addon = 'repository.jurialmunkey'
        self.assertEqual(reader(addon), 'auto-updateable')
        for rule, label in ((0, 'ANY'), (1, 'USER_DISABLED_AUTO_UPDATE'),
                            (2, 'PIN_OLD_VERSION'), (3, 'PIN_ZIP_INSTALL'), (99, 'unknown-rule')):
            with sqlite3.connect(surface.database) as conn:
                conn.execute('DELETE FROM update_rules')
                conn.execute('INSERT INTO update_rules VALUES (?, ?)', (addon, rule))
            before = surface.database.read_bytes()
            self.assertEqual(reader(addon), 'blocked: ' + label)
            self.assertEqual(surface.database.read_bytes(), before)
        with sqlite3.connect(surface.database) as conn:
            conn.execute('DROP TABLE update_rules')
        self.assertEqual(reader(addon), 'unknown')

    def test_catalog_wait_is_bounded_and_abortable(self):
        from resources.lib.setupwizard.catalog import wait_for_catalog
        import types
        ticks = [0]
        monitor = types.SimpleNamespace(abortRequested=lambda: False,
            waitForAbort=lambda delay: ticks.__setitem__(0, ticks[0] + delay) or False)
        calls = []
        self.assertFalse(wait_for_catalog(lambda addon: calls.append(addon) or False,
            ('repository.serph91p',), monitor, timeout=2, clock=lambda: ticks[0]))
        self.assertEqual(ticks[0], 2)
        self.assertEqual(len(calls), 3)
        self.assertTrue(wait_for_catalog(lambda addon: ticks[0] >= 3,
            ('repository.serph91p',), monitor, timeout=2, clock=lambda: ticks[0]))
        monitor.abortRequested = lambda: True
        self.assertFalse(wait_for_catalog(lambda _: True, ('repository.serph91p',), monitor))

    def test_original_repositories_installed_before_leaves_and_index_gate(self):
        from resources.lib.setupwizard.catalog import SQLiteCatalogReader
        from resources.lib.setupwizard.origins import ordered_requirements
        from resources.lib.setupwizard.addons import REQUIREMENTS, MEDIA_REQUIREMENTS
        with tempfile.TemporaryDirectory() as tmp:
            surface = guided(Path(tmp), [0, 0], ready=False)
            original = SQLiteCatalogReader.__call__
            def inspect(reader, addon):
                if addon == 'repository.jurialmunkey':
                    self.assertIn('repository.jurialmunkey', surface.items)
                    self.assertNotIn('skin.arctic.fuse.3', surface.items)
                return original(reader, addon)
            with patch.object(SQLiteCatalogReader, '__call__', inspect):
                surface.run()
            installs = [c for c in surface.commands if c.startswith('InstallAddon(')]
            expected = [r.addon_id for r in ordered_requirements(REQUIREMENTS + MEDIA_REQUIREMENTS)
                        if r.addon_id not in ('repository.serph91p', 'repository.xbmc.org')]
            self.assertEqual(installs, ['InstallAddon(' + addon + ')' for addon in expected])
            self.assertFalse(any('weniger sicher' in str(a) for a in surface.approvals))

    def test_second_catalog_gate_timeout_installs_only_repository_addons(self):
        with tempfile.TemporaryDirectory() as tmp:
            surface = guided(Path(tmp), [0, 0], ready=False)
            with patch('resources.lib.setupwizard.catalog.wait_for_catalog', side_effect=(True, False)):
                surface.run()
            installs = [c for c in surface.commands if c.startswith('InstallAddon(')]
            self.assertEqual(installs, ['InstallAddon(repository.jurialmunkey)', 'InstallAddon(repository.beta.emby.kodi)'])
            self.assertNotIn('skin.arctic.fuse.3', surface.items)

    def test_existing_wrong_origin_never_silently_migrates_or_reinstalls(self):
        with tempfile.TemporaryDirectory() as tmp:
            surface = guided(Path(tmp), [0, 0])
            with sqlite3.connect(surface.database) as conn:
                conn.execute("UPDATE installed SET origin='repository.serph91p' WHERE addonID='skin.arctic.fuse.3'")
            before = surface.database.read_bytes()
            surface.run()
            self.assertTrue(all(cmd == 'UpdateAddonRepos' for cmd in surface.commands))
            self.assertEqual(surface.database.read_bytes(), before)
            self.assertTrue(any('Migration' in str(d) for d in surface.dialogs))

    def test_native_migration_is_wired_and_does_not_require_global_policy_weakening(self):
        for policy in (0, 1):
            with tempfile.TemporaryDirectory() as tmp:
                surface = guided(Path(tmp), [0, 0])
                surface.policy = policy
                with sqlite3.connect(surface.database) as conn:
                    conn.execute("UPDATE installed SET origin='repository.serph91p' WHERE addonID='skin.arctic.fuse.3'")
                before = surface.database.read_bytes()
                with patch('resources.lib.setupwizard.migration.SQLiteMigrationCandidates',
                           return_value=lambda _: ('999.0',)):
                    surface.run()
                self.assertEqual(surface.commands[-1], 'ActivateWindow(AddonBrowser,addons://user/all,return)')
                self.assertFalse(any(c.startswith('InstallAddon(') or c.startswith('SetSettingValue(') for c in surface.commands))
                self.assertEqual(surface.policy, policy)
                self.assertEqual(surface.database.read_bytes(), before)

    def test_missing_origins_default_entry_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            surface = guided(Path(tmp), [0, 0])
            surface.database.unlink()
            surface.run()
            self.assertEqual(surface.commands, [])
            self.assertFalse(surface.database.exists())

    def test_activation_refusal_and_symlink_guard_preserve_state(self):
        from resources.lib.setupwizard.activation import request_activation
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            surface = Surface(root)
            api = KodiAddonAPI(surface.modules['xbmc'])
            with self.assertRaises(ValueError): request_activation(root, 'touch', api)
            with self.assertRaises(ValueError): request_activation(root, '../touch', api, approved=True)
            outside = root / 'outside'
            outside.mkdir()
            (root / 'setupwizard-backups').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError): request_activation(root, 'touch', api, approved=True)
            self.assertEqual(surface.commands, [])
            self.assertEqual(list(outside.iterdir()), [])

    def test_configuration_is_not_ready_with_wrong_skin_or_pinned_repository(self):
        from resources.lib.setupwizard.origins import SQLiteOriginReader
        from resources.lib.setupwizard.catalog import SQLiteUpdateRuleReader
        from resources.lib.setupwizard.common_layouts import apply_common_layout
        from resources.lib.setupwizard.navigation import empty_bindings
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'setupwizard-backups').mkdir()
            apply_common_layout(root, root / 'setupwizard-backups/fixture', 'arctic', empty_bindings())
            surface = Surface(root)
            api = KodiAddonAPI(surface.modules['xbmc'], origin_read_fn=SQLiteOriginReader(surface.translate))
            reader = SQLiteUpdateRuleReader(surface.translate)
            status = state.inspect(root, 'arctic', api, reader)
            self.assertTrue(status.configured)
            self.assertFalse(status.ready)
            surface.skin = 'skin.arctic.fuse.3'
            self.assertTrue(state.inspect(root, 'arctic', api, reader).ready)
            with sqlite3.connect(surface.database) as conn:
                conn.execute('INSERT INTO update_rules VALUES (?, 2)', ('repository.jurialmunkey',))
            status = state.inspect(root, 'arctic', api, reader)
            self.assertFalse(status.ready)
            self.assertIn('PIN_OLD_VERSION', status.update_detail)
            self.assertTrue(status.configured)


    def test_pinned_repo_opens_verified_native_list_and_resumes_without_cached_success(self):
        from resources.lib.setupwizard.common_layouts import apply_common_layout
        from resources.lib.setupwizard.navigation import empty_bindings
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'setupwizard-backups').mkdir()
            apply_common_layout(root, root / 'setupwizard-backups/fixture', 'arctic', empty_bindings())
            state.save(root, 'arctic')
            surface = guided(root, [0], skin='skin.arctic.fuse.3')
            with sqlite3.connect(surface.database) as conn:
                conn.execute('INSERT INTO update_rules VALUES (?, 2)', ('repository.jurialmunkey',))
            before = surface.database.read_bytes()
            surface.run()
            self.assertEqual(surface.commands, ['ActivateWindow(AddonBrowser,addons://user/xbmc.addon.repository,return)'])
            self.assertEqual(surface.database.read_bytes(), before)
            self.assertEqual(state.load(root), 'arctic')
            surface.commands.clear()
            surface.run()
            self.assertFalse(any('Setup zurückgelesen' in title for title, _ in surface.questions))


    def test_native_keep_dialog_does_not_count_as_confirmed_activation(self):
        from resources.lib.setupwizard.activation import active_skin
        surface = Surface(Path('.'), skin='skin.estuary.modv2')
        surface.keep_dialog = True
        with self.assertRaises(RuntimeError): active_skin(KodiAddonAPI(surface.modules['xbmc']))
        surface.keep_dialog = False
        self.assertEqual(active_skin(KodiAddonAPI(surface.modules['xbmc'])), 'skin.estuary.modv2')


if __name__ == '__main__': unittest.main()
