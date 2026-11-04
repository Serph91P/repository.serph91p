#!/usr/bin/env python3
"""Native Kodi checker with original dependency feed and frozen upstream art.

The official CLI checks only the official dependency catalog and has no native
per-image dimension exemption. Keep the unchanged upstream images; tolerate
only their two exact dimension messages, bound to their exact original bytes.
Everything else, including real dependencies and PO syntax, remains fatal.
"""
import argparse
import hashlib
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ADDON_ID='skin.arctic.fuse.3'
DEPENDENCY_FEEDS=(
    'https://raw.githubusercontent.com/jurialmunkey/repository.jurialmunkey/master/repo/zips/addons.xml',
    'https://raw.githubusercontent.com/jurialmunkey/repository.jurialmunkey/master/omega/zips/addons.xml',
)
ART={
    'icon.png':'ef6a35b6add6da0b71fe34ac26b6637c34b7642d3ffc85f94e45fe40555f41b5',
    'fanart.jpg':'e94d311931abdc895d3f6720ea7e2de530ce5021c7fc0a8357bbee8c3fa8d5e8',
}
BASELINE_ERRORS={
    'icon should have either 256x256 or 512x512 but it has 600x584',
    'fanart should have either 1280x720 or 1920x1080 or 3840x2160 but it has 1980x1080',
}


def validate_baseline(path,errors):
    if ET.parse(path/'addon.xml').getroot().get('id')!=ADDON_ID:
        raise ValueError('art baseline is restricted to the maintained Arctic Fuse skin')
    for relative,digest in ART.items():
        if hashlib.sha256((path/relative).read_bytes()).hexdigest()!=digest:
            raise ValueError('upstream artwork changed; explicit baseline review required: '+relative)
    unexpected=set(errors)-BASELINE_ERRORS
    if unexpected:
        raise ValueError('unexpected Kodi checker errors: '+repr(sorted(unexpected)))


def required_feed_entries(xml,required):
    root=ET.fromstring(xml)
    if root.tag!='addons':
        raise ValueError('invalid dependency catalog root')
    # The original feeds also contain legacy Nexus-only add-ons with versions
    # the checker cannot parse. Do not parse or normalize unrelated add-ons.
    return [element for element in root.findall('addon') if element.get('id') in required]


def main(path):
    from kodi_addon_checker.__main__ import check_artifact
    from kodi_addon_checker.check_addon import get_all_repo_addons
    from kodi_addon_checker.addons.Repository import Repository
    from kodi_addon_checker.addons.Addon import Addon
    from kodi_addon_checker.reporter import ReportManager

    validate_baseline(path,[])
    class Collector:
        def __init__(self): self.records=[]
        def report(self,record):
            self.records.append(record)
            print(str(record))
    ReportManager.register(Collector,'serph91p',True)
    repos=get_all_repo_addons()
    # Native Repository.find picks the highest available version. The original
    # feed supplements official metadata; no catalog is mirrored or published.
    required={entry.get('addon') for entry in ET.parse(path/'addon.xml').findall('./requires/import')}
    if not getattr(repos['omega'],'addons',None):
        raise ValueError('official dependency catalog unavailable; fail closed')
    for feed in DEPENDENCY_FEEDS:
        response=Repository._session.get(feed,timeout=(30,30))
        response.raise_for_status()
        entries=required_feed_entries(response.content,required)
        if not entries:
            raise ValueError('original dependency feed has no required entries')
        repos['omega'].addons.extend(Addon(entry) for entry in entries)
    args=argparse.Namespace(branch='omega',PR=False,allow_folder_id_mismatch=False,
                            skip_dependency_checks=False,reporter=['serph91p'])
    report=check_artifact(str(path),args,repos)
    records=ReportManager.reporters['serph91p'][0].records
    errors=[record.message for record in records if record.log_level=='ERROR']
    if report.problem_count!=len(errors):
        raise ValueError('incomplete native checker report')
    validate_baseline(path,errors)
    print('Native checker passed; only frozen upstream image dimensions exempted.')

if __name__=='__main__':
    try: main(Path(sys.argv[1]).resolve())
    except (ValueError,OSError) as error: raise SystemExit(str(error))
