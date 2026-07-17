import hashlib
import io
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from scripts import build_repository as builder


FIXTURE_SHA = "25b5920a9204acedf3d05dc009d78918d2bf0648"
FIXTURE_RUN_ID = 29549561132
FIXTURE_ADDON_ID = "plugin.video.twitch"
FIXTURE_VERSION = "3.1.8"
FIXTURE_ASSET = "plugin.video.twitch-3.1.8.zip"
FIXTURE_PUBLICATION_ID = "plugin.video.twitch@3.1.8"
FIXTURE_SOURCE_REPO = "Serph91P/plugin.video.twitch"
FIXTURE_BRANCH = "develop"
FIXTURE_ARTIFACT_SHA256 = (
    "d83db0534b640f2283d9c7ded69d9f8406c274f13385cf045e2a77184058caaa"
)


def _valid_dispatch(**overrides):
    payload = {
        "source_repo": FIXTURE_SOURCE_REPO,
        "candidate_sha": FIXTURE_SHA,
        "validation_run_id": FIXTURE_RUN_ID,
        "validation_head_sha": FIXTURE_SHA,
        "validation_workflow": "Add-on Validations",
        "expected_branch": "develop",
        "package_artifact_name": "addon-package",
        "evidence_artifact_name": "validation-evidence",
    }
    payload.update(overrides)
    return payload


def _valid_evidence(**overrides):
    evidence = {
        "candidate_sha": FIXTURE_SHA,
        "validation_head_sha": FIXTURE_SHA,
        "validation_run_id": "29549561132",
        "addon_id": FIXTURE_ADDON_ID,
        "addon_version": FIXTURE_VERSION,
        "asset_name": FIXTURE_ASSET,
        "artifact_sha256": FIXTURE_ARTIFACT_SHA256,
        "tag": "",
        "publication_id": FIXTURE_PUBLICATION_ID,
    }
    evidence.update(overrides)
    return evidence


def _valid_run(**overrides):
    run = {
        "id": FIXTURE_RUN_ID,
        "head_sha": FIXTURE_SHA,
        "conclusion": "success",
        "name": "Add-on Validations",
        "head_branch": "develop",
    }
    run.update(overrides)
    return run


def _make_addon_zip(path, addon_id, version, member_count=5):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        metadata = (
            f'<addon id="{addon_id}" name="Test" version="{version}" '
            f'provider-name="Test"><extension point="xbmc.addon.metadata">'
            f"<assets><icon>icon.png</icon></assets></extension></addon>"
        )
        archive.writestr(f"{addon_id}/addon.xml", metadata)
        archive.writestr(f"{addon_id}/icon.png", b"icon-data")
        for i in range(member_count - 2):
            archive.writestr(f"{addon_id}/file{i}.txt", f"data{i}".encode())
    return path


def _zip_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_evidence_archive(evidence, dest):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("validation-evidence.json", json.dumps(evidence, indent=2))
    return dest


def _make_package_archive(addon_zip_path, dest, member_name=FIXTURE_ASSET):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(addon_zip_path, member_name)
    return dest


def _make_mock_api_responses(evidence_archive, package_archive):
    run_data = _valid_run()

    def api_get(url):
        if "/git/ref/heads/develop" in url:
            return {"object": {"sha": FIXTURE_SHA}}
        expected_prefix = (
            f"{builder.GH_API}/repos/{FIXTURE_SOURCE_REPO}/actions/runs/"
            f"{FIXTURE_RUN_ID}"
        )
        if not url.startswith(expected_prefix):
            raise RuntimeError(f"Unexpected API URL: {url}")
        if "/actions/runs/" in url and "/artifacts" not in url:
            return run_data
        if "/actions/runs/" in url and "/artifacts" in url:
            return {
                "artifacts": [
                    {
                        "name": "validation-evidence",
                        "id": 1,
                        "expired": False,
                        "archive_download_url": "https://example.invalid/evidence.zip",
                    },
                    {
                        "name": "addon-package",
                        "id": 2,
                        "expired": False,
                        "archive_download_url": "https://example.invalid/package.zip",
                    },
                ]
            }
        raise RuntimeError(f"Unexpected API URL: {url}")

    def download(url, dest):
        if "evidence" in url:
            shutil.copy2(evidence_archive, dest)
        elif "package" in url:
            shutil.copy2(package_archive, dest)
        else:
            raise RuntimeError(f"Unexpected download URL: {url}")

    return api_get, download


def _make_repo_root(tmpdir):
    root = Path(tmpdir)
    (root / "addon.xml").write_text(
        '<addon id="repository.serph91p" name="Repo" version="1.0.0" '
        'provider-name="Test"/>',
        encoding="utf-8",
    )
    resources = root / "resources"
    resources.mkdir()
    (resources / "icon.png").write_bytes(b"icon-data")
    return root


def _snapshot_tree(directory):
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


class TestValidateDispatchPayload(unittest.TestCase):
    def test_valid_payload_passes(self):
        builder.validate_dispatch_payload(_valid_dispatch())

    def test_non_dict_is_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.validate_dispatch_payload("not-a-dict")

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.validate_dispatch_payload(_valid_dispatch(addons=[], extra="x"))

    def test_missing_source_repo_is_rejected(self):
        payload = _valid_dispatch()
        del payload["source_repo"]
        with self.assertRaises(RuntimeError):
            builder.validate_dispatch_payload(payload)

    def test_source_repo_without_slash_is_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.validate_dispatch_payload(_valid_dispatch(source_repo="noslash"))

    def test_missing_candidate_sha_is_rejected(self):
        payload = _valid_dispatch()
        del payload["candidate_sha"]
        with self.assertRaises(RuntimeError):
            builder.validate_dispatch_payload(payload)

    def test_short_candidate_sha_is_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.validate_dispatch_payload(_valid_dispatch(candidate_sha="abc"))

    def test_non_hex_candidate_sha_is_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.validate_dispatch_payload(_valid_dispatch(candidate_sha="g" * 40))

    def test_missing_validation_run_id_is_rejected(self):
        payload = _valid_dispatch()
        del payload["validation_run_id"]
        with self.assertRaises(RuntimeError):
            builder.validate_dispatch_payload(payload)

    def test_string_validation_run_id_is_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.validate_dispatch_payload(
                _valid_dispatch(validation_run_id="not-int")
            )

    def test_negative_validation_run_id_is_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.validate_dispatch_payload(_valid_dispatch(validation_run_id=-1))

    def test_missing_validation_head_sha_is_rejected(self):
        payload = _valid_dispatch()
        del payload["validation_head_sha"]
        with self.assertRaises(RuntimeError):
            builder.validate_dispatch_payload(payload)

    def test_missing_validation_workflow_is_rejected(self):
        payload = _valid_dispatch()
        del payload["validation_workflow"]
        with self.assertRaises(RuntimeError):
            builder.validate_dispatch_payload(payload)

    def test_missing_expected_branch_is_rejected(self):
        payload = _valid_dispatch()
        del payload["expected_branch"]
        with self.assertRaises(RuntimeError):
            builder.validate_dispatch_payload(payload)

    def test_defaults_for_optional_artifact_names(self):
        payload = _valid_dispatch()
        del payload["package_artifact_name"]
        del payload["evidence_artifact_name"]
        builder.validate_dispatch_payload(payload)


