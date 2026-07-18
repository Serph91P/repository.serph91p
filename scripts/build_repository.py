#!/usr/bin/env python3
"""Build and validate the Serph91P Kodi repository."""

import argparse
import datetime
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
        "publication_enabled": False,
        "publication_branch": "develop",
        "validation_workflow": "Add-on Validations",
        "validation_workflow_path": ".github/workflows/addon-validations.yml@develop",
        "validation_workflow_id": 234989014,
        "package_artifact_name": "addon-package",
        "evidence_artifact_name": "validation-evidence",
        "runtime_entries": ("addon.xml", "addon.py", "resources/"),
    },
    {
        "owner": "Serph91P",
        "repo": "plugin.video.twitch",
        "addon_id": "plugin.video.twitch",
        "branch": "main",
        "publication_enabled": False,
        "publication_branch": "develop",
        "validation_workflow": "Add-on Validations",
        "validation_workflow_path": ".github/workflows/addon-validations.yml@develop",
        "validation_workflow_id": 211623879,
        "package_artifact_name": "addon-package",
        "evidence_artifact_name": "validation-evidence",
        "runtime_entries": ("addon.xml", "changelog.txt", "resources/"),
    },
    {
        "owner": "Serph91P",
        "repo": "script.module.python.twitch",
        "addon_id": "script.module.python.twitch",
        "branch": "main",
        "publication_enabled": False,
        "publication_branch": "develop",
        "validation_workflow": "Add-on Validations",
        "validation_workflow_path": ".github/workflows/addon-validations.yml@develop",
        "validation_workflow_id": 211624357,
        "package_artifact_name": "addon-package",
        "evidence_artifact_name": "validation-evidence",
        "runtime_entries": ("addon.xml", "changelog.txt", "resources/"),
    },
    {
        "owner": "Serph91P",
        "repo": "PlexKodiConnect",
        "addon_id": "plugin.video.plexkodiconnect",
        "branch": "main",
        "publication_enabled": False,
        "publication_branch": "develop",
        "validation_workflow": "Add-on Validations",
        "validation_workflow_path": ".github/workflows/addon-validations.yml@develop",
        "validation_workflow_id": 234989955,
        "package_artifact_name": "addon-package",
        "evidence_artifact_name": "validation-evidence",
        "runtime_entries": (
            "addon.xml",
            "changelog.txt",
            "context_extras.py",
            "context_menu.py",
            "default.py",
            "service.py",
            "fanart.jpg",
            "icon.png",
            "themoviedb.png",
            "resources/",
        ),
    },
    {
        "owner": "Serph91P",
        "repo": "plugin.video.plexkodiconnect.movies",
        "addon_id": "plugin.video.plexkodiconnect.movies",
        "branch": "main",
        "publication_enabled": False,
        "publication_branch": "develop",
        "validation_workflow": "Add-on Validations",
        "validation_workflow_path": ".github/workflows/addon-validations.yml@develop",
        "validation_workflow_id": 235177143,
        "package_artifact_name": "addon-package",
        "evidence_artifact_name": "validation-evidence",
        "runtime_entries": ("addon.xml", "changelog.txt", "default.py", "icon.png"),
    },
    {
        "owner": "Serph91P",
        "repo": "plugin.video.plexkodiconnect.tvshows",
        "addon_id": "plugin.video.plexkodiconnect.tvshows",
        "branch": "main",
        "publication_enabled": False,
        "publication_branch": "develop",
        "validation_workflow": "Add-on Validations",
        "validation_workflow_path": ".github/workflows/addon-validations.yml@develop",
        "validation_workflow_id": 235177212,
        "package_artifact_name": "addon-package",
        "evidence_artifact_name": "validation-evidence",
        "runtime_entries": ("addon.xml", "changelog.txt", "default.py", "icon.png"),
    },
    {
        "owner": "Serph91P",
        "repo": "script.tubecast",
        "addon_id": "script.tubecast",
        "branch": "main",
        "publication_enabled": False,
        "publication_branch": "develop",
        "validation_workflow": "Add-on Validations",
        "validation_workflow_path": ".github/workflows/addon-validations.yml@develop",
        "validation_workflow_id": 234990067,
        "package_artifact_name": "addon-package",
        "evidence_artifact_name": "validation-evidence",
        "runtime_entries": ("addon.xml", "main.py", "script.py", "resources/"),
    },
]

