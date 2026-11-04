# Maintained Arctic Fuse 3

Source: Serph91P/skin.arctic.fuse.3, omega. Same add-on ID, original authors,
license and imports. Initial fork version 3.4.18.1. Validation workflow ID
406868734 (`Add-on Validations`, `.github/workflows/addon-validations.yml`).
Runtime allowlist is explicit and agrees with the source package workflow.
Notifier binds this source to omega, never the generic develop fallback.

This extends the existing immutable pipeline; PR artifacts cannot publish.
The one-time `bootstrap_pending` flag permits unrelated existing add-ons to
continue updating until the first real skin package has passed validation and
been published. It never adds an empty catalog row. After that first approved
publication, remove only that flag and tighten its test in the same task.

Approval/activation order: target policy merge, existing dispatch credential
provisioning for the new source (no new PAT), skin omega merge/validation and
notification, Pages deployment, public feed/ZIP/checksum verification. YouTube
Goto fix is its own versioned source change in plugin.video.youtube PR9.
Original leaf repositories/feeds and the setup wizard's separate original-skin
contract are unchanged; choose repository.serph91p as the maintained skin source.

The daily source workflow prepares tested merge candidates, never automatically
merges/publishes. No-change exits before builds. Kodi stays on its current skin
and Max triggers any reload. Roll back via the previous public package; never
replace bytes under a previously published version.
