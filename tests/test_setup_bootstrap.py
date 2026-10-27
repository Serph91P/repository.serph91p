"""Offline bootstrap contracts; live original ZIP validation is a separate CLI."""
import copy
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
import zipfile
from tools import build_setup_bootstrap as b
from tools import validate_setup_sources as v
from tools.build_setup_repository import build as build_repository
from tools.build_setup_bundle import PROFILES, manifest, build as build_bundle


class BootstrapTests(unittest.TestCase):
    def test_root_exposes_only_own_and_declared_bootstrap_feeds(self):
        root = b.validate_root()
        dirs = root.findall("extension[@point='xbmc.addon.repository']/dir")
        self.assertEqual(len(dirs), 1+len(b.SOURCES))
        self.assertFalse(root.findall("requires/import[@addon='repository.jurialmunkey']"))
        for directory in dirs[1:]:
            self.assertEqual(directory.get('minversion'), '21.0.0')
            self.assertEqual(directory.get('maxversion'), '21.9.999')
            self.assertIn('/setup-bootstrap/', directory.findtext('info'))

    def test_local_catalogs_contain_one_original_repository_each(self):
        files = b.local_files()
        self.assertEqual(len(files), 2*len(b.SOURCES))
        for source in b.SOURCES:
            root = ET.fromstring(files[source['id'] + '/addons.xml'])
            self.assertEqual(len(root), 1)
            addon = root[0]
            self.assertEqual(addon.get('id'), source['id'])
            self.assertEqual(addon.get('version'), source['version'])
            self.assertEqual(len(addon.findall("extension[@point='xbmc.addon.repository']")), 1)
            self.assertFalse(any(i.get('addon', '').startswith('repository.') for i in addon.findall('requires/import')))
            path = addon.findtext("extension[@point='xbmc.addon.metadata']/path")
            if source['id'] in ('repository.jurialmunkey','repository.adamsbuilds'):
                self.assertEqual(path, source['path'])
            else:
                self.assertIsNone(path)
            resolved = source['datadir'] + (path or source['id'] + '/' + source['id'] + '-' + source['version'] + '.zip')
            self.assertEqual(resolved, b.source_url(source))

    def test_build_is_reproducible_metadata_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / 'one', Path(tmp) / 'two'
            self.assertEqual(b.build(first), b.build(second))
            for name in b.build(first):
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
            self.assertFalse(list(first.rglob('*.zip')))

    def test_repository_zip_is_reproducible_without_bootstrap_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = build_repository(Path(tmp) / 'one')
            second = build_repository(Path(tmp) / 'two')
            self.assertEqual(first.name, 'repository.serph91p-1.0.3.zip')
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.namelist(), ['repository.serph91p/addon.xml',
                    'repository.serph91p/resources/icon.png', 'repository.serph91p/resources/fanart.jpg'])

    def test_bundles_never_import_repositories_and_are_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            for profile in PROFILES:
                _, xml = manifest(profile)
                self.assertFalse(any(i.get('addon').startswith('repository.') for i in ET.fromstring(xml).findall('requires/import')))
                first = build_bundle(profile, Path(tmp) / 'one')
                second = build_bundle(profile, Path(tmp) / 'two')
                self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_symlink_output_is_rejected_without_touching_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'target'
            target.mkdir()
            link = root / 'link'
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                b.build(link / 'nested')
            self.assertEqual(list(target.iterdir()), [])

    def test_symlink_file_target_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            foreign = root / 'foreign'
            foreign.write_bytes(b'preserve')
            target = root / 'out'
            target.symlink_to(foreign)
            with self.assertRaises(ValueError):
                b.safe_write(target, b'changed')
            self.assertEqual(foreign.read_bytes(), b'preserve')

    def test_checksum_or_leaf_injection_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative, data in b.local_files().items():
                b.safe_write(root / relative, data)
            source = b.SOURCES[0]
            path = root / source['id'] / 'addons.xml'
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            with self.assertRaisesRegex(ValueError, 'MD5'):
                b.local_files(root)
            outer = ET.fromstring(original)
            ET.SubElement(outer, 'addon', id='skin.foreign', version='1.0')
            data = ET.tostring(outer)
            path.write_bytes(data)
            path.with_name('addons.xml.md5').write_text(hashlib.md5(data).hexdigest() + '\n')
            with self.assertRaisesRegex(ValueError, 'exactly one'):
                b.local_files(root)

    def test_xml_entities_rejected(self):
        with self.assertRaises(ValueError):
            b.parse_xml(b'<!DOCTYPE addon [<!ENTITY x "bad">]><addon/>')

    def fixture_zip(self, root, source, members=None):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr(source['id'] + '/addon.xml', ET.tostring(root))
            for name, content in members or []:
                archive.writestr(name, content)
        payload = data.getvalue()
        fixture_source = dict(source, sha256=hashlib.sha256(payload).hexdigest())
        return payload, fixture_source

    def test_original_reader_pins_hash_and_identity_without_extracting(self):
        source = b.SOURCES[0]
        root = ET.fromstring(b.local_files()[source['id'] + '/addons.xml'])[0]
        root.find("extension[@point='xbmc.addon.metadata']").remove(root.find("extension[@point='xbmc.addon.metadata']/path"))
        data, fixture = self.fixture_zip(root, source, [('../../not-extracted', b'ignored')])
        parsed = b.original_manifest(data, fixture)
        self.assertEqual(b.catalog(parsed, fixture), b.local_files()[source['id'] + '/addons.xml'])
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            b.original_manifest(data + b'changed', fixture)
        wrong = dict(fixture, version='99.0')
        with self.assertRaisesRegex(ValueError, 'identity'):
            b.original_manifest(data, wrong)
        root.find("extension[@point='xbmc.addon.repository']").set('point', 'xbmc.python.script')
        data, fixture = self.fixture_zip(root, source)
        with self.assertRaisesRegex(ValueError, 'normal repository'):
            b.original_manifest(data, fixture)

    def test_validator_rejects_catalog_metadata_tampering(self):
        local = b.local_files()
        fake_originals = {}
        fixture_sources = []
        for source in b.SOURCES:
            addon = ET.fromstring(local[source['id'] + '/addons.xml'])[0]
            metadata = addon.find("extension[@point='xbmc.addon.metadata']")
            if metadata.find('path') is not None:
                metadata.remove(metadata.find('path'))
            data, fixture = self.fixture_zip(addon, source)
            fake_originals[b.source_url(source)] = data
            fixture_sources.append(fixture)
        def fetcher(url):
            if url in fake_originals:
                return fake_originals[url]
            raise OSError('unpublished offline fixture')
        with patch.object(v, 'SOURCES', fixture_sources):
            result = v.validate(fetcher)
            self.assertEqual(len(result['original_repositories']), len(b.SOURCES))
            self.assertFalse(result['publication_ready'])
            altered = dict(local)
            key = b.SOURCES[0]['id'] + '/addons.xml'
            altered[key] = altered[key].replace(b'Alpha Repository', b'Altered Repository')
            with patch.object(v, 'local_files', return_value=altered), self.assertRaisesRegex(ValueError, 'differs from original'):
                v.validate(fetcher)

    def test_only_allowlisted_public_tls_urls(self):
        for url in ('file:///etc/passwd', 'http://repo.kodinerds.net/addons',
                    'https://127.0.0.1/', 'https://embydata.com@localhost/',
                    'https://embydata.com:8443/x', 'https://unknown.example/x'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                v.checked_url(url)
        for source in b.SOURCES:
            self.assertEqual(v.checked_url(b.source_url(source)), b.source_url(source))


if __name__ == '__main__':
    unittest.main()
