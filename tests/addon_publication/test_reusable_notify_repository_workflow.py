import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
NOTIFIER_TEMPLATE = ROOT / "addon-workflow-templates" / "notify-repository.yml"
NOTIFIER_DOC = ROOT / "addon-publication" / "NOTIFIER.md"
FULL_SHA_ACTION = re.compile(r"^[^\s@]+@[0-9a-f]{40}$")


class ReusableNotifierWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / ".github" / "workflows" / "reusable-notify-repository.yml").read_text(encoding="utf-8")
        cls.workflow = yaml.load(cls.text, Loader=yaml.BaseLoader)

    def test_yaml_parses_and_only_workflow_call_triggers(self):
        self.assertEqual(list(self.workflow["on"]), ["workflow_call"])

    def test_interface_requires_exact_identity_inputs_and_dispatch_secret(self):
        call = self.workflow["on"]["workflow_call"]
        self.assertEqual(
            set(call["inputs"]),
            {
                "source_repository",
                "candidate_sha",
                "validation_run_id",
                "validation_workflow",
                "validation_workflow_path",
                "expected_branch",
                "addon_id",
                "addon_version",
                "asset_name",
                "artifact_sha256",
                "publication_id",
            },
        )
        for spec in call["inputs"].values():
            self.assertEqual(spec["required"], "true")
            self.assertTrue(spec["description"].strip())
        self.assertEqual(call["inputs"]["validation_run_id"]["type"], "number")
        self.assertEqual(set(call["secrets"]), {"REPO_DISPATCH_TOKEN"})
        self.assertEqual(call["secrets"]["REPO_DISPATCH_TOKEN"]["required"], "true")

    def test_permissions_timeout_and_actions_are_strict(self):
        self.assertEqual(
            self.workflow["permissions"],
            {"actions": "read", "contents": "read", "id-token": "write"},
        )
        job = self.workflow["jobs"]["notify"]
        self.assertEqual(job["timeout-minutes"], "15")
        uses = [step["uses"] for step in job["steps"] if "uses" in step]
        self.assertTrue(uses)
        self.assertTrue(all(FULL_SHA_ACTION.fullmatch(value) for value in uses), uses)
        checkout = next(
            step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@")
        )
        self.assertEqual(checkout["with"]["repository"], "Serph91P/repository.serph91p")
        self.assertIn("steps.tooling-ref.outputs.sha", checkout["with"]["ref"])
        self.assertEqual(checkout["with"]["persist-credentials"], "false")

    def test_tooling_ref_uses_oidc_job_workflow_ref_and_requires_full_sha(self):
        step = next(
            step for step in self.workflow["jobs"]["notify"]["steps"] if step.get("id") == "tooling-ref"
        )
        self.assertNotIn("env", step)
        self.assertIn("ACTIONS_ID_TOKEN_REQUEST_URL", step["run"])
        self.assertIn("ACTIONS_ID_TOKEN_REQUEST_TOKEN", step["run"])
        self.assertIn('claims.get("job_workflow_ref")', step["run"])
        self.assertIn('r"[0-9a-f]{40}"', step["run"])
        self.assertIn(
            '"Serph91P/repository.serph91p/.github/workflows/"', step["run"]
        )
        self.assertIn('"reusable-notify-repository.yml@"', step["run"])
        self.assertNotIn("github.workflow_ref", step["run"])
        self.assertNotIn("job.workflow_ref", step["run"])

    def test_tokens_are_step_separated_and_dispatch_schema_is_exact(self):
        steps = self.workflow["jobs"]["notify"]["steps"]
        validation = next(step for step in steps if step.get("id") == "validate")
        dispatch = next(step for step in steps if step.get("id") == "dispatch")
        self.assertEqual(validation["env"]["GITHUB_TOKEN"], "${{ github.token }}")
        self.assertNotIn("REPO_DISPATCH_TOKEN", validation.get("env", {}))
        self.assertEqual(
            dispatch["env"]["REPO_DISPATCH_TOKEN"],
            "${{ secrets.REPO_DISPATCH_TOKEN }}",
        )
        self.assertNotIn("GITHUB_TOKEN", dispatch.get("env", {}))
        self.assertEqual(
            dispatch["env"]["CLIENT_PAYLOAD"],
            "${{ steps.validate.outputs.client_payload }}",
        )
        before_dispatch = "\n".join(
            str(step) for step in steps if step.get("id") != "dispatch"
        )
        self.assertNotIn("secrets.REPO_DISPATCH_TOKEN", before_dispatch)
        self.assertIn("validated-addon-publication", dispatch["run"])
        self.assertIn("Serph91P/repository.serph91p", dispatch["run"])

    def test_workflow_does_not_log_or_dispatch_sensitive_material(self):
        dispatch = next(
            step
            for step in self.workflow["jobs"]["notify"]["steps"]
            if step.get("id") == "dispatch"
        )
        payload_source = dispatch["env"]["CLIENT_PAYLOAD"].lower()
        self.assertNotIn("artifact_sha256", payload_source)
        self.assertNotIn("asset_name", payload_source)
        for forbidden_log in (
            "set -x",
            "printenv",
            "echo $repo_dispatch_token",
            "echo ${repo_dispatch_token}",
            "archive_download_url",
            "signed_url",
        ):
            self.assertNotIn(forbidden_log, self.text.lower())

    def test_caller_example_runs_only_after_validation_and_passes_exact_contract(self):
        documentation = NOTIFIER_DOC.read_text(encoding="utf-8")
        examples = re.findall(r"```yaml\n(.*?)```", documentation, re.DOTALL)
        self.assertEqual(len(examples), 1)
        example = yaml.load(examples[0], Loader=yaml.BaseLoader)
        job = example["jobs"]["notify-repository"]
        self.assertEqual(job["needs"], ["validate", "package"])
        self.assertIn("needs.validate.result == \'success\'", job["if"])
        self.assertIn("needs.package.result == \'success\'", job["if"])
        self.assertEqual(
            set(job["with"]),
            {
                "source_repository",
                "candidate_sha",
                "validation_run_id",
                "validation_workflow",
                "validation_workflow_path",
                "expected_branch",
                "addon_id",
                "addon_version",
                "asset_name",
                "artifact_sha256",
                "publication_id",
            },
        )
        self.assertEqual(set(job["secrets"]), {"REPO_DISPATCH_TOKEN"})


