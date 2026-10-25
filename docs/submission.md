# Project 1 delivery plan

Owner: alanlima. Tracking: [#281 delivery readiness](https://github.com/alanlima/pawlocal/issues/281), [#284 README/evidence](https://github.com/alanlima/pawlocal/issues/284), [#283 peer reviews](https://github.com/alanlima/pawlocal/issues/283). Documentation preparation: [PR #403](https://github.com/alanlima/pawlocal/pull/403). Last evidence review: 25 October 2026. **Final delivery acceptance and platform submission remain pending; no receipt is recorded.**

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
| [App/dashboard captures](images/delivery/README.md) | Actual public discovery/detail, filters/share, production metrics/logs, plus authenticated local HTTP/API/PostgreSQL fixture captures. | Local ephemeral issuer does not prove hosted Cognito; no exact hosted frontend-build binding or correlated trace proof. Incident dashboard still reports unknown external journey/related traces. |

The successful drill recorded 548 HTTP 500 followed by 103 valid HTTP 200 across 320.95 seconds under continuing traffic. The real alert returned Normal. This supports observed application recovery; it does not close formal G1/G2/production-origin acceptance. Do not replace `NO DATA / UNKNOWN` with a success claim.

## Delivery gates and owners

| Owner | Remaining action | Exit evidence |
| --- | --- | --- |
| Documentation agent + independent reviewer | Review README, infra docs, all paths, commands and screenshot captions. | Issue-linked PR, rendered inspection, both required reviews on final head. |
| Developer/platform owner | Local verification completed below; rebind to final submission source if application code changes. | Eight healthy services; browser/API/PostgreSQL test; retained rows and authenticated API read after local database restart. |
| Developer | Aggregate checks and browser harness completed below; retain final-commit evidence. | 73 Vitest + 9 Node + 240 backend tests, no PostgreSQL skips; one browser integration test. |
| Monitoring owner/reviewer | Refresh one correlated journey's metrics/logs/traces and reconcile #226/#230. | Same journey trace ID, release/environment, signal readback, privacy review; outstanding probe/exporter/usage/read-scope gates retained. |
| Incident owner/reviewer | Reconcile #229/#231 with the new drill and #399 qualification. | Explicit accepted scope and remaining policy gates. Do not infer acceptance from issue closure or green wrappers. |
| alanlima | Finish separate rollback review. | Exact tested release path, result and approved scope; link evidence here when supplied. No new rollback operation authorized by this plan. |
| Orchestrator + owner | Reconcile historical parents listed in #281 (including #43) and freeze final reviewed submission commit. | Current acceptance/supersession evidence; no premature closure. |
| alanlima | Submit form and record confirmation before cutoff. | Public URL, exact commit, timestamp/receipt. |
| alanlima | Complete three assigned evaluations under #283. | Allocation and three completion confirmations before peer-review cutoff. |

## Infrastructure document review

Use the [architecture](architecture.md), [Actions catalogue](github-actions.md), [Terraform operations](terraform-greenfield-operations.md) and [hosted telemetry guide](hosted-telemetry-operations.md) for the maintained contracts. Read [DEC-015](decisions.md#dec-015--temporary-disabling-of-shared-strict-release-plan-invocation-305) and [DEC-017](decisions.md) alongside the source policies. Documents cannot establish current live settings by themselves.

## Verification record

[PR #403's verification record](https://github.com/alanlima/pawlocal/pull/403#issuecomment-6397255513) preserves the source heads, setup, commands, detailed results, initial failures and review history. Current checks and reviews remain attached to that PR. Selecting the final submission commit and recording the submission receipt remain owner actions.

## Local reproducibility verification

Reproduce the application checks with the [README commands](../README.md#run-checks), [backend integration setup](../backend/README.md) and [ephemeral issuer/browser harness](../backend/README.md#browser-integration-authentication). The [PR verification record](https://github.com/alanlima/pawlocal/pull/403#issuecomment-6397255513) contains the recorded clean-environment and persistence results. The local harness uses an ephemeral issuer and PostgreSQL; hosted Cognito, DSQL recovery and sustained telemetry/recovery acceptance require their own evidence.
