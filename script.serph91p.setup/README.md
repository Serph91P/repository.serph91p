# Serph91P Kodi Setup Wizard

**0.3.0 development candidate for Kodi 21/Omega. Not released or device-approved.**

## One repository, three profiles

The paired `repository.serph91p` **1.0.1** candidate exposes Serph91P, Jurialmunkey Omega, Emby Next Gen **beta for Kodi 21**, and Kodinerds Omega/Matrix catalogs using Kodi's native multi-directory repository mechanism. No third-party repository ZIP search, manual extraction into addon directories, database edits or imaginary installation APIs.

For this unpublished candidate, install/update **one Serph91P repository ZIP first**, then install the wizard ZIP. After publication, Kodi should install the wizard from that repository; publication integration and fresh-device acceptance remain separate gates. The wizard is not yet in the live catalog. Its declared repository 1.0.1 dependency cannot be satisfied by the old repository ZIP.

Extra catalogs apply only to Kodi 21. Kodi records their packages as originating from `repository.serph91p`. Catalogs/packages remain upstream-hosted, not copied, signed or immutable mirrors. MD5 catalog change tokens are not signatures or package SHA-256 pins. `validate_setup_sources.py` checks live checksum consistency and rejects ambiguous equal-version IDs across the five federated catalogs. Normal official Kodi catalogs provide YouTube, Amber, official resources and platform-specific IPTV binaries.

Profiles:
- **Arctic Fuse 3:** native Skin Variables hubs, widgets and submenus.
- **Amber:** private Skin Shortcuts main menu and content submenus. Same media structure, not an Arctic-style widget clone.
- **Touch: Estuary MOD V2:** customizable main menu, native personal-widget lists and matching submenus; its own touchmode flag is enabled while inactive. Replaces the old bundled Estuary-touch choice. Legacy touch backups remain restorable.

Every profile requests Emby Next Gen, Twitch, YouTube, Gronkh.tv, TubeCast, IPTV Simple and TMDb Helper. Skin requirements stay profile-scoped. Kodi resolves transitive dependencies and platform binaries. The progress bar counts verified addons, not download bytes, shows the current addon/wait status and closes on success, failure or exception. Native Kodi confirmations stay interactive. An installation request or a timeout is never reported as success. Native repository refresh is requested, not falsely claimed complete.

## Shared LibreELEC-reference structure

All adapters consume one semantic model (`navigation.py`), in this order:
- **Movies:** In-Progress Movies, New Movies, Top Rated Movies, Genres.
- **Series:** Fortsetzen, Neu, Top Rated, Genres.
- **Twitch:** Following Live Channels, Twitch VOD fortsetzen, Neue Twitch VODs, Latest uploads (Gronkh.tv).
- **YouTube:** Recommendations, My Subscriptions, Search.
- **Live TV:** Sender and Programm/EPG, visible after the local PVR configuration has channels. Arctic keeps its native PVR slot; the other skins expose equivalent native destinations. IPTV sources are not copied.

Labels, order and destinations are shared; presentation is skin-specific. Utility controls can differ. Content actions also work via fixed program-entrypoint arguments. No credentials, authenticated reference-device paths or raw userdata backups are distributed.

**Log into Emby and sync on the target before applying the layout.** The wizard discovers that device's local Emby node files and asks which library is Series and which is Twitch VODs. Resume/new/genres destinations use those local nodes, never copied server IDs or an undifferentiated all-series fallback. If suitable nodes are unavailable, layout application stops with an explanation. Accounts, IPTV/EPG, YouTube API/OAuth and library choices stay local. Installation does not prove playback, login or sync success.

## Apply and restore

Use neutral **bundled Estuary** while applying/restoring files, then manually select the final skin. No automatic switch, reload or restart. MOD V2 replaces shared `addon_data/script.skinshortcuts/mainmenu.DATA.xml`; confirmation warns that other skins sharing it also see it. Amber's private `skin.amber-*` menus remain separate. Unrelated inactive-skin settings are preserved.

Each adapter has an exact path policy. Symlink checks, bounded regular files, complete preimages, persisted hash manifests, atomic replacement and readback protect changes. Common layouts use schema 4; legacy schema 1/2/3 backups keep their original validation. Restore refuses user drift. Local backups can contain private preimages and must not be published. No cached favourites, active-skin XML, addon sources or Kodi addon database is edited. This is not a boundary against a hostile concurrent writer in the same profile.

## Build and evidence

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_setup*.py' -v
python3 tools/validate_setup_sources.py --report /your/task-workspace/sources.json
python3 tools/build_setup_repository.py --output-dir dist
python3 tools/build_setup_addon.py --output-dir dist
```

Builders have fixed member allowlists and repeatable timestamps. Packages exclude tests, docs, caches, local bindings, backups and credentials. Tests emulate supported Kodi module surfaces, not real rendering or installation. Compare the full suite against an untouched baseline; do not weaken unrelated date-sensitive publication fixtures.

Primary sources: [Kodi repository implementation](https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/addons/Repository.cpp), [installer builtins](https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/interfaces/builtins/AddonBuiltins.cpp), [MOD V2 package-version source](https://github.com/b-jesch/skin.estuary.modv2/tree/cc5401c952e15d23509d0dbaf34a704474052e53), [Kodinerds](https://repo.kodinerds.net/), [Jurialmunkey Omega](https://jurialmunkey.github.io/repository.jurialmunkey/omega/zips/addons.xml), [Emby Omega beta](https://embydata.com/downloads/addons/xbmb3c/multi-repo/beta/v21_omega/addons.xml), and official Omega Skin Shortcuts 2.0.3.
