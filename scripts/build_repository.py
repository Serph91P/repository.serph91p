#!/usr/bin/env python3
"""Build and validate the Serph91P Kodi repository."""

import argparse
import hashlib
import json
import os
import re
import shutil
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit


ADDONS = [
    {
        "owner": "Serph91P",
        "repo": "plugin.video.gronkhtv",
        "addon_id": "plugin.video.gronkhtv",
        "branch": "main",
    },
    {
        "owner": "Serph91P",
        "repo": "plugin.video.twitch",
        "addon_id": "plugin.video.twitch",
        "branch": "main",
    },
    {
        "owner": "Serph91P",
        "repo": "script.module.python.twitch",
        "addon_id": "script.module.python.twitch",
        "branch": "main",
    },
    {
        "owner": "Serph91P",
        "repo": "PlexKodiConnect",
        "addon_id": "plugin.video.plexkodiconnect",
        "branch": "main",
    },
    {
        "owner": "Serph91P",
        "repo": "plugin.video.plexkodiconnect.movies",
        "addon_id": "plugin.video.plexkodiconnect.movies",
        "branch": "main",
    },
    {
        "owner": "Serph91P",
        "repo": "plugin.video.plexkodiconnect.tvshows",
        "addon_id": "plugin.video.plexkodiconnect.tvshows",
        "branch": "main",
    },
    {
        "owner": "Serph91P",
        "repo": "script.tubecast",
        "addon_id": "script.tubecast",
        "branch": "main",
    },
]

def _parse_kodi_version(version_string):
    """Parse a dotted numeric addon version into a comparable tuple of ints.

    Fails closed if the string is empty or any segment is not a non-negative
    integer.
    """
    if not version_string or not isinstance(version_string, str):
        raise RuntimeError(f"Invalid addon version: {version_string!r}")
    parts = version_string.split(".")
    parsed = []
    for part in parts:
        if not part or not part.isdigit():
            raise RuntimeError(f"Invalid addon version segment in {version_string!r}")
        parsed.append(int(part))
    if not parsed:
        raise RuntimeError(f"Invalid addon version: {version_string!r}")
    return tuple(parsed)


def _check_version_monotonicity(repo_root, addon_id, candidate_version):
    """Reject a candidate version lower than the currently published version.

    Reads the existing repo addons.xml, finds the current version for addon_id,
    and ensures candidate >= current. Equal versions are permitted because
    rerunning an immutable candidate may be needed. Fails closed if the
    manifest is missing, unparseable, or the existing version is invalid.
    """
    manifest_path = repo_root / "repo" / "addons.xml"
    if not manifest_path.is_file():
        return
    try:
        root = ET.parse(manifest_path).getroot()
    except (OSError, ET.ParseError) as error:
        raise RuntimeError(
            f"Cannot parse existing manifest {manifest_path} for version check: "
            f"{error}"
        ) from error
    if root.tag != "addons":
        raise RuntimeError(
            f"Existing manifest {manifest_path} has unexpected root {root.tag!r}"
        )
    for addon in root.findall("addon"):
        if addon.get("id") == addon_id:
            current_version = addon.get("version")
            if not current_version:
                raise RuntimeError(
                    f"Existing addon {addon_id} in {manifest_path} has no version"
                )
            candidate_tuple = _parse_kodi_version(candidate_version)
            current_tuple = _parse_kodi_version(current_version)
            if candidate_tuple < current_tuple:
                raise RuntimeError(
                    f"Rejecting {addon_id} version {candidate_version}: "
                    f"currently published version {current_version} is newer"
                )
            return


REPO_ADDON_ID = "repository.serph91p"
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
REPO_OUTPUT = REPO_ROOT / "repo"
SITE_OUTPUT = REPO_ROOT / "_site"
TEMP_DIR = REPO_ROOT / "_temp"
GH_API = "https://api.github.com"
NO_RELEASE = object()


def github_api_get(url):
    """Make an authenticated GitHub API request if a token is available."""
    request = urllib.request.Request(url)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"token {token}")
    request.add_header("Accept", "application/vnd.github.v3+json")
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def download_file(url, destination):
    """Download a file to a new local destination."""
    request = urllib.request.Request(url)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"token {token}")
    with urllib.request.urlopen(request) as response, open(destination, "wb") as output:
        shutil.copyfileobj(response, output)


def get_source_token():
    """Return the source-artifact token or raise before any source request."""
    token = (os.environ.get("SOURCE_GITHUB_TOKEN") or "").strip()
    if not token:
        raise RuntimeError(
            "SOURCE_GITHUB_TOKEN is required for cross-repository source access "
            "but is missing or empty"
        )
    return token


