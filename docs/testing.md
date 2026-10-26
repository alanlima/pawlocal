# Testing strategy

This document describes the automated checks and additional operational evidence expected for each stage. Pull request CI runs the applicable frontend, backend, Compose, and Terraform checks described below; it does not provision cloud infrastructure.

## GitHub-hosted runner and action runtime policy

All GitHub-hosted jobs are pinned to `ubuntu-24.04`. GitHub's Ubuntu 26 migration notice says that `ubuntu-latest` begins moving from Ubuntu 24.04 to Ubuntu 26.04 on October 19, 2026, recommends the explicit `ubuntu-24.04` label when migration causes risk, and identifies `ubuntu-26.04` as the opt-in validation label. PawLocal will therefore remain on Ubuntu 24.04 until a separate change validates every hosted job on Ubuntu 26.04. This avoids changing the operating system underneath CI, release, seed, and protected Terraform jobs without review. See the [official migration notice](https://github.com/actions/runner-images/issues/14748) and [runner image labels](https://github.com/actions/runner-images#available-images).

Issue #83 also establishes maintained Node.js 24 majors for every direct external JavaScript action used by PawLocal. The original warning named six action families; the review also covered the other direct external actions so a resulting full run cannot retain the same forced-runtime warning through an unreviewed dependency.

