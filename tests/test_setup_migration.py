"""Existing-addon takeover is read-only until an explicit native migration."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'script.serph91p.setup'))
from resources.lib.setupwizard.addons import REQUIREMENTS_BY_ID
from resources.lib.setupwizard.migration import inspect_existing, safe_candidate_version, verify_migration


class API:
    strict_origins = True
    def __init__(self, addon='skin.amber', version='3.99.2', origin='repository.xbmc.org', enabled=True):
        self.item = {'addonid': addon, 'version': version, 'enabled': enabled}
        self.source = origin
        self.xbmc = SimpleNamespace(getCondVisibility=lambda _: False)
    def details(self, addon): return self.item
    def origin(self, addon):
        if isinstance(self.source, Exception): raise self.source
        return self.source
    def install(self, _): raise AssertionError('No installation during inventory')
    def enable(self, _): raise AssertionError('No activation during inventory')


class MigrationTests(unittest.TestCase):
    def setUp(self): self.req = REQUIREMENTS_BY_ID['skin.amber']
    def test_correct_existing_addon_is_adopted_without_reinstallation(self):
        api=API()
        self.assertEqual(inspect_existing(api,self.req).state,'adopt')
        self.assertEqual(api.item,{'addonid':'skin.amber','version':'3.99.2','enabled':True})
    def test_missing_addon_is_not_a_migration(self):
        api=API();api.item=None
        self.assertEqual(inspect_existing(api,self.req).state,'missing')
    def test_wrong_readable_source_gets_explicit_migration_not_adoption(self):
        plan=inspect_existing(API(origin='repository.old.vendor'),self.req)
        self.assertEqual(plan.state,'migrate')
        self.assertEqual(plan.repository,'repository.xbmc.org')
    def test_empty_but_readable_zip_origin_can_be_migrated(self):
        self.assertEqual(inspect_existing(API(origin=''),self.req).state,'migrate')
    def test_unreadable_origin_never_grants_migration_permission(self):
        self.assertEqual(inspect_existing(API(origin=RuntimeError('unavailable')),self.req).state,'blocked')
    def test_api_inspection_error_blocks(self):
        api=API();api.details=lambda _: (_ for _ in ()).throw(RuntimeError('unavailable'))
        self.assertEqual(inspect_existing(api,self.req).state,'blocked')
    def test_disabled_current_addon_only_needs_native_enable(self):
        self.assertEqual(inspect_existing(API(enabled=False),self.req).state,'enable')
    def test_old_installed_version_needs_native_update_not_installaddon(self):
        self.assertEqual(inspect_existing(API(version='3.1'),self.req).state,'migrate')
    def test_unknown_installed_version_cannot_be_proven_non_downgrade(self):
        self.assertEqual(inspect_existing(API(version='unknown'),self.req).state,'blocked')
    def test_candidates_must_satisfy_floor_and_never_downgrade_existing(self):
        plan=inspect_existing(API(version='4.0',origin=''),self.req)
        for value in ('3.99.2','0.0','unknown'):
            self.assertFalse(safe_candidate_version(plan,value),value)
        self.assertTrue(safe_candidate_version(plan,'4.0'))
        self.assertTrue(safe_candidate_version(plan,'4.1'))
    def test_candidate_must_satisfy_profile_floor_even_if_installed_older(self):
        plan=inspect_existing(API(version='2.0',origin=''),self.req)
        self.assertFalse(safe_candidate_version(plan,'3.1'))
        self.assertTrue(safe_candidate_version(plan,'3.99.2'))
    def test_success_requires_live_correct_source_version_and_enable_state(self):
        api=API(version='4.0',origin='repository.old.vendor')
        before=inspect_existing(api,self.req)
        self.assertFalse(verify_migration(api,before))
        api.source='repository.xbmc.org';api.item['version']='3.99.2'
        self.assertFalse(verify_migration(api,before))
        api.item['version']='4.0';api.item['enabled']=False
        self.assertFalse(verify_migration(api,before))
        api.item['enabled']=True
        self.assertTrue(verify_migration(api,before))
    def test_current_maintained_youtube_fork_is_not_migrated_to_older_official(self):
        req=REQUIREMENTS_BY_ID['plugin.video.youtube']
        self.assertEqual(req.min_version,(7,4,4,1))
        plan=inspect_existing(API(addon=req.addon_id,version='7.4.4.1',origin='repository.serph91p'),req)
        self.assertEqual(plan.state,'adopt')
        self.assertEqual(plan.repository,'repository.serph91p')
    def test_non_allowlisted_identifier_is_rejected(self):
        req=SimpleNamespace(addon_id='unknown.addon',label='Unknown',min_version=(0,),min_version_string='')
        with self.assertRaises(ValueError):inspect_existing(API(),req)

    def test_ensure_never_uses_installaddon_as_existing_version_upgrade(self):
        from resources.lib.setupwizard.addons import ensure_requirement
        for enabled in (True,False):
            api=API(version='2.0',enabled=enabled)
            self.assertFalse(ensure_requirement(api,self.req,
                lambda _:self.fail('Native migration must happen before install consent'),
                lambda _:self.fail('No pointless old-version wait'),lambda _:None))


if __name__=='__main__':unittest.main()
