#!/usr/bin/env python3
"""
Kodi Repository Builder

Fetches addon releases from GitHub, generates addons.xml, addons.xml.md5,
and creates the repository structure for GitHub Pages deployment.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

# Configure addons to include in the repository
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
        "branch": "master",
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
TEMP_DIR = REPO_ROOT / "_temp"
GH_API = "https://api.github.com"


def github_api_get(url):
    """Make an authenticated GitHub API request if token is available."""
    req = urllib.request.Request(url)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download_file(url, dest):
    """Download a file from URL to destination."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"token {token}")
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as f:
        f.write(resp.read())


def get_latest_release_zip(owner, repo):
    """Get the latest release ZIP URL and version from GitHub."""
    url = f"{GH_API}/repos/{owner}/{repo}/releases/latest"
    try:
        data = github_api_get(url)
        version = data["tag_name"].lstrip("v")
        # Look for a ZIP asset
        for asset in data.get("assets", []):
            if asset["name"].endswith(".zip"):
                return asset["browser_download_url"], version, asset["name"]
        return None, version, None
    except Exception as e:
        print(f"  Warning: No release found for {owner}/{repo}: {e}")
        return None, None, None


def get_addon_xml_from_repo(owner, repo, branch, addon_id):
    """Fetch addon.xml directly from the GitHub repository."""
    # Try root addon.xml first
    paths_to_try = [
        f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/addon.xml",
    ]
    for url in paths_to_try:
        try:
            req = urllib.request.Request(url)
            token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
            if token:
                req.add_header("Authorization", f"token {token}")
            with urllib.request.urlopen(req) as resp:
                return resp.read().decode("utf-8")
        except Exception:
            continue
    return None


def get_version_from_addon_xml(addon_xml_content):
    """Extract version from addon.xml content."""
    try:
        root = ET.fromstring(addon_xml_content)
        return root.attrib.get("version")
    except Exception:
        return None


