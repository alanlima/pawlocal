from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class RetiredCombinedStateWorkflowTests(unittest.TestCase):
    def test_legacy_combined_state_workflow_is_inert(self) -> None:
        source = (ROOT / ".github/workflows/terraform-current-stack-operations.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch", source)
        self.assertIn("permanently disabled", source)
        self.assertNotIn("terraform init", source)
        self.assertNotIn("terraform plan", source)
        self.assertNotIn("terraform apply", source)
        self.assertNotIn("pawlocal/terraform.tfstate", source)

    def test_legacy_rollback_workflow_is_inert(self) -> None:
        source = (ROOT / ".github/workflows/rollback-development.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch", source)
        self.assertIn("retired", source)
        self.assertIn("run: |\n          echo 'The combined-state rollback path", source)
        self.assertNotIn("run: echo", source)
        self.assertNotIn("terraform", source.lower().split("echo", 1)[0])
        self.assertNotIn("run-deployment-adapter.sh", source)


if __name__ == "__main__":
    unittest.main()
