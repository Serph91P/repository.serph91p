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

Alle Addons werden automatisch aktualisiert wenn:
- Ein Push auf den `main` Branch eines Addon-Repos erfolgt
- Die GitHub Actions Pipeline automatisch eine neue Version baut
- Kodi erkennt das Update und installiert es automatisch

## Arctic setup wizard candidate

`script.serph91p.setup/` contains a **Kodi 21 development candidate**, not an add-on published in the repository yet. See its [scope, prerequisites, safety model and build instructions](script.serph91p.setup/README.md). Version 0.3.3 restores the reference Arctic sidebar icons and asks for one wizard-owned approval of the fixed addon list (native Kodi prompts remain), allows layout application before Emby login/sync and marks unbound entries explicitly. It offers Arctic Fuse 3, Amber and Estuary MOD V2, a common LibreELEC-reference media structure and verified installation progress. The paired repository 1.0.1 candidate exposes the necessary upstream catalogs natively; one manual update of that own-repository ZIP is needed for the unpublished test. Skin-specific layouts differ; no identical Arctic widgets on touch are promised. Native catalog federation and menu adapters are source candidates; publication integration and fresh-device validation remain open in [issue #41](https://github.com/Serph91P/repository.serph91p/issues/41).

## Fuer Entwickler

Die Repository-Aktualiserung erfolgt automatisch ueber `repository_dispatch` Events von den einzelnen Addon-Repos.

Manuell kann das Repository mit folgendem Workflow-Dispatch aktualisiert werden:
1. Gehe zu Actions → "Update Repository"
2. Klicke "Run workflow"
