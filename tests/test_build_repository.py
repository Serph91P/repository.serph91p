import hashlib
import shutil
import tempfile
import unittest
import urllib.error
import warnings
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest import mock

from scripts import build_repository as builder


def addon_xml(addon_id, version, assets=()):
    asset_xml = "".join(f"<{kind}>{path}</{kind}>" for kind, path in assets)
    return (
        f'<addon id="{addon_id}" name="Test" version="{version}" '
        f'provider-name="Test"><extension point="xbmc.addon.metadata">'
        f"<assets>{asset_xml}</assets></extension></addon>"
    )


def write_addon_zip(path, addon_id, version, assets=(), extra_entries=()):
    metadata = addon_xml(
        addon_id, version, tuple((kind, name) for kind, name, _ in assets)
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{addon_id}/addon.xml", metadata)
        for _kind, name, content in assets:
            archive.writestr(f"{addon_id}/{name}", content)
        for name, content in extra_entries:
            archive.writestr(name, content)


class BuildRepositoryRegressionTests(unittest.TestCase):
    def test_source_only_addon_is_built_from_configured_branch_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_zip = root / "source.zip"
            source_xml = addon_xml(
                "plugin.video.gronkhtv",
                "2.3.0",
                (("icon", "resources/icon.png"),),
            )
            with zipfile.ZipFile(source_zip, "w") as archive:
                archive.writestr("plugin.video.gronkhtv-main/addon.xml", source_xml)
                archive.writestr(
                    "plugin.video.gronkhtv-main/resources/icon.png", b"source-icon"
                )
                archive.writestr("plugin.video.gronkhtv-main/default.py", b"pass\n")

            (root / "addon.xml").write_text(
                addon_xml("repository.serph91p", "1.0.0"), encoding="utf-8"
            )
            config = {
                "owner": "Serph91P",
                "repo": "plugin.video.gronkhtv",
                "addon_id": "plugin.video.gronkhtv",
                "branch": "main",
            }

            def copy_source(_url, destination):
                shutil.copy2(source_zip, destination)

            with (
                mock.patch.object(builder, "REPO_ROOT", root),
                mock.patch.object(builder, "REPO_OUTPUT", root / "repo"),
                mock.patch.object(builder, "TEMP_DIR", root / "_temp"),
                mock.patch.object(builder, "SITE_OUTPUT", root / "_site", create=True),
                mock.patch.object(builder, "ADDONS", [config]),
                mock.patch.object(
                    builder, "get_latest_release_zip", return_value=builder.NO_RELEASE
                ),
                mock.patch.object(builder, "download_file", side_effect=copy_source),
            ):
                builder.build_repository()

            package = (
                root
                / "repo"
                / "plugin.video.gronkhtv"
                / "plugin.video.gronkhtv-2.3.0.zip"
            )
            self.assertTrue(package.is_file())
            with zipfile.ZipFile(package) as archive:
                self.assertEqual(
                    {
                        "plugin.video.gronkhtv/addon.xml",
                        "plugin.video.gronkhtv/resources/icon.png",
                        "plugin.video.gronkhtv/default.py",
                    },
                    set(archive.namelist()),
                )
            generated = ET.parse(root / "repo" / "addons.xml").getroot()
            addon = generated.find("./addon[@id='plugin.video.gronkhtv']")
            self.assertEqual("2.3.0", addon.get("version"))
            self.assertEqual(
                b"source-icon",
                (root / "repo/plugin.video.gronkhtv/resources/icon.png").read_bytes(),
            )

    def test_release_zip_is_the_only_source_for_metadata_and_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release_zip = root / "plugin.video.gronkhtv-2.1.0.zip"
            release_xml = addon_xml(
                "plugin.video.gronkhtv",
                "2.1.0",
                (("icon", "resources/icon.png"), ("fanart", "resources/fanart.jpg")),
            )
            with zipfile.ZipFile(release_zip, "w") as archive:
                archive.writestr("plugin.video.gronkhtv/addon.xml", release_xml)
                archive.writestr(
                    "plugin.video.gronkhtv/resources/icon.png", b"icon-2.1.0"
                )
                archive.writestr(
                    "plugin.video.gronkhtv/resources/fanart.jpg", b"fanart-2.1.0"
                )

            (root / "addon.xml").write_text(
                addon_xml("repository.serph91p", "1.0.0"), encoding="utf-8"
            )
            branch_xml = addon_xml("plugin.video.gronkhtv", "2.2.0")

            def copy_release(_url, destination):
                shutil.copy2(release_zip, destination)

            config = {
                "owner": "Serph91P",
                "repo": "plugin.video.gronkhtv",
                "addon_id": "plugin.video.gronkhtv",
                "branch": "main",
            }
            with (
                mock.patch.object(builder, "REPO_ROOT", root),
                mock.patch.object(builder, "REPO_OUTPUT", root / "repo"),
                mock.patch.object(builder, "TEMP_DIR", root / "_temp"),
                mock.patch.object(builder, "SITE_OUTPUT", root / "_site", create=True),
                mock.patch.object(builder, "ADDONS", [config]),
                mock.patch.object(
                    builder,
                    "get_latest_release_zip",
                    return_value=(
                        "https://example.invalid/release.zip",
                        "2.1.0",
                        release_zip.name,
                    ),
                ),
                mock.patch.object(builder, "download_file", side_effect=copy_release),
                mock.patch.object(
                    builder,
                    "get_addon_xml_from_repo",
                    return_value=branch_xml,
                    create=True,
                ) as branch_source,
            ):
                builder.build_repository()

            branch_source.assert_not_called()
            generated = ET.parse(root / "repo" / "addons.xml").getroot()
            gronkh = generated.find("./addon[@id='plugin.video.gronkhtv']")
            self.assertIsNotNone(gronkh)
            self.assertEqual("2.1.0", gronkh.get("version"))
            addon_dir = root / "repo" / "plugin.video.gronkhtv"
            self.assertEqual(
                b"icon-2.1.0", (addon_dir / "resources/icon.png").read_bytes()
            )
            self.assertEqual(
                b"fanart-2.1.0", (addon_dir / "resources/fanart.jpg").read_bytes()
            )
            site = root / "_site"
            self.assertTrue(
                (
                    site / "plugin.video.gronkhtv" / "plugin.video.gronkhtv-2.1.0.zip"
                ).is_file()
            )
            self.assertTrue(
                (
                    site / "repository.serph91p" / "repository.serph91p-1.0.0.zip"
                ).is_file()
            )
            self.assertTrue((site / "repository.serph91p-1.0.0.zip").is_file())
            self.assertIn(
                'href="plugin.video.gronkhtv/"',
                (site / "index.html").read_text(encoding="utf-8"),
            )

    def test_repository_package_publishes_its_local_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                mock.patch.object(builder, "TEMP_DIR", root / "_temp"),
                mock.patch.object(
                    builder, "REPO_ROOT", Path(builder.__file__).resolve().parents[1]
                ),
            ):
                package, version = builder._create_repository_package()
                metadata = builder.publish_release_zip(
                    package,
                    "repository.serph91p",
                    version,
                    package.name,
                    root / "repo",
                )

            self.assertEqual("repository.serph91p", metadata.get("id"))
            addon_dir = root / "repo" / "repository.serph91p"
            self.assertTrue((addon_dir / "resources/icon.png").is_file())
            self.assertTrue((addon_dir / "resources/fanart.jpg").is_file())


