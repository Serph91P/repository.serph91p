import datetime
import hashlib
import importlib.util
import io
import json
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "addon-publication" / "notify_repository.py"
SPEC = importlib.util.spec_from_file_location("notify_repository", MODULE_PATH)
notifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notifier)

SHA = "a" * 40
CHECKSUM = "b" * 64
RUN_ID = 123456
SOURCE = "Serph91P/plugin.video.example"
ADDON_ID = "plugin.video.example"
VERSION = "1.2.3+omega.1"
ASSET = f"{ADDON_ID}-{VERSION}.zip"
PUBLICATION_ID = f"{ADDON_ID}@{VERSION}"
NOW = datetime.datetime(2026, 7, 17, 12, 0, tzinfo=datetime.timezone.utc)


def valid_inputs(**overrides):
    values = {
        "source_repository": SOURCE,
        "candidate_sha": SHA,
        "validation_run_id": RUN_ID,
        "validation_workflow": "Add-on Validations",
        "validation_workflow_path": ".github/workflows/addon-validations.yml@develop",
        "expected_branch": "develop",
        "addon_id": ADDON_ID,
        "addon_version": VERSION,
        "asset_name": ASSET,
        "artifact_sha256": CHECKSUM,
        "publication_id": PUBLICATION_ID,
    }
    values.update(overrides)
    return values


def valid_run(**overrides):
    value = {
        "id": RUN_ID,
        "head_sha": SHA,
        "name": "Add-on Validations",
        "path": ".github/workflows/addon-validations.yml@develop",
        "head_branch": "develop",
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": SOURCE},
    }
    value.update(overrides)
    return value


def valid_evidence(**overrides):
    value = {
        "validation_run_id": RUN_ID,
        "candidate_sha": SHA,
        "validation_head_sha": SHA,
        "addon_id": ADDON_ID,
        "addon_version": VERSION,
        "asset_name": ASSET,
        "artifact_sha256": CHECKSUM,
        "publication_id": PUBLICATION_ID,
    }
    value.update(overrides)
    return value


def artifact(name, artifact_id, *, expired=False, run_id=RUN_ID, **overrides):
    value = {
        "id": artifact_id,
        "name": name,
        "expired": expired,
        "created_at": "2026-07-01T12:00:00Z",
        "expires_at": "2026-07-31T12:00:00Z",
        "archive_download_url": (
            f"https://api.github.com/repos/{SOURCE}/actions/artifacts/{artifact_id}/zip"
        ),
        "workflow_run": {"id": run_id},
    }
    value.update(overrides)
    return value


