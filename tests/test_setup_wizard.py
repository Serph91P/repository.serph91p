"""Exercise default.py with only supported Kodi module surfaces.

These fixtures emulate Kodi; they are NOT a real-device acceptance test.
"""
import json
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ADDON = Path(__file__).resolve().parents[1] / 'script.serph91p.setup'
sys.path.insert(0, str(ADDON))
from resources.lib.setupwizard.addons import (ALL_REQUIREMENTS, REQUIREMENTS, MEDIA_REQUIREMENTS,
    KodiAddonAPI, bounded_wait, check_requirement, ensure_requirement,
    version_at_least, REPOSITORY_REQUIREMENT)

def seed_nodes(root):
    for label in ('Serien', 'Twitch_VOD'):
        for prefix, names in (('emby_dynamic_tvshows_', ('resume_episode.xml',)),
                              ('emby_tvshows_', ('inprogressepisodes.xml', 'recentlyadded.xml', 'genres.xml'))):
            folder = root / 'library/video' / (prefix + label)
            folder.mkdir(parents=True, exist_ok=True)
            for name in names:
                (folder / name).write_text('<node/>')


class Surface:
    def __init__(self, profile, selections=(), ready=True, skin='skin.estuary', major=21, profile_index=0, repo_ready=True):
        self.profile, self.selections, self.skin, self.major = profile, iter((profile_index, *selections)), skin, major
        self.commands, self.dialogs, self.settings, self.log = [], [], [], []
        self.progress_events = []
        from resources.lib.setupwizard.regional import reference
        self.locale = reference()
        self.touchmode = False
        self.bad_response = False
        self.items = {r.addon_id: {'addonid': r.addon_id, 'enabled': True,
            'version': '.'.join(map(str, r.min_version))} for r in ALL_REQUIREMENTS} if ready else {}
        if repo_ready:
            r = REPOSITORY_REQUIREMENT
            self.items[r.addon_id] = {'addonid': r.addon_id, 'enabled': True, 'version': '1.0.1'}
        surface = self
        class Monitor:
            def abortRequested(self): return False
            def waitForAbort(self, delay): return True  # Cancel waits, never stall tests.
        class Dialog:
            def select(self, title, labels): return next(surface.selections, -1)
            def yesno(self, *args): return True
            def ok(self, *args): surface.dialogs.append(args)
            def textviewer(self, *args): surface.dialogs.append(args)
        class DialogProgressBG:
            def create(self, heading, message=""): surface.progress_events.append(("create", heading, message))
            def update(self, percent=0, heading="", message=""): surface.progress_events.append(("update", percent, heading, message))
            def close(self): surface.progress_events.append(("close",))
        class Addon:
            def __init__(self, addon_id=None): self.addon_id = addon_id
            def openSettings(self): surface.settings.append(self.addon_id)
        self.modules = {
            'xbmc': types.SimpleNamespace(executeJSONRPC=self.rpc,
                executebuiltin=self.builtin, Monitor=Monitor, getSkinDir=lambda: self.skin,
                getCondVisibility=self.condition,
                LOGINFO=1, log=lambda message, level: self.log.append(message)),
            'xbmcaddon': types.SimpleNamespace(Addon=Addon),
            'xbmcgui': types.SimpleNamespace(Dialog=Dialog, DialogProgressBG=DialogProgressBG),
            'xbmcvfs': types.SimpleNamespace(translatePath=self.translate),
        }
    def translate(self, path):
        if path != 'special://profile': raise AssertionError(path)
        return str(self.profile)
    def rpc(self, data):
        if self.bad_response: return 'not json'
        request = json.loads(data)
        self.assert_request(request)
        method, params = request['method'], request['params']
        if method == 'Application.GetProperties': result = {'version': {'major': self.major}}
        elif method == 'Addons.GetAddonDetails':
            if params['addonid'] not in self.items:
                return json.dumps({'jsonrpc':'2.0','id':1,'error': {'code':-32602,'message':'Invalid params.'}})
            result = {'addon': self.items[params['addonid']]}
        elif method == 'Addons.SetAddonEnabled':
            self.items[params['addonid']]['enabled'] = params['enabled']; result = 'OK'
        elif method == 'Settings.GetSettingValue':
            result = {'value': self.locale[params['setting']]}
        elif method == 'Settings.SetSettingValue':
            self.locale[params['setting']] = params['value']
            self.commands.append('SetSettingValue('+params['setting']+')')
            result = True
        else: raise AssertionError('Unsupported RPC: ' + method)
        return json.dumps({'jsonrpc':'2.0','id':1,'result':result})
    @staticmethod
    def assert_request(request):
        assert request['jsonrpc'] == '2.0' and request['id'] == 1
    def condition(self, expression):
        if expression != 'Skin.HasSetting(touchmode)':
            raise AssertionError(expression)
        return self.touchmode
    def builtin(self, command, wait=False):
        self.commands.append(command)
        if command == 'Skin.SetBool(touchmode)':
            self.touchmode = True
        elif command == 'Skin.Reset(touchmode)':
            self.touchmode = False
        elif command.startswith('InstallAddon('):
            addon_id = command[len('InstallAddon('):-1]
            req = next(r for r in ALL_REQUIREMENTS if r.addon_id == addon_id)
            self.items[addon_id] = {'addonid':addon_id, 'enabled': True, 'version': '.'.join(map(str,req.min_version))}
        elif command == 'UpdateAddonRepos':
            pass
        elif command == 'Addon.OpenSettings(plugin.service.emby-next-gen)':
            self.settings.append('plugin.service.emby-next-gen')
        elif not command.startswith('ActivateWindow('):
            raise AssertionError('Unsupported builtin: ' + command)
    def run(self, argv=()):
        with patch.dict(sys.modules, self.modules), patch.object(sys, 'argv', [str(ADDON/'default.py'), *argv]):
            runpy.run_path(str(ADDON / 'default.py'), run_name='__main__')