class ReleaseValidationTests(unittest.TestCase):
    def test_empty_releases_after_missing_latest_returns_no_release(self):
        not_found = urllib.error.HTTPError(
            "https://example.invalid/releases/latest", 404, "Not Found", {}, None
        )
        with mock.patch.object(
            builder,
            "github_api_get",
            side_effect=[not_found, []],
        ) as github_api_get:
            result = builder.get_latest_release_zip("owner", "repo", "plugin.example")

        self.assertIs(builder.NO_RELEASE, result)
        self.assertEqual(
            [
                mock.call(f"{builder.GH_API}/repos/owner/repo/releases/latest"),
                mock.call(f"{builder.GH_API}/repos/owner/repo/releases"),
            ],
            github_api_get.call_args_list,
        )

    def test_existing_prerelease_after_missing_latest_fails_closed(self):
        not_found = urllib.error.HTTPError(
            "https://example.invalid/releases/latest", 404, "Not Found", {}, None
        )
        with mock.patch.object(
            builder,
            "github_api_get",
            side_effect=[not_found, [{"prerelease": True, "tag_name": "v2.0.0-rc1"}]],
        ) as github_api_get:
            with self.assertRaises(RuntimeError):
                builder.get_latest_release_zip("owner", "repo", "plugin.example")

        self.assertEqual(
            f"{builder.GH_API}/repos/owner/repo/releases",
            github_api_get.call_args_list[1].args[0],
        )

    def test_release_list_failure_after_missing_latest_propagates(self):
        not_found = urllib.error.HTTPError(
            "https://example.invalid/releases/latest", 404, "Not Found", {}, None
        )
        list_error = urllib.error.URLError("release list unavailable")
        with mock.patch.object(
            builder,
            "github_api_get",
            side_effect=[not_found, list_error],
        ) as github_api_get:
            with self.assertRaises(urllib.error.URLError):
                builder.get_latest_release_zip("owner", "repo", "plugin.example")

        self.assertEqual(
            f"{builder.GH_API}/repos/owner/repo/releases",
            github_api_get.call_args_list[1].args[0],
        )

    def test_malformed_release_list_after_missing_latest_fails_closed(self):
        not_found = urllib.error.HTTPError(
            "https://example.invalid/releases/latest", 404, "Not Found", {}, None
        )
        with mock.patch.object(
            builder,
            "github_api_get",
            side_effect=[not_found, {"message": "unexpected response"}],
        ) as github_api_get:
            with self.assertRaises(RuntimeError):
                builder.get_latest_release_zip("owner", "repo", "plugin.example")

        self.assertEqual(
            f"{builder.GH_API}/repos/owner/repo/releases",
            github_api_get.call_args_list[1].args[0],
        )

    def test_release_identity_must_agree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid_zip = root / "plugin.example-1.2.3.zip"
            write_addon_zip(valid_zip, "plugin.example", "1.2.3")
            cases = (
                ("plugin.other", "1.2.3", valid_zip.name),
                ("plugin.example", "1.2.4", valid_zip.name),
                ("plugin.example", "1.2.3", "renamed.zip"),
            )
            for addon_id, release_version, release_filename in cases:
                with self.subTest(
                    addon_id=addon_id,
                    release_version=release_version,
                    release_filename=release_filename,
                ):
                    with self.assertRaises(RuntimeError):
                        builder.publish_release_zip(
                            valid_zip,
                            addon_id,
                            release_version,
                            release_filename,
                            root / "output",
                        )

    def test_unsafe_or_ambiguous_archive_members_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            addon_id = "plugin.example"
            cases = {
                "traversal": ("../outside.txt", b"bad"),
                "absolute": ("/absolute.txt", b"bad"),
                "wrong-root": ("other/file.txt", b"bad"),
                "ambiguous-addon-xml": (f"{addon_id}/nested/addon.xml", b"<addon/>"),
            }
            for label, extra_entry in cases.items():
                archive_path = root / f"{label}.zip"
                write_addon_zip(
                    archive_path,
                    addon_id,
                    "1.0.0",
                    extra_entries=(extra_entry,),
                )
                with self.subTest(label=label), self.assertRaises(RuntimeError):
                    builder.publish_release_zip(
                        archive_path,
                        addon_id,
                        "1.0.0",
                        f"{addon_id}-1.0.0.zip",
                        root / "output",
                    )

            duplicate_path = root / "duplicate.zip"
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(duplicate_path, "w") as archive:
                    metadata = addon_xml(addon_id, "1.0.0")
                    archive.writestr(f"{addon_id}/addon.xml", metadata)
                    archive.writestr(f"{addon_id}/addon.xml", metadata)
            with self.assertRaises(RuntimeError):
                builder.publish_release_zip(
                    duplicate_path,
                    addon_id,
                    "1.0.0",
                    f"{addon_id}-1.0.0.zip",
                    root / "output",
                )

    def test_release_archive_referenced_symlink_asset_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            addon_id = "plugin.example"
            archive_path = root / f"{addon_id}-1.0.0.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    f"{addon_id}/addon.xml",
                    addon_xml(
                        addon_id,
                        "1.0.0",
                        (("icon", "resources/icon.png"),),
                    ),
                )
                symlink = zipfile.ZipInfo(f"{addon_id}/resources/icon.png")
                symlink.create_system = 3
                symlink.external_attr = 0o120777 << 16
                archive.writestr(symlink, "target.png")

            with self.assertRaises(RuntimeError):
                builder.publish_release_zip(
                    archive_path,
                    addon_id,
                    "1.0.0",
                    archive_path.name,
                    root / "output",
                )

    def test_release_archive_unreferenced_symlink_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            addon_id = "plugin.example"
            archive_path = root / f"{addon_id}-1.0.0.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(f"{addon_id}/addon.xml", addon_xml(addon_id, "1.0.0"))
                symlink = zipfile.ZipInfo(f"{addon_id}/link")
                symlink.create_system = 3
                symlink.external_attr = 0o120777 << 16
                archive.writestr(symlink, "target")

            with self.assertRaises(RuntimeError):
                builder.publish_release_zip(
                    archive_path,
                    addon_id,
                    "1.0.0",
                    archive_path.name,
                    root / "output",
                )

    def test_release_archive_allows_regular_directory_and_omitted_type_bits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            addon_id = "plugin.example"
            archive_path = root / f"{addon_id}-1.0.0.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                metadata = zipfile.ZipInfo(f"{addon_id}/addon.xml")
                metadata.create_system = 3
                metadata.external_attr = 0o100644 << 16
                archive.writestr(metadata, addon_xml(addon_id, "1.0.0"))
                resources = zipfile.ZipInfo(f"{addon_id}/resources/")
                resources.create_system = 3
                resources.external_attr = 0o040755 << 16
                archive.writestr(resources, b"")
                no_type = zipfile.ZipInfo(f"{addon_id}/resources/data.txt")
                no_type.create_system = 0
                no_type.external_attr = 0
                archive.writestr(no_type, b"data")

            builder.publish_release_zip(
                archive_path,
                addon_id,
                "1.0.0",
                archive_path.name,
                root / "output",
            )

    def test_release_archive_other_special_member_types_are_rejected(self):
        special_types = {
            "fifo": 0o010000,
            "character-device": 0o020000,
            "block-device": 0o060000,
            "socket": 0o140000,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            addon_id = "plugin.example"
            for label, file_type in special_types.items():
                archive_path = root / f"{addon_id}-1.0.0.zip"
                with zipfile.ZipFile(archive_path, "w") as archive:
                    archive.writestr(
                        f"{addon_id}/addon.xml", addon_xml(addon_id, "1.0.0")
                    )
                    special = zipfile.ZipInfo(f"{addon_id}/unreferenced-{label}")
                    special.create_system = 3
                    special.external_attr = (file_type | 0o644) << 16
                    archive.writestr(special, b"special")

                with self.subTest(label=label), self.assertRaises(RuntimeError):
                    builder.publish_release_zip(
                        archive_path,
                        addon_id,
                        "1.0.0",
                        archive_path.name,
                        root / "output",
                    )

    def test_release_archive_validates_unreferenced_member_crc(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            addon_id = "plugin.example"
            archive_path = root / f"{addon_id}-1.0.0.zip"
            payload = b"corrupt-me-unreferenced"
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_STORED) as archive:
                archive.writestr(f"{addon_id}/addon.xml", addon_xml(addon_id, "1.0.0"))
                archive.writestr(f"{addon_id}/unused.dat", payload)
            archive_bytes = archive_path.read_bytes()
            self.assertEqual(1, archive_bytes.count(payload))
            archive_path.write_bytes(archive_bytes.replace(payload, payload.upper()))

            with self.assertRaises(RuntimeError):
                builder.publish_release_zip(
                    archive_path,
                    addon_id,
                    "1.0.0",
                    archive_path.name,
                    root / "output",
                )

    def test_missing_local_asset_is_rejected_but_http_assets_are_remote(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            addon_id = "plugin.example"
            archive_path = root / f"{addon_id}-1.0.0.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    f"{addon_id}/addon.xml",
                    addon_xml(
                        addon_id,
                        "1.0.0",
                        (
                            ("icon", "resources/missing.png"),
                            ("fanart", "https://example.invalid/fanart.jpg"),
                        ),
                    ),
                )
            with self.assertRaises(RuntimeError):
                builder.publish_release_zip(
                    archive_path,
                    addon_id,
                    "1.0.0",
                    archive_path.name,
                    root / "output",
                )

    def test_build_fails_instead_of_renaming_an_inconsistent_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad_zip = root / "upstream-name.zip"
            write_addon_zip(bad_zip, "plugin.example", "1.0.0")
            (root / "addon.xml").write_text(
                addon_xml("repository.serph91p", "1.0.0"), encoding="utf-8"
            )

            def copy_release(_url, destination):
                shutil.copy2(bad_zip, destination)

            config = {
                "owner": "owner",
                "repo": "repo",
                "addon_id": "plugin.example",
                "branch": "main",
            }
            with (
                mock.patch.object(builder, "REPO_ROOT", root),
                mock.patch.object(builder, "REPO_OUTPUT", root / "repo"),
                mock.patch.object(builder, "TEMP_DIR", root / "_temp"),
                mock.patch.object(builder, "SITE_OUTPUT", root / "_site", create=True),
                mock.patch.object(builder, "ADDONS", [config]),
                mock.patch.object(
                    builder,
                    "get_latest_release_zip",
                    return_value=(
                        "https://example.invalid/release.zip",
                        "1.0.0",
                        bad_zip.name,
                    ),
                ),
                mock.patch.object(builder, "download_file", side_effect=copy_release),
                mock.patch.object(builder, "create_source_package") as source_fallback,
            ):
                with self.assertRaises(RuntimeError):
                    builder.build_repository()
            source_fallback.assert_not_called()


class SourceArchiveValidationTests(unittest.TestCase):
    def test_unsafe_or_ambiguous_source_archives_are_rejected(self):
        addon_id = "plugin.example"
        metadata = addon_xml(addon_id, "1.0.0")
        cases = {
            "traversal": (
                ("repo-main/addon.xml", metadata),
                ("repo-main/../outside.txt", b"bad"),
            ),
            "absolute": (
                ("repo-main/addon.xml", metadata),
                ("/absolute.txt", b"bad"),
            ),
            "backslash": (
                ("repo-main/addon.xml", metadata),
                ("repo-main\\outside.txt", b"bad"),
            ),
            "ambiguous-roots": (
                ("repo-main/addon.xml", metadata),
                ("other-root/file.txt", b"bad"),
            ),
            "missing-root-addon-xml": (("repo-main/default.py", b"pass\n"),),
            "ambiguous-addon-xml": (
                ("repo-main/addon.xml", metadata),
                ("repo-main/nested/addon.xml", metadata),
            ),
            "root-file": (
                ("repo-main", b"bad"),
                ("repo-main/addon.xml", metadata),
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for label, entries in cases.items():
                source_zip = root / f"{label}.zip"
                with zipfile.ZipFile(source_zip, "w") as archive:
                    for name, content in entries:
                        archive.writestr(name, content)
                with self.subTest(label=label), self.assertRaises(RuntimeError):
                    builder.create_source_package(source_zip, addon_id, root)

    def test_source_archive_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_zip = root / "symlink.zip"
            with zipfile.ZipFile(source_zip, "w") as archive:
                archive.writestr(
                    "repo-main/addon.xml", addon_xml("plugin.example", "1.0.0")
                )
                symlink = zipfile.ZipInfo("repo-main/link")
                symlink.create_system = 3
                symlink.external_attr = 0o120777 << 16
                archive.writestr(symlink, "target")

            with self.assertRaises(RuntimeError):
                builder.create_source_package(source_zip, "plugin.example", root)

    def test_source_archive_directory_shaped_special_types_are_rejected(self):
        special_types = {
            "symlink": 0o120000,
            "fifo": 0o010000,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for label, file_type in special_types.items():
                source_zip = root / f"{label}.zip"
                with zipfile.ZipFile(source_zip, "w") as archive:
                    archive.writestr(
                        "repo-main/addon.xml", addon_xml("plugin.example", "1.0.0")
                    )
                    special = zipfile.ZipInfo("repo-main/link/")
                    special.create_system = 3
                    special.external_attr = (file_type | 0o777) << 16
                    archive.writestr(special, b"")

                with self.subTest(label=label), self.assertRaises(RuntimeError):
                    builder.create_source_package(source_zip, "plugin.example", root)

    def test_source_fallback_rejects_nested_repository_only_members(self):
        denied = (
            "resources/generated.pyc",
            "resources/__pycache__/generated.py",
            "resources/.github/workflows/publish.yml",
            "resources/tests/test_runtime.py",
            "resources/readME.md",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, relative in enumerate(denied):
                source_zip = root / f"denied-{index}.zip"
                with zipfile.ZipFile(source_zip, "w") as archive:
                    archive.writestr(
                        "repo-main/addon.xml", addon_xml("plugin.example", "1.0.0")
                    )
                    archive.writestr(f"repo-main/{relative}", b"repository-only")
                with self.subTest(relative=relative):
                    with self.assertRaisesRegex(RuntimeError, "repository-only"):
                        builder.create_source_package(
                            source_zip, "plugin.example", root
                        )


class SiteManifestTests(unittest.TestCase):
    def test_manifest_requires_advertised_packages_assets_and_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            addons = ET.Element("addons")
            for addon_id in ("plugin.video.gronkhtv", "repository.serph91p"):
                addon = ET.SubElement(addons, "addon", id=addon_id, version="1.0.0")
                metadata = ET.SubElement(
                    addon, "extension", point="xbmc.addon.metadata"
                )
                assets = ET.SubElement(metadata, "assets")
                ET.SubElement(assets, "icon").text = "resources/icon.png"
                addon_dir = site / addon_id
                (addon_dir / "resources").mkdir(parents=True)
                (addon_dir / f"{addon_id}-1.0.0.zip").write_bytes(b"zip")
                (addon_dir / "resources/icon.png").write_bytes(b"icon")
            ET.ElementTree(addons).write(site / "addons.xml", encoding="utf-8")
            manifest_bytes = (site / "addons.xml").read_bytes()
            (site / "addons.xml.md5").write_text(
                hashlib.md5(manifest_bytes).hexdigest(), encoding="utf-8"
            )

            configured_addons = [{"addon_id": "plugin.video.gronkhtv"}]
            with mock.patch.object(builder, "ADDONS", configured_addons):
                builder.validate_site_manifest(site)
                (site / "plugin.video.gronkhtv" / "resources/icon.png").unlink()
                with self.assertRaises(RuntimeError):
                    builder.validate_site_manifest(site)

    def test_manifest_requires_every_configured_addon(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            addons = ET.Element("addons")
            for addon_id in ("plugin.video.gronkhtv", "repository.serph91p"):
                ET.SubElement(addons, "addon", id=addon_id, version="1.0.0")
                addon_dir = site / addon_id
                addon_dir.mkdir()
                (addon_dir / f"{addon_id}-1.0.0.zip").write_bytes(b"zip")
            ET.ElementTree(addons).write(site / "addons.xml", encoding="utf-8")
            manifest_bytes = (site / "addons.xml").read_bytes()
            (site / "addons.xml.md5").write_text(
                hashlib.md5(manifest_bytes).hexdigest(), encoding="utf-8"
            )
            configured_addons = [
                {"addon_id": "plugin.video.gronkhtv"},
                {"addon_id": "plugin.video.missing"},
            ]

            with (
                mock.patch.object(builder, "ADDONS", configured_addons),
                self.assertRaises(RuntimeError),
            ):
                builder.validate_site_manifest(site)


class ReconciliationTests(unittest.TestCase):
    def test_main_branch_and_pkc_helpers_are_configured(self):
        configs = {config["addon_id"]: config for config in builder.ADDONS}
        self.assertEqual("main", configs["plugin.video.plexkodiconnect"]["branch"])
        self.assertIn("plugin.video.plexkodiconnect.movies", configs)
        self.assertIn("plugin.video.plexkodiconnect.tvshows", configs)

    def test_repository_urls_match_flat_pages_layout(self):
        metadata = ET.parse(Path(builder.__file__).parents[1] / "addon.xml").getroot()
        repository = metadata.find("./extension[@point='xbmc.addon.repository']/dir")
        base_url = "https://serph91p.github.io/repository.serph91p"
        self.assertEqual(f"{base_url}/addons.xml", repository.findtext("info"))
        self.assertEqual(f"{base_url}/addons.xml.md5", repository.findtext("checksum"))
        self.assertEqual(base_url, repository.findtext("datadir"))


if __name__ == "__main__":
    unittest.main()
