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
    min_version_string: str = ''

REQUIREMENTS = (
    AddonRequirement('skin.arctic.fuse.3', (3, 3, 12), 'Arctic Fuse 3'),
    AddonRequirement('script.skinvariables', (2, 2, 9), 'Skin Variables'),
    AddonRequirement('script.texturemaker', (0, 2, 9), 'Texture Maker'),
    AddonRequirement('resource.images.weathericons.white', (0, 0, 1), 'Wettersymbole'),
    AddonRequirement('resource.images.studios.coloured', (0, 0, 1), 'Studio-Symbole'),
    AddonRequirement('resource.font.robotocjksc', (0, 0, 3), 'Roboto CJK'),
    AddonRequirement('plugin.video.themoviedb.helper', (6, 17, 9), 'TMDb Helper'),
)
PROFILE_REQUIREMENTS = (
    AddonRequirement('script.skinshortcuts', (2, 0, 3), 'Skin Shortcuts'),
    AddonRequirement('skin.amber', (3, 99, 2), 'Amber'),
    AddonRequirement('skin.estuary.modv2', (21, 4), 'Estuary MOD V2', '21.4+omega.10'),
    AddonRequirement('skin.rotary', (0, 0, 1), 'Rotary'),
    AddonRequirement('skin.nimbus', (0, 2, 7), 'Nimbus Plus', '0.2.07'),
    AddonRequirement('script.nimbus.helper', (0, 0, 98), 'Nimbus Plus Helper'),
)
MEDIA_REQUIREMENTS = (
    AddonRequirement('plugin.service.emby-next-gen', (12, 4, 23), 'Emby Next Gen'),
    AddonRequirement('plugin.video.twitch', (3, 1, 11), 'Twitch'),
    AddonRequirement('plugin.video.youtube', (7, 4, 4, 1), 'YouTube'),
    AddonRequirement('plugin.video.gronkhtv', (2, 3, 10), 'Gronkh.tv'),
    AddonRequirement('script.tubecast', (1, 6, 1), 'TubeCast', '1.6.1+omega.2'),
    AddonRequirement('pvr.iptvsimple', (0,), 'PVR IPTV Simple'),
)
REPOSITORY_REQUIREMENT = AddonRequirement('repository.serph91p', (1, 0, 3), 'Serph91P Repository mit Setup-Quellen')
OFFICIAL_REPOSITORY_REQUIREMENT = AddonRequirement('repository.xbmc.org', (0,), 'Offizielles Kodi Repository')
LIBREELEC_REPOSITORY_REQUIREMENT = AddonRequirement('repository.libreelec.tv', (0,), 'LibreELEC-Systemrepository')
ORIGINAL_REPOSITORY_REQUIREMENTS = (
    AddonRequirement('repository.jurialmunkey', (3, 4), 'Jurialmunkey Repository'),
    AddonRequirement('repository.beta.emby.kodi', (1, 0, 11), 'Emby Beta Repository'),
    AddonRequirement('repository.kodinerds', (7, 0, 1, 9), 'Kodinerds Repository'),
    AddonRequirement('repository.adamsbuilds', (1, 0), 'AdamsBuilds Repository'),
)
ALL_REQUIREMENTS = REQUIREMENTS + PROFILE_REQUIREMENTS + MEDIA_REQUIREMENTS + (REPOSITORY_REQUIREMENT, OFFICIAL_REPOSITORY_REQUIREMENT, LIBREELEC_REPOSITORY_REQUIREMENT) + ORIGINAL_REPOSITORY_REQUIREMENTS
REQUIREMENTS_BY_ID = {r.addon_id: r for r in ALL_REQUIREMENTS}

