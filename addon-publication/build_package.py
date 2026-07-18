#!/usr/bin/env python3
"""Build and validate one deterministic Kodi add-on package."""

import argparse
import hashlib
import json
import os
import re
import stat
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import NamedTuple
from xml.etree import ElementTree


VERSION_RE = re.compile(
    r"^[0-9]+(?:\.[0-9]+)*(?:\+[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?$",
    re.ASCII,
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
ADDON_ID_RE = re.compile(r"^[0-9A-Za-z._-]+$", re.ASCII)
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
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


class PackageError(RuntimeError):
    """Raised when package input violates the immutable package contract."""


class RuntimeEntry(NamedTuple):
    path: str
    is_directory: bool


class BuildResult(NamedTuple):
    package_path: Path
    evidence_path: Path
    addon_version: str
    asset_name: str
    artifact_sha256: str
    publication_id: str


def _normalized_path(value, *, allow_directory_marker=False):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise PackageError("path must be a non-empty string")
    if "\\" in value:
        raise PackageError(f"backslash path is not allowed: {value!r}")
    is_directory = allow_directory_marker and value.endswith("/")
    candidate = value[:-1] if is_directory else value
    if not candidate or candidate.startswith("/") or candidate.endswith("/"):
        raise PackageError(f"malformed path: {value!r}")
    raw_parts = candidate.split("/")
    if any(part in ("", ".", "..") for part in raw_parts):
        raise PackageError(f"traversal or malformed path: {value!r}")
    path = PurePosixPath(candidate)
    if path.is_absolute():
        raise PackageError(f"absolute path is not allowed: {value!r}")
    normalized = unicodedata.normalize("NFC", candidate)
    if any(part in ("", ".", "..") for part in PurePosixPath(normalized).parts):
        raise PackageError(f"normalized traversal path: {value!r}")
    return normalized, is_directory


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
        raise PackageError(f"repository-only path is not allowed: {value!r}")


def _runtime_entries(values):
    if not isinstance(values, (list, tuple)) or not values:
        raise PackageError("runtime allowlist must be a non-empty list")
    entries = []
    normalized_seen = set()
    folded_seen = set()
    for raw in values:
        path, is_directory = _normalized_path(raw, allow_directory_marker=True)
        if len(PurePosixPath(path).parts) != 1:
            raise PackageError(f"runtime allowlist entry must be top-level: {raw!r}")
        normalized_key = path
        folded_key = path.casefold()
        if normalized_key in normalized_seen or folded_key in folded_seen:
            raise PackageError(f"runtime allowlist collision: {raw!r}")
        normalized_seen.add(normalized_key)
        folded_seen.add(folded_key)
        entries.append(RuntimeEntry(path, is_directory))
    if not any(
        entry.path == "addon.xml" and not entry.is_directory for entry in entries
    ):
        raise PackageError("runtime allowlist must contain addon.xml as a file")
    for entry in entries:
        for other in entries:
            if entry == other:
                continue
            if entry.is_directory and other.path.startswith(entry.path + "/"):
                raise PackageError(
                    f"overlapping runtime allowlist entries: {entry.path!r} and {other.path!r}"
                )
    return entries


def _parse_manifest(data, expected_addon_id):
    try:
        root = ElementTree.fromstring(data)
    except (ElementTree.ParseError, UnicodeError) as error:
        raise PackageError(f"invalid addon.xml: {error}") from error
    if root.tag != "addon":
        raise PackageError("addon.xml root must be addon")
    addon_id = root.attrib.get("id")
    version = root.attrib.get("version")
    if addon_id != expected_addon_id:
        raise PackageError(
            f"addon.xml add-on ID {addon_id!r} does not match configured add-on ID {expected_addon_id!r}"
        )
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise PackageError(f"invalid addon.xml version: {version!r}")
    return root, version


def _manifest_references(root):
    references = set()
    for element in root.iter():
        for attribute in ("library", "icon", "fanart"):
            value = element.attrib.get(attribute)
            if value:
                references.add(value.strip())
        if element.tag.rsplit("}", 1)[-1] == "assets":
            for asset in element.iter():
                if asset is not element and asset.text and asset.text.strip():
                    references.add(asset.text.strip())
    local = set()
    for reference in references:
        if not reference or "://" in reference or reference.startswith("special:"):
            continue
        path, marker = _normalized_path(reference, allow_directory_marker=True)
        if marker:
            path = path.rstrip("/")
        local.add(path)
    return local


def _regular_file_mode(path):
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode):
        raise PackageError(f"symlink is not allowed: {path}")
    if not stat.S_ISREG(mode):
        raise PackageError(f"non-regular file is not allowed: {path}")