class TestValidateImmutableEvidence(unittest.TestCase):
    def test_valid_evidence_passes(self):
        builder.validate_immutable_evidence(
            _valid_evidence(),
            FIXTURE_SHA,
            FIXTURE_RUN_ID,
            FIXTURE_SHA,
        )

    def test_valid_evidence_with_string_run_id_passes(self):
        evidence = _valid_evidence(validation_run_id="29549561132")
        builder.validate_immutable_evidence(
            evidence,
            FIXTURE_SHA,
            FIXTURE_RUN_ID,
            FIXTURE_SHA,
        )

    def test_missing_required_field_is_rejected(self):
        for field in (
            "candidate_sha",
            "validation_head_sha",
            "validation_run_id",
            "addon_id",
            "addon_version",
            "publication_id",
            "artifact_sha256",
            "asset_name",
        ):
            with self.subTest(field=field):
                evidence = _valid_evidence()
                del evidence[field]
                with self.assertRaises(RuntimeError):
                    builder.validate_immutable_evidence(
                        evidence,
                        FIXTURE_SHA,
                        FIXTURE_RUN_ID,
                        FIXTURE_SHA,
                    )

    def test_wrong_candidate_sha_is_rejected(self):
        evidence = _valid_evidence(candidate_sha="a" * 40)
        with self.assertRaises(RuntimeError):
            builder.validate_immutable_evidence(
                evidence,
                FIXTURE_SHA,
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
            )

    def test_wrong_validation_head_sha_is_rejected(self):
        evidence = _valid_evidence(validation_head_sha="b" * 40)
        with self.assertRaises(RuntimeError):
            builder.validate_immutable_evidence(
                evidence,
                FIXTURE_SHA,
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
            )

    def test_wrong_run_id_is_rejected(self):
        evidence = _valid_evidence(validation_run_id="99999999999")
        with self.assertRaises(RuntimeError):
            builder.validate_immutable_evidence(
                evidence,
                FIXTURE_SHA,
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
            )

    def test_candidate_sha_must_be_40_hex(self):
        evidence = _valid_evidence(candidate_sha="not-a-sha")
        with self.assertRaises(RuntimeError):
            builder.validate_immutable_evidence(
                evidence,
                "not-a-sha",
                FIXTURE_RUN_ID,
                "not-a-sha",
            )

    def test_addon_id_and_version_must_be_present(self):
        for field in ("addon_id", "addon_version"):
            with self.subTest(field=field):
                evidence = _valid_evidence(**{field: ""})
                with self.assertRaises(RuntimeError):
                    builder.validate_immutable_evidence(
                        evidence,
                        FIXTURE_SHA,
                        FIXTURE_RUN_ID,
                        FIXTURE_SHA,
                    )

    def test_publication_id_must_match_addon_id_and_version(self):
        evidence = _valid_evidence(publication_id="wrong@wrong")
        with self.assertRaises(RuntimeError):
            builder.validate_immutable_evidence(
                evidence,
                FIXTURE_SHA,
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
            )

    def test_non_dict_evidence_is_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.validate_immutable_evidence(
                "not-a-dict",
                FIXTURE_SHA,
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
            )

    def test_non_numeric_run_id_in_evidence_is_rejected(self):
        evidence = _valid_evidence(validation_run_id="not-a-number")
        with self.assertRaises(RuntimeError):
            builder.validate_immutable_evidence(
                evidence,
                FIXTURE_SHA,
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
            )


class TestValidateGithubRun(unittest.TestCase):
    def test_valid_run_passes(self):
        builder.validate_github_run(
            _valid_run(),
            FIXTURE_RUN_ID,
            FIXTURE_SHA,
            "Add-on Validations",
            FIXTURE_BRANCH,
        )

    def test_wrong_run_id_is_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.validate_github_run(
                _valid_run(id=99999999999),
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
                "Add-on Validations",
                FIXTURE_BRANCH,
            )

    def test_wrong_head_sha_is_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.validate_github_run(
                _valid_run(head_sha="deadbeef" + "0" * 32),
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
                "Add-on Validations",
                FIXTURE_BRANCH,
            )

    def test_wrong_workflow_name_is_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.validate_github_run(
                _valid_run(name="Wrong Workflow"),
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
                "Add-on Validations",
                FIXTURE_BRANCH,
            )

    def test_wrong_branch_is_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.validate_github_run(
                _valid_run(head_branch="main"),
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
                "Add-on Validations",
                FIXTURE_BRANCH,
            )

    def test_failed_conclusion_is_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.validate_github_run(
                _valid_run(conclusion="failure"),
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
                "Add-on Validations",
                FIXTURE_BRANCH,
            )

    def test_missing_conclusion_is_rejected(self):
        run = _valid_run()
        del run["conclusion"]
        with self.assertRaises(RuntimeError):
            builder.validate_github_run(
                run,
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
                "Add-on Validations",
                FIXTURE_BRANCH,
            )

    def test_in_progress_conclusion_is_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.validate_github_run(
                _valid_run(conclusion=None),
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
                "Add-on Validations",
                FIXTURE_BRANCH,
            )

    def test_non_dict_run_data_is_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.validate_github_run(
                "not-a-dict",
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
                "Add-on Validations",
                FIXTURE_BRANCH,
            )


class TestVerifyPackageSha256(unittest.TestCase):
    def test_matching_sha256_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.zip"
            _make_addon_zip(path, "plugin.example", "1.0.0")
            expected = _zip_sha256(path)
            builder.verify_package_sha256(path, expected)

    def test_mismatched_sha256_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.zip"
            _make_addon_zip(path, "plugin.example", "1.0.0")
            with self.assertRaises(RuntimeError):
                builder.verify_package_sha256(path, "0" * 64)


class TestValidateArchiveTopology(unittest.TestCase):
    def test_valid_topology_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.zip"
            _make_addon_zip(path, "plugin.example", "1.0.0")
            builder.validate_archive_topology(path, "plugin.example", "1.0.0")

    def test_member_with_wrong_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad.zip"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("wrong/addon.xml", "<addon/>")
                archive.writestr("plugin.example/addon.xml", "<addon/>")
            with self.assertRaises(RuntimeError):
                builder.validate_archive_topology(path, "plugin.example", "1.0.0")

    def test_missing_addon_xml_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "noxml.zip"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("plugin.example/file.txt", b"data")
            with self.assertRaises(RuntimeError):
                builder.validate_archive_topology(path, "plugin.example", "1.0.0")

    def test_embedded_id_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "wrongid.zip"
            metadata = (
                '<addon id="plugin.wrong" name="Test" version="1.0.0" '
                'provider-name="Test"/>'
            )
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("plugin.wrong/addon.xml", metadata)
            with self.assertRaises(RuntimeError):
                builder.validate_archive_topology(path, "plugin.example", "1.0.0")

    def test_embedded_version_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "wrongver.zip"
            metadata = (
                '<addon id="plugin.example" name="Test" version="2.0.0" '
                'provider-name="Test"/>'
            )
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("plugin.example/addon.xml", metadata)
            with self.assertRaises(RuntimeError):
                builder.validate_archive_topology(path, "plugin.example", "1.0.0")

    def test_symlink_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "symlink.zip"
            metadata = (
                '<addon id="plugin.example" name="Test" version="1.0.0" '
                'provider-name="Test"/>'
            )
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("plugin.example/addon.xml", metadata)
                symlink = zipfile.ZipInfo("plugin.example/link")
                symlink.create_system = 3
                symlink.external_attr = 0o120777 << 16
                symlink.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(symlink, "target")
            with self.assertRaises(RuntimeError):
                builder.validate_archive_topology(path, "plugin.example", "1.0.0")


