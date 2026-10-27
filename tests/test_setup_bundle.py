import ast
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
import zipfile
from tools.build_setup_bundle import build, manifest, VERSION, PROFILES
from resources.lib.setupwizard.addons import (REQUIREMENTS, PROFILE_REQUIREMENTS,
    MEDIA_REQUIREMENTS, PROFILE_REQUIREMENTS)
from resources.lib.setupwizard.profiles import requirements_for


class NativeBundleTests(unittest.TestCase):
    def test_each_bundle_has_exact_fixed_profile_dependencies(self):
        for profile in PROFILES:
            with self.subTest(profile=profile.key):
                addon_id, xml = manifest(profile)
                root = ET.fromstring(xml)
                self.assertEqual(root.get('id'), 'script.module.serph91p.setup.' + profile.key)
                self.assertEqual(root.get('version'), VERSION)
                imports = root.findall('./requires/import')
                self.assertEqual(len(imports), len({x.get('addon') for x in imports}))
                actual = {x.get('addon'): x.get('version') for x in imports}
                expected = {'xbmc.python': '3.0.0'}
                for req in requirements_for(
                        profile, REQUIREMENTS, PROFILE_REQUIREMENTS, MEDIA_REQUIREMENTS):
                    expected[req.addon_id] = req.min_version_string or '.'.join(map(str, req.min_version + (0,) * max(0, 3 - len(req.min_version))))
                self.assertEqual(actual, expected)
                self.assertFalse(any(addon.startswith('repository.') for addon in actual))
                self.assertTrue(all(x.get('optional') is None for x in imports))
                self.assertEqual(root.find('./extension[@point="xbmc.python.module"]').get('library'), 'lib')
                self.assertEqual(len(root.findall('./extension')), 2)
                if profile.key != 'arctic':
                    self.assertNotIn('skin.arctic.fuse.3', actual)
                    self.assertNotIn('script.skinvariables', actual)

    def test_archive_has_only_native_manifest_and_inert_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            for profile in PROFILES:
                target = build(profile, Path(tmp))
                addon_id, xml = manifest(profile)
                with zipfile.ZipFile(target) as archive:
                    self.assertIsNone(archive.testzip())
                    self.assertEqual(set(archive.namelist()), {
                        addon_id + '/addon.xml', addon_id + '/lib/__init__.py'})
                    self.assertEqual(archive.read(addon_id + '/addon.xml'), xml)
                    tree = ast.parse(archive.read(addon_id + '/lib/__init__.py'))
                    self.assertEqual(len(tree.body), 1)
                    self.assertIsInstance(tree.body[0], ast.Expr)
                    self.assertIsInstance(tree.body[0].value, ast.Constant)
                    self.assertIsInstance(tree.body[0].value.value, str)

    def test_parsed_bundle_contract_needs_no_individual_wizard_installs(self):
        # Emulated installed state, not a real Kodi dependency-installation claim.
        from tests.test_setup_wizard import Surface
        for index, profile in enumerate(PROFILES):
            with self.subTest(profile=profile.key), tempfile.TemporaryDirectory() as tmp:
                surface = Surface(Path(tmp), [0, 6], ready=False, profile_index=index)
                for item in ET.fromstring(manifest(profile)[1]).findall('./requires/import'):
                    if item.get('addon') != 'xbmc.python':
                        surface.items[item.get('addon')] = {
                            'addonid': item.get('addon'), 'version': item.get('version'), 'enabled': True}
                from resources.lib.setupwizard.origins import ordered_requirements
                for req in ordered_requirements(requirements_for(profile, REQUIREMENTS, PROFILE_REQUIREMENTS, MEDIA_REQUIREMENTS)):
                    surface.items[req.addon_id] = {'addonid': req.addon_id, 'version': req.min_version_string or '.'.join(map(str, req.min_version)), 'enabled': True}
                surface.run()
                self.assertTrue(any('Alle benötigten Addons' in str(x) for x in surface.dialogs))
                self.assertFalse(any(c.startswith(('InstallAddon(', 'enable')) for c in surface.commands))

    def test_build_is_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            for profile in PROFILES:
                first = build(profile, Path(tmp) / 'first').read_bytes()
                second = build(profile, Path(tmp) / 'second').read_bytes()
                self.assertEqual(first, second)

    def test_rejects_unknown_profile(self):
        with self.assertRaises(ValueError):
            manifest(replace(PROFILES[0], key='../../foreign'))

    def test_rejects_symlink_target_without_overwriting_foreign_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            foreign = parent / 'foreign'
            foreign.write_bytes(b'preserve')
            out = parent / 'out'
            out.mkdir()
            addon_id, _ = manifest(PROFILES[0])
            (out / (addon_id + '-' + VERSION + '.zip')).symlink_to(foreign)
            with self.assertRaises(ValueError):
                build(PROFILES[0], out)
            self.assertEqual(foreign.read_bytes(), b'preserve')

    def test_rejects_symlink_output_ancestor(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            foreign = parent / 'foreign'
            foreign.mkdir()
            link = parent / 'link'
            link.symlink_to(foreign, target_is_directory=True)
            with self.assertRaises(ValueError):
                build(PROFILES[0], link / 'nested')
            self.assertEqual(list(foreign.iterdir()), [])


if __name__ == '__main__': unittest.main()
