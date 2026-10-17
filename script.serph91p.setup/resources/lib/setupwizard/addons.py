"""Kodi Omega add-on inspection and repository-managed installation."""
from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass

@dataclass(frozen=True)
class AddonRequirement:
    addon_id: str
    min_version: tuple
    label: str

REQUIREMENTS = (
    AddonRequirement('skin.arctic.fuse.3', (3, 3, 12), 'Arctic Fuse 3'),
    AddonRequirement('script.skinvariables', (2, 2, 9), 'Skin Variables'),
    AddonRequirement('script.texturemaker', (0, 2, 9), 'Texture Maker'),
    AddonRequirement('plugin.video.themoviedb.helper', (6, 17, 9), 'TMDb Helper'),
    AddonRequirement('resource.images.weathericons.white', (0, 0, 1), 'Wettersymbole'),
    AddonRequirement('resource.images.studios.coloured', (0, 0, 1), 'Studio-Symbole'),
    AddonRequirement('resource.font.robotocjksc', (0, 0, 3), 'Roboto CJK'),
)
PROFILE_REQUIREMENTS = (
    AddonRequirement('skin.amber', (3, 99, 2), 'Amber'),
    AddonRequirement('skin.estuary', (4, 0, 0), 'Estuary (Kodi-Standard)'),
)
MEDIA_REQUIREMENTS = (
    AddonRequirement('plugin.service.emby-next-gen', (12, 4, 23), 'Emby Next Gen'),
    AddonRequirement('plugin.video.twitch', (3, 1, 11), 'Twitch'),
    AddonRequirement('plugin.video.youtube', (7,), 'YouTube'),
    AddonRequirement('plugin.video.gronkhtv', (2, 3, 7), 'Gronkh.tv'),
    AddonRequirement('script.tubecast', (0,), 'TubeCast'),
    AddonRequirement('pvr.iptvsimple', (0,), 'PVR IPTV Simple'),
)
ALL_REQUIREMENTS = REQUIREMENTS + PROFILE_REQUIREMENTS + MEDIA_REQUIREMENTS
REQUIREMENTS_BY_ID = {r.addon_id: r for r in ALL_REQUIREMENTS}

class KodiAddonAPI:
    def __init__(self, xbmc, xbmcaddon=None):
        self.xbmc = xbmc

    def rpc(self, method, params):
        try:
            value = json.loads(self.xbmc.executeJSONRPC(json.dumps({
                'jsonrpc': '2.0', 'method': method, 'params': params, 'id': 1})))
        except Exception as exc:
            raise RuntimeError('Kodi JSON-RPC response unavailable') from exc
        if not isinstance(value, dict) or value.get('id') != 1:
            raise RuntimeError('Malformed Kodi response')
        return value

    def major_version(self):
        value = self.rpc('Application.GetProperties', {'properties': ['version']})
        major = value.get('result', {}).get('version', {}).get('major')
        if not isinstance(major, int) or isinstance(major, bool):
            raise RuntimeError('Kodi version unavailable')
        return major

    def details(self, addon_id):
        self._allowed(addon_id)
        value = self.rpc('Addons.GetAddonDetails', {
            'addonid': addon_id, 'properties': ['version', 'enabled']})
        if 'error' in value:
            error = value['error']
            if isinstance(error, dict) and error.get('code') == -32602:
                return None  # Fixed method/params: Kodi reports a missing installed ID this way.
            raise RuntimeError('Kodi add-on inspection failed')
        details = value.get('result', {}).get('addon')
        if (not isinstance(details, dict) or details.get('addonid') != addon_id
                or not isinstance(details.get('enabled'), bool)
                or not isinstance(details.get('version'), str)):
            raise RuntimeError('Malformed Kodi add-on details')
        return details

    @staticmethod
    def _allowed(addon_id):
        if addon_id not in REQUIREMENTS_BY_ID:
            raise ValueError('Add-on ID not allowlisted')

    def install(self, addon_id):
        self._allowed(addon_id)
        self.xbmc.executebuiltin('InstallAddon({})'.format(addon_id))

    def enable(self, addon_id):
        self._allowed(addon_id)
        value = self.rpc('Addons.SetAddonEnabled', {'addonid': addon_id, 'enabled': True})
        if value.get('result') != 'OK' or 'error' in value:
            raise RuntimeError('Kodi did not enable the add-on')


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+(?:\.\d+)*(?:[+~\-][A-Za-z0-9.\-]+)?', value):
        return ()
    return tuple(int(p) for p in re.split(r'[+~\-]', value, maxsplit=1)[0].split('.'))


def version_at_least(installed, minimum):
    # Pre-release markers cannot satisfy a stable floor of the same core version.
    actual = version_tuple(installed)
    width = max(len(actual), len(minimum))
    left = actual + (0,) * (width - len(actual))
    right = minimum + (0,) * (width - len(minimum))
    return bool(actual) and (left > right or (left == right and '~' not in installed and '-' not in installed))


def check_requirement(api, requirement):
    try:
        details = api.details(requirement.addon_id)
    except Exception:
        return False, 'API-Fehler'
    if details is None:
        return False, 'nicht installiert'
    if not isinstance(details.get('enabled'), bool):
        return False, 'API-Fehler'
    if not details['enabled']:
        return False, 'deaktiviert'
    if not version_at_least(details.get('version'), requirement.min_version):
        return False, 'Version zu alt oder nicht prüfbar'
    return True, 'aktiv, Version ' + details['version']


def bounded_wait(api, requirement, monitor=None, timeout=90, interval=1,
                 clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + max(0, timeout)
    while True:
        okay, status = check_requirement(api, requirement)
        if okay:
            return True
        if status == 'API-Fehler':
            return False
        remaining = deadline - clock()
        if remaining <= 0:
            return False
        delay = min(max(interval, 0.01), remaining)
        if monitor is not None:
            if monitor.waitForAbort(delay):
                return False
        else:
            sleep(delay)


def ensure_requirement(api, requirement, confirm, wait_for_install, log):
    okay, status = check_requirement(api, requirement)
    log('{}: {}'.format(requirement.label, status))
    if okay:
        return True
    if status == 'API-Fehler':
        return False  # Inspection errors must never trigger mutation.
    if not confirm('{}: {}. Über Kodis Repository-Verwaltung installieren/aktivieren?'.format(requirement.label, status)):
        return False
    try:
        if status == 'deaktiviert':
            api.enable(requirement.addon_id)
        else:
            api.install(requirement.addon_id)
    except Exception:
        log(requirement.label + ': Anfrage fehlgeschlagen')
        return False
    if not wait_for_install(requirement):
        log(requirement.label + ': Installation/Aktivierung nicht bestätigt')
        return False
    okay, status = check_requirement(api, requirement)
    log('{}: {}'.format(requirement.label, status))
    return okay


def install_selected(api, requirements, confirm, wait_for_install, log):
    for requirement in requirements:
        if not ensure_requirement(api, requirement, confirm, wait_for_install, log):
            return False
    return True
