#!/usr/bin/env python3
"""Validate immutable publication evidence and prepare a metadata-only dispatch."""

import argparse
import datetime
import hashlib
import io
import json
import os
import re
import stat
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import NamedTuple


GH_API = "https://api.github.com"
TARGET_BRANCH = "develop"
PACKAGE_ARTIFACT = "addon-package"
EVIDENCE_ARTIFACT = "validation-evidence"
EVIDENCE_FILENAME = "validation-evidence.json"
MAX_EVIDENCE_ARCHIVE_BYTES = 2 * 1024 * 1024
MAX_EVIDENCE_JSON_BYTES = 64 * 1024
MAX_PACKAGE_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_PACKAGE_BYTES = 512 * 1024 * 1024
MAX_ARTIFACT_PAGES = 100
ARTIFACT_RETENTION = datetime.timedelta(days=30)
SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
REPOSITORY_RE = re.compile(
    r"^[0-9A-Za-z_.-]+/[0-9A-Za-z_.-]+$", re.ASCII
)
ADDON_ID_RE = re.compile(r"^[0-9A-Za-z._-]+$", re.ASCII)
VERSION_RE = re.compile(
    r"^[0-9]+(?:\.[0-9]+)*(?:\+[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?$",
    re.ASCII,
)
WORKFLOW_PATH_RE = re.compile(
    r"^\.github/workflows/[0-9A-Za-z_.-]+\.ya?ml@develop$", re.ASCII
)
INPUT_FIELDS = (
    "source_repository",
    "candidate_sha",
    "validation_run_id",
    "validation_workflow",
    "validation_workflow_path",
    "expected_branch",
    "addon_id",
    "addon_version",
    "asset_name",
    "artifact_sha256",
    "publication_id",
)
EVIDENCE_FIELDS = (
    "validation_run_id",
    "candidate_sha",
    "validation_head_sha",
    "addon_id",
    "addon_version",
    "asset_name",
    "artifact_sha256",
    "publication_id",
)
DISPATCH_FIELDS = (
    "source_repo",
    "candidate_sha",
    "validation_run_id",
    "validation_head_sha",
    "validation_workflow",
    "validation_workflow_path",
    "expected_branch",
    "publication_id",
)


class NotificationError(RuntimeError):
    """Raised when notifier input or evidence violates the strict contract."""


class ArtifactSelection(NamedTuple):
    package: dict
    evidence: dict


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Strip authorization before following a redirect to another origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        old = urllib.parse.urlsplit(req.full_url)
        new = urllib.parse.urlsplit(newurl)
        if (old.scheme, old.hostname, old.port) != (new.scheme, new.hostname, new.port):
            redirected.remove_header("Authorization")
        return redirected


def _require_nonempty_string(value, label):
    if not isinstance(value, str) or not value:
        raise NotificationError(f"{label} must be a non-empty string")
    return value


def _require_positive_integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise NotificationError(f"{label} must be a positive integer")
    return value