ARTIFACT_RETENTION_DAYS = 30
ARTIFACT_PAGE_SIZE = 100
MAX_ARTIFACT_PAGES = 100
REPOSITORY_ONLY_COMPONENTS = {
    ".git",
    ".github",
    ".hermes",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "tests",
    "workflows",
}
REPOSITORY_ONLY_FILENAMES = {
    ".gitignore",
    "pyproject.toml",
    "requirements-dev.txt",
}
KODI_VERSION_RE = re.compile(
    r"^[0-9]+(?:\.[0-9]+)*(?:\+[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?$",
    re.ASCII,
)


def _source_repo_key(config):
    return f"{config['owner']}/{config['repo']}"


def _source_config(source_repo):
    matches = [config for config in ADDONS if _source_repo_key(config) == source_repo]
    if len(matches) != 1:
        raise RuntimeError(
            f"source_repo {source_repo!r} is not in the configured ADDONS list"
        )
    return matches[0]


def _parse_kodi_version(version_string):
    """Parse the accepted Kodi version grammar into a total-order key."""
    if not isinstance(version_string, str) or not KODI_VERSION_RE.fullmatch(
        version_string
    ):
        raise RuntimeError(f"Invalid addon version segment in {version_string!r}")

    core_text, separator, suffix_text = version_string.partition("+")
    core = [int(part) for part in core_text.split(".")]
    while len(core) > 1 and core[-1] == 0:
        core.pop()

    if not separator:
        suffix = (0,)
    else:
        tokens = []
        for token in suffix_text.split("."):
            if token.isdigit():
                tokens.append((0, int(token)))
            else:
                tokens.append((1, token.casefold()))
        suffix = (1, tuple(tokens))
    return tuple(core), suffix


def _check_version_monotonicity(repo_root, addon_id, candidate_version):
    """Reject a candidate version lower than the currently published version.

    Reads the existing repo addons.xml, finds the current version for addon_id,
    and ensures candidate >= current. Equal versions are permitted because
    rerunning an immutable candidate may be needed. Fails closed if the
    manifest is missing, unparseable, or the existing version is invalid.
    Rejects duplicate addon ids as ambiguous.
    """
    manifest_path = repo_root / "repo" / "addons.xml"
    if not manifest_path.is_file():
        raise RuntimeError(
            f"Cannot enforce version floor without current repository manifest "
            f"{manifest_path}"
        )
    try:
        root = ET.parse(manifest_path).getroot()
    except (OSError, ET.ParseError) as error:
        raise RuntimeError(
            f"Cannot parse existing manifest {manifest_path} for version check: {error}"
        ) from error
    if root.tag != "addons":
        raise RuntimeError(
            f"Existing manifest {manifest_path} has unexpected root {root.tag!r}"
        )
    matching_versions = []
    for addon in root:
        if addon.tag != "addon":
            raise RuntimeError(
                f"Existing manifest {manifest_path} has unexpected element "
                f"{addon.tag!r}"
            )
        if addon.get("id") == addon_id:
            current_version = addon.get("version")
            if not current_version:
                raise RuntimeError(
                    f"Existing addon {addon_id} in {manifest_path} has no version"
                )
            matching_versions.append(current_version)
    if not matching_versions:
        return
    if len(matching_versions) > 1:
        raise RuntimeError(
            f"Existing manifest {manifest_path} contains duplicate addon {addon_id!r}: "
            f"versions {matching_versions}"
        )
    candidate_tuple = _parse_kodi_version(candidate_version)
    current_tuple = _parse_kodi_version(matching_versions[0])
    if candidate_tuple < current_tuple:
        raise RuntimeError(
            f"Rejecting {addon_id} version {candidate_version}: "
            f"currently published version {matching_versions[0]} is newer"
        )


