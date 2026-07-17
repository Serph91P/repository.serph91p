import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "reusable-addon-package.yml"
FULL_SHA_ACTION = re.compile(r"^[^\s@]+@[0-9a-f]{40}$")


class ReusableWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.workflow = yaml.load(cls.text, Loader=yaml.BaseLoader)

    def test_yaml_parses_and_only_workflow_call_triggers(self):
        self.assertEqual(list(self.workflow["on"]), ["workflow_call"])

    def test_interface_documents_inputs_and_outputs(self):
        call = self.workflow["on"]["workflow_call"]
        self.assertEqual(set(call["inputs"]), {"addon_id", "runtime_entries_json"})
        for spec in call["inputs"].values():
            self.assertEqual(spec["required"], "true")
            self.assertTrue(spec["description"].strip())
        self.assertEqual(
            set(call["outputs"]),
            {"addon_version", "asset_name", "artifact_sha256", "publication_id"},
        )
        for spec in call["outputs"].values():
            self.assertTrue(spec["description"].strip())
            self.assertTrue(spec["value"].strip())

    def test_permissions_timeout_and_exact_sha_checkouts(self):
        self.assertEqual(
            self.workflow["permissions"],
            {"contents": "read", "id-token": "write"},
        )
        job = self.workflow["jobs"]["package"]
        self.assertEqual(job["timeout-minutes"], "20")
        steps = job["steps"]
        uses = [step["uses"] for step in steps if "uses" in step]
        self.assertTrue(uses)
        self.assertTrue(all(FULL_SHA_ACTION.fullmatch(value) for value in uses), uses)
        checkouts = [
            step
            for step in steps
            if step.get("uses", "").startswith("actions/checkout@")
        ]
        self.assertEqual(len(checkouts), 2)
        self.assertEqual(checkouts[0]["with"]["ref"], "${{ github.sha }}")
        self.assertEqual(checkouts[0]["with"]["path"], "source")
        self.assertEqual(
            checkouts[1]["with"]["repository"], "Serph91P/repository.serph91p"
        )
        self.assertIn("steps.tooling-ref.outputs.sha", checkouts[1]["with"]["ref"])

    def test_exactly_two_single_file_artifacts_have_30_day_retention(self):
        steps = self.workflow["jobs"]["package"]["steps"]
        uploads = [
            step
            for step in steps
            if step.get("uses", "").startswith("actions/upload-artifact@")
        ]
        self.assertEqual(len(uploads), 2)
        self.assertEqual(
            [step["with"]["name"] for step in uploads],
            ["addon-package", "validation-evidence"],
        )
        self.assertEqual(
            [step["with"]["retention-days"] for step in uploads], ["30", "30"]
        )
        self.assertEqual(
            [step["with"]["if-no-files-found"] for step in uploads], ["error", "error"]
        )
        self.assertTrue(all("*" not in step["with"]["path"] for step in uploads))
        self.assertEqual(
            uploads[0]["with"]["path"],
            "artifacts/addon-package/${{ steps.build.outputs.asset_name }}",
        )
        self.assertEqual(
            uploads[1]["with"]["path"],
            "artifacts/validation-evidence/validation-evidence.json",
        )

    def test_package_is_extracted_before_kodi_checker(self):
        steps = self.workflow["jobs"]["package"]["steps"]
        commands = "\n".join(step.get("run", "") for step in steps)
        self.assertIn("extract", commands.lower())
        self.assertIn("kodi-addon-checker", commands)
        checker_line = next(
            line
            for line in commands.splitlines()
            if "kodi-addon-checker" in line and not line.lstrip().startswith("#")
        )
        self.assertIn("extracted", checker_line)
        self.assertNotIn(" source", checker_line)

    def test_checker_dependencies_are_fully_pinned_before_the_exact_source_install(self):
        steps = self.workflow["jobs"]["package"]["steps"]
        commands = "\n".join(step.get("run", "") for step in steps)
        self.assertIn("addon-check-requirements.txt", commands)
        self.assertIn("--no-deps", commands)
        requirements = (
            ROOT / "addon-publication" / "addon-check-requirements.txt"
        ).read_text(encoding="utf-8")
        entries = [line for line in requirements.splitlines() if line]
        self.assertEqual(
            entries,
            [
                "certifi==2026.6.17",
                "charset-normalizer==3.4.9",
                "colorama==0.4.6",
                "elementpath==5.1.3",
                "idna==3.18",
                "mando==0.7.1",
                "packaging==26.2",
                "pillow==12.3.0",
                "polib==1.2.0",
                "radon==6.0.1",
                "requests==2.34.2",
                "setuptools==83.0.0",
                "six==1.17.0",
                "urllib3==2.7.0",
                "xmlschema==4.3.2",
            ],
        )

    def test_tooling_ref_must_be_full_sha(self):
        steps = self.workflow["jobs"]["package"]["steps"]
        ref_step = next(step for step in steps if step.get("id") == "tooling-ref")
        self.assertNotIn("env", ref_step)
        self.assertIn("ACTIONS_ID_TOKEN_REQUEST_URL", ref_step["run"])
        self.assertIn("ACTIONS_ID_TOKEN_REQUEST_TOKEN", ref_step["run"])
        self.assertIn('claims.get("job_workflow_ref")', ref_step["run"])
        self.assertIn('r"[0-9a-f]{40}"', ref_step["run"])
        self.assertIn(
            "Serph91P/repository.serph91p/.github/workflows/reusable-addon-package.yml@",
            ref_step["run"],
        )
        self.assertNotIn("github.workflow_ref", self.text)
        self.assertNotIn("job.workflow_ref", self.text)


if __name__ == "__main__":
    unittest.main()
