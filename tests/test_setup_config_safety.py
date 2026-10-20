import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "script.serph91p.setup/resources/lib/setupwizard/config.py"
spec = importlib.util.spec_from_file_location("setupwizard_config", MODULE)
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)
TEMPLATE = REPO / "script.serph91p.setup/resources/templates/arctic-fuse-3-minimal.json"


class SetupConfigSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kodi-config-test-", dir=os.environ.get("TMPDIR")))
        self.profile = self.tmp / "profile"
        self.profile.mkdir()
        self.backups = self.profile / "setupwizard-backups"
        self.backups.mkdir()
        self.backup = self.backups / "test-1"
        self.template = TEMPLATE.read_bytes()
        self.spec = json.loads(self.template)

    def target(self, rel):
        path = self.profile / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def apply(self):
        return config.apply_template(self.profile, self.backup, self.template)

    def test_apply_uses_profile_relative_allowlisted_targets_and_merges_settings(self):
        settings = self.profile / config.SKIN_SETTINGS
        settings.parent.mkdir(parents=True)
        settings.write_text('<settings version="2"><setting id="my.private.setting">keep me</setting><setting id="HomeSwitcher.1101.Name">old</setting></settings>')
        changed = self.apply()
        self.assertEqual(len(changed), 6)
        root = ET.parse(settings).getroot()
        values = {node.get("id"): node.text for node in root.findall("setting")}
        self.assertEqual(values["my.private.setting"], "keep me")
        self.assertEqual(values["HomeSwitcher.1101.Name"], "Serien")
        self.assertEqual(values['HomeSwitcher.Home.Shortcut.Path'], 'ActivateWindow(1181)')
        self.assertEqual(values['HomeSwitcher.Home.Shortcut.Target'] or '', '')
        types = {node.get('id'): node.get('type') for node in root.findall('setting')}
        for key in config.SAFE_SETTINGS:
            self.assertEqual(types[key], 'bool' if key.startswith('homeswitcher.') else 'string')
        for n in ("1101", "1102", "1103"):
            self.assertEqual(values[f"HomeSwitcher.{n}.Toggle"], "true")
        self.assertTrue((self.profile / config.SKIN_NODE / "skinvariables-shortcut-1103widgets.json").is_file())
        manifest = json.loads((self.backup / config.MANIFEST).read_text())
        self.assertEqual({entry["path"] for entry in manifest["files"]}, config.ALLOWED_TARGETS)
        self.assertTrue(all(entry["path"].startswith("addon_data/") for entry in manifest["files"]))

    def test_noop_does_not_create_backup(self):
        for item in config.validate_template(self.template)["files"]:
            path = self.target(item["path"])
            path.write_text(item["content"])
        settings = self.target(config.SKIN_SETTINGS)
        settings.write_bytes(config._merge_skin_settings(None, config.SAFE_SETTINGS))
        self.assertEqual(self.apply(), [])
        self.assertFalse(self.backup.exists())

    def test_restore_round_trip_and_retry_after_partial_restore(self):
        old = self.target(next(iter(config.ALLOWED)))
        old.write_text('{"previous":true}')
        changed = self.apply()
        self.assertEqual(len(changed), 6)
        self.assertEqual(set(config.rollback(self.profile, self.backup)), set(changed))
        self.assertEqual(old.read_text(), '{"previous":true}')
        self.assertEqual(config.rollback(self.profile, self.backup), [])

    def test_drift_rejected_before_any_restore(self):
        self.apply()
        first = self.profile / next(iter(config.ALLOWED))
        first.write_text('external edit')
        second = self.profile / config.SKIN_SETTINGS
        before = second.read_bytes()
        with self.assertRaises(config.LayoutConflict):
            config.rollback(self.profile, self.backup)
        self.assertEqual(second.read_bytes(), before)

    def test_manifest_truncation_and_backup_tampering_rejected(self):
        self.apply()
        path = self.backup / config.MANIFEST
        original = path.read_bytes()
        path.write_bytes(original[:-4])
        with self.assertRaises(Exception):
            config.rollback(self.profile, self.backup)
        path.write_bytes(original)
        # The default profile had no preimage; apply a second fixture with one.
        self.profile = self.tmp / "profile-with-preimage"
        self.profile.mkdir()
        (self.profile / "setupwizard-backups").mkdir()
        rel = next(iter(config.ALLOWED))
        preimage = self.target(rel)
        preimage.write_bytes(b"preimage")
        self.backup = self.profile / "setupwizard-backups" / "tamper"
        self.apply()
        oldfile = self.backup / "files" / rel
        oldfile.write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            config.rollback(self.profile, self.backup)

    def test_rejects_symlink_profile_and_backup_ancestors(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        profile_link = self.tmp / "profile-link"
        profile_link.symlink_to(self.profile, target_is_directory=True)
        with self.assertRaises(ValueError):
            config.apply_template(profile_link, self.backup, self.template)
        # A symlink in the allowed backup ancestry is rejected before creation.
        (self.profile / "setupwizard-backups").rename(self.profile / "real-backups")
        (self.profile / "setupwizard-backups").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            config.apply_template(self.profile, self.profile / "setupwizard-backups" / "bad", self.template)

    def test_rejects_backup_outside_managed_profile_root(self):
        with self.assertRaises(ValueError):
            config.apply_template(self.profile, self.tmp / "external" / "backup", self.template)

    def test_apply_write_failure_leaves_full_backup_and_can_restore(self):
        target = self.target(next(iter(config.ALLOWED)))
        target.write_bytes(b"previous bytes")
        atomic = config._atomic
        writes = 0
        def fail_on_second_target(path, data):
            nonlocal writes
            if Path(path).is_relative_to(self.profile) and "/setupwizard-backups/" not in str(path):
                writes += 1
                if writes == 2:
                    raise OSError("injected target write failure")
            return atomic(path, data)
        with mock.patch.object(config, "_atomic", side_effect=fail_on_second_target):
            with self.assertRaises(OSError):
                self.apply()
        self.assertTrue((self.backup / config.MANIFEST).is_file())
        # Rollback accepts targets already at old state as well as applied new state.
        config.rollback(self.profile, self.backup)
        self.assertEqual(target.read_bytes(), b"previous bytes")

    def test_rejects_mutated_or_partial_skin_settings_allowlist(self):
        altered = json.loads(self.template)
        altered["skin_settings"]["HomeSwitcher.1101.Toggle"] = "false"
        with self.assertRaises(ValueError):
            config.validate_template(json.dumps(altered).encode())


if __name__ == "__main__":
    unittest.main()
