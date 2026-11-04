import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

FILE=Path(__file__).resolve().parents[1]/'addon-publication/check_arctic_package.py'
spec=importlib.util.spec_from_file_location('arctic_checker',FILE)
assert spec and spec.loader
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class ArcticCheckerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'addon.xml').write_text('<addon id="skin.arctic.fuse.3"/>')
        (self.root/'icon.png').write_bytes(b'icon');(self.root/'fanart.jpg').write_bytes(b'fanart')
        self.art={k:m.hashlib.sha256((self.root/k).read_bytes()).hexdigest() for k in m.ART}
        self.guard=patch.dict(m.ART,self.art);self.guard.start();self.addCleanup(self.guard.stop)
    def test_only_known_image_errors_are_accepted(self):
        m.validate_baseline(self.root,list(m.BASELINE_ERRORS))
        m.validate_baseline(self.root,[])
    def test_every_other_error_stays_fatal(self):
        for error in ['Invalid PO file','Invalid XML data','dependency missing','icon does not exist']:
            with self.assertRaises(ValueError):m.validate_baseline(self.root,list(m.BASELINE_ERRORS)+[error])
    def test_changed_art_requires_explicit_new_review(self):
        (self.root/'icon.png').write_bytes(b'changed')
        with self.assertRaises(ValueError):m.validate_baseline(self.root,[])
    def test_policy_cannot_apply_to_another_addon(self):
        (self.root/'addon.xml').write_text('<addon id="plugin.other"/>')
        with self.assertRaises(ValueError):m.validate_baseline(self.root,[])