def source_github_api_get(url):
    """Make a GitHub API request using the source-artifact credential."""
    token = get_source_token()
    request = urllib.request.Request(url)
    request.add_header("Authorization", f"token {token}")
    request.add_header("Accept", "application/vnd.github.v3+json")
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise RuntimeError(
                f"Source authorization rejected (HTTP {error.code}). "
                f"Verify SOURCE_ARTIFACT_TOKEN grants access to the source repository"
            ) from error
        raise


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Strip Authorization on cross-origin redirects."""

    _DEFAULT_PORTS = {"http": 80, "https": 443}

    def _effective_origin(self, parsed):
        port = parsed.port
        if port is None:
            port = self._DEFAULT_PORTS.get(parsed.scheme.lower())
        return (parsed.scheme.lower(), parsed.hostname, port)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        orig_parts = urlsplit(req.full_url)
        orig_origin = self._effective_origin(orig_parts)
        new_origin = self._effective_origin(urlsplit(newurl))
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and new_origin != orig_origin:
            redirected.remove_header("Authorization")
        return redirected


_source_opener = urllib.request.build_opener(_SafeRedirectHandler)


def source_download_file(url, destination):
    """Download a file using the source-artifact credential."""
    token = get_source_token()
    request = urllib.request.Request(url)
    request.add_header("Authorization", f"token {token}")
    try:
        with (
            _source_opener.open(request) as response,
            open(destination, "wb") as output,
        ):
            shutil.copyfileobj(response, output)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise RuntimeError(
                f"Source authorization rejected (HTTP {error.code}). "
                f"Verify SOURCE_ARTIFACT_TOKEN grants access to the source repository"
            ) from error
        raise


def get_latest_release_zip(owner, repo, addon_id):
    """Return the one correctly named ZIP attached to the latest release."""
    releases_url = f"{GH_API}/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
    try:
        data = github_api_get(f"{releases_url}/releases/latest")
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        releases = github_api_get(f"{releases_url}/releases")
        if not isinstance(releases, list):
            raise RuntimeError(
                f"Malformed release list after missing latest release for {owner}/{repo}"
            ) from error
        if releases:
            raise RuntimeError(
                f"Release list is not empty after missing latest release for {owner}/{repo}"
            ) from error
        return NO_RELEASE
    tag = data.get("tag_name")
    if not tag:
        raise RuntimeError(f"Latest release for {owner}/{repo} has no tag")
    version = tag[1:] if tag.startswith("v") else tag
    _validated_filename_component(addon_id, "addon ID")
    _validated_filename_component(version, "release version")
    expected_name = f"{addon_id}-{version}.zip"
    matches = [
        asset for asset in data.get("assets", []) if asset.get("name") == expected_name
    ]
    if len(matches) != 1:
        zip_names = sorted(
            asset.get("name", "")
            for asset in data.get("assets", [])
            if asset.get("name", "").lower().endswith(".zip")
        )
        raise RuntimeError(
            f"Release {tag} for {owner}/{repo} must contain exactly one "
            f"{expected_name}; found ZIP assets: {zip_names}"
        )
    return matches[0]["browser_download_url"], version, expected_name


def _source_archive_url(owner, repo, branch):
    return (
        f"{GH_API}/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
        f"/zipball/{quote(branch, safe='')}"
    )


def _validated_relative_path(value, description):
    """Validate a ZIP-style path that must remain below an addon directory."""
    if not value or "\\" in value or value.startswith("/"):
        raise RuntimeError(f"Unsafe {description}: {value!r}")
    if re.match(r"^[A-Za-z]:", value):
        raise RuntimeError(f"Unsafe {description}: {value!r}")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise RuntimeError(f"Unsafe {description}: {value!r}")
    return PurePosixPath(*parts)


def _validated_filename_component(value, description):
    """Reject values that could escape a generated directory or filename."""
    if (
        not value
        or value in (".", "..")
        or "/" in value
        or "\\" in value
        or "\0" in value
    ):
        raise RuntimeError(f"Unsafe {description}: {value!r}")
    return value


def _local_asset_paths(addon):
    """Return validated local paths referenced by Kodi metadata assets."""
    paths = []
    for asset in addon.findall(".//assets/*"):
        value = (asset.text or "").strip()
        if not value:
            raise RuntimeError("Addon metadata contains an empty asset reference")
        parsed = urlsplit(value)
        if parsed.scheme.lower() in ("http", "https"):
            continue
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise RuntimeError(f"Unsupported asset reference: {value!r}")
        paths.append(_validated_relative_path(value, "local asset path"))
    return paths


def _validated_archive(archive, addon_id, release_version, release_filename):
    """Validate package identity and return its metadata plus local asset members."""
    expected_filename = f"{addon_id}-{release_version}.zip"
    if release_filename != expected_filename:
        raise RuntimeError(
            f"Release filename {release_filename!r} does not match {expected_filename!r}"
        )

    members = {}
    canonical_names = set()
    addon_xml_members = []
    for info in archive.infolist():
        name = info.filename
        relative_name = name[:-1] if info.is_dir() and name.endswith("/") else name
        path = _validated_relative_path(relative_name, "archive member")
        file_type = (info.external_attr >> 16) & 0o170000
        expected_types = (0, 0o040000) if info.is_dir() else (0, 0o100000)
        if file_type not in expected_types:
            raise RuntimeError(f"Unsupported release archive member type: {name!r}")
        if path.parts[0] != addon_id:
            raise RuntimeError(f"Archive member has wrong root: {name!r}")
        canonical_name = relative_name.casefold()
        if canonical_name in canonical_names:
            raise RuntimeError(f"Duplicate archive member: {name!r}")
        canonical_names.add(canonical_name)
        members[relative_name] = info
        if path.name.casefold() == "addon.xml":
            addon_xml_members.append(relative_name)

    expected_xml = f"{addon_id}/addon.xml"
    if addon_xml_members != [expected_xml]:
        raise RuntimeError(
            f"Archive must contain exactly one root {expected_xml}; found {addon_xml_members}"
        )
    try:
        addon = ET.fromstring(archive.read(members[expected_xml]))
    except ET.ParseError as error:
        raise RuntimeError(f"Invalid {expected_xml}: {error}") from error
    if addon.tag != "addon":
        raise RuntimeError(f"Root element in {expected_xml} must be 'addon'")
    embedded_id = addon.get("id")
    embedded_version = addon.get("version")
    if embedded_id != addon_id:
        raise RuntimeError(
            f"Configured addon ID {addon_id!r} does not match embedded ID {embedded_id!r}"
        )
    if embedded_version != release_version:
        raise RuntimeError(
            f"Release version {release_version!r} does not match embedded version "
            f"{embedded_version!r}"
        )

    assets = []
    for relative_asset in _local_asset_paths(addon):
        member_name = f"{addon_id}/{relative_asset.as_posix()}"
        info = members.get(member_name)
        if info is None or info.is_dir():
            raise RuntimeError(
                f"Package is missing local asset {relative_asset.as_posix()!r}"
            )
        if relative_asset.as_posix() == release_filename:
            raise RuntimeError(
                f"Local asset collides with release ZIP: {release_filename!r}"
            )
        assets.append((relative_asset, info))
    return addon, assets


def _validated_source_members(archive, addon_id):
    """Validate a GitHub source ZIP and return its embedded identity and files."""
    roots = set()
    canonical_names = set()
    addon_xml_members = []
    files = []
    members = {}
    for info in archive.infolist():
        name = info.filename
        relative_name = name[:-1] if info.is_dir() and name.endswith("/") else name
        path = _validated_relative_path(relative_name, "source archive member")
        roots.add(path.parts[0])
        canonical_name = relative_name.casefold()
        if canonical_name in canonical_names:
            raise RuntimeError(f"Duplicate source archive member: {name!r}")
        canonical_names.add(canonical_name)
        file_type = (info.external_attr >> 16) & 0o170000
        expected_types = (0, 0o040000) if info.is_dir() else (0, 0o100000)
        if file_type not in expected_types:
            raise RuntimeError(f"Unsupported source archive member type: {name!r}")
        if len(path.parts) == 1:
            if not info.is_dir():
                raise RuntimeError(f"Source archive root must be a directory: {name!r}")
            continue
        if info.is_dir():
            continue
        relative_path = PurePosixPath(*path.parts[1:])
        files.append((relative_path, info))
        members[relative_name] = info
        if relative_path.name.casefold() == "addon.xml":
            addon_xml_members.append(relative_name)

    if len(roots) != 1:
        raise RuntimeError(
            f"Source archive must contain exactly one root; found {sorted(roots)}"
        )
    root = next(iter(roots))
    expected_xml = f"{root}/addon.xml"
    if addon_xml_members != [expected_xml]:
        raise RuntimeError(
            f"Source archive must contain exactly one root addon.xml; "
            f"found {addon_xml_members}"
        )
    try:
        addon = ET.fromstring(archive.read(members[expected_xml]))
    except ET.ParseError as error:
        raise RuntimeError(f"Invalid source addon.xml: {error}") from error
    if addon.tag != "addon":
        raise RuntimeError("Root element in source addon.xml must be 'addon'")
    embedded_id = addon.get("id")
    embedded_version = addon.get("version")
    _validated_filename_component(embedded_id, "embedded addon ID")
    _validated_filename_component(embedded_version, "embedded addon version")
    if embedded_id != addon_id:
        raise RuntimeError(
            f"Configured addon ID {addon_id!r} does not match embedded ID {embedded_id!r}"
        )
    return embedded_id, embedded_version, files


def create_source_package(source_zip, addon_id, destination):
    """Securely repackage a GitHub source archive as a Kodi addon ZIP."""
    _validated_filename_component(addon_id, "addon ID")
    try:
        with zipfile.ZipFile(source_zip, "r") as source:
            embedded_id, embedded_version, files = _validated_source_members(
                source, addon_id
            )
            filename = f"{embedded_id}-{embedded_version}.zip"
            package = destination / filename
            with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as output:
                for relative_path, info in files:
                    output.writestr(
                        f"{embedded_id}/{relative_path.as_posix()}", source.read(info)
                    )
    except zipfile.BadZipFile as error:
        raise RuntimeError(f"Invalid source ZIP: {error}") from error
    return package, embedded_version, filename


def publish_release_zip(
    zip_path, addon_id, release_version, release_filename, repository_output
):
    """Validate and publish one release without renaming or sourcing branch files."""
    _validated_filename_component(addon_id, "addon ID")
    _validated_filename_component(release_version, "release version")
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            addon, assets = _validated_archive(
                archive, addon_id, release_version, release_filename
            )
            for info in archive.infolist():
                if not info.is_dir():
                    archive.read(info)
            addon_dir = repository_output / addon_id
            addon_dir.mkdir(parents=True, exist_ok=False)
            shutil.copy2(zip_path, addon_dir / release_filename)
            for relative_asset, info in assets:
                destination = addon_dir.joinpath(*relative_asset.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, open(destination, "wb") as output:
                    shutil.copyfileobj(source, output)
    except zipfile.BadZipFile as error:
        raise RuntimeError(
            f"Invalid release ZIP {release_filename!r}: {error}"
        ) from error
    return addon


def _write_addons_xml(addons, destination):
    root = ET.Element("addons")
    for addon in addons:
        root.append(addon)
    ET.indent(root, space="    ")
    content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    destination.write_bytes(content + b"\n")
    return content + b"\n"


def _write_directory_listing(directory):
    links = []
    for child in sorted(directory.iterdir(), key=lambda item: item.name):
        if child.name == "index.html":
            continue
        suffix = "/" if child.is_dir() else ""
        links.append(f'<a href="{child.name}{suffix}">{child.name}{suffix}</a><br/>')
    content = "<html><body>\n" + "\n".join(links) + "\n</body></html>\n"
    (directory / "index.html").write_text(content, encoding="utf-8")


def create_pages_site(repository_output=REPO_OUTPUT, site_output=SITE_OUTPUT):
    """Create the flat Pages tree and Kodi-parseable directory listings."""
    if site_output.exists():
        shutil.rmtree(site_output)
    site_output.mkdir(parents=True)
    for child in sorted(repository_output.iterdir(), key=lambda item: item.name):
        destination = site_output / child.name
        if child.is_dir():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)

    repository_packages = sorted((site_output / REPO_ADDON_ID).glob("*.zip"))
    if len(repository_packages) != 1:
        raise RuntimeError("Site must contain exactly one repository addon package")
    shutil.copy2(repository_packages[0], site_output / repository_packages[0].name)

    directories = sorted(
        (path for path in site_output.rglob("*") if path.is_dir()),
        key=lambda path: (len(path.parts), path.as_posix()),
        reverse=True,
    )
    for directory in directories:
        _write_directory_listing(directory)
    _write_directory_listing(site_output)


def validate_site_manifest(site_output=SITE_OUTPUT):
    """Prove every package and local asset advertised by addons.xml exists."""
    manifest_path = site_output / "addons.xml"
    try:
        root = ET.parse(manifest_path).getroot()
    except (OSError, ET.ParseError) as error:
        raise RuntimeError(
            f"Invalid generated manifest {manifest_path}: {error}"
        ) from error
    if root.tag != "addons":
        raise RuntimeError(f"Generated manifest has unexpected root {root.tag!r}")

    addon_ids = []
    for addon in root.findall("addon"):
        addon_id = addon.get("id")
        version = addon.get("version")
        if not addon_id or not version:
            raise RuntimeError("Generated manifest addon is missing id or version")
        _validated_filename_component(addon_id, "manifest addon ID")
        _validated_filename_component(version, "manifest addon version")
        if addon_id in addon_ids:
            raise RuntimeError(
                f"Generated manifest contains duplicate addon {addon_id!r}"
            )
        addon_ids.append(addon_id)
        package = site_output / addon_id / f"{addon_id}-{version}.zip"
        if not package.is_file():
            raise RuntimeError(
                f"Generated site is missing advertised package {package}"
            )
        for asset in _local_asset_paths(addon):
            asset_path = site_output / addon_id
            asset_path = asset_path.joinpath(*asset.parts)
            if not asset_path.is_file():
                raise RuntimeError(
                    f"Generated site is missing advertised asset {asset_path}"
                )

    required_addons = {config["addon_id"] for config in ADDONS}
    required_addons.add(REPO_ADDON_ID)
    missing_coverage = required_addons.difference(addon_ids)
    if missing_coverage:
        raise RuntimeError(
            f"Generated manifest is missing required addons: {sorted(missing_coverage)}"
        )

    checksum_path = site_output / "addons.xml.md5"
    if not checksum_path.is_file():
        raise RuntimeError(f"Generated site is missing checksum {checksum_path}")
    expected_checksum = hashlib.md5(manifest_path.read_bytes()).hexdigest()
    if checksum_path.read_text(encoding="utf-8") != expected_checksum:
        raise RuntimeError("Generated addons.xml.md5 does not match addons.xml")


def _create_repository_package_in(repo_root, temp_dir):
    """Create the repository addon package, parameterized for test isolation."""
    addon_xml_path = repo_root / "addon.xml"
    if not addon_xml_path.is_file():
        raise RuntimeError(f"Missing repository metadata: {addon_xml_path}")
    try:
        root = ET.parse(addon_xml_path).getroot()
    except ET.ParseError as error:
        raise RuntimeError(f"Invalid repository metadata: {error}") from error
    if root.get("id") != REPO_ADDON_ID or not root.get("version"):
        raise RuntimeError("Repository addon.xml has an invalid id or version")
    version = root.get("version")
    package_dir = temp_dir / REPO_ADDON_ID
    package_dir.mkdir(parents=True, exist_ok=True)
    package_path = package_dir / f"{REPO_ADDON_ID}-{version}.zip"
    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(addon_xml_path, f"{REPO_ADDON_ID}/addon.xml")
        resources_dir = repo_root / "resources"
        if resources_dir.exists():
            for item in sorted(resources_dir.rglob("*")):
                if item.is_file():
                    archive.write(
                        item, f"{REPO_ADDON_ID}/{item.relative_to(repo_root)}"
                    )
    return package_path, version


def _create_repository_package():
    return _create_repository_package_in(REPO_ROOT, TEMP_DIR)


def validate_dispatch_payload(payload):
    """Validate the shape and types of a repository dispatch payload."""
    if not isinstance(payload, dict):
        raise RuntimeError("Dispatch payload must be a JSON object")
    allowed_fields = {
        "source_repo",
        "candidate_sha",
        "validation_run_id",
        "validation_head_sha",
        "validation_workflow",
        "expected_branch",
        "package_artifact_name",
        "evidence_artifact_name",
    }
    unknown = set(payload.keys()) - allowed_fields
    if unknown:
        raise RuntimeError(
            f"Dispatch payload contains unknown fields: {sorted(unknown)}"
        )
    source_repo = payload.get("source_repo")
    if not source_repo or not isinstance(source_repo, str) or "/" not in source_repo:
        raise RuntimeError(
            "Dispatch payload must contain a valid source_repo (owner/repo)"
        )
    candidate_sha = payload.get("candidate_sha")
    if (
        not candidate_sha
        or not isinstance(candidate_sha, str)
        or len(candidate_sha) != 40
    ):
        raise RuntimeError(
            f"Dispatch candidate_sha must be a 40-character hex SHA: {candidate_sha!r}"
        )
    if not all(c in "0123456789abcdef" for c in candidate_sha):
        raise RuntimeError(f"Dispatch candidate_sha must be hex: {candidate_sha!r}")
    validation_run_id = payload.get("validation_run_id")
    if not isinstance(validation_run_id, int) or validation_run_id <= 0:
        raise RuntimeError(
            f"Dispatch validation_run_id must be a positive integer: "
            f"{validation_run_id!r}"
        )
    validation_head_sha = payload.get("validation_head_sha")
    if (
        not validation_head_sha
        or not isinstance(validation_head_sha, str)
        or len(validation_head_sha) != 40
    ):
        raise RuntimeError(
            f"Dispatch validation_head_sha must be a 40-character hex SHA: "
            f"{validation_head_sha!r}"
        )
    if not all(c in "0123456789abcdef" for c in validation_head_sha):
        raise RuntimeError(
            f"Dispatch validation_head_sha must be hex: {validation_head_sha!r}"
        )
    validation_workflow = payload.get("validation_workflow")
    if not validation_workflow or not isinstance(validation_workflow, str):
        raise RuntimeError("Dispatch validation_workflow must be a non-empty string")
    expected_branch = payload.get("expected_branch")
    if not expected_branch or not isinstance(expected_branch, str):
        raise RuntimeError("Dispatch expected_branch must be a non-empty string")


def validate_immutable_evidence(
    evidence, candidate_sha, validation_run_id, validation_head_sha
):
    """Validate evidence JSON against the immutable publication contract."""
    if not isinstance(evidence, dict):
        raise RuntimeError("Validation evidence must be a JSON object")
    required_fields = (
        "candidate_sha",
        "validation_head_sha",
        "validation_run_id",
        "addon_id",
        "addon_version",
        "publication_id",
        "artifact_sha256",
        "asset_name",
    )
    for field in required_fields:
        if field not in evidence:
            raise RuntimeError(
                f"Validation evidence is missing required field: {field}"
            )
    evidence_run_id = evidence["validation_run_id"]
    try:
        evidence_run_id = int(evidence_run_id)
    except (TypeError, ValueError):
        raise RuntimeError(
            f"Evidence validation_run_id {evidence_run_id!r} is not a valid integer"
        )
    if evidence_run_id != int(validation_run_id):
        raise RuntimeError(
            f"Evidence validation_run_id {evidence_run_id} does not "
            f"match dispatch validation_run_id {int(validation_run_id)}"
        )
    if evidence["candidate_sha"] != candidate_sha:
        raise RuntimeError(
            f"Evidence candidate_sha {evidence['candidate_sha']!r} does not match "
            f"dispatch candidate_sha {candidate_sha!r}"
        )
    if evidence["validation_head_sha"] != validation_head_sha:
        raise RuntimeError(
            f"Evidence validation_head_sha {evidence['validation_head_sha']!r} "
            f"does not match dispatch validation_head_sha {validation_head_sha!r}"
        )
    candidate = evidence["candidate_sha"]
    if (
        not isinstance(candidate, str)
        or len(candidate) != 40
        or not all(c in "0123456789abcdef" for c in candidate)
    ):
        raise RuntimeError(
            f"candidate_sha must be a 40-character hex SHA: {candidate!r}"
        )
    addon_id = evidence["addon_id"]
    addon_version = evidence["addon_version"]
    if not addon_id or not isinstance(addon_id, str):
        raise RuntimeError("Evidence addon_id must be a non-empty string")
    if not addon_version or not isinstance(addon_version, str):
        raise RuntimeError("Evidence addon_version must be a non-empty string")
    expected_pub = f"{addon_id}@{addon_version}"
    if evidence["publication_id"] != expected_pub:
        raise RuntimeError(
            f"Evidence publication_id {evidence['publication_id']!r} does not match "
            f"expected {expected_pub!r}"
        )


def validate_github_run(
    run_data,
    validation_run_id,
    validation_head_sha,
    validation_workflow,
    expected_branch,
):
    """Validate a GitHub Actions run response against dispatch fields."""
    if not isinstance(run_data, dict):
        raise RuntimeError("GitHub run data must be a JSON object")
    if run_data.get("id") != int(validation_run_id):
        raise RuntimeError(
            f"Run ID {run_data.get('id')!r} does not match dispatch "
            f"validation_run_id {int(validation_run_id)!r}"
        )
    if run_data.get("head_sha") != validation_head_sha:
        raise RuntimeError(
            f"Run head_sha {run_data.get('head_sha')!r} does not match dispatch "
            f"validation_head_sha {validation_head_sha!r}"
        )
    if run_data.get("name") != validation_workflow:
        raise RuntimeError(
            f"Run workflow name {run_data.get('name')!r} does not match dispatch "
            f"validation_workflow {validation_workflow!r}"
        )
    if run_data.get("head_branch") != expected_branch:
        raise RuntimeError(
            f"Run head_branch {run_data.get('head_branch')!r} does not match "
            f"dispatch expected_branch {expected_branch!r}"
        )
    if run_data.get("conclusion") != "success":
        raise RuntimeError(
            f"Run conclusion {run_data.get('conclusion')!r} is not 'success'"
        )


def verify_package_sha256(zip_path, expected_sha256):
    """Verify that a downloaded ZIP matches the expected SHA-256."""
    actual = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    if actual != expected_sha256:
        raise RuntimeError(
            f"Package SHA-256 {actual!r} does not match expected {expected_sha256!r}"
        )


def validate_archive_topology(zip_path, addon_id, addon_version):
    """Validate archive member structure, addon.xml identity, and compression type."""
    _validated_filename_component(addon_id, "addon ID")
    _validated_filename_component(addon_version, "addon version")
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            addon_xml_path = None
            canonical_names = set()
            for info in archive.infolist():
                name = info.filename
                relative_name = (
                    name[:-1] if info.is_dir() and name.endswith("/") else name
                )
                path = _validated_relative_path(relative_name, "archive member")
                file_type = (info.external_attr >> 16) & 0o170000
                expected_types = (0, 0o040000) if info.is_dir() else (0, 0o100000)
                if file_type not in expected_types:
                    raise RuntimeError(
                        f"Unsupported release archive member type: {name!r}"
                    )
                if path.parts[0] != addon_id:
                    raise RuntimeError(f"Archive member has wrong root: {name!r}")
                canonical_name = relative_name.casefold()
                if canonical_name in canonical_names:
                    raise RuntimeError(f"Duplicate archive member: {name!r}")
                canonical_names.add(canonical_name)
                if not info.is_dir() and info.compress_type != zipfile.ZIP_DEFLATED:
                    raise RuntimeError(
                        f"Archive member {name!r} uses compression type "
                        f"{info.compress_type}, expected deflate (8)"
                    )
                if path.name.casefold() == "addon.xml" and len(path.parts) == 2:
                    addon_xml_path = relative_name
            if addon_xml_path is None:
                raise RuntimeError(f"Archive is missing root {addon_id}/addon.xml")
            try:
                addon = ET.fromstring(archive.read(addon_xml_path))
            except ET.ParseError as error:
                raise RuntimeError(f"Invalid {addon_xml_path}: {error}") from error
            if addon.tag != "addon":
                raise RuntimeError(f"Root element in {addon_xml_path} must be 'addon'")
            embedded_id = addon.get("id")
            embedded_version = addon.get("version")
            if embedded_id != addon_id:
                raise RuntimeError(
                    f"Evidence addon_id {addon_id!r} does not match embedded ID "
                    f"{embedded_id!r}"
                )
            if embedded_version != addon_version:
                raise RuntimeError(
                    f"Evidence addon_version {addon_version!r} does not match "
                    f"embedded version {embedded_version!r}"
                )
            for info in archive.infolist():
                if not info.is_dir():
                    archive.read(info)
    except zipfile.BadZipFile as error:
        raise RuntimeError(f"Invalid ZIP archive: {error}") from error


def publish_validated_addon(addon_zip_path, asset_name, repository_output):
    """Copy a validated addon ZIP and return its parsed addon element."""
    _validated_filename_component(asset_name, "asset name")
    with zipfile.ZipFile(addon_zip_path, "r") as archive:
        addon_id = None
        addon_xml_path = None
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename
            parts = name.rstrip("/").split("/")
            if len(parts) == 2 and parts[1].lower() == "addon.xml":
                if addon_xml_path is not None:
                    raise RuntimeError("Multiple root addon.xml files found")
                addon_xml_path = name
                addon_id = parts[0]
        if addon_xml_path is None:
            raise RuntimeError("Addon ZIP is missing root addon.xml")
        try:
            addon = ET.fromstring(archive.read(addon_xml_path))
        except ET.ParseError as error:
            raise RuntimeError(f"Invalid {addon_xml_path}: {error}") from error
        addon_dir = repository_output / addon_id
        addon_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(addon_zip_path, addon_dir / asset_name)
        for relative_asset in _local_asset_paths(addon):
            member_name = f"{addon_id}/{relative_asset.as_posix()}"
            for info in archive.infolist():
                if info.filename == member_name and not info.is_dir():
                    destination = addon_dir.joinpath(*relative_asset.parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with (
                        archive.open(info) as source,
                        open(destination, "wb") as output,
                    ):
                        shutil.copyfileobj(source, output)
                    break
            else:
                raise RuntimeError(
                    f"Addon ZIP is missing local asset {relative_asset.as_posix()!r}"
                )
    return addon


def promote_repository_outputs(staging, repo_output, site_output):
    """Promote staged outputs and restore both previous trees on failure."""
    outputs = (
        (staging / "repo", repo_output, staging / "_previous_repo"),
        (staging / "_site", site_output, staging / "_previous_site"),
    )
    backed_up = []
    promoted = []
    try:
        for _source, destination, backup in outputs:
            if destination.exists():
                os.replace(destination, backup)
                backed_up.append((destination, backup))
        for source, destination, _backup in outputs:
            os.replace(source, destination)
            promoted.append(destination)
    except BaseException:
        for destination in reversed(promoted):
            if destination.exists():
                shutil.rmtree(destination)
        for destination, backup in reversed(backed_up):
            if backup.exists():
                os.replace(backup, destination)
        raise
    for _destination, backup in backed_up:
        if backup.exists():
            shutil.rmtree(backup)


def build_immutable_repository(dispatch_payload, repo_root=None):
    """Build the repository from an immutable validated dispatch payload."""
    if repo_root is None:
        repo_root = REPO_ROOT
    print("=" * 60)
    print("Building Serph91P Kodi Repository (immutable)")
    print("=" * 60)

    validate_dispatch_payload(dispatch_payload)
    get_source_token()

    source_repo = dispatch_payload["source_repo"]
    candidate_sha = dispatch_payload["candidate_sha"]
    validation_run_id = dispatch_payload["validation_run_id"]
    validation_head_sha = dispatch_payload["validation_head_sha"]
    validation_workflow = dispatch_payload["validation_workflow"]
    expected_branch = dispatch_payload["expected_branch"]
    package_artifact_name = dispatch_payload.get(
        "package_artifact_name", "addon-package"
    )
    evidence_artifact_name = dispatch_payload.get(
        "evidence_artifact_name", "validation-evidence"
    )

    source_config = None
    for config in ADDONS:
        config_repo = f"{config['owner']}/{config['repo']}"
        if config_repo == source_repo:
            source_config = config
            break
    if source_config is None:
        raise RuntimeError(
            f"source_repo {source_repo!r} is not in the configured ADDONS list"
        )
    run_data = source_github_api_get(
        f"{GH_API}/repos/{quote(source_repo, safe='/')}/actions/runs/"
        f"{validation_run_id}"
    )
    validate_github_run(
        run_data,
        validation_run_id,
        validation_head_sha,
        validation_workflow,
        expected_branch,
    )
    source_ref_url = (
        f"{GH_API}/repos/{quote(source_repo, safe='/')}/git/ref/heads/"
        f"{quote(expected_branch, safe='')}"
    )
    source_ref = source_github_api_get(source_ref_url)
    current_sha = source_ref.get("object", {}).get("sha")
    if current_sha != candidate_sha:
        raise RuntimeError(
            f"Expected branch {expected_branch!r} moved: current SHA "
            f"{current_sha!r} does not match candidate_sha {candidate_sha!r}"
        )

    artifacts_data = source_github_api_get(
        f"{GH_API}/repos/{quote(source_repo, safe='/')}/actions/runs/"
        f"{validation_run_id}/artifacts"
    )
    evidence_artifacts = [
        a
        for a in artifacts_data.get("artifacts", [])
        if a.get("name") == evidence_artifact_name
    ]
    package_artifacts = [
        a
        for a in artifacts_data.get("artifacts", [])
        if a.get("name") == package_artifact_name
    ]
    if len(evidence_artifacts) != 1:
        raise RuntimeError(
            f"Expected exactly one '{evidence_artifact_name}' artifact, "
            f"found {len(evidence_artifacts)}"
        )
    if len(package_artifacts) != 1:
        raise RuntimeError(
            f"Expected exactly one '{package_artifact_name}' artifact, "
            f"found {len(package_artifacts)}"
        )
    evidence_artifact = evidence_artifacts[0]
    package_artifact = package_artifacts[0]
    if evidence_artifact.get("expired", False):
        raise RuntimeError("Evidence artifact has expired")
    if package_artifact.get("expired", False):
        raise RuntimeError("Package artifact has expired")

    temp_dir = repo_root / "_temp"
    staging = repo_root / "_staging"
    staging_repo = staging / "repo"
    staging_site = staging / "_site"

    for path in (staging, staging_repo, staging_site):
        if path.exists():
            shutil.rmtree(path)

    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
        staging_repo.mkdir(parents=True)
        staging_site.mkdir(parents=True)

        evidence_archive = temp_dir / "evidence.zip"
        package_archive = temp_dir / "package.zip"

        source_download_file(
            evidence_artifact["archive_download_url"], evidence_archive
        )
        source_download_file(package_artifact["archive_download_url"], package_archive)

        with zipfile.ZipFile(evidence_archive, "r") as zf:
            evidence_members = [m for m in zf.namelist() if not m.endswith("/")]
            if evidence_members != ["validation-evidence.json"]:
                raise RuntimeError(
                    f"Evidence archive must contain exactly "
                    f"'validation-evidence.json', found: {evidence_members}"
                )
            evidence = json.loads(zf.read("validation-evidence.json"))

        validate_immutable_evidence(
            evidence, candidate_sha, validation_run_id, validation_head_sha
        )

        addon_id = evidence["addon_id"]
        addon_version = evidence["addon_version"]
        asset_name = evidence["asset_name"]
        expected_filename = f"{addon_id}-{addon_version}.zip"
        if asset_name != expected_filename:
            raise RuntimeError(
                f"Evidence asset_name {asset_name!r} does not match "
                f"expected {expected_filename!r}"
            )
        if addon_id != source_config["addon_id"]:
            raise RuntimeError(
                f"Evidence addon_id {addon_id!r} does not match configured addon "
                f"{source_config['addon_id']!r} for {source_repo}"
            )
        if candidate_sha != run_data.get("head_sha"):
            raise RuntimeError(
                f"candidate_sha {candidate_sha!r} does not match "
                f"run head_sha {run_data.get('head_sha')!r}"
            )

        _check_version_monotonicity(repo_root, addon_id, addon_version)

        with zipfile.ZipFile(package_archive, "r") as zf:
            package_members = [m for m in zf.namelist() if not m.endswith("/")]
            if package_members != [asset_name]:
                raise RuntimeError(
                    f"Package archive must contain exactly {asset_name!r}, "
                    f"found: {package_members}"
                )
            addon_zip_path = temp_dir / asset_name
            with zf.open(asset_name) as src, open(addon_zip_path, "wb") as dst:
                shutil.copyfileobj(src, dst)

        verify_package_sha256(addon_zip_path, evidence["artifact_sha256"])
        validate_archive_topology(addon_zip_path, addon_id, addon_version)

        published = []
        try:
            addon = publish_validated_addon(addon_zip_path, asset_name, staging_repo)
            published.append(addon)
            print(f"  Validated: {addon_id} v{addon_version}")

            for config in ADDONS:
                if config["addon_id"] == addon_id:
                    continue
                owner = config["owner"]
                repo = config["repo"]
                other_addon_id = config["addon_id"]
                print(f"\nProcessing: {other_addon_id} ({owner}/{repo})")
                release = get_latest_release_zip(owner, repo, other_addon_id)
                other_download_dir = temp_dir / other_addon_id
                other_download_dir.mkdir(parents=True)
                if release is NO_RELEASE:
                    branch = config["branch"]
                    print(f"  No release found, building from source ({branch} branch)")
                    source_zip = other_download_dir / "source.zip"
                    download_file(_source_archive_url(owner, repo, branch), source_zip)
                    zip_path, version, filename = create_source_package(
                        source_zip, other_addon_id, other_download_dir
                    )
                else:
                    release_url, version, filename = release
                    print(f"  Found release: v{version} ({filename})")
                    zip_path = other_download_dir / filename
                    download_file(release_url, zip_path)
                published.append(
                    publish_release_zip(
                        zip_path,
                        other_addon_id,
                        version,
                        filename,
                        staging_repo,
                    )
                )
                print(f"  OK: v{version}")

            print(f"\nProcessing: {REPO_ADDON_ID} (self)")
            package_path, version = _create_repository_package_in(repo_root, temp_dir)
            published.append(
                publish_release_zip(
                    package_path,
                    REPO_ADDON_ID,
                    version,
                    package_path.name,
                    staging_repo,
                )
            )
            print(f"  OK: v{version}")

            print("\nGenerating addons.xml...")
            manifest = _write_addons_xml(published, staging_repo / "addons.xml")
            checksum = hashlib.md5(manifest).hexdigest()
            (staging_repo / "addons.xml.md5").write_text(checksum, encoding="utf-8")
            create_pages_site(staging_repo, staging_site)
            validate_site_manifest(staging_site)
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

        source_ref = source_github_api_get(source_ref_url)
        current_sha = source_ref.get("object", {}).get("sha")
        if current_sha != candidate_sha:
            raise RuntimeError(
                f"Expected branch {expected_branch!r} moved before promotion: "
                f"current SHA {current_sha!r} does not match candidate_sha "
                f"{candidate_sha!r}"
            )

        promote_repository_outputs(staging, repo_root / "repo", repo_root / "_site")
        staging.rmdir()

        print(f"\n  addons.xml: {repo_root / 'repo' / 'addons.xml'}")
        print(f"  addons.xml.md5: {checksum}")
        print(f"  Pages site: {repo_root / '_site'}")
        print("\n" + "=" * 60)
        print("Repository built and validated successfully!")
        print(f"Addons included: {len(published)}")
        for addon in published:
            print(f"  - {addon.get('id')}")
        print("=" * 60)

    except BaseException:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def build_repository():
    """Build the repository and fail on any configured addon inconsistency."""
    print("=" * 60)
    print("Building Serph91P Kodi Repository")
    print("=" * 60)
    for output in (REPO_OUTPUT, TEMP_DIR, SITE_OUTPUT):
        if output.exists():
            shutil.rmtree(output)
    REPO_OUTPUT.mkdir(parents=True)
    TEMP_DIR.mkdir(parents=True)

    addons = []
    try:
        for config in ADDONS:
            owner = config["owner"]
            repo = config["repo"]
            addon_id = config["addon_id"]
            print(f"\nProcessing: {addon_id} ({owner}/{repo})")
            release = get_latest_release_zip(owner, repo, addon_id)
            _validated_filename_component(addon_id, "addon ID")
            download_dir = TEMP_DIR / addon_id
            download_dir.mkdir(parents=True)
            if release is NO_RELEASE:
                branch = config["branch"]
                print(f"  No release found, building from source ({branch} branch)")
                source_zip = download_dir / "source.zip"
                download_file(_source_archive_url(owner, repo, branch), source_zip)
                zip_path, version, filename = create_source_package(
                    source_zip, addon_id, download_dir
                )
            else:
                release_url, version, filename = release
                _validated_filename_component(version, "release version")
                if filename != f"{addon_id}-{version}.zip":
                    raise RuntimeError(
                        f"Release filename {filename!r} does not match addon ID and version"
                    )
                print(f"  Found release: v{version} ({filename})")
                zip_path = download_dir / filename
                download_file(release_url, zip_path)
            addons.append(
                publish_release_zip(zip_path, addon_id, version, filename, REPO_OUTPUT)
            )
            print(f"  OK: v{version}")

        print(f"\nProcessing: {REPO_ADDON_ID} (self)")
        package_path, version = _create_repository_package()
        addons.append(
            publish_release_zip(
                package_path,
                REPO_ADDON_ID,
                version,
                package_path.name,
                REPO_OUTPUT,
            )
        )
        print(f"  OK: v{version}")

        print("\nGenerating addons.xml...")
        manifest = _write_addons_xml(addons, REPO_OUTPUT / "addons.xml")
        checksum = hashlib.md5(manifest).hexdigest()
        (REPO_OUTPUT / "addons.xml.md5").write_text(checksum, encoding="utf-8")
        create_pages_site(REPO_OUTPUT, SITE_OUTPUT)
        validate_site_manifest(SITE_OUTPUT)
    finally:
        if TEMP_DIR.exists():
            shutil.rmtree(TEMP_DIR)

    print(f"  addons.xml: {REPO_OUTPUT / 'addons.xml'}")
    print(f"  addons.xml.md5: {checksum}")
    print(f"  Pages site: {SITE_OUTPUT}")
    print("\n" + "=" * 60)
    print("Repository built and validated successfully!")
    print(f"Addons included: {len(addons)}")
    for addon in addons:
        print(f"  - {addon.get('id')}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate-site",
        action="store_true",
        help="validate the existing generated site",
    )
    arguments = parser.parse_args()
    if arguments.validate_site:
        validate_site_manifest()
        print(f"Validated generated site: {SITE_OUTPUT}")
    else:
        dispatch_payload_json = os.environ.get("DISPATCH_PAYLOAD", "").strip()
        if dispatch_payload_json:
            dispatch_payload = json.loads(dispatch_payload_json)
            build_immutable_repository(dispatch_payload)
        else:
            build_repository()


if __name__ == "__main__":
    main()
