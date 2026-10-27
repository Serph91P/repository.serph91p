# Serph91P Kodi Repository

Custom Kodi addon repository hosted on GitHub Pages.

## Enthaltene Addons

| Addon | Beschreibung |
|-------|-------------|
| plugin.video.gronkhtv | Gronkh.tv Stream-Archiv |
| plugin.video.twitch | Twitch fuer Kodi |
| script.module.python.twitch | Twitch API Modul |
| plugin.video.plexkodiconnect | PlexKodiConnect |
| plugin.video.plexkodiconnect.movies | PlexKodiConnect Filme |
| plugin.video.plexkodiconnect.tvshows | PlexKodiConnect Serien |
| script.tubecast | TubeCast - YouTube Cast |
| plugin.video.youtube | YouTube fork with optional phone-to-profile TubeCast routing |

## Installation in Kodi

1. **Kodi oeffnen** → Einstellungen → Dateimanager
2. **Quelle hinzufuegen** → URL eingeben:
   ```
   https://serph91p.github.io/repository.serph91p/
   ```
   Name: `Serph91P Repository`
3. Zurueck zum Hauptmenue → **Addons** → **Aus ZIP-Datei installieren**
4. `Serph91P Repository` waehlen → `repository.serph91p/` → ZIP-Datei waehlen
5. Danach kann ueber **Aus Repository installieren** → **Serph91P Repository** jedes Addon installiert werden

## Automatische Updates

Eigene gepflegte Addons können über die bestehende Veröffentlichungspipeline aktualisiert werden. In Kodi müssen dafür der richtige Repository-Ursprung, globale Update-Einstellungen und die automatische Aktualisierung des einzelnen Addons passen. Eine Veröffentlichung allein beweist keine erfolgte Installation am Gerät. Fremde Addons im neuen Wizard-Kandidaten sollen über ihre ursprünglichen Repository-IDs aktualisiert werden, nicht als Kopien unter unserem Repository.

## Arctic setup wizard candidate

`script.serph91p.setup/` contains the **Kodi 21 setup wizard 0.4.3**. See its [profiles, prerequisites, migration and safety model](script.serph91p.setup/README.md). It resumes from live state, adds missing original repositories itself and guides existing add-ons through Kodi's native Versions dialog without uninstalling or resetting account data. Repository 1.0.3 provides four repository-only bootstrap feeds, including AdamsBuilds; original packages remain upstream. Choose Arctic Fuse 3, Amber, Rotary touch grid or Nimbus Plus with native helper menus/widgets. Existing Estuary MOD V2 is retained but no longer offered for new setup. Maintained Twitch/YouTube/TubeCast/Gronkh forks are protected from downgrade. Publication requires the successful main-branch Pages workflow below; local fixture transport is not public availability. Physical touch, accounts and playback still require device acceptance.
Die freigegebenen Quell-Branches stehen in `scripts/build_repository.py`:
`main` fuer GronkhTV, `master` fuer den YouTube-Fork, sonst `develop`.
Ein erfolgreicher Validierungslauf liefert ein unveraenderliches Paket und dessen
Nachweis. Erst der gepruefte Dispatch aktualisiert die oeffentliche Kodi-Site;
Kodi kann anschliessend eine hoehere Version als Update erkennen.

Die Profilfunktion ist ab YouTube `7.4.4.1` und TubeCast `1.6.1+omega.2` verfuegbar.
[Einbindung, Erstveroeffentlichung und Freigabe-Gates](addon-publication/YOUTUBE.md).

## Fuer Entwickler

Externe Addon-Versionen werden ausschließlich über validierte immutable Artefakte und `validated-addon-publication`-Events veröffentlicht. Der Workflow **Update Repository** ist kein manueller oder ungeprüfter ZIP-Import.

Die eigene Wizard-Quelle hat einen getrennten, manuellen Veröffentlichungspfad:
1. Geprüfte Änderungen nach Freigabe auf `main` übernehmen.
2. Nach Publikationsfreigabe unter Actions → **Publish target-owned Setup source** → **Run workflow**, Branch `main`, ausführen.
3. Der Workflow baut den Wizard aus dem exakten ausgecheckten Commit, erhält bestehende externe Pakete und veröffentlicht die acht fest geprüften Original-Repository-Bootstrapdateien. Fremde ZIPs werden nicht gespiegelt. Dirty/untracked Quelle oder abweichende Paketdateien werden abgelehnt.
4. Öffentliche Wizard-/Repository-ZIPs und Bootstrap-URLs anschließend wirklich abrufen und eine frische Kodi-Installation prüfen. Ein lokal erfolgreicher Build ist keine erfolgte Veröffentlichung.

Der normale validierte Upstream-Publikationspfad nimmt dieselbe geprüfte eigene Quelle mit; beide Wege teilen die Pages-Concurrency. Die Quellprovenienz des Wizards ist bewusst keine nachgeahmte externe Workflow-Validierungs-ID.
Manuelle Wiederholungen beginnen im freigegebenen Quell-Workflow mit
`workflow_dispatch`. Das Ziel nimmt ausschliesslich den validierten
`validated-addon-publication`-Dispatch entgegen; es bietet keinen ungeprueften
manuellen Publish-Bypass fuer fremde Pakete. Der gepruefte eigene Wizard hat den oben getrennt beschriebenen Pfad.