class TestPublishValidatedAddon(unittest.TestCase):
    def test_returns_addon_element(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            zip_path = root / "addon.zip"
            _make_addon_zip(zip_path, FIXTURE_ADDON_ID, FIXTURE_VERSION)
            output = root / "repo"
            output.mkdir()

            addon = builder.publish_validated_addon(
                zip_path,
                FIXTURE_ASSET,
                output,
            )
            self.assertEqual(addon.get("id"), FIXTURE_ADDON_ID)
            self.assertEqual(addon.get("version"), FIXTURE_VERSION)

    def test_copies_zip_to_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            zip_path = root / "addon.zip"
            _make_addon_zip(zip_path, FIXTURE_ADDON_ID, FIXTURE_VERSION)
            output = root / "repo"
            output.mkdir()

            builder.publish_validated_addon(zip_path, FIXTURE_ASSET, output)

            dest = output / FIXTURE_ADDON_ID / FIXTURE_ASSET
            self.assertTrue(dest.is_file())
            self.assertEqual(dest.read_bytes(), zip_path.read_bytes())

    def test_does_not_touch_other_addons(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            existing = root / "repo" / "plugin.other"
            existing.mkdir(parents=True)
            (existing / "existing.zip").write_bytes(b"old")

            zip_path = root / "addon.zip"
            _make_addon_zip(zip_path, FIXTURE_ADDON_ID, FIXTURE_VERSION)

            builder.publish_validated_addon(zip_path, FIXTURE_ASSET, root / "repo")

            self.assertTrue((existing / "existing.zip").is_file())
            self.assertEqual((existing / "existing.zip").read_bytes(), b"old")


class TestBuildImmutableRepository(unittest.TestCase):
    _target_addon_config = {
        "owner": "Serph91P",
        "repo": "plugin.video.twitch",
        "addon_id": "plugin.video.twitch",
        "branch": "main",
    }

    def _build_with_mock(self, root, dispatch_payload, api_get, download):
        with (
            mock.patch.dict(
                os.environ, {"SOURCE_GITHUB_TOKEN": "test-source-token"}, clear=False
            ),
            mock.patch.object(builder, "github_api_get", side_effect=api_get),
            mock.patch.object(builder, "source_github_api_get", side_effect=api_get),
            mock.patch.object(builder, "download_file", side_effect=download),
            mock.patch.object(builder, "source_download_file", side_effect=download),
            mock.patch.object(builder, "ADDONS", [self._target_addon_config]),
        ):
            builder.build_immutable_repository(dispatch_payload, root)

    def test_unknown_source_repo_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            payload = _valid_dispatch(source_repo="unknown/repo")
            with self.assertRaises(RuntimeError):
                builder.build_immutable_repository(payload, root)

    def test_branch_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            payload = _valid_dispatch(expected_branch="wrong-branch")
            with self.assertRaises(RuntimeError):
                builder.build_immutable_repository(payload, root)

    def test_moving_expected_branch_is_rejected_before_artifact_download(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)

            def api_get(url):
                if "/actions/runs/" in url and "/artifacts" not in url:
                    return _valid_run()
                if "/git/ref/heads/develop" in url:
                    return {"object": {"sha": "a" * 40}}
                raise RuntimeError(f"Unexpected URL: {url}")

            with (
                mock.patch.object(builder, "github_api_get", side_effect=api_get),
                mock.patch.object(builder, "download_file") as download,
                mock.patch.object(builder, "ADDONS", [self._target_addon_config]),
                self.assertRaises(RuntimeError),
            ):
                builder.build_immutable_repository(_valid_dispatch(), root)
            download.assert_not_called()

    def test_branch_move_after_artifact_download_is_rejected_before_promotion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            existing_repo = root / "repo"
            existing_site = root / "_site"
            existing_repo.mkdir()
            existing_site.mkdir()
            (existing_repo / "sentinel.txt").write_text("old repo", encoding="utf-8")
            (existing_site / "sentinel.txt").write_text("old site", encoding="utf-8")

            addon_zip = root / "addon.zip"
            _make_addon_zip(addon_zip, FIXTURE_ADDON_ID, FIXTURE_VERSION)
            evidence_archive = root / "evidence.zip"
            package_archive = root / "package.zip"
            evidence = _valid_evidence(artifact_sha256=_zip_sha256(addon_zip))
            _make_evidence_archive(evidence, evidence_archive)
            _make_package_archive(addon_zip, package_archive)
            base_api_get, download = _make_mock_api_responses(
                evidence_archive, package_archive
            )
            ref_reads = 0

            def api_get(url):
                nonlocal ref_reads
                if "/git/ref/heads/" in url:
                    ref_reads += 1
                    sha = FIXTURE_SHA if ref_reads == 1 else "b" * 40
                    return {"object": {"sha": sha}}
                return base_api_get(url)

            with self.assertRaisesRegex(RuntimeError, "moved"):
                self._build_with_mock(root, _valid_dispatch(), api_get, download)

            self.assertEqual(ref_reads, 2)
            self.assertEqual(
                (existing_repo / "sentinel.txt").read_text(encoding="utf-8"),
                "old repo",
            )
            self.assertEqual(
                (existing_site / "sentinel.txt").read_text(encoding="utf-8"),
                "old site",
            )
            self.assertFalse((root / "_staging").exists())

    def test_workflow_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            payload = _valid_dispatch(validation_workflow="Wrong Workflow")

            def api_get(url):
                if "/actions/runs/" in url and "/artifacts" not in url:
                    return _valid_run()
                if "/actions/runs/" in url and "/artifacts" in url:
                    return {"artifacts": []}
                raise RuntimeError(f"Unexpected URL: {url}")

            with (
                mock.patch.object(builder, "github_api_get", side_effect=api_get),
                self.assertRaises(RuntimeError),
            ):
                builder.build_immutable_repository(payload, root)

    def test_failed_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            addon_zip = root / "addon.zip"
            _make_addon_zip(addon_zip, FIXTURE_ADDON_ID, FIXTURE_VERSION)
            evidence_archive = root / "evidence.zip"
            package_archive = root / "package.zip"
            evidence = _valid_evidence(artifact_sha256=_zip_sha256(addon_zip))
            _make_evidence_archive(evidence, evidence_archive)
            _make_package_archive(addon_zip, package_archive)

            api_get, download = _make_mock_api_responses(
                evidence_archive, package_archive
            )
            run_data = _valid_run(conclusion="failure")

            def api_get_fail(url):
                if "/actions/runs/" in url and "/artifacts" not in url:
                    return run_data
                if "/actions/runs/" in url and "/artifacts" in url:
                    return {
                        "artifacts": [
                            {
                                "name": "validation-evidence",
                                "id": 1,
                                "expired": False,
                                "archive_download_url": "https://example.invalid/evidence.zip",
                            },
                            {
                                "name": "addon-package",
                                "id": 2,
                                "expired": False,
                                "archive_download_url": "https://example.invalid/package.zip",
                            },
                        ]
                    }
                raise RuntimeError(f"Unexpected URL: {url}")

            with self.assertRaises(RuntimeError):
                self._build_with_mock(root, _valid_dispatch(), api_get_fail, download)

    def test_missing_evidence_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            addon_zip = root / "addon.zip"
            _make_addon_zip(addon_zip, FIXTURE_ADDON_ID, FIXTURE_VERSION)
            evidence_archive = root / "evidence.zip"
            package_archive = root / "package.zip"
            evidence = _valid_evidence(artifact_sha256=_zip_sha256(addon_zip))
            _make_evidence_archive(evidence, evidence_archive)
            _make_package_archive(addon_zip, package_archive)

            def api_get(url):
                if "/actions/runs/" in url and "/artifacts" not in url:
                    return _valid_run()
                if "/actions/runs/" in url and "/artifacts" in url:
                    return {
                        "artifacts": [
                            {
                                "name": "addon-package",
                                "id": 2,
                                "expired": False,
                                "archive_download_url": "https://example.invalid/package.zip",
                            },
                        ]
                    }
                raise RuntimeError(f"Unexpected URL: {url}")

            def download(url, dest):
                if "evidence" in url:
                    shutil.copy2(evidence_archive, dest)
                elif "package" in url:
                    shutil.copy2(package_archive, dest)

            with self.assertRaises(RuntimeError):
                self._build_with_mock(root, _valid_dispatch(), api_get, download)

    def test_missing_package_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            addon_zip = root / "addon.zip"
            _make_addon_zip(addon_zip, FIXTURE_ADDON_ID, FIXTURE_VERSION)
            evidence_archive = root / "evidence.zip"
            package_archive = root / "package.zip"
            evidence = _valid_evidence(artifact_sha256=_zip_sha256(addon_zip))
            _make_evidence_archive(evidence, evidence_archive)
            _make_package_archive(addon_zip, package_archive)

            def api_get(url):
                if "/actions/runs/" in url and "/artifacts" not in url:
                    return _valid_run()
                if "/actions/runs/" in url and "/artifacts" in url:
                    return {
                        "artifacts": [
                            {
                                "name": "validation-evidence",
                                "id": 1,
                                "expired": False,
                                "archive_download_url": "https://example.invalid/evidence.zip",
                            },
                        ]
                    }
                raise RuntimeError(f"Unexpected URL: {url}")

            def download(url, dest):
                if "evidence" in url:
                    shutil.copy2(evidence_archive, dest)
                elif "package" in url:
                    shutil.copy2(package_archive, dest)

            with self.assertRaises(RuntimeError):
                self._build_with_mock(root, _valid_dispatch(), api_get, download)

    def test_expired_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            addon_zip = root / "addon.zip"
            _make_addon_zip(addon_zip, FIXTURE_ADDON_ID, FIXTURE_VERSION)
            evidence_archive = root / "evidence.zip"
            package_archive = root / "package.zip"
            evidence = _valid_evidence(artifact_sha256=_zip_sha256(addon_zip))
            _make_evidence_archive(evidence, evidence_archive)
            _make_package_archive(addon_zip, package_archive)

            def api_get(url):
                if "/actions/runs/" in url and "/artifacts" not in url:
                    return _valid_run()
                if "/actions/runs/" in url and "/artifacts" in url:
                    return {
                        "artifacts": [
                            {
                                "name": "validation-evidence",
                                "id": 1,
                                "expired": True,
                                "archive_download_url": "https://example.invalid/evidence.zip",
                            },
                            {
                                "name": "addon-package",
                                "id": 2,
                                "expired": False,
                                "archive_download_url": "https://example.invalid/package.zip",
                            },
                        ]
                    }
                raise RuntimeError(f"Unexpected URL: {url}")

            def download(url, dest):
                if "evidence" in url:
                    shutil.copy2(evidence_archive, dest)
                elif "package" in url:
                    shutil.copy2(package_archive, dest)

            with self.assertRaises(RuntimeError):
                self._build_with_mock(root, _valid_dispatch(), api_get, download)

    def test_sha_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            addon_zip = root / "addon.zip"
            _make_addon_zip(addon_zip, FIXTURE_ADDON_ID, FIXTURE_VERSION)
            evidence_archive = root / "evidence.zip"
            package_archive = root / "package.zip"
            evidence = _valid_evidence(artifact_sha256="0" * 64)
            _make_evidence_archive(evidence, evidence_archive)
            _make_package_archive(addon_zip, package_archive)
            api_get, download = _make_mock_api_responses(
                evidence_archive, package_archive
            )

            with self.assertRaises(RuntimeError):
                self._build_with_mock(root, _valid_dispatch(), api_get, download)

    def test_topology_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            addon_zip = root / "addon.zip"
            with zipfile.ZipFile(addon_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("plugin.wrong/addon.xml", "<addon/>")
            evidence_archive = root / "evidence.zip"
            package_archive = root / "package.zip"
            evidence = _valid_evidence(artifact_sha256=_zip_sha256(addon_zip))
            _make_evidence_archive(evidence, evidence_archive)
            _make_package_archive(addon_zip, package_archive)
            api_get, download = _make_mock_api_responses(
                evidence_archive, package_archive
            )

            with self.assertRaises(RuntimeError):
                self._build_with_mock(root, _valid_dispatch(), api_get, download)

    def test_malformed_evidence_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            addon_zip = root / "addon.zip"
            _make_addon_zip(addon_zip, FIXTURE_ADDON_ID, FIXTURE_VERSION)
            evidence_archive = root / "evidence.zip"
            package_archive = root / "package.zip"
            with zipfile.ZipFile(evidence_archive, "w") as zf:
                zf.writestr("wrong-name.json", "{}")
            _make_package_archive(addon_zip, package_archive)
            api_get, download = _make_mock_api_responses(
                evidence_archive, package_archive
            )

            with self.assertRaises(RuntimeError):
                self._build_with_mock(root, _valid_dispatch(), api_get, download)

    def test_malformed_package_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            addon_zip = root / "addon.zip"
            _make_addon_zip(addon_zip, FIXTURE_ADDON_ID, FIXTURE_VERSION)
            evidence_archive = root / "evidence.zip"
            package_archive = root / "package.zip"
            evidence = _valid_evidence(artifact_sha256=_zip_sha256(addon_zip))
            _make_evidence_archive(evidence, evidence_archive)
            with zipfile.ZipFile(package_archive, "w") as zf:
                zf.writestr("not-a-zip.bin", b"not a zip")
            api_get, download = _make_mock_api_responses(
                evidence_archive, package_archive
            )

            with self.assertRaises(RuntimeError):
                self._build_with_mock(root, _valid_dispatch(), api_get, download)

    def test_package_with_multiple_members_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            addon_zip = root / "addon.zip"
            _make_addon_zip(addon_zip, FIXTURE_ADDON_ID, FIXTURE_VERSION)
            evidence_archive = root / "evidence.zip"
            package_archive = root / "package.zip"
            evidence = _valid_evidence(artifact_sha256=_zip_sha256(addon_zip))
            _make_evidence_archive(evidence, evidence_archive)
            with zipfile.ZipFile(package_archive, "w") as zf:
                zf.write(addon_zip, "one.zip")
                zf.writestr("extra.txt", b"extra")
            api_get, download = _make_mock_api_responses(
                evidence_archive, package_archive
            )

            with self.assertRaises(RuntimeError):
                self._build_with_mock(root, _valid_dispatch(), api_get, download)

    def test_stale_candidate_sha_vs_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            addon_zip = root / "addon.zip"
            _make_addon_zip(addon_zip, FIXTURE_ADDON_ID, FIXTURE_VERSION)
            evidence_archive = root / "evidence.zip"
            package_archive = root / "package.zip"
            stale_sha = "a" * 40
            evidence = _valid_evidence(
                candidate_sha=stale_sha,
                validation_head_sha=FIXTURE_SHA,
            )
            _make_evidence_archive(evidence, evidence_archive)
            _make_package_archive(addon_zip, package_archive)

            def api_get(url):
                if "/git/ref/heads/develop" in url:
                    return {"object": {"sha": stale_sha}}
                if "/actions/runs/" in url and "/artifacts" not in url:
                    return {
                        "id": FIXTURE_RUN_ID,
                        "head_sha": FIXTURE_SHA,
                        "name": "Add-on Validations",
                        "head_branch": FIXTURE_BRANCH,
                        "conclusion": "success",
                    }
                if "/actions/runs/" in url and "/artifacts" in url:
                    return {
                        "artifacts": [
                            {
                                "name": "validation-evidence",
                                "id": 1,
                                "expired": False,
                                "archive_download_url": "https://example.invalid/evidence.zip",
                            },
                            {
                                "name": "addon-package",
                                "id": 2,
                                "expired": False,
                                "archive_download_url": "https://example.invalid/package.zip",
                            },
                        ]
                    }
                raise RuntimeError(f"Unexpected URL: {url}")

            def download(url, dest):
                if "evidence" in url:
                    shutil.copy2(evidence_archive, dest)
                elif "package" in url:
                    shutil.copy2(package_archive, dest)

            payload = _valid_dispatch(candidate_sha=stale_sha)
            with self.assertRaisesRegex(RuntimeError, "does not match run head_sha"):
                self._build_with_mock(root, payload, api_get, download)

    def test_existing_preserved_on_build_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            repo_dir = root / "repo"
            site_dir = root / "_site"
            repo_dir.mkdir()
            site_dir.mkdir()
            (repo_dir / "existing.txt").write_bytes(b"keep-me")
            (site_dir / "existing.txt").write_bytes(b"keep-me")

            payload = _valid_dispatch(source_repo="unknown/repo")
            with self.assertRaises(RuntimeError):
                builder.build_immutable_repository(payload, root)

            self.assertTrue((repo_dir / "existing.txt").is_file())
            self.assertEqual((repo_dir / "existing.txt").read_bytes(), b"keep-me")
            self.assertTrue((site_dir / "existing.txt").is_file())
            self.assertEqual((site_dir / "existing.txt").read_bytes(), b"keep-me")

    def test_evidence_addon_must_match_source_repository(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            addon_zip = root / "plugin.other-3.1.8.zip"
            _make_addon_zip(addon_zip, "plugin.other", FIXTURE_VERSION)
            evidence_archive = root / "evidence.zip"
            package_archive = root / "package.zip"
            evidence = _valid_evidence(
                addon_id="plugin.other",
                asset_name=addon_zip.name,
                publication_id=f"plugin.other@{FIXTURE_VERSION}",
                artifact_sha256=_zip_sha256(addon_zip),
            )
            _make_evidence_archive(evidence, evidence_archive)
            _make_package_archive(addon_zip, package_archive)
            api_get, download = _make_mock_api_responses(
                evidence_archive, package_archive
            )

            with self.assertRaises(RuntimeError):
                self._build_with_mock(root, _valid_dispatch(), api_get, download)

    def test_package_member_name_must_match_evidence_asset_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            addon_zip = root / "wrong-name.zip"
            _make_addon_zip(addon_zip, FIXTURE_ADDON_ID, FIXTURE_VERSION)
            evidence_archive = root / "evidence.zip"
            package_archive = root / "package.zip"
            evidence = _valid_evidence(artifact_sha256=_zip_sha256(addon_zip))
            _make_evidence_archive(evidence, evidence_archive)
            _make_package_archive(
                addon_zip, package_archive, member_name=addon_zip.name
            )
            api_get, download = _make_mock_api_responses(
                evidence_archive, package_archive
            )

            with self.assertRaises(RuntimeError):
                self._build_with_mock(root, _valid_dispatch(), api_get, download)

    def test_existing_outputs_are_restored_when_second_promotion_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            staging = root / "_staging"
            staging_repo = staging / "repo"
            staging_site = staging / "_site"
            repo = root / "repo"
            site = root / "_site"
            for directory, marker in (
                (staging_repo, b"new-repo"),
                (staging_site, b"new-site"),
                (repo, b"old-repo"),
                (site, b"old-site"),
            ):
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "marker").write_bytes(marker)

            real_replace = builder.os.replace
            calls = 0

            def fail_second_promotion(source, destination):
                nonlocal calls
                calls += 1
                if calls == 4:
                    raise OSError("simulated second promotion failure")
                real_replace(source, destination)

            with (
                mock.patch.object(
                    builder.os, "replace", side_effect=fail_second_promotion
                ),
                self.assertRaises(OSError),
            ):
                builder.promote_repository_outputs(staging, repo, site)

            self.assertEqual((repo / "marker").read_bytes(), b"old-repo")
            self.assertEqual((site / "marker").read_bytes(), b"old-site")

    def test_lower_candidate_version_is_rejected_before_promotion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            existing_repo = root / "repo"
            existing_site = root / "_site"
            existing_repo.mkdir()
            existing_site.mkdir()

            higher_version = "3.1.10"
            existing_addon_xml = (
                '<addons><addon id="plugin.video.twitch" name="Twitch" '
                f'version="{higher_version}" '
                'provider-name="test"/></addons>'
            )
            existing_manifest_bytes = existing_addon_xml.encode("utf-8")
            (existing_repo / "addons.xml").write_bytes(existing_manifest_bytes)
            checksum = hashlib.md5(existing_manifest_bytes).hexdigest()
            (existing_repo / "addons.xml.md5").write_text(checksum, encoding="utf-8")
            (existing_site / "addons.xml").write_bytes(existing_manifest_bytes)
            (existing_site / "addons.xml.md5").write_text(checksum, encoding="utf-8")
            (existing_repo / "sentinel.txt").write_bytes(b"keep-repo")
            (existing_site / "sentinel.txt").write_bytes(b"keep-site")
            repo_before = _snapshot_tree(existing_repo)
            site_before = _snapshot_tree(existing_site)

            addon_zip = root / "addon.zip"
            _make_addon_zip(addon_zip, FIXTURE_ADDON_ID, FIXTURE_VERSION)
            evidence_archive = root / "evidence.zip"
            package_archive = root / "package.zip"
            evidence = _valid_evidence(artifact_sha256=_zip_sha256(addon_zip))
            _make_evidence_archive(evidence, evidence_archive)
            _make_package_archive(addon_zip, package_archive)
            api_get, download = _make_mock_api_responses(
                evidence_archive, package_archive
            )

            with self.assertRaises(RuntimeError) as ctx:
                self._build_with_mock(root, _valid_dispatch(), api_get, download)

            error = str(ctx.exception)
            self.assertIn(FIXTURE_ADDON_ID, error)
            self.assertIn(FIXTURE_VERSION, error)
            self.assertIn(higher_version, error)
            self.assertEqual(_snapshot_tree(existing_repo), repo_before)
            self.assertEqual(_snapshot_tree(existing_site), site_before)

    def test_malformed_existing_manifest_is_rejected_without_output_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            site = root / "_site"
            repo.mkdir()
            site.mkdir()
            (repo / "addons.xml").write_bytes(b"<addons><unexpected/></addons>")
            (repo / "addons.xml.md5").write_bytes(b"existing-checksum")
            (site / "marker").write_bytes(b"existing-site")
            repo_before = _snapshot_tree(repo)
            site_before = _snapshot_tree(site)

            with self.assertRaises(RuntimeError):
                builder._check_version_monotonicity(
                    root, FIXTURE_ADDON_ID, FIXTURE_VERSION
                )

            self.assertEqual(_snapshot_tree(repo), repo_before)
            self.assertEqual(_snapshot_tree(site), site_before)

    def test_non_ascii_existing_version_is_rejected_without_output_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            site = root / "_site"
            repo.mkdir()
            site.mkdir()
            (repo / "addons.xml").write_text(
                '<addons><addon id="plugin.video.twitch" version="٣.١.١٠"/></addons>',
                encoding="utf-8",
            )
            (repo / "addons.xml.md5").write_bytes(b"existing-checksum")
            (site / "marker").write_bytes(b"existing-site")
            repo_before = _snapshot_tree(repo)
            site_before = _snapshot_tree(site)

            with self.assertRaisesRegex(RuntimeError, "Invalid addon version segment"):
                builder._check_version_monotonicity(
                    root, FIXTURE_ADDON_ID, FIXTURE_VERSION
                )

            self.assertEqual(_snapshot_tree(repo), repo_before)
            self.assertEqual(_snapshot_tree(site), site_before)

    def test_matching_addon_with_legitimate_nested_children_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            site = root / "_site"
            repo.mkdir()
            site.mkdir()
            existing_addon_xml = (
                "<addons>"
                '<addon id="plugin.video.twitch" name="Twitch" version="3.1.8" '
                'provider-name="test">'
                "<requires>"
                '<import addon="xbmc.python" version="3.0.0"/>'
                "</requires>"
                '<extension point="xbmc.addon.metadata">'
                "<summary>Twitch</summary>"
                "</extension>"
                "</addon>"
                "</addons>"
            )
            existing_manifest_bytes = existing_addon_xml.encode("utf-8")
            (repo / "addons.xml").write_bytes(existing_manifest_bytes)
            checksum = hashlib.md5(existing_manifest_bytes).hexdigest()
            (repo / "addons.xml.md5").write_text(checksum, encoding="utf-8")
            (site / "addons.xml").write_bytes(existing_manifest_bytes)
            (site / "addons.xml.md5").write_text(checksum, encoding="utf-8")
            (repo / "sentinel.txt").write_bytes(b"keep-repo")
            (site / "sentinel.txt").write_bytes(b"keep-site")
            repo_before = _snapshot_tree(repo)
            site_before = _snapshot_tree(site)

            builder._check_version_monotonicity(root, FIXTURE_ADDON_ID, FIXTURE_VERSION)

            self.assertEqual(_snapshot_tree(repo), repo_before)
            self.assertEqual(_snapshot_tree(site), site_before)

    def test_root_unexpected_element_after_matching_addon_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            site = root / "_site"
            repo.mkdir()
            site.mkdir()
            existing_addon_xml = (
                "<addons>"
                '<addon id="plugin.video.twitch" name="Twitch" version="3.1.10" '
                'provider-name="test"/>'
                "<unexpected-root/>"
                "</addons>"
            )
            existing_manifest_bytes = existing_addon_xml.encode("utf-8")
            (repo / "addons.xml").write_bytes(existing_manifest_bytes)
            checksum = hashlib.md5(existing_manifest_bytes).hexdigest()
            (repo / "addons.xml.md5").write_text(checksum, encoding="utf-8")
            (site / "addons.xml").write_bytes(existing_manifest_bytes)
            (site / "addons.xml.md5").write_text(checksum, encoding="utf-8")
            (repo / "sentinel.txt").write_bytes(b"keep-repo")
            (site / "sentinel.txt").write_bytes(b"keep-site")
            repo_before = _snapshot_tree(repo)
            site_before = _snapshot_tree(site)

            with self.assertRaises(RuntimeError):
                builder._check_version_monotonicity(
                    root, FIXTURE_ADDON_ID, FIXTURE_VERSION
                )

            self.assertEqual(_snapshot_tree(repo), repo_before)
            self.assertEqual(_snapshot_tree(site), site_before)

    def test_duplicate_addon_earlier_version_cannot_bypass_later_higher_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            site = root / "_site"
            repo.mkdir()
            site.mkdir()
            existing_addon_xml = (
                "<addons>"
                '<addon id="plugin.video.twitch" name="Twitch" version="3.1.7" '
                'provider-name="test"/>'
                '<addon id="plugin.other" name="Other" version="1.0.0" '
                'provider-name="test"/>'
                '<addon id="plugin.video.twitch" name="Twitch" version="3.1.10" '
                'provider-name="test"/>'
                "</addons>"
            )
            existing_manifest_bytes = existing_addon_xml.encode("utf-8")
            (repo / "addons.xml").write_bytes(existing_manifest_bytes)
            checksum = hashlib.md5(existing_manifest_bytes).hexdigest()
            (repo / "addons.xml.md5").write_text(checksum, encoding="utf-8")
            (site / "addons.xml").write_bytes(existing_manifest_bytes)
            (site / "addons.xml.md5").write_text(checksum, encoding="utf-8")
            (repo / "sentinel.txt").write_bytes(b"keep-repo")
            (site / "sentinel.txt").write_bytes(b"keep-site")
            repo_before = _snapshot_tree(repo)
            site_before = _snapshot_tree(site)

            with self.assertRaises(RuntimeError) as ctx:
                builder._check_version_monotonicity(
                    root, FIXTURE_ADDON_ID, FIXTURE_VERSION
                )

            error = str(ctx.exception)
            self.assertIn("plugin.video.twitch", error)
            self.assertIn("3.1.7", error)
            self.assertIn("3.1.10", error)
            self.assertEqual(_snapshot_tree(repo), repo_before)
            self.assertEqual(_snapshot_tree(site), site_before)

    def test_successful_build_updates_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            addon_zip = root / "addon.zip"
            _make_addon_zip(addon_zip, FIXTURE_ADDON_ID, FIXTURE_VERSION)
            evidence_archive = root / "evidence.zip"
            package_archive = root / "package.zip"
            evidence = _valid_evidence(artifact_sha256=_zip_sha256(addon_zip))
            _make_evidence_archive(evidence, evidence_archive)
            _make_package_archive(addon_zip, package_archive)
            api_get, download = _make_mock_api_responses(
                evidence_archive, package_archive
            )

            self._build_with_mock(root, _valid_dispatch(), api_get, download)

            repo = root / "repo"
            site = root / "_site"
            self.assertTrue((repo / FIXTURE_ADDON_ID / FIXTURE_ASSET).is_file())
            self.assertTrue((repo / "addons.xml").is_file())
            self.assertTrue((repo / "addons.xml.md5").is_file())
            self.assertTrue((site / "addons.xml").is_file())
            self.assertTrue((site / "index.html").is_file())

    def test_no_staging_left_after_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            addon_zip = root / "addon.zip"
            _make_addon_zip(addon_zip, FIXTURE_ADDON_ID, FIXTURE_VERSION)
            evidence_archive = root / "evidence.zip"
            package_archive = root / "package.zip"
            evidence = _valid_evidence(artifact_sha256=_zip_sha256(addon_zip))
            _make_evidence_archive(evidence, evidence_archive)
            _make_package_archive(addon_zip, package_archive)
            api_get, download = _make_mock_api_responses(
                evidence_archive, package_archive
            )

            self._build_with_mock(root, _valid_dispatch(), api_get, download)

            self.assertFalse((root / "_staging").exists())
            self.assertFalse((root / "_temp").exists())

    def test_no_staging_left_after_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            payload = _valid_dispatch(source_repo="unknown/repo")
            with self.assertRaises(RuntimeError):
                builder.build_immutable_repository(payload, root)

            self.assertFalse((root / "_staging").exists())
            self.assertFalse((root / "_temp").exists())

    def test_temp_paths_are_under_repo_root(self):
        paths_used = []

        def track_temp(path):
            paths_used.append(path)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            addon_zip = root / "addon.zip"
            _make_addon_zip(addon_zip, FIXTURE_ADDON_ID, FIXTURE_VERSION)
            evidence_archive = root / "evidence.zip"
            package_archive = root / "package.zip"
            evidence = _valid_evidence(artifact_sha256=_zip_sha256(addon_zip))
            _make_evidence_archive(evidence, evidence_archive)
            _make_package_archive(addon_zip, package_archive)
            api_get, download = _make_mock_api_responses(
                evidence_archive, package_archive
            )

            self._build_with_mock(root, _valid_dispatch(), api_get, download)

            for p in root.rglob("*"):
                if p.is_dir() and "_temp" in p.name:
                    self.assertTrue(
                        str(p).startswith(str(root)),
                        f"Temp path {p} is outside repo_root {root}",
                    )


class TestSourceTokenIsolation(unittest.TestCase):
    """Source-repository requests must use a separate SOURCE_GITHUB_TOKEN."""

    _target_addon_config = {
        "owner": "Serph91P",
        "repo": "plugin.video.twitch",
        "addon_id": "plugin.video.twitch",
        "branch": "main",
    }

    def _build_with_mock(self, root, dispatch_payload, api_get, download):
        with (
            mock.patch.object(builder, "source_github_api_get", side_effect=api_get),
            mock.patch.object(builder, "source_download_file", side_effect=download),
            mock.patch.object(builder, "ADDONS", [self._target_addon_config]),
        ):
            builder.build_immutable_repository(dispatch_payload, root)

    def test_missing_source_token_fails_before_first_source_request(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            with (
                mock.patch.dict(os.environ, {}, clear=True),
                self.assertRaises(RuntimeError) as ctx,
            ):
                builder.build_immutable_repository(_valid_dispatch(), root)
            self.assertIn("SOURCE_GITHUB_TOKEN", str(ctx.exception))

    def test_empty_source_token_fails_before_first_source_request(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            with (
                mock.patch.dict(
                    os.environ, {"SOURCE_GITHUB_TOKEN": "   "}, clear=False
                ),
                self.assertRaises(RuntimeError) as ctx,
            ):
                builder.build_immutable_repository(_valid_dispatch(), root)
            self.assertIn("SOURCE_GITHUB_TOKEN", str(ctx.exception))

    def test_every_source_boundary_uses_source_token_not_target_token(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            addon_zip = root / "addon.zip"
            _make_addon_zip(addon_zip, FIXTURE_ADDON_ID, FIXTURE_VERSION)
            evidence_archive = root / "evidence.zip"
            package_archive = root / "package.zip"
            evidence = _valid_evidence(artifact_sha256=_zip_sha256(addon_zip))
            _make_evidence_archive(evidence, evidence_archive)
            _make_package_archive(addon_zip, package_archive)

            run_url = (
                f"{builder.GH_API}/repos/{FIXTURE_SOURCE_REPO}/actions/runs/"
                f"{FIXTURE_RUN_ID}"
            )
            ref_url = (
                f"{builder.GH_API}/repos/{FIXTURE_SOURCE_REPO}/git/ref/heads/"
                f"{FIXTURE_BRANCH}"
            )
            artifacts_url = f"{run_url}/artifacts"
            evidence_url = "https://example.invalid/evidence.zip"
            package_url = "https://example.invalid/package.zip"
            responses = {
                run_url: json.dumps(_valid_run()).encode(),
                ref_url: json.dumps({"object": {"sha": FIXTURE_SHA}}).encode(),
                artifacts_url: json.dumps(
                    {
                        "artifacts": [
                            {
                                "name": "validation-evidence",
                                "id": 1,
                                "expired": False,
                                "archive_download_url": evidence_url,
                            },
                            {
                                "name": "addon-package",
                                "id": 2,
                                "expired": False,
                                "archive_download_url": package_url,
                            },
                        ]
                    }
                ).encode(),
                evidence_url: evidence_archive.read_bytes(),
                package_url: package_archive.read_bytes(),
            }
            captured_api_requests = []
            captured_download_requests = []

            def api_urlopen(request):
                captured_api_requests.append(
                    (request.full_url, request.get_header("Authorization"))
                )
                return io.BytesIO(responses[request.full_url])

            def download_urlopen(request):
                captured_download_requests.append(
                    (request.full_url, request.get_header("Authorization"))
                )
                return io.BytesIO(responses[request.full_url])

            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "SOURCE_GITHUB_TOKEN": "source-tok-abc",
                        "GITHUB_TOKEN": "target-tok-xyz",
                    },
                    clear=True,
                ),
                mock.patch("urllib.request.urlopen", side_effect=api_urlopen),
                mock.patch.object(
                    builder._source_opener, "open", side_effect=download_urlopen
                ),
                mock.patch.object(builder, "ADDONS", [self._target_addon_config]),
            ):
                builder.build_immutable_repository(_valid_dispatch(), root)

            self.assertEqual(
                captured_api_requests,
                [
                    (run_url, "token source-tok-abc"),
                    (ref_url, "token source-tok-abc"),
                    (artifacts_url, "token source-tok-abc"),
                    (ref_url, "token source-tok-abc"),
                ],
            )
            self.assertEqual(
                captured_download_requests,
                [
                    (evidence_url, "token source-tok-abc"),
                    (package_url, "token source-tok-abc"),
                ],
            )
            all_requests = captured_api_requests + captured_download_requests
            self.assertNotIn("target-tok-xyz", repr(all_requests))

    def test_target_token_is_not_used_for_source_requests(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            addon_zip = root / "addon.zip"
            _make_addon_zip(addon_zip, FIXTURE_ADDON_ID, FIXTURE_VERSION)
            evidence_archive = root / "evidence.zip"
            package_archive = root / "package.zip"
            evidence = _valid_evidence(artifact_sha256=_zip_sha256(addon_zip))
            _make_evidence_archive(evidence, evidence_archive)
            _make_package_archive(addon_zip, package_archive)

            def api_get_side_effect(url):
                if "/git/ref/heads/" in url:
                    return {"object": {"sha": FIXTURE_SHA}}
                if "/actions/runs/" in url and "/artifacts" not in url:
                    return _valid_run()
                if "/actions/runs/" in url and "/artifacts" in url:
                    return {
                        "artifacts": [
                            {
                                "name": "validation-evidence",
                                "id": 1,
                                "expired": False,
                                "archive_download_url": "https://example.invalid/evidence.zip",
                            },
                            {
                                "name": "addon-package",
                                "id": 2,
                                "expired": False,
                                "archive_download_url": "https://example.invalid/package.zip",
                            },
                        ]
                    }
                raise RuntimeError(f"Unexpected URL: {url}")

            def download_side_effect(url, dest):
                if "evidence" in url:
                    shutil.copy2(evidence_archive, dest)
                elif "package" in url:
                    shutil.copy2(package_archive, dest)

            target_api_mock = mock.MagicMock()
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "SOURCE_GITHUB_TOKEN": "source-tok-abc",
                        "GITHUB_TOKEN": "target-tok-xyz",
                    },
                    clear=False,
                ),
                mock.patch.object(
                    builder, "source_github_api_get", side_effect=api_get_side_effect
                ),
                mock.patch.object(
                    builder, "source_download_file", side_effect=download_side_effect
                ),
                mock.patch.object(
                    builder, "github_api_get", side_effect=target_api_mock
                ),
                mock.patch.object(builder, "ADDONS", [self._target_addon_config]),
            ):
                builder.build_immutable_repository(_valid_dispatch(), root)

            target_api_mock.assert_not_called()

    def test_source_token_is_not_used_for_unrelated_addon_downloads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            addon_zip = root / "addon.zip"
            _make_addon_zip(addon_zip, FIXTURE_ADDON_ID, FIXTURE_VERSION)
            evidence_archive = root / "evidence.zip"
            package_archive = root / "package.zip"
            evidence = _valid_evidence(artifact_sha256=_zip_sha256(addon_zip))
            _make_evidence_archive(evidence, evidence_archive)
            _make_package_archive(addon_zip, package_archive)

            other_addon_id = "plugin.other"
            other_version = "1.0.0"
            other_filename = f"{other_addon_id}-{other_version}.zip"
            other_archive = root / other_filename
            _make_addon_zip(other_archive, other_addon_id, other_version)
            other_url = f"https://example.invalid/{other_filename}"

            api_get, _download = _make_mock_api_responses(
                evidence_archive, package_archive
            )
            source_download_urls = []
            generic_download_urls = []
            release_lookup = mock.MagicMock(
                return_value=(other_url, other_version, other_filename)
            )

            def source_download(url, dest):
                source_download_urls.append(url)
                if "evidence" in url:
                    shutil.copy2(evidence_archive, dest)
                elif "package" in url:
                    shutil.copy2(package_archive, dest)
                else:
                    shutil.copy2(other_archive, dest)

            def generic_download(url, dest):
                generic_download_urls.append(url)
                shutil.copy2(other_archive, dest)

            addons = [
                self._target_addon_config,
                {
                    "owner": "Example",
                    "repo": other_addon_id,
                    "addon_id": other_addon_id,
                    "branch": "main",
                },
            ]
            with (
                mock.patch.dict(
                    os.environ, {"SOURCE_GITHUB_TOKEN": "source-tok-abc"}, clear=True
                ),
                mock.patch.object(
                    builder, "source_github_api_get", side_effect=api_get
                ),
                mock.patch.object(
                    builder, "source_download_file", side_effect=source_download
                ),
                mock.patch.object(
                    builder, "download_file", side_effect=generic_download
                ),
                mock.patch.object(
                    builder,
                    "get_latest_release_zip",
                    release_lookup,
                ),
                mock.patch.object(builder, "ADDONS", addons),
            ):
                builder.build_immutable_repository(_valid_dispatch(), root)

            self.assertEqual(
                source_download_urls,
                [
                    "https://example.invalid/evidence.zip",
                    "https://example.invalid/package.zip",
                ],
            )
            self.assertEqual(generic_download_urls, [other_url])
            release_lookup.assert_called_once_with(
                "Example", other_addon_id, other_addon_id
            )

    def test_source_token_401_fails_closed_with_sanitized_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            error_401 = urllib.error.HTTPError(
                "https://api.github.com/repos/test/repo/actions/runs/123",
                401,
                "Unauthorized",
                {},
                None,
            )

            with (
                mock.patch.dict(
                    os.environ,
                    {"SOURCE_GITHUB_TOKEN": "secret-source-tok"},
                    clear=False,
                ),
                mock.patch("urllib.request.urlopen", side_effect=error_401),
                mock.patch.object(builder, "ADDONS", [self._target_addon_config]),
                self.assertRaises(RuntimeError) as ctx,
            ):
                builder.build_immutable_repository(_valid_dispatch(), root)
            error_msg = str(ctx.exception)
            self.assertNotIn("secret-source-tok", error_msg)
            self.assertIn("401", error_msg)

    def test_source_token_403_fails_closed_with_sanitized_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            error_403 = urllib.error.HTTPError(
                "https://api.github.com/repos/test/repo/actions/runs/123",
                403,
                "Forbidden",
                {},
                None,
            )

            with (
                mock.patch.dict(
                    os.environ,
                    {"SOURCE_GITHUB_TOKEN": "secret-source-tok"},
                    clear=False,
                ),
                mock.patch("urllib.request.urlopen", side_effect=error_403),
                mock.patch.object(builder, "ADDONS", [self._target_addon_config]),
                self.assertRaises(RuntimeError) as ctx,
            ):
                builder.build_immutable_repository(_valid_dispatch(), root)
            error_msg = str(ctx.exception)
            self.assertNotIn("secret-source-tok", error_msg)
            self.assertIn("403", error_msg)

    def test_source_download_401_fails_closed_with_sanitized_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            error_401 = urllib.error.HTTPError(
                "https://example.invalid/evidence.zip",
                401,
                "Unauthorized",
                {},
                None,
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {"SOURCE_GITHUB_TOKEN": "secret-source-tok"},
                    clear=False,
                ),
                mock.patch.object(
                    builder._source_opener, "open", side_effect=error_401
                ),
                self.assertRaises(RuntimeError) as ctx,
            ):
                builder.source_download_file(
                    "https://example.invalid/evidence.zip",
                    Path(tmpdir) / "out.zip",
                )
            error_msg = str(ctx.exception)
            self.assertNotIn("secret-source-tok", error_msg)
            self.assertIn("401", error_msg)

    def test_source_download_403_fails_closed_with_sanitized_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            error_403 = urllib.error.HTTPError(
                "https://example.invalid/package.zip",
                403,
                "Forbidden",
                {},
                None,
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {"SOURCE_GITHUB_TOKEN": "secret-source-tok"},
                    clear=False,
                ),
                mock.patch.object(
                    builder._source_opener, "open", side_effect=error_403
                ),
                self.assertRaises(RuntimeError) as ctx,
            ):
                builder.source_download_file(
                    "https://example.invalid/package.zip",
                    Path(tmpdir) / "out.zip",
                )
            error_msg = str(ctx.exception)
            self.assertNotIn("secret-source-tok", error_msg)
            self.assertIn("403", error_msg)


