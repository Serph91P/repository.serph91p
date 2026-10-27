"""Read-only original repository ZIP verification; never publishes or installs."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from xml.etree import ElementTree as ET
try:
    from tools.build_setup_bootstrap import (ROOT, PAGES, SOURCES, MAX_ZIP, SITE,
        source_url, original_manifest, catalog, local_files, validate_root)
except ModuleNotFoundError:
    from build_setup_bootstrap import (ROOT, PAGES, SOURCES, MAX_ZIP, SITE,
        source_url, original_manifest, catalog, local_files, validate_root)

ALLOWED_HOSTS = frozenset(('raw.githubusercontent.com', 'embydata.com',
                           'repo.kodinerds.net', 'serph91p.github.io', 'adamsbuilds.github.io'))


def checked_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS or
            parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError('non-public/non-allowlisted source URL')
    return url


class PublicRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    checked_url(url)
    request = urllib.request.Request(url, headers={'User-Agent': 'Kodi/21.2 (setup-contract-check)'})
    opener = urllib.request.build_opener(PublicRedirects())
    with opener.open(request, timeout=40) as response:
        checked_url(response.url)
        data = response.read(MAX_ZIP + 1)
    if len(data) > MAX_ZIP:
        raise ValueError('oversized public source')
    return data


def public_prerequisites(fetcher, local):
    """Missing unpublished candidates are explicit blockers, not weakened validation."""
    checks = []
    for source in SOURCES:
        url = PAGES + '/setup-bootstrap/' + source['id'] + '/addons.xml'
        try:
            data = fetcher(url)
            token = fetcher(url + '.md5')
            ready = (data == local[source['id'] + '/addons.xml'] and
                     token == local[source['id'] + '/addons.xml.md5'])
            checks.append({'url': url, 'ready': ready, 'reason': 'exact candidate bytes required'})
        except (OSError, ValueError) as exc:
            checks.append({'url': url, 'ready': False, 'reason': str(exc)})
    own_url = PAGES + '/addons.xml'
    try:
        data = fetcher(own_url)
        token = fetcher(own_url + '.md5').decode().strip().split()[0].lower()
        if hashlib.md5(data).hexdigest() != token:
            raise ValueError('own public catalog MD5 mismatch')
        root = ET.fromstring(data)
        if root.tag != 'addons':
            raise ValueError('invalid own public catalog')
        candidates = [ET.parse(ROOT / 'addon.xml').getroot(),
                      ET.parse(ROOT / 'script.serph91p.setup/addon.xml').getroot()]
        for addon in candidates:
            matches = [a for a in root if (a.get('id'), a.get('version')) ==
                       (addon.get('id'), addon.get('version'))]
            checks.append({'url': own_url, 'id': addon.get('id'), 'version': addon.get('version'),
                           'ready': len(matches) == 1,
                           'reason': 'candidate must be present exactly once in own public catalog'})
    except (OSError, ValueError, ET.ParseError, IndexError) as exc:
        checks.append({'url': own_url, 'ready': False, 'reason': str(exc)})
    return checks


def validate(fetcher=fetch):
    validate_root()
    local = local_files()
    reports = []
    for source in SOURCES:
        url = source_url(source)
        data = fetcher(url)
        original = original_manifest(data, source)
        if catalog(original, source) != local[source['id'] + '/addons.xml']:
            raise ValueError('bootstrap metadata differs from original except allowed relative path: ' + source['id'])
        reports.append({'id': source['id'], 'version': source['version'], 'url': url,
                        'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data),
                        'original_repository_verified': True,
                        'catalog_metadata_matches_original': True})
    prerequisites = public_prerequisites(fetcher, local)
    return {'original_repositories': reports, 'publication_prerequisites': prerequisites,
            'publication_ready': all(p['ready'] for p in prerequisites),
            'device_validated': False,
            'note': 'Only original repository addons are bootstrapped. No mirrored ZIPs, leaf federation, '
                    'publication, device actions or immutable-publication trust validation performed. '
                    'MD5 is a catalog change token, not a signature. Artwork URLs are preserved, not verified.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = validate()
    text = json.dumps(result, indent=2) + '\n'
    if args.report:
        try:
            from tools.build_setup_bootstrap import safe_write
        except ModuleNotFoundError:
            from build_setup_bootstrap import safe_write
        safe_write(args.report, text.encode())
    print(text)
