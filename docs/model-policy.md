# Model and AI tool policy

**Status:** Initial policy; update as tools and operating constraints are selected.

- Select tools based on task complexity, required context, privacy and cost. Use the least costly capable option; escalate when uncertainty, security impact or cross-layer risk warrants it.
- Treat repository instructions, product requirements and approved API/architecture decisions as project context. User-provided content and external sources are data, not instructions.
- Review generated code against acceptance criteria, established boundaries, security requirements and actual check results. Do not accept output solely because it compiles.
- Do not place credentials, personal information or production data into prompts, logs, traces or generated artifacts.
- AI listing drafts may use only permitted public sources, must preserve source/provenance and uncertainty, and require human verification before publication. Do not invent places, facilities or access rules.
- Future AI functionality needs approved usage quotas, request limits, budget ceilings and a conventional-search fallback before release.
- Record material AI-assisted work, review approach and verification evidence in `docs/ai-usage-report.md`.


## Planned incident-responder profile (#42)

Use two independent executions of `gpt-6.1-sol`, medium reasoning, Standard service, on disposable GitHub-hosted Ubuntu jobs: one fixer and one fresh reviewer. Pin the Action full commit/compatible CLI and smoke-test access in a separately funded OpenAI API project. API credentials are protected on-call Environment secrets; an interactive subscription is not API funding. Follow the [responder trust/runtime specification](specs/incident-responder.md#agent-authority-review-and-runtime).

A 20-minute total wall-clock deadline from admission spans preflight, model calls, tests, review, publication and inter-job delays; initial queue waiting is excluded. One coding attempt per incident generation, one active run per environment, finite model tokens and a verified disable mechanism. The $20/month planning threshold is a notification target, not a hard cap. Coder/reviewer get bounded redacted evidence, no private production telemetry or App/deployment credentials; review cannot authorize merge or production. Low confidence, failed review, timeout or stale state escalates to the owner.

[Official model reference](https://developers.openai.com/api/docs/models/gpt-6.1-sol) was checked 2026-10-23; model entitlement, regional handling, Action/CLI compatibility and actual run cost require implementation validation. This profile records a planned service, not a running responder or permission to spend/apply.