def _collect_files(source_dir, entries):
    files = []
    normalized_seen = set()
    folded_seen = set()

    def add_file(path):
        _regular_file_mode(path)
        raw_relative = path.relative_to(source_dir).as_posix()
        normalized, marker = _normalized_path(raw_relative)
        if marker:
            raise PackageError(f"unexpected directory marker: {raw_relative!r}")
        _reject_repository_only_path(normalized)
        folded = normalized.casefold()
        if normalized in normalized_seen or folded in folded_seen:
            raise PackageError(f"source path collision: {raw_relative!r}")
        normalized_seen.add(normalized)
        folded_seen.add(folded)
        files.append((normalized, path))

    for entry in entries:
        path = source_dir.joinpath(*PurePosixPath(entry.path).parts)
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError as error:
            raise PackageError(
                f"runtime allowlist entry is missing: {entry.path}"
            ) from error
        if stat.S_ISLNK(mode):
            raise PackageError(f"symlink is not allowed: {entry.path}")
        if entry.is_directory:
            if not stat.S_ISDIR(mode):
                raise PackageError(
                    f"runtime directory entry is not a directory: {entry.path}"
                )
            found = False

            def fail_walk(error):
                raise PackageError(f"unable to scan runtime directory {entry.path!r}: {error}") from error

            for current_root, directory_names, file_names in os.walk(
                path, followlinks=False, onerror=fail_walk
            ):
                current = Path(current_root)
                for name in list(directory_names):
                    child = current / name
                    child_mode = child.lstat().st_mode
                    if stat.S_ISLNK(child_mode):
                        raise PackageError(f"symlink is not allowed: {child}")
                    if not stat.S_ISDIR(child_mode):
                        raise PackageError(
                            f"special directory member is not allowed: {child}"
                        )
                for name in file_names:
                    found = True
                    add_file(current / name)
            if not found:
                raise PackageError(
                    f"runtime directory entry has no regular files: {entry.path}"
                )
        else:
            add_file(path)
    return sorted(files, key=lambda item: item[0])


def _reference_is_present(reference, files):
    if reference in files:
        return True
    prefix = reference.rstrip("/") + "/"
    return any(name.startswith(prefix) for name in files)


def _validate_manifest_references(root, file_names):
    for reference in sorted(_manifest_references(root)):
        if not _reference_is_present(reference, file_names):
            raise PackageError(
                f"manifest reference is not an approved regular archive member: {reference}"
            )


def _validate_identity(addon_id, validation_run_id, candidate_sha, validation_head_sha):
    if not isinstance(addon_id, str) or not ADDON_ID_RE.fullmatch(addon_id):
        raise PackageError(f"invalid configured add-on ID: {addon_id!r}")
    if (
        isinstance(validation_run_id, bool)
        or not isinstance(validation_run_id, int)
        or validation_run_id <= 0
    ):
        raise PackageError("validation run ID must be a positive integer")
    if not isinstance(candidate_sha, str) or not SHA_RE.fullmatch(candidate_sha):
        raise PackageError("candidate SHA must be 40 lowercase hexadecimal characters")
    if not isinstance(validation_head_sha, str) or not SHA_RE.fullmatch(
        validation_head_sha
    ):
        raise PackageError(
            "validation head SHA must be 40 lowercase hexadecimal characters"
        )


