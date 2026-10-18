# Serph91P Kodi Setup Wizard

**0.3.4 development candidate for Kodi 21/Omega. Not released or device-approved.**

## One repository, three profiles

The paired `repository.serph91p` **1.0.1** candidate exposes Serph91P, Jurialmunkey Omega, Emby Next Gen **beta for Kodi 21**, and Kodinerds Omega/Matrix catalogs using Kodi's native multi-directory repository mechanism. No third-party repository ZIP search, manual extraction into addon directories, database edits or imaginary installation APIs.

For this unpublished candidate, install/update **one Serph91P repository ZIP first**, then install the wizard ZIP. After publication, Kodi should install the wizard from that repository; publication integration and fresh-device acceptance remain separate gates. The wizard is not yet in the live catalog. Its declared repository 1.0.1 dependency cannot be satisfied by the old repository ZIP.

Extra catalogs apply only to Kodi 21. Kodi records their packages as originating from `repository.serph91p`. Catalogs/packages remain upstream-hosted, not copied, signed or immutable mirrors. MD5 catalog change tokens are not signatures or package SHA-256 pins. `validate_setup_sources.py` checks live checksum consistency and rejects ambiguous equal-version IDs across the five federated catalogs. Normal official Kodi catalogs provide YouTube, Amber, official resources and platform-specific IPTV binaries.

Profiles:
- **Arctic Fuse 3:** native Skin Variables hubs, widgets and submenus.
- **Amber:** private Skin Shortcuts main menu and content submenus. Same media structure, not an Arctic-style widget clone.
- **Touch: Estuary MOD V2:** customizable main menu, native personal-widget lists and matching submenus; its own touchmode flag is enabled while inactive. Replaces the old bundled Estuary-touch choice. Legacy touch backups remain restorable.

Every profile requests Emby Next Gen, Twitch, YouTube, Gronkh.tv, TubeCast, IPTV Simple and TMDb Helper. Skin requirements stay profile-scoped. Kodi resolves transitive dependencies and platform binaries. The progress bar counts verified addons, not download bytes, shows the current addon/wait status and closes on success, failure or exception. The wizard shows the complete profile-scoped list once and asks for one batch approval; it does not repeat its own question for each addon. A declined or missing batch approval causes no refresh, install or enable request. Native Kodi confirmations stay interactive: Omega InstallAddon hardcodes InstallModalPrompt::CHOICE_YES, so every newly installed addon can still trigger Kodi's own prompt. No native dialogs are automatically accepted or safety settings changed.

### Grouped native installation candidate

For grouped dependency installation, the candidate additionally provides one fixed native dependency-module ZIP per skin, generated with `python tools/build_setup_bundle.py`. The user explicitly installs the chosen bundle through Kodi Install from ZIP; Kodi resolves its complete dependency graph instead of the wizard issuing InstallAddon per package. Only the chosen skin and its fixed requirements are declared, not all three skins. Repository1.0.1 must already be installed and its catalogs loaded. Bundles contain only addon.xml and an inert module marker, no installer script, security override, credentials, wizard payload or layout changes. This manual candidate bootstrap is not yet a button-integrated published repository bundle and has not been device-validated. Kodi security/dependency-error dialogs and addon login/setup dialogs may remain; zero native dialogs is not promised. Removing the marker is not an automatic rollback of downloaded dependencies; use the agreed fresh test profile.

Candidate flow: keep the normal Estuary skin active; update wizard0.3.4; explicitly install the bundle ZIP matching the chosen skin (`touch` means Estuary MOD V2), wait for Kodi installation to finish, then open the wizard, select that profile and verify the complete addon list before applying its layout. Do not install all three bundles unless all three setups are actually wanted. The dependency bundle does not replace or update the wizard.

An installation request or a timeout is never reported as success. Native repository refresh is requested, not falsely claimed complete.

## Current portable reference correction in0.3.4

The current reference was read without changing the source device. Arctic imports275 portable native style/control/icon settings with their real bool/string types, including its settings level, options tiles, colors, background and empty unused-slot toggles. Device-specific node URLs and generated caches are excluded; content bindings stay local. The exact typed locale values were read through Kodi21 Settings.GetSettingValue, including its keyboard-layout list. Layout approval explicitly includes the reference language/region (English, Central Europe). Native Settings.SetSettingValue performs whitelisted changes only, journals preimages before mutation and verifies readback; no active guisettings.xml edits or OS timezone/network/account changes.

MODV2 emits both shared and skin-prefixed user menu families, without changing global shared_menu. Thus it no longer intentionally leaves a configured private menu family absent and falls through to packaged stock menus. Native rebuild/rendering on the user device still requires acceptance; no silent native-dialog confirmation is performed.

## Amber native shelves in0.3.4

Official Omega Amber3.99.02 has doNotShareMenu, so its generated skin.amber-prefixed menus are used regardless of shared_menu. Its six native shelf slots use the unnumbered widget* family and .2 through .6, not invented shelf/resume/recent properties. Ready rows use the same target-local paths as the common media model, video target, native Library/Playlist/Addon source IDs and Poster/Thumb/Square artwork. Unused slots explicitly disable native defaults; deferred Series never substitutes the unfiltered all-TV-shows view. Resume-series rows are episodes with Thumb artwork. This is a source-contract correction, not a claim of real Amber rendering acceptance.