class NotifyRepositoryWorkflowPayloadTests(unittest.TestCase):
    def test_validation_workflow_path_in_client_payload(self):
        with NOTIFIER_TEMPLATE.open(encoding="utf-8") as f:
            text = f.read()
        self.assertIn('validation_workflow_path": "${{ github.event.workflow_run.path }}@develop"', text)

    def test_dispatch_payload_passes_validator(self):
        representative = {
            "source_repo": "Serph91P/plugin.video.example",
            "candidate_sha": "25b5920a9204acedf3d05dc009d78918d2bf0648",
            "validation_run_id": 29549561132,
            "validation_head_sha": "25b5920a9204acedf3d05dc009d78918d2bf0648",
            "validation_workflow": "Add-on Validations",
            "validation_workflow_path": ".github/workflows/addon-validations.yml@develop",
            "expected_branch": "develop",
        }
        self.assertEqual(list(representative.keys()), [
            "source_repo", "candidate_sha", "validation_run_id",
            "validation_head_sha", "validation_workflow", "validation_workflow_path", "expected_branch"
        ])
        from scripts import build_repository as builder
        builder.validate_dispatch_payload(representative)

    def test_validation_workflow_path_main_tag_raises_error(self):
        invalid = {
            "source_repo": "Serph91P/plugin.video.example",
            "candidate_sha": "25b5920a9204acedf3d05dc009d78918d2bf0648",
            "validation_run_id": 29549561132,
            "validation_head_sha": "25b5920a9204acedf3d05dc009d78918d2bf0648",
            "validation_workflow": "Add-on Validations",
            "validation_workflow_path": ".github/workflows/addon-validations.yml@main",
            "expected_branch": "develop",
        }
        with self.assertRaises(RuntimeError):
            from scripts import build_repository as builder
            builder.validate_dispatch_payload(invalid)

    def test_validation_workflow_path_no_suffix_raises_error(self):
        invalid = {
            "source_repo": "Serph91P/plugin.video.example",
            "candidate_sha": "25b5920a9204acedf3d05dc009d78918d2bf0648",
            "validation_run_id": 29549561132,
            "validation_head_sha": "25b5920a9204acedf3d05dc009d78918d2bf0648",
            "validation_workflow": "Add-on Validations",
            "validation_workflow_path": "simple/path",
            "expected_branch": "develop",
        }
        with self.assertRaises(RuntimeError):
            from scripts import build_repository as builder
            builder.validate_dispatch_payload(invalid)


if __name__ == "__main__":
    unittest.main()
