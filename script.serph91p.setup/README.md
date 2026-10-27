# Serph91P Kodi Setup Wizard

**0.4.1 development candidate for Kodi 21/Omega. Not released or device-approved.**

## One repository, three profiles

The paired `repository.serph91p` **1.0.3** candidate exposes its own catalog plus three **repository-addon-only bootstrap catalogs**. Install the wizard from the existing Serph91P repository. The wizard itself requests native installation of missing `repository.jurialmunkey`, `repository.beta.emby.kodi`, and/or `repository.kodinerds`, as required by the selected profile, before installing leaf add-ons. Users confirm Kodi's native prompts, not manually locate/install three companion ZIPs. Original repository ZIPs remain on their original hosts. Kodi records each repository's own ID and leaf add-ons' actual installing repository. The former upstream-leaf federation under Serph91P is removed.

There are no repository dependency imports, including the own repository: Kodi explicitly refuses that installation mechanism. The own source is checked at runtime. An old own repository must be updated through Kodi's native repository UI; `InstallAddon` does not update an already installed add-on. The wizard opens that UI instead of pretending to update it or timing out. Catalog readiness also checks the indexed version against the installed repository, so a stale pre-upgrade checksum cannot pass. Missing/unknown own sources fail closed.

**The candidate is not a functioning public bootstrap yet:** the new Pages bootstrap URLs and current wizard/repository entries are not published. Installing the candidate ZIP alone does not make those URLs available. Local native tests use an explicitly declared loopback transport substitution, not fabricated production responses. First-party publication integration and fresh-device acceptance remain separate gates.

Bootstrap feeds apply only to Kodi 21 and contain no foreign leaf add-ons. Three bounded HTTPS original repository downloads are SHA-256-pinned and their manifests compared to the generated bootstrap metadata by `validate_setup_sources.py`. Catalog MD5 tokens remain change tokens, not signatures. Installed origins are read narrowly from native Addons33, read-only; missing/ambiguous/unreadable data fails closed. Correct versions alone never prove origins. An existing same-version Serph91P-origin foreign leaf needs Kodi's user-mediated version/reinstall path, not an automatic uninstall or database edit.

### Resume and updates

The wizard persists only schema and selected profile, never trusted completion flags or credentials. Each open rechecks live add-ons/origins, generated layout bytes and native locale. Unchanged steps are skipped; partial setup resumes and drift requires renewed approval. **Setup erneut ausführen** deliberately repeats choices without deleting accounts. Unknown login state stays unknown.

Kodi's `addons.updatemode` (official-only versus any repositories) and `general.addonupdates` (global automatic-update intent) are different settings. No security policy is silently changed. Per-add-on `update_rules` can still prevent updates even with global auto-update enabled: native testing reproduced this for newly installed repository add-ons. A user can enable **Auto-update** in that repository's native information dialog; no SQL writes or auto-clicks are used by the wizard. Opening settings alone is not consent or successful readback. Async repository refresh also needs indexed-catalog readback before leaf installation.

Profiles:
- **Arctic Fuse 3:** native Skin Variables hubs, widgets and submenus.
- **Amber:** private Skin Shortcuts main menu and content submenus. Same media structure, not an Arctic-style widget clone.
- **Touch: Estuary MOD V2:** customizable main menu, native personal-widget lists and matching submenus; its own touchmode flag is enabled while inactive. Replaces the old bundled Estuary-touch choice. Legacy touch backups remain restorable.

Every profile requests Emby Next Gen, Twitch, YouTube, Gronkh.tv, TubeCast and IPTV Simple. TMDb Helper is shared for Series / Top Rated; the other Arctic helpers stay Arctic-scoped. Twitch 3.1.11, TubeCast 1.6.1+omega.2 and Gronkh.tv 2.3.10 are deliberately Serph91P-maintained versions; older official versions are not silently substituted. The original Kodi sources provide Amber, YouTube and appropriate resources.

### Native menu readiness

Amber and Touch both need TMDb Helper (shared Series / Top Rated) from Jurialmunkey and Skin Shortcuts 2.0.3+ from Kodi's original repository. These helpers are dependencies, not additional login questions. The wizard checks the native compiled menu's labels and actions, not just its editable DATA.xml input. If stale, an explicit guided step uses Skin Shortcuts' native buildxml/reload mechanism and waits for matching output; no active skin XML is edited. Already-current output is not rebuilt. Native XML settings save/reordering is compared semantically while generated input menus and rollback hashes remain byte-exact. MOD V2 readiness also requires the live native touchmode flag, not merely the selected skin name.

