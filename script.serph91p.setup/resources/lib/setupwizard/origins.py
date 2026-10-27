"""Fixed original-repository contracts; never infer origin from a version.

Kodi Omega does not expose installed origin via its Python/JSON-RPC API.
The optional reader below accesses only installed.addonID/origin, read-only.
An unavailable reader is an inspection failure, not permission to install.
"""

ORIGINS = {
    'skin.arctic.fuse.3': 'repository.jurialmunkey',
    'script.skinvariables': 'repository.jurialmunkey',
    'script.texturemaker': 'repository.jurialmunkey',
    'plugin.video.themoviedb.helper': 'repository.jurialmunkey',
    'resource.font.robotocjksc': 'repository.jurialmunkey',
    'plugin.service.emby-next-gen': 'repository.beta.emby.kodi',
    'skin.estuary.modv2': 'repository.kodinerds',
    'skin.amber': 'repository.xbmc.org',
    'script.skinshortcuts': 'repository.xbmc.org',
    'plugin.video.youtube': 'repository.xbmc.org',
    'pvr.iptvsimple': 'repository.xbmc.org',
    'resource.images.weathericons.white': 'repository.xbmc.org',
    'resource.images.studios.coloured': 'repository.xbmc.org',
    # Intentionally maintained forks: do not downgrade to official releases.
    'plugin.video.twitch': 'repository.serph91p',
    'script.tubecast': 'repository.serph91p',
    'plugin.video.gronkhtv': 'repository.serph91p',
}
for _repository in ('repository.jurialmunkey', 'repository.beta.emby.kodi',
                    'repository.kodinerds', 'repository.serph91p', 'repository.xbmc.org',
                    'repository.libreelec.tv'):
    ORIGINS[_repository] = _repository


class OriginUnavailable(RuntimeError):
    """The installed origin cannot be proven without mutating Kodi."""


class SQLiteOriginReader:
    """Narrow Omega Addons33 reader. No creation, migration or writable SQL.

    Pass xbmcvfs.translatePath, not the profile path (database can be shared).
    Other schema generations intentionally fail closed until source-reviewed.
    """
    def __init__(self, translate_path):
        self.translate_path = translate_path

    def __call__(self, addon_id):
        if addon_id not in ORIGINS:
            raise ValueError('Add-on ID not allowlisted')
        connection = None
        try:
            import sqlite3
            import os
            import stat
            from pathlib import Path
            from .config import _no_symlink_ancestors
            root = Path(self.translate_path('special://database'))
            if not root.is_absolute() or not root.is_dir():
                raise OriginUnavailable('Native database directory unavailable')
            database = root / 'Addons33.db'
            _no_symlink_ancestors(database)
            info = database.stat()
            if not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o444 or not os.access(database, os.R_OK):
                raise OriginUnavailable('Native database unreadable')
            # SQLite may consult these adjacent files in WAL/hot-journal mode.
            for suffix in ('-wal', '-shm', '-journal'):
                sidecar = Path(str(database) + suffix)
                _no_symlink_ancestors(sidecar)
                # Do not let SQLite create/recover journal or shared-memory
                # state. Active journal/WAL inspection is deliberately blocked.
                if sidecar.exists():
                    raise OriginUnavailable('Active journal/WAL database unavailable')
            connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=0)
            connection.execute('PRAGMA query_only=ON')
            # This fixed SELECT both validates required schema and reads one ID.
            rows = connection.execute(
                'SELECT addonID, origin FROM installed WHERE addonID = ? LIMIT 2',
                (addon_id,)).fetchall()
            if (len(rows) != 1 or rows[0][0] != addon_id
                    or not isinstance(rows[0][1], str) or not rows[0][1]):
                raise OriginUnavailable('Installed origin missing or ambiguous')
            return rows[0][1]
        except OriginUnavailable:
            raise
        except Exception as exc:
            raise OriginUnavailable('Native installed origin unreadable') from exc
        finally:
            if connection is not None:
                connection.close()


