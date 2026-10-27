"""Deterministic metadata-only bootstrap site; no publication or ZIP mirroring."""
from __future__ import annotations
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import stat
from xml.etree import ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'setup-bootstrap'
PAGES = 'https://serph91p.github.io/repository.serph91p'
SOURCES = (
    {'id': 'repository.jurialmunkey', 'version': '3.4',
     'datadir': 'https://raw.githubusercontent.com/jurialmunkey/repository.jurialmunkey/master/',
     'path': 'repository.jurialmunkey-3.4.zip',
     'sha256': '972ba8bda0dd16108a1601534e547a774522d73cd2c7919ce651a2d32af7a3fd'},
    {'id': 'repository.beta.emby.kodi', 'version': '1.0.11',
     'datadir': 'https://embydata.com/downloads/addons/xbmb3c/multi-repo/repositories/',
     'path': 'repository.beta.emby.kodi/repository.beta.emby.kodi-1.0.11.zip',
     'sha256': '05634d92540987f4a9bc62e71472a19e8b569a4428f37a35ba1ca51b025b6f61'},
    {'id': 'repository.kodinerds', 'version': '7.0.1.9',
     'datadir': 'https://repo.kodinerds.net/addons/',
     'path': 'repository.kodinerds/repository.kodinerds-7.0.1.9.zip',
     'sha256': '690771ac6c21a7b726a58401de172799cbacc257c73b8ca17885d1bd5345e8ea'},
    {'id': 'repository.adamsbuilds', 'version': '1.0',
     'datadir': 'https://adamsbuilds.github.io/repo/',
     'path': 'repository.adamsbuilds-1.0.zip',
     'sha256': '915fc41dd3f45c4a6ae32441626f2234a8e201b372eb1da29cddbdc6e3b77334'},
)
MAX_ZIP = 8 * 1024 * 1024
MAX_MANIFEST = 256 * 1024


def source_url(source):
    return source['datadir'] + source['path']


def parse_xml(data):
    if len(data) > MAX_MANIFEST or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('unsafe or oversized XML')
    return ET.fromstring(data)


def original_manifest(data, source):
    if len(data) > MAX_ZIP or hashlib.sha256(data).hexdigest() != source['sha256']:
        raise ValueError('original ZIP SHA-256 mismatch or size limit')
    member = source['id'] + '/addon.xml'
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) > 1024 or archive.namelist().count(member) != 1:
            raise ValueError('missing or ambiguous original manifest')
        item = archive.getinfo(member)
        mode = item.external_attr >> 16
        if item.file_size > MAX_MANIFEST or stat.S_ISLNK(mode):
            raise ValueError('unsafe manifest member')
        root = parse_xml(archive.read(item))
    if root.tag != 'addon' or root.get('id') != source['id'] or root.get('version') != source['version']:
        raise ValueError('original repository identity/version mismatch')
    extensions = root.findall('extension')
    main = [e.get('point') for e in extensions if e.get('point') != 'xbmc.addon.metadata']
    if main != ['xbmc.addon.repository'] or len(root.findall("extension[@point='xbmc.addon.metadata']")) != 1:
        raise ValueError('original is not a normal repository addon')
    return root


def catalog(root, source):
    root = copy.deepcopy(root)
    if source['id'] in ('repository.jurialmunkey','repository.adamsbuilds'):
        metadata = root.find("extension[@point='xbmc.addon.metadata']")
        if metadata.find('path') is not None:
            raise ValueError('unexpected original metadata path')
        ET.SubElement(metadata, 'path').text = source['path']
    outer = ET.Element('addons')
    outer.append(root)
    ET.indent(outer, space='    ')
    return ET.tostring(outer, encoding='utf-8', xml_declaration=True) + b'\n'


def safe_write(path, data):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('symlink output path')
    if path.exists() and not path.is_file():
        raise ValueError('non-regular output path')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def local_files(site=SITE):
    """Validate checked-in metadata and return exactly two files per source."""
    files = {}
    for source in SOURCES:
        for name in ('addons.xml', 'addons.xml.md5'):
            path = Path(site) / source['id'] / name
            if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
                raise ValueError('unsafe bootstrap source')
            files[source['id'] + '/' + name] = path.read_bytes()
        data = files[source['id'] + '/addons.xml']
        outer = parse_xml(data)
        if outer.tag != 'addons' or len(outer) != 1:
            raise ValueError('bootstrap must contain exactly one repository')
        addon = outer[0]
        if addon.tag != 'addon' or (addon.get('id'), addon.get('version')) != (source['id'], source['version']):
            raise ValueError('bootstrap identity/version mismatch')
        main = [e.get('point') for e in addon.findall('extension') if e.get('point') != 'xbmc.addon.metadata']
        if main != ['xbmc.addon.repository']:
            raise ValueError('bootstrap contains non-repository content')
        paths = addon.findall("extension[@point='xbmc.addon.metadata']/path")
        expected = [source['path']] if source['id'] in ('repository.jurialmunkey','repository.adamsbuilds') else []
        if [p.text for p in paths] != expected or addon.find('path') is not None:
            raise ValueError('invalid relative metadata path')
        if files[source['id'] + '/addons.xml.md5'] != (hashlib.md5(data).hexdigest() + '\n').encode():
            raise ValueError('bootstrap MD5 change token mismatch')
    return files


def validate_root():
    root = ET.parse(ROOT / 'addon.xml').getroot()
    if (root.get('id'), root.get('version')) != ('repository.serph91p', '1.0.3'):
        raise ValueError('unexpected own repository identity/version')
    dirs = root.findall("extension[@point='xbmc.addon.repository']/dir")
    expected = [(PAGES + '/addons.xml', PAGES)] + [
        (PAGES + '/setup-bootstrap/' + s['id'] + '/addons.xml', s['datadir']) for s in SOURCES]
    if len(dirs) != len(expected):
        raise ValueError('own repository must expose own catalog and declared repository-only bootstrap catalogs')
    for directory, (info, datadir) in zip(dirs, expected):
        if (directory.findtext('info'), directory.findtext('checksum'), directory.findtext('datadir')) != (info, info + '.md5', datadir):
            raise ValueError('unexpected repository feed contract')
        info_node, data_node = directory.find('info'), directory.find('datadir')
        if (info_node is None or data_node is None or
                info_node.get('compressed') != 'false' or data_node.get('zip') != 'true'):
            raise ValueError('unexpected feed encoding')
        if info != PAGES + '/addons.xml' and directory.attrib != {'minversion': '21.0.0', 'maxversion': '21.9.999'}:
            raise ValueError('bootstrap catalogs must be gated to Kodi 21')
    if any(i.get('addon', '').startswith('repository.') for i in root.findall('requires/import')):
        raise ValueError('repository addons must not be dependency imports')
    return root


def build(output_dir):
    validate_root()
    files = local_files()
    output = Path(output_dir)
    for relative, data in files.items():
        safe_write(output / 'setup-bootstrap' / relative, data)
    return {str(Path('setup-bootstrap') / p): hashlib.sha256(data).hexdigest() for p, data in files.items()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.output_dir), indent=2))
