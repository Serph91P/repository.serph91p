"""One semantic media menu for all skins; device bindings never ship in the ZIP."""
from dataclasses import dataclass
import json
from pathlib import Path
from urllib.parse import quote
from typing import Optional, Dict
from .config import _profile, _no_symlink_ancestors, MAX_FILE_BYTES

BASE = 'special://home/addons/script.serph91p.setup/resources/playlists/'
PROFILE_IDS = ('arctic', 'amber', 'touch', 'rotary', 'nimbus')
BINDING_KEYS = ('series_resume', 'series_new', 'series_genres', 'twitch_resume', 'twitch_new')


def empty_bindings() -> Dict[str, Optional[str]]:
    return dict.fromkeys(BINDING_KEYS)

@dataclass(frozen=True)
class Item:
    label: str
    path: Optional[str]
    target: str = 'videos'

@dataclass(frozen=True)
class Group:
    key: str
    label: str
    items: tuple


def binding_path(profile_id):
    if profile_id not in PROFILE_IDS:
        raise ValueError('unknown skin profile')
    return 'addon_data/script.serph91p.setup/bindings-' + profile_id + '.json'


def library_bindings(profile, choose):
    """Resolve synced Emby library nodes on THIS device, never copy reference IDs."""
    profile = _profile(profile)
    root = profile / 'library/video'
    _no_symlink_ancestors(root)
    candidates = {}
    if root.is_dir():
        folders = sorted(root.iterdir())
        if len(folders) > 500:
            raise ValueError('too many video node folders')
        for folder in folders:
            if folder.is_symlink() or not folder.is_dir() or not folder.name.startswith('emby_'):
                continue
            if '_tvshows_' not in folder.name:
                continue
            label = folder.name.split('_tvshows_', 1)[1]
            values = candidates.setdefault(label, {})
            for name in ('resume_episode.xml', 'inprogressepisodes.xml', 'recentlyadded.xml', 'genres.xml'):
                path = folder / name
                _no_symlink_ancestors(path)
                if path.is_file():
                    if path.stat().st_size > MAX_FILE_BYTES:
                        raise ValueError('oversized library node')
                    kind = ('new' if name == 'recentlyadded.xml' else
                            'genres' if name == 'genres.xml' else 'resume')
                    # Prefer dynamic resume_episode for Series; static inprogress for VODs.
                    values[(kind, 'dynamic' if 'dynamic_' in folder.name else 'static')] = (
                        'library://video/' + quote(folder.name, safe='_.-') + '/' + name + '/')
    ready = sorted(k for k, v in candidates.items()
                   if all(any(a[0] == kind for a in v) for kind in ('resume', 'new', 'genres')))

    selected = {}
    for key, title in (('series', 'Serien-Bibliothek'), ('twitch', 'Twitch-VOD-Bibliothek')):
        options = [x for x in ready if x not in selected.values()]
        if not options:
            continue  # Install layout with explicit None bindings before personal sync.
        index = choose(title, options + ['Später einrichten / nicht verknüpfen'])
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index <= len(options):
            raise ValueError('Bibliotheksauswahl abgebrochen; Layout nicht angewendet')
        if index < len(options):
            selected[key] = options[index]
    result = empty_bindings()
    for key, label in selected.items():
        v = candidates[label]
        preference = ('dynamic', 'static') if key == 'series' else ('static', 'dynamic')
        for kind in (('resume', 'new', 'genres') if key == 'series' else ('resume', 'new')):
            result[key + '_' + kind] = next(v[(kind, p)] for p in preference if (kind, p) in v)
    return validate_bindings(result)


def validate_bindings(value):
    import re
    keys = set(BINDING_KEYS)
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError('invalid local library bindings')
    for path in value.values():
        if path is None:
            continue
        if not isinstance(path, str) or not re.fullmatch(
            r'library://video/emby_[A-Za-z0-9_.%\-]+/(?:resume_episode|inprogressepisodes|recentlyadded|genres)\.xml/', path):
            raise ValueError('non-local or unsupported library binding')
        from urllib.parse import unquote
        folder = unquote(path.split('/')[3])
        if '..' in folder or not re.fullmatch(r'emby_[\w .-]+', folder):
            raise ValueError('invalid local node path')
    return value


def load_bindings(profile, profile_id):
    p = _profile(profile) / binding_path(profile_id)
    _no_symlink_ancestors(p)
    if not p.is_file() or p.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('Layout zuerst einrichten; Emby kann später verknüpft werden.')
    return validate_bindings(json.loads(p.read_text(encoding='utf-8')))


def _library_item(label, path):
    if path is None:
        return Item(label + ' (Emby einrichten)', None, 'setup')
    return Item(label, path)


def groups(bindings):
    b = validate_bindings(bindings)
    return (
        Group('movies', 'Movies', (
            Item('In-Progress Movies', BASE + 'continue-movies.xsp'),
            Item('New Movies', 'videodb://recentlyaddedmovies/'),
            Item('Top Rated Movies', BASE + 'top-rated-movies.xsp'),
            Item('Genres', 'library://video/movies/genres.xml/'))),
        Group('series', 'Series', (
            _library_item('Fortsetzen', b['series_resume']), _library_item('Neu', b['series_new']),
            Item('Top Rated', 'plugin://plugin.video.themoviedb.helper/?info=top_rated&tmdb_type=tv&widget=true'),
            _library_item('Genres', b['series_genres']))),
        Group('twitch', 'Twitch', (
            Item('Following Live Channels', 'plugin://plugin.video.twitch/?mode=followed&content=live'),
            _library_item('Twitch VOD fortsetzen', b['twitch_resume']),
            _library_item('Neue Twitch VODs', b['twitch_new']),
            Item('Latest uploads', 'plugin://plugin.video.gronkhtv/?action=listing&category=Latest+uploads'))),
        Group('youtube', 'YouTube', (
            Item('Recommendations', 'plugin://plugin.video.youtube/special/recommendations'),
            Item('My Subscriptions', 'plugin://plugin.video.youtube/special/my_subscriptions'),
            Item('Search', 'plugin://plugin.video.youtube/kodion/search/list/'))),
        Group('livetv', 'Live TV', (Item('Sender', 'TVChannels', 'window'),
                                  Item('Programm / EPG', 'TVGuide', 'window'))),
    )


def action(item):
    if item.target == 'setup':
        if item.path is not None:
            raise ValueError('invalid deferred setup action')
        return 'Addon.OpenSettings(plugin.service.emby-next-gen)'
    if item.target == 'window':
        if item.path not in ('TVChannels', 'TVGuide'):
            raise ValueError('unsupported utility window')
        return 'ActivateWindow(' + item.path + ')'
    return 'ActivateWindow(Videos,' + item.path + ',return)'


def group_action(group, profile_id):
    binding_path(profile_id)
    return 'RunScript(script.serph91p.setup,group=' + group.key + ',profile=' + profile_id + ')'


def binding_bytes(bindings):
    return (json.dumps(validate_bindings(bindings), sort_keys=True, indent=2) + '\n').encode()