class WizardTests(unittest.TestCase):
    def test_versions(self):
        self.assertTrue(version_at_least('3.3.12', (3,3,12)))
        self.assertTrue(version_at_least('3.3.12+omega.1', (3,3,12)))
        self.assertFalse(version_at_least('3.3.11', (3,3,12)))
        self.assertFalse(version_at_least('3.3.12-beta', (3,3,12)))
        self.assertFalse(version_at_least('n/a', (1,)))
    def test_actual_module_surface_default_to_install_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Surface(Path(tmp), [0,6], ready=False); s.run()
            self.assertEqual(set(s.items), {r.addon_id for r in REQUIREMENTS + MEDIA_REQUIREMENTS} | {REPOSITORY_REQUIREMENT.addon_id})
            self.assertEqual(len(s.commands), 1 + len(REQUIREMENTS + MEDIA_REQUIREMENTS))
            self.assertFalse(any('Restart' in x or 'Reload' in x or 'Skin.SetSkin' in x for x in s.commands))
            self.assertTrue(any('Alle benötigten Addons' in str(x) for x in s.dialogs))
    def test_progress_tracks_verified_addons_and_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Surface(Path(tmp), [0, 6], ready=False); s.run()
            events = s.progress_events
            self.assertEqual(events[0][0], 'create')
            self.assertEqual(events[-1], ('close',))
            updates = [e for e in events if e[0] == 'update']
            self.assertEqual(updates[0][1], 0)
            self.assertEqual(updates[-1][1], 100)
            self.assertEqual([e[1] for e in updates], sorted(e[1] for e in updates))
            self.assertTrue(any('Warte auf Installation' in e[3] for e in updates))
            for req in REQUIREMENTS + MEDIA_REQUIREMENTS:
                self.assertTrue(any(req.label in e[3] for e in updates))

    def test_progress_failure_closes_and_names_addon(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Surface(Path(tmp), [0, 6], ready=False)
            s.modules['xbmc'].executebuiltin = lambda command, wait=False: None
            s.run()
            self.assertEqual(s.progress_events[-1], ('close',))
            self.assertFalse(any(e[0] == 'update' and e[1] == 100 for e in s.progress_events))
            self.assertTrue(any('Einrichtung unvollständig. Arctic Fuse 3' in str(x) for x in s.dialogs))
            self.assertFalse(any('Alle benötigten Addons' in str(x) for x in s.dialogs))

    def test_progress_exception_always_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Surface(Path(tmp), [0, 6])
            with patch('resources.lib.setupwizard.ui.ensure_requirement', side_effect=RuntimeError):
                s.run()
            self.assertEqual(s.progress_events[-1], ('close',))
            self.assertTrue(any('Vorgang nicht abgeschlossen' in str(x) for x in s.dialogs))

    def test_progress_rejected_confirmation_no_install(self):
        from resources.lib.setupwizard.ui import install_with_progress
        s = Surface(Path('.'), ready=False)
        okay, detail = install_with_progress(KodiAddonAPI(s.modules['xbmc']), REQUIREMENTS,
            types.SimpleNamespace(yesno=lambda *args: False), s.modules['xbmc'].Monitor(),
            s.modules['xbmcgui'].DialogProgressBG(), lambda _: None)
        self.assertFalse(okay)
        self.assertIn('nicht freigegeben', detail)
        self.assertEqual(s.commands, [])
        self.assertEqual(s.progress_events, [])

    def test_progress_shutdown_stops_before_install(self):
        from resources.lib.setupwizard.ui import install_with_progress
        s = Surface(Path('.'), ready=False)
        okay, _ = install_with_progress(KodiAddonAPI(s.modules['xbmc']), REQUIREMENTS,
            s.modules['xbmcgui'].Dialog(), types.SimpleNamespace(abortRequested=lambda: True),
            s.modules['xbmcgui'].DialogProgressBG(), lambda _: None, approved=True)
        self.assertFalse(okay)
        self.assertEqual(s.commands, [])
        self.assertEqual(s.progress_events[-1], ('close',))

    def test_wait_reports_each_poll(self):
        s = Surface(Path('.'), ready=False)
        ticks, statuses = [0], []
        self.assertFalse(bounded_wait(KodiAddonAPI(s.modules['xbmc']), REQUIREMENTS[0],
            timeout=2, clock=lambda: ticks[0], sleep=lambda n: ticks.__setitem__(0, ticks[0] + n),
            on_status=statuses.append))
        self.assertEqual(statuses, ['nicht installiert'] * 3)

    def test_default_layout_apply_and_restore_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed_nodes(root)
            s = Surface(root, [1,0,0,3,0,6]); s.run()
            self.assertTrue(any('Medienmenü geschrieben' in str(x) for x in s.dialogs))
            self.assertTrue(any('wiederhergestellt' in str(x) for x in s.dialogs))
            self.assertFalse((root / 'userdata').exists())
            self.assertFalse(any(root.glob('addon_data/**/*.json')))
            self.assertEqual(s.commands, [])
    def test_live_arctic_refuses_configuration_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Surface(Path(tmp), [1,3,6], skin='skin.arctic.fuse.3'); s.run()
            self.assertEqual(list(Path(tmp).iterdir()), [])
            self.assertTrue(any('Estuary' in str(x) for x in s.dialogs))
    def test_emBy_settings_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Surface(Path(tmp), [2,0,6]); s.run()
            self.assertEqual(s.settings, ['plugin.service.emby-next-gen'])
            self.assertEqual(s.commands, [])
    def test_youtube_opens_addon_and_returns(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Surface(Path(tmp), [2,2]); s.run()
            self.assertEqual(s.commands, ['ActivateWindow(Videos,plugin://plugin.video.youtube/,return)'])
    def test_unsupported_kodi_rejects_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Surface(Path(tmp), [0], major=22); s.run()
            self.assertEqual(s.commands, [])
            self.assertTrue(any('Kodi 21' in str(x) for x in s.dialogs))
    def test_status_menu_no_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Surface(Path(tmp), [4,6], ready=False); s.run()
            self.assertEqual(s.commands, [])
            self.assertTrue(any('nicht installiert' in str(x) for x in s.dialogs))
    def test_inspection_failure_no_install(self):
        s = Surface(Path('.')); s.bad_response = True
        api = KodiAddonAPI(s.modules['xbmc'])
        self.assertFalse(ensure_requirement(api, REQUIREMENTS[0], lambda _: True, lambda _: True, lambda _: None))
        self.assertEqual(s.commands, [])
    def test_install_requires_confirmation(self):
        s = Surface(Path('.'), ready=False); api = KodiAddonAPI(s.modules['xbmc'])
        self.assertFalse(ensure_requirement(api, REQUIREMENTS[0], lambda _: False, lambda _: True, lambda _: None))
        self.assertEqual(s.commands, [])
    def test_disabled_addon_enable_and_readback(self):
        s = Surface(Path('.')); req = REQUIREMENTS[0]; s.items[req.addon_id]['enabled'] = False
        api = KodiAddonAPI(s.modules['xbmc'])
        self.assertTrue(ensure_requirement(api, req, lambda _: True, lambda r: check_requirement(api,r)[0], lambda _: None))
        self.assertEqual(s.commands, [])
    def test_api_rejects_unlisted_id(self):
        s = Surface(Path('.')); api = KodiAddonAPI(s.modules['xbmc'])
        with self.assertRaises(ValueError): api.install('malicious),RestartApp(')
    def test_wait_observes_version_and_enable_not_only_presence(self):
        s = Surface(Path('.')); req = REQUIREMENTS[0]; s.items[req.addon_id]['version'] = '1.0'
        api = KodiAddonAPI(s.modules['xbmc']); ticks = [0]
        def sleep(n): ticks[0] += n
        self.assertFalse(bounded_wait(api,req,timeout=2,clock=lambda:ticks[0],sleep=sleep))
        self.assertEqual(ticks[0],2)
        s.items[req.addon_id]['version']='3.3.12'
        self.assertTrue(bounded_wait(api,req,timeout=0))
    def test_wait_can_abort(self):
        s=Surface(Path('.'),ready=False); api=KodiAddonAPI(s.modules['xbmc'])
        self.assertFalse(bounded_wait(api,REQUIREMENTS[0],monitor=s.modules['xbmc'].Monitor()))

if __name__ == '__main__': unittest.main()
