"""Read-only live check of the candidate's native upstream catalog contract."""
import argparse
import collections
import gzip
import hashlib
import json
from pathlib import Path
import sys
import urllib.request
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'script.serph91p.setup'))
from resources.lib.setupwizard.addons import (REQUIREMENTS, PROFILE_REQUIREMENTS,
                                              MEDIA_REQUIREMENTS, version_at_least)


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Kodi/21.2 (setup-contract-check)'})
    with urllib.request.urlopen(request, timeout=40) as response:
        if not response.url.startswith('https://'):
            raise ValueError('non-TLS catalog redirect')
        data = response.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024:
        raise ValueError('oversized upstream catalog')
    return gzip.decompress(data) if data.startswith(b'\x1f\x8b') else data


def validate():
    root = ET.parse(ROOT / 'addon.xml').getroot()
    catalog = collections.defaultdict(list)
    reports = []
    for directory in root.findall('./extension/dir'):
        url = directory.findtext('info')
        checksum_url = directory.findtext('checksum')
        if not checksum_url or not url:
            raise ValueError('repository dir without checksum/info')
        data = fetch(url)
        expected = fetch(checksum_url).decode().strip().split()[0].lower()
        if hashlib.md5(data).hexdigest() != expected:
            raise ValueError('upstream catalog changed during read or checksum mismatch: ' + url)
        parsed = ET.fromstring(data)
        if parsed.tag != 'addons':
            raise ValueError('invalid upstream catalog')
        reports.append({'url': url, 'addons': len(parsed), 'md5_change_token_matches': True,
                        'sha256_downloaded_catalog': hashlib.sha256(data).hexdigest()})
        for addon in parsed:
            catalog[addon.get('id')].append((addon.get('version'), url))
    duplicates = [(aid, version) for aid, entries in catalog.items()
                  for version, count in collections.Counter(v for v, _ in entries).items() if count > 1]
    if duplicates:
        raise ValueError('ambiguous equal-version federated IDs: ' + repr(duplicates))
    required = []
    for req in REQUIREMENTS + PROFILE_REQUIREMENTS + MEDIA_REQUIREMENTS:
        if req.addon_id in ('skin.amber', 'plugin.video.youtube', 'pvr.iptvsimple',
                             'resource.images.weathericons.white', 'resource.images.studios.coloured'):
            required.append({'id': req.addon_id, 'source': 'official Kodi/platform repository',
                             'runtime_acceptance_required': True})
            continue
        versions = [v for v, _ in catalog.get(req.addon_id, []) if version_at_least(v, req.min_version)]
        if not versions:
            raise ValueError('required addon unavailable at minimum: ' + req.addon_id)
        required.append({'id': req.addon_id, 'available_versions': versions})
    return {'catalogs': reports, 'ambiguous_duplicates': duplicates, 'requirements': required,
            'note': 'Catalog MD5 tokens are not signatures or package SHA-256 pins. No publication or device installation performed.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = validate()
    text = json.dumps(result, indent=2) + '\n'
    if args.report:
        args.report.write_text(text)
    print(text)
