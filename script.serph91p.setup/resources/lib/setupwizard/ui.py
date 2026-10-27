"""Confirmation-gated Kodi UI. No forced restart or account copying."""
from __future__ import annotations
from pathlib import Path
from uuid import uuid4
from .addons import (REQUIREMENTS, PROFILE_REQUIREMENTS, MEDIA_REQUIREMENTS, KodiAddonAPI,
                     bounded_wait, ensure_requirement)
from .config import MANIFEST
from .common_layouts import apply_common_layout
from .navigation import library_bindings, load_bindings, groups, action
from .addons import REPOSITORY_REQUIREMENT
from .origins import (SQLiteOriginReader, ordered_requirements, repository_policy,
                      check_requirement_strict as check_requirement)
from .activation import request_activation
from .layouts import describe_layout
from .profiles import PROFILES, requirements_for

TITLE = 'Serph91P Kodi Setup'
REPOSITORIES = ('Benötigt das vorhandene Serph91P Repository und repository.xbmc.org. '
    'Originalquellen: repository.jurialmunkey, repository.beta.emby.kodi, repository.kodinerds. '
    'Das eigene Repository muss den veröffentlichten Stand 1.0.3 haben; bei älterem Stand öffnet der Assistent dessen native Aktualisierung. Fehlende Original-Repositories fügt er anschließend selbst über Kodi hinzu. '
    'Native Bestätigungen bleiben sichtbar; keine manuelle Suche nach Repository-ZIPs. '
    'IPTV Simple: Kodi-Originalrepo oder geprüftes LibreELEC-Systemrepo; allgemeine Linux-Pakete bleiben OS-verwaltet und ungeprüft. Gepflegte Serph91P-Ausnahmen: '
    'Twitch 3.1.11, TubeCast 1.6.1+omega.2, Gronkh.tv 2.3.10. '
    'Abweichende bestehende Herkunft: in Kodi Addon-Informationen / Versionen das Original-Repository '
    'wählen oder manuell neu installieren. Keine automatische Löschung oder Datenbankänderung.')