class _HeaderCaptureHandler(BaseHTTPRequestHandler):
    """HTTP handler that records headers seen by the server."""

    def __init__(self, *args, captured_headers=None, serve_body=b"ok", **kwargs):
        self._captured = captured_headers
        self._serve_body = serve_body
        super().__init__(*args, **kwargs)

    def do_GET(self):
        if self._captured is not None:
            self._captured.append(dict(self.headers))
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(self._serve_body)))
        self.end_headers()
        self.wfile.write(self._serve_body)

    def log_message(self, format, *args):
        pass


def _start_server(handler_class=_HeaderCaptureHandler, serve_body=b"ok"):
    captured = []

    def handler(*a, **kw):
        return handler_class(*a, captured_headers=captured, serve_body=serve_body, **kw)

    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1], captured


def _shutdown_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


class TestSourceDownloadRedirectSecurity(unittest.TestCase):
    def test_cross_origin_redirect_strips_authorization(self):
        target_server, target_thread, target_port, target_headers = _start_server(
            serve_body=b"payload"
        )
        try:
            origin_headers = []

            class _RedirectHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    origin_headers.append(dict(self.headers))
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{target_port}/blob")
                    self.end_headers()

                def log_message(self, format, *args):
                    pass

            origin_server = HTTPServer(("127.0.0.1", 0), _RedirectHandler)
            origin_thread = threading.Thread(
                target=origin_server.serve_forever, daemon=True
            )
            origin_thread.start()
            origin_port = origin_server.server_address[1]
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    dest = Path(tmpdir) / "downloaded.bin"
                    with mock.patch.dict(
                        os.environ,
                        {"SOURCE_GITHUB_TOKEN": "src-secret-token-123"},
                    ):
                        builder.source_download_file(
                            f"http://127.0.0.1:{origin_port}/api/artifact", dest
                        )
                    self.assertEqual(dest.read_bytes(), b"payload")

                self.assertEqual(len(origin_headers), 1)
                self.assertIn("Authorization", origin_headers[0])
                self.assertIn(
                    "src-secret-token-123", origin_headers[0]["Authorization"]
                )

                self.assertEqual(len(target_headers), 1)
                self.assertNotIn("Authorization", target_headers[0])
                self.assertNotIn("src-secret-token-123", str(target_headers[0]))
            finally:
                _shutdown_server(origin_server, origin_thread)
        finally:
            _shutdown_server(target_server, target_thread)

    def test_same_origin_redirect_preserves_authorization(self):
        all_headers = []

        class _SameOriginRedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                all_headers.append(dict(self.headers))
                if self.path == "/redirect-me":
                    self.send_response(302)
                    self.send_header("Location", "/final")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", "7")
                    self.end_headers()
                    self.wfile.write(b"payload")

            def log_message(self, format, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), _SameOriginRedirectHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                dest = Path(tmpdir) / "downloaded.bin"
                with mock.patch.dict(
                    os.environ,
                    {"SOURCE_GITHUB_TOKEN": "src-secret-token-456"},
                ):
                    builder.source_download_file(
                        f"http://127.0.0.1:{port}/redirect-me", dest
                    )
                self.assertEqual(dest.read_bytes(), b"payload")

            self.assertEqual(len(all_headers), 2)
            self.assertIn("Authorization", all_headers[0])
            self.assertIn("src-secret-token-456", all_headers[0]["Authorization"])
            self.assertIn("Authorization", all_headers[1])
            self.assertIn("src-secret-token-456", all_headers[1]["Authorization"])
        finally:
            _shutdown_server(server, thread)


