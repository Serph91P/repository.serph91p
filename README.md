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

`script.serph91p.setup/` contains a **Kodi 21 development candidate**, not a published wizard yet. See its [scope, prerequisites, safety model and build instructions](script.serph91p.setup/README.md). Version 0.4.0 adds resumable guided setup, live state/origin inspection and an explicit setup-again path, while preserving the portable Arctic/Amber/current Omega MODV2 reference layouts. Repository 1.0.2 replaces foreign leaf-catalog federation with three original-repository-only bootstrap feeds; original repository ZIPs stay on original hosts. Existing maintained Twitch/TubeCast/Gronkh versions remain explicit Serph91P exceptions. Native Kodi21.2 testing has verified original bootstrap, current MODV2 installation/activation/touchmode and a real Jurial repository update3.4→3.5; this is not whole-wizard or physical-device acceptance. New bootstrap URLs/public candidate entries remain unpublished. Integration/review, immutable publication and fresh-device validation remain open in [issue #41](https://github.com/Serph91P/repository.serph91p/issues/41).

## Fuer Entwickler

Externe Addon-Versionen werden ausschließlich über validierte immutable Artefakte und `validated-addon-publication`-Events veröffentlicht. Der Workflow **Update Repository** ist kein manueller oder ungeprüfter ZIP-Import.

Die eigene Wizard-Quelle hat einen getrennten, manuellen Veröffentlichungspfad:
1. Geprüfte Änderungen nach Freigabe auf `main` übernehmen.
2. Nach Publikationsfreigabe unter Actions → **Publish target-owned Setup source** → **Run workflow**, Branch `main`, ausführen.
3. Der Workflow baut den Wizard aus dem exakten ausgecheckten Commit, erhält bestehende externe Pakete und veröffentlicht die sechs fest geprüften Original-Repository-Bootstrapdateien. Fremde ZIPs werden nicht gespiegelt. Dirty/untracked Quelle oder abweichende Paketdateien werden abgelehnt.
4. Öffentliche Wizard-/Repository-ZIPs und Bootstrap-URLs anschließend wirklich abrufen und eine frische Kodi-Installation prüfen. Ein lokal erfolgreicher Build ist keine erfolgte Veröffentlichung.

Der normale validierte Upstream-Publikationspfad nimmt dieselbe geprüfte eigene Quelle mit; beide Wege teilen die Pages-Concurrency. Die Quellprovenienz des Wizards ist bewusst keine nachgeahmte externe Workflow-Validierungs-ID.