REPO_ADDON_ID = "repository.serph91p"
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
REPO_OUTPUT = REPO_ROOT / "repo"
SITE_OUTPUT = REPO_ROOT / "_site"
TEMP_DIR = REPO_ROOT / "_temp"
GH_API = "https://api.github.com"
CURRENT_MANIFEST_URL = "https://serph91p.github.io/repository.serph91p/addons.xml"
MAX_MANIFEST_BYTES = 5 * 1024 * 1024
NO_RELEASE = object()


def download_current_manifest(repo_root=None):
    """Download and validate the public target manifest without credentials."""
    if repo_root is None:
        repo_root = REPO_ROOT
    request = urllib.request.Request(
        CURRENT_MANIFEST_URL,
        headers={"Accept": "application/xml, text/xml"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        response_url = response.geturl()
        final_url = urlsplit(response_url)
        if (
            final_url.scheme != "https"
            or final_url.hostname != "serph91p.github.io"
            or final_url.port not in (None, 443)
            or final_url.path != "/repository.serph91p/addons.xml"
        ):
            raise RuntimeError(
                f"Current repository manifest redirected to untrusted URL "
                f"{response_url!r}"
            )
        content = response.read(MAX_MANIFEST_BYTES + 1)
    if not content or len(content) > MAX_MANIFEST_BYTES:
        raise RuntimeError("Current repository manifest is empty or too large")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise RuntimeError(f"Current repository manifest is invalid: {error}") from error
    if root.tag != "addons":
        raise RuntimeError(
            f"Current repository manifest has unexpected root {root.tag!r}"
        )
    seen = set()
    for addon in root:
        if addon.tag != "addon":
            raise RuntimeError(
                f"Current repository manifest has unexpected element {addon.tag!r}"
            )
        addon_id = addon.get("id")
        version = addon.get("version")
        if not addon_id or addon_id in seen:
            raise RuntimeError(
                f"Current repository manifest has missing or duplicate add-on ID "
                f"{addon_id!r}"
            )
        _parse_kodi_version(version)
        seen.add(addon_id)
    destination = repo_root / "repo" / "addons.xml"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".xml.tmp")
    temporary.write_bytes(content)
    os.replace(temporary, destination)
    print(f"Downloaded current repository manifest: {destination}")


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


def get_latest_release_zip(owner, repo, addon_id, api_get=None):
    """Return the one correctly named ZIP attached to the latest release."""
    if api_get is None:
        api_get = github_api_get
    releases_url = f"{GH_API}/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
    try:
        data = api_get(f"{releases_url}/releases/latest")
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        releases = api_get(f"{releases_url}/releases")
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


def _reject_repository_only_path(value):
    parts = tuple(part.casefold() for part in PurePosixPath(value).parts)
    filename = parts[-1]
    if (
        any(part in REPOSITORY_ONLY_COMPONENTS for part in parts)
        or filename in REPOSITORY_ONLY_FILENAMES
        or filename.endswith((".pyc", ".pyo"))
        or filename == "readme"
        or filename.startswith("readme.")
    ):
        raise RuntimeError(f"repository-only path is not allowed: {value!r}")


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
        if not info.is_dir():
            _reject_repository_only_path(PurePosixPath(*path.parts[1:]))
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


def _validated_source_members(archive, addon_id, runtime_entries):
    """Validate a GitHub source ZIP and return its embedded identity and files."""
    if not runtime_entries:
        raise RuntimeError("Runtime allowlist is empty")
    allowed_files = {entry for entry in runtime_entries if not entry.endswith("/")}
    directory_prefixes = tuple(
        entry for entry in runtime_entries if entry.endswith("/")
    )
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
        relative = relative_path.as_posix()
        if relative not in allowed_files and not any(
            relative.startswith(prefix) for prefix in directory_prefixes
        ):
            continue
        _reject_repository_only_path(relative_path)
        files.append((relative_path, info))
        members[relative_name] = info
        if relative == "addon.xml":
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
    validate_runtime_allowlist(
        [f"{addon_id}/{relative.as_posix()}" for relative, _info in files],
        addon_id,
        runtime_entries,
    )
    return embedded_id, embedded_version, files


def create_source_package(source_zip, addon_id, destination, runtime_entries):
    """Securely repackage a GitHub source archive as a Kodi addon ZIP."""
    _validated_filename_component(addon_id, "addon ID")
    try:
        with zipfile.ZipFile(source_zip, "r") as source:
            embedded_id, embedded_version, files = _validated_source_members(
                source, addon_id, runtime_entries
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
    """Validate the shape, types, and target-owned source policy.

    Unknown fields including artifact names are rejected before any source API
    access. The workflow identity, branch, and publication enabled flag are
    compared against target-owned per-source policy, not selected by caller
    values.
    """
    if not isinstance(payload, dict):
        raise RuntimeError("Dispatch payload must be a JSON object")
    allowed_fields = {
        "source_repo",
        "candidate_sha",
        "validation_run_id",
        "validation_head_sha",
        "validation_workflow",
        "validation_workflow_path",
        "expected_branch",
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
    source_config = _source_config(source_repo)
    if not source_config["publication_enabled"]:
        raise RuntimeError(
            f"Immutable publication is disabled for source {source_repo!r}"
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
    if (
        isinstance(validation_run_id, bool)
        or not isinstance(validation_run_id, int)
        or validation_run_id <= 0
    ):
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
    if validation_workflow != source_config["validation_workflow"]:
        raise RuntimeError(
            f"Dispatch validation_workflow {validation_workflow!r} does not match "
            f"target policy workflow {source_config['validation_workflow']!r}"
        )
    validation_workflow_path = payload.get("validation_workflow_path")
    if (
        not isinstance(validation_workflow_path, str)
        or not re.fullmatch(
            r"\.github/workflows/[0-9A-Za-z_.-]+\.ya?ml@develop",
            validation_workflow_path,
        )
    ):
        raise RuntimeError(
            "Dispatch validation_workflow_path must identify a develop workflow run"
        )
    if validation_workflow_path != source_config["validation_workflow_path"]:
        raise RuntimeError(
            f"Dispatch validation_workflow_path {validation_workflow_path!r} does "
            f"not match approved path "
            f"{source_config['validation_workflow_path']!r}"
        )
    expected_branch = payload.get("expected_branch")
    if not expected_branch or not isinstance(expected_branch, str):
        raise RuntimeError("Dispatch expected_branch must be a non-empty string")
    if expected_branch != source_config["publication_branch"]:
        raise RuntimeError(
            f"Dispatch expected_branch {expected_branch!r} does not match "
            f"approved branch {source_config['publication_branch']!r}"
        )


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


def validate_github_run(run_data, validation_run_id, validation_head_sha, source_config):
    """Validate a GitHub Actions run response against target-owned policy.

    Compares the run directly against target policy values, not caller-supplied
    dispatch values. Requires exact run ID, candidate/head SHA, configured
    workflow name, configured path/ref, configured publication branch, completed
    status, successful conclusion, push event, exact source repository, and
    stable workflow ID when configured.
    """
    if not isinstance(run_data, dict):
        raise RuntimeError("GitHub run data must be a JSON object")
    if run_data.get("id") != int(validation_run_id):
        raise RuntimeError(
            f"Run ID {run_data.get('id')!r} does not match "
            f"validation_run_id {int(validation_run_id)!r}"
        )
    if run_data.get("head_sha") != validation_head_sha:
        raise RuntimeError(
            f"Run head_sha {run_data.get('head_sha')!r} does not match "
            f"validation_head_sha {validation_head_sha!r}"
        )
    if run_data.get("name") != source_config["validation_workflow"]:
        raise RuntimeError(
            f"Run workflow name {run_data.get('name')!r} does not match "
            f"target policy workflow {source_config['validation_workflow']!r}"
        )
    if run_data.get("path") != source_config["validation_workflow_path"]:
        raise RuntimeError(
            f"Run workflow path {run_data.get('path')!r} does not match "
            f"target policy path {source_config['validation_workflow_path']!r}"
        )
    if run_data.get("head_branch") != source_config["publication_branch"]:
        raise RuntimeError(
            f"Run head_branch {run_data.get('head_branch')!r} does not match "
            f"target policy branch {source_config['publication_branch']!r}"
        )
    if run_data.get("status") != "completed":
        raise RuntimeError(
            f"Run status {run_data.get('status')!r} is not 'completed'"
        )
    if run_data.get("conclusion") != "success":
        raise RuntimeError(
            f"Run conclusion {run_data.get('conclusion')!r} is not 'success'"
        )
    if run_data.get("event") != "push":
        raise RuntimeError(
            f"Run event {run_data.get('event')!r} is not 'push'"
        )
    run_repo = run_data.get("repository", {})
    if not isinstance(run_repo, dict) or run_repo.get("full_name") != (
        f"{source_config['owner']}/{source_config['repo']}"
    ):
        raise RuntimeError(
            f"Run repository {run_repo!r} does not match target "
            f"{source_config['owner']}/{source_config['repo']}"
        )
    if run_data.get("workflow_id") != source_config["validation_workflow_id"]:
        raise RuntimeError(
            f"Run workflow_id {run_data.get('workflow_id')!r} does not match "
            f"target policy workflow_id "
            f"{source_config['validation_workflow_id']!r}"
        )


def verify_package_sha256(zip_path, expected_sha256):
    """Verify that a downloaded ZIP matches the expected SHA-256."""
    actual = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    if actual != expected_sha256:
        raise RuntimeError(
            f"Package SHA-256 {actual!r} does not match expected {expected_sha256!r}"
        )


def fetch_validated_run_artifacts(source_repo, run_id, source_config, now=None):
    """Paginate every page of run artifacts and validate the complete set.

    Requests every page explicitly. Validates every page shape, every artifact
    record, requires exactly two total artifacts (one package, one evidence),
    rejects unexpected names, duplicate required names (including on later
    pages), duplicate IDs, malformed fields, expired or not-currently-live
    artifacts, and retention other than exactly 30 days. Does not download
    before the complete set is validated.
    """
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    if not isinstance(now, datetime.datetime) or now.tzinfo is None:
        raise RuntimeError("Artifact validation time must include a timezone")
    now = now.astimezone(datetime.timezone.utc)
    package_name = source_config["package_artifact_name"]
    evidence_name = source_config["evidence_artifact_name"]
    required_names = {package_name, evidence_name}
    seen_ids = set()
    seen_names = set()
    all_artifacts = []
    page = 1
    expected_total = None

    while True:
        if page > MAX_ARTIFACT_PAGES:
            raise RuntimeError("Artifact pagination exceeded the page limit")
        url = (
            f"{GH_API}/repos/{quote(source_repo, safe='/')}/actions/runs/"
            f"{run_id}/artifacts?per_page={ARTIFACT_PAGE_SIZE}&page={page}"
        )
        page_data = source_github_api_get(url)
        if not isinstance(page_data, dict):
            raise RuntimeError(
                f"Artifact page {page} response is not a JSON object"
            )
        total_count = page_data.get("total_count")
        if (
            isinstance(total_count, bool)
            or not isinstance(total_count, int)
            or total_count < 0
        ):
            raise RuntimeError(
                f"Artifact page {page} has invalid total_count: {total_count!r}"
            )
        if expected_total is None:
            expected_total = total_count
        elif total_count != expected_total:
            raise RuntimeError(
                f"Artifact page {page} total_count {total_count} does not "
                f"match first page total_count {expected_total}"
            )
        artifacts = page_data.get("artifacts")
        if not isinstance(artifacts, list):
            raise RuntimeError(
                f"Artifact page {page} has non-list artifacts"
            )
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise RuntimeError(
                    f"Artifact record on page {page} is not a JSON object"
                )
            artifact_id = artifact.get("id")
            if (
                isinstance(artifact_id, bool)
                or not isinstance(artifact_id, int)
                or artifact_id <= 0
            ):
                raise RuntimeError(
                    f"Artifact on page {page} has invalid id: {artifact_id!r}"
                )
            if artifact_id in seen_ids:
                raise RuntimeError(
                    f"Duplicate artifact id {artifact_id} on page {page}"
                )
            seen_ids.add(artifact_id)
            name = artifact.get("name")
            if not isinstance(name, str) or not name:
                raise RuntimeError(
                    f"Artifact id {artifact_id} on page {page} has "
                    f"invalid name: {name!r}"
                )
            if name not in required_names:
                raise RuntimeError(
                    f"Unexpected artifact name {name!r} on page {page}"
                )
            if name in seen_names:
                raise RuntimeError(
                    f"Duplicate required artifact name {name!r} on page {page}"
                )
            seen_names.add(name)
            expired = artifact.get("expired")
            if not isinstance(expired, bool):
                raise RuntimeError(
                    f"Artifact {name!r} id {artifact_id} has "
                    f"invalid expired field: {expired!r}"
                )
            if expired:
                raise RuntimeError(
                    f"Artifact {name!r} id {artifact_id} has expired"
                )
            created_at = artifact.get("created_at")
            expires_at = artifact.get("expires_at")
            if not isinstance(created_at, str) or not created_at:
                raise RuntimeError(
                    f"Artifact {name!r} id {artifact_id} has "
                    f"invalid created_at: {created_at!r}"
                )
            if not isinstance(expires_at, str) or not expires_at:
                raise RuntimeError(
                    f"Artifact {name!r} id {artifact_id} has "
                    f"invalid expires_at: {expires_at!r}"
                )
            try:
                created_dt = datetime.datetime.strptime(
                    created_at, "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=datetime.timezone.utc)
                expires_dt = datetime.datetime.strptime(
                    expires_at, "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=datetime.timezone.utc)
            except ValueError as error:
                raise RuntimeError(
                    f"Artifact {name!r} id {artifact_id} has "
                    f"malformed timestamp: {error}"
                ) from error
            retention = expires_dt - created_dt
            if retention != datetime.timedelta(days=ARTIFACT_RETENTION_DAYS):
                raise RuntimeError(
                    f"Artifact {name!r} id {artifact_id} has retention "
                    f"{retention}, expected {ARTIFACT_RETENTION_DAYS} days"
                )
            if now < created_dt or now >= expires_dt:
                raise RuntimeError(
                    f"Artifact {name!r} id {artifact_id} retention window "
                    f"is not currently live"
                )
            download_url = artifact.get("archive_download_url")
            if not isinstance(download_url, str) or not download_url:
                raise RuntimeError(
                    f"Artifact {name!r} id {artifact_id} has "
                    f"invalid archive_download_url"
                )
            run_binding = artifact.get("workflow_run")
            if not isinstance(run_binding, dict) or run_binding.get("id") != run_id:
                raise RuntimeError(
                    f"Artifact {name!r} id {artifact_id} workflow_run "
                    f"id does not match run {run_id}"
                )
            all_artifacts.append(artifact)
        if len(artifacts) < ARTIFACT_PAGE_SIZE:
            if expected_total is not None and len(all_artifacts) >= expected_total:
                break
            if not artifacts:
                break
        page += 1

    if expected_total is not None and len(all_artifacts) != expected_total:
        raise RuntimeError(
            f"Fetched {len(all_artifacts)} artifacts but total_count "
            f"is {expected_total}"
        )
    if len(all_artifacts) != 2:
        raise RuntimeError(
            f"Expected exactly two artifacts, found {len(all_artifacts)}"
        )
    selected = {}
    for artifact in all_artifacts:
        selected[artifact["name"]] = artifact
    return selected


def validate_runtime_allowlist(members, addon_id, runtime_entries):
    """Validate archive members against the target-owned runtime allowlist.

    Slash-terminated directories authorize and require their subtree. Exact
    file entries are required. Rejects undeclared runtime members.
    """
    if not runtime_entries:
        raise RuntimeError("Runtime allowlist is empty")
    dir_prefixes = []
    allowed_files = set()
    for entry in runtime_entries:
        if entry.endswith("/"):
            dir_prefixes.append(entry)
        else:
            allowed_files.add(entry)
    runtime_members = []
    for member in members:
        name = member.filename if hasattr(member, "filename") else member
        relative_name = (
            name[:-1]
            if hasattr(member, "is_dir") and member.is_dir() and name.endswith("/")
            else name
        )
        path = PurePosixPath(relative_name)
        if len(path.parts) < 2:
            continue
        if path.parts[0] != addon_id:
            continue
        subpath = "/".join(path.parts[1:])
        if subpath in ("", "."):
            continue
        is_dir = (
            hasattr(member, "is_dir") and member.is_dir()
        ) or name.endswith("/")
        if is_dir:
            continue
        _reject_repository_only_path(subpath)
        matched = False
        for prefix in dir_prefixes:
            if subpath.startswith(prefix):
                matched = True
                break
        if not matched and subpath in allowed_files:
            matched = True
        if not matched:
            raise RuntimeError(
                f"Undeclared runtime member {subpath!r} not in "
                f"allowlist for {addon_id}"
            )
        runtime_members.append(subpath)
    for entry in runtime_entries:
        if entry.endswith("/"):
            has_subtree = any(m.startswith(entry) for m in runtime_members)
            if not has_subtree:
                raise RuntimeError(
                    f"Runtime allowlist directory {entry!r} requires "
                    f"at least one member in subtree for {addon_id}"
                )
        else:
            if entry not in runtime_members:
                raise RuntimeError(
                    f"Runtime allowlist file {entry!r} not found "
                    f"in archive for {addon_id}"
                )


def validate_archive_topology(zip_path, addon_id, addon_version, runtime_entries=None):
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
                if not info.is_dir():
                    _reject_repository_only_path(PurePosixPath(*path.parts[1:]))
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
            if runtime_entries is not None:
                validate_runtime_allowlist(
                    archive.infolist(), addon_id, runtime_entries
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
    source_config = _source_config(source_repo)
    expected_branch = source_config["publication_branch"]
    package_artifact_name = source_config["package_artifact_name"]
    evidence_artifact_name = source_config["evidence_artifact_name"]

    run_data = source_github_api_get(
        f"{GH_API}/repos/{quote(source_repo, safe='/')}/actions/runs/"
        f"{validation_run_id}"
    )
    validate_github_run(run_data, validation_run_id, validation_head_sha, source_config)
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

    selected = fetch_validated_run_artifacts(
        source_repo, validation_run_id, source_config
    )
    evidence_artifact = selected[evidence_artifact_name]
    package_artifact = selected[package_artifact_name]

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
        validate_archive_topology(
            addon_zip_path, addon_id, addon_version,
            source_config["runtime_entries"],
        )

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
                release = get_latest_release_zip(
                    owner,
                    repo,
                    other_addon_id,
                    api_get=source_github_api_get,
                )
                other_download_dir = temp_dir / other_addon_id
                other_download_dir.mkdir(parents=True)
                if release is NO_RELEASE:
                    branch = config["branch"]
                    print(f"  No release found, building from source ({branch} branch)")
                    source_zip = other_download_dir / "source.zip"
                    source_download_file(
                        _source_archive_url(owner, repo, branch), source_zip
                    )
                    zip_path, version, filename = create_source_package(
                        source_zip,
                        other_addon_id,
                        other_download_dir,
                        config["runtime_entries"],
                    )
                else:
                    release_url, version, filename = release
                    print(f"  Found release: v{version} ({filename})")
                    zip_path = other_download_dir / filename
                    source_download_file(release_url, zip_path)
                _check_version_monotonicity(repo_root, other_addon_id, version)
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
            _check_version_monotonicity(repo_root, REPO_ADDON_ID, version)
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
                    source_zip,
                    addon_id,
                    download_dir,
                    config["runtime_entries"],
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
    parser.add_argument(
        "--download-current-manifest",
        action="store_true",
        help="download the current public repository manifest",
    )
    arguments = parser.parse_args()
    if arguments.validate_site and arguments.download_current_manifest:
        parser.error("validation and manifest download modes are mutually exclusive")
    if arguments.download_current_manifest:
        download_current_manifest()
    elif arguments.validate_site:
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
