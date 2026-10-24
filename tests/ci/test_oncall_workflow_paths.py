import fnmatch
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class OncallWorkflowPathTests(unittest.TestCase):
    def setUp(self):
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/fullstack-release.yml").read_text(
                encoding="utf-8"
            )
        )
        self.events = workflow.get("on", workflow.get(True))

    def selected(self, event, path):
        included = False
        for pattern in self.events[event]["paths"]:
            excluded = pattern.startswith("!")
            if fnmatch.fnmatchcase(path, pattern[1:] if excluded else pattern):
                included = not excluded
        return included

    def test_oncall_guides_run_required_pr_checks_without_deployment_push(self):
        for guide in ("docs/oncall-setup.md", "docs/oncall-troubleshooting.md"):
            with self.subTest(guide=guide):
                self.assertTrue(self.selected("pull_request", guide))
                self.assertFalse(self.selected("push", guide))

    def test_other_markdown_remains_outside_both_path_selections(self):
        for document in (
            "docs/testing.md",
            "frontend/README.md",
            "backend/README.md",
            "ops/incident-response/README.md",
            "docs/oncall-future.md",
            "docs/oncall-setup.mdx",
        ):
            for event in ("pull_request", "push"):
                with self.subTest(document=document, event=event):
                    self.assertFalse(self.selected(event, document))

    def test_existing_application_and_workflow_paths_remain_selected(self):
        for path in (
            "frontend/src/App.tsx",
            "backend/pawlocal/application/places.py",
            ".github/workflows/fullstack-release.yml",
        ):
            for event in ("pull_request", "push"):
                with self.subTest(path=path, event=event):
                    self.assertTrue(self.selected(event, path))


if __name__ == "__main__":
    unittest.main()
