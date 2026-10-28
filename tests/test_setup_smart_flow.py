"""Default-entry resume and multiple migrations, not readiness from flags."""
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from tests.test_setup_flow import guided
from resources.lib.setupwizard import state
from resources.lib.setupwizard.addons import (KodiAddonAPI, REQUIREMENTS, PROFILE_REQUIREMENTS, MEDIA_REQUIREMENTS, REQUIREMENTS_BY_ID)
from resources.lib.setupwizard.profiles import PROFILES, requirements_for
from resources.lib.setupwizard.origins import ordered_requirements, ORIGINS


def required(surface):
    api=KodiAddonAPI(surface.modules['xbmc'])
    return ordered_requirements(requirements_for(PROFILES[0],REQUIREMENTS,PROFILE_REQUIREMENTS,MEDIA_REQUIREMENTS),api=api)


class SmartFlowTests(unittest.TestCase):
    def test_two_source_migrations_continue_in_one_run_with_one_batch_consent(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);surface=guided(root,[0,0]);ids=['plugin.video.twitch','plugin.video.youtube']
            with sqlite3.connect(surface.database) as conn:
                conn.execute('CREATE TABLE addons(id INTEGER, addonID TEXT, version TEXT)')
                conn.execute('CREATE TABLE addonlinkrepo(idRepo INTEGER,idAddon INTEGER)')
                for index,addon in enumerate(ids,1):
                    conn.execute('UPDATE installed SET origin=? WHERE addonID=?',('',addon))
                    conn.execute('INSERT INTO addons VALUES(?,?,?)',(index,addon,surface.items[addon]['version']))
                    conn.execute('INSERT INTO addonlinkrepo VALUES(1,?)',(index,))
            pending=[req.addon_id for req in required(surface) if req.addon_id in ids]
            opened=[];original=surface.modules['xbmc'].executebuiltin
            def native(command,wait=False):
                if command=='ActivateWindow(AddonBrowser,addons://user/all,return)':
                    addon=pending[len(opened)];opened.append(addon)
                    with sqlite3.connect(surface.database) as conn:
                        conn.execute('UPDATE installed SET origin=? WHERE addonID=?',(ORIGINS[addon],addon))
                else:original(command,wait=wait)
            surface.modules['xbmc'].executebuiltin=native
            gui=surface.modules['xbmcgui']
            gui.getCurrentWindowId=lambda:10040;gui.getCurrentWindowDialogId=lambda:9999
            gui.Dialog.notification=lambda *_args,**_kw:None
            condition=surface.modules['xbmc'].getCondVisibility
            surface.modules['xbmc'].getCondVisibility=lambda value:False if value in (
                'Window.IsVisible(10138)','Window.IsVisible(10151)','Window.IsVisible(10160)') else condition(value)
            surface.modules['xbmcgui'].Dialog.yesno=lambda _self,*args:surface.approvals.append(args) or 'Komplettsetup' in str(args)
            surface.run()
            self.assertEqual(opened,pending)
            self.assertEqual(sum('Komplettsetup' in str(x) for x in surface.approvals),1)
            self.assertFalse((root/state.INSTALL_PATH).exists())
            self.assertTrue(any('Alle benötigten Addons' in str(x) for x in surface.dialogs))
            self.assertFalse(any(command.startswith('InstallAddon(') for command in surface.commands))

    def test_native_refusal_pauses_then_reopen_keeps_scope_without_reconfirming(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);first=guided(root,[0,0],ready=False)
            first.modules['xbmc'].executebuiltin=lambda *_args,**_kw:None
            first.run()
            self.assertEqual(state.installation_session(root,'arctic',required(first),KodiAddonAPI(first.modules['xbmc'])),'paused')
            self.assertTrue(any('Einrichtung pausiert' in str(x) for x in first.dialogs))
            second=guided(root,[0],ready=False)
            second.modules['xbmcgui'].Dialog.yesno=lambda _self,*args:second.approvals.append(args) or False
            second.run()
            self.assertFalse(any('Komplettsetup' in str(x) for x in second.approvals))
            self.assertTrue(any('Alle benötigten Addons' in str(x) for x in second.dialogs))
            self.assertFalse((root/state.INSTALL_PATH).exists())

    def test_active_interrupted_run_skips_start_menu_and_rechecks_missing_addon(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);surface=guided(root,[-1]);state.save(root,'arctic')
            del surface.items['plugin.video.youtube']
            state.remember_installation(root,'arctic',required(surface),KodiAddonAPI(surface.modules['xbmc']))
            surface.modules['xbmcgui'].Dialog.yesno=lambda _self,*args:surface.approvals.append(args) or False
            surface.run()
            self.assertFalse(any('Einrichtung fortsetzen' in title for title,_ in surface.questions))
            self.assertFalse(any('Komplettsetup' in str(x) for x in surface.approvals))
            self.assertIn('InstallAddon(plugin.video.youtube)',surface.commands)
            self.assertFalse((root/state.INSTALL_PATH).exists())


if __name__=='__main__':unittest.main()
