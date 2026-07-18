import datetime
import hashlib
import io
import json
import os
import re
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

import yaml

from scripts import build_repository as builder


FIXTURE_SHA = "25b5920a9204acedf3d05dc009d78918d2bf0648"
FIXTURE_RUN_ID = 29549561132
FIXTURE_ADDON_ID = "plugin.video.twitch"
FIXTURE_VERSION = "3.1.8"
FIXTURE_ASSET = "plugin.video.twitch-3.1.8.zip"
FIXTURE_PUBLICATION_ID = "plugin.video.twitch@3.1.8"
FIXTURE_SOURCE_REPO = "Serph91P/plugin.video.twitch"
FIXTURE_BRANCH = "develop"
FIXTURE_WORKFLOW_PATH = ".github/workflows/addon-validations.yml@develop"
FIXTURE_API_WORKFLOW_PATH = ".github/workflows/addon-validations.yml"
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
        "validation_workflow_path": FIXTURE_WORKFLOW_PATH,
        "expected_branch": "develop",
        "publication_id": FIXTURE_PUBLICATION_ID,
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
        "path": FIXTURE_API_WORKFLOW_PATH,
        "head_branch": "develop",
        "status": "completed",
        "event": "push",
        "repository": {"full_name": FIXTURE_SOURCE_REPO},
        "workflow_id": 211623879,
    }
    run.update(overrides)
    return run


def _make_addon_zip(path, addon_id, version, extra_members=None):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        metadata = (
            f'<addon id="{addon_id}" name="Test" version="{version}" '
            f'provider-name="Test"><extension point="xbmc.addon.metadata">'
            f"<assets><icon>resources/icon.png</icon></assets></extension></addon>"
        )
        archive.writestr(f"{addon_id}/addon.xml", metadata)
        archive.writestr(f"{addon_id}/changelog.txt", b"changes")
        archive.writestr(f"{addon_id}/resources/icon.png", b"icon-data")
        if extra_members:
            for name, content in extra_members.items():
                archive.writestr(f"{addon_id}/{name}", content)
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
                "total_count": 2,
                "artifacts": [
                    {
                        "name": "validation-evidence",
                        "id": 1,
                        "expired": False,
                        "created_at": "2026-07-01T00:00:00Z",
                        "expires_at": "2026-07-31T00:00:00Z",
                        "archive_download_url": "https://example.invalid/evidence.zip",
                        "workflow_run": {"id": FIXTURE_RUN_ID},
                    },
                    {
                        "name": "addon-package",
                        "id": 2,
                        "expired": False,
                        "created_at": "2026-07-01T00:00:00Z",
                        "expires_at": "2026-07-31T00:00:00Z",
                        "archive_download_url": "https://example.invalid/package.zip",
                        "workflow_run": {"id": FIXTURE_RUN_ID},
                    },
                ],
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
    current_repo = root / "repo"
    current_repo.mkdir()
    (current_repo / "addons.xml").write_text("<addons/>", encoding="utf-8")
    return root


def _snapshot_tree(directory):
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


