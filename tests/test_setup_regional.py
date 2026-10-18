import copy
import json
from pathlib import Path
import tempfile
import unittest
from tests.test_setup_wizard import Surface
from resources.lib.setupwizard import regional as r, config as c
from resources.lib.setupwizard.addons import KodiAddonAPI
from resources.lib.setupwizard.common_layouts import apply_common_layout
from resources.lib.setupwizard.navigation import empty_bindings
from resources.lib.setupwizard.touch import restore_layout


class API:
    def __init__(self):
        self.values=r.reference()
        self.values['locale.country']='USA'
        self.values['locale.keyboardlayouts']=['English QWERTY']
        self.calls=[]; self.fail=None; self.language_effect=False; self.clock_effect=False
    def rpc(self,method,params):
        self.calls.append((method,copy.deepcopy(params)))
        key=params['setting']
        assert key in r.KEYS
        if method=='Settings.GetSettingValue':
            return {'result':{'value':copy.deepcopy(self.values[key])}}
        assert method=='Settings.SetSettingValue'
        if key==self.fail:
            self.fail=None
            return {'result':False}
        self.values[key]=copy.deepcopy(params['value'])
        if self.clock_effect and key=='locale.use24hourclock':
            self.values['locale.timeformat']='callback-generated-timeformat'
        if self.language_effect and key=='locale.language':
            self.values['locale.country']='parent-generated-default'
        return {'result':True}
    def mutations(self):
        return [x for x in self.calls if x[0]=='Settings.SetSettingValue']