Platform-specific PVR provenance is checked separately: official Kodi Android/Windows use `repository.xbmc.org`; LibreELEC uses its enabled native system repository `repository.libreelec.tv`, not Kodi's generic repository. Generic Linux distro packages remain OS-managed/unverified and stop complete automatic setup without attempting installation or repair. A system-origin UUID is never a global provenance exemption. The progress bar counts verified add-ons, not download bytes, and closes on failure/cancellation too. One wizard-owned batch approval does not suppress Kodi's own interactive install/security dialogs. Declining approval causes no refresh/install/enable request.

### Grouped native installation candidate

Optional inert dependency bundles version 0.2.0 are generated with `python tools/build_setup_bundle.py`. They contain no repository dependency imports: Kodi explicitly refuses repository-type dependencies. Install and index the required original repositories first; bundles do not establish or migrate origins. Their contents are only addon.xml and an inert module marker, no installer/security override, credentials or layout payload. They are not the default guided flow and are not a released one-click substitute. Removing a marker does not roll back downloaded dependencies.

Candidate flow: use a fresh profile and neutral bundled Estuary for backed layout writes. Open the wizard and choose one profile; verify native original repositories, policy, indexed catalogs and installed origins before applying its layout. Personal account/sync/IPTV choices stay local. Selecting all three bundles is not required. Skin activation must be an explicit user choice with Kodi's own keep-change confirmation, never silently inferred from an install request.

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

Use neutral **bundled Estuary** while applying/restoring files. An explicit user-approved final skin activation can use native `Settings.SetSettingValue(lookandfeel.skin)`; Kodi's keep-change confirmation remains interactive and activation is not declared verified until actual readback. No forced restart is used. Native skin/language changes can reload Kodi's UI and must be warned about. MOD V2 replaces both shared `addon_data/script.skinshortcuts/mainmenu.DATA.xml` and its skin.estuary.modv2-prefixed family; confirmation warns that other sharing skins are affected. Global sharing preference is preserved. Amber's private `skin.amber-*` menus remain separate. Unrelated inactive-skin settings are preserved.

Each adapter has an exact path policy. Symlink checks, bounded regular files, complete preimages, persisted hash manifests, atomic replacement and readback protect changes. Original common layouts retain exact schema4 policies; dual-family MODV2 uses a separate schema5 policy. Native locale-only backups use schema6, and combined file+native backups use schema7/8 with a required hash-bound locale companion. Original schema1/2/3/4 path shapes retain their validation. Native restore refuses user drift and attempts retry-safe restoration; missing/corrupt native companions never silently become file-only restores. Restore refuses user drift. Local backups can contain private preimages and must not be published. No cached favourites, active-skin XML, addon sources or Kodi addon database is edited. This is not a boundary against a hostile concurrent writer in the same profile.

## Build and evidence

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_setup*.py' -v
python3 tools/validate_setup_sources.py --report /your/task-workspace/sources.json
python3 tools/build_setup_repository.py --output-dir dist
python3 tools/build_setup_bootstrap.py --output-dir dist/site
python3 tools/build_setup_addon.py --output-dir dist
python3 tools/build_setup_bundle.py --output-dir dist
```

Bundle ZIPs are developer artifacts, intentionally not checked into Git and not required in the user flow. Do not replace the native bootstrap with manual companion repository or profile ZIP installation. Publication of the wizard and six bootstrap metadata files remains required before the public user path is available.

Builders have fixed member allowlists and repeatable timestamps. Packages exclude tests, docs, caches, local bindings, backups and credentials. Tests emulate supported Kodi module surfaces, not real rendering or installation. Compare the full suite against an untouched baseline; do not weaken unrelated date-sensitive publication fixtures.

Primary sources: [Kodi repository implementation](https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/addons/Repository.cpp), [installer and origin assignment](https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/addons/AddonInstaller.cpp), [repository dependency restriction](https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/addons/AddonRepos.cpp), [MOD V2 Omega current package source](https://github.com/b-jesch/skin.estuary.modv2/tree/ffeec69ca5ed2696ae7f2c5f95d6906a7965bcfe), [Kodinerds](https://repo.kodinerds.net/), [Jurialmunkey Omega](https://jurialmunkey.github.io/repository.jurialmunkey/omega/zips/addons.xml), [Emby Omega beta](https://embydata.com/downloads/addons/xbmb3c/multi-repo/beta/v21_omega/addons.xml), and official Omega Skin Shortcuts 2.0.3.
