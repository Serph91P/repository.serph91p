"""Read-only native repository-index readiness, not a fixed refresh sleep.

UpdateAddonRepos queues work even with wait=True. A nonempty checksum in
Omega's repo table is minimum evidence that a repository has been indexed;
it does not prove latest remote content or package download availability.
"""
import os
from pathlib import Path
import sqlite3
import stat
import time
from .config import _no_symlink_ancestors
from .addons import ALL_REQUIREMENTS

REPOSITORIES = frozenset(r.addon_id for r in ALL_REQUIREMENTS if r.addon_id.startswith('repository.'))


class SQLiteCatalogReader:
    def __init__(self, translate_path):
        self.translate_path = translate_path

    def __call__(self, repository_id):
        if repository_id not in REPOSITORIES:
            raise ValueError('Repository not allowlisted')
        connection = None
        try:
            root = Path(self.translate_path('special://database'))
            if not root.is_absolute() or not root.is_dir():
                return False
            database = root / 'Addons33.db'
            _no_symlink_ancestors(database)
            info = database.stat()
            if not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o444 or not os.access(database, os.R_OK):
                return False
            for suffix in ('-wal', '-shm', '-journal'):
                sidecar = Path(str(database) + suffix)
                _no_symlink_ancestors(sidecar)
                if sidecar.exists():
                    return False
            connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=0)
            connection.execute('PRAGMA query_only=ON')
            rows = connection.execute('SELECT addonID, checksum FROM repo WHERE addonID = ? LIMIT 2',
                                      (repository_id,)).fetchall()
            return (len(rows) == 1 and rows[0][0] == repository_id
                    and isinstance(rows[0][1], str) and bool(rows[0][1].strip()))
        except (OSError, ValueError, sqlite3.Error):
            return False
        finally:
            if connection is not None:
                connection.close()


class SQLiteUpdateRuleReader(SQLiteCatalogReader):
    """No entry means auto-updateable; ANY=0 entries are not absence.

    Kodi AddonUpdateRules::IsAutoUpdateable requires no rule entry at all.
    Never clear rules or infer per-addon state from the global preference.
    """
    def __call__(self, addon_id):
        if addon_id not in {r.addon_id for r in ALL_REQUIREMENTS}:
            raise ValueError('Addon not allowlisted')
        connection = None
        try:
            root = Path(self.translate_path('special://database'))
            if not root.is_absolute() or not root.is_dir():
                return 'unknown'
            database = root / 'Addons33.db'
            _no_symlink_ancestors(database)
            info = database.stat()
            if not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o444:
                return 'unknown'
            for suffix in ('-wal', '-shm', '-journal'):
                sidecar = Path(str(database) + suffix)
                _no_symlink_ancestors(sidecar)
                if sidecar.exists():
                    return 'unknown'
            connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=0)
            connection.execute('PRAGMA query_only=ON')
            rows = connection.execute('SELECT updateRule FROM update_rules WHERE addonID = ? LIMIT 8',
                                      (addon_id,)).fetchall()
            if not rows:
                return 'auto-updateable'
            names = {0: 'ANY', 1: 'USER_DISABLED_AUTO_UPDATE', 2: 'PIN_OLD_VERSION', 3: 'PIN_ZIP_INSTALL'}
            return 'blocked: ' + ', '.join(names.get(row[0], 'unknown-rule') for row in rows)
        except (OSError, ValueError, sqlite3.Error):
            return 'unknown'
        finally:
            if connection is not None:
                connection.close()


def wait_for_catalog(reader, repository_ids, monitor, on_status=None, *, timeout=60,
                     interval=1, clock=time.monotonic):
    """Bounded readback; abort/timeout refuses all subsequent leaf mutations."""
    ids = tuple(repository_ids)
    if not ids or any(item not in REPOSITORIES for item in ids):
        raise ValueError('Invalid repository readiness selection')
    deadline = clock() + max(0, timeout)
    while not monitor.abortRequested():
        missing = tuple(item for item in ids if not reader(item))
        if on_status:
            on_status('Katalog: ' + (', '.join(missing) if missing else 'Index zurückgelesen'))
        if not missing:
            return True
        remaining = deadline - clock()
        if remaining <= 0 or monitor.waitForAbort(min(max(interval, .01), remaining)):
            return False
    return False