class LocaleTests(unittest.TestCase):
    def setup_paths(self,tmp):
        root=Path(tmp); (root/'setupwizard-backups').mkdir()
        return root,root/'setupwizard-backups'/'backup'

    def test_apply_readback_and_idempotent_restore_with_native_list_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,backup=self.setup_paths(tmp); api=API(); before=copy.deepcopy(api.values)
            self.assertTrue(r.apply(root,backup,api,approved=True))
            self.assertEqual(api.values,r.reference())
            self.assertIsInstance(api.values['locale.keyboardlayouts'],list)
            record=r.preflight_restore(root,backup,api)
            self.assertEqual(record['before'],before)
            self.assertEqual(json.loads((backup/c.MANIFEST).read_text()),r.ONLY_LOCALE)
            r.restore(root,backup,api)
            self.assertEqual(api.values,before)
            self.assertEqual(r.restore(root,backup,api),[])

    def test_declined_or_missing_approval_has_no_api_or_filesystem_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,backup=self.setup_paths(tmp); api=API()
            with self.assertRaises(ValueError): r.apply(root,backup,api)
            self.assertEqual(api.calls,[])
            self.assertFalse(backup.exists())

    def test_noop_does_not_create_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,backup=self.setup_paths(tmp); api=API();api.values=r.reference()
            self.assertEqual(r.apply(root,backup,api,approved=True),[])
            self.assertEqual(api.mutations(),[])
            self.assertFalse(backup.exists())

    def test_setter_failure_rolls_back_and_preserves_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,backup=self.setup_paths(tmp);api=API()
            api.values['locale.charset']='UTF-8'
            before=copy.deepcopy(api.values);api.fail='locale.country'
            with self.assertRaises(RuntimeError): r.apply(root,backup,api,approved=True)
            self.assertEqual(api.values,before)
            self.assertTrue((backup/r.JOURNAL).is_file())

    def test_parent_side_effects_do_not_prevent_inflight_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,backup=self.setup_paths(tmp);api=API()
            api.values['locale.language']='resource.language.de_de'
            before=copy.deepcopy(api.values);api.language_effect=True;api.fail='locale.country'
            with self.assertRaises(RuntimeError): r.apply(root,backup,api,approved=True)
            self.assertEqual(api.values,before)

    def test_clock_callback_requires_timeformat_after_clock_on_apply_and_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,backup=self.setup_paths(tmp);api=API();api.clock_effect=True
            api.values['locale.use24hourclock']='false'
            api.values['locale.timeformat']='h:mm:ss xx'
            before=copy.deepcopy(api.values)
            r.apply(root,backup,api,approved=True)
            self.assertEqual(api.values,r.reference())
            r.restore(root,backup,api)
            self.assertEqual(api.values,before)

    def test_keyboard_layouts_cannot_exceed_native_max_three(self):
        values=r.reference();values['locale.keyboardlayouts']=['one','two','three','four']
        with self.assertRaises(ValueError):r._validate_values(values)

    def test_user_drift_refuses_before_file_or_native_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,backup=self.setup_paths(tmp);api=API()
            apply_common_layout(root,backup,'touch',empty_bindings())
            r.apply(root,backup,api,approved=True)
            (root/'unchanged').write_text('sentinel')
            skin=(root/c.SKIN_SETTINGS)  # Touch uses its separate settings file.
            path=root/'addon_data/skin.estuary.modv2/settings.xml'; before=path.read_bytes()
            api.values['locale.country']='Germany'
            surface=Surface(root)
            surface.locale=api.values
            with self.assertRaises(ValueError): restore_layout(root,backup,surface.modules['xbmc'])
            self.assertEqual(path.read_bytes(),before)
            self.assertFalse(any(x.startswith('SetSettingValue') for x in surface.commands))

    def test_corruption_and_foreign_keys_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,backup=self.setup_paths(tmp);api=API();r.apply(root,backup,api,approved=True)
            path=backup/r.JOURNAL;record=json.loads(path.read_text())
            record['after']['services.webserver']='true'
            record['sha256']=r._digest({k:record[k] for k in ('schema','before','after')})
            path.write_text(json.dumps(record))
            calls=len(api.calls)
            with self.assertRaises(ValueError):r.restore(root,backup,api)
            self.assertEqual(len(api.calls),calls)

    def test_symlink_journal_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,backup=self.setup_paths(tmp);api=API();r.apply(root,backup,api,approved=True)
            journal=backup/r.JOURNAL; foreign=root/'foreign';journal.rename(foreign);journal.symlink_to(foreign)
            with self.assertRaises(ValueError):r.restore(root,backup,api)

    def test_actual_script_surface_applies_locale_and_file_restore_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);s=Surface(root,[1,6]);s.locale['locale.country']='USA'
            before=copy.deepcopy(s.locale);s.run()
            backups=list((root/'setupwizard-backups').iterdir());self.assertEqual(len(backups),1)
            self.assertEqual(s.locale,r.reference())
            self.assertTrue(any('Referenz-Region' in str(x) for x in s.dialogs))
            restore_layout(root,backups[0],s.modules['xbmc'])
            self.assertEqual(s.locale,before)
            self.assertFalse((root/c.SKIN_SETTINGS).exists())

    def test_missing_combined_journal_refuses_before_restoring_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,backup=self.setup_paths(tmp);api=API()
            apply_common_layout(root,backup,'touch',empty_bindings())
            r.apply(root,backup,api,approved=True)
            meta=json.loads((backup/c.MANIFEST).read_text())
            self.assertEqual(meta['schema'],8)
            (backup/r.JOURNAL).unlink()
            path=root/'addon_data/skin.estuary.modv2/settings.xml';before=path.read_bytes()
            s=Surface(root);s.locale=api.values
            with self.assertRaises(ValueError):restore_layout(root,backup,s.modules['xbmc'])
            self.assertEqual(path.read_bytes(),before)
            self.assertFalse(any(x.startswith('SetSettingValue') for x in s.commands))

    def test_locale_only_restore_router(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,backup=self.setup_paths(tmp);s=Surface(root);s.locale['locale.country']='USA'
            before=copy.deepcopy(s.locale);api=KodiAddonAPI(s.modules['xbmc'])
            r.apply(root,backup,api,approved=True)
            restore_layout(root,backup,s.modules['xbmc'])
            self.assertEqual(s.locale,before)


if __name__ == '__main__':unittest.main()
