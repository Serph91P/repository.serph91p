"""Generate and validate deterministic local candidate ZIP."""
import tempfile
import unittest
import zipfile
import shutil
from unittest.mock import patch
from pathlib import Path
from tools.build_setup_addon import build, ROOT

class PackageTests(unittest.TestCase):
    def test_zip_contents_and_repeatable_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            first_dir = Path(tmp) / "first"
            package = build(first_dir)
            first_bytes = package.read_bytes()
            with zipfile.ZipFile(package) as zf:
                self.assertTrue(zf.namelist())
                self.assertTrue(all(n.startswith("script.serph91p.setup/") for n in zf.namelist()))
                self.assertFalse(any(".." in Path(n).parts for n in zf.namelist()))
                self.assertIn("script.serph91p.setup/addon.xml", zf.namelist())
                self.assertIn("script.serph91p.setup/default.py", zf.namelist())
                self.assertIn("script.serph91p.setup/resources/templates/arctic-fuse-3-minimal.json", zf.namelist())
            second = build(Path(tmp) / "second")
            self.assertEqual(first_bytes, second.read_bytes())

    def test_symlink_runtime_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            shutil.copytree(ROOT, source)
            external = root / 'external.py'
            external.write_text('must not ship')
            (source / 'default.py').unlink()
            (source / 'default.py').symlink_to(external)
            with patch('tools.build_setup_addon.ROOT', source):
                with self.assertRaises(ValueError):
                    build(root / 'output')

    def test_output_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            actual = root / 'actual'
            actual.mkdir()
            link = root / 'output'
            link.symlink_to(actual, target_is_directory=True)
            with self.assertRaises(ValueError):
                build(link)

    def test_manifest_traversal_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            shutil.copytree(ROOT, source)
            manifest = source / 'addon.xml'
            manifest.write_text(manifest.read_text().replace('library="default.py"', 'library="../external.py"'))
            with patch('tools.build_setup_addon.ROOT', source):
                with self.assertRaises(ValueError):
                    build(root / 'output')

if __name__ == "__main__": unittest.main()
