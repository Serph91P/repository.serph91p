"""Confirmation-gated Kodi UI. No restart, reload or account copying."""
from __future__ import annotations
from pathlib import Path
from uuid import uuid4
from .addons import (ALL_REQUIREMENTS, MEDIA_REQUIREMENTS, KodiAddonAPI,
                     bounded_wait, check_requirement, install_selected)
from .config import apply_template, rollback, MANIFEST
from .templates import minimal_layout_template, describe_template

TITLE = 'Serph91P Arctic Setup'
REPOSITORIES = (
    'Arctic Fuse: repository.jurialmunkey (Omega). '
    'Emby: repository.beta.emby.kodi für Kodi 21. '
    'Twitch/Gronkh: repository.serph91p. '
    'YouTube: ein kompatibles YouTube-/Kodi-Repository. '
    'Fehlt eine Quelle, diese zuerst über Kodis Addon-Verwaltung installieren. '
    'Der Assistent lädt keine fremden ZIPs nach.'
)


def run():
    import xbmc
    import xbmcaddon
    import xbmcgui
    import xbmcvfs
    dialog, api, monitor = xbmcgui.Dialog(), KodiAddonAPI(xbmc), xbmc.Monitor()
    try:
        if api.major_version() != 21:
            dialog.ok(TITLE, 'Dieser Kandidat ist auf Kodi 21/Omega begrenzt. Andere Kodi-Versionen sind noch nicht geprüft. Es wurde nichts geändert.')
            return
    except Exception:
        dialog.ok(TITLE, 'Kodi-Version konnte nicht geprüft werden. Es wurde nichts geändert.')
        return
    profile = Path(xbmcvfs.translatePath('special://profile'))
    if not profile.is_absolute() or not profile.is_dir() or profile.is_symlink():
        dialog.ok(TITLE, 'Kein sicherer lokaler Kodi-Profilpfad verfügbar.')
        return

    def log(message):
        xbmc.log('[script.serph91p.setup] ' + message, xbmc.LOGINFO)

    def all_ready():
        return all(check_requirement(api, item)[0] for item in ALL_REQUIREMENTS)

    def inactive():
        if xbmc.getSkinDir() == 'skin.arctic.fuse.3':
            dialog.ok(TITLE, 'Zum Schreiben oder Wiederherstellen bitte zuerst in Kodi manuell auf Estuary wechseln. Der laufende Skin könnte die Dateien sonst überschreiben. Kein automatischer Skinwechsel oder Neustart.')
            return False
        return True

    choices = ['Addons installieren / prüfen', 'Portables Arctic-Layout anwenden',
               'Bei Diensten anmelden', 'Layout-Sicherung wiederherstellen',
               'Status und Voraussetzungen', 'Kodi-Oberflächeneinstellungen öffnen', 'Beenden']
    while not monitor.abortRequested():
        choice = dialog.select(TITLE, choices)
        if choice in (-1, 6):
            return
        try:
            if choice == 0:
                if not dialog.yesno(TITLE, REPOSITORIES + '\n\nBenötigte Addons jetzt prüfen? Einzelne Änderungen werden nochmals bestätigt.'):
                    continue
                okay = install_selected(api, ALL_REQUIREMENTS,
                    lambda prompt: dialog.yesno(TITLE, prompt),
                    lambda req: bounded_wait(api, req, monitor=monitor), log)
                dialog.ok(TITLE, ('Alle benötigten Addons sind installiert und aktiv. Layout und Anmeldungen bleiben getrennte Schritte.' if okay else
                    'Einrichtung unvollständig. Ein Addon fehlt, ist deaktiviert, inkompatibel oder wurde nicht rechtzeitig installiert.\n' + REPOSITORIES))
            elif choice == 1:
                if not all_ready():
                    dialog.ok(TITLE, 'Zuerst alle benötigten Addons installieren/aktivieren. Es wurde kein Layout geschrieben.')
                    continue
                if not inactive() or not dialog.yesno(TITLE, describe_template() + '\nVorhandene betroffene Dateien werden gesichert. Fortfahren?'):
                    continue
                backup_root = profile / 'setupwizard-backups'
                if backup_root.is_symlink():
                    raise ValueError('unsafe backup root')
                backup_root.mkdir(mode=0o700, exist_ok=True)
                changed = apply_template(profile, backup_root / uuid4().hex, minimal_layout_template())
                dialog.ok(TITLE, ('Portables Layout geschrieben und gesichert. Arctic Fuse 3 anschließend selbst in Kodi auswählen. Keine Anmeldung, kein Skin-Reload und kein Neustart ausgeführt.' if changed else
                    'Das Layout entspricht bereits dieser Vorlage. Keine Dateien geändert und keine zusätzliche Sicherung angelegt.'))
            elif choice == 2:
                selected = dialog.select('Dienst öffnen: Anmeldung bleibt auf diesem Gerät', [r.label for r in MEDIA_REQUIREMENTS])
                if selected < 0:
                    continue
                req = MEDIA_REQUIREMENTS[selected]
                if not check_requirement(api, req)[0]:
                    dialog.ok(TITLE, 'Dieses Addon fehlt oder ist nicht einsatzbereit. Zuerst installieren/aktivieren.')
                    continue
                if req.addon_id == 'plugin.service.emby-next-gen':
                    dialog.ok(TITLE, 'Emby-Verbindung und Bibliothekssynchronisierung im Emby-Addon auf diesem Gerät einrichten. Diese Ansicht öffnet nur dessen Einstellungen; eine erfolgreiche Anmeldung wird nicht behauptet.')
                    xbmcaddon.Addon(req.addon_id).openSettings()
                else:
                    dialog.ok(TITLE, 'Im folgenden Addon die Anmeldung durchführen. YouTube kann zusätzliche API-/OAuth-Einrichtung verlangen. Dieser Assistent liest oder speichert keine Zugangsdaten und prüft keine Anmeldung.')
                    xbmc.executebuiltin('ActivateWindow(Videos,plugin://{}/,return)'.format(req.addon_id))
                    return
            elif choice == 3:
                if not inactive():
                    continue
                root = profile / 'setupwizard-backups'
                if root.is_symlink():
                    raise ValueError('unsafe backup root')
                backups = sorted((p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and (p / MANIFEST).is_file()), key=lambda p: p.stat().st_mtime, reverse=True) if root.is_dir() else []
                if not backups:
                    dialog.ok(TITLE, 'Keine Layout-Sicherung gefunden.')
                    continue
                selected = dialog.select('Layout-Sicherung auswählen', [p.name for p in backups])
                if selected < 0 or not dialog.yesno(TITLE, 'Gesichertes Layout wiederherstellen? Nachträgliche fremde Änderungen werden nicht überschrieben.'):
                    continue
                rollback(profile, backups[selected])
                dialog.ok(TITLE, 'Sicherung geprüft und Layout wiederhergestellt. Kein Skin-Reload und kein Neustart ausgeführt.')
            elif choice == 4:
                lines = [r.label + ': ' + check_requirement(api, r)[1] for r in ALL_REQUIREMENTS]
                dialog.textviewer(TITLE, '\n'.join(lines) + '\n\n' + REPOSITORIES + '\n\nAnmeldungen, Bibliothekssync und tatsächliche Widgets sind hier nicht live geprüft. Das ist ein Geräte-Testkandidat, noch kein freigegebenes Komplettsetup.')
            elif choice == 5:
                xbmc.executebuiltin('ActivateWindow(appearancesettings)')
                return
        except Exception as exc:
            log('Vorgang fehlgeschlagen: ' + type(exc).__name__)
            dialog.ok(TITLE, 'Vorgang nicht abgeschlossen. Vorhandene Sicherungen bleiben erhalten. Bei fremden Änderungen verweigert Restore das Überschreiben. Details: Fehlertyp ' + type(exc).__name__)
