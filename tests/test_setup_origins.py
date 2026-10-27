"""Local origin contracts; SQLite fixtures are not native-device acceptance."""
import sys
import tempfile
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'script.serph91p.setup'))
from resources.lib.setupwizard import addons


class StrictOriginTests(unittest.TestCase):
    def test_matching_version_is_not_matching_origin(self):
        class API:
            strict_origins = True
            def details(self, addon_id):
                return {'enabled': True, 'version': '99.0'}
            def origin(self, addon_id): return 'repository.serph91p'
        req = addons.REQUIREMENTS_BY_ID['skin.arctic.fuse.3']
        okay, status = addons.check_requirement(API(), req)
        self.assertFalse(okay)
        self.assertIn('Herkunft', status)
    def test_readonly_origin_reader_fails_closed(self):
        from resources.lib.setupwizard.origins import SQLiteOriginReader, OriginUnavailable
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / 'Addons33.db'
            conn = sqlite3.connect(database)
            conn.execute('CREATE TABLE installed (addonID TEXT, origin TEXT)')
            conn.execute('INSERT INTO installed VALUES (?, ?)', ('skin.amber', 'repository.xbmc.org'))
            conn.commit()
            reader = SQLiteOriginReader(lambda path: tmp)
            self.assertEqual(reader('skin.amber'), 'repository.xbmc.org')
            with self.assertRaises(OriginUnavailable): reader('plugin.video.youtube')
            conn.execute('BEGIN EXCLUSIVE')
            with self.assertRaises(OriginUnavailable): reader('skin.amber')
            conn.rollback()
            conn.close()
            before = database.read_bytes()
            self.assertEqual(reader('skin.amber'), 'repository.xbmc.org')
            self.assertEqual(before, database.read_bytes())
            with self.assertRaises(ValueError): reader('not.allowlisted')
            database.rename(Path(tmp) / 'real.db')
            database.symlink_to(Path(tmp) / 'real.db')
            with self.assertRaises(OriginUnavailable): reader('skin.amber')

    def test_missing_schema_and_module_are_unverifiable(self):
        from resources.lib.setupwizard.origins import SQLiteOriginReader, OriginUnavailable
        with tempfile.TemporaryDirectory() as tmp:
            reader = SQLiteOriginReader(lambda path: tmp)
            with self.assertRaises(OriginUnavailable): reader('skin.amber')
            self.assertFalse((Path(tmp) / 'Addons33.db').exists())
            sqlite3.connect(Path(tmp) / 'Addons33.db').close()
            with self.assertRaises(OriginUnavailable): reader('skin.amber')
            with patch.dict(sys.modules, {'sqlite3': None}):
                with self.assertRaises(OriginUnavailable): reader('skin.amber')

    def test_strict_no_provider_never_reports_success(self):
        from resources.lib.setupwizard.origins import check_requirement_strict
        class API:
            def details(self, addon_id): return {'enabled': True, 'version': '99'}
        self.assertFalse(check_requirement_strict(API(), addons.REQUIREMENTS[0])[0])
    def test_repository_plan_and_maintained_floors(self):
        from resources.lib.setupwizard.origins import ordered_requirements
        from resources.lib.setupwizard.profiles import PROFILES, requirements_for
        for profile in PROFILES:
            leaves = requirements_for(profile, addons.REQUIREMENTS, addons.PROFILE_REQUIREMENTS, addons.MEDIA_REQUIREMENTS)
            plan = ordered_requirements(leaves)
            repos = [r.addon_id for r in plan if r.addon_id.startswith('repository.')]
            self.assertIn('repository.beta.emby.kodi', repos)
            self.assertIn('repository.jurialmunkey', repos)  # Shared Top Rated uses TMDb Helper.
            self.assertEqual('repository.kodinerds' in repos, profile.key == 'touch')
            self.assertEqual(plan[len(repos):], leaves)
        req = addons.REQUIREMENTS_BY_ID['skin.estuary.modv2']
        class API:
            def details(self, addon_id): return {'enabled': True, 'version': '21.4+omega.9'}
        self.assertFalse(addons.check_requirement(API(), req)[0])
        self.assertTrue(addons.version_at_least('21.4+omega.10', '21.4+omega.10'))
        self.assertTrue(addons.version_at_least('21.4+omega.11', '21.4+omega.10'))
        self.assertFalse(addons.version_at_least('21.4+omega.2', '21.4+omega.10'))
        self.assertEqual(addons.REQUIREMENTS_BY_ID['script.tubecast'].min_version_string, '1.6.1+omega.2')
        self.assertEqual(addons.REQUIREMENTS_BY_ID['plugin.video.gronkhtv'].min_version, (2, 3, 10))

    def test_policy_cancel_preserves_settings_and_blocks(self):
        from resources.lib.setupwizard.origins import repository_policy, confirm_repository_policy
        class API:
            def __init__(self): self.calls = []
            def rpc(self, method, params):
                self.calls.append((method, params))
                self_test.assertEqual(method, 'Settings.GetSettingValue')
                return {'result': {'value': 0}}
        self_test = self
        api = API()
        state = repository_policy(api)
        self.assertTrue(state.needs_choice)
        self.assertTrue(state.automatic_updates)
        self.assertEqual([call[1]['setting'] for call in api.calls],
                         ['addons.updatemode', 'general.addonupdates'])
        self.assertFalse(confirm_repository_policy(api, lambda message: False, lambda: self.fail('settings opened')))
        self.assertTrue(all(call[0] == 'Settings.GetSettingValue' for call in api.calls))

    def test_wrong_origin_never_installs_even_when_old_or_disabled(self):
        class API:
            strict_origins = True
            def details(self, addon_id): return {'enabled': False, 'version': '0.1'}
            def origin(self, addon_id): return 'repository.serph91p'
            def request_install(self, addon_id): self_test.fail('unexpected install')
            def set_enabled(self, addon_id): self_test.fail('unexpected enable')
        self_test = self
        req = addons.REQUIREMENTS[0]
        self.assertFalse(addons.ensure_requirement(API(), req, lambda _: self.fail('unexpected consent'),
                                                 lambda _: self.fail('unexpected wait'), lambda _: None))

    def test_injected_kodi_reader_enables_strict_checks(self):
        class XBMC:
            def executeJSONRPC(self, request):
                return '{"result":{"addon":{"enabled":true,"version":"99"}}}'
        api = addons.KodiAddonAPI(XBMC(), origin_read_fn=lambda _: 'repository.debian.languages')
        self.assertTrue(api.strict_origins)
        self.assertFalse(addons.check_requirement(api, addons.REQUIREMENTS_BY_ID['skin.amber'])[0])

    def test_user_opening_settings_is_not_consent_readback(self):
        from resources.lib.setupwizard.origins import confirm_repository_policy
        class API:
            def rpc(self, method, params): return {'result': {'value': 0}}
        opened = []
        self.assertFalse(confirm_repository_policy(API(), lambda _: True, lambda: opened.append(True)))
        self.assertEqual(opened, [True])


if __name__ == '__main__': unittest.main()
