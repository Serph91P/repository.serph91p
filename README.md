# Serph91P Kodi Repository

Custom Kodi addon repository hosted on GitHub Pages.

## Enthaltene Addons

| Addon | Beschreibung |
|-------|-------------|
| plugin.video.gronkhtv | Gronkh.tv Stream-Archiv |
| plugin.video.twitch | Twitch fuer Kodi |
| script.module.python.twitch | Twitch API Modul |
| plugin.video.plexkodiconnect | PlexKodiConnect |
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

## Fuer Entwickler

Die Repository-Aktualiserung erfolgt automatisch ueber `repository_dispatch` Events von den einzelnen Addon-Repos.

Manuell kann das Repository mit folgendem Workflow-Dispatch aktualisiert werden:
1. Gehe zu Actions → "Update Repository"
2. Klicke "Run workflow"