def _write_deterministic_zip(package_path, addon_id, files):
    with zipfile.ZipFile(
        package_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for relative, source_path in files:
            member_name = f"{addon_id}/{relative}"
            info = zipfile.ZipInfo(member_name, FIXED_TIMESTAMP)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(
                info,
                source_path.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )


def validate_package_archive(package_path, addon_id, runtime_entries):
    entries = _runtime_entries(runtime_entries)
    allowed_files = {entry.path for entry in entries if not entry.is_directory}
    allowed_directories = tuple(
        entry.path + "/" for entry in entries if entry.is_directory
    )
    normalized_seen = set()
    folded_seen = set()
    file_names = set()
    manifest_data = None
    try:
        with zipfile.ZipFile(package_path, "r") as archive:
            infos = archive.infolist()
            if not infos:
                raise PackageError("package archive is empty")
            for info in infos:
                if info.is_dir():
                    raise PackageError(
                        f"directory archive member is not allowed: {info.filename!r}"
                    )
                raw_name = info.filename
                normalized, marker = _normalized_path(raw_name)
                if marker:
                    raise PackageError(
                        f"directory archive member is not allowed: {raw_name!r}"
                    )
                if normalized in normalized_seen:
                    raise PackageError(
                        f"duplicate or normalized archive path collision: {raw_name!r}"
                    )
                folded = normalized.casefold()
                if folded in folded_seen:
                    raise PackageError(
                        f"case-fold archive path collision: {raw_name!r}"
                    )
                normalized_seen.add(normalized)
                folded_seen.add(folded)
                parts = PurePosixPath(normalized).parts
                if len(parts) < 2 or parts[0] != addon_id:
                    raise PackageError(
                        f"archive member is outside exact root {addon_id!r}: {raw_name!r}"
                    )
                relative = "/".join(parts[1:])
                _reject_repository_only_path(relative)
                if relative not in allowed_files and not any(
                    relative.startswith(prefix) for prefix in allowed_directories
                ):
                    raise PackageError(f"unapproved archive member: {relative!r}")
                mode = info.external_attr >> 16
                kind = stat.S_IFMT(mode)
                if kind not in (0, stat.S_IFREG):
                    raise PackageError(
                        f"archive member is not a regular file: {raw_name!r}"
                    )
                if info.compress_type != zipfile.ZIP_DEFLATED:
                    raise PackageError(
                        f"archive member uses unapproved compression: {raw_name!r}"
                    )
                try:
                    data = archive.read(info)
                except (OSError, RuntimeError, zipfile.BadZipFile) as error:
                    raise PackageError(
                        f"corrupt archive member: {raw_name!r}"
                    ) from error
                file_names.add(relative)
                if relative == "addon.xml":
                    if manifest_data is not None:
                        raise PackageError("duplicate root addon.xml")
                    manifest_data = data
    except zipfile.BadZipFile as error:
        raise PackageError(f"invalid package ZIP: {error}") from error
    for entry in entries:
        present = (
            entry.path in file_names
            if not entry.is_directory
            else any(name.startswith(entry.path + "/") for name in file_names)
        )
        if not present:
            raise PackageError(
                f"required runtime entry is absent from archive: {entry.path}"
            )
    if manifest_data is None:
        raise PackageError("package archive has no root addon.xml")
    manifest_root, version = _parse_manifest(manifest_data, addon_id)
    _validate_manifest_references(manifest_root, file_names)
    return version


def build_package(
    source_dir,
    output_dir,
    addon_id,
    runtime_entries,
    validation_run_id,
    candidate_sha,
    validation_head_sha,
):
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    _validate_identity(addon_id, validation_run_id, candidate_sha, validation_head_sha)
    entries = _runtime_entries(runtime_entries)
    try:
        source_mode = source_dir.lstat().st_mode
    except FileNotFoundError as error:
        raise PackageError(f"source directory does not exist: {source_dir}") from error
    if stat.S_ISLNK(source_mode) or not stat.S_ISDIR(source_mode):
        raise PackageError("source directory must be a real directory, not a symlink")
    files = _collect_files(source_dir, entries)
    file_names = {name for name, _ in files}
    manifest_path = next((path for name, path in files if name == "addon.xml"), None)
    if manifest_path is None:
        raise PackageError("approved source files do not contain addon.xml")
    manifest_root, version = _parse_manifest(manifest_path.read_bytes(), addon_id)
    _validate_manifest_references(manifest_root, file_names)

    if output_dir.exists():
        if output_dir.is_symlink() or any(output_dir.iterdir()):
            raise PackageError(
                f"output directory must not exist or must be empty: {output_dir}"
            )
    output_dir.mkdir(parents=True, exist_ok=True)
    package_directory = output_dir / "addon-package"
    evidence_directory = output_dir / "validation-evidence"
    package_directory.mkdir()
    evidence_directory.mkdir()
    asset_name = f"{addon_id}-{version}.zip"
    package_path = package_directory / asset_name
    _write_deterministic_zip(package_path, addon_id, files)
    archive_version = validate_package_archive(package_path, addon_id, runtime_entries)
    if archive_version != version:
        raise PackageError("built archive version does not match source manifest")
    checksum = hashlib.sha256(package_path.read_bytes()).hexdigest()
    publication_id = f"{addon_id}@{version}"
    evidence = {
        "validation_run_id": validation_run_id,
        "candidate_sha": candidate_sha,
        "validation_head_sha": validation_head_sha,
        "addon_id": addon_id,
        "addon_version": version,
        "asset_name": asset_name,
        "artifact_sha256": checksum,
        "publication_id": publication_id,
    }
    if tuple(evidence) != EVIDENCE_FIELDS:
        raise AssertionError("evidence field order drifted")
    evidence_path = evidence_directory / "validation-evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=True, indent=2, separators=(",", ": "))
        + "\n",
        encoding="ascii",
    )
    return BuildResult(
        package_path,
        evidence_path,
        version,
        asset_name,
        checksum,
        publication_id,
    )


def _write_github_outputs(path, result):
    values = {
        "addon_version": result.addon_version,
        "asset_name": result.asset_name,
        "artifact_sha256": result.artifact_sha256,
        "publication_id": result.publication_id,
        "package_path": result.package_path,
        "evidence_path": result.evidence_path,
    }
    with Path(path).open("a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--addon-id", required=True)
    parser.add_argument("--runtime-entries-json", required=True)
    parser.add_argument("--validation-run-id", required=True, type=int)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--validation-head-sha", required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    try:
        runtime_entries = json.loads(args.runtime_entries_json)
    except json.JSONDecodeError as error:
        parser.error(f"invalid runtime entries JSON: {error}")
    try:
        result = build_package(
            args.source_dir,
            args.output_dir,
            args.addon_id,
            runtime_entries,
            args.validation_run_id,
            args.candidate_sha,
            args.validation_head_sha,
        )
    except PackageError as error:
        parser.error(str(error))
    if args.github_output:
        _write_github_outputs(args.github_output, result)
    print(
        json.dumps(
            {
                "addon_version": result.addon_version,
                "asset_name": result.asset_name,
                "artifact_sha256": result.artifact_sha256,
                "publication_id": result.publication_id,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
