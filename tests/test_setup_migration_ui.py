"""Guided native source selection, never simulated installation success."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from tests.test_setup_migration import API
from resources.lib.setupwizard.addons import REQUIREMENTS_BY_ID
from resources.lib.setupwizard.migration import (inspect_existing, guide_native_migration,
                                                SQLiteMigrationCandidates)


class MigrationUITests(unittest.TestCase):
    def setUp(self):
        self.req=REQUIREMENTS_BY_ID['skin.amber']
        self.api=API(origin='',version='4.0')
        self.plan=inspect_existing(self.api,self.req)
    def test_no_ui_if_already_correct_and_no_reinstall(self):
        self.api.source='repository.xbmc.org'
        dialog=Mock();opened=[]
        self.assertTrue(guide_native_migration(self.api,inspect_existing(self.api,self.req),dialog,
            lambda _:self.fail('No candidate lookup for existing correct addon'),opened.append))
        self.assertEqual(opened,[]);dialog.yesno.assert_not_called()
    def test_user_decline_preserves_existing_state(self):
        dialog=Mock();dialog.yesno.return_value=False;opened=[]
        self.assertFalse(guide_native_migration(self.api,self.plan,dialog,lambda _:('4.1',),opened.append))
        self.assertEqual(opened,[]);self.assertEqual(self.api.source,'')
    def test_only_native_my_addons_list_no_install_or_uninstall_and_no_completion_claim(self):
        dialog=Mock();dialog.yesno.return_value=True;opened=[]
        self.assertFalse(guide_native_migration(self.api,self.plan,dialog,lambda _:('4.0',),opened.append))
        self.assertEqual(opened,['ActivateWindow(AddonBrowser,addons://user/all,return)'])
        text=dialog.yesno.call_args.args[1]
        for word in ('Versionen','repository.xbmc.org','Nicht','Deinstallieren','Paketcache'):
            self.assertIn(word,text)
        self.assertEqual(self.api.source,'')
    def test_no_candidate_or_only_downgrade_never_opens_native_flow(self):
        for candidates in ((),('3.99.2',),('unknown',)):
            dialog=Mock();opened=[]
            self.assertFalse(guide_native_migration(self.api,self.plan,dialog,lambda _:candidates,opened.append))
            self.assertEqual(opened,[]);dialog.yesno.assert_not_called()
    def test_unreadable_candidates_fail_closed(self):
        dialog=Mock();opened=[]
        def broken(_):raise RuntimeError('Unavailable')
        self.assertFalse(guide_native_migration(self.api,self.plan,dialog,broken,opened.append))
        self.assertEqual(opened,[])
    def test_candidate_reader_is_readonly_and_repository_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'Addons33.db'
            with sqlite3.connect(path) as conn:
                conn.executescript('CREATE TABLE repo(id INTEGER,addonID TEXT);CREATE TABLE addons(id INTEGER,addonID TEXT,version TEXT);CREATE TABLE addonlinkrepo(idRepo INTEGER,idAddon INTEGER);')
                conn.executemany('INSERT INTO repo VALUES (?,?)',[(1,'repository.xbmc.org'),(2,'repository.other')])
                conn.executemany('INSERT INTO addons VALUES (?,?,?)',[(1,'skin.amber','4.0'),(2,'skin.amber','3.99.2'),(3,'skin.amber','99.0'),(4,'skin.unrelated','99.0')])
                conn.executemany('INSERT INTO addonlinkrepo VALUES (?,?)',[(1,1),(1,2),(2,3),(1,4)])
            reader=SQLiteMigrationCandidates(lambda _:tmp,lambda repo:repo=='repository.xbmc.org')
            before=path.read_bytes()
            self.assertEqual(reader(self.plan),('4.0',))
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(SQLiteMigrationCandidates(lambda _:tmp,lambda _:False)(self.plan),())
            path.rename(Path(tmp)/'real.db');path.symlink_to(Path(tmp)/'real.db')
            self.assertEqual(reader(self.plan),())


if __name__=='__main__':unittest.main()
