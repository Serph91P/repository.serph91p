"""Build the local repository bootstrap candidate without publishing anything."""
from pathlib import Path
import hashlib
import stat
import zipfile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
MEMBERS = ('addon.xml', 'resources/icon.png', 'resources/fanart.jpg')


def build(output_dir):
    # Validate the metadata-only feed contract, without adding hosted metadata to the ZIP.
    try:
        from tools.build_setup_bootstrap import validate_root, local_files
    except ModuleNotFoundError:
        from build_setup_bootstrap import validate_root, local_files
    root = validate_root()
    local_files()
    out = Path(output_dir)
    for parent in (out, *out.parents):
        if parent.is_symlink():
            raise ValueError('symlink output path')
    out.mkdir(parents=True, exist_ok=True)
    target = out / 'repository.serph91p-1.0.2.zip'
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValueError('invalid repository target')
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in MEMBERS:
            source = ROOT / rel
            for parent in (source, *source.parents):
                if parent.is_symlink():
                    raise ValueError('symlink source')
            if not stat.S_ISREG(source.lstat().st_mode):
                raise ValueError('non-regular source')
            info = zipfile.ZipInfo('repository.serph91p/' + rel, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            z.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(target) as z:
        if z.testzip() is not None or z.namelist() != ['repository.serph91p/' + p for p in MEMBERS]:
            raise ValueError('repository archive failed validation')
    print(str(target) + ' sha256=' + hashlib.sha256(target.read_bytes()).hexdigest())
    return target


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--output-dir', type=Path, required=True)
    build(p.parse_args().output_dir)