## Previous sidebar icon correction in0.3.3

Arctic now receives the five portable native sidebar icon choices from the supplied reference backup. Exact native consumers and icon files were checked against the official3.3.12 package. Legacy template/backup settings remain unchanged. This is a scoped icon correction, not a claim that full skin/locale migration, MOD-V2 menu consumption or target-device rendering is complete.

## Shared LibreELEC-reference structure

All adapters consume one semantic model (`navigation.py`), in this order:
- **Movies:** In-Progress Movies, New Movies, Top Rated Movies, Genres.
- **Series:** Fortsetzen, Neu, Top Rated, Genres.
- **Twitch:** Following Live Channels, Twitch VOD fortsetzen, Neue Twitch VODs, Latest uploads (Gronkh.tv).
- **YouTube:** Recommendations, My Subscriptions, Search.
- **Live TV:** Sender and Programm/EPG, visible after the local PVR configuration has channels. Arctic keeps its native PVR slot; the other skins expose equivalent native destinations. IPTV sources are not copied.

Labels, order and destinations are shared; presentation is skin-specific. Utility controls can differ. Content actions also work via fixed program-entrypoint arguments. No credentials, authenticated reference-device paths or raw userdata backups are distributed.

**The layout can be applied before personal Emby setup.** Missing Series/Twitch-VOD bindings are explicitly stored as null. Their native submenu labels say **Emby einrichten** and open Emby's own settings; unresolved paths are never emitted as content widgets. Other groups and public widget routes remain available, subject to their own login requirements. This is layout success, not media/login success.

After Emby login and sync, reapply the layout using neutral Estuary to select local Series and Twitch-VOD libraries. Each can be skipped independently; a missing Twitch-VOD library never blocks Series or the layout. Resume/new/genres use only the target's own discovered nodes, never copied server IDs or an all-series fallback. Existing complete bindings from 0.3.0 and their backups remain valid. Accounts, IPTV/EPG, YouTube API/OAuth and library choices stay local.

## Apply and restore

Use neutral **bundled Estuary** while applying/restoring files, then manually select the final skin. No explicit skin-switch/reload/restart builtin is invoked. Changing language via the supported native setting can cause Kodi itself to reload its UI; the approval warns about this. MOD V2 replaces both shared `addon_data/script.skinshortcuts/mainmenu.DATA.xml` and its skin.estuary.modv2-prefixed family; confirmation warns that other sharing skins are affected. Global sharing preference is preserved. Amber's private `skin.amber-*` menus remain separate. Unrelated inactive-skin settings are preserved.

Each adapter has an exact path policy. Symlink checks, bounded regular files, complete preimages, persisted hash manifests, atomic replacement and readback protect changes. Original common layouts retain exact schema4 policies; dual-family MODV2 uses a separate schema5 policy. Native locale-only backups use schema6, and combined file+native backups use schema7/8 with a required hash-bound locale companion. Original schema1/2/3/4 path shapes retain their validation. Native restore refuses user drift and attempts retry-safe restoration; missing/corrupt native companions never silently become file-only restores. Restore refuses user drift. Local backups can contain private preimages and must not be published. No cached favourites, active-skin XML, addon sources or Kodi addon database is edited. This is not a boundary against a hostile concurrent writer in the same profile.

## Build and evidence

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_setup*.py' -v
python3 tools/validate_setup_sources.py --report /your/task-workspace/sources.json
python3 tools/build_setup_repository.py --output-dir dist
python3 tools/build_setup_addon.py --output-dir dist
python3 tools/build_setup_bundle.py --output-dir dist
```

Bundle ZIPs are generated artifacts, intentionally not checked into Git. For this unpublished candidate, distribute the chosen profile ZIP directly alongside the wizard ZIP; a source checkout can reproduce it with the command above. Repository catalog/button integration is a separate open publication step.

Builders have fixed member allowlists and repeatable timestamps. Packages exclude tests, docs, caches, local bindings, backups and credentials. Tests emulate supported Kodi module surfaces, not real rendering or installation. Compare the full suite against an untouched baseline; do not weaken unrelated date-sensitive publication fixtures.

Primary sources: [Kodi repository implementation](https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/addons/Repository.cpp), [installer builtins](https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/interfaces/builtins/AddonBuiltins.cpp), [MOD V2 package-version source](https://github.com/b-jesch/skin.estuary.modv2/tree/cc5401c952e15d23509d0dbaf34a704474052e53), [Kodinerds](https://repo.kodinerds.net/), [Jurialmunkey Omega](https://jurialmunkey.github.io/repository.jurialmunkey/omega/zips/addons.xml), [Emby Omega beta](https://embydata.com/downloads/addons/xbmb3c/multi-repo/beta/v21_omega/addons.xml), and official Omega Skin Shortcuts 2.0.3.