def evidence_archive(evidence=None, *, members=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        if members is None:
            archive.writestr(
                "validation-evidence.json",
                json.dumps(evidence if evidence is not None else valid_evidence()),
            )
        else:
            for name, data in members:
                archive.writestr(name, data)
    return output.getvalue()


def package_artifact_archive(package_bytes=b"package", *, members=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        if members is None:
            archive.writestr(ASSET, package_bytes)
        else:
            for name, data in members:
                archive.writestr(name, data)
    return output.getvalue()


class ValidateInputsTests(unittest.TestCase):
    def test_valid_inputs_bind_exact_source(self):
        values = notifier.validate_inputs(valid_inputs(), SOURCE)
        self.assertEqual(values["source_repository"], SOURCE)

    def test_missing_unknown_and_malformed_inputs_fail_closed(self):
        bad_cases = []
        missing = valid_inputs()
        del missing["addon_id"]
        bad_cases.append(missing)
        bad_cases.extend(
            [
                valid_inputs(extra="no"),
                valid_inputs(source_repository="Other/repo"),
                valid_inputs(candidate_sha="A" * 40),
                valid_inputs(validation_run_id=True),
                valid_inputs(validation_run_id=0),
                valid_inputs(validation_workflow=""),
                valid_inputs(
                    validation_workflow_path=(
                        ".github/workflows/addon-validations.yml@main"
                    )
                ),
                valid_inputs(expected_branch="main"),
                valid_inputs(addon_id="bad/id"),
                valid_inputs(addon_version="1.0 beta"),
                valid_inputs(asset_name="other.zip"),
                valid_inputs(artifact_sha256="B" * 64),
                valid_inputs(publication_id="wrong@1.0"),
            ]
        )
        for values in bad_cases:
            with self.subTest(values=values):
                with self.assertRaises(notifier.NotificationError):
                    notifier.validate_inputs(values, SOURCE)


class ValidateRunTests(unittest.TestCase):
    def test_successful_push_run_on_develop_passes(self):
        notifier.validate_run(valid_run(), valid_inputs())

    def test_identity_mismatches_fail_closed(self):
        cases = [
            valid_run(id=RUN_ID + 1),
            valid_run(head_sha="c" * 40),
            valid_run(name="Other"),
            valid_run(path=".github/workflows/untrusted.yml@develop"),
            valid_run(head_branch="main"),
            valid_run(event="workflow_dispatch"),
            valid_run(status="in_progress"),
            valid_run(conclusion="failure"),
            valid_run(repository={"full_name": "Other/repo"}),
            {"id": RUN_ID},
            "not-an-object",
        ]
        for run in cases:
            with self.subTest(run=run):
                with self.assertRaises(notifier.NotificationError):
                    notifier.validate_run(run, valid_inputs())


class ArtifactPaginationTests(unittest.TestCase):
    def _fetcher(self, pages):
        calls = []

        def fetch(url):
            calls.append(url)
            return pages[len(calls) - 1]

        return fetch, calls

    def test_artifacts_are_found_across_pages(self):
        next_url = (
            f"https://api.github.com/repos/{SOURCE}/actions/runs/{RUN_ID}/artifacts"
            "?per_page=100&page=2"
        )
        pages = [
            (
                {"artifacts": [artifact("unrelated", 9)]},
                {"Link": f'<{next_url}>; rel="next"'},
            ),
            (
                {
                    "artifacts": [
                        artifact("validation-evidence", 1),
                        artifact("addon-package", 2),
                    ]
                },
                {},
            ),
        ]
        fetch, calls = self._fetcher(pages)
        selected = notifier.find_required_artifacts(fetch, SOURCE, RUN_ID, now=NOW)
        self.assertEqual(selected["validation-evidence"]["id"], 1)
        self.assertEqual(selected["addon-package"]["id"], 2)
        self.assertEqual(len(calls), 2)

    def test_zero_duplicate_expired_and_wrong_run_fail_closed(self):
        cases = [
            [{"artifacts": []}, {}],
            [
                {
                    "artifacts": [
                        artifact("validation-evidence", 1),
                        artifact("validation-evidence", 2),
                        artifact("addon-package", 3),
                    ]
                },
                {},
            ],
            [
                {
                    "artifacts": [
                        artifact("validation-evidence", 1, expired=True),
                        artifact("addon-package", 2),
                    ]
                },
                {},
            ],
            [
                {
                    "artifacts": [
                        artifact("validation-evidence", 1, run_id=999),
                        artifact("addon-package", 2),
                    ]
                },
                {},
            ],
            [
                {
                    "artifacts": [
                        artifact(
                            "validation-evidence",
                            1,
                            expires_at="2026-07-08T12:00:00Z",
                        ),
                        artifact("addon-package", 2),
                    ]
                },
                {},
            ],
        ]
        for page in cases:
            with self.subTest(page=page):
                fetch, _ = self._fetcher([tuple(page)])
                with self.assertRaises(notifier.NotificationError):
                    notifier.find_required_artifacts(fetch, SOURCE, RUN_ID, now=NOW)

    def test_duplicate_across_pages_and_malformed_pagination_fail_closed(self):
        base = (
            f"https://api.github.com/repos/{SOURCE}/actions/runs/{RUN_ID}/artifacts"
            "?per_page=100&page=2"
        )
        duplicate_pages = [
            (
                {"artifacts": [artifact("validation-evidence", 1)]},
                {"Link": f'<{base}>; rel="next"'},
            ),
            (
                {
                    "artifacts": [
                        artifact("validation-evidence", 2),
                        artifact("addon-package", 3),
                    ]
                },
                {},
            ),
        ]
        fetch, _ = self._fetcher(duplicate_pages)
        with self.assertRaises(notifier.NotificationError):
            notifier.find_required_artifacts(fetch, SOURCE, RUN_ID, now=NOW)

        unsafe_pages = [
            (
                {
                    "artifacts": [
                        artifact("validation-evidence", 1),
                        artifact("addon-package", 2),
                    ]
                },
                {"Link": '<https://evil.invalid/next>; rel="next"'},
            )
        ]
        fetch, _ = self._fetcher(unsafe_pages)
        with self.assertRaises(notifier.NotificationError):
            notifier.find_required_artifacts(fetch, SOURCE, RUN_ID, now=NOW)

    def test_duplicate_required_artifact_on_later_page_fails_closed(self):
        """Regression: duplicate addon-package on a later page must be rejected."""
        base = (
            f"https://api.github.com/repos/{SOURCE}/actions/runs/{RUN_ID}/artifacts"
            "?per_page=100&page=2"
        )
        pages = [
            (
                {
                    "artifacts": [
                        artifact("addon-package", 1),
                    ]
                },
                {"Link": f'<{base}>; rel="next"'},
            ),
            (
                {
                    "artifacts": [
                        artifact("addon-package", 3),
                        artifact("validation-evidence", 2),
                    ]
                },
                {},
            ),
        ]
        fetch, _ = self._fetcher(pages)
        with self.assertRaises(notifier.NotificationError):
            notifier.find_required_artifacts(fetch, SOURCE, RUN_ID, now=NOW)

    def test_malformed_page_or_artifact_fails_closed(self):
        for payload in (
            [],
            {},
            {"artifacts": "not-a-list"},
            {"artifacts": [{"name": "addon-package"}]},
            {
                "artifacts": [
                    artifact(
                        "addon-package",
                        1,
                        archive_download_url=(
                            "https://api.github.com/repos/Other/repo/"
                            "actions/artifacts/1/zip"
                        ),
                    )
                ]
            },
        ):
            with self.subTest(payload=payload):
                fetch, _ = self._fetcher([(payload, {})])
                with self.assertRaises(notifier.NotificationError):
                    notifier.find_required_artifacts(fetch, SOURCE, RUN_ID, now=NOW)

    def test_missing_malformed_expired_and_future_retention_timestamps_fail_closed(self):
        cases = [
            {"created_at": None},
            {"expires_at": None},
            {"created_at": "2026-07-01T12:00:00+00:00"},
            {
                "created_at": "2026-06-17T12:00:00Z",
                "expires_at": "2026-07-17T12:00:00Z",
            },
            {
                "created_at": "2026-07-18T12:00:00Z",
                "expires_at": "2026-08-17T12:00:00Z",
            },
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                page = {
                    "artifacts": [
                        artifact("validation-evidence", 1, **overrides),
                        artifact("addon-package", 2),
                    ]
                }
                fetch, _ = self._fetcher([(page, {})])
                with self.assertRaises(notifier.NotificationError):
                    notifier.find_required_artifacts(fetch, SOURCE, RUN_ID, now=NOW)


class EvidenceTests(unittest.TestCase):
    def test_exact_evidence_and_optional_empty_tag_pass(self):
        for evidence in (valid_evidence(), valid_evidence(tag="")):
            with self.subTest(evidence=evidence):
                parsed = notifier.read_and_validate_evidence_archive(
                    evidence_archive(evidence), valid_inputs()
                )
                self.assertEqual(parsed["publication_id"], PUBLICATION_ID)

    def test_malformed_missing_mismatched_or_extra_evidence_fails_closed(self):
        bad = []
        missing = valid_evidence()
        del missing["asset_name"]
        bad.append(missing)
        bad.extend(
            [
                valid_evidence(validation_run_id=str(RUN_ID)),
                valid_evidence(candidate_sha="c" * 40),
                valid_evidence(validation_head_sha="c" * 40),
                valid_evidence(addon_id="plugin.other"),
                valid_evidence(addon_version="9.9.9"),
                valid_evidence(asset_name="wrong.zip"),
                valid_evidence(artifact_sha256="c" * 64),
                valid_evidence(publication_id="wrong@9.9.9"),
                valid_evidence(tag="develop"),
                valid_evidence(tag=None),
                valid_evidence(extra="no"),
            ]
        )
        for evidence in bad:
            with self.subTest(evidence=evidence):
                with self.assertRaises(notifier.NotificationError):
                    notifier.read_and_validate_evidence_archive(
                        evidence_archive(evidence), valid_inputs()
                    )
        for raw in (b"not-a-zip", evidence_archive(members=[])):
            with self.subTest(raw=raw):
                with self.assertRaises(notifier.NotificationError):
                    notifier.read_and_validate_evidence_archive(raw, valid_inputs())

    def test_evidence_wrapper_has_exact_cardinality_and_filename(self):
        cases = [
            [("wrong.json", "{}")],
            [("validation-evidence.json", "{}"), ("extra", "x")],
            [("validation-evidence.json/", "")],
        ]
        for members in cases:
            with self.subTest(members=members):
                with self.assertRaises(notifier.NotificationError):
                    notifier.read_and_validate_evidence_archive(
                        evidence_archive(members=members), valid_inputs()
                    )

    def test_duplicate_evidence_json_keys_fail_closed(self):
        rendered = json.dumps(valid_evidence(), separators=(",", ":"))
        rendered = rendered.replace(
            f'"candidate_sha":"{SHA}"',
            f'"candidate_sha":"{"c" * 40}","candidate_sha":"{SHA}"',
        )
        with self.assertRaises(notifier.NotificationError):
            notifier.read_and_validate_evidence_archive(
                evidence_archive(members=[("validation-evidence.json", rendered)]),
                valid_inputs(),
            )


class PackageArtifactTests(unittest.TestCase):
    def test_package_wrapper_filename_and_checksum_are_verified(self):
        package_bytes = b"exact immutable package bytes"
        values = valid_inputs(artifact_sha256=hashlib.sha256(package_bytes).hexdigest())
        notifier.read_and_validate_package_archive(
            package_artifact_archive(package_bytes), values
        )

    def test_package_wrapper_mismatch_and_malformed_cardinality_fail_closed(self):
        package_bytes = b"exact immutable package bytes"
        values = valid_inputs(artifact_sha256=hashlib.sha256(package_bytes).hexdigest())
        bad_archives = [
            b"not-a-zip",
            package_artifact_archive(package_bytes, members=[]),
            package_artifact_archive(
                package_bytes, members=[("wrong.zip", package_bytes)]
            ),
            package_artifact_archive(
                package_bytes,
                members=[(ASSET, package_bytes), ("extra", b"no")],
            ),
            package_artifact_archive(b"tampered"),
        ]
        for raw in bad_archives:
            with self.subTest(raw=raw):
                with self.assertRaises(notifier.NotificationError):
                    notifier.read_and_validate_package_archive(raw, values)


class PrepareDispatchTests(unittest.TestCase):
    def test_both_artifact_wrappers_are_downloaded_and_validated(self):
        package_bytes = b"exact immutable package bytes"
        values = valid_inputs(artifact_sha256=hashlib.sha256(package_bytes).hexdigest())
        artifacts = {
            "artifacts": [
                artifact("addon-package", 1),
                artifact("validation-evidence", 2),
            ]
        }

        def api_request(_token, url):
            if url.endswith(f"/actions/runs/{RUN_ID}"):
                return valid_run(), {}
            return artifacts, {}

        with (
            mock.patch.object(notifier, "_api_request", side_effect=api_request),
            mock.patch.object(
                notifier,
                "_download_artifact",
                side_effect=[
                    package_artifact_archive(package_bytes),
                    evidence_archive(
                        valid_evidence(artifact_sha256=values["artifact_sha256"])
                    ),
                ],
            ) as download,
        ):
            payload = notifier.prepare_dispatch(
                values, SOURCE, "source-token", now=NOW
            )

        self.assertEqual(download.call_count, 2)
        self.assertEqual(payload["source_repo"], SOURCE)


class DispatchPayloadTests(unittest.TestCase):
    def test_dispatch_payload_is_exact_metadata_only_schema(self):
        payload = notifier.build_dispatch_payload(valid_inputs())
        self.assertEqual(
            tuple(payload),
            (
                "source_repo",
                "candidate_sha",
                "validation_run_id",
                "validation_head_sha",
                "validation_workflow",
                "validation_workflow_path",
                "expected_branch",
            ),
        )
        self.assertIs(type(payload["validation_run_id"]), int)
        rendered = json.dumps(payload, sort_keys=True).lower()
        for forbidden in (
            "token",
            "credential",
            "artifact_sha256",
            "asset_name",
            "archive_download_url",
            "signed",
        ):
            self.assertNotIn(forbidden, rendered)


if __name__ == "__main__":
    unittest.main()
