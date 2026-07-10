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
        if len(path.parts) == 1:
            if not info.is_dir():
                raise RuntimeError(f"Source archive root must be a directory: {name!r}")
            continue
        if info.is_dir():
            continue
        file_type = (info.external_attr >> 16) & 0o170000
        if file_type not in (0, 0o100000):
            raise RuntimeError(f"Unsupported source archive member type: {name!r}")
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


def _create_repository_package():
    addon_xml_path = REPO_ROOT / "addon.xml"
    if not addon_xml_path.is_file():
        raise RuntimeError(f"Missing repository metadata: {addon_xml_path}")
    try:
        root = ET.parse(addon_xml_path).getroot()
    except ET.ParseError as error:
        raise RuntimeError(f"Invalid repository metadata: {error}") from error
    if root.get("id") != REPO_ADDON_ID or not root.get("version"):
        raise RuntimeError("Repository addon.xml has an invalid id or version")
    version = root.get("version")
    package_dir = TEMP_DIR / REPO_ADDON_ID
    package_dir.mkdir(parents=True)
    package_path = package_dir / f"{REPO_ADDON_ID}-{version}.zip"
    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(addon_xml_path, f"{REPO_ADDON_ID}/addon.xml")
        resources_dir = REPO_ROOT / "resources"
        if resources_dir.exists():
            for item in sorted(resources_dir.rglob("*")):
                if item.is_file():
                    archive.write(
                        item, f"{REPO_ADDON_ID}/{item.relative_to(REPO_ROOT)}"
                    )
    return package_path, version


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
        build_repository()


if __name__ == "__main__":
    main()
