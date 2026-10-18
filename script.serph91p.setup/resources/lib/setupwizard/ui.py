"""Confirmation-gated Kodi UI. No restart, reload or account copying."""
from __future__ import annotations
from pathlib import Path
from uuid import uuid4
from .addons import (REQUIREMENTS, PROFILE_REQUIREMENTS, MEDIA_REQUIREMENTS, KodiAddonAPI,
                     bounded_wait, check_requirement, ensure_requirement)
from .config import MANIFEST
from .common_layouts import apply_common_layout
from .navigation import library_bindings, load_bindings, groups, action
from .addons import REPOSITORY_REQUIREMENT
from .layouts import describe_layout
from .profiles import PROFILES, requirements_for

TITLE = 'Serph91P Kodi Setup'
REPOSITORIES = ('Benötigt Serph91P Repository 1.0.1 oder neuer: Es bindet die Quellen '
    'für Arctic, Emby Next Gen Beta und Estuary MOD V2 nativ ein. '
    'Im Teststand das beigefügte Repository-ZIP einmal installieren/aktualisieren; '
    'keine einzelnen Fremd-Repository-ZIPs nötig. IPTV Simple kommt plattformgerecht von Kodi.')


def install_with_progress(api, required, dialog, monitor, progress, log):
    """Count verified add-ons, not download bytes. Background UI permits Kodi prompts."""
    current = 'Vorbereitung'
    try:
        progress.create(TITLE, 'Addons werden geprüft ...')
        total = len(required)
        for index, req in enumerate(required):
            current = req.label
            if monitor.abortRequested():
                return False, current + ': Kodi beendet den Vorgang.'

            def update(status):
                progress.update(int(index * 100 / total), TITLE,
                    '{}/{} geprüft | {}: {}'.format(index, total, current, status))

            def report(message):
                log(message)
                update(message)

            update('Prüfung läuft')
            okay = ensure_requirement(api, req,
                lambda prompt: dialog.yesno(TITLE, prompt),
                lambda item: bounded_wait(api, item, monitor=monitor,
                    on_status=lambda status: update('Warte auf Installation/Aktivierung: ' + status)),
                report)
            if not okay:
                return False, current + ': nicht abgeschlossen (abgelehnt, fehlgeschlagen oder Zeitlimit).'
            progress.update(int((index + 1) * 100 / total), TITLE,
                '{}/{} geprüft | {}: installiert und aktiv'.format(index + 1, total, current))
        return True, ''
    finally:
        progress.close()


def open_group(argv, xbmc, xbmcgui, xbmcvfs):
    from .navigation import PROFILE_IDS
    params = {}
    for value in argv:
        if '=' not in value:
            raise ValueError('unknown script argument')
        key, val = value.split('=', 1)
        if key in params or key not in ('group', 'profile'):
            raise ValueError('unknown script argument')
        params[key] = val
    if set(params) != {'group', 'profile'} or params['profile'] not in PROFILE_IDS:
        raise ValueError('invalid content menu arguments')
    profile = Path(xbmcvfs.translatePath('special://profile'))
    media = groups(load_bindings(profile, params['profile']))
    group = next((g for g in media if g.key == params['group']), None)
    if group is None:
        raise ValueError('unknown content group')
    choice = xbmcgui.Dialog().select(group.label, [i.label for i in group.items])
    if 0 <= choice < len(group.items):
        xbmc.executebuiltin(action(group.items[choice]))