class TestValidateDispatchPayload(unittest.TestCase):
    def _enabled_addon(self):
        config = next(
            c.copy()
            for c in builder.ADDONS
            if f"{c['owner']}/{c['repo']}" == FIXTURE_SOURCE_REPO
        )
        config["publication_enabled"] = True
        return config

    def test_valid_payload_passes(self):
        with mock.patch.object(builder, "ADDONS", [self._enabled_addon()]):
            builder.validate_dispatch_payload(_valid_dispatch())

    def test_non_dict_is_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.validate_dispatch_payload("not-a-dict")

    def test_unknown_fields_are_rejected(self):
        with mock.patch.object(builder, "ADDONS", [self._enabled_addon()]):
            with self.assertRaises(RuntimeError):
                builder.validate_dispatch_payload(_valid_dispatch(addons=[], extra="x"))

    def test_sender_selected_artifact_names_are_rejected(self):
        with mock.patch.object(builder, "ADDONS", [self._enabled_addon()]):
            with self.assertRaises(RuntimeError) as ctx:
                builder.validate_dispatch_payload(
                    _valid_dispatch(
                        package_artifact_name="addon-package",
                        evidence_artifact_name="validation-evidence",
                    )
                )
            self.assertIn("unknown fields", str(ctx.exception))

    def test_missing_source_repo_is_rejected(self):
        payload = _valid_dispatch()
        del payload["source_repo"]
        with self.assertRaises(RuntimeError):
            builder.validate_dispatch_payload(payload)

    def test_source_repo_without_slash_is_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.validate_dispatch_payload(_valid_dispatch(source_repo="noslash"))

    def test_unconfigured_source_repo_is_rejected(self):
        with self.assertRaises(RuntimeError) as ctx:
            builder.validate_dispatch_payload(
                _valid_dispatch(source_repo="unknown/repo")
            )
        self.assertIn("not in the configured ADDONS list", str(ctx.exception))

    def test_wrong_workflow_path_is_rejected(self):
        with mock.patch.object(builder, "ADDONS", [self._enabled_addon()]):
            with self.assertRaises(RuntimeError) as ctx:
                builder.validate_dispatch_payload(
                    _valid_dispatch(
                        validation_workflow_path=(
                            ".github/workflows/untrusted.yml@develop"
                        )
                    )
                )
            self.assertIn("does not match approved path", str(ctx.exception))

    def test_wrong_expected_branch_is_rejected(self):
        with mock.patch.object(builder, "ADDONS", [self._enabled_addon()]):
            with self.assertRaises(RuntimeError) as ctx:
                builder.validate_dispatch_payload(
                    _valid_dispatch(expected_branch="main")
                )
            self.assertIn("does not match approved branch", str(ctx.exception))

    def test_missing_candidate_sha_is_rejected(self):
        payload = _valid_dispatch()
        del payload["candidate_sha"]
        with mock.patch.object(builder, "ADDONS", [self._enabled_addon()]):
            with self.assertRaises(RuntimeError):
                builder.validate_dispatch_payload(payload)

    def test_short_candidate_sha_is_rejected(self):
        with mock.patch.object(builder, "ADDONS", [self._enabled_addon()]):
            with self.assertRaises(RuntimeError):
                builder.validate_dispatch_payload(_valid_dispatch(candidate_sha="abc"))

    def test_non_hex_candidate_sha_is_rejected(self):
        with mock.patch.object(builder, "ADDONS", [self._enabled_addon()]):
            with self.assertRaises(RuntimeError):
                builder.validate_dispatch_payload(
                    _valid_dispatch(candidate_sha="g" * 40)
                )

    def test_missing_validation_run_id_is_rejected(self):
        payload = _valid_dispatch()
        del payload["validation_run_id"]
        with mock.patch.object(builder, "ADDONS", [self._enabled_addon()]):
            with self.assertRaises(RuntimeError):
                builder.validate_dispatch_payload(payload)

    def test_string_validation_run_id_is_rejected(self):
        with mock.patch.object(builder, "ADDONS", [self._enabled_addon()]):
            with self.assertRaises(RuntimeError):
                builder.validate_dispatch_payload(
                    _valid_dispatch(validation_run_id="not-int")
                )

    def test_negative_validation_run_id_is_rejected(self):
        with mock.patch.object(builder, "ADDONS", [self._enabled_addon()]):
            with self.assertRaises(RuntimeError):
                builder.validate_dispatch_payload(_valid_dispatch(validation_run_id=-1))

    def test_missing_validation_head_sha_is_rejected(self):
        payload = _valid_dispatch()
        del payload["validation_head_sha"]
        with mock.patch.object(builder, "ADDONS", [self._enabled_addon()]):
            with self.assertRaises(RuntimeError):
                builder.validate_dispatch_payload(payload)

    def test_missing_validation_workflow_is_rejected(self):
        payload = _valid_dispatch()
        del payload["validation_workflow"]
        with mock.patch.object(builder, "ADDONS", [self._enabled_addon()]):
            with self.assertRaises(RuntimeError):
                builder.validate_dispatch_payload(payload)

    def test_missing_validation_workflow_path_is_rejected(self):
        payload = _valid_dispatch()
        del payload["validation_workflow_path"]
        with mock.patch.object(builder, "ADDONS", [self._enabled_addon()]):
            with self.assertRaises(RuntimeError):
                builder.validate_dispatch_payload(payload)

    def test_wrong_validation_workflow_path_is_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.validate_dispatch_payload(
                _valid_dispatch(
                    validation_workflow_path=(
                        ".github/workflows/addon-validations.yml@main"
                    )
                )
            )

    def test_missing_publication_id_is_rejected(self):
        payload = _valid_dispatch()
        del payload["publication_id"]
        with self.assertRaises(RuntimeError):
            builder.validate_dispatch_payload(payload)

    def test_malformed_publication_id_is_rejected(self):
        for publication_id in (
            "",
            "plugin.video.twitch",
            "plugin.video.twitch@",
            "@3.1.8",
            "plugin.video.twitch@3.1 beta",
            "plugin/video@3.1.8",
        ):
            with self.subTest(publication_id=publication_id), self.assertRaises(
                RuntimeError
            ):
                builder.validate_dispatch_payload(
                    _valid_dispatch(publication_id=publication_id)
                )

    def test_missing_expected_branch_is_rejected(self):
        payload = _valid_dispatch()
        del payload["expected_branch"]
        with mock.patch.object(builder, "ADDONS", [self._enabled_addon()]):
            with self.assertRaises(RuntimeError):
                builder.validate_dispatch_payload(payload)

    def test_disabled_source_is_rejected(self):
        with self.assertRaises(RuntimeError) as ctx:
            builder.validate_dispatch_payload(_valid_dispatch())
        self.assertIn("disabled", str(ctx.exception))