def validate_inputs(values, actual_source_repository):
    """Validate exact reusable-workflow identity inputs."""
    if not isinstance(values, dict):
        raise NotificationError("notifier inputs must be an object")
    if tuple(values) != INPUT_FIELDS and set(values) != set(INPUT_FIELDS):
        missing = sorted(set(INPUT_FIELDS) - set(values))
        unknown = sorted(set(values) - set(INPUT_FIELDS))
        raise NotificationError(
            f"notifier input fields do not match contract; missing={missing}, unknown={unknown}"
        )
    source = _require_nonempty_string(values["source_repository"], "source repository")
    actual = _require_nonempty_string(actual_source_repository, "actual source repository")
    if not REPOSITORY_RE.fullmatch(source) or source != actual:
        raise NotificationError("source repository identity does not match")
    candidate_sha = values["candidate_sha"]
    if not isinstance(candidate_sha, str) or not SHA_RE.fullmatch(candidate_sha):
        raise NotificationError("candidate SHA must be 40 lowercase hexadecimal characters")
    _require_positive_integer(values["validation_run_id"], "validation run ID")
    _require_nonempty_string(values["validation_workflow"], "validation workflow")
    workflow_path = values["validation_workflow_path"]
    if not isinstance(workflow_path, str) or not WORKFLOW_PATH_RE.fullmatch(
        workflow_path
    ):
        raise NotificationError(
            "validation workflow path must identify a develop workflow run"
        )
    if values["expected_branch"] != TARGET_BRANCH:
        raise NotificationError("expected branch must be develop")
    addon_id = values["addon_id"]
    if not isinstance(addon_id, str) or not ADDON_ID_RE.fullmatch(addon_id):
        raise NotificationError("configured add-on ID is invalid")
    version = values["addon_version"]
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise NotificationError("configured add-on version is invalid")
    expected_asset = f"{addon_id}-{version}.zip"
    if values["asset_name"] != expected_asset:
        raise NotificationError("package filename does not match configured identity")
    checksum = values["artifact_sha256"]
    if not isinstance(checksum, str) or not SHA256_RE.fullmatch(checksum):
        raise NotificationError("artifact SHA-256 must be 64 lowercase hexadecimal characters")
    if values["publication_id"] != f"{addon_id}@{version}":
        raise NotificationError("publication ID does not match configured identity")
    return dict(values)


def validate_run(run, values):
    """Bind an exact completed successful push run to the notifier inputs."""
    if not isinstance(run, dict):
        raise NotificationError("validation run response must be an object")
    repository = run.get("repository")
    checks = (
        (run.get("id"), values["validation_run_id"], "run ID"),
        (run.get("head_sha"), values["candidate_sha"], "run head SHA"),
        (run.get("name"), values["validation_workflow"], "workflow name"),
        (
            run.get("path"),
            values["validation_workflow_path"],
            "workflow path",
        ),
        (run.get("head_branch"), TARGET_BRANCH, "run branch"),
        (run.get("event"), "push", "run event"),
        (run.get("status"), "completed", "run status"),
        (run.get("conclusion"), "success", "run conclusion"),
        (
            repository.get("full_name") if isinstance(repository, dict) else None,
            values["source_repository"],
            "run repository",
        ),
    )
    for actual, expected, label in checks:
        if actual != expected:
            raise NotificationError(f"{label} does not match immutable notifier input")


def _artifact_page_url(source_repository, run_id, page):
    repository = urllib.parse.quote(source_repository, safe="/")
    return (
        f"{GH_API}/repos/{repository}/actions/runs/{run_id}/artifacts"
        f"?per_page=100&page={page}"
    )


def _validate_page_url(url, source_repository, run_id):
    if not isinstance(url, str):
        raise NotificationError("artifact pagination URL must be a string")
    parsed = urllib.parse.urlsplit(url)
    expected_path = urllib.parse.urlsplit(
        _artifact_page_url(source_repository, run_id, 1)
    ).path
    if (
        parsed.scheme != "https"
        or parsed.netloc != "api.github.com"
        or parsed.path != expected_path
        or parsed.fragment
    ):
        raise NotificationError("artifact pagination URL escaped the exact run endpoint")
    query = urllib.parse.parse_qs(parsed.query, strict_parsing=True)
    if set(query) != {"per_page", "page"} or query["per_page"] != ["100"]:
        raise NotificationError("artifact pagination query is malformed")
    if len(query["page"]) != 1 or not query["page"][0].isdigit():
        raise NotificationError("artifact pagination page is malformed")
    page = int(query["page"][0])
    if page <= 0 or page > MAX_ARTIFACT_PAGES:
        raise NotificationError("artifact pagination page is outside the accepted range")


def _header(headers, name):
    if not isinstance(headers, dict):
        raise NotificationError("artifact response headers must be an object")
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == name.lower():
            if not isinstance(value, str):
                raise NotificationError(f"{name} header must be a string")
            return value
    return None


