"""Distribution-specific PVR source contracts, not physical-device evidence."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'script.serph91p.setup'))
from resources.lib.setupwizard import addons, origins, pvr


class API:
    strict_origins = True
    def __init__(self, linux=False, android=False, le=False, le_origin=pvr.SYSTEM_ORIGIN, present=True):
        self.linux, self.android, self.le = linux, android, le
        self.le_origin, self.present, self.mutations = le_origin, present, []
        self.xbmc = self
    def getCondVisibility(self, value):
        return {'System.Platform.Linux':self.linux,'System.Platform.Android':self.android}.get(value, False)
    def details(self, addon_id):
        if addon_id == pvr.LIBREELEC_REPOSITORY and not self.le: return None
        if addon_id == 'pvr.iptvsimple' and not self.present: return None
        return {'enabled':True,'version':'99.0'}
    def origin(self, addon_id):
        if addon_id == pvr.LIBREELEC_REPOSITORY: return self.le_origin
        if addon_id == 'pvr.iptvsimple' and self.le: return pvr.LIBREELEC_REPOSITORY
        if addon_id == 'pvr.iptvsimple' and self.linux and not self.android: return pvr.SYSTEM_ORIGIN
        return pvr.OFFICIAL_REPOSITORY
    def install(self, addon_id): self.mutations.append(('install',addon_id))
    def enable(self, addon_id): self.mutations.append(('enable',addon_id))


class PVRContractTests(unittest.TestCase):
    def test_android_keeps_strict_official_repository_origin(self):
        api=API(linux=True,android=True)
        self.assertTrue(origins.check_requirement_strict(api, addons.REQUIREMENTS_BY_ID['pvr.iptvsimple'])[0])
        self.assertEqual(pvr.distribution(api).repository, pvr.OFFICIAL_REPOSITORY)

    def test_libreelec_leaf_uses_verified_system_repository(self):
        api=API(linux=True,le=True)
        self.assertTrue(origins.check_requirement_strict(api, addons.REQUIREMENTS_BY_ID['pvr.iptvsimple'])[0])
        self.assertTrue(origins.check_origin(api,pvr.LIBREELEC_REPOSITORY)[0])

    def test_libreelec_plan_does_not_schedule_wrong_pvr_repository(self):
        api=API(linux=True,le=True)
        plan=origins.ordered_requirements((addons.REQUIREMENTS_BY_ID['pvr.iptvsimple'],),api=api)
        self.assertEqual([r.addon_id for r in plan], [pvr.LIBREELEC_REPOSITORY,'pvr.iptvsimple'])

    def test_linux_system_uuid_is_unverified_not_wrong_source(self):
        api=API(linux=True)
        ok,status=origins.check_requirement_strict(api,addons.REQUIREMENTS_BY_ID['pvr.iptvsimple'])
        self.assertFalse(ok)
        self.assertIn('OS-verwaltet',status)

    def test_linux_missing_pvr_never_attempts_install_or_enable(self):
        api=API(linux=True,present=False)
        result=addons.ensure_requirement(api,addons.REQUIREMENTS_BY_ID['pvr.iptvsimple'],lambda _:True,lambda _:True,lambda _:None)
        self.assertFalse(result)
        self.assertEqual(api.mutations,[])

    def test_repo_id_without_native_system_origin_does_not_grant_libreelec(self):
        api=API(linux=True,le=True,le_origin='repository.serph91p')
        self.assertFalse(pvr.distribution(api).automatic_install)
        self.assertFalse(origins.check_origin(api,pvr.LIBREELEC_REPOSITORY)[0])

    def test_system_uuid_never_exempts_other_leaf_origins(self):
        api=API(linux=True)
        api.origin=lambda addon_id:pvr.SYSTEM_ORIGIN
        self.assertFalse(origins.check_origin(api,'skin.amber')[0])

    def test_unknown_generic_linux_no_repository_guess(self):
        api=API(linux=True)
        contract=pvr.distribution(api)
        self.assertIsNone(contract.repository)
        self.assertIn('Paket-Herkunft',contract.detail)


    def test_native_linux_preflight_does_not_advise_source_reinstall(self):
        import tempfile
        from tests.test_setup_flow import guided
        with tempfile.TemporaryDirectory() as tmp:
            surface=guided(Path(tmp),[0,0],ready=False)
            surface.modules['xbmc'].getCondVisibility=lambda expression: expression == 'System.Platform.Linux'
            surface.run()
            messages=' '.join(str(value) for value in surface.dialogs)
            self.assertIn('OS-verwaltet',messages)
            self.assertNotIn('manuell neu installieren',messages)
            self.assertEqual(surface.commands,[])


if __name__=='__main__': unittest.main()