class TestValidateImmutableEvidence(unittest.TestCase):
    def test_valid_evidence_passes(self):
        builder.validate_immutable_evidence(
            _valid_evidence(),
            FIXTURE_SHA,
            FIXTURE_RUN_ID,
            FIXTURE_SHA,
            FIXTURE_PUBLICATION_ID,
        )

    def test_valid_evidence_with_string_run_id_passes(self):
        evidence = _valid_evidence(validation_run_id="29549561132")
        builder.validate_immutable_evidence(
            evidence,
            FIXTURE_SHA,
            FIXTURE_RUN_ID,
            FIXTURE_SHA,
            FIXTURE_PUBLICATION_ID,
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
                        FIXTURE_PUBLICATION_ID,
                    )

    def test_wrong_candidate_sha_is_rejected(self):
        evidence = _valid_evidence(candidate_sha="a" * 40)
        with self.assertRaises(RuntimeError):
            builder.validate_immutable_evidence(
                evidence,
                FIXTURE_SHA,
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
                FIXTURE_PUBLICATION_ID,
            )

    def test_wrong_validation_head_sha_is_rejected(self):
        evidence = _valid_evidence(validation_head_sha="b" * 40)
        with self.assertRaises(RuntimeError):
            builder.validate_immutable_evidence(
                evidence,
                FIXTURE_SHA,
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
                FIXTURE_PUBLICATION_ID,
            )

    def test_wrong_run_id_is_rejected(self):
        evidence = _valid_evidence(validation_run_id="99999999999")
        with self.assertRaises(RuntimeError):
            builder.validate_immutable_evidence(
                evidence,
                FIXTURE_SHA,
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
                FIXTURE_PUBLICATION_ID,
            )

    def test_candidate_sha_must_be_40_hex(self):
        evidence = _valid_evidence(candidate_sha="not-a-sha")
        with self.assertRaises(RuntimeError):
            builder.validate_immutable_evidence(
                evidence,
                "not-a-sha",
                FIXTURE_RUN_ID,
                "not-a-sha",
                FIXTURE_PUBLICATION_ID,
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
                        FIXTURE_PUBLICATION_ID,
                    )

    def test_publication_id_must_match_addon_id_and_version(self):
        evidence = _valid_evidence(publication_id="wrong@wrong")
        with self.assertRaises(RuntimeError):
            builder.validate_immutable_evidence(
                evidence,
                FIXTURE_SHA,
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
                FIXTURE_PUBLICATION_ID,
            )

    def test_publication_id_must_match_dispatch(self):
        with self.assertRaises(RuntimeError):
            builder.validate_immutable_evidence(
                _valid_evidence(),
                FIXTURE_SHA,
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
                f"{FIXTURE_ADDON_ID}@9.9.9",
            )

    def test_non_dict_evidence_is_rejected(self):
        with self.assertRaises(RuntimeError):
            builder.validate_immutable_evidence(
                "not-a-dict",
                FIXTURE_SHA,
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
                FIXTURE_PUBLICATION_ID,
            )

    def test_non_numeric_run_id_in_evidence_is_rejected(self):
        evidence = _valid_evidence(validation_run_id="not-a-number")
        with self.assertRaises(RuntimeError):
            builder.validate_immutable_evidence(
                evidence,
                FIXTURE_SHA,
                FIXTURE_RUN_ID,
                FIXTURE_SHA,
                FIXTURE_PUBLICATION_ID,
            )


