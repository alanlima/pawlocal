from __future__ import annotations

import re
import unittest
from pathlib import Path


WORKFLOW_DIRECTORY = Path(".github/workflows")
REFERENCE = Path("docs/github-actions.md")
OPERATIONS_GUIDE = Path("docs/terraform-greenfield-operations.md")
REFERENCE_PATTERN = re.compile(
    r"<!-- actions-reference: (?P<workflow>[^;]+); "
    r"dispatch-inputs: (?P<dispatch>[^; ]+); call-inputs: (?P<call>[^ ]+) -->"
)
WORKFLOW_PROTECTED_CONFIGURATION_PATTERN = re.compile(
    r"(?P<context>vars|secrets)\.(?P<name>[A-Z][A-Z0-9_]+)\b"
)
DOCUMENTED_PROTECTED_CONFIGURATION_PATTERN = re.compile(
    r"<!-- actions-protected-configuration\n(?P<entries>.*?)\n-->", re.DOTALL
)


def workflow_files() -> list[Path]:
    return sorted(
        (*WORKFLOW_DIRECTORY.glob("*.yml"), *WORKFLOW_DIRECTORY.glob("*.yaml"))
    )


def workflow_event_inputs(source: str, event: str) -> tuple[str, ...]:
    """Return an event's input names in their declared order."""

    lines = source.splitlines()
    try:
        event_start = lines.index(f"  {event}:")
    except ValueError:
        return ()

    inputs: list[str] = []
    in_inputs = False
    for line in lines[event_start + 1 :]:
        if re.match(r"^  [A-Za-z0-9_-]+:", line):
            break
        if line == "    inputs:":
            in_inputs = True
            continue
        if not in_inputs:
            continue
        match = re.match(r"^      ([A-Za-z0-9_-]+):\s*$", line)
        if match:
            inputs.append(match.group(1))
        elif line and not line.startswith(("      ", "        ")):
            break
    return tuple(inputs)


def parse_input_names(raw_inputs: str) -> tuple[str, ...]:
    return () if raw_inputs == "-" else tuple(raw_inputs.split(","))


def documented_workflows(
    source: str,
) -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    result: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    for match in REFERENCE_PATTERN.finditer(source):
        workflow = match.group("workflow")
        if workflow in result:
            raise AssertionError(f"Duplicate actions-reference metadata for {workflow}")
        result[workflow] = (
            parse_input_names(match.group("dispatch")),
            parse_input_names(match.group("call")),
        )
    return result


def documented_protected_configuration(source: str) -> set[str]:
    match = DOCUMENTED_PROTECTED_CONFIGURATION_PATTERN.search(source)
    if not match:
        raise AssertionError("Missing actions-protected-configuration metadata")
    return {
        entry.strip()
        for entry in match.group("entries").splitlines()
        if entry.strip()
    }


class GitHubActionsReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reference = REFERENCE.read_text(encoding="utf-8")

    def test_reference_contains_mermaid_workflow_map(self) -> None:
        self.assertIn("```mermaid", self.reference)
        self.assertIn("## Workflow map", self.reference)

    def test_every_workflow_is_documented_exactly_once(self) -> None:
        actual = {path.name for path in workflow_files()}
        documented = set(documented_workflows(self.reference))
        self.assertEqual(
            actual,
            documented,
            "Update docs/github-actions.md when workflow files are added or removed.",
        )

    def test_manual_dispatch_inputs_match_reference(self) -> None:
        documented = documented_workflows(self.reference)
        actual = {
            path.name: workflow_event_inputs(
                path.read_text(encoding="utf-8-sig"), "workflow_dispatch"
            )
            for path in workflow_files()
        }
        expected = {name: inputs[0] for name, inputs in documented.items()}
        self.assertEqual(
            actual,
            expected,
            "Update the workflow input tables and actions-reference metadata together.",
        )

    def test_reusable_call_inputs_match_reference(self) -> None:
        documented = documented_workflows(self.reference)
        actual = {
            path.name: workflow_event_inputs(
                path.read_text(encoding="utf-8-sig"), "workflow_call"
            )
            for path in workflow_files()
        }
        expected = {name: inputs[1] for name, inputs in documented.items()}
        self.assertEqual(
            actual,
            expected,
            "Update reusable inputs and actions-reference metadata together.",
        )

    def test_reference_links_every_workflow_file(self) -> None:
        for path in workflow_files():
            with self.subTest(workflow=path.name):
                self.assertIn(
                    f"(../.github/workflows/{path.name})",
                    self.reference,
                )

    def test_protected_configuration_matches_reference_exactly(self) -> None:
        actual = {
            f'{match.group("context")}.{match.group("name")}'
            for path in workflow_files()
            for match in WORKFLOW_PROTECTED_CONFIGURATION_PATTERN.finditer(
                path.read_text(encoding="utf-8-sig")
            )
            if match.group("name") != "GITHUB_TOKEN"
        }
        documented = documented_protected_configuration(self.reference)
        self.assertEqual(
            actual,
            documented,
            "Update protected configuration metadata and prose together.",
        )
        for entry in sorted(documented):
            name = entry.split(".", 1)[1]
            with self.subTest(configuration=name):
                self.assertIn(f"`{name}`", self.reference)

    def test_reference_change_runs_workflow_validation(self) -> None:
        workflow = (WORKFLOW_DIRECTORY / "workflow-validation.yml").read_text(
            encoding="utf-8-sig"
        )
        self.assertEqual(workflow.count('      - "docs/github-actions.md"'), 2)
        self.assertEqual(
            workflow.count('      - "docs/terraform-greenfield-operations.md"'), 2
        )

    def test_release_and_converge_caveats_remain_explicit(self) -> None:
        operations_guide = OPERATIONS_GUIDE.read_text(encoding="utf-8")

        self.assertIn(
            "development Release therefore uses the current run's full commit SHA",
            self.reference,
        )
        self.assertIn(
            "Only production Converge and Release require a commit/image pair from "
            "a prior successful verified-development deployment.",
            self.reference,
        )
        documents = {
            REFERENCE: self.reference,
            OPERATIONS_GUIDE: operations_guide,
        }
        for document, source in documents.items():
            with self.subTest(document=document):
                self.assertIn("Converge and Release enforce required handoff inputs before planning", source)
                self.assertIn("Foundation audit", source)
                self.assertIn("publication", source)



if __name__ == "__main__":
    unittest.main()
