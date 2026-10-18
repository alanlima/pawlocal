# GitHub issue and pull request descriptions

The orchestrator checks the rendered description before creating or editing an issue or pull request. Use the repository templates as prompts, not mandatory boilerplate: remove sections that do not apply and replace every placeholder before publishing.

## Issue structure

Use these sections as applicable:

```markdown
## Context
Why this work is needed and any relevant current behavior or decision.

## Scope
- Concrete work included.
- Explicit exclusions or constraints, when useful.

## Acceptance criteria
- [ ] Observable, verifiable outcome.

## Evidence and links
Relevant files, decisions, issues, or supporting evidence, when available.

## Outstanding items
Known dependency or open question, if any.
```

Keep acceptance criteria testable and within the issue's approved scope. Apply at least one project-stage label and one work-type label as required by `AGENTS.md`. Omit evidence or outstanding-item sections when there is nothing useful to report.

## Pull request structure

```markdown
## Summary
What changed and why.

## Scope
How the change addresses the linked issue; call out material boundaries.

## Verification
- `command` — result.
- Link to CI, deployment, or other external evidence when relevant.

## Outstanding items
Known follow-up or risk, if any.

## Related issue
Closes #123
```

Report only checks that actually ran. State deployment or runtime status separately from implementation and CI status. Do not change the issue's acceptance criteria through PR wording; link a scope change to an explicit issue update. Omit inapplicable sections, and use `Closes #...` only when the PR is intended to complete that issue.

## Description review checklist

Before posting or editing, inspect the rendered Markdown (or GitHub preview) and confirm:

- Headings form a clear hierarchy; lists and checkboxes render correctly.
- Paragraphs are concise and useful details are not repeated.
- Placeholders are replaced and irrelevant sections are removed.
- Scope and acceptance criteria match the approved issue; implementation status is stated accurately.
- Each verification or completion claim has corresponding evidence, and unrun checks are not presented as passing.
- Dependencies, outstanding work, and links are current and clearly identified.

This review improves clarity and reporting accuracy; it does not add or weaken implementation acceptance requirements.

## Pull request merge method

Use GitHub's **Squash and merge** for every PR so each PR contributes one commit to `main`. Repository settings should allow squash merging and disable merge commits and rebase merging. Do not rewrite historical commits to apply this policy retroactively.