class TestValidateGithubRun(unittest.TestCase):
    def _source_config(self, **overrides):
        config = {
            "owner": "Serph91P",
            "repo": "plugin.video.twitch",
            "addon_id": "plugin.video.twitch",
            "branch": "main",
            "publication_branch": "develop",
            "validation_workflow": "Add-on Validations",
            "validation_workflow_path": ".github/workflows/addon-validations.yml@develop",
            "validation_workflow_id": 211623879,
            "package_artifact_name": "addon-package",
            "evidence_artifact_name": "validation-evidence",
        }
        config.update(overrides)
        return config

    def validate(self, run, config=None):
        if config is None:
            config = self._source_config()
        return builder.validate_github_run(
            run,
            FIXTURE_RUN_ID,
            FIXTURE_SHA,
            config,
        )

    def test_matching_unsuffixed_workflow_path_and_branch_passes(self):
        self.validate(_valid_run())

    def test_wrong_run_id_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.validate(_valid_run(id=99999999999))

    def test_wrong_head_sha_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.validate(_valid_run(head_sha="deadbeef" + "0" * 32))

    def test_wrong_workflow_name_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.validate(_valid_run(name="Wrong Workflow"))

    def test_wrong_workflow_path_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.validate(_valid_run(path=".github/workflows/untrusted.yml"))

    def test_suffixed_api_workflow_path_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.validate(_valid_run(path=FIXTURE_WORKFLOW_PATH))

    def test_missing_or_malformed_api_workflow_path_is_rejected(self):
        missing = _valid_run()
        del missing["path"]
        for run in (
            missing,
            _valid_run(path=""),
            _valid_run(path=".github/workflows/nested/validations.yml"),
        ):
            with self.subTest(run=run), self.assertRaises(RuntimeError):
                self.validate(run)

    def test_missing_branch_is_rejected(self):
        run = _valid_run()
        del run["head_branch"]
        with self.assertRaises(RuntimeError):
            self.validate(run)

    def test_wrong_branch_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.validate(_valid_run(head_branch="main"))

    def test_failed_conclusion_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.validate(_valid_run(conclusion="failure"))

    def test_missing_conclusion_is_rejected(self):
        run = _valid_run()
        del run["conclusion"]
        with self.assertRaises(RuntimeError):
            self.validate(run)

    def test_in_progress_conclusion_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.validate(_valid_run(conclusion=None))

    def test_non_dict_run_data_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.validate("not-a-dict")

    def test_wrong_workflow_id_is_rejected(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.validate(
                _valid_run(workflow_id=987654),
            )
        self.assertIn("workflow_id", str(ctx.exception))

    def test_missing_status_is_rejected(self):
        run = _valid_run()
        del run["status"]
        with self.assertRaises(RuntimeError):
            self.validate(run)

    def test_wrong_event_is_rejected(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.validate(_valid_run(event="workflow_dispatch"))
        self.assertIn("event", str(ctx.exception))

    def test_wrong_repository_is_rejected(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.validate(_valid_run(repository={"full_name": "attacker/repo"}))
        self.assertIn("repository", str(ctx.exception))


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


class TestKodiVersionComparator(unittest.TestCase):
    def parse(self, value):
        return builder._parse_kodi_version(value)

    def test_accepted_suffix_grammar_and_trailing_zero_equality(self):
        self.parse("1.6.1+omega.1")
        self.assertEqual(self.parse("1"), self.parse("1.0.0"))
        self.assertEqual(self.parse("1.6.1+OMEGA.1"), self.parse("1.6.1+omega.1"))

    def test_core_and_suffix_ordering(self):
        self.assertLess(self.parse("1.9"), self.parse("1.10"))
        self.assertLess(self.parse("1.0"), self.parse("1.0+omega"))
        self.assertLess(self.parse("1.0+omega.2"), self.parse("1.0+omega.10"))
        self.assertLess(self.parse("1.0+1"), self.parse("1.0+alpha"))
        self.assertLess(self.parse("1.0+alpha.2"), self.parse("1.0+alpha.beta"))

    def test_malformed_and_non_ascii_versions_are_rejected(self):
        malformed = (
            "",
            "1.",
            ".1",
            "1+",
            "1++omega",
            "1+omega..1",
            "1-omega",
            "١.0",
            "1+oméga",
            None,
            1,
        )
        for value in malformed:
            with self.subTest(value=value):
                with self.assertRaises(RuntimeError):
                    self.parse(value)


class TestFetchValidatedRunArtifacts(unittest.TestCase):
    source_config = {
        "package_artifact_name": "addon-package",
        "evidence_artifact_name": "validation-evidence",
    }

    def artifact(self, name, artifact_id, **overrides):
        value = {
            "name": name,
            "id": artifact_id,
            "expired": False,
            "created_at": "2026-07-01T00:00:00Z",
            "expires_at": "2026-07-31T00:00:00Z",
            "archive_download_url": f"https://example.invalid/{artifact_id}.zip",
            "workflow_run": {"id": FIXTURE_RUN_ID},
        }
        value.update(overrides)
        return value

    def fetch(self, pages):
        calls = []

        def api_get(url):
            calls.append(url)
            return pages[len(calls) - 1]

        return api_get, calls

    def test_required_artifacts_on_separate_pages_are_accepted(self):
        api_get, calls = self.fetch(
            [
                {
                    "total_count": 2,
                    "artifacts": [self.artifact("addon-package", 1)],
                },
                {
                    "total_count": 2,
                    "artifacts": [self.artifact("validation-evidence", 2)],
                },
            ]
        )
        with mock.patch.object(builder, "source_github_api_get", side_effect=api_get):
            selected = builder.fetch_validated_run_artifacts(
                FIXTURE_SOURCE_REPO,
                FIXTURE_RUN_ID,
                self.source_config,
                now=datetime.datetime(2026, 7, 17, tzinfo=datetime.timezone.utc),
            )
        self.assertEqual(set(selected), {"addon-package", "validation-evidence"})
        self.assertEqual(len(calls), 2)

    def test_duplicate_required_artifact_on_later_page_is_rejected(self):
        api_get, calls = self.fetch(
            [
                {
                    "total_count": 3,
                    "artifacts": [self.artifact("addon-package", 1)],
                },
                {
                    "total_count": 3,
                    "artifacts": [
                        self.artifact("validation-evidence", 2),
                        self.artifact("addon-package", 3),
                    ],
                },
            ]
        )
        with (
            mock.patch.object(builder, "source_github_api_get", side_effect=api_get),
            self.assertRaisesRegex(RuntimeError, "Duplicate required artifact name"),
        ):
            builder.fetch_validated_run_artifacts(
                FIXTURE_SOURCE_REPO,
                FIXTURE_RUN_ID,
                self.source_config,
                now=datetime.datetime(2026, 7, 17, tzinfo=datetime.timezone.utc),
            )
        self.assertEqual(len(calls), 2)

    def test_artifact_retention_must_be_exact(self):
        api_get, _calls = self.fetch(
            [
                {
                    "total_count": 2,
                    "artifacts": [
                        self.artifact(
                            "addon-package",
                            1,
                            expires_at="2026-07-31T00:00:01Z",
                        ),
                        self.artifact("validation-evidence", 2),
                    ],
                }
            ]
        )
        with (
            mock.patch.object(builder, "source_github_api_get", side_effect=api_get),
            self.assertRaisesRegex(RuntimeError, "retention"),
        ):
            builder.fetch_validated_run_artifacts(
                FIXTURE_SOURCE_REPO,
                FIXTURE_RUN_ID,
                self.source_config,
                now=datetime.datetime(2026, 7, 17, tzinfo=datetime.timezone.utc),
            )


class TestValidateArchiveTopology(unittest.TestCase):
    def test_valid_topology_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.zip"
            _make_addon_zip(path, "plugin.example", "1.0.0")
            builder.validate_archive_topology(path, "plugin.example", "1.0.0")

    def test_target_runtime_allowlist_accepts_declared_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.zip"
            _make_addon_zip(path, "plugin.example", "1.0.0")
            builder.validate_archive_topology(
                path,
                "plugin.example",
                "1.0.0",
                ("addon.xml", "changelog.txt", "resources/"),
            )

    def test_target_runtime_allowlist_rejects_undeclared_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.zip"
            _make_addon_zip(
                path,
                "plugin.example",
                "1.0.0",
                extra_members={"undeclared.py": b"untrusted"},
            )
            with self.assertRaisesRegex(RuntimeError, "Undeclared runtime member"):
                builder.validate_archive_topology(
                    path,
                    "plugin.example",
                    "1.0.0",
                    ("addon.xml", "changelog.txt", "resources/"),
                )

    def test_target_runtime_allowlist_rejects_nested_repository_only_members(self):
        denied = (
            "resources/generated.pyc",
            "resources/__pycache__/generated.py",
            "resources/.github/workflows/publish.yml",
            "resources/WorkFlows/publish.yml",
            "resources/.HeRmEs/config.yaml",
            "resources/Requirements-Dev.TXT",
            "resources/.GITIGNORE",
            "resources/PyProject.TOML",
            "resources/tests/test_runtime.py",
            "resources/READme.txt",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            for index, relative in enumerate(denied):
                path = Path(tmpdir) / f"denied-{index}.zip"
                _make_addon_zip(
                    path,
                    "plugin.example",
                    "1.0.0",
                    extra_members={relative: b"repository-only"},
                )
                with self.subTest(relative=relative):
                    with self.assertRaisesRegex(RuntimeError, "repository-only"):
                        builder.validate_archive_topology(
                            path,
                            "plugin.example",
                            "1.0.0",
                            ("addon.xml", "changelog.txt", "resources/"),
                        )

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
        "publication_enabled": True,
        "publication_branch": "develop",
        "validation_workflow": "Add-on Validations",
        "validation_workflow_path": ".github/workflows/addon-validations.yml@develop",
        "validation_workflow_id": 211623879,
        "package_artifact_name": "addon-package",
        "evidence_artifact_name": "validation-evidence",
        "runtime_entries": ("addon.xml", "changelog.txt", "resources/"),
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

    def _add_existing_outputs(self, root):
        repo = root / "repo"
        site = root / "_site"
        repo.mkdir(exist_ok=True)
        site.mkdir()
        (repo / "sentinel.txt").write_bytes(b"existing-repo")
        (site / "sentinel.txt").write_bytes(b"existing-site")
        return repo, site, _snapshot_tree(repo), _snapshot_tree(site)

    def test_unknown_source_repo_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            payload = _valid_dispatch(source_repo="unknown/repo")
            with self.assertRaises(RuntimeError):
                builder.build_immutable_repository(payload, root)

    def test_missing_or_wrong_workflow_path_preserves_outputs_without_download(self):
        cases = []
        missing = _valid_dispatch()
        del missing["validation_workflow_path"]
        cases.append(missing)
        cases.append(
            _valid_dispatch(
                validation_workflow_path=".github/workflows/untrusted.yml@develop"
            )
        )
        for payload in cases:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmpdir:
                root = _make_repo_root(tmpdir)
                repo, site, repo_before, site_before = self._add_existing_outputs(root)
                api_get = mock.Mock(return_value=_valid_run())
                download = mock.Mock()

                with self.assertRaises(RuntimeError):
                    self._build_with_mock(root, payload, api_get, download)

                download.assert_not_called()
                self.assertEqual(_snapshot_tree(repo), repo_before)
                self.assertEqual(_snapshot_tree(site), site_before)

    def test_missing_or_wrong_addon_publication_id_prevents_all_downloads(self):
        missing = _valid_dispatch()
        del missing["publication_id"]
        cases = [
            missing,
            _valid_dispatch(publication_id=f"{FIXTURE_ADDON_ID}@3.1 beta"),
            _valid_dispatch(publication_id=f"plugin.other@{FIXTURE_VERSION}"),
        ]
        for payload in cases:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmpdir:
                root = _make_repo_root(tmpdir)
                repo, site, repo_before, site_before = self._add_existing_outputs(root)
                api_get = mock.Mock()
                download = mock.Mock()

                with self.assertRaises(RuntimeError):
                    self._build_with_mock(root, payload, api_get, download)

                api_get.assert_not_called()
                download.assert_not_called()
                self.assertEqual(_snapshot_tree(repo), repo_before)
                self.assertEqual(_snapshot_tree(site), site_before)

    def test_evidence_publication_mismatch_prevents_package_download_and_mutation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            repo, site, repo_before, site_before = self._add_existing_outputs(root)
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
            tracked_download = mock.Mock(side_effect=download)
            payload = _valid_dispatch(
                publication_id=f"{FIXTURE_ADDON_ID}@9.9.9"
            )

            with self.assertRaises(RuntimeError):
                self._build_with_mock(root, payload, api_get, tracked_download)

            self.assertEqual(
                [call.args[0] for call in tracked_download.call_args_list],
                ["https://example.invalid/evidence.zip"],
            )
            self.assertEqual(_snapshot_tree(repo), repo_before)
            self.assertEqual(_snapshot_tree(site), site_before)

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
            existing_repo.mkdir(exist_ok=True)
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
                        "total_count": 2,
                        "artifacts": [
                            {
                                "name": "validation-evidence",
                                "id": 1,
                                "expired": False,
                                "created_at": "2026-07-01T00:00:00Z",
                                "expires_at": "2026-07-31T00:00:00Z",
                                "archive_download_url": "https://example.invalid/evidence.zip",
                                "workflow_run": {"id": FIXTURE_RUN_ID},
                            },
                            {
                                "name": "addon-package",
                                "id": 2,
                                "expired": False,
                                "created_at": "2026-07-01T00:00:00Z",
                                "expires_at": "2026-07-31T00:00:00Z",
                                "archive_download_url": "https://example.invalid/package.zip",
                                "workflow_run": {"id": FIXTURE_RUN_ID},
                            },
                        ],
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
                        "total_count": 1,
                        "artifacts": [
                            {
                                "name": "addon-package",
                                "id": 2,
                                "expired": False,
                                "created_at": "2026-07-01T00:00:00Z",
                                "expires_at": "2026-07-31T00:00:00Z",
                                "archive_download_url": "https://example.invalid/package.zip",
                                "workflow_run": {"id": FIXTURE_RUN_ID},
                            },
                        ],
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
                        "total_count": 1,
                        "artifacts": [
                            {
                                "name": "validation-evidence",
                                "id": 1,
                                "expired": False,
                                "created_at": "2026-07-01T00:00:00Z",
                                "expires_at": "2026-07-31T00:00:00Z",
                                "archive_download_url": "https://example.invalid/evidence.zip",
                                "workflow_run": {"id": FIXTURE_RUN_ID},
                            },
                        ],
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
                        "total_count": 2,
                        "artifacts": [
                            {
                                "name": "validation-evidence",
                                "id": 1,
                                "expired": True,
                                "created_at": "2026-07-01T00:00:00Z",
                                "expires_at": "2026-07-31T00:00:00Z",
                                "archive_download_url": "https://example.invalid/evidence.zip",
                                "workflow_run": {"id": FIXTURE_RUN_ID},
                            },
                            {
                                "name": "addon-package",
                                "id": 2,
                                "expired": False,
                                "created_at": "2026-07-01T00:00:00Z",
                                "expires_at": "2026-07-31T00:00:00Z",
                                "archive_download_url": "https://example.invalid/package.zip",
                                "workflow_run": {"id": FIXTURE_RUN_ID},
                            },
                        ],
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
                        "path": FIXTURE_API_WORKFLOW_PATH,
                        "head_branch": FIXTURE_BRANCH,
                        "conclusion": "success",
                        "status": "completed",
                        "event": "push",
                        "repository": {"full_name": FIXTURE_SOURCE_REPO},
                        "workflow_id": 211623879,
                    }
                if "/actions/runs/" in url and "/artifacts" in url:
                    return {
                        "total_count": 2,
                        "artifacts": [
                            {
                                "name": "validation-evidence",
                                "id": 1,
                                "expired": False,
                                "created_at": "2026-07-01T00:00:00Z",
                                "expires_at": "2026-07-31T00:00:00Z",
                                "archive_download_url": "https://example.invalid/evidence.zip",
                                "workflow_run": {"id": FIXTURE_RUN_ID},
                            },
                            {
                                "name": "addon-package",
                                "id": 2,
                                "expired": False,
                                "created_at": "2026-07-01T00:00:00Z",
                                "expires_at": "2026-07-31T00:00:00Z",
                                "archive_download_url": "https://example.invalid/package.zip",
                                "workflow_run": {"id": FIXTURE_RUN_ID},
                            },
                        ],
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
            repo_dir.mkdir(exist_ok=True)
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
            existing_repo.mkdir(exist_ok=True)
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

    def test_unrelated_reconciled_downgrade_is_rejected_before_promotion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            existing_repo = root / "repo"
            existing_site = root / "_site"
            existing_repo.mkdir(exist_ok=True)
            existing_site.mkdir()
            existing_manifest = (
                "<addons>"
                f'<addon id="{FIXTURE_ADDON_ID}" version="{FIXTURE_VERSION}"/>'
                '<addon id="plugin.other" version="2.0.0"/>'
                "</addons>"
            ).encode("utf-8")
            (existing_repo / "addons.xml").write_bytes(existing_manifest)
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
            api_get, candidate_download = _make_mock_api_responses(
                evidence_archive, package_archive
            )

            other_id = "plugin.other"
            other_version = "1.9.0"
            other_filename = f"{other_id}-{other_version}.zip"
            other_zip = root / other_filename
            _make_addon_zip(other_zip, other_id, other_version)
            other_url = f"https://example.invalid/{other_filename}"
            other_config = {
                "owner": "Example",
                "repo": other_id,
                "addon_id": other_id,
                "branch": "main",
            }

            def download(url, destination):
                if url == other_url:
                    shutil.copy2(other_zip, destination)
                else:
                    candidate_download(url, destination)

            with (
                mock.patch.dict(
                    os.environ, {"SOURCE_GITHUB_TOKEN": "test-source-token"}
                ),
                mock.patch.object(
                    builder, "source_github_api_get", side_effect=api_get
                ),
                mock.patch.object(
                    builder, "source_download_file", side_effect=download
                ),
                mock.patch.object(builder, "download_file", side_effect=download),
                mock.patch.object(
                    builder,
                    "get_latest_release_zip",
                    return_value=(other_url, other_version, other_filename),
                ),
                mock.patch.object(
                    builder,
                    "ADDONS",
                    [self._target_addon_config, other_config],
                ),
                self.assertRaisesRegex(RuntimeError, "plugin.other"),
            ):
                builder.build_immutable_repository(_valid_dispatch(), root)

            self.assertEqual(_snapshot_tree(existing_repo), repo_before)
            self.assertEqual(_snapshot_tree(existing_site), site_before)

    def test_repository_self_downgrade_is_rejected_before_promotion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_repo_root(tmpdir)
            (root / "repo" / "addons.xml").write_text(
                '<addons><addon id="repository.serph91p" version="2.0.0"/></addons>',
                encoding="utf-8",
            )
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

            with self.assertRaisesRegex(RuntimeError, "repository.serph91p"):
                self._build_with_mock(root, _valid_dispatch(), api_get, download)

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

    def test_missing_existing_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(RuntimeError, "current repository manifest"):
                builder._check_version_monotonicity(
                    Path(tmpdir), FIXTURE_ADDON_ID, FIXTURE_VERSION
                )

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

    def test_equal_and_higher_versions_are_monotonic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "addons.xml").write_text(
                '<addons><addon id="plugin.other" version="2.0.0"/></addons>',
                encoding="utf-8",
            )

            builder._check_version_monotonicity(root, "plugin.other", "2.0")
            builder._check_version_monotonicity(root, "plugin.other", "2.1.0")

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
        "publication_enabled": True,
        "publication_branch": "develop",
        "validation_workflow": "Add-on Validations",
        "validation_workflow_path": ".github/workflows/addon-validations.yml@develop",
        "validation_workflow_id": 211623879,
        "package_artifact_name": "addon-package",
        "evidence_artifact_name": "validation-evidence",
        "runtime_entries": ("addon.xml", "changelog.txt", "resources/"),
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
                mock.patch.object(builder, "ADDONS", [self._target_addon_config]),
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
                mock.patch.object(builder, "ADDONS", [self._target_addon_config]),
                self.assertRaises(RuntimeError) as ctx,
            ):
                builder.build_immutable_repository(_valid_dispatch(), root)
            self.assertIn("SOURCE_GITHUB_TOKEN", str(ctx.exception))

    def test_every_source_and_reconciliation_boundary_uses_only_source_token(self):
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
            artifacts_base = f"{run_url}/artifacts"
            evidence_url = "https://example.invalid/evidence.zip"
            package_url = "https://example.invalid/package.zip"
            other_id = "plugin.other"
            other_version = "1.0.0"
            other_filename = f"{other_id}-{other_version}.zip"
            other_zip = root / other_filename
            _make_addon_zip(other_zip, other_id, other_version)
            latest_release_url = (
                f"{builder.GH_API}/repos/Example/{other_id}/releases/latest"
            )
            other_url = f"https://example.invalid/{other_filename}"
            artifacts_payload = {
                "total_count": 2,
                "artifacts": [
                    {
                        "name": "validation-evidence",
                        "id": 1,
                        "expired": False,
                        "created_at": "2026-07-01T00:00:00Z",
                        "expires_at": "2026-07-31T00:00:00Z",
                        "archive_download_url": evidence_url,
                        "workflow_run": {"id": FIXTURE_RUN_ID},
                    },
                    {
                        "name": "addon-package",
                        "id": 2,
                        "expired": False,
                        "created_at": "2026-07-01T00:00:00Z",
                        "expires_at": "2026-07-31T00:00:00Z",
                        "archive_download_url": package_url,
                        "workflow_run": {"id": FIXTURE_RUN_ID},
                    },
                ],
            }
            responses = {
                run_url: json.dumps(_valid_run()).encode(),
                ref_url: json.dumps({"object": {"sha": FIXTURE_SHA}}).encode(),
                artifacts_base: json.dumps(artifacts_payload).encode(),
                evidence_url: evidence_archive.read_bytes(),
                package_url: package_archive.read_bytes(),
                latest_release_url: json.dumps(
                    {
                        "tag_name": f"v{other_version}",
                        "assets": [
                            {
                                "name": other_filename,
                                "browser_download_url": other_url,
                            }
                        ],
                    }
                ).encode(),
                other_url: other_zip.read_bytes(),
            }
            captured_api_requests = []
            captured_download_requests = []

            def api_urlopen(request):
                captured_api_requests.append(
                    (request.full_url, request.get_header("Authorization"))
                )
                for key, value in responses.items():
                    if request.full_url == key or request.full_url.startswith(
                        key + "?"
                    ):
                        return io.BytesIO(value)
                raise RuntimeError(f"Unexpected URL: {request.full_url}")

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
                mock.patch.object(
                    builder,
                    "ADDONS",
                    [
                        self._target_addon_config,
                        {
                            "owner": "Example",
                            "repo": other_id,
                            "addon_id": other_id,
                            "branch": "main",
                        },
                    ],
                ),
            ):
                builder.build_immutable_repository(_valid_dispatch(), root)

            self.assertEqual(
                captured_api_requests,
                [
                    (run_url, "token source-tok-abc"),
                    (ref_url, "token source-tok-abc"),
                    (f"{artifacts_base}?per_page=100&page=1", "token source-tok-abc"),
                    (latest_release_url, "token source-tok-abc"),
                    (ref_url, "token source-tok-abc"),
                ],
            )
            self.assertEqual(
                captured_download_requests,
                [
                    (evidence_url, "token source-tok-abc"),
                    (package_url, "token source-tok-abc"),
                    (other_url, "token source-tok-abc"),
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
                        "total_count": 2,
                        "artifacts": [
                            {
                                "name": "validation-evidence",
                                "id": 1,
                                "expired": False,
                                "created_at": "2026-07-01T00:00:00Z",
                                "expires_at": "2026-07-31T00:00:00Z",
                                "archive_download_url": "https://example.invalid/evidence.zip",
                                "workflow_run": {"id": FIXTURE_RUN_ID},
                            },
                            {
                                "name": "addon-package",
                                "id": 2,
                                "expired": False,
                                "created_at": "2026-07-01T00:00:00Z",
                                "expires_at": "2026-07-31T00:00:00Z",
                                "archive_download_url": "https://example.invalid/package.zip",
                                "workflow_run": {"id": FIXTURE_RUN_ID},
                            },
                        ],
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

    def test_source_token_is_used_for_unrelated_source_reads(self):
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
            source_api = mock.MagicMock(side_effect=api_get)

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
                mock.patch.object(builder, "source_github_api_get", source_api),
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
                    other_url,
                ],
            )
            self.assertEqual(generic_download_urls, [])
            release_lookup.assert_called_once_with(
                "Example",
                other_addon_id,
                other_addon_id,
                api_get=source_api,
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


class TestTrustBoundaryBypassRegressions(unittest.TestCase):
    """Focused regression tests for the two required attack vectors."""

    def _enabled_addon(self):
        config = next(
            c.copy()
            for c in builder.ADDONS
            if f"{c['owner']}/{c['repo']}" == FIXTURE_SOURCE_REPO
        )
        config["publication_enabled"] = True
        return config

    def test_same_name_untrusted_workflow_path_is_rejected(self):
        """A run with the approved display name but wrong workflow_id at an
        untrusted workflow path must fail even if sender input tries to match it."""
        with mock.patch.object(builder, "ADDONS", [self._enabled_addon()]):
            with self.assertRaises(RuntimeError) as ctx:
                builder.validate_dispatch_payload(
                    _valid_dispatch(
                        validation_workflow="Add-on Validations",
                        validation_workflow_path=(
                            ".github/workflows/untrusted.yml@develop"
                        ),
                    )
                )
            error = str(ctx.exception)
            self.assertIn("does not match approved path", error)

    def test_altered_artifact_names_from_sender_are_rejected(self):
        """Sender-selected package or evidence artifact names must be rejected."""
        with mock.patch.object(builder, "ADDONS", [self._enabled_addon()]):
            with self.assertRaises(RuntimeError) as ctx:
                builder.validate_dispatch_payload(
                    _valid_dispatch(package_artifact_name="malicious-package")
                )
            self.assertIn("unknown fields", str(ctx.exception))
            with self.assertRaises(RuntimeError) as ctx:
                builder.validate_dispatch_payload(
                    _valid_dispatch(evidence_artifact_name="malicious-evidence")
                )
            self.assertIn("unknown fields", str(ctx.exception))


class TestImmutablePublicationWorkflows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.target_workflow_path = (
            Path(__file__).parents[1] / ".github/workflows/update-repository.yml"
        )
        cls.target_workflow_text = cls.target_workflow_path.read_text(encoding="utf-8")
        cls.target_workflow = yaml.load(
            cls.target_workflow_text, Loader=yaml.BaseLoader
        )

    def test_repository_workflow_accepts_only_validated_publications(self):
        workflow = (
            Path(__file__).parents[1] / ".github/workflows/update-repository.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("types: [validated-addon-publication]", workflow)
        self.assertNotIn("addon-updated", workflow)
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertNotIn("\n  push:", workflow)

    def test_repository_workflow_never_falls_back_to_mutable_build(self):
        build_step = next(
            step
            for step in self.target_workflow["jobs"]["build-repository"]["steps"]
            if step["name"] == "Build repository"
        )
        self.assertEqual(
            build_step["env"]["DISPATCH_PAYLOAD"],
            "${{ toJSON(github.event.client_payload) }}",
        )

    def test_notifier_template_calls_pinned_reusable_workflow(self):
        workflow = (
            Path(__file__).parents[1] / "addon-workflow-templates/notify-repository.yml"
        ).read_text(encoding="utf-8")

        self.assertRegex(
            workflow,
            r"uses: Serph91P/repository\.serph91p/\.github/workflows/"
            r"reusable-notify-repository\.yml@[0-9a-f]{40}",
        )
        self.assertNotIn("repository-dispatch", workflow)
        self.assertIn("expected_branch: develop", workflow)

    def test_notifier_template_uses_fixed_workflow_path(self):
        workflow = (
            Path(__file__).parents[1] / "addon-workflow-templates/notify-repository.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(".github/workflows/addon-validations.yml@develop", workflow)
        self.assertNotIn("${{ github.event.workflow_run.path }}", workflow)

    def test_workflow_maps_source_artifact_token_separately(self):
        workflow = (
            Path(__file__).parents[1] / ".github/workflows/update-repository.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("SOURCE_GITHUB_TOKEN", workflow)
        self.assertIn("SOURCE_ARTIFACT_TOKEN", workflow)
        self.assertIn("${{ secrets.SOURCE_ARTIFACT_TOKEN }}", workflow)
        build_step = next(
            step
            for step in self.target_workflow["jobs"]["build-repository"]["steps"]
            if step["name"] == "Build repository"
        )
        build_env = build_step["env"]
        self.assertNotIn("GITHUB_TOKEN", build_env)

    def test_target_checkout_does_not_persist_credentials(self):
        checkout = self.target_workflow["jobs"]["build-repository"]["steps"][0]
        self.assertEqual(checkout["with"]["persist-credentials"], "false")

    def test_workflow_downloads_current_manifest_before_immutable_build(self):
        steps = self.target_workflow["jobs"]["build-repository"]["steps"]
        names = [step["name"] for step in steps]
        download_index = names.index("Download current repository manifest")
        build_index = names.index("Build repository")
        self.assertLess(download_index, build_index)
        self.assertEqual(
            steps[download_index]["run"],
            "python scripts/build_repository.py --download-current-manifest",
        )

    def test_target_actions_use_exact_verified_full_sha_pins(self):
        expected = {
            "actions/checkout": "34e114876b0b11c390a56381ad16ebd13914f8d5",
            "actions/setup-python": "a26af69be951a213d495a4c3e4e4022e16d87065",
            "actions/upload-pages-artifact": (
                "56afc609e74202658d3ffba0e8f6dda462b719fa"
            ),
            "actions/deploy-pages": "d6db90164ac5ed86f2b6aed7e0febac5b3c0c03e",
        }
        actual = {}
        for job in self.target_workflow["jobs"].values():
            for step in job["steps"]:
                if "uses" not in step:
                    continue
                action, revision = step["uses"].rsplit("@", 1)
                self.assertRegex(revision, r"^[0-9a-f]{40}$")
                actual[action] = revision
        self.assertEqual(actual, expected)
        self.assertIsNone(re.search(r"uses:\s+[^\s]+@v\d+", self.target_workflow_text))

    def test_target_jobs_have_timeouts_and_least_privilege(self):
        self.assertNotIn("permissions", self.target_workflow)
        build = self.target_workflow["jobs"]["build-repository"]
        deploy = self.target_workflow["jobs"]["deploy"]
        self.assertEqual(build["timeout-minutes"], "30")
        self.assertEqual(build["permissions"], {"contents": "read"})
        self.assertEqual(deploy["timeout-minutes"], "10")
        self.assertEqual(
            deploy["permissions"],
            {"pages": "write", "id-token": "write"},
        )

    def test_source_token_not_in_dispatch_payload(self):
        notify = (
            Path(__file__).parents[1] / "addon-workflow-templates/notify-repository.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("SOURCE_GITHUB_TOKEN", notify)
        self.assertNotIn("SOURCE_ARTIFACT_TOKEN", notify)
        self.assertNotIn("source_token", notify)

    def test_target_policy_is_bound_per_source_in_addons(self):
        for config in builder.ADDONS:
            with self.subTest(source=f"{config['owner']}/{config['repo']}"):
                self.assertEqual(
                    config["validation_workflow_path"],
                    ".github/workflows/addon-validations.yml@develop",
                )
                self.assertEqual(config["publication_branch"], "develop")
                self.assertEqual(config["package_artifact_name"], "addon-package")
                self.assertEqual(
                    config["evidence_artifact_name"], "validation-evidence"
                )
                self.assertFalse(config["publication_enabled"])


if __name__ == "__main__":
    unittest.main()
