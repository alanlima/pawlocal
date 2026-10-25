# Project 1 delivery plan

Owner: alanlima. Tracking: [#281 delivery readiness](https://github.com/alanlima/pawlocal/issues/281), [#284 README/evidence](https://github.com/alanlima/pawlocal/issues/284), [#283 peer reviews](https://github.com/alanlima/pawlocal/issues/283). Last evidence review: 25 October 2026. **Preparation in progress; no platform submission or receipt recorded.**

## Problem, goal and reviewer entry point

Dog owners lack a single reliable source for dog-friendly places and verified access/facility information across South East Queensland. PawLocal provides searchable public discovery and place sharing, with authenticated favourites and community contributions. Unknown facts remain unknown; AI-generated drafts require human approval. The [README](../README.md#problem-and-goal) is the public project description and reviewer entry point; [product-spec.md](../product-spec.md) owns the detailed acceptance criteria.

Start with the [public application](https://pawlocal.alanlima.cloud/), then follow the [12-criterion evidence map](../README.md#project-self-review-guide), [local setup/checks](../README.md#run-locally), [architecture](architecture.md), [agent process](agent-workflow.md), [release catalogue](github-actions.md), and [dashboard/screenshots](images/delivery/README.md). The [production drill wiki](https://github.com/alanlima/pawlocal/wiki/Incident-drill-2026-10-25-02) provides the alert-to-repair timeline.

## Official requirements and dates

Use the [current project rubric](https://github.com/DataTalksClub/ai-dev-tools-zoomcamp/blob/main/project/README.md), rather than older FAQ/cohort material: 12 criteria, 24 points, 10 points to pass. Three peer evaluations are mandatory independently of score. The [live Project 1 form](https://courses.datatalks.club/ai-dev-tools-2026/project/project1) and [course calendar](https://courses.datatalks.club/ai-dev-tools-2026/calendar.ics) were rechecked on 25 October.

| Milestone | UTC | Australia/Brisbane |
| --- | --- | --- |
| Internal readiness target | 26 October 08:00 | Monday 26 October, 18:00 |
| Project submission closes | 26 October 23:00 | Tuesday 27 October, 09:00 |
| Three peer reviews due | 2 November 23:00 | Tuesday 3 November, 09:00 |

The form's `data-deadline` is `2026-10-26T23:00:00+00:00`; calendar entries confirm both UTC cutoffs. Displayed times depend on browser timezone. The internal target leaves 15 hours before submission closes.

## Submission form preparation

The inspected page requests these fields. Prepare them before the owner submits; this document does not submit the form.

| Field | Prepared value / next action |
| --- | --- |
| Public repository | `https://github.com/alanlima/pawlocal` — verify anonymous visibility at final freeze. |
| Exact commit | Pending final reviewed commit. Source audited here: `8895b99a549ee0db134cec69bd681618f8db46d7`; include the eventual documentation commit before submission. |
| Progress links | Optional, up to 14. Select useful public issues/PRs and the drill wiki; verify each without privileged Grafana access. |
| Time spent | Owner to enter actual time. No estimate has been invented. |
| FAQ contribution | Optional; owner to provide if applicable. |
| Certificate name | Owner to enter intended certificate name. |
| Receipt | Pending: retain submitted URL/commit and confirmation timestamp. |

Useful progress candidates: [foundations/task tracker](https://github.com/alanlima/pawlocal/issues), [delivery reconciliation #281](https://github.com/alanlima/pawlocal/issues/281), [README scope #284](https://github.com/alanlima/pawlocal/issues/284), [telemetry amendment #225](https://github.com/alanlima/pawlocal/issues/225), [drill #396](https://github.com/alanlima/pawlocal/issues/396), [repair PR #400](https://github.com/alanlima/pawlocal/pull/400), [drill wiki](https://github.com/alanlima/pawlocal/wiki/Incident-drill-2026-10-25-02). Do not submit Grafana credentials or private review material.

## Current release and incident evidence

| Evidence | What it establishes | Limit |
| --- | --- | --- |
| [Development 40180921838](https://github.com/alanlima/pawlocal/actions/runs/40180921838) | Actual frontend/backend checks and development release of `8895b99a549ee0db134cec69bd681618f8db46d7`. | Not a fresh clean local Compose run. |
| [Production 40181618456](https://github.com/alanlima/pawlocal/actions/runs/40181618456) | Production promotion of the incident repair. | Does not demonstrate the ordinary manual path; [40044690011](https://github.com/alanlima/pawlocal/actions/runs/40044690011) is historical manual evidence. |
| [Drill #396](https://github.com/alanlima/pawlocal/issues/396), [wiki](https://github.com/alanlima/pawlocal/wiki/Incident-drill-2026-10-25-02) | Real production alert → [run 40180189022](https://github.com/alanlima/pawlocal/actions/runs/40180189022) → repair PR → actual CI → automatic merge → DEV → PROD; continuing traffic observed recovery. | First attempt escalated and used prepared rollback. Second attempt repaired automatically. Keep both attempts auditable. |
| [Incident #399 outcome](https://github.com/alanlima/pawlocal/issues/399#issuecomment-6396140419) | `RELEASE_COMPLETED_UNVERIFIED`. | Enforcement disabled: review/check/provenance/stable-recovery policies are not proven by successful job wrappers. |
| [Fresh app/dashboard captures](images/delivery/README.md) | Actual discovery/detail, filters, share confirmation, anonymous save boundary, production metrics/logs. | No fresh signed-in writes, exact frontend-build binding or correlated trace proof. Incident dashboard still reports unknown external journey/related traces. |

The successful drill recorded 548 HTTP 500 followed by 103 valid HTTP 200 across 320.95 seconds under continuing traffic. The real alert returned Normal. This supports observed application recovery; it does not close formal G1/G2/production-origin acceptance. Do not replace `NO DATA / UNKNOWN` with a success claim.

## Delivery gates and owners

| Owner | Remaining action | Exit evidence |
| --- | --- | --- |
| Documentation agent + independent reviewer | Review README, infra docs, all paths, commands and screenshot captions. | Issue-linked PR, rendered inspection, both required reviews on final head. |
| Developer/platform owner | Run clean Compose startup and authenticated frontend/API/database persistence on the evaluated source. | Healthy services, exact source/config, database readback after fresh context/process, disposable test scope. |
| Developer | Run documented aggregate checks with disposable PostgreSQL integration enabled; run browser harness. | Exact command/results, no unexplained skips; distinguish unit/API SQLite tests from PostgreSQL integration. |
| Monitoring owner/reviewer | Refresh one correlated journey's metrics/logs/traces and reconcile #226/#230. | Same journey trace ID, release/environment, signal readback, privacy review; outstanding probe/exporter/usage/read-scope gates retained. |
| Incident owner/reviewer | Reconcile #229/#231 with the new drill and #399 qualification. | Explicit accepted scope and remaining policy gates. Do not infer acceptance from issue closure or green wrappers. |
| alanlima | Finish separate rollback review. | Exact tested release path, result and approved scope; link evidence here when supplied. No new rollback operation authorized by this plan. |
| Orchestrator + owner | Reconcile historical parents listed in #281 (including #43) and freeze final reviewed submission commit. | Current acceptance/supersession evidence; no premature closure. |
| alanlima | Submit form and record confirmation before cutoff. | Public URL, exact commit, timestamp/receipt. |
| alanlima | Complete three assigned evaluations under #283. | Allocation and three completion confirmations before peer-review cutoff. |

## Infrastructure document review

The review corrected stale pre-deployment/current DSQL-outage and telemetry-disabled claims in the README, architecture, implementation plan, testing, backend README and hosted telemetry guide. Original stage criteria and initial rollout examples are historical; maintained operational instructions remain canonical. Development/production/IAM-bootstrap ownership, runtime secret boundaries, ordinary manual promotion and incident exceptions remain explicit.

Read [DEC-015](decisions.md#dec-015--temporary-disabling-of-shared-strict-release-plan-invocation-305) and [DEC-017](decisions.md) alongside the source policies: shared strict release-plan validation is temporarily disabled; incident software policy enforcement has its own broader temporary switch. Existing external GitHub/IAM controls, Terraform state ownership and infrastructure approval still apply. Documents cannot establish current live settings by themselves.

## Verification record

Documentation branch: `docs/284-delivery-readme`, based on source `8895b99a549ee0db134cec69bd681618f8db46d7`. Final documentation PR/commit will be recorded in #284. Live screenshots were captured separately; no frontend bundle commit is claimed from the `BUILD local` label.

- Official rubric, form fields, embedded UTC deadline and calendar: inspected 25 October 2026.
- Public production UI: real discovery/detail, category filtering (17 dog parks), facility controls, share confirmation and anonymous save prompt inspected and captured.
- Grafana production application/incident dashboards: inspected; actual metrics and safe structured logs visible. Unknown panels retained in captions.
- Infrastructure source/workflow review: architecture, Terraform ownership, DSQL role configuration, CI/release and telemetry instructions inspected; no infrastructure operation performed.
- `git diff --check`: passed. All relative Markdown file targets and heading fragments resolve across the 12 changed/new Markdown documents.
- Rendered README and delivery plan: inspected using GitHub-rendered Markdown previews; embedded images loaded. Mermaid rendering requires the GitHub repository viewer and remains a final PR-view check.
- Independent documentation review: screenshot/content review found one DEC-015 fragment mismatch, corrected; final integrated review is tracked on the PR.
- Aggregate README check command: passed after `npm ci --prefix frontend`, using the existing backend test virtual environment and `PYTHONPATH` bound to this worktree. Frontend: 15 files / 73 Vitest tests plus 9 Node checks passed. Backend: 237 passed, 3 PostgreSQL/migration tests skipped because no disposable integration URL was configured. This was an isolated source worktree using an existing Python environment, not a clean dependency installation.
- Initial Windows checkout test failure: WSL/Bash received CRLF shell scripts and rejected `pipefail`. Repeating with LF checkout bytes passed; no shell source change was included. README records this prerequisite.
- Clean Compose startup, PostgreSQL integration and authenticated browser persistence: not rerun; Docker daemon was unavailable (`docker ps` could not connect to Docker Desktop Linux engine).
- Submission/peer-review receipt: pending owner/platform action.