class TestSourceDownloadRedirectOriginNormalization(unittest.TestCase):
    def test_default_ports_are_treated_as_same_origin(self):
        handler = builder._SafeRedirectHandler()
        cases = [
            ("http://example.invalid/a", "http://example.invalid:80/b"),
            ("https://example.invalid/a", "https://example.invalid:443/b"),
            ("http://example.invalid:8080/a", "http://example.invalid:8080/b"),
        ]
        for orig_url, new_url in cases:
            with self.subTest(orig=orig_url, new=new_url):
                req = urllib.request.Request(orig_url)
                req.add_header("Authorization", "token test-token")
                result = handler.redirect_request(req, None, 302, "Moved", {}, new_url)
                self.assertIsNotNone(result)
                self.assertEqual(result.get_header("Authorization"), "token test-token")

    def test_cross_port_is_treated_as_cross_origin(self):
        handler = builder._SafeRedirectHandler()
        req = urllib.request.Request("http://example.invalid:8080/a")
        req.add_header("Authorization", "token test-token")
        result = handler.redirect_request(
            req, None, 302, "Moved", {}, "http://example.invalid:9090/b"
        )
        self.assertIsNotNone(result)
        self.assertIsNone(result.get_header("Authorization"))


class TestImmutablePublicationWorkflows(unittest.TestCase):
    def test_repository_workflow_accepts_only_validated_publications(self):
        workflow = (
            Path(__file__).parents[1] / ".github/workflows/update-repository.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("types: [validated-addon-publication]", workflow)
        self.assertNotIn("addon-updated", workflow)
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertNotIn("\n  push:", workflow)

    def test_notifier_forwards_the_validated_run_branch(self):
        workflow = (
            Path(__file__).parents[1] / "addon-workflow-templates/notify-repository.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("event-type: validated-addon-publication", workflow)
        self.assertIn("workflow_run.head_branch == 'develop'", workflow)
        self.assertIn(
            '"expected_branch": "${{ steps.evidence.outputs.head_branch }}"',
            workflow,
        )
        self.assertNotIn("workflow_run.head_branch == 'main'", workflow)

    def test_workflow_maps_source_artifact_token_separately(self):
        workflow = (
            Path(__file__).parents[1] / ".github/workflows/update-repository.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("SOURCE_GITHUB_TOKEN", workflow)
        self.assertIn("SOURCE_ARTIFACT_TOKEN", workflow)
        self.assertIn("${{ secrets.SOURCE_ARTIFACT_TOKEN }}", workflow)

    def test_source_token_not_in_dispatch_payload(self):
        notify = (
            Path(__file__).parents[1] / "addon-workflow-templates/notify-repository.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("SOURCE_GITHUB_TOKEN", notify)
        self.assertNotIn("SOURCE_ARTIFACT_TOKEN", notify)
        self.assertNotIn("source_token", notify)


if __name__ == "__main__":
    unittest.main()
