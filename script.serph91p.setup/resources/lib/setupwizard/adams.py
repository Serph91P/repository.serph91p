"""Adams userdata adapters; native skins/helper render, never our skin XML.

Rotary 0.0.1: six native shortcuts, shared wizard list submenus, no widgets.
Nimbus Plus 0.2.07–0.2.08/helper 0.0.98–0.0.99: verified userdata contract.
Its dialog routes have no bulk-import API. Build a backup-able userdata snapshot
in memory, preserve unrelated rows, then use only its narrow native generators.
Never touch Kodi's addon DB, favourites, other keymaps or installed skin XML.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import stat
from xml.etree import ElementTree as ET
from .config import _target, _no_symlink_ancestors, _merge_skin_settings, MAX_FILE_BYTES
from .navigation import groups, action, group_action

SKINS = {'rotary':'skin.rotary','nimbus':'skin.nimbus'}
# Both original helper schemas and native generator APIs were checked.
# 99 adds its widget bridge only to generated output, never stored cpath rows.
NIMBUS_HELPERS = ('0.0.98','0.0.99')
DATABASE = 'addon_data/script.nimbus.helper/cpath_cache.db'
KEYMAP = 'keymaps/nimbus_touch_submenu.xml'
PREFIXES = ('movie','tvshow','custom1','custom2','custom3','custom4')
MENU_IDS = ('movies','tvshows','custom1','custom2','custom3','custom4')
LABEL_KEYS = ('MenuMovieLabel','MenuTVShowLabel','MenuCustom1Label','MenuCustom2Label','MenuCustom3Label','MenuCustom4Label')
KEYMAP_BYTES = ('<keymap><Home><touch>'
    '<swipe direction="left">RunScript(script.nimbus.helper, mode=touch_home_submenu_swipe)</swipe>'
    '<longpress>RunScript(script.nimbus.helper, mode=touch_home_submenu_longpress)</longpress>'
    '</touch><mouse><longclick id="0">RunScript(script.nimbus.helper, mode=touch_home_submenu_longpress)</longclick>'
    '</mouse></Home></keymap>').encode()


def shortcuts(key, bindings):
    return tuple((g.label,group_action(g,key)) for g in groups(bindings)) + (('Setup','RunScript(script.serph91p.setup)'),)


def skin_settings(key,bindings):
    media=groups(bindings)
    values={};types={}
    if key=='rotary':
        for n,(label,builtin) in enumerate(shortcuts(key,bindings),1):
            values.update({'rotary.home.%d.label'%n:label,'rotary.home.%d.action'%n:builtin,
                           'rotary.home.%d.icon'%n:'DefaultVideo.png'})
        values['rotary.home.count']='6'
        values['rotary.apps.rev']=str(int(hashlib.sha256(repr(shortcuts(key,bindings)).encode()).hexdigest()[:8],16))
    elif key=='nimbus':
        values.update({'touchmode':'true','firsttimerun':'true'})
        types.update({'touchmode':'bool','firsttimerun':'bool'})
        for keyname in ('Movies','TVShows')+tuple('Custom%d'%i for i in range(1,11))+('Music','MusicVideo','TV','Radio','Games','Programs','Pictures','Videos','Fav','Weather'):
            flag='HomeMenuNo'+keyname+'Button'
            values[flag]='false' if keyname in ('Movies','TVShows','Custom1','Custom2','Custom3','Custom4') else 'true'
            types[flag.lower()]='bool'
        for label_key,(label,_) in zip(LABEL_KEYS,shortcuts(key,bindings)):
            values[label_key]=label
        for menu,g in zip(MENU_IDS,media):
            flag='SubmenuEnabled.'+menu;values[flag]='true';types[flag.lower()]='bool'
            for n,item in enumerate(g.items,1):
                prefix='Submenu.%s.%d.'%(menu,n)
                values.update({prefix+'label':item.label,prefix+'action':action(item),
                               prefix+'window':'Videos' if item.target=='videos' else '',
                               prefix+'target':item.path if item.target=='videos' else ''})
    else:raise ValueError('unknown Adams profile')
    return values,types


def _settings(profile,key,bindings):
    path=_target(profile,'addon_data/'+SKINS[key]+'/settings.xml')
    data=path.read_bytes() if path.exists() and path.stat().st_size<=MAX_FILE_BYTES else None
    if path.exists() and data is None:raise ValueError('oversized skin settings')
    if data is not None:
        if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():raise ValueError('unsafe skin settings')
        root=ET.fromstring(data)
        if root.tag!='settings':raise ValueError('invalid skin settings')
        for node in list(root):
            identifier=node.get('id','').lower()
            parts=identifier.split('.')
            rotary=(key=='rotary' and len(parts)==4 and parts[:2]==['rotary','home']
                    and parts[2].isdigit() and int(parts[2])>6 and parts[3] in ('label','icon','action'))
            # Kodi materializes absent Skin.String lookups as empty strings.
            # Preserve those inert saved slots, but remove stale real shortcuts.
            rotary_empty=rotary and node.get('type')=='string' and not (node.text or '')
            submenu=(key=='nimbus' and len(parts)==4 and parts[0]=='submenu' and parts[1] in MENU_IDS[:5]
                     and parts[2].isdigit() and parts[3] in ('label','action','window','target'))
            submenu_flag=key=='nimbus' and identifier in tuple('submenuenabled.'+menu for menu in MENU_IDS[:5])
            if (rotary and not rotary_empty) or submenu or submenu_flag:root.remove(node)
        data=ET.tostring(root,encoding='utf-8')
    values,types=skin_settings(key,bindings)
    return _merge_skin_settings(data,values,types)


def cpath_rows(bindings):
    rows=[]
    for prefix,(label,builtin) in zip(PREFIXES,shortcuts('nimbus',bindings)):
        rows.append((prefix+'.main_menu',builtin,label,'__CUSTOM_ACTION__',label))
    for prefix,g in zip(PREFIXES,groups(bindings)):
        for n,item in enumerate((i for i in g.items if i.target=='videos' and i.path is not None),1):
            kind='WidgetListCategory' if item.label=='Genres' else 'WidgetListPoster' if g.key in ('movies','series') else 'WidgetListLandscape'
            rows.append((prefix+'.widget.'+str(n),item.path,item.label,kind,item.label))
    return tuple(rows)


def _managed(key):
    if key in tuple(p+'.main_menu' for p in PREFIXES):return True
    for p in PREFIXES:
        if key.startswith(p+'.widget.'):
            suffix=key[len(p+'.widget.'):]
            if not suffix.isdigit() or not 1<=int(suffix)<=50:raise ValueError('unknown managed widget slot')
            return True
    return False


def database_payload(profile,bindings):
    path=_target(profile,DATABASE);source=None;memory=sqlite3.connect(':memory:')
    original=None
    try:
        if path.exists():
            info=path.stat()
            if not stat.S_ISREG(info.st_mode) or not info.st_mode&0o444 or info.st_size>MAX_FILE_BYTES:raise ValueError('unsafe helper database')
            for suffix in ('-wal','-shm','-journal'):
                side=Path(str(path)+suffix);_no_symlink_ancestors(side)
                if side.exists():raise ValueError('active helper database journal')
            original=path.read_bytes()
            source=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=0)
            source.backup(memory)
        memory.execute('CREATE TABLE IF NOT EXISTS custom_paths(cpath_setting text unique,cpath_path text,cpath_header text,cpath_type text,cpath_label text)')
        memory.execute('CREATE TABLE IF NOT EXISTS menu_order(order_key text unique,order_value text)')
        if tuple(r[1] for r in memory.execute('PRAGMA table_info(custom_paths)'))!=('cpath_setting','cpath_path','cpath_header','cpath_type','cpath_label') or tuple(r[1] for r in memory.execute('PRAGMA table_info(menu_order)'))!=('order_key','order_value'):
            raise ValueError('unknown Nimbus helper database schema')
        all_rows=memory.execute('SELECT * FROM custom_paths LIMIT 5001').fetchall()
        if len(all_rows)>5000 or any(not isinstance(r[0],str) for r in all_rows):raise ValueError('unsafe helper rows')
        current=tuple(sorted(r for r in all_rows if _managed(r[0])))
        expected=tuple(sorted(cpath_rows(bindings)));order=json.dumps(list(MENU_IDS))
        orders=memory.execute('SELECT order_value FROM menu_order WHERE order_key=?',('main_menu',)).fetchall()
        if original is not None and current==expected and orders==[(order,)]:return original
        for row in current:memory.execute('DELETE FROM custom_paths WHERE cpath_setting=?',(row[0],))
        memory.executemany('INSERT INTO custom_paths VALUES (?,?,?,?,?)',expected)
        memory.execute('INSERT OR REPLACE INTO menu_order VALUES (?,?)',('main_menu',order));memory.commit()
        if memory.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise ValueError('helper database integrity check failed')
        return memory.serialize()
    except sqlite3.Error as exc:raise ValueError('helper database snapshot unavailable') from exc
    finally:
        if source is not None:source.close()
        memory.close()


def payloads(profile,key,bindings):
    result={'addon_data/'+SKINS[key]+'/settings.xml':_settings(profile,key,bindings)}
    if key=='nimbus':result.update({DATABASE:database_payload(profile,bindings),KEYMAP:KEYMAP_BYTES})
    return result


class NimbusCompatibilityError(ValueError):
    """A known compatibility limit, not a userdata or restore failure."""


def validate_runtime(api,key,translate_path):
    if key=='nimbus':
        version=(api.details('script.nimbus.helper') or {}).get('version')
        if version not in NIMBUS_HELPERS:
            shown=version if isinstance(version,str) and len(version)<=32 else 'unbekannt'
            raise NimbusCompatibilityError('Nimbus-Layout vorerst nicht anwendbar: Helper-Version '+shown+
                ' ist mit diesem Wizard noch nicht geprüft. Unterstützt: '+', '.join(NIMBUS_HELPERS)+'. '
                'Dafür ist eine passende Wizard-Version erforderlich, kein Zurücksetzen der Userdata oder Helper-Downgrade.')
        if Path(translate_path('special://userdata')).resolve()!=Path(translate_path('special://profile')).resolve():
            raise NimbusCompatibilityError('Nimbus-Touchmodus benötigt das Kodi-Standardprofil. '
                'Keine profilübergreifende Keymap-Änderung; das Layout wurde hier nicht angewendet.')


def refresh_native(api,key,profile,bindings):
    """Narrow vendor generators only; not reset_all/remake_all/favourites."""
    if api.xbmc.getSkinDir()!=SKINS[key]:raise ValueError('selected skin must be active')
    if key=='rotary':
        api.xbmc.executebuiltin('ReloadSkin()',wait=True)
        return
    import sys,importlib,xbmcaddon,xbmcvfs
    validate_runtime(api,key,xbmcvfs.translatePath)
    library=Path(xbmcaddon.Addon('script.nimbus.helper').getAddonInfo('path'))/'resources/lib'
    _no_symlink_ancestors(library)
    if not library.is_absolute() or not (library/'modules/cpath_maker.py').is_file():raise ValueError('native helper library unavailable')
    existing=sys.modules.get('modules')
    if existing is not None and tuple(Path(p).resolve() for p in getattr(existing,'__path__',()))!=(library/'modules',):raise ValueError('helper namespace collision')
    sys.path.insert(0,str(library))
    try:
        cpaths=importlib.import_module('modules.cpath_maker')
        custom=importlib.import_module('modules.custom_actions')
        for prefix,menu in zip(PREFIXES,MENU_IDS):
            for kind,method in (('main_menu','remake_main_menus'),('widget','remake_widgets')):
                worker=cpaths.CPaths(prefix+'.'+kind)
                try:getattr(worker,method)(reload_skin=False)
                finally:worker.dbcon.close()
            custom.make_submenu_xml(menu)
        cpaths.make_main_menu_order_xml(reload_skin=False)
        custom.apply_touch_submenu_gesture_setting()
        api.xbmc.executebuiltin('ReloadSkin()',wait=True)
    finally:sys.path.remove(str(library))


def native_current(api,key,profile,bindings):
    if api.xbmc.getSkinDir()!=SKINS[key]:return False
    values,types=skin_settings(key,bindings)
    for name,value in values.items():
        if types.get(name.lower())=='bool':
            if api.xbmc.getCondVisibility('Skin.HasSetting('+name+')')!=(value=='true'):return False
        elif value and api.xbmc.getInfoLabel('Skin.String('+name+')')!=value:return False
    if key=='rotary':return True
    import xbmcaddon
    root=Path(xbmcaddon.Addon(SKINS[key]).getAddonInfo('path'))/'xml'
    for menu,(_,builtin) in zip(MENU_IDS,shortcuts(key,bindings)):
        path=root/('script-nimbus-main_menu_'+menu+'.xml');_no_symlink_ancestors(path)
        if not path.is_file() or path.stat().st_size>MAX_FILE_BYTES:return False
        data=path.read_bytes()
        if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():return False
        if builtin not in tuple(n.text for n in ET.fromstring(data).iter('onclick')):return False
    return True