def check_origin(api, addon_id):
    # The distribution-provided official repository itself has no installed
    # upstream origin. Exact ID presence/enabled/version is checked by caller.
    # This unqualified exception never applies to official leaves. LibreELEC
    # below needs a separately recognized native-system repository contract.
    if addon_id == 'repository.xbmc.org':
        return True, 'Offizielles Repository vorhanden'
    from .pvr import distribution, LIBREELEC_REPOSITORY
    if addon_id == LIBREELEC_REPOSITORY:
        if distribution(api).kind == 'libreelec':
            return True, 'Natives LibreELEC-Systemrepository bestätigt'
        return False, 'Herkunft des LibreELEC-Systemrepositorys nicht prüfbar'
    expected = ORIGINS.get(addon_id)
    if addon_id == 'pvr.iptvsimple':
        contract = distribution(api)
        if not contract.automatic_install:
            return False, 'Herkunft nicht prüfbar: ' + contract.detail
        expected = contract.repository
    if not isinstance(expected, str):
        return False, 'Herkunft nicht allowlisted'
    try:
        actual = api.origin(addon_id)
    except Exception:
        return False, 'Herkunft nicht prüfbar'
    if not isinstance(actual, str) or not actual:
        return False, 'Herkunft nicht prüfbar'
    if actual != expected:
        return False, 'Herkunft abweichend; Kodi Versionen/Repository neu wählen: ' + expected
    return True, 'Herkunft bestätigt: ' + expected


def check_requirement_strict(api, requirement):
    """Status/UI entry point: always strict, including legacy/mock API objects."""
    from .addons import check_requirement
    return check_requirement(api, requirement, strict_origin=True)


def repository_requirements(requirements, api=None):
    """Only repositories required by this exact leaf selection, in stable order."""
    from .addons import (ORIGINAL_REPOSITORY_REQUIREMENTS, REPOSITORY_REQUIREMENT,
                         OFFICIAL_REPOSITORY_REQUIREMENT, LIBREELEC_REPOSITORY_REQUIREMENT)
    from .pvr import distribution, LIBREELEC_REPOSITORY
    selected = tuple(requirements)
    expected = set()
    for item in selected:
        if item.addon_id not in ORIGINS:
            raise ValueError('Requirement without an original repository contract')
        source = ORIGINS[item.addon_id]
        if item.addon_id == 'pvr.iptvsimple' and api is not None:
            source = distribution(api).repository
        if source is not None:
            expected.add(source)
    candidates = (REPOSITORY_REQUIREMENT, OFFICIAL_REPOSITORY_REQUIREMENT, LIBREELEC_REPOSITORY_REQUIREMENT) + ORIGINAL_REPOSITORY_REQUIREMENTS
    return tuple(item for item in candidates if item.addon_id in expected)


def ordered_requirements(requirements, api=None):
    leaves = tuple(requirements)
    repositories = repository_requirements(leaves, api=api)
    repo_ids = {item.addon_id for item in repositories}
    return repositories + tuple(item for item in leaves if item.addon_id not in repo_ids)


from dataclasses import dataclass

@dataclass(frozen=True)
class RepositoryPolicy:
    repository_mode: object
    auto_update_mode: object

    @property
    def needs_choice(self):
        return type(self.repository_mode) is not int or self.repository_mode != 1

    @property
    def automatic_updates(self):
        # Global intent only. Kodi per-addon update rules are NOT exposed here.
        return type(self.auto_update_mode) is int and self.auto_update_mode == 0


def repository_policy(api):
    def read(name):
        try:
            value = api.rpc('Settings.GetSettingValue', {'setting': name})
            if 'error' in value:
                return None
            result = value.get('result', {})
            actual = result.get('value') if isinstance(result, dict) else None
            return actual if type(actual) is int and actual in (0, 1, 2) else None
        except Exception:
            return None
    # Kodi Omega Settings.h: repository selection and automatic-update intent
    # are different settings. addons.official is NOT a native setting.
    return RepositoryPolicy(read('addons.updatemode'), read('general.addonupdates'))


def confirm_repository_policy(api, confirm, open_settings):
    """User-mediated native setting only: no setter, no auto-click or guessing."""
    policy = repository_policy(api)
    if not policy.needs_choice:
        return True
    if not confirm('Kodi bevorzugt offizielle Quellen. Für die geprüften Original-Repositories und '
                   'gepflegten Serph91P-Versionen bitte „Beliebige Repositories“ selbst wählen. '
                   'Kodi Add-on-Einstellungen öffnen? Die globale Sicherheitsrichtlinie wird nicht automatisch geändert.'):
        return False
    open_settings()
    # Merely opening a settings window is not proof of user choice.
    return not repository_policy(api).needs_choice
