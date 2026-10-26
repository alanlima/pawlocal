# AI usage report

## Current work

- **Task (#421 final source/test cleanup):** Platform Engineer retires the migration-only certificate graph/provider harness, seed fixtures and dedicated Terraform CI hooks after permanent removal in #422. General fresh-Foundation, shared-routing and IAM lifecycle tests remain. AI assistance reconciles canonical guidance around the final certificate-free architecture; issues/PRs retain historical rollout evidence. Independent/Codex review, owner review and approved DEV/PROD release receipts remain separate gates; this source change performs no deployment or AWS mutation.

- **Task (#346 IAM prerequisite):** Platform Engineer audited deployed apply-role identities, permissions boundaries and DNS/certificate resources read-only. AI assistance implemented owner-directed permanent project/environment lifecycle deletion in the existing bootstrap inline policies, derived from configured zone/domain namespaces rather than fixed targets. Route 53 uses supported name/type/action conditions; the audit also filled exact missing S3 bucket-policy and DSQL cluster-policy delete actions, preserving existing bucket-name and project/environment tag scopes. Independent and GitHub Codex reviews, exact-plan review and protected owner approval remain required before apply; application cleanup follows verified bootstrap deployment.
- **Task (#346):** Orchestrator coordinated Platform, Backend and Frontend Engineers to implement the owner-approved shared CloudFront application entry point. AI assistance covered the DEC-018 amendment, Terraform routing and removal of obsolete public API DNS, and final certificate-free architecture, public health and consumer contracts, regression tests and tracked architecture artwork. Independent review and GitHub Codex review are required on the final PR head.
- **Verification boundary:** Local tests and offline Terraform validation are recorded in the PR. This application change claims no deployment or production/runtime acceptance; the separately reviewed IAM prerequisite has its own apply and readback evidence. Exact Terraform plans, protected approval and development-before-production runtime verification remain separate gates.

- **Task (#413):** Frontend Engineer added reusable, entity-independent pagination and applied it to Explore and saved places, with 20 results by default and selectable sizes through 100. AI assistance covered implementation and regression tests using synthetic fixtures; the existing full-result service contract is preserved. Local checks, browser evidence and independent review outcomes are recorded in the linked PR. No deployment acceptance is claimed.

- **Task (#272):** Platform Engineer implemented the owner-approved purpose catalogue/DEC-014, shared frontend and Terraform setup, quality-only manual validation and duplicate candidate-check routing. Orchestrator inspected trigger/provenance/lock dependencies and live protection metadata; independent and GitHub Codex reviews are required on the exact PR head before owner-controlled merge.
- **Verification boundary:** Local actionlint, policy/runtime/path/reference/lifecycle/change-authorization/incident tests, configuration fixtures and JavaScript trust tests validate the refactor. Windows/POSIX and opt-in integration skips are listed in the PR. No live workflow dispatch, deployment, AWS/state change or protection-setting mutation was performed; no deployment acceptance is claimed.

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