def _next_link(headers):
    link = _header(headers, "Link")
    if link is None:
        return None
    next_urls = []
    for raw_part in link.split(","):
        match = re.fullmatch(
            r'\s*<([^<>]+)>\s*;\s*rel="(next|prev|last|first)"\s*',
            raw_part,
            re.ASCII,
        )
        if not match:
            raise NotificationError("artifact pagination Link header is malformed")
        if match.group(2) == "next":
            next_urls.append(match.group(1))
    if len(next_urls) > 1:
        raise NotificationError("artifact pagination has duplicate next links")
    return next_urls[0] if next_urls else None


def _validate_artifact(value, source_repository, run_id, now):
    if not isinstance(value, dict):
        raise NotificationError("artifact entry must be an object")
    artifact_id = value.get("id")
    name = value.get("name")
    expired = value.get("expired")
    download_url = value.get("archive_download_url")
    workflow_run = value.get("workflow_run")
    created_at = value.get("created_at")
    expires_at = value.get("expires_at")
    if isinstance(artifact_id, bool) or not isinstance(artifact_id, int) or artifact_id <= 0:
        raise NotificationError("artifact ID must be a positive integer")
    _require_nonempty_string(name, "artifact name")
    if not isinstance(expired, bool):
        raise NotificationError("artifact expired flag must be boolean")
    if not isinstance(workflow_run, dict) or workflow_run.get("id") != run_id:
        raise NotificationError("artifact is not bound to the exact validation run")
    if not isinstance(created_at, str) or not isinstance(expires_at, str):
        raise NotificationError("artifact retention timestamps are malformed")
    try:
        created = datetime.datetime.strptime(
            created_at, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=datetime.timezone.utc)
        expires = datetime.datetime.strptime(
            expires_at, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError) as error:
        raise NotificationError("artifact retention timestamps are malformed") from error
    if expires - created != ARTIFACT_RETENTION:
        raise NotificationError("artifact retention must be exactly 30 days")
    if now < created or now >= expires:
        raise NotificationError("artifact retention window is not currently live")
    if not isinstance(download_url, str):
        raise NotificationError("artifact download URL must be a string")
    parsed = urllib.parse.urlsplit(download_url)
    repository = urllib.parse.quote(source_repository, safe="/")
    expected_path = f"/repos/{repository}/actions/artifacts/{artifact_id}/zip"
    if (
        parsed.scheme != "https"
        or parsed.netloc != "api.github.com"
        or parsed.path != expected_path
        or parsed.query
        or parsed.fragment
    ):
        raise NotificationError("artifact download URL is malformed")
    return value


def find_required_artifacts(fetch_page, source_repository, run_id, *, now=None):
    """Enumerate every artifact page and select exact required artifacts."""
    if (
        not isinstance(source_repository, str)
        or not REPOSITORY_RE.fullmatch(source_repository)
    ):
        raise NotificationError("source repository identity is malformed")
    _require_positive_integer(run_id, "validation run ID")
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    if not isinstance(now, datetime.datetime) or now.tzinfo is None:
        raise NotificationError("artifact validation time must include a timezone")
    now = now.astimezone(datetime.timezone.utc)
    url = _artifact_page_url(source_repository, run_id, 1)
    visited = set()
    artifacts = []
    while url is not None:
        _validate_page_url(url, source_repository, run_id)
        if url in visited:
            raise NotificationError("artifact pagination cycle detected")
        if len(visited) >= MAX_ARTIFACT_PAGES:
            raise NotificationError("artifact pagination exceeded the page limit")
        visited.add(url)
        response = fetch_page(url)
        if not isinstance(response, tuple) or len(response) != 2:
            raise NotificationError("artifact fetcher returned a malformed response")
        payload, headers = response
        if not isinstance(payload, dict) or not isinstance(payload.get("artifacts"), list):
            raise NotificationError("artifact page payload is malformed")
        artifacts.extend(
            _validate_artifact(item, source_repository, run_id, now)
            for item in payload["artifacts"]
        )
        url = _next_link(headers)
    selected = {}
    for required_name in (PACKAGE_ARTIFACT, EVIDENCE_ARTIFACT):
        matches = [item for item in artifacts if item["name"] == required_name]
        if len(matches) != 1:
            raise NotificationError(
                f"required artifact {required_name!r} must occur exactly once"
            )
        if matches[0]["expired"]:
            raise NotificationError(f"required artifact {required_name!r} has expired")
        selected[required_name] = matches[0]
    return selected


