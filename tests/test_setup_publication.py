"""Offline publication acceptance tests using disposable target git repositories."""
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest import mock

from scripts import build_repository as builder
from scripts import setup_publication as setup

ROOT = Path(__file__).resolve().parents[1]


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode().strip()


class SetupPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in setup.INPUTS:
            source, destination = ROOT / name, self.root / name
            if source.is_dir():
                shutil.copytree(source, destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        git(self.root, 'init', '-q')
        git(self.root, 'add', '.')
        # Fixture-only commit: never changes the user's checkout or history.
        git(self.root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
        self.sha = git(self.root, 'rev-parse', 'HEAD')
        (self.root / 'repo').mkdir()
        (self.root / '_site').mkdir()
        (self.root / '_site' / 'sentinel').write_bytes(b'previous site')
        self.versions = {'repository.serph91p': '1.0.1', 'plugin.unrelated': '2.1.0'}
        self.manifest()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(builder, 'ADDONS', []).start()
        mock.patch.object(builder, 'download_current_package', side_effect=self.download).start()

    def manifest(self):
        outer = ET.Element('addons')
        for aid, version in self.versions.items():
            ET.SubElement(outer, 'addon', id=aid, version=version)
        (self.root / 'repo' / 'addons.xml').write_bytes(ET.tostring(outer))

    def download(self, aid, version, destination):
        with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(aid + '/addon.xml', f'<addon id="{aid}" version="{version}"/>')

    def build(self):
        builder.build_first_party_repository(self.sha, self.root)

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for name in ('repo', '_site') for p in (self.root / name).rglob('*') if p.is_file()}

    def test_staged_site_wizard_bootstrap_originals_not_mirrored(self):
        self.build()
        site = self.root / '_site'
        package = site / setup.ADDON_ID / (setup.ADDON_ID + '-0.4.1.zip')
        self.assertTrue(package.is_file())
        self.assertIn(package.name, (package.parent / 'index.html').read_text())
        ids = {a.get('id') for a in ET.parse(site / 'addons.xml').getroot()}
        self.assertEqual(ids, {setup.ADDON_ID, 'repository.serph91p', 'plugin.unrelated'})
        setup.validate_site(site)
        self.assertEqual(len(list((site / 'setup-bootstrap').rglob('addons.xml*'))), 6)
        self.assertFalse(list((site / 'setup-bootstrap').rglob('*.zip')))
        for source in ('repository.jurialmunkey', 'repository.beta.emby.kodi', 'repository.kodinerds'):
            self.assertFalse((site / source).exists())
            catalog = ET.parse(site / 'setup-bootstrap' / source / 'addons.xml').getroot()
            self.assertEqual([a.get('id') for a in catalog], [source])
        provenance = json.loads((site / 'setup-source-provenance.json').read_text())
        self.assertEqual(provenance['kind'], 'first-party-target-source-v1')
        self.assertEqual(provenance['target_commit'], self.sha)
        self.assertEqual(provenance['artifact_sha256'], hashlib.sha256(package.read_bytes()).hexdigest())
        self.assertNotIn('validation_run_id', provenance)
        self.assertTrue((site / 'plugin.unrelated' / 'plugin.unrelated-2.1.0.zip').is_file())

    def test_source_must_match_exact_head(self):
        for value in ('main', '../bad', 'a' * 40, self.sha.upper()):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                builder.build_first_party_repository(value, self.root)

    def test_dirty_source_rejected_without_touching_outputs(self):
        before = self.snapshot()
        (self.root / setup.ADDON_ID / 'default.py').write_text('changed')
        with self.assertRaisesRegex(RuntimeError, 'differs'):
            self.build()
        self.assertEqual(before, self.snapshot())

    def test_symlink_source_rejected(self):
        path = self.root / setup.ADDON_ID / 'default.py'
        path.unlink()
        path.symlink_to(self.root / 'addon.xml')
        with self.assertRaisesRegex(RuntimeError, 'unsafe'):
            self.build()

    def test_tracked_symlink_rejected(self):
        path = self.root / setup.ADDON_ID / 'default.py'
        path.unlink()
        path.symlink_to('../addon.xml')
        git(self.root, 'add', '.')
        git(self.root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'bad fixture')
        self.sha = git(self.root, 'rev-parse', 'HEAD')
        with self.assertRaisesRegex(RuntimeError, 'unsafe'):
            self.build()

    def test_untracked_source_rejected(self):
        (self.root / setup.ADDON_ID / 'extra.py').write_text('unexpected')
        with self.assertRaisesRegex(RuntimeError, 'untracked'):
            self.build()

    def test_downgrade_rejected_outputs_unchanged(self):
        self.versions[setup.ADDON_ID] = '0.5.0'
        self.manifest()
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, 'newer'):
            self.build()
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.root / '_staging').exists())

    def test_validation_failure_preserves_outputs(self):
        before = self.snapshot()
        with mock.patch.object(setup, 'validate_site', side_effect=RuntimeError('bad site')):
            with self.assertRaisesRegex(RuntimeError, 'bad site'):
                self.build()
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.root / '_staging').exists())
        self.assertFalse((self.root / '_temp').exists())

    def test_original_metadata_digest_tampering_rejected_even_if_committed(self):
        path = self.root / 'setup-bootstrap/repository.jurialmunkey/addons.xml'
        data = path.read_bytes().replace(b'jurialmunkey', b'jurialmunkey', 1) + b'\n'
        path.write_bytes(data)
        path.with_name('addons.xml.md5').write_text(hashlib.md5(data).hexdigest() + '\n')
        git(self.root, 'add', '.')
        git(self.root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'changed metadata fixture')
        self.sha = git(self.root, 'rev-parse', 'HEAD')
        with self.assertRaisesRegex(RuntimeError, 'reviewed'):
            self.build()

    def test_first_party_is_not_a_dispatch_source(self):
        with self.assertRaisesRegex(RuntimeError, 'configured ADDONS'):
            builder.validate_dispatch_payload({'source_repo': setup.SOURCE_REPOSITORY})

    def test_bad_external_sha_and_workflow_still_rejected(self):
        from tests.test_immutable_publication import _valid_dispatch
        # Restore production external policy for these guard checks only.
        # The Twitch policy is explicit and no first-party entry is added to it.
        config = {'owner': 'Serph91P', 'repo': 'plugin.video.twitch',
                  'addon_id': 'plugin.video.twitch', 'publication_enabled': True,
                  'validation_workflow': 'Add-on Validations',
                  'validation_workflow_path': '.github/workflows/addon-validations.yml',
                  'publication_branch': 'develop'}
        with mock.patch.object(builder, 'ADDONS', [config]):
            for payload in (_valid_dispatch(candidate_sha='not-a-sha'),
                            _valid_dispatch(validation_workflow='Untrusted workflow')):
                with self.assertRaises(RuntimeError):
                    builder.validate_dispatch_payload(payload)

    def test_source_tree_traversal_rejected(self):
        real_git = setup._git
        def unsafe(root, *args):
            if args[0] == 'ls-tree':
                return b'100644 blob ' + b'a' * 40 + b'\t../escape\0'
            return real_git(root, *args)
        with mock.patch.object(setup, '_git', side_effect=unsafe):
            with self.assertRaisesRegex(RuntimeError, 'unsafe'):
                self.build()

    def test_external_immutable_build_includes_first_party_without_forged_evidence(self):
        import datetime
        from tests.test_immutable_publication import (
            _make_addon_zip, _make_evidence_archive, _make_package_archive,
            _make_mock_api_responses, _valid_dispatch, _valid_evidence, _zip_sha256)
        self.versions['plugin.video.twitch'] = '3.1.8'
        self.manifest()
        package = self.root / 'fixture-addon.zip'
        _make_addon_zip(package, 'plugin.video.twitch', '3.1.8')
        evidence_archive, package_archive = self.root / 'fixture-evidence.zip', self.root / 'fixture-package.zip'
        _make_evidence_archive(_valid_evidence(artifact_sha256=_zip_sha256(package)), evidence_archive)
        _make_package_archive(package, package_archive)
        api_get, download = _make_mock_api_responses(evidence_archive, package_archive)
        config = {'owner': 'Serph91P', 'repo': 'plugin.video.twitch',
                  'addon_id': 'plugin.video.twitch', 'publication_enabled': True,
                  'validation_workflow': 'Add-on Validations',
                  'validation_workflow_path': '.github/workflows/addon-validations.yml',
                  'validation_workflow_id': 211623879, 'publication_branch': 'develop',
                  'package_artifact_name': 'addon-package', 'evidence_artifact_name': 'validation-evidence',
                  'runtime_entries': ('addon.xml', 'changelog.txt', 'resources/')}
        strict_fetch = builder.fetch_validated_run_artifacts
        # Explicit fixture-time injection; the complete production validator runs.
        def at_fixture_time(*args):
            return strict_fetch(*args, now=datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc))
        with (mock.patch.object(builder, 'ADDONS', [config]),
              mock.patch.object(builder, 'source_github_api_get', side_effect=api_get),
              mock.patch.object(builder, 'source_download_file', side_effect=download),
              mock.patch.object(builder, 'fetch_validated_run_artifacts', side_effect=at_fixture_time),
              mock.patch.dict('os.environ', {'SOURCE_GITHUB_TOKEN': 'offline-fixture-only'})):
            builder.build_immutable_repository(_valid_dispatch(), self.root, target_commit=self.sha)
        site = self.root / '_site'
        setup.validate_site(site)
        ids = {a.get('id') for a in ET.parse(site / 'addons.xml').getroot()}
        self.assertEqual(ids, {'plugin.video.twitch', 'plugin.unrelated', setup.ADDON_ID, 'repository.serph91p'})
        self.assertTrue((site / setup.ADDON_ID / (setup.ADDON_ID + '-0.4.1.zip')).is_file())

    def test_workflow_has_explicit_nonrecursive_target_source_mode(self):
        workflow = (ROOT / '.github/workflows/publish-setup-source.yml').read_text()
        external = (ROOT / '.github/workflows/update-repository.yml').read_text()
        self.assertIn('--first-party --target-commit', workflow)
        self.assertIn("github.event_name == 'repository_dispatch'", external)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertNotIn('repository-dispatch@', workflow)