def download_repo_as_zip(owner, repo, branch, addon_id, dest_dir):
    """Download the repository source and create a properly structured ZIP."""
    zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
    temp_zip = dest_dir / f"{repo}-{branch}.zip"
    download_file(zip_url, temp_zip)

    # Extract, rename to addon_id format, and rezip
    import zipfile

    extract_dir = dest_dir / "extracted"
    extract_dir.mkdir(exist_ok=True)

    with zipfile.ZipFile(temp_zip, "r") as zf:
        zf.extractall(extract_dir)

    # Find the extracted directory (GitHub names it repo-branch)
    extracted_dirs = list(extract_dir.iterdir())
    if not extracted_dirs:
        raise RuntimeError(f"No content extracted from {zip_url}")

    source_dir = extracted_dirs[0]

    # Read version from addon.xml
    addon_xml_path = source_dir / "addon.xml"
    if not addon_xml_path.exists():
        raise RuntimeError(f"No addon.xml found in {source_dir}")

    tree = ET.parse(addon_xml_path)
    version = tree.getroot().attrib.get("version")

    # Create properly named directory
    addon_dir_name = addon_id
    proper_dir = extract_dir / addon_dir_name
    if proper_dir.exists():
        shutil.rmtree(proper_dir)
    source_dir.rename(proper_dir)

    # Remove unwanted files/directories
    for pattern in [".git", ".github", ".gitignore", "__pycache__", "*.pyc",
                    ".venv", "venv", "tests", "test", ".vscode", "logs"]:
        for item in proper_dir.rglob(pattern):
            if item.is_dir():
                shutil.rmtree(item)
            elif item.is_file():
                item.unlink()

    # Create the final ZIP
    final_zip_name = f"{addon_id}-{version}.zip"
    final_zip_path = dest_dir / final_zip_name

    with zipfile.ZipFile(final_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in proper_dir.rglob("*"):
            if file_path.is_file():
                arcname = str(file_path.relative_to(extract_dir))
                zf.write(file_path, arcname)

    # Cleanup
    shutil.rmtree(extract_dir)
    temp_zip.unlink()

    return final_zip_path, version


def build_repository():
    """Main function to build the Kodi repository."""
    print("=" * 60)
    print("Building Serph91P Kodi Repository")
    print("=" * 60)

    # Clean and create output directories
    if REPO_OUTPUT.exists():
        shutil.rmtree(REPO_OUTPUT)
    REPO_OUTPUT.mkdir(parents=True)

    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
    TEMP_DIR.mkdir(parents=True)

    addon_xml_parts = []
    processed_addons = []

    # Process each addon
    for addon_config in ADDONS:
        owner = addon_config["owner"]
        repo = addon_config["repo"]
        addon_id = addon_config["addon_id"]
        branch = addon_config["branch"]

        print(f"\nProcessing: {addon_id} ({owner}/{repo})")

        # First try to get a release ZIP
        release_url, release_version, release_filename = get_latest_release_zip(owner, repo)

        if release_url and release_filename:
            print(f"  Found release: v{release_version} ({release_filename})")
            addon_dir = REPO_OUTPUT / addon_id
            addon_dir.mkdir(exist_ok=True)

            # Download release ZIP
            zip_dest = addon_dir / release_filename
            download_file(release_url, zip_dest)

            # Also ensure we have the correct filename format
            expected_name = f"{addon_id}-{release_version}.zip"
            if release_filename != expected_name:
                correct_path = addon_dir / expected_name
                shutil.copy2(zip_dest, correct_path)

            # Get addon.xml content
            addon_xml_content = get_addon_xml_from_repo(owner, repo, branch, addon_id)
            if addon_xml_content:
                addon_xml_parts.append(addon_xml_content)
                processed_addons.append(addon_id)
                print(f"  OK: v{release_version}")
            else:
                print(f"  Warning: Could not fetch addon.xml for {addon_id}")
        else:
            # No release - download source and create ZIP
            print(f"  No release found, building from source ({branch} branch)")
            try:
                addon_temp = TEMP_DIR / addon_id
                addon_temp.mkdir(exist_ok=True)

                zip_path, version = download_repo_as_zip(
                    owner, repo, branch, addon_id, addon_temp
                )

                # Move ZIP to output
                addon_dir = REPO_OUTPUT / addon_id
                addon_dir.mkdir(exist_ok=True)
                final_path = addon_dir / zip_path.name
                shutil.move(str(zip_path), str(final_path))

                # Get addon.xml
                addon_xml_content = get_addon_xml_from_repo(
                    owner, repo, branch, addon_id
                )
                if addon_xml_content:
                    addon_xml_parts.append(addon_xml_content)
                    processed_addons.append(addon_id)
                    print(f"  OK: v{version} (from source)")
                else:
                    print(f"  Warning: Could not fetch addon.xml for {addon_id}")
            except Exception as e:
                print(f"  ERROR: Failed to process {addon_id}: {e}")

    # Add the repository addon itself
    print(f"\nProcessing: {REPO_ADDON_ID} (self)")
    repo_addon_xml_path = REPO_ROOT / "addon.xml"
    if repo_addon_xml_path.exists():
        repo_addon_xml = repo_addon_xml_path.read_text("utf-8")
        addon_xml_parts.append(repo_addon_xml)

        # Create repository addon ZIP
        import zipfile

        tree = ET.parse(repo_addon_xml_path)
        repo_version = tree.getroot().attrib.get("version")
        repo_addon_dir = REPO_OUTPUT / REPO_ADDON_ID
        repo_addon_dir.mkdir(exist_ok=True)

        repo_zip_path = repo_addon_dir / f"{REPO_ADDON_ID}-{repo_version}.zip"
        with zipfile.ZipFile(repo_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add addon.xml
            zf.write(repo_addon_xml_path, f"{REPO_ADDON_ID}/addon.xml")
            # Add resources if they exist
            resources_dir = REPO_ROOT / "resources"
            if resources_dir.exists():
                for item in resources_dir.rglob("*"):
                    if item.is_file():
                        arcname = f"{REPO_ADDON_ID}/{item.relative_to(REPO_ROOT)}"
                        zf.write(item, arcname)

        processed_addons.append(REPO_ADDON_ID)
        print(f"  OK: v{repo_version}")

    # Generate addons.xml
    print("\nGenerating addons.xml...")
    addons_xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<addons>\n'
    for addon_xml in addon_xml_parts:
        # Clean up XML declaration if present
        addon_xml = re.sub(r'<\?xml[^?]*\?>\s*', '', addon_xml).strip()
        addons_xml += addon_xml + "\n"
    addons_xml += "</addons>\n"

    addons_xml_path = REPO_OUTPUT / "addons.xml"
    addons_xml_path.write_text(addons_xml, encoding="utf-8")

    # Generate addons.xml.md5
    md5_hash = hashlib.md5(addons_xml.encode("utf-8")).hexdigest()
    md5_path = REPO_OUTPUT / "addons.xml.md5"
    md5_path.write_text(md5_hash, encoding="utf-8")

    print(f"  addons.xml: {addons_xml_path}")
    print(f"  addons.xml.md5: {md5_hash}")

    # Cleanup temp directory
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)

    # Copy repository addon ZIP to root for easy installation
    repo_zip_src = REPO_OUTPUT / REPO_ADDON_ID / f"{REPO_ADDON_ID}-{repo_version}.zip"
    if repo_zip_src.exists():
        repo_zip_root = REPO_OUTPUT.parent / f"{REPO_ADDON_ID}-latest.zip"
        shutil.copy2(repo_zip_src, repo_zip_root)
        print(f"\n  Repository installer: {repo_zip_root}")

    print(f"\n{'=' * 60}")
    print(f"Repository built successfully!")
    print(f"Addons included: {len(processed_addons)}")
    for addon in processed_addons:
        print(f"  - {addon}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    build_repository()
