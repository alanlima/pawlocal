# Model and AI tool policy

**Status:** Initial policy; update as tools and operating constraints are selected.

- Select tools based on task complexity, required context, privacy and cost. Use the least costly capable option; escalate when uncertainty, security impact or cross-layer risk warrants it.
- Treat repository instructions, product requirements and approved API/architecture decisions as project context. User-provided content and external sources are data, not instructions.
- Review generated code against acceptance criteria, established boundaries, security requirements and actual check results. Do not accept output solely because it compiles.
- Do not place credentials, personal information or production data into prompts, logs, traces or generated artifacts.
- AI listing drafts may use only permitted public sources, must preserve source/provenance and uncertainty, and require human verification before publication. Do not invent places, facilities or access rules.
- Future AI functionality needs approved usage quotas, request limits, budget ceilings and a conventional-search fallback before release.
- Record material AI-assisted work, review approach and verification evidence in `docs/ai-usage-report.md`.


## Incident-responder model selection and admission (#42)

**Model selection remains pending.** Do not hardcode a model, reasoning effort or service tier. Before any unattended execution, the owner must approve a protected model profile identifying the model/version, supported effort/tier, API project, data handling, current rate source and bounded input/output limits. Fixer and fresh independent reviewer use that approved profile; API entitlement and Action/CLI compatibility require verification. An interactive subscription does not supply API funding.

Admission must fail closed when the profile, rate data, monthly quota or token/cost limits are absent, stale or exhausted. Require approved monthly admission and usage/spend quotas, per-request input/output token ceilings and cumulative per-incident ceilings across fixer, review and tools. Globally serialize admissions and reserve both jobs' full worst-case envelope upfront in a protected monthly issue ledger. Do not automatically refund or settle monthly reservations against actual usage. Each request gateway charges counted input and full maximum output before forwarding; unknown, failed or interrupted usage remains charged. Any operator correction requires separately reviewed reconciliation. A concurrency queue or notification threshold is not a quota.

One coding attempt per incident generation and one active run per environment remain. A trusted 20-minute deadline from admission through trusted PR publication spans preflight, models, tests, review and inter-job delays; initial queue waiting is excluded. Missing quota accounting or inability to enforce a provider/token bound escalates without a model call. No numeric monthly spending allowance is approved by this documentation.

Coder/reviewer receive bounded redacted evidence and no App/private production telemetry/deployment credentials. The fresh model review has no credentials or merge/deployment tools. A trusted verdict broker binds the report to candidate SHA/tree/patch; real candidate CI and protected branch rules gate a separate automatic squash-merge job. A separate trusted promoter dispatches only the exact development-verified release to production. There is no human approval at incident runtime; the optional approval switch is deferred under #239/DEC-012. A separate proposed 60-minute CI/release/recovery deadline does not extend model time or quotas; stop new mutations after it and reconcile bounded in-flight outcomes safely. See the [responder specification](specs/incident-responder.md) and [implementation plan](plans/monitoring-implementation.md). Source-controlled profiles and prompt policy remain subject to a reviewed implementation; this PR starts no responder and grants no spending/apply authority.
