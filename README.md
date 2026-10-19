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
| plugin.video.youtube | YouTube fork with optional phone-to-profile TubeCast routing (publication pending) |

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

Die freigegebenen Quell-Branches stehen in `scripts/build_repository.py`:
`main` fuer GronkhTV, `master` fuer den YouTube-Fork, sonst `develop`.
Ein erfolgreicher Validierungslauf liefert ein unveraenderliches Paket und dessen
Nachweis. Erst der gepruefte Dispatch aktualisiert die oeffentliche Kodi-Site;
Kodi kann anschliessend eine hoehere Version als Update erkennen.

Die YouTube-/TubeCast-Profilfunktion ist noch nicht allgemein veroeffentlicht.
[Einbindung, Erstveroeffentlichung und Freigabe-Gates](addon-publication/YOUTUBE.md).

## Fuer Entwickler

Die Repository-Aktualiserung erfolgt automatisch ueber `repository_dispatch` Events von den einzelnen Addon-Repos.

Manuelle Wiederholungen beginnen im freigegebenen Quell-Workflow mit
`workflow_dispatch`. Das Ziel nimmt ausschliesslich den validierten
`validated-addon-publication`-Dispatch entgegen; es bietet keinen ungeprueften
manuellen Publish-Bypass.
