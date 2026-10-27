# Serph91P Kodi Setup Wizard

**0.4.3 for Kodi 21/Omega. Native fixture tests are not physical-device or playback acceptance.**

## One repository, four profiles

Install the wizard from `repository.serph91p` **1.0.3 or newer**. Its own feed and four repository-addon-only bootstrap feeds let the wizard request missing original repositories through Kodi's native installer: Jurialmunkey, Emby Beta, Kodinerds and AdamsBuilds. Confirm Kodi's prompts; do not manually install companion repository ZIPs. ZIPs and leaf catalogs remain on original hosts and keep their original IDs. Repository dependencies are not placed in `<requires>` because Kodi refuses that installation mechanism.

The public path requires a successful Pages publication of the paired repository, wizard and eight bootstrap metadata files. Local loopback metadata transport used in prepublication tests is not proof of public availability. `validate_setup_sources.py` verifies bounded original repository ZIP downloads, pinned SHA-256 and manifests; MD5 catalog tokens are change tokens, not signatures.

- **Arctic Fuse 3:** native Skin Variables hubs, widgets and submenus.
- **Amber:** private Skin Shortcuts menu, native shelves and submenus.
- **Rotary 0.0.1:** touch-first grid with six native home shortcuts. These open the same content lists; Rotary has no equivalent custom widgets or skin-native submenus. Its young version is disclosed before selection.
- **Nimbus Plus 0.2.07 / helper 0.0.98:** native menus, widgets, submenus and touch mode. The version-bound adapter stages the helper's own `cpath_cache.db` userdata contract, preserving unrelated rows, plus skin settings and a dedicated touch keymap. Explicit layout approval and backups are required. The original helper's narrow generators, not wizard-written skin XML, generate the skin-owned XML. Those generated files are not a file-backup policy; after restoring userdata, use the native helper to rebuild its output. Unknown helper versions or schemas stop writes. Nimbus keymap changes require the default Kodi profile; no cross-profile write is attempted.

Estuary MOD V2 is a retired new-setup choice. Existing installations/settings and legacy backups remain intact. Opening a saved retired profile offers an explicit new choice; cancelling does not migrate its layout or erase it.

Every profile requests Emby Next Gen, Twitch, YouTube, Gronkh.tv, TubeCast and IPTV Simple. TMDb Helper is shared for Series / Top Rated. Twitch 3.1.11, YouTube 7.4.4.1, TubeCast 1.6.1+omega.2 and Gronkh.tv 2.3.10 remain maintained Serph91P forks; older upstream packages must not replace them.

## Resume, origins and migration

The saved state contains only schema/profile, never credentials or trusted completion flags. Every opening rechecks live installation, enabled state, origin, indexed repository version, layout and native state. Correct existing add-ons are adopted, not reinstalled. Unreadable/ambiguous origins fail closed; a successfully read empty ZIP origin is a distinct, known unassigned state.

Known wrong-source, ZIP or older same-ID installs enter a user-mediated migration. The wizard checks that the target repository offers a version at least as new as the installed/minimum version, then opens **My add-ons → All**. Select the named add-on → **Versions** → the named repository/version, not the package cache. Reopen the wizard to verify enabled state, version and origin. Opening that UI is never recorded as success.

Use **Versions**, not the generic repository **Install** button: Omega's `CGUIDialogAddonInfo::OnInstall` can uninstall a foreign-origin add-on. `OnSelectVersion` updates in place. The wizard performs no silent uninstall, InstallAddon-on-existing, origin SQL write or pin removal. It does not change existing add-on account data. Add-on-owned migrations or expired sessions can still require login; there is no blanket guarantee for arbitrary add-on versions or tokens.

Global `addons.updatemode`, automatic-update intent `general.addonupdates`, and per-add-on `update_rules` are separate. None are silently weakened. Existing-only migration does not require changing repository policy. Native update dialogs and explicit user choices remain interactive. Catalog refresh requires indexed-version readback before leaf installation; a request/timeout is not success.

