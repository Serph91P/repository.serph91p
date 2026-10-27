# YouTube fork and TubeCast distribution

The optional phone-to-profile feature is published through the existing
immutable Kodi repository pipeline:

- YouTube fork: `7.4.4.1`, [feature PR](https://github.com/Serph91P/plugin.video.youtube/pull/3).
- TubeCast: `1.6.1+omega.2`, [sender-routing PR](https://github.com/Serph91P/script.tubecast/pull/12).

The published executable/configuration files match the natively accepted
LibreELEC test builds. Release-only changes increase the versions, describe the
feature and retain the original distribution licenses. This is the tested
standard YouTube runtime, not the separately planned Unofficial-base migration.

## Source contracts

YouTube uses `Serph91P/plugin.video.youtube`, branch `master`, the existing
`Add-on Validations` workflow at `.github/workflows/addon-validations.yml`,
and Actions workflow ID `389194440`. Fork tests precede the SHA-pinned shared
packager. A skipped upstream-only job is not validation evidence. Its archive
allowlist is `addon.xml`, `changelog.txt`, `LICENSES/` and `resources/`.

TubeCast uses its existing immutable `develop` publication wiring. Its allowlist
is `addon.xml`, `LICENSE`, `main.py`, `script.py` and `resources/`. No second
updater or manual ZIP import is required.

The completed-run notifier retains the exact run, workflow, branch, package
hash, evidence, OIDC and artifact guards. Pull-request artifacts are test-only
and cannot dispatch public updates. Keep the existing `REPO_DISPATCH_TOKEN`
provisioned through the owner credential process; never put credentials in
source. The target's `SOURCE_ARTIFACT_TOKEN` must be able to read source artifacts.

## Bootstrap completed

The first approved YouTube publication was validated by source run
[39304849914](https://github.com/Serph91P/plugin.video.youtube/actions/runs/39304849914)
and deployed by target run
[39305121460](https://github.com/Serph91P/repository.serph91p/actions/runs/39305121460).
The public index and both downloaded packages were verified against source
artifact hashes.

The one-time `bootstrap_pending` registry exception is now removed. Every
configured source, including YouTube, is mandatory during later updates. A
missing or broken public YouTube package must fail closed rather than silently
drop the add-on. Tests prohibit bootstrap flags in the active registry.

## Future release order

1. Test and obtain approval for changed runtime and public publication.
2. Increase Kodi-sortable package versions before publishing changed bytes;
   never overwrite an existing `(add-on ID, version)` with different content.
3. Merge any target-policy changes first, then approved source changes on the
   configured publication branches. Successful source validation automatically
   notifies the target. A source `workflow_dispatch` on `master` is available for
   a controlled YouTube retry; the target itself has no manual-upload bypass.
4. Wait for source validation, notifier and target deployment to complete.
   Verify the actual Pages index/checksum and downloaded ZIP hashes against the
   evidence of the same source run. Keep Kodi installation/update-selection
   checks distinct from an HTTP download check.

No beta channel or test-ZIP publication is introduced by this integration.