def run(argv=None):
    import xbmc
    import xbmcaddon
    import xbmcgui
    import xbmcvfs
    dialog, api, monitor = xbmcgui.Dialog(), KodiAddonAPI(xbmc), xbmc.Monitor()
    if argv:
        try:
            open_group(argv, xbmc, xbmcgui, xbmcvfs)
        except Exception as exc:
            dialog.ok(TITLE, 'Inhalte nicht geöffnet: ' + str(exc))
        return
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

    selected = dialog.select(TITLE + ' — Skin-Profil wählen', [p.label for p in PROFILES])
    if selected < 0 or selected >= len(PROFILES):
        return
    profile_choice = PROFILES[selected]
    if profile_choice.warning and not dialog.yesno(TITLE, profile_choice.warning):
        return
    required = requirements_for(profile_choice, REQUIREMENTS, PROFILE_REQUIREMENTS, MEDIA_REQUIREMENTS)

    def all_ready():
        return all(check_requirement(api, item)[0] for item in required)

    def inactive():
        if xbmc.getSkinDir() != 'skin.estuary':
            dialog.ok(TITLE, 'Zum Schreiben oder Wiederherstellen zuerst manuell Estuary aktivieren. Kein automatischer Skinwechsel oder Neustart.')
            return False
        return True

    choices = ['Addons installieren / prüfen', 'Portables Skin-Layout anwenden',
               'Bei Diensten anmelden', 'Layout-Sicherung wiederherstellen',
               'Status und Voraussetzungen', 'Kodi-Oberflächeneinstellungen öffnen', 'Beenden', 'Inhalte öffnen']
    while not monitor.abortRequested():
        choice = dialog.select(TITLE, choices)
        if choice in (-1, 6):
            return
        try:
            if choice == 0:
                if not dialog.yesno(TITLE, REPOSITORIES + '\n\nBenötigte Addons jetzt prüfen? Einzelne Änderungen werden nochmals bestätigt.'):
                    continue
                repo_ok, repo_status = check_requirement(api, REPOSITORY_REQUIREMENT)
                if not repo_ok:
                    dialog.ok(TITLE, 'Setup-Quellen fehlen oder sind nicht bereit: ' + repo_status + '\n' + REPOSITORIES)
                    continue
                xbmc.executebuiltin('UpdateAddonRepos', wait=True)
                okay, detail = install_with_progress(api, required, dialog, monitor,
                    xbmcgui.DialogProgressBG(), log)
                if monitor.abortRequested():
                    return
                dialog.ok(TITLE, ('Alle benötigten Addons sind installiert und aktiv. Layout und Anmeldungen bleiben getrennte Schritte.' if okay else
                    'Einrichtung unvollständig. ' + detail + '\n' + REPOSITORIES))
            elif choice == 1:
                if not all_ready():
                    dialog.ok(TITLE, 'Zuerst alle benötigten Addons installieren/aktivieren. Es wurde kein Layout geschrieben.')
                    continue
                if not inactive():
                    continue
                if not dialog.yesno(TITLE, describe_layout(profile_choice.key) +
                    '\nEmby muss angemeldet und synchronisiert sein. Die lokalen Serien-/Twitch-VOD-Bibliotheken werden anschließend ausgewählt. '
                    'Vorhandene betroffene Dateien werden gesichert. Bei MOD V2 wird das geteilte Skin-Shortcuts-Menü ersetzt. Fortfahren?'):
                    continue
                bindings = library_bindings(profile, lambda title, options: dialog.select(title, options))
                backup_root = profile / 'setupwizard-backups'
                if backup_root.is_symlink():
                    raise ValueError('unsafe backup root')
                backup_root.mkdir(mode=0o700, exist_ok=True)
                backup = backup_root / uuid4().hex
                changed = apply_common_layout(profile, backup, profile_choice.key, bindings)
                dialog.ok(TITLE, ('Gemeinsames Medienmenü geschrieben, gesichert und zurückgelesen. '
                    'Gewählten Skin jetzt selbst in Kodi aktivieren; die Anzeige auf diesem Gerät ist damit noch nicht geprüft. Sicherung: ' + str(backup)
                    if changed else 'Gemeinsames Medienmenü bereits aktuell; keine Änderung.'))
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
                elif req.addon_id in ('script.tubecast', 'pvr.iptvsimple'):
                    dialog.ok(TITLE, 'Hier die geräteeigene Konfiguration vornehmen: TubeCast-Empfang beziehungsweise IPTV-Playlist und EPG. Keine Zugangsdaten oder privaten Quell-URLs werden übernommen.')
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
                from .touch import restore_layout
                restore_layout(profile, backups[selected], xbmc)
                dialog.ok(TITLE, 'Sicherung geprüft und Layout wiederhergestellt. Kein Skin-Reload und kein Neustart ausgeführt.')
            elif choice == 4:
                lines = [r.label + ': ' + check_requirement(api, r)[1] for r in required]
                dialog.textviewer(TITLE, '\n'.join(lines) + '\n\n' + REPOSITORIES + '\n\nAnmeldungen, Bibliothekssync und tatsächliche Widgets sind hier nicht live geprüft. Das ist ein Geräte-Testkandidat, noch kein freigegebenes Komplettsetup.')
            elif choice == 5:
                xbmc.executebuiltin('ActivateWindow(appearancesettings)')
                return
            elif choice == 7:
                from .layouts import NAVIGATION
                labels = ['Movies', 'Series', 'Twitch', 'YouTube', 'Live TV', 'Programm / EPG']
                selected = dialog.select('Inhalte öffnen', labels)
                if 0 <= selected < 4:
                    key = ('movies', 'series', 'twitch', 'youtube')[selected]
                    open_group(('group=' + key, 'profile=' + profile_choice.key), xbmc, xbmcgui, xbmcvfs)
                elif selected in (4, 5):
                    xbmc.executebuiltin(NAVIGATION[selected - 4][1])
        except Exception as exc:
            log('Vorgang fehlgeschlagen: ' + type(exc).__name__)
            dialog.ok(TITLE, 'Vorgang nicht abgeschlossen. Vorhandene Sicherungen bleiben erhalten. Bei fremden Änderungen verweigert Restore das Überschreiben. Details: ' + type(exc).__name__ + ': ' + str(exc))
