"""Build native Kodi dependency bundles, without downloads or install code."""
from __future__ import annotations
import argparse
import hashlib
import io
from pathlib import Path
import sys
from xml.etree import ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'script.serph91p.setup'))
from resources.lib.setupwizard.addons import (REQUIREMENTS, PROFILE_REQUIREMENTS,
    MEDIA_REQUIREMENTS)
from resources.lib.setupwizard.profiles import PROFILES as ALL_PROFILES, requirements_for
PROFILES = tuple(p for p in ALL_PROFILES if not p.retired)

VERSION = '0.2.0'


def manifest(profile):
    if profile not in PROFILES:
        raise ValueError('unknown fixed profile')
    addon_id = 'script.module.serph91p.setup.' + profile.key
    root = ET.Element('addon', {'id': addon_id, 'name': 'Serph91P Komplettpaket: ' + profile.label,
                              'version': VERSION, 'provider-name': 'Serph91P'})
    imports = ET.SubElement(root, 'requires')
    ET.SubElement(imports, 'import', addon='xbmc.python', version='3.0.0')
    required = requirements_for(
        profile, REQUIREMENTS, PROFILE_REQUIREMENTS, MEDIA_REQUIREMENTS)
    for req in required:
        if req.addon_id.startswith('repository.'):
            raise ValueError('repository addons require explicit native installation, not imports')
        version = req.min_version_string or '.'.join(map(str, req.min_version + (0,) * max(0, 3 - len(req.min_version))))
        ET.SubElement(imports, 'import', addon=req.addon_id, version=version)
    ET.SubElement(root, 'extension', point='xbmc.python.module', library='lib')
    metadata = ET.SubElement(root, 'extension', point='xbmc.addon.metadata')
    ET.SubElement(metadata, 'summary', lang='en_GB').text = 'Fixed native dependency bundle: ' + profile.label
    ET.SubElement(metadata, 'description', lang='en_GB').text = (
        'Test candidate. Install explicitly through Kodi Install from ZIP. Kodi installs the selected '
        'skin and fixed media dependencies through its native dependency resolver. Requires Serph91P '
        'Repository 1.0.3 and the original Jurialmunkey, Emby beta and Kodinerds repositories '
        'already explicitly installed and their own catalogs loaded. Repository addons cannot be '
        'installed as dependencies. No installer code, credentials, '
        'settings changes, layout changes or wizard payload. Not device-validated.')
    ET.SubElement(metadata, 'license').text = 'MIT'
    ET.SubElement(metadata, 'platform').text = 'all'
    ET.indent(root)
    return addon_id, ET.tostring(root, encoding='utf-8', xml_declaration=True)


def build(profile, output_dir):
    addon_id, xml = manifest(profile)
    output_dir = Path(output_dir).absolute()
    if any(p.is_symlink() for p in (output_dir, *output_dir.parents)):
        raise ValueError('symlink output directory')
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / (addon_id + '-' + VERSION + '.zip')
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValueError('package target must be a regular file')
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for rel, payload in (('addon.xml', xml), ('lib/__init__.py', b'"""Native dependency marker; no install or startup code."""\n')):
            item = zipfile.ZipInfo(addon_id + '/' + rel, date_time=(1980, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            archive.writestr(item, payload)
    target.write_bytes(data.getvalue())
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=[p.key for p in PROFILES])
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    for profile in PROFILES:
        if args.profile and profile.key != args.profile:
            continue
        package = build(profile, args.output_dir)
        print(str(package) + ' sha256=' + hashlib.sha256(package.read_bytes()).hexdigest())