def validate_evidence(evidence, values):
    """Validate evidence with producer-compatible optional empty tag behavior."""
    if not isinstance(evidence, dict):
        raise NotificationError("validation evidence must be an object")
    fields = set(evidence)
    required = set(EVIDENCE_FIELDS)
    if fields not in (required, required | {"tag"}):
        raise NotificationError("validation evidence fields do not match the contract")
    if "tag" in evidence and evidence["tag"] != "":
        raise NotificationError("optional evidence tag must be exactly empty")
    expected = {
        "validation_run_id": values["validation_run_id"],
        "candidate_sha": values["candidate_sha"],
        "validation_head_sha": values["candidate_sha"],
        "addon_id": values["addon_id"],
        "addon_version": values["addon_version"],
        "asset_name": values["asset_name"],
        "artifact_sha256": values["artifact_sha256"],
        "publication_id": values["publication_id"],
    }
    for field, expected_value in expected.items():
        actual = evidence.get(field)
        if field == "validation_run_id":
            if type(actual) is not int:
                raise NotificationError("evidence validation run ID must be an integer")
        elif not isinstance(actual, str):
            raise NotificationError(f"evidence {field} must be a string")
        if actual != expected_value:
            raise NotificationError(f"evidence {field} does not match notifier input")
    return evidence