class KodiAddonAPI:
    def __init__(self, xbmc, xbmcaddon=None, origin_read_fn=None):
        self.xbmc = xbmc
        self.origin_read_fn = origin_read_fn
        # Legacy test adapters stay version-only; production/UI readiness must
        # inject the native reader and/or call check_requirement_strict.
        self.strict_origins = origin_read_fn is not None

    def origin(self, addon_id):
        self._allowed(addon_id)
        if self.origin_read_fn is None:
            raise RuntimeError('Native installed-origin reader unavailable')
        return self.origin_read_fn(addon_id)

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
        # Omega InstallAddon calls InstallModal (including native No/Cancel).
        # Wait for that operation, not a fire-and-forget request followed by
        # a timer which cannot distinguish refusal from an installation.
        self.xbmc.executebuiltin('InstallAddon({})'.format(addon_id), wait=True)

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
    if isinstance(minimum, str):
        actual_core, minimum_core = version_tuple(installed), version_tuple(minimum)
        if not actual_core or not minimum_core:
            return False
        width = max(len(actual_core), len(minimum_core))
        left = actual_core + (0,) * (width - len(actual_core))
        right = minimum_core + (0,) * (width - len(minimum_core))
        if left != right:
            return left > right
        # Reviewed floors use stable +omega.N revisions. Do not discard N or
        # accept another release family. Compare numeric tokens numerically.
        if '~' in installed or '-' in installed:
            return False
        suffix = minimum.partition('+')[2]
        actual_suffix = installed.partition('+')[2]
        if not suffix:
            return True
        family = re.match(r'[A-Za-z]+', suffix)
        actual_family = re.match(r'[A-Za-z]+', actual_suffix)
        if not family or not actual_family or family[0].lower() != actual_family[0].lower():
            return False
        tokens = lambda text: tuple((1, int(p)) if p.isdigit() else (0, p.lower())
                                    for p in re.findall(r'\d+|[^\d]+', text))
        return tokens(actual_suffix) >= tokens(suffix)
    # Pre-release markers cannot satisfy a stable floor of the same core version.
    actual = version_tuple(installed)
    width = max(len(actual), len(minimum))
    left = actual + (0,) * (width - len(actual))
    right = minimum + (0,) * (width - len(minimum))
    return bool(actual) and (left > right or (left == right and '~' not in installed and '-' not in installed))


def check_requirement(api, requirement, strict_origin=None):
    if requirement.addon_id == 'pvr.iptvsimple':
        from .pvr import distribution
        contract = distribution(api)
        if not contract.automatic_install:
            return False, 'Herkunft nicht prüfbar: ' + contract.detail
    try:
        details = api.details(requirement.addon_id)
    except Exception:
        return False, 'API-Fehler'
    if details is None:
        return False, 'nicht installiert'
    if not isinstance(details.get('enabled'), bool):
        return False, 'API-Fehler'
    if strict_origin is True or (strict_origin is None and getattr(api, 'strict_origins', False)):
        from .origins import check_origin
        okay, status = check_origin(api, requirement.addon_id)
        if not okay:
            return False, status
    if not details['enabled']:
        return False, 'deaktiviert'
    if not version_at_least(details.get('version'), requirement.min_version_string or requirement.min_version):
        return False, 'Version zu alt oder nicht prüfbar'
    return True, 'aktiv, Version ' + details['version']


def bounded_wait(api, requirement, monitor=None, timeout=90, interval=1,
                 clock=time.monotonic, sleep=time.sleep, on_status=None):
    deadline = clock() + max(0, timeout)
    while True:
        if monitor is not None and monitor.abortRequested():
            return False
        okay, status = check_requirement(api, requirement)
        if on_status is not None:
            on_status(status)
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
    if status == 'API-Fehler' or status.startswith('Herkunft'):
        return False  # Inspection errors must never trigger mutation.
    if status == 'Version zu alt oder nicht prüfbar':
        log(requirement.label + ': vorhandenes Addon nativ aktualisieren/migrieren; InstallAddon aktualisiert keine installierten Addons')
        return False
    if status == 'deaktiviert':
        details = api.details(requirement.addon_id)
        if not version_at_least(details.get('version'), requirement.min_version_string or requirement.min_version):
            log(requirement.label + ': zuerst nativ aktualisieren/migrieren; alte deaktivierte Installation bleibt erhalten')
            return False
    if not confirm('{}: {}. Über Kodis Repository-Verwaltung installieren/aktivieren?'.format(requirement.label, status)):
        return False
    try:
        if status == 'deaktiviert':
            api.enable(requirement.addon_id)
        else:
            api.install(requirement.addon_id)
        details = api.details(requirement.addon_id)
        if details is None or not details.get('enabled'):
            log(requirement.label + ': nativer Vorgang beendet, aber nicht installiert/aktiv '
                '(abgelehnt, abgebrochen oder fehlgeschlagen); kein weiteres Warten')
            return False
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