PVR provenance is platform-specific: Android/Windows use `repository.xbmc.org`; LibreELEC uses its own enabled `repository.libreelec.tv`. Generic distro Linux PVR packages remain OS-managed/unverified and stop full automatic setup without APT, PVR-file or database changes. Fixture success is not Android/PVR acceptance.

## Shared content and local accounts

All adapters use `navigation.py`:
- **Movies:** In-Progress Movies, New Movies, Top Rated Movies, Genres.
- **Series:** Fortsetzen, Neu, Top Rated, Genres.
- **Twitch:** Following Live Channels, Twitch VOD fortsetzen, Neue Twitch VODs, Latest uploads (Gronkh.tv).
- **YouTube:** Recommendations, My Subscriptions, Search.
- **Live TV:** Sender and Programm/EPG, usable after local PVR/channel configuration.

Presentation differs by skin. Missing Series/Twitch-VOD bindings stay null and show **Emby einrichten**, never an all-series fallback or copied server ID. Layout can be applied before login. After Emby login/sync, select separate target-local Series and Twitch-VOD libraries. Accounts, IPTV/EPG, API/OAuth and personal library choices remain local. The private login-transfer package is separate and never included here.

## Apply, native readiness and restore

Use neutral bundled **Estuary** for file apply/restore. Exact path policies, bounded regular files, symlink checks, complete preimages, hash-bound manifests, atomic replacement and readback protect changes. Existing local backups may contain private preimages: never publish them. Original backup schemas remain accepted; native locale companions cannot silently degrade to file-only restores. User drift blocks overwrite. This is not isolation from a hostile concurrent writer.

Skin activation is explicit through native `Settings.SetSettingValue(lookandfeel.skin)` and Kodi's Keep dialog. Setter acceptance alone does not prove activation. Native skin/language reloads are disclosed. The portable Arctic reference contains 275 typed style settings and 13 typed locale fields (English/Central Europe); only whitelisted native settings are journaled and changed, never active guisettings.xml, OS networking or accounts.

Amber uses its private `skin.amber-*` Skin Shortcuts data; legacy MOD V2 backups retain both shared and skin-prefixed families. The native compiler's labels/actions are checked, not just input DATA.xml. Rotary checks its live native shortcuts; Nimbus checks live settings and helper-generated menu output. Stale output requires approved native refresh. Skin XML save reordering is compared semantically; generated data and rollback hashes remain exact. Wizard code never directly writes installed skin XML or Kodi's add-on database. Nimbus's backed helper-userdata snapshot is a separate database, not a migration-origin edit.

## Build and verification

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 tools/validate_setup_sources.py --report /your/task-workspace/sources.json
python3 tools/build_setup_repository.py --output-dir dist
python3 tools/build_setup_bootstrap.py --output-dir dist/site
python3 tools/build_setup_addon.py --output-dir dist
```

Builders have fixed member allowlists and repeatable timestamps. Packages exclude tests, docs, caches, bindings, backups and credentials. Optional inert bundles from `tools/build_setup_bundle.py` are developer artifacts, not required user downloads or migration tools. Do not replace automatic bootstrap with manual companion ZIPs.

Public availability must be checked from real Pages URLs after publication. Physical touch, authenticated content and playback still require target-device acceptance; mocks and headless Kodi do not establish them. Existing LibreELEC is a read-only source and must not be changed.

Primary sources: Kodi Omega `GUIDialogAddonInfo.cpp`, `AddonInstaller.cpp`, `Repository.cpp`; [AdamsBuilds original repository](https://adamsbuilds.github.io/repo/), [original feeds and packages](https://raw.githubusercontent.com/adamsbuilds/repo/master/zips/addons.xml), [Jurialmunkey Omega](https://jurialmunkey.github.io/repository.jurialmunkey/omega/zips/addons.xml), [Emby beta](https://embydata.com/downloads/addons/xbmb3c/multi-repo/beta/v21_omega/addons.xml), [Kodinerds](https://repo.kodinerds.net/).