def _reject_duplicate_json_fields(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise NotificationError("validation evidence JSON has duplicate fields")
        value[key] = item
    return value


def read_and_validate_evidence_archive(raw_archive, values):
    """Read one exact evidence JSON file from an artifact wrapper ZIP."""
    if not isinstance(raw_archive, bytes) or len(raw_archive) > MAX_EVIDENCE_ARCHIVE_BYTES:
        raise NotificationError("evidence artifact bytes are missing or too large")
    try:
        with zipfile.ZipFile(io.BytesIO(raw_archive), "r") as archive:
            infos = archive.infolist()
            if len(infos) != 1:
                raise NotificationError("evidence artifact must contain exactly one file")
            info = infos[0]
            mode = info.external_attr >> 16
            if (
                info.filename != EVIDENCE_FILENAME
                or info.is_dir()
                or info.flag_bits & 0x1
                or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                or info.file_size > MAX_EVIDENCE_JSON_BYTES
            ):
                raise NotificationError("evidence artifact member is invalid")
            raw_json = archive.read(info)
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        if isinstance(error, NotificationError):
            raise
        raise NotificationError("evidence artifact is not a valid ZIP") from error
    try:
        evidence = json.loads(
            raw_json.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_fields
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NotificationError("validation evidence JSON is malformed") from error
    return validate_evidence(evidence, values)


def read_and_validate_package_archive(raw_archive, values):
    """Verify one exact immutable package inside its artifact wrapper ZIP."""
    if not isinstance(raw_archive, bytes) or len(raw_archive) > MAX_PACKAGE_ARCHIVE_BYTES:
        raise NotificationError("package artifact bytes are missing or too large")
    try:
        with zipfile.ZipFile(io.BytesIO(raw_archive), "r") as archive:
            infos = archive.infolist()
            if len(infos) != 1:
                raise NotificationError("package artifact must contain exactly one file")
            info = infos[0]
            mode = info.external_attr >> 16
            if (
                info.filename != values["asset_name"]
                or info.is_dir()
                or info.flag_bits & 0x1
                or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                or info.file_size > MAX_PACKAGE_BYTES
            ):
                raise NotificationError("package artifact member is invalid")
            package = archive.read(info)
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        if isinstance(error, NotificationError):
            raise
        raise NotificationError("package artifact is not a valid ZIP") from error
    actual_sha256 = hashlib.sha256(package).hexdigest()
    if actual_sha256 != values["artifact_sha256"]:
        raise NotificationError("package artifact SHA-256 does not match evidence")


def build_dispatch_payload(values):
    """Build the exact metadata-only repository dispatch payload."""
    payload = {
        "source_repo": values["source_repository"],
        "candidate_sha": values["candidate_sha"],
        "validation_run_id": values["validation_run_id"],
        "validation_head_sha": values["candidate_sha"],
        "validation_workflow": values["validation_workflow"],
        "validation_workflow_path": values["validation_workflow_path"],
        "expected_branch": TARGET_BRANCH,
        "publication_id": values["publication_id"],
    }
    if tuple(payload) != DISPATCH_FIELDS:
        raise AssertionError("dispatch field order drifted")
    return payload


def _api_request(token, url):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(MAX_EVIDENCE_ARCHIVE_BYTES + 1)
            headers = dict(response.headers.items())
    except (OSError, urllib.error.HTTPError, urllib.error.URLError) as error:
        raise NotificationError("GitHub API request failed") from error
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NotificationError("GitHub API returned malformed JSON") from error
    return payload, headers


def _download_artifact(token, url, maximum_bytes, label):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    try:
        with opener.open(request, timeout=30) as response:
            raw = response.read(maximum_bytes + 1)
    except (OSError, urllib.error.HTTPError, urllib.error.URLError) as error:
        raise NotificationError(f"{label} artifact download failed") from error
    if len(raw) > maximum_bytes:
        raise NotificationError(f"{label} artifact exceeds the size limit")
    return raw


def prepare_dispatch(values, actual_source_repository, token, *, now=None):
    """Verify one exact completed run and return its metadata-only dispatch."""
    validated = validate_inputs(values, actual_source_repository)
    if not isinstance(token, str) or not token:
        raise NotificationError("GitHub Actions token is required")
    source = urllib.parse.quote(validated["source_repository"], safe="/")
    run_id = validated["validation_run_id"]
    run, _ = _api_request(
        token, f"{GH_API}/repos/{source}/actions/runs/{run_id}"
    )
    validate_run(run, validated)
    selected = find_required_artifacts(
        lambda url: _api_request(token, url),
        validated["source_repository"],
        run_id,
        now=now,
    )
    evidence_bytes = _download_artifact(
        token,
        selected[EVIDENCE_ARTIFACT]["archive_download_url"],
        MAX_EVIDENCE_ARCHIVE_BYTES,
        "evidence",
    )
    read_and_validate_evidence_archive(evidence_bytes, validated)
    package_bytes = _download_artifact(
        token,
        selected[PACKAGE_ARTIFACT]["archive_download_url"],
        MAX_PACKAGE_ARCHIVE_BYTES,
        "package",
    )
    read_and_validate_package_archive(package_bytes, validated)
    return build_dispatch_payload(validated)


def _write_github_output(path, payload):
    rendered = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    with Path(path).open("a", encoding="ascii") as output:
        output.write(f"client_payload={rendered}\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repository", required=True)
    parser.add_argument("--actual-source-repository", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--validation-run-id", required=True, type=int)
    parser.add_argument("--validation-workflow", required=True)
    parser.add_argument("--validation-workflow-path", required=True)
    parser.add_argument("--expected-branch", required=True)
    parser.add_argument("--addon-id", required=True)
    parser.add_argument("--addon-version", required=True)
    parser.add_argument("--asset-name", required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--publication-id", required=True)
    parser.add_argument("--github-output", required=True, type=Path)
    args = parser.parse_args(argv)
    values = {
        "source_repository": args.source_repository,
        "candidate_sha": args.candidate_sha,
        "validation_run_id": args.validation_run_id,
        "validation_workflow": args.validation_workflow,
        "validation_workflow_path": args.validation_workflow_path,
        "expected_branch": args.expected_branch,
        "addon_id": args.addon_id,
        "addon_version": args.addon_version,
        "asset_name": args.asset_name,
        "artifact_sha256": args.artifact_sha256,
        "publication_id": args.publication_id,
    }
    try:
        payload = prepare_dispatch(
            values,
            args.actual_source_repository,
            os.environ.get("GITHUB_TOKEN", ""),
        )
        _write_github_output(args.github_output, payload)
    except NotificationError as error:
        parser.error(str(error))
    print("Validated immutable publication evidence for metadata-only dispatch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
