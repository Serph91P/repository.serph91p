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

`script.serph91p.setup/` contains a **Kodi 21 development candidate**, not a published wizard yet. See its [scope, prerequisites, safety model and build instructions](script.serph91p.setup/README.md). Version 0.4.1 provides resumable guided setup and automatically requests native installation of missing original repositories; users do not manually install companion repository ZIPs. Repository 1.0.3 supplies three original-repository-only bootstrap feeds; original ZIPs stay on original hosts. Existing maintained Twitch/TubeCast/Gronkh versions remain explicit Serph91P exceptions. A fresh Kodi21.2 test verified installation of all three previously absent repositories through the real production bootstrap, native confirmations, self-origins and indexed catalogs. Its declared loopback metadata transport is not proof of public availability. Current MODV2 installation/activation/touchmode and a real Jurial repository update3.4→3.5 were separately verified. This is not whole-wizard or physical-device acceptance. Public bootstrap URLs/current candidate entries remain unpublished; publication and device acceptance remain open in [issue #41](https://github.com/Serph91P/repository.serph91p/issues/41).
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
3. Der Workflow baut den Wizard aus dem exakten ausgecheckten Commit, erhält bestehende externe Pakete und veröffentlicht die sechs fest geprüften Original-Repository-Bootstrapdateien. Fremde ZIPs werden nicht gespiegelt. Dirty/untracked Quelle oder abweichende Paketdateien werden abgelehnt.
4. Öffentliche Wizard-/Repository-ZIPs und Bootstrap-URLs anschließend wirklich abrufen und eine frische Kodi-Installation prüfen. Ein lokal erfolgreicher Build ist keine erfolgte Veröffentlichung.

Der normale validierte Upstream-Publikationspfad nimmt dieselbe geprüfte eigene Quelle mit; beide Wege teilen die Pages-Concurrency. Die Quellprovenienz des Wizards ist bewusst keine nachgeahmte externe Workflow-Validierungs-ID.
Manuelle Wiederholungen beginnen im freigegebenen Quell-Workflow mit
`workflow_dispatch`. Das Ziel nimmt ausschliesslich den validierten
`validated-addon-publication`-Dispatch entgegen; es bietet keinen ungeprueften
manuellen Publish-Bypass fuer fremde Pakete. Der gepruefte eigene Wizard hat den oben getrennt beschriebenen Pfad.
