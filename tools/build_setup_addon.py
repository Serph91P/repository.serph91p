"""Deterministic safe package builder for the wizard source directory."""
from __future__ import annotations
import argparse
import hashlib
import os
import stat
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

ADDON_ID = "script.serph91p.setup"
ROOT = Path(__file__).resolve().parents[1] / ADDON_ID
STAMP = (1980, 1, 1, 0, 0, 0)


def build(output_dir: Path) -> Path:
    output_dir = Path(output_dir)
    if output_dir.exists() and (output_dir.is_symlink() or not output_dir.is_dir()):
        raise ValueError("output path must be a real directory")
    root = ElementTree.parse(ROOT / "addon.xml").getroot()
    if root.tag != "addon" or root.attrib.get("id") != ADDON_ID:
        raise ValueError("unexpected add-on identity")
    if root.attrib.get("version") != "0.4.1":
        raise ValueError("unexpected add-on version")
    refs = set()
    for node in root.iter():
        for attr in ("library", "icon", "fanart"):
            if node.attrib.get(attr): refs.add(node.attrib[attr])
    allowed = {
        'addon.xml', 'default.py',
        'resources/lib/setupwizard/__init__.py',
        'resources/lib/setupwizard/addons.py',
        'resources/lib/setupwizard/config.py',
        'resources/lib/setupwizard/templates.py',
        'resources/lib/setupwizard/ui.py',
        'resources/lib/setupwizard/state.py',
        'resources/lib/setupwizard/origins.py',
        'resources/lib/setupwizard/pvr.py',
        'resources/lib/setupwizard/catalog.py',
        'resources/lib/setupwizard/activation.py',
        'resources/lib/setupwizard/menus.py',
        'resources/lib/setupwizard/profiles.py',
        'resources/lib/setupwizard/layouts.py',
        'resources/lib/setupwizard/touch.py',
        'resources/lib/setupwizard/navigation.py',
        'resources/lib/setupwizard/common_layouts.py',
        'resources/lib/setupwizard/regional.py',
        'resources/playlists/top-rated-movies.xsp',
        'resources/playlists/continue-movies.xsp',
        'resources/playlists/continue-episodes.xsp',
        'resources/templates/arctic-fuse-3-minimal.json',
        'resources/templates/arctic-reference.json',
    }
    files = []
    for rel in sorted(allowed):
        path = ROOT.joinpath(*PurePosixPath(rel).parts)
        current = ROOT
        if ROOT.is_symlink():
            raise ValueError('symlink source root forbidden')
        for part in PurePosixPath(rel).parts[:-1]:
            current = current / part
            if current.is_symlink() or not current.is_dir():
                raise ValueError('symlink/special source directory forbidden')
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError('non-regular package file')
        files.append((rel, path))
    files.sort()
    names = {rel for rel, _ in files}
    if not {"addon.xml", "default.py"}.issubset(names) or not refs.issubset(names):
        raise ValueError("required source or manifest reference missing")
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "script.serph91p.setup-0.4.1.zip"
    if target.is_symlink() or (target.exists() and not target.is_file()): raise ValueError("package target must be a regular file")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel, path in files:
            info = zipfile.ZipInfo(f"{ADDON_ID}/{rel}", STAMP)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            zf.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(target) as zf:
        actual = zf.namelist()
        if actual != [f"{ADDON_ID}/{rel}" for rel, _ in files]: raise ValueError("archive members mismatch")
        for info in zf.infolist():
            if PurePosixPath(info.filename).is_absolute() or ".." in PurePosixPath(info.filename).parts:
                raise ValueError("unsafe archive path")
            zf.read(info)
    print(f"{target} sha256={hashlib.sha256(target.read_bytes()).hexdigest()} members={len(files)}")
    return target

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    build(parser.parse_args().output_dir)
