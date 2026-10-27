"""Check native Skin Shortcuts output and request its supported rebuild.

Do not edit active skin XML or treat a queued RunScript/JSON-RPC ACK as success.
"""
from pathlib import Path,PurePosixPath
import re
import time
from xml.etree import ElementTree as ET
from .config import _profile,MAX_FILE_BYTES
from .navigation import load_bindings
from .common_layouts import common_payloads
from .activation import active_skin

SKINS={'amber':'skin.amber','touch':'skin.estuary.modv2'}
BUILD='RunScript(script.skinshortcuts,type=buildxml&mainmenuID=9000&group=mainmenu)'
DIRTY='SetProperty(skinshortcuts-reloadmainmenu,True,home)'


def _xml(data):
    if len(data)>MAX_FILE_BYTES or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('unsafe native menu XML')
    return ET.fromstring(data)


def _read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_FILE_BYTES:
        raise ValueError('native menu file not safely readable')
    return _xml(path.read_bytes())


def _expected(profile,key):
    bindings=load_bindings(profile,key)
    payloads=common_payloads(profile,key,bindings)
    prefix='skin.amber-' if key=='amber' else ''
    rel='addon_data/script.skinshortcuts/'+prefix+'mainmenu.DATA.xml'
    tree=_xml(payloads[rel])
    return [(n.findtext('label'),n.findtext('action')) for n in tree.findall('shortcut')]


def current(profile,key,api):
    if key=='arctic':
        return True  # Arctic uses Skin Variables, not the Skin Shortcuts compiler.
    try:
        if key in ('rotary','nimbus'):
            from .adams import native_current
            return native_current(api,key,_profile(profile),load_bindings(profile,key))
        if key not in SKINS or active_skin(api)!=SKINS[key]:
            return False
        expected=_expected(_profile(profile),key)
        response=api.rpc('Addons.GetAddonDetails',{'addonid':SKINS[key],'properties':['path']})
        addon=response.get('result',{}).get('addon',{})
        if addon.get('addonid')!=SKINS[key] or not isinstance(addon.get('path'),str):
            return False
        root=Path(addon['path'])
        if not root.is_absolute() or root.is_symlink():
            return False
        metadata=_read(root/'addon.xml')
        if metadata.get('id')!=SKINS[key]:
            return False
        folders=[n.get('folder','') for n in metadata.findall("extension[@point='xbmc.gui.skin']/res")]
        if not folders:
            return False
        for folder in folders:
            relative=PurePosixPath(folder)
            if not folder or relative.is_absolute() or any(p in ('.','..') for p in relative.parts):
                return False
            path=root.joinpath(*relative.parts)/'script-skinshortcuts-includes.xml'
            path.resolve().relative_to(root.resolve())
            tree=_read(path)
            include=tree.find("include[@name='skinshortcuts-mainmenu']")
            if include is None:
                return False
            actual=[]
            for item in include.findall('item'):
                visible=item.findtext('visible','')
                guard=re.search(r'String\.IsEqual\(System\.ProfileName,([^)]*)\)',visible)
                if guard and guard.group(1)!=api.xbmc.getInfoLabel('System.ProfileName'):
                    continue
                actual.append((item.findtext('label'),[n.text for n in item.findall('onclick')]))
            if len(actual)!=len(expected) or any(label!=a or action not in actions
                    for (label,action),(a,actions) in zip(expected,actual)):
                return False
        return True
    except (OSError,ValueError,TypeError,KeyError,AttributeError,RuntimeError,ET.ParseError):
        return False


def refresh(profile,key,api,monitor,*,approved=False,timeout=30,
            clock=time.monotonic,sleep=time.sleep):
    if approved is not True:
        raise ValueError('native menu rebuild not approved')
    if key in ('rotary','nimbus'):
        from .adams import refresh_native
        refresh_native(api,key,profile,load_bindings(profile,key))
        deadline=clock()+timeout
        while not monitor.abortRequested() and clock()<deadline:
            if current(profile,key,api):return
            sleep(.25)
        raise RuntimeError('native Adams menu output not confirmed; setup remains incomplete')
    if key not in SKINS or active_skin(api)!=SKINS[key]:
        raise ValueError('selected shared-menu skin must be active and confirmed')
    if current(profile,key,api):
        return
    api.xbmc.executebuiltin(DIRTY,wait=True)
    api.xbmc.executebuiltin(BUILD,wait=False)
    deadline=clock()+timeout
    while not monitor.abortRequested():
        if current(profile,key,api):
            return
        if clock()>=deadline:
            break
        sleep(.25)
    raise RuntimeError('native menu output not confirmed; setup remains incomplete')