| External action family | Repository policy | Official evidence |
| --- | --- | --- |
| `actions/checkout` | `@v7` | [`action.yml`](https://github.com/actions/checkout/blob/v7/action.yml) |
| `actions/github-script` | `@v9` | [`action.yml`](https://github.com/actions/github-script/blob/v9/action.yml) |
| `actions/setup-node` | `@v7` | [`action.yml`](https://github.com/actions/setup-node/blob/v7/action.yml) |
| `actions/setup-python` | `@v7` | [`action.yml`](https://github.com/actions/setup-python/blob/v7/action.yml) |
| `actions/upload-artifact` | `@v7` | [`action.yml`](https://github.com/actions/upload-artifact/blob/v7/action.yml) |
| `aws-actions/configure-aws-credentials` | `@v6` | [`action.yml`](https://github.com/aws-actions/configure-aws-credentials/blob/v6/action.yml) |
| `docker/build-push-action` | `@v7` | [`action.yml`](https://github.com/docker/build-push-action/blob/v7/action.yml) |
| `docker/login-action` | `@v4` | [`action.yml`](https://github.com/docker/login-action/blob/v4/action.yml) |
| `docker/setup-buildx-action` | `@v4` | [`action.yml`](https://github.com/docker/setup-buildx-action/blob/v4/action.yml) |
| `hashicorp/setup-terraform` | `@v4` | [`action.yml`](https://github.com/hashicorp/setup-terraform/blob/v4/action.yml) |
| `actions/download-artifact` | Not used; no action reference is required | [Current `@v8` metadata](https://github.com/actions/download-artifact/blob/v8/action.yml) is Node.js 24-compatible if a future workflow reintroduces downloads |

`tests/ci/test_action_runtime_policy.py` inventories every hosted job, rejects floating runner labels, parses every step-level external `uses` value, and fails closed on quoted unreviewed families, action subpaths, floating refs, SHAs, or unsupported external forms. External steps inside repository-local composite action metadata are scanned by the same runtime policy. Job-level reusable workflow calls remain outside this external JavaScript action policy; their hosted jobs and external steps are inventoried separately. The same suite enforces the reviewed action majors, verifies that the download-artifact exception remains true, and keeps smoke artifacts unique across job retries. Pull-request CI safely executes the frontend, backend, Compose, Terraform, and workflow-validation jobs. Workflow validation includes a non-mutating `actions/github-script` runtime assertion plus a smoke job that configures Buildx, authenticates to GHCR without publishing, builds without loading or publishing, and uploads short-lived policy evidence. Protected release, production, seed, and Terraform apply jobs are validated statically on pull requests but are not dispatched merely to test an action upgrade: they require environment approvals, runtime credentials, and in some cases would mutate AWS or application data. In particular, `aws-actions/configure-aws-credentials` remains static-plus-review evidence until the next separately authorized credentialed run. No Issue #83 validation run grants deployment, seed, Terraform plan/apply, or AWS mutation authorization.

| Workflow / direct hosted job | Safe Issue #83 verification | Live credentialed verification |
| --- | --- | --- |
| `backend-ci.yml` / `backend` | Pull-request job runs on Ubuntu 24.04 | Not applicable |
| `compose-ci.yml` / `compose` | Pull-request build, readiness, and smoke job runs on Ubuntu 24.04 | Not applicable |
| `deploy-production.yml` / `verify-production` | Actionlint, policy inventory, unchanged-input review, and protected-path tests | Next separately approved production promotion only |
| `development-dsql-seed.yml` / `seed` | Actionlint, policy inventory, unchanged-input review, and feature-branch fail-closed unit test | Next separately approved development seed only |
| `frontend-deploy.yml` / `frontend` | Pull-request job runs on Ubuntu 24.04 | Not applicable |
| `frontend-production-deploy.yml` / `disabled` | Safe manual no-op dispatch on Ubuntu 24.04 | Not applicable; workflow is retired |
| `fullstack-release.yml` / `publish` | Pull-request condition skips publication; the same checkout, Buildx, GHCR login, and no-push build actions run in the runtime smoke job | Next authorized `main` release only |
| `fullstack-release.yml` / `verify-development` | Pull-request condition skips deployment; action inputs and protected-path tests are validated | Next authorized `main` release only |
| `rollback-development.yml` / `disabled` | Safe manual no-op dispatch on Ubuntu 24.04 | Not applicable; workflow is retired |
| `terraform-ci.yml` / `terraform` | All five matrix roots run on Ubuntu 24.04 | Not applicable; no AWS credentials are used |
| `terraform-current-stack-operations.yml` / `disabled` | Safe manual no-op dispatch on Ubuntu 24.04 | Not applicable; workflow is retired |
| `terraform-environment.yml` / `production-eligibility` | Actionlint, policy inventory, and production eligibility unit tests | Next separately approved production promotion only |
| `terraform-environment.yml` / `plan` | Actionlint, policy inventory, plan-policy tests, and release workflow fail-closed path | Next separately approved environment plan only |
| `terraform-environment.yml` / `apply` | Actionlint, policy inventory, exact-plan/apply tests, and release workflow fail-closed path | Next separately approved exact-plan apply only |
| `workflow-validation.yml` / `action-runtime-smoke` | Pull-request no-push action smoke runs on Ubuntu 24.04 | Not applicable |
| `workflow-validation.yml` / `validate` | Pull-request action runtime, Actionlint, security, and path tests run on Ubuntu 24.04 | Not applicable |

## CI workflow path ownership and required checks

Every pull request runs the real frontend/backend checks through unfiltered `fullstack-release.yml` under [#411](https://github.com/alanlima/pawlocal/issues/411). Main release pushes and the separate Compose, Terraform and workflow-validation triggers retain GitHub-native path filters. `fullstack-release.yml` owns automatic frontend/backend candidate checks and calls their reusable component workflows once; those components are otherwise callable by the manual full suite. The [central Actions catalogue](github-actions.md#automatic-trigger-matrix-and-duplicate-resolution) records the full trigger matrix, exact names, callers and intentional overlaps; `tests/ci/test_workflow_paths.py` and `test_workflow_catalogue.py` enforce coverage and migration contracts.

| Changed path | Automatic pull-request checks |
| --- | --- |
| `README.md`, ordinary Markdown, docs, images and unrelated paths | Real frontend/backend checks; matching guides also run delivery validation |
| `frontend/**`, root npm manifests/lockfiles | Frontend and backend candidate checks through `fullstack-release.yml` |
| `backend/**`, root Python manifests/lockfiles | Frontend and backend candidate checks through `fullstack-release.yml` |
| Compose files, Dockerfiles and `.dockerignore` files, `.env.example`, `observability/**` | Frontend/backend checks plus matching Compose validation/readiness checks |
| `infra/terraform/**` | Frontend/backend checks plus offline Terraform format/validation |
| `openapi.yaml` | Both candidate checks and Compose |
| `.github/workflows/**`, `.github/actions/**`, `.github/workflow-catalogue.json`, `tests/ci/**`, reserved `scripts/ci/**` | Frontend/backend checks plus delivery validation; matching Compose and Terraform consumers also run according to catalogue paths |
| `docs/github-actions.md`, `docs/terraform-greenfield-operations.md`, `docs/iam-bootstrap-actions.md`, `ops/iam-bootstrap/README.md` | Frontend/backend checks plus delivery validation: existing explicit guide exceptions |
| Mixed paths | Union of matching workflows |
| Manual `Quality · Run complete validation suite` dispatch (`ci.yml`) | All five reusable Quality suites, with no environment configuration synchronization |

Relevant `main` pushes and manual main dispatch of `fullstack-release.yml` validate both components before publishing and verifying development. Production uses `deploy-production.yml` to promote an exact development-verified release, subject to its ordinary approval or authenticated incident route. `frontend-production-deploy.yml` is a retired non-deploying stub retained for historical references; it does not deploy production. Manual configuration synchronization belongs to the existing protected Operations dispatcher, `reconcile-environment.yml`.

The earlier Issue #272 ruleset snapshot lacked Quality CI contexts and is historical. Read-only inspection of active main ruleset `25363056` on 25 October 2026 confirmed issuer-bound `PawLocal change authorization` from App integration `5450140`, `Backend checks / Backend checks`, and `Frontend checks and HTTP-mode build / frontend`, with strict current-base checks. The [delivery tracker](https://github.com/alanlima/pawlocal/issues/281) records the reconciled protection evidence. Every PR now creates the two real component checks without a path filter; inspect their actual results and PR authorization before claiming merge readiness. PR activity types remain GitHub's defaults to avoid extra candidate runs for the same SHA. Documentation-only main pushes still do not start an application release. This documentation changes no protection settings. The manual full suite remains available for authorized on-demand validation. See the [Actions catalogue](github-actions.md#find-the-workflow-for-your-task) for workflow ownership.

Actionlint is downloaded as a versioned release with its SHA-256 verified. Actionlint 1.7.12 does not yet recognize GitHub's `queue` concurrency key, so only that exact schema diagnostic is ignored; all other workflow diagnostics remain errors.

- **Stage 0:** Review specification acceptance criteria, API consistency, security assumptions and stage gates.
- **Stage 1:** CI runs frontend formatting/lint, Vitest and React Testing Library, a production build, and Playwright browser tests for principal discovery, detail/share, contribution, and responsive behavior. Cover loading, error and empty states.
- **Stage 2:** Exercise instrumented user journeys and synthetic API/dependency failures; verify telemetry correlation, dashboards and recovery signals.
- **Stage 3:** CI installs the backend test extra, runs Ruff lint checks, applies Alembic migrations to a disposable PostgreSQL service, and runs pytest including PostgreSQL-backed persistence and migration checks. The real-browser frontend/API/database flow remains documented in `backend/README.md` as an additional local verification.
- **Stage 4:** CI validates `docker compose config`, builds and starts the complete local stack, waits for service health checks, smoke-checks the frontend, API, and Grafana, and removes containers and volumes even when a preceding step fails. Issue #135 Terraform CI must format and validate every implemented bootstrap, development, production, and reusable-module directory without AWS credentials or remote-state mutation. Module tests verify that development and production Lightsail names preserve the container-service identity. Permanent native module tests verify fresh development/production Foundation without a Lightsail certificate or custom-domain mapping, shared CloudFront routing/public bindings, and the absence of obsolete certificate creation/validation authority while retaining lifecycle deletion. General greenfield and IAM policy checks remain in CI. Historical migration-only graph fixtures/provider projections have been retired; their implementation and rollout evidence remains in [#346](https://github.com/alanlima/pawlocal/issues/346) and [#421](https://github.com/alanlima/pawlocal/issues/421). Offline tests establish source contracts, not live deployment or state convergence; review actual saved plans and matching environment readback separately. A validation result is not a plan, apply, or deployment. The original Issue #43 release deferred hosted telemetry to #59. Later hosted instrumentation and dashboard sources are implemented; verify their live acceptance separately as described below. Backup/restore and recovery/rollback drills are deferred to #44 after development and production deployment. Migrations must remain compatible with the currently deployed application during a rollout.

Issue #43's full-stack release acceptance requires evidence of successful PR CI, automatic deployment of a merged main release to development, development health/smoke checks tied to an immutable release identifier, and a manually initiated production promotion that validates the release was tested in development and promotes the same backend image digest. Record frontend version, migrations, and deployment outcome; migrations must remain compatible with the currently deployed application. Release acceptance alone does not prove telemetry, backup/HA, restore or rollback guarantees. Hosted telemetry now has separate #59 evidence; backup/recovery scope remains under #44. Active environment workflows implement the greenfield path, while retired combined-state stubs and historical static deployment records are not current deployment proof. DSQL compatibility/runtime credentials, exact-plan evidence, and explicit provisioning approval remain deployment gates.

Tests must verify approved behavior, avoid relying on invented place data, and never use production personal data. Report only checks actually executed.


## Hosted monitoring and delivery evidence

Reviewed tests in `backend/tests/test_cloud_telemetry.py` cover disabled/unavailable exporters, privacy, exact runtime credential retrieval, cache-expiry refresh and failure without stale fallback. The Grafana Cloud definition/query/access tests live under `observability/grafana/cloud/tests/`; incident controller tests live under `tests/ci/` and the on-call tooling. Use the maintained [Grafana Cloud guide](../observability/grafana/cloud/README.md) and [on-call setup](oncall-setup.md) for commands and configuration contracts.

Code and automated tests are one layer of evidence. Live acceptance requires the demonstrated environment/release, bounded traffic, actual metric/log/trace readback and correlation, privacy review, the relevant alert's firing and resolution, and an observation window. A dashboard screenshot, HTTP 200, `telemetry_enabled=true`, green deployment or Normal/no-data alert is insufficient by itself. [#225](https://github.com/alanlima/pawlocal/issues/225) accepts reviewed automated resilience/credential-refresh evidence and verified development ingestion for its amended MVP; the real credential-rotation and exporter outage/restoration drill remains explicitly deferred to #241/post-MVP.

Use [#226](https://github.com/alanlima/pawlocal/issues/226) for G1, [#230](https://github.com/alanlima/pawlocal/issues/230) for production monitoring, [#229](https://github.com/alanlima/pawlocal/issues/229) for the full development-origin repair/recovery loop and [#231](https://github.com/alanlima/pawlocal/issues/231) for separately authorized production-origin acceptance. Issue closure or a merged controller is not a substitute for these criteria. Final reproducibility and rubric evidence belong to [#281](https://github.com/alanlima/pawlocal/issues/281) and [#284](https://github.com/alanlima/pawlocal/issues/284); only record commands and results actually executed on the selected commit.
