import re
import unittest
import urllib.request
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
                "validation_event",
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
        self.assertNotIn(
            "@develop",
            call["inputs"]["validation_workflow_path"]["description"],
        )
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
        self.assertIn('"publication_id"', dispatch["run"])

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
            job["permissions"],
            {"actions": "read", "contents": "read", "id-token": "write"},
        )
        self.assertEqual(
            set(job["with"]),
            {
                "source_repository",
                "candidate_sha",
                "validation_run_id",
                "validation_workflow",
                "validation_workflow_path",
                "validation_event",
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
    @classmethod
    def setUpClass(cls):
        cls.text = NOTIFIER_TEMPLATE.read_text(encoding="utf-8")
        cls.workflow = yaml.load(cls.text, Loader=yaml.BaseLoader)

    def test_template_is_only_a_pinned_reusable_workflow_caller(self):
        self.assertEqual(list(self.workflow["on"]), ["workflow_call"])
        job = self.workflow["jobs"]["notify-repository"]
        self.assertNotIn("runs-on", job)
        self.assertNotIn("steps", job)
        self.assertTrue(FULL_SHA_ACTION.fullmatch(job["uses"]), job["uses"])
        self.assertTrue(
            job["uses"].startswith(
                "Serph91P/repository.serph91p/.github/workflows/"
                "reusable-notify-repository.yml@"
            )
        )
        self.assertNotIn("repository-dispatch", self.text)
        self.assertNotRegex(self.text, r"uses:\s+[^\s]+@v\d+")

    def test_template_inputs_match_exact_pinned_reusable_workflow(self):
        job = self.workflow["jobs"]["notify-repository"]
        pin = job["uses"].rsplit("@", 1)[1]
        url = (
            "https://raw.githubusercontent.com/Serph91P/repository.serph91p/"
            f"{pin}/.github/workflows/reusable-notify-repository.yml"
        )
        with urllib.request.urlopen(url, timeout=30) as response:
            pinned = yaml.load(response.read(), Loader=yaml.BaseLoader)
        declared = set(pinned["on"]["workflow_call"]["inputs"])
        self.assertLessEqual(set(job["with"]), declared)

    def test_template_permissions_preserve_caller_oidc(self):
        job = self.workflow["jobs"]["notify-repository"]
        self.assertEqual(
            job["permissions"],
            {"actions": "read", "contents": "read", "id-token": "write"},
        )

    def test_template_forwards_context_and_fixed_identity(self):
        call = self.workflow["on"]["workflow_call"]
        self.assertEqual(
            set(call["inputs"]),
            {
                "addon_id",
                "addon_version",
                "asset_name",
                "artifact_sha256",
                "publication_id",
            },
        )
        job = self.workflow["jobs"]["notify-repository"]
        self.assertEqual(job["with"]["source_repository"], "${{ github.repository }}")
        self.assertEqual(job["with"]["candidate_sha"], "${{ github.sha }}")
        self.assertEqual(job["with"]["validation_run_id"], "${{ github.run_id }}")
        self.assertEqual(job["with"]["validation_workflow"], "Add-on Validations")
        self.assertEqual(job["with"]["validation_event"], "${{ github.event_name }}")
        self.assertEqual(
            job["with"]["validation_workflow_path"],
            ".github/workflows/addon-validations.yml",
        )
        self.assertEqual(job["with"]["expected_branch"], "develop")
        self.assertNotIn("github.event.workflow_run.path", self.text)
        self.assertEqual(
            job["secrets"],
            {"REPO_DISPATCH_TOKEN": "${{ secrets.REPO_DISPATCH_TOKEN }}"},
        )


if __name__ == "__main__":
    unittest.main()
