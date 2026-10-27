"""Wizard-owned repository bootstrap; no manual companion ZIP prerequisites."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from tests.test_setup_wizard import Surface, ADDON
from resources.lib.setupwizard.addons import KodiAddonAPI, REPOSITORY_REQUIREMENT, ORIGINAL_REPOSITORY_REQUIREMENTS
from resources.lib.setupwizard.origins import SQLiteOriginReader
from resources.lib.setupwizard.ui import install_with_progress
from resources.lib.setupwizard.catalog import SQLiteCatalogReader


class RepositoryBootstrapFlowTests(unittest.TestCase):
    def install(self, surface, reader=lambda _: True):
        api=KodiAddonAPI(surface.modules['xbmc'],origin_read_fn=SQLiteOriginReader(surface.translate))
        return install_with_progress(api,(REPOSITORY_REQUIREMENT,)+ORIGINAL_REPOSITORY_REQUIREMENTS,
            surface.modules['xbmcgui'].Dialog(),surface.modules['xbmc'].Monitor(),
            surface.modules['xbmcgui'].DialogProgressBG(),lambda _:None,approved=True,catalog_reader=reader)

    def test_wizard_has_no_repository_dependency_imports(self):
        root=ET.parse(ADDON/'addon.xml').getroot()
        self.assertFalse([n for n in root.findall('requires/import') if n.get('addon','').startswith('repository.')])

    def test_current_own_repo_installs_original_repos_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            surface=Surface(Path(tmp),ready=False)
            surface.items['repository.serph91p']['version']='1.0.3'
            okay,detail=self.install(surface)
            self.assertTrue(okay,detail)
            installs=[s for s in surface.commands if s.startswith('InstallAddon(')]
            self.assertEqual(installs,[
                'InstallAddon('+r.addon_id+')' for r in ORIGINAL_REPOSITORY_REQUIREMENTS])
            self.assertNotIn('InstallFromZip',surface.commands)
            self.assertLess(surface.commands.index('UpdateAddonRepos'),surface.commands.index(installs[0]))

    def test_missing_own_repo_cannot_be_invented_from_nowhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            surface=Surface(Path(tmp),ready=False,repo_ready=False)
            self.assertFalse(self.install(surface)[0])
            self.assertEqual(surface.commands,[])

    def test_unindexed_bootstrap_never_installs_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            surface=Surface(Path(tmp),ready=False)
            surface.items['repository.serph91p']['version']='1.0.3'
            with patch('resources.lib.setupwizard.catalog.wait_for_catalog',return_value=False):
                self.assertFalse(self.install(surface)[0])
            self.assertEqual([c for c in surface.commands if c.startswith('InstallAddon(')],[])

    def test_catalog_does_not_accept_old_repo_version_after_native_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            surface=Surface(Path(tmp))
            with sqlite3.connect(surface.database) as conn:
                columns={r[1] for r in conn.execute('PRAGMA table_info(repo)')}
                if 'version' not in columns:conn.execute("ALTER TABLE repo ADD COLUMN version TEXT DEFAULT '1.0.2'")
                conn.execute("UPDATE repo SET version='1.0.2'")
            reader=SQLiteCatalogReader(surface.translate,version_read_fn=lambda _: '1.0.3')
            before=surface.database.read_bytes()
            self.assertFalse(reader('repository.serph91p'))
            self.assertEqual(surface.database.read_bytes(),before)
            with sqlite3.connect(surface.database) as conn:
                conn.execute("UPDATE repo SET version='1.0.3'")
            before=surface.database.read_bytes()
            self.assertTrue(reader('repository.serph91p'))
            self.assertEqual(surface.database.read_bytes(),before)

    def test_outdated_own_repo_refuses_unsupported_builtin_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            surface=Surface(Path(tmp),ready=False)
            surface.items['repository.serph91p'].update(version='1.0.2',enabled=False)
            okay,detail=self.install(surface)
            self.assertFalse(okay)
            self.assertIn('nativ aktualisieren',detail)
            self.assertEqual(surface.commands,[])

    def test_old_own_repo_opens_native_update_and_does_not_install_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            surface=Surface(Path(tmp),[0,6],ready=False)
            surface.items['repository.serph91p']['version']='1.0.2'
            surface.run()
            self.assertEqual(surface.commands,['ActivateWindow(AddonBrowser,addons://user/xbmc.addon.repository,return)'])


if __name__=='__main__':unittest.main()
