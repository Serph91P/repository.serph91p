# Immutable publication notifier

`.github/workflows/reusable-notify-repository.yml` is the only supported
notification boundary for immutable add-on publication. Callers must pin the
reusable workflow to a full 40-character commit SHA. The notifier then verifies
the completed source run and its artifacts through the GitHub API before it can
send a repository dispatch.

## Caller contract

The reusable workflow requires these inputs:

| Input | Contract |
| --- | --- |
| `source_repository` | Exact source repository in `owner/name` form. It must equal the caller repository. |
| `candidate_sha` | Exact lowercase 40-character commit SHA validated by the source run. |
| `validation_run_id` | Positive numeric ID of the completed source validation run. |
| `validation_workflow` | Exact source validation workflow name. |
| `validation_workflow_path` | Exact source workflow path reported by GitHub, including its `@develop` suffix. |
| `validation_event` | Exact source event, restricted to `push` or `workflow_dispatch`. |
| `expected_branch` | Must be `develop`. |
| `addon_id` | Exact configured add-on ID. |
| `addon_version` | Exact configured add-on version. |
| `asset_name` | Exact deterministic package filename, `<addon_id>-<addon_version>.zip`. |
| `artifact_sha256` | Exact lowercase package SHA-256 from the packaging job. |
| `publication_id` | Exact publication identity, `<addon_id>@<addon_version>`. |

A source workflow can enforce the validation and packaging order as follows. The
workflow must run on a `push` or explicit `workflow_dispatch` for `develop`, and
`validation_workflow_path` must be fixed to the approved workflow path on the
develop branch. `workflow_dispatch` provides a bootstrap after the notifier has
first been deployed to the default branch.

```yaml
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - run: ./scripts/validate

  package:
    needs: validate
    permissions:
      contents: read
      id-token: write
    uses: Serph91P/repository.serph91p/.github/workflows/reusable-addon-package.yml@<40-char-sha>
    with:
      addon_id: plugin.video.example
      runtime_entries_json: '["addon.xml", "resources/"]'

  notify-repository:
    needs: [validate, package]
    if: ${{ needs.validate.result == 'success' && needs.package.result == 'success' }}
    permissions:
      actions: read
      contents: read
      id-token: write
    uses: Serph91P/repository.serph91p/.github/workflows/reusable-notify-repository.yml@<40-char-sha>
    with:
      source_repository: ${{ github.repository }}
      candidate_sha: ${{ github.sha }}
      validation_run_id: ${{ github.run_id }}
      validation_workflow: Source validation
      validation_workflow_path: .github/workflows/addon-validations.yml@develop
      validation_event: ${{ github.event_name }}
      expected_branch: develop
      addon_id: plugin.video.example
      addon_version: ${{ needs.package.outputs.addon_version }}
      asset_name: ${{ needs.package.outputs.asset_name }}
      artifact_sha256: ${{ needs.package.outputs.artifact_sha256 }}
      publication_id: ${{ needs.package.outputs.publication_id }}
    secrets:
      REPO_DISPATCH_TOKEN: ${{ secrets.REPOSITORY_DISPATCH_TOKEN }}
```

The workflow intentionally exposes no `workflow_call` outputs. Its only success
effect is a `validated-addon-publication` dispatch to
`Serph91P/repository.serph91p`. The dispatch `client_payload` contains only
`source_repo`, `candidate_sha`, `validation_run_id`, `validation_head_sha`,
`validation_workflow`, `validation_workflow_path`, and `expected_branch`.

`addon-workflow-templates/notify-repository.yml` is a source-side forwarding
workflow for projects that keep notification in a separate reusable file. It
is pinned to the trusted notifier by full commit SHA, derives source and run
identity from the GitHub context, fixes the workflow name, path, and branch,
and forwards only package outputs. It performs no direct dispatch.

Call the notifier only after a successful completed `push` or explicit
`workflow_dispatch` validation run for `develop`. The notifier independently
verifies that exact allowlisted event, branch, conclusion,
workflow name, workflow path, run ID, source repository, and head SHA. It
paginates all run artifacts, requires exactly one live `addon-package` artifact
and one live `validation-evidence` artifact, and requires both metadata records
to declare the producer's exact 30-day retention interval. It downloads both
wrappers with the
source-read token while stripping authorization on cross-origin redirects. The
package wrapper must contain exactly one regular, unencrypted file named by
`asset_name`; the notifier hashes those exact package bytes and requires the
configured SHA-256. It separately validates the single evidence JSON file,
rejecting duplicate JSON member names, before dispatching.

## Credentials and permissions

The caller must provide the required `REPO_DISPATCH_TOKEN` secret. Limit that
token to dispatching `Serph91P/repository.serph91p`.

Credential scopes are intentionally separated by step:

1. The tooling bootstrap uses GitHub OIDC only to read the trusted
   `job_workflow_ref` claim and resolve the exact reusable-workflow commit SHA.
2. The validation step receives only the caller `github.token` and uses it to
   read the exact validation run and its artifacts.
3. The dispatch step receives only `REPO_DISPATCH_TOKEN` and the validated,
   metadata-only client payload.

The reusable workflow grants `actions: read`, `contents: read`, and
`id-token: write`; the last permission exists only to obtain the trusted
reusable-workflow identity claim. Tokens, artifact download URLs, redirect URLs,
credentials, and signed URLs are never included in the dispatch payload or
printed by the notifier.

## Target-owned publication policy

The target repository (`repository.serph91p`) maintains authoritative
configuration for immutable publication. Each source has a per-source entry in
the target's `ADDONS` list. Dispatch-provided values identify the run and
candidate; they cannot redefine workflow identity, branch, artifact names,
add-on ID, or allowlist policy. The target enforces per-source:

- `publication_enabled` must be `True` for the source.
- `expected_branch` must match `publication_branch` from the source policy.
- `validation_workflow` must match the approved workflow name.
- `validation_workflow_path` must exactly match the approved workflow path on
  `develop`.
- `workflow_id` from the GitHub API run response must match the source's
  `validation_workflow_id`.
- Artifact names are fixed to `addon-package` and `validation-evidence`;
  sender-selected artifact names are rejected.
- Runtime allowlist entries are enforced against the source's
  `runtime_entries` tuple.
