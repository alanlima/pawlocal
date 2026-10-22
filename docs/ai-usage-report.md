# AI usage report

## Current work

- **Task (#214):** After owner review of a synthetic summary draft, the platform engineer added value-free reconciliation and cleanup job summaries. Tests cover full mapping/selection, verified variables versus accepted secrets, partial failures/retries, uncertain writes, escaping and setup/cancellation fallback. Existing permissions, approvals, locks and publication gates are unchanged; live verification is recorded separately in the issue/PR.

- **Task (#206, Terraform publication):** Platform engineer added state-owned generated Strings and exact-key permissions. Senior escalation resolved provider metadata authorization and boundary-size constraints; native tests enumerate the reviewed permission-pair delta.
- **Verification:** Independent source/plan review, live publication and integrated development/production releases passed; links are in the [configuration inventory](configuration-inventory.md).
- **Task (#206):** Integrate enforced reconciliation, same-run public build values, collision checks and exact cleanup/recovery. Terraform publication rolls out first through a separate reviewed PR so missing sources never require an enforce bypass.
- **Verification:** Both environments passed protected release and legacy cleanup. Tests cover missing/invalid sources, partial writes/reruns, secret exclusion and cleanup recovery. Real Vite/browser fixtures verify stale identity/scopes rejection and rebuilt OAuth redirects. Cognito replacement and destroy/reapply remain fixture evidence, separate from live acceptance.



- **Task (#205):** Implement the reviewed Parameter Store mapping, audit reconciler, protected dispatch/reusable workflow and scoped bootstrap reader identities. Platform specialists split script/workflow and IAM ownership, then integrated one PR for independent review.
- **Verification boundary:** Synthetic tests cover variable create/update/no-op/read-back, encrypted secret writes, access/API failures, partial retry, strict source/target rejection and absence of payloads in reports. IAM policy tests enforce exact read-only keys/OIDC trust. Live role apply and workflow evidence are recorded separately in the PR; no generated publication or required-value enforcement is claimed here.

- **Task (#204):** Establish the Parameter Store naming/mapping, source/destination inventory, authentication setup, audit/enforce, recovery and cleanup specification before #205/#206 implementation.
- **AI assistance:** Platform engineer inspected actual workflow/frontend/Terraform consumers and credential-name metadata; orchestration and independent review resolve permission and job-boundary details. No token values were retrieved or copied.
- **Verification boundary:** Documentation checks and independent review are recorded in the PR. This specification changes no workflow, mapping, Terraform resource or live configuration and makes no deployment/readiness claim.

- **Task:** Establish the documentation-first baseline for Issue #135 before Terraform or workflow implementation.
- **AI assistance:** Reconciled project instructions, architecture, decisions, implementation plan, testing guidance, and historical runbooks with the approved greenfield bootstrap/development/production ownership model. A separate planning reviewer identified evidence and isolation conflicts that were incorporated into the documentation.
- **Human review required:** The documentation records approved boundaries only. It does not define final Terraform paths, state keys, workflows, GitHub configuration, or operator commands, and it does not verify the partial teardown's live AWS/state result. The Issue #135 implementation and every apply/deployment gate still require review.
- **Verification:** Repository docs and current Terraform/workflow references were inspected; Issue #135, PRs #113/#88/#74/#134, and failed run 39480644777 were checked read-only. Documentation checks are recorded in the linked pull request. No Terraform, workflow, AWS, or GitHub Environment change was performed.

## Initial foundations

- **Task:** Review PawLocal agent instructions and establish Stage 0 project foundations.
- **AI assistance:** Used to draft the product specification, API outline, architecture, workflow guidance, staged plan and issue-ready acceptance criteria from the repository instructions.
- **Human review required:** Product/API/architecture documents are drafts. No GitHub repository was available through the connected GitHub integration, so issue proposals are documented locally and no remote issues, branch or PR were created.
- **Verification:** Repository contents and Git state were inspected; official AI Dev Tools Zoomcamp project requirements were consulted. No tests or application checks were run because this change establishes documentation and directory structure only.