def install_with_progress(api, required, dialog, monitor, progress, log, *, approved=False,
                          catalog_reader=None):
    """One explicit batch approval; native Kodi dialogs remain interactive."""
    if approved is not True:
        return False, "Installation nicht freigegeben."
    current = 'Vorbereitung'
    try:
        progress.create(TITLE, 'Addons werden geprüft ...')
        total = len(required)
        repositories = tuple(r.addon_id for r in required if r.addon_id.startswith('repository.'))
        catalog_checked = False
        bootstrap_checked = False
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
            if req.addon_id.startswith('repository.') and req.addon_id not in ('repository.serph91p', 'repository.xbmc.org', 'repository.libreelec.tv') and not bootstrap_checked:
                from .catalog import wait_for_catalog
                if catalog_reader is None:
                    return False, 'Native Bootstrap-Katalogprüfung nicht verfügbar; keine Original-Repositories installiert.'
                api.xbmc.executebuiltin('UpdateAddonRepos', wait=True)
                if not wait_for_catalog(catalog_reader, ('repository.serph91p',), monitor, update):
                    return False, 'Aktualisierter Bootstrap-Katalogindex nicht bereit; keine Original-Repositories installiert.'
                bootstrap_checked = True
            if not req.addon_id.startswith('repository.') and not catalog_checked:
                from .catalog import wait_for_catalog
                if catalog_reader is None:
                    return False, 'Native Katalogprüfung nicht verfügbar; keine Inhalts-Addons installiert.'
                api.xbmc.executebuiltin('UpdateAddonRepos', wait=True)
                if not wait_for_catalog(catalog_reader, repositories, monitor, update):
                    return False, 'Katalogindex nicht bereit (Zeitlimit, Abbruch oder nicht lesbar); später fortsetzen.'
                catalog_checked = True
            ready, status = check_requirement(api, req)
            if status.startswith('Herkunft'):
                return False, req.label + ': ' + status + '. Native Kodi Versionen/Original-Repository oder manuelle Neuinstallation verwenden.'
            if req.addon_id == 'repository.serph91p' and not ready:
                return False, req.label + ': vorhandene eigene Quelle nativ aktualisieren/aktivieren; keine manuelle Installation der Original-Repositories erforderlich.'
            if req.addon_id == 'repository.xbmc.org' and not ready:
                return False, req.label + ': muss bereits nativ vorhanden und bereit sein.'
            okay = ensure_requirement(api, req,
                lambda _prompt: True,  # Fixed allowlisted batch already approved above.
                lambda item: bounded_wait(api, item, monitor=monitor,
                    on_status=lambda status: update('Warte auf Installation/Aktivierung: ' + status)),
                report)
            if not okay:
                return False, current + ': nicht abgeschlossen (abgelehnt, fehlgeschlagen oder Zeitlimit).'
            if not check_requirement(api, req)[0]:
                return False, current + ': Herkunft oder Zustand nach Installation nicht bestätigt.'
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
    from .catalog import SQLiteUpdateRuleReader
    update_reader = SQLiteUpdateRuleReader(xbmcvfs.translatePath)
    reader = SQLiteOriginReader(xbmcvfs.translatePath)
    dialog, api, monitor = xbmcgui.Dialog(), KodiAddonAPI(xbmc, xbmcaddon, origin_read_fn=reader), xbmc.Monitor()
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

    from . import state
    try:
        saved_profile = state.load(profile)
    except (OSError, ValueError):
        dialog.ok(TITLE, 'Statusdatei nicht sicher lesbar oder unbekannte Version. Keine Änderungen. '
                  'Die Statusdatei setup-state.json nach Sicherung manuell prüfen; keine Zugangsdaten löschen.')
        return

    def select_profile():
        selected = dialog.select(TITLE + ' — Skin-Profil wählen', [p.label for p in PROFILES])
        if not 0 <= selected < len(PROFILES):
            return None
        item = PROFILES[selected]
        if item.warning and not dialog.yesno(TITLE, item.warning):
            return None
        state.save(profile, item.key)
        return item

    try:
        if saved_profile:
            profile_choice = next(p for p in PROFILES if p.key == saved_profile)
        else:
            # A known active skin supplies a preference, not completion proof.
            # Every addon/origin/layout/setting is still inspected below.
            try:
                current_skin = xbmc.getSkinDir()
            except Exception:
                current_skin = None
            profile_choice = next((p for p in PROFILES if p.addon_id == current_skin), None)
            if profile_choice is None:
                profile_choice = select_profile()
            else:
                state.save(profile, profile_choice.key)
    except (OSError, ValueError):
        dialog.ok(TITLE, 'Statusdatei nicht sicher speicherbar. Keine Einrichtung ausgeführt.')
        return
    if profile_choice is None:
        return
    required = ordered_requirements(requirements_for(profile_choice, REQUIREMENTS, PROFILE_REQUIREMENTS, MEDIA_REQUIREMENTS), api=api)

    def all_ready():
        return all(check_requirement(api, item)[0] for item in required)

    def inactive():
        if xbmc.getSkinDir() != 'skin.estuary':
            dialog.ok(TITLE, 'Zum Schreiben oder Wiederherstellen zuerst manuell Estuary aktivieren. Kein automatischer Skinwechsel oder Neustart.')
            return False
        return True

    choices = ['Addons installieren / prüfen', 'Portables Skin-Layout anwenden',
               'Bei Diensten anmelden', 'Layout-Sicherung wiederherstellen',
               'Status und Voraussetzungen', 'Kodi-Oberflächeneinstellungen öffnen', 'Zurück', 'Inhalte öffnen',
               'Gewählten Skin jetzt aktivieren', 'Native Repository-Auto-Updates prüfen',
               'Native Menüansicht übernehmen / prüfen']
    expert, guiding, force = False, False, False
    forced_done = set()
    while not monitor.abortRequested():
        status = state.inspect(profile, profile_choice.key, api, update_reader)
        choice = None
        if expert:
            choice = dialog.select(TITLE + ' — Expert / Tools', choices)
            if choice in (-1, 6):
                expert = False
                continue
        else:
            if not guiding:
                if status.ready:
                    selected = dialog.select(TITLE + ' — Setup zurückgelesen', [
                        'Inhalte öffnen', 'Dienste / Anmeldung optional (Status unbekannt)',
                        'Expert / Tools', 'Setup erneut ausführen',
                        'Kodi-Oberflächeneinstellungen öffnen', 'Beenden'])
                    if selected == 0:
                        choice = 7
                    elif selected == 1:
                        choice = 2
                    elif selected == 2:
                        expert = True
                        continue
                    elif selected == 3:
                        choice = -2
                    elif selected == 4:
                        choice = 5
                    else:
                        return
                else:
                    selected = dialog.select(TITLE + ' — Einrichtung fortsetzen', [
                        'Geführte Einrichtung fortsetzen', 'Expert / Tools',
                        'Setup erneut ausführen', 'Beenden'])
                    if selected == 0:
                        guiding = True
                        choice = None
                    elif selected == 1:
                        expert = True
                        continue
                    elif selected == 2:
                        choice = -2
                    else:
                        return
                if choice == -2:
                    if not dialog.yesno(TITLE, 'Setup erneut ausführen? Nur die Assistenten-Profilwahl wird ersetzt. '
                            'Keine Zugangsdaten, anderen Addons oder Sicherungen werden gelöscht. '
                            'Jede Installation und Layout-/Regionsänderung benötigt erneut Zustimmung.'):
                        continue
                    try:
                        chosen = select_profile()
                    except (OSError, ValueError):
                        dialog.ok(TITLE, 'Statusdatei nicht sicher speicherbar.')
                        return
                    if chosen is None:
                        return
                    profile_choice = chosen
                    required = ordered_requirements(requirements_for(chosen, REQUIREMENTS, PROFILE_REQUIREMENTS, MEDIA_REQUIREMENTS), api=api)
                    force, guiding = True, True
                    forced_done.clear()
                    status = state.inspect(profile, profile_choice.key, api, update_reader)
            if guiding:
                if not status.addons or (force and 'addons' not in forced_done):
                    choice = 0
                elif not status.layout or not status.regional or (force and 'layout' not in forced_done):
                    choice = 1
                elif not status.skin:
                    choice = 8
                elif not status.menu:
                    choice = 10
                elif not status.updates:
                    choice = 9
                else:
                    guiding, force = False, False
                    dialog.ok(TITLE, 'Addons, Layout und Region zurückgelesen. '
                        'Anmeldung: unbekannt; Bibliothekssync und Darstellung nicht geprüft. '
                        'Offene Emby-Verknüpfungen: ' + str(status.pending_bindings) + '. '
                        'Dienste können optional geöffnet werden; keine erneute Pflichtanmeldung. '
                        'Gewählter Skin aktiv zurückgelesen; Darstellung noch nicht geprüft.')
                    continue
        try:
            if choice == 0:
                summary = ('Komplettsetup für ' + profile_choice.label + ':\n'
                    + ', '.join(item.label for item in required)
                    + '\n\nQuellen: Serph91P/Jurialmunkey, Emby Beta, Kodinerds und Kodi. '
                    'Kataloge aktualisieren und diese feste Auswahl inklusive notwendiger Abhängigkeiten installieren/aktivieren? '
                    'Der Assistent fragt nur einmal. Kodi-eigene Dialoge bleiben bedienbar.')
                if not dialog.yesno(TITLE, summary, 'Abbrechen', 'Alles installieren'):
                    if guiding:
                        return
                    continue
                repo_ok, repo_status = check_requirement(api, REPOSITORY_REQUIREMENT)
                if not repo_ok and (repo_status in ('nicht installiert', 'API-Fehler') or repo_status.startswith('Herkunft')):
                    dialog.ok(TITLE, 'Setup-Quellen fehlen oder sind nicht bereit: ' + repo_status + '\n' + REPOSITORIES)
                    if guiding:
                        return
                    continue
                if not repo_ok:
                    if dialog.yesno(TITLE, 'Das vorhandene Serph91P Repository muss zuerst nativ auf 1.0.3 oder neuer aktualisiert/aktiviert werden. '
                            'Repository-Liste öffnen, Serph91P wählen und native Aktualisierung bestätigen? Danach den Wizard erneut öffnen; '
                            'Jurialmunkey/Emby/Kodinerds werden vom Wizard selbst hinzugefügt. Keine manuelle ZIP-Suche.'):
                        xbmc.executebuiltin('ActivateWindow(AddonBrowser,addons://user/xbmc.addon.repository,return)')
                    return
                official = next(r for r in required if r.addon_id == 'repository.xbmc.org')
                if not check_requirement(api, official)[0]:
                    dialog.ok(TITLE, 'Offizielles repository.xbmc.org muss bereits vorhanden, aktiv und prüfbar sein. Keine Installation über Bootstrap.')
                    return
                for item in required:
                    okay, detail = check_requirement(api, item)
                    if detail.startswith('Herkunft') or detail == 'API-Fehler':
                        if item.addon_id == 'pvr.iptvsimple':
                            from .pvr import distribution
                            if not distribution(api).automatic_install:
                                dialog.ok(TITLE, item.label + ': ' + detail + '\n'
                                    'Setup bleibt unvollständig. Keine Addons installiert; OS-Paketverwaltung und vorhandene PVR-Dateien bleiben unverändert.')
                                return
                        dialog.ok(TITLE, item.label + ': ' + detail + '. In Kodi Versionen/Originalquelle wählen oder manuell neu installieren. Keine automatische Migration.')
                        return
                policy = repository_policy(api)
                if policy.needs_choice:
                    if dialog.yesno(TITLE, 'Kodi Updatequellen sind nicht als „Beliebige Repositories“ zurückgelesen. '
                            'Diese globale Auswahl ist weniger restriktiv und damit weniger sicher als nur offizielle Quellen. '
                            'Für Originalquellen und gepflegte Serph91P-Ausnahmen bei Bedarf selbst in System / Addons wählen. '
                            'Systemeinstellungen jetzt öffnen? Danach den Assistenten erneut öffnen; keine automatische Richtlinienänderung.'):
                        xbmc.executebuiltin('ActivateWindow(systemsettings)')
                    return
                from .catalog import SQLiteCatalogReader, wait_for_catalog
                catalog_reader = SQLiteCatalogReader(xbmcvfs.translatePath,
                    version_read_fn=lambda addon_id: (api.details(addon_id) or {}).get('version'))
                okay, detail = install_with_progress(api, required, dialog, monitor,
                    xbmcgui.DialogProgressBG(), log, approved=True, catalog_reader=catalog_reader)
                if monitor.abortRequested():
                    return
                dialog.ok(TITLE, ('Alle benötigten Addons sind installiert und aktiv. Layout und Anmeldungen bleiben getrennte Schritte.' if okay else
                    'Einrichtung unvollständig. ' + detail + '\n' + REPOSITORIES))
                if guiding and not okay:
                    return
                forced_done.add('addons')
            elif choice == 1:
                if not all_ready():
                    dialog.ok(TITLE, 'Zuerst alle benötigten Addons installieren/aktivieren. Es wurde kein Layout geschrieben.')
                    continue
                if not inactive():
                    if guiding:
                        return
                    continue
                if not dialog.yesno(TITLE, status.layout_detail + '\n' + status.regional_detail + '\n' + describe_layout(profile_choice.key) +
                    '\nDas Layout lässt sich auch vor der Emby-Anmeldung anwenden. Fehlende persönliche Bibliotheken bleiben als Emby einrichten markiert und können später verknüpft werden. '
                    'Portable Skin-Einstellungen sowie Sprache/Region der Vorlage (English, Central Europe) werden übernommen und gesichert. '
                    'Bei einer Sprachänderung lädt Kodi seine Oberfläche selbst neu. '
                    'Bei MOD V2 werden geteilte und private Skin-Shortcuts-Menüs ersetzt; die globale Freigabeeinstellung bleibt unverändert. Fortfahren?'):
                    if guiding:
                        return
                    continue
                from .navigation import binding_path
                from .config import _target
                saved_bindings = _target(profile, binding_path(profile_choice.key)).exists()
                bindings = (load_bindings(profile, profile_choice.key)
                            if guiding and saved_bindings and not force else
                            library_bindings(profile, lambda title, options: dialog.select(title, options)))
                if monitor.abortRequested():
                    return
                backup_root = profile / 'setupwizard-backups'
                if backup_root.is_symlink():
                    raise ValueError('unsafe backup root')
                backup_root.mkdir(mode=0o700, exist_ok=True)
                backup = backup_root / uuid4().hex
                file_changes = (apply_common_layout(profile, backup, profile_choice.key, bindings)
                                if not guiding or not status.layout or force else [])
                from .regional import apply as apply_region
                locale_changes = apply_region(profile, backup, api, approved=True)
                changed = file_changes + locale_changes
                pending = sum(value is None for value in bindings.values())
                message = ('Gemeinsames Medienmenü geschrieben, gesichert und zurückgelesen.'
                           if file_changes else 'Gemeinsames Medienmenü bereits aktuell; keine Dateiänderung.')
                message += ('\nReferenz-Region übernommen, gesichert und zurückgelesen.' if locale_changes
                            else '\nReferenz-Region bereits aktuell und zurückgelesen.')
                if pending:
                    message += ('\nEmby-Verknüpfungen noch offen: ' + str(pending) + '. '
                        'Die markierten Einträge öffnen Emby einrichten; ihre Widgets folgen nach Verknüpfung.'
                        '\nNach Anmeldung/Sync bei neutralem Estuary erneut Layout anwenden.')
                message += '\nGewählten Skin jetzt selbst in Kodi aktivieren. Darstellung noch nicht geprüft.'
                if changed:
                    message += '\nSicherung: ' + str(backup)
                dialog.ok(TITLE, message)
                if monitor.abortRequested():
                    return
                forced_done.add('layout')
                verified = state.inspect(profile, profile_choice.key, api, update_reader)
                if guiding and not verified.configured:
                    dialog.ok(TITLE, 'Einrichtung nach Rücklesen noch unvollständig. Beim nächsten Öffnen fortsetzen.')
                    return
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
                if selected < 0 or not dialog.yesno(TITLE, 'Gesichertes Layout und gegebenenfalls Region wiederherstellen? Nachträgliche fremde Änderungen werden nicht überschrieben. Eine Sprachänderung kann Kodis eigenen Skin-Reload auslösen.'):
                    continue
                from .touch import restore_layout
                restore_layout(profile, backups[selected], xbmc)
                dialog.ok(TITLE, 'Sicherung geprüft und Layout wiederhergestellt. Der Assistent fordert keinen Skin-Reload oder Neustart an. Eine wiederhergestellte Sprache kann Kodis eigenen Skin-Reload auslösen.')
            elif choice == 4:
                lines = [r.label + ': ' + check_requirement(api, r)[1] for r in required]
                policy = repository_policy(api)
                lines.extend((status.layout_detail, status.regional_detail, status.skin_detail, status.menu_detail, status.update_detail,
                              'Native Repository-Richtlinie: ' + str(policy.repository_mode),
                              'Globale automatische Updates: ' + ('aktiv' if policy.automatic_updates else 'nicht aktiv oder unbekannt') +
                              '; Update-Regeln je Addon nicht geprüft', 'Anmeldestatus: unbekannt'))
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
            elif choice == 10:
                if status.menu:
                    dialog.ok(TITLE, status.menu_detail + '. Keine Änderung.')
                    guiding = False
                    continue
                if not status.configured or not status.skin:
                    dialog.ok(TITLE, 'Zuerst Addons, Layout, Region und bestätigte Skinaktivierung abschließen. Keine Menüänderung.')
                    if guiding:
                        return
                    continue
                if not dialog.yesno(TITLE, 'Skin Shortcuts baut jetzt die native Menüansicht aus dem bereits geprüften Layout auf. '
                        'Es kann die Oberfläche nativ neu laden. Keine erneute Layout-/Login-Einrichtung und kein Neustart. Fortfahren?'):
                    return
                from .menus import refresh as refresh_menu
                progress = xbmcgui.DialogProgressBG()
                try:
                    progress.create(TITLE, 'Native Menüausgabe aufbauen und zurücklesen ...')
                    refresh_menu(profile, profile_choice.key, api, monitor, approved=True)
                finally:
                    progress.close()
                dialog.ok(TITLE, 'Native Menüausgabe zurückgelesen. Kein Erfolg allein aus dem Start des Hintergrundauftrags abgeleitet.')
            elif choice == 9:
                if dialog.yesno(TITLE, status.update_detail + '\nNative Liste „Meine Addon-Repositories“ öffnen? '
                        'Jedes dort genannte Repository auswählen, in Addon-Informationen Auto-update selbst aktivieren. '
                        'Bei festgehaltener alter Version ggf. neueste Originalversion nativ neu installieren. '
                        'Dann Assistenten erneut öffnen; bloßes Öffnen wird nicht als Freigabe gewertet.'):
                    xbmc.executebuiltin('ActivateWindow(AddonBrowser,addons://user/xbmc.addon.repository,return)')
                return
            elif choice == 8:
                if status.skin:
                    dialog.ok(TITLE, 'Gewählter Skin ist bereits aktiv zurückgelesen. Keine Änderung.')
                    guiding = False
                    continue
                if not status.configured:
                    dialog.ok(TITLE, 'Zuerst Addons, Layout und Region prüfen/anwenden. Kein Skinwechsel.')
                    if guiding:
                        return
                    continue
                if profile_choice.key == 'touch' and xbmc.getSkinDir() == profile_choice.addon_id:
                    if dialog.yesno(TITLE, 'MOD V2 ist bereits aktiv, sein nativer Touchmodus aber nicht bestätigt. '
                            'Skin-Einstellungen öffnen und dort Touchmodus einschalten? Vorhandene Einstellungen werden nicht still überschrieben.'):
                        xbmc.executebuiltin('ActivateWindow(skinsettings)')
                    return
                if dialog.yesno(TITLE, 'Gewählten Skin jetzt aktivieren: ' + profile_choice.label + '? '
                        'Kodi lädt die Oberfläche nativ neu und öffnet seinen Bestätigungsdialog. '
                        'Dort selbst „Beibehalten / Ja“ wählen. Bei Ablehnung/Timeout bleibt der vorherige Skin. '
                        'Der vorherige Skin wird lokal gesichert. Kein Neustart, keine automatische Bestätigung.'):
                    dialog.ok(TITLE, 'Im folgenden Kodi-Bestätigungsdialog selbst bestätigen. Aktivierung noch nicht verifiziert; '
                              'beim nächsten Öffnen wird der tatsächlich aktive Skin zurückgelesen.')
                    request_activation(profile, profile_choice.key, api, approved=True)
                return
        except Exception as exc:
            log('Vorgang fehlgeschlagen: ' + type(exc).__name__)
            dialog.ok(TITLE, 'Vorgang nicht abgeschlossen. Vorhandene Sicherungen bleiben erhalten. Bei fremden Änderungen verweigert Restore das Überschreiben. Details: ' + type(exc).__name__ + ': ' + str(exc))
            if guiding:
                return
