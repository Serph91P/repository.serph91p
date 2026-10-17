# Serph91P Kodi Setup Wizard

**Version 0.2.0: local Kodi 21/Omega candidate, not a repository release or device-approved setup.**

## Skin choice and actual layout coverage

The wizard asks for one of three profiles:

- **Schön: Arctic Fuse 3.** Curated movie/series/Twitch/YouTube hubs and local-library widgets. Existing Arctic settings outside the curated set are preserved.
- **Schnell: Amber.** An Amber-specific Skin Shortcuts menu with Live TV, EPG, YouTube, movies, series, Twitch, Gronkh.tv, resume and recently-added views. It is not the same visual widget layout as Arctic. The target is `addon_data/script.skinshortcuts/skin.amber-mainmenu.DATA.xml`, not a shared menu: Amber's verified `doNotShareMenu` override requires the skin prefix.
- **Touch: Estuary with touchmode.** Kodi's bundled skin exposes an actual touchmode setting. Activation is confirmation-gated, records the previous false state locally before the native runtime change, waits for the builtin to execute and reads its result back. Existing true state is a no-op. Restore uses the same supported runtime API. The native touch home screen is not rewritten or misrepresented as an Arctic clone.

All skins have the same fixed **Inhalte öffnen** destinations in the wizard. Amber uses these destinations in its main menu too. Local-library resume views depend on the device's own Emby sync and resume data; they are not a personal server-side resume/recommendation export. Touch keeps its native layout, so not every common destination is an extra top-level home tile.

### Why not Estouchy by default?

[Estouchy's official source](https://github.com/xbmc/skin.estouchy) is not archived, but the latest source commit found is `31fe633093718505eb2c6f719b5b571afdc45997` from **2024-02-06**, version 4.0.0. That is not evidence of active current maintenance. Estouchy is also absent from the checked [official Omega add-on index](https://mirrors.kodi.tv/addons/omega/addons.xml.gz). Neither fact alone proves abandonment or incompatibility on every platform, but automatic fresh-device availability must not be promised.

Instead this candidate uses **Estuary 4.0.0 bundled in Kodi Omega**. Its [official SkinSettings.xml](https://github.com/xbmc/xbmc/blob/Omega/addons/skin.estuary/xml/SkinSettings.xml) explicitly exposes `Skin.ToggleSetting(touchmode)` / `Skin.HasSetting(touchmode)`. The wizard uses the equivalent fixed `Skin.SetBool(touchmode)` and `Skin.Reset(touchmode)` operations, not active-skin XML edits. This is a documented-feature recommendation, not a touch usability benchmark.

## Common media add-ons

Each profile requests the same media add-ons through Kodi's add-on manager:

- Emby Next Gen (`plugin.service.emby-next-gen`), not the legacy Python-2 Emby ID.
- Twitch, YouTube and Gronkh.tv.
- TubeCast and PVR IPTV Simple.

Only the selected skin is required; Amber/Touch do not force-install Arctic or its helpers. Skin dependencies and platform-specific PVR binaries are resolved by Kodi. No foreign binary ZIP is copied across devices. TubeCast/PVR open their own settings, not fictitious video-plugin routes. Account, Emby server/library sync, IPTV playlist and EPG choices remain device-local. YouTube may require API/OAuth setup in addition to sign-in.

This is a curated declared set, not an automatic clone of every add-on or setting from an old device. Repository manager confirmations and missing sources can still interrupt installation and are reported as incomplete.

## Safety and prerequisites

- Kodi 21/Omega, Python 3 and a writable local profile are required. Other Kodi majors are rejected. Android/LibreELEC/Windows/iOS behavior is not device-validated.
- Configure the needed repositories first: Jurialmunkey Omega for Arctic; compatible Emby Next Gen source; Serph91P for Twitch/Gronkh/TubeCast; compatible YouTube source; official Kodi repository/platform packages for Amber and IPTV Simple. The wizard does not silently bootstrap missing repositories.
- File-based layouts/restore require neutral **Estuary** to be active; select the desired final skin manually afterward. No automatic skin switch, reload or restart occurs. Touchmode is a small explicit native runtime setting, not a skin reload.
- Only fixed per-profile file allowlists may be changed. Profile and symlink checks, complete preimages, persisted hash manifests, atomic writes/readback and drift-aware restore protect layout changes. Old Arctic v1 manifests remain supported; Amber uses a profile-bound v2 manifest; touchmode uses a narrowly validated v3 runtime-state manifest with no supplied executable action.
- Accounts, cookies, OAuth tokens, personal databases, private source URLs, device paths and raw backup data are never shipped. Do not publish local preimage backups; existing settings in those backups may be private.
- No `favourites.xml` edits are performed while Kodi holds its favourites in memory. No Kodi add-on database or add-on code directory is modified directly.
- This is not a security boundary against a hostile concurrent writer in the same profile.

**The original one-repo/only-login goal is still not a released end-to-end feature.** External-repository bootstrap, immutable publication integration and fresh-device skin/navigation/sync/login acceptance remain open. No production publication pipeline changes are included.

## Build and test

From the repository root, use an isolated Python environment with PyYAML for existing workflow tests:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_setup_wizard tests.test_setup_config_safety tests.test_setup_package tests.test_setup_profiles tests.test_setup_layout_profiles -v
PYTHONDONTWRITEBYTECODE=1 python3 tools/build_setup_addon.py --output-dir dist
```

The ZIP builder has a fixed runtime-member allowlist and deterministic timestamps. No tests, documentation, caches or personal backups are packaged. Tests exercise `default.py` using a restricted supported Kodi module surface and real temporary-file transactions, but do not claim real Kodi rendering or device acceptance. Compare full-suite results against an untouched source baseline; existing date-sensitive publication fixtures must not be weakened to get a green result.

Additional primary sources: [Amber's official Omega metadata](https://github.com/xbmc/repo-skins/blob/omega/skin.amber/addon.xml), [Amber menu format](https://github.com/bartolomesoriano/skin.amber/blob/master/shortcuts/mainmenu.DATA.xml), [Amber overrides](https://github.com/bartolomesoriano/skin.amber/blob/master/shortcuts/overrides.xml), and the official Omega Skin Shortcuts 2.0.3 package's `resources/lib/skinshorcuts/datafunctions.py` for skin-prefixed menu paths. Supported Kodi API contracts are in [Kodi Omega's interfaces](https://github.com/xbmc/xbmc/tree/Omega/xbmc/interfaces).
