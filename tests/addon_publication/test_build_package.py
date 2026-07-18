import hashlib
import importlib.util
import json
import stat
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "addon-publication" / "build_package.py"
SPEC = importlib.util.spec_from_file_location("addon_package_builder", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load package builder")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)

ADDON_ID = "script.example.exact"
VERSION = "1.2.3+omega.1"
SHA = "a" * 40
ALLOWLIST = ["addon.xml", "default.py", "resources/"]


def addon_xml(addon_id=ADDON_ID, version=VERSION, asset="resources/icon.png"):
    return (
        f'<addon id="{addon_id}" name="Example" version="{version}" '
        f'provider-name="Example"><extension point="xbmc.python.pluginsource" '
        f'library="default.py"/><extension point="xbmc.addon.metadata">'
        f"<assets><icon>{asset}</icon></assets></extension></addon>"
    )


def make_source(root, xml=None):
    root.mkdir(parents=True, exist_ok=True)
    (root / "addon.xml").write_text(xml or addon_xml(), encoding="utf-8")
    (root / "default.py").write_text("print('ok')\n", encoding="utf-8")
    resources = root / "resources"
    resources.mkdir()
    (resources / "icon.png").write_bytes(b"icon")
    (resources / "data.txt").write_text("data\n", encoding="utf-8")
    return root


class PackageBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = make_source(self.root / "source")

    def build(self, output_name="output"):
        return builder.build_package(
            source_dir=self.source,
            output_dir=self.root / output_name,
            addon_id=ADDON_ID,
            runtime_entries=ALLOWLIST,
            validation_run_id=12345,
            candidate_sha=SHA,
            validation_head_sha=SHA,
        )

    def test_build_is_deterministic_and_evidence_binds_checksum(self):
        first = self.build("first")
        second = self.build("second")
        first_bytes = first.package_path.read_bytes()
        second_bytes = second.package_path.read_bytes()
        self.assertEqual(first_bytes, second_bytes)
        checksum = hashlib.sha256(first_bytes).hexdigest()
        self.assertEqual(first.artifact_sha256, checksum)
        self.assertEqual(second.artifact_sha256, checksum)
        self.assertRegex(checksum, r"^[0-9a-f]{64}$")
        evidence = json.loads(first.evidence_path.read_text(encoding="utf-8"))
        self.assertEqual(
            list(evidence),
            [
                "validation_run_id",
                "candidate_sha",
                "validation_head_sha",
                "addon_id",
                "addon_version",
                "asset_name",
                "artifact_sha256",
                "publication_id",
            ],
        )
        self.assertEqual(evidence["validation_run_id"], 12345)
        self.assertEqual(evidence["artifact_sha256"], checksum)
        self.assertEqual(evidence["publication_id"], f"{ADDON_ID}@{VERSION}")
        with zipfile.ZipFile(first.package_path) as archive:
            names = archive.namelist()
            self.assertEqual(names, sorted(names))
            self.assertTrue(all(name.startswith(f"{ADDON_ID}/") for name in names))
            self.assertEqual({name.split("/", 1)[0] for name in names}, {ADDON_ID})
            self.assertTrue(
                all(
                    info.date_time == (1980, 1, 1, 0, 0, 0)
                    for info in archive.infolist()
                )
            )
            self.assertTrue(
                all(
                    info.compress_type == zipfile.ZIP_DEFLATED
                    for info in archive.infolist()
                )
            )

    def test_wrong_exact_addon_id_is_rejected(self):
        with self.assertRaisesRegex(builder.PackageError, "add-on ID"):
            builder.build_package(
                self.source,
                self.root / "out",
                "script.example.other",
                ALLOWLIST,
                12345,
                SHA,
                SHA,
            )

    def test_invalid_addon_xml_forms_are_rejected(self):
        invalid = [
            "<addon",
            '<addon id="script.example.exact" name="Example"/>',
            addon_xml(version="1.2.beta"),
            addon_xml(version="1.2.3-omega"),
            addon_xml(version="1.2.3+oméga"),
            '<addon id="script.example.exact" id="script.other" version="1.0.0"/>',
        ]
        for index, xml in enumerate(invalid):
            with self.subTest(index=index):
                source = self.root / f"invalid-{index}"
                make_source(source, xml)
                with self.assertRaises(builder.PackageError):
                    builder.build_package(
                        source,
                        self.root / f"out-{index}",
                        ADDON_ID,
                        ALLOWLIST,
                        1,
                        SHA,
                        SHA,
                    )

    def test_missing_and_malformed_allowlist_entries_are_rejected(self):
        cases = [
            ["default.py", "resources/"],
            ["addon.xml", "missing.py", "resources/"],
            ["addon.xml", "../default.py", "resources/"],
            ["addon.xml", "/default.py", "resources/"],
            ["addon.xml", "resources\\icon.png"],
            ["addon.xml", "default.py", "resources//"],
            ["addon.xml", "default.py", "resources/./"],
            ["addon.xml", "resources/", "resources/icon.png"],
            ["addon.xml", "addon.xml", "resources/"],
        ]
        for index, entries in enumerate(cases):
            with self.subTest(entries=entries):
                with self.assertRaises(builder.PackageError):
                    builder.build_package(
                        self.source,
                        self.root / f"allow-{index}",
                        ADDON_ID,
                        entries,
                        1,
                        SHA,
                        SHA,
                    )

    def test_nested_allowlist_entries_are_rejected(self):
        for entry in ("resources/icon.png", "resources/nested/"):
            with self.subTest(entry=entry):
                with self.assertRaisesRegex(builder.PackageError, "top-level"):
                    builder._runtime_entries(["addon.xml", entry])

    def test_internal_and_outside_symlinks_are_rejected(self):
        outside = self.root / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        for index, target in enumerate((outside, self.source / "default.py")):
            link = self.source / "resources" / f"link-{index}"
            link.symlink_to(target)
            with self.subTest(target=target):
                with self.assertRaisesRegex(builder.PackageError, "symlink"):
                    self.build(f"symlink-{index}")
            link.unlink()

    def test_source_normalized_and_casefold_collisions_are_rejected(self):
        collision_sets = [
            ("resources/Readme.txt", "resources/README.txt"),
            ("resources/café.txt", "resources/café.txt"),
        ]
        for index, names in enumerate(collision_sets):
            created = []
            for name in names:
                path = self.source / name
                path.write_text(name, encoding="utf-8")
                created.append(path)
            with self.subTest(names=names):
                with self.assertRaisesRegex(builder.PackageError, "collision"):
                    self.build(f"collision-{index}")
            for path in created:
                path.unlink()

    def test_unapproved_or_missing_manifest_reference_is_rejected(self):
        (self.source / "addon.xml").write_text(
            addon_xml(asset="fanart.jpg"), encoding="utf-8"
        )
        (self.source / "fanart.jpg").write_bytes(b"fanart")
        with self.assertRaisesRegex(builder.PackageError, "manifest reference"):
            self.build("unapproved-reference")
        (self.source / "fanart.jpg").unlink()
        with self.assertRaisesRegex(builder.PackageError, "manifest reference"):
            self.build("missing-reference")

    def test_evidence_inputs_fail_closed(self):
        for run_id, candidate, head in (
            (0, SHA, SHA),
            ("1", SHA, SHA),
            (1, "A" * 40, SHA),
            (1, SHA, "abc"),
        ):
            with self.subTest(run_id=run_id, candidate=candidate, head=head):
                with self.assertRaises(builder.PackageError):
                    builder.build_package(
                        self.source,
                        self.root / "bad-evidence",
                        ADDON_ID,
                        ALLOWLIST,
                        run_id,
                        candidate,
                        head,
                    )


class ArchiveValidatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def archive(self, members):
        path = self.root / f"archive-{len(list(self.root.iterdir()))}.zip"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, data in members:
                    archive.writestr(name, data)
        return path

    def assert_rejected(self, members):
        path = self.archive(members)
        with self.assertRaises(builder.PackageError):
            builder.validate_package_archive(path, ADDON_ID, ALLOWLIST)

    def test_archive_rejects_traversal_absolute_backslash_and_wrong_root(self):
        for name in (
            f"{ADDON_ID}/../escape.py",
            "/absolute.py",
            f"{ADDON_ID}\\default.py",
            f"{ADDON_ID}//default.py",
            f"{ADDON_ID}/./default.py",
            "script.example.other/default.py",
        ):
            with self.subTest(name=name):
                self.assert_rejected([(name, b"x")])

    def test_archive_rejects_empty_and_dot_path_segments(self):
        manifest = addon_xml().encode("utf-8")
        valid = [
            (f"{ADDON_ID}/addon.xml", manifest),
            (f"{ADDON_ID}/default.py", b"print('ok')\n"),
            (f"{ADDON_ID}/resources/icon.png", b"icon"),
        ]
        for malformed in (
            f"{ADDON_ID}/resources//extra.txt",
            f"{ADDON_ID}/resources/./extra.txt",
        ):
            with self.subTest(malformed=malformed):
                self.assert_rejected(valid + [(malformed, b"extra")])

    def test_archive_rejects_duplicate_normalized_casefold_and_unapproved_members(self):
        cases = [
            [(f"{ADDON_ID}/default.py", b"a"), (f"{ADDON_ID}/default.py", b"b")],
            [(f"{ADDON_ID}/Readme.txt", b"a"), (f"{ADDON_ID}/README.txt", b"b")],
            [(f"{ADDON_ID}/café.txt", b"a"), (f"{ADDON_ID}/café.txt", b"b")],
            [(f"{ADDON_ID}/README.md", b"x")],
        ]
        for members in cases:
            with self.subTest(members=[name for name, _ in members]):
                self.assert_rejected(members)

    def test_archive_rejects_symlink_member(self):
        path = self.root / "symlink.zip"
        info = zipfile.ZipInfo(f"{ADDON_ID}/resources/link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(info, "../../outside")
        with self.assertRaisesRegex(builder.PackageError, "regular file"):
            builder.validate_package_archive(path, ADDON_ID, ALLOWLIST)


if __name__ == "__main__":
    unittest.main()
