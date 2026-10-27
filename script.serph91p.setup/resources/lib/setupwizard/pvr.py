"""Narrow PVR distribution contracts; never turn a system UUID into provenance.

LibreELEC 12 patches repository.libreelec.tv into its official repositories.
Generic Linux distro packages are NOT managed or installed by this wizard.
"""
from dataclasses import dataclass
from typing import Optional

SYSTEM_ORIGIN = 'b6a50484-93a0-4afb-a01c-8d17e059feda'
LIBREELEC_REPOSITORY = 'repository.libreelec.tv'
OFFICIAL_REPOSITORY = 'repository.xbmc.org'


@dataclass(frozen=True)
class PVRDistribution:
    kind: str
    repository: Optional[str]
    automatic_install: bool
    detail: str


def distribution(api):
    native = getattr(api, 'xbmc', None)
    condition = getattr(native, 'getCondVisibility', None)
    try:
        android = bool(condition('System.Platform.Android')) if condition else False
        linux = bool(condition('System.Platform.Linux')) if condition else False
    except Exception:
        return PVRDistribution('unknown', None, False, 'PVR-Plattform nicht prüfbar')
    if linux and not android:
        # Repo ID alone is not a distribution claim: require native system
        # provenance and enabled state, never any arbitrary distro repository.
        try:
            repo = api.details(LIBREELEC_REPOSITORY)
            if (isinstance(repo, dict) and repo.get('enabled') is True
                    and api.origin(LIBREELEC_REPOSITORY) == SYSTEM_ORIGIN):
                return PVRDistribution('libreelec', LIBREELEC_REPOSITORY, True,
                                       'LibreELEC-Systemrepository für gerätespezifische PVR-Binaries')
        except Exception:
            pass
        return PVRDistribution('os-unverified', None, False,
            'OS-verwaltetes IPTV Simple: Paket-Herkunft und Update-Verantwortung werden von diesem Wizard '
            'nicht geprüft. Vorhandenen PVR-Client erhalten; keine automatische Paketinstallation oder Reparatur.')
    # This is only the expected source, not a grant of provenance. Strict
    # installed-origin, version and enabled checks must still pass afterwards.
    return PVRDistribution('kodi', OFFICIAL_REPOSITORY, True,
                           'PVR muss aus dem offiziellen Kodi-Repository stammen')


def libreelec_repository_available(api):
    return distribution(api).kind == 'libreelec'
