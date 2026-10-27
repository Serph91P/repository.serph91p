"""Read-only inventory and verification for in-place native addon migration.

Never reads, copies or resets addon_data, account settings or credentials.
A readable empty native origin is a ZIP/unassigned source, not a DB failure.
Completion is always proved again from native version/enabled/origin state.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
import stat
from .addons import AddonRequirement, REQUIREMENTS_BY_ID, version_at_least, version_tuple
from .config import _no_symlink_ancestors
from .origins import ORIGINS


@dataclass(frozen=True)
class ExistingAddon:
    requirement: AddonRequirement
    repository: str
    installed_version: str
    state: str
    detail: str


def inspect_existing(api, requirement):
    """Classify only wizard-owned requirements, without changing any state."""
    if requirement != REQUIREMENTS_BY_ID.get(requirement.addon_id):
        raise ValueError('Requirement not allowlisted')
    addon_id = requirement.addon_id
    expected: str = ORIGINS[addon_id]
    def result(state, detail, version=''):
        return ExistingAddon(requirement, expected, version, state, detail)
    if addon_id in ('pvr.iptvsimple', 'repository.libreelec.tv'):
        from .pvr import distribution
        contract = distribution(api)
        if not contract.automatic_install:
            return result('blocked', 'OS-verwalteter oder unbekannter PVR-Ursprung; keine automatische Migration')
        if addon_id == 'pvr.iptvsimple':
            repository = contract.repository
            if not isinstance(repository, str):
                return result('blocked', 'Kein prüfbares natives PVR-Repository')
            expected = repository
    try:
        details = api.details(addon_id)
    except Exception:
        return result('blocked', 'Native Addon-Prüfung nicht verfügbar')
    if details is None:
        return result('missing', 'Nicht installiert; keine Bestandsmigration')
    version = details.get('version')
    if not version_tuple(version) or not isinstance(details.get('enabled'), bool):
        return result('blocked', 'Installierte Version oder Aktivierung nicht prüfbar')
    try:
        # Native system repository exceptions never apply to ordinary leaves.
        actual = expected if addon_id in ('repository.xbmc.org', 'repository.libreelec.tv') else api.origin(addon_id)
    except Exception:
        return result('blocked', 'Native Herkunft nicht lesbar; keine Migration auf Verdacht', version)
    if not isinstance(actual, str):
        return result('blocked', 'Native Herkunft nicht eindeutig', version)
    floor = requirement.min_version_string or requirement.min_version
    if actual == expected and version_at_least(version, floor):
        if details['enabled']:
            return result('adopt', 'Vorhandene Installation übernehmen; Einstellungen und Anmeldung bleiben bestehen', version)
        return result('enable', 'Vorhandene passende Installation nur nativ aktivieren', version)
    reason = ('ZIP-/nicht zugeordnete Installation' if not actual else 'Abweichende Updatequelle') if actual != expected else 'Installierte Version zu alt'
    return result('migrate', reason + '; nativ zu ' + expected + ' wechseln, Daten behalten', version)


def safe_candidate_version(plan, version):
    """Never offer an older candidate, including older upstream fork versions."""
    if plan.state not in ('migrate', 'adopt', 'enable'):
        return False
    req = plan.requirement
    return (version_at_least(version, req.min_version_string or req.min_version)
            and version_at_least(version, plan.installed_version))


def verify_migration(api, before):
    """Opening UI or clicking confirmation is not completion evidence."""
    if before.state not in ('migrate', 'adopt', 'enable'):
        return False
    current = inspect_existing(api, before.requirement)
    return current.state == 'adopt' and safe_candidate_version(before, current.installed_version)


class SQLiteMigrationCandidates:
    """Read only the intended indexed repository; native UI filters compatibility."""
    def __init__(self, translate_path, index_reader):
        self.translate_path = translate_path
        self.index_reader = index_reader

    def __call__(self, plan):
        connection = None
        try:
            if plan.requirement != REQUIREMENTS_BY_ID.get(plan.requirement.addon_id):
                return ()
            if not self.index_reader(plan.repository):
                return ()
            path = Path(self.translate_path('special://database')) / 'Addons33.db'
            if not path.is_absolute():
                return ()
            _no_symlink_ancestors(path)
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o444 or not os.access(path, os.R_OK):
                return ()
            for suffix in ('-wal', '-shm', '-journal'):
                sidecar = Path(str(path) + suffix)
                _no_symlink_ancestors(sidecar)
                if sidecar.exists():
                    return ()
            connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=0)
            connection.execute('PRAGMA query_only=ON')
            rows = connection.execute('SELECT a.version FROM addons a '
                'JOIN addonlinkrepo l ON l.idAddon=a.id JOIN repo r ON r.id=l.idRepo '
                'WHERE r.addonID=? AND a.addonID=? LIMIT 129',
                (plan.repository, plan.requirement.addon_id)).fetchall()
            if len(rows) > 128:
                return ()
            return tuple(sorted({row[0] for row in rows if safe_candidate_version(plan, row[0])},
                                key=version_tuple, reverse=True))
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            return ()
        finally:
            if connection is not None:
                connection.close()


def guide_native_migration(api, before, dialog, candidate_reader, open_window):
    """Open only My add-ons; Versions is the safe native source-switch path.

    Omega's repository-list Install button can silently uninstall a foreign
    origin. Never drive that button, synthesize clicks or call InstallAddon
    for existing addons. Opening the native UI never returns migration success.
    """
    current = inspect_existing(api, before.requirement)
    if current.state == 'adopt':
        return verify_migration(api, before)
    title = 'Vorhandene Addons übernehmen / migrieren'
    if current.state != 'migrate':
        dialog.ok(title, current.detail + '. Bestehende Daten unverändert.')
        return False
    try:
        versions = tuple(v for v in candidate_reader(current) if safe_candidate_version(current, v))
    except Exception:
        versions = ()
    if not versions:
        dialog.ok(title, current.requirement.label + ': Migration noch nicht möglich. '
            'Keine gleich hohe oder neuere Zielversion aus ' + current.repository +
            ' sicher indexiert. Keine Neuinstallation, kein Downgrade; vorhandene Daten bleiben unverändert.')
        return False
    names = {'repository.serph91p': 'Serph91P Repository',
             'repository.xbmc.org': 'Kodi Add-on repository',
             'repository.jurialmunkey': 'jurialmunkey Alpha Repository',
             'repository.beta.emby.kodi': 'Kodi Emby Beta Addons',
             'repository.kodinerds': 'Kodinerds Addon Repo'}
    message = (current.requirement.label + ' (' + current.requirement.addon_id + ') ist bereits installiert: '
        + current.installed_version + '. ' + current.detail + '.\n\n'
        'Meine Addons / Alle wird geöffnet. Dort dieses Addon wählen → Versionen / Versions → '
        + names.get(current.repository, current.repository) + ' [' + current.repository + ']. '
        'Indexierte Zielversionen: ' + ', '.join(versions[:8]) + '. Keine ältere Version wählen.\n\n'
        'Nicht Installieren, Deinstallieren oder Paketcache wählen! Falls nur Aktualisieren statt Versionen erscheint, '
        'Auto-update nativ vorübergehend deaktivieren und die bisherige Wahl danach selbst wiederherstellen. '
        'Der Wizard ändert keine Updatesperren oder Sicherheitsrichtlinie und löscht keine Addon-Daten oder Logins. '
        'Addon-eigene Änderungen/abgelaufene Sitzungen können erneutes Anmelden verlangen.\n\n'
        'Nach der nativen Auswahl den Wizard erneut öffnen: Quelle, Version und Aktivierung werden neu geprüft; '
        'das Öffnen dieser Liste ist noch keine bestätigte Migration. Jetzt öffnen?')
    if dialog.yesno(title, message):
        open_window('ActivateWindow(AddonBrowser,addons://user/all,return)')
    return False
