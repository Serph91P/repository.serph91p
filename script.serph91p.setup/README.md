# Serph91P Arctic Setup Wizard

**Local development candidate for Kodi 21/Omega. Not published or device-approved.**

## What this candidate does

The German wizard exposes separate actions to check/install the required add-ons through Kodi's configured repositories, apply a curated portable Arctic Fuse 3 layout, open service sign-in/settings entry points, show status, and restore a layout backup. Each install/enable and each layout write requires confirmation. Installation waits are bounded and verify enabled state plus minimum version, rather than merely the add-on's presence.

The layout provides movie, series, Twitch and YouTube hubs, local-library movie/episode widgets, and safe add-on-root shortcuts. It deliberately does not copy a personal Kodi backup, hardcode Emby library-node names, or promise authenticated recommendations/followed-channel widgets before sign-in. Movies and series require a local library populated by the user's own Emby sync. This is not a byte-for-byte personal layout export.

The wizard never copies accounts, passwords, cookies, OAuth tokens, databases, sources.xml, guisettings.xml, or device paths. It does not fetch arbitrary ZIP URLs, extract add-ons itself, modify Kodi's add-on database, switch/reload skins or restart Kodi. Account and library choices remain on the target device.

## Prerequisites and limits

- Kodi 21/Omega with Python 3, a writable local profile, and normal add-on-manager access. Other Kodi major versions are rejected by this candidate. Android/LibreELEC/Windows behavior is not yet device-tested.
- Configure **Jurialmunkey's Omega repository** (`repository.jurialmunkey`) for Arctic Fuse 3 and its dependencies. The observed live index offers Arctic Fuse 3.3.12, Skin Variables 2.2.9, TMDb Helper 6.17.9 and Texture Maker 0.2.11.
- Configure a compatible **Emby Next Gen** repository (`repository.beta.emby.kodi` for the referenced setup). The intended add-on ID is `plugin.service.emby-next-gen`, not the legacy Python-2 `plugin.video.emby`. Repository metadata from an earlier install is not proof of current endpoint reachability.
- The existing **Serph91P repository** supplies Twitch and Gronkh.tv. A compatible **YouTube** source is also required; the wizard does not silently bootstrap external repositories.
- Kodi must allow the configured repository to satisfy the requested add-ons. Repository availability and dependencies are handled by Kodi and may still require native confirmations. A timeout/cancellation or unavailable package is reported as incomplete, not success.
- Applying/restoring the layout requires Arctic Fuse 3 to be inactive. Select Estuary manually first, then select Arctic manually afterward. The wizard deliberately does not restart or reload the skin.
- YouTube may require additional API/OAuth configuration beyond a login. Emby needs device-local server and library-sync choices. This candidate opens the relevant settings/add-on; it neither handles nor verifies credentials.

**The requested “add one repo, install everything, then only log in” experience is not yet achieved.** Safe external-repository bootstrapping, integration with this repository's immutable publication contract, and fresh-device acceptance remain release gates. The production repository/publication pipeline is unchanged.

## Safety model

Only an exact allowlist of Arctic layout-node JSON files and selected merged Arctic skin settings may be written, relative to `special://profile` (already Kodi's userdata directory). Untouched skin settings are preserved. Complete local backups and a hash manifest precede layout mutation; restore validates the manifest and preserves conflicting user changes. Existing backup directories are not overwritten. Symlinks and path traversal are refused. Reapplying identical content is a no-op. Backups may contain the device's pre-existing skin configuration and therefore remain local; do not publish them.

Atomic writes reduce interrupted-file damage. This is not a security boundary against a hostile concurrent process modifying the same profile. The real skin/parser and on-device interruption behavior remain acceptance work.

## Build and test

From the repository root, with Python 3 and PyYAML installed in an isolated environment for the existing workflow tests:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_setup_wizard tests.test_setup_config_safety tests.test_setup_package -v
PYTHONDONTWRITEBYTECODE=1 python3 tools/build_setup_addon.py --output-dir dist
```

The builder uses a fixed runtime-file allowlist and deterministic ZIP timestamps. No test fixtures, README, private metadata, caches or backup files are packaged. Run the full existing suite separately and compare any pre-existing fixture-date failures with an unchanged baseline; do not equate a local mock run with Kodi runtime evidence.

Supported API references: Kodi Omega `xbmc/interfaces/legacy/Addon.h`, `xbmc/interfaces/builtins/AddonBuiltins.cpp`, and `xbmc/interfaces/json-rpc/schema/methods.json` in [Kodi's source](https://github.com/xbmc/xbmc/tree/Omega/xbmc/interfaces). The adapter uses `Addons.GetAddonDetails`, `Addons.SetAddonEnabled`, `Application.GetProperties`, `InstallAddon(...)` and `xbmcvfs.translatePath`. A real-module-surface test executes `default.py` with only these supported methods exposed.
