# YouTube fork and TubeCast distribution

This wires the paired-profile feature into the existing immutable publication
pipeline. It does not create a beta repository, publish test ZIPs, install an
add-on, or change the public repository by itself.

Companion changes:
- [YouTube fork feature](https://github.com/Serph91P/plugin.video.youtube/pull/3)
- [TubeCast sender routing](https://github.com/Serph91P/script.tubecast/pull/12)

## Source contract

YouTube uses `Serph91P/plugin.video.youtube`, branch `master`, the existing
`Add-on Validations` workflow at `.github/workflows/addon-validations.yml`,
and Actions workflow ID `389194440` (read from the GitHub API, not inferred).
The fork-only jobs run profile tests and then call the SHA-pinned shared packager.
The existing upstream-only job remains unchanged. Pull-request runs build test
artifacts but are never eligible for public dispatch.

The package allowlist is `addon.xml`, `changelog.txt`, `LICENSES/` and `resources/`.
The original GPL license and changelog must accompany the distribution. All
Python entrypoints and the TubeCast capability manifest are under `resources/`. The completed-run
notifier uses a full-SHA pin and the target-owned `master` exception. It retains
the exact run, workflow, branch, package hash, evidence, OIDC and artifact guards.
A skipped legacy upstream validation is not publication evidence.

TubeCast already has the corresponding immutable `develop` publication wiring;
no second TubeCast updater or manual ZIP import is needed.

## One-time bootstrap

YouTube is not yet in the public `addons.xml`. Its target-owned registry entry
therefore has `bootstrap_pending: True`. Only that explicitly marked source may
be absent while another add-on updates. Existing configured sources stay
mandatory. If YouTube is already advertised, its current package must still be
downloaded and validated; the flag never permits dropping an advertised package
or accepting missing/broken package bytes. The first valid YouTube candidate is
published directly from its own validated package/evidence pair.

Immediately after the first approved public YouTube publication, remove the
`bootstrap_pending` entry and its matching temporary registry-test assertion in
a follow-up change. All future missing YouTube manifest entries must then fail
closed like the existing add-ons. Do not leave the bootstrap exception enabled
as a permanent optional-add-on policy.

## Activation gates and order

1. Complete the native LibreELEC test of the two test packages: two phones,
   separately signed-in profiles, Kodi's selected profile deliberately different,
   correct remote histories, stop/next/reconnect and cancellation/error cases.
   Unit tests and package CI do not establish that result.
2. Obtain approval for merge **and public Pages publication**. Merging the
   source workflow onto its publication branch will automatically publish after
   successful validation if its dispatch secret is configured.
3. Assign a new Kodi-sortable TubeCast version before publishing its changed
   bytes: `1.6.1+omega.1` is already public and cannot be overwritten. YouTube's
   initial `7.4.4` identity is not in this repository yet, but an installation
   already on `7.4.4` will not automatically upgrade to the same version; either
   explicitly select this repository's package for the initial installation or
   approve a higher fork version before publishing. Never relabel a previously
   published package with different bytes.
4. Provision YouTube's existing `REPO_DISPATCH_TOKEN` secret through the owner
   credential process. The fork currently has no repository secrets. Do not
   create new tokens or copy credentials into code. Confirm the target's
   `SOURCE_ARTIFACT_TOKEN` can read the YouTube workflow artifacts.
5. Merge the target policy first. Its temporary bootstrap state lets other
   add-ons continue updating. Then merge/validate the YouTube source workflow
   and feature on `master`, publish YouTube, and publish the bumped TubeCast
   feature on `develop`. A manual source `workflow_dispatch` is available for
   a controlled retry once the source workflow is on its default branch.
6. Verify the actual Pages manifest/checksum, both downloaded ZIPs, Kodi update
   selection and native profile routing. Remove the bootstrap exception as above.

Until these gates are met, keep the changes as draft PRs and use only the
explicitly supplied test ZIPs for the requested device test.
