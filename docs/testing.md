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

`tests/ci/test_action_runtime_policy.py` inventories every hosted job, rejects floating runner labels, enforces these action majors, and verifies that the download-artifact exception remains true. Pull-request CI safely executes the frontend, backend, Compose, Terraform, and workflow-validation jobs. Workflow validation includes a non-mutating `actions/github-script` runtime assertion plus a smoke job that configures Buildx, authenticates to GHCR with read-only package permission, builds without loading or publishing, and uploads short-lived policy evidence. Protected release, production, seed, and Terraform apply jobs are validated statically on pull requests but are not dispatched merely to test an action upgrade: they require environment approvals, runtime credentials, and in some cases would mutate AWS or application data. In particular, `aws-actions/configure-aws-credentials` remains static-plus-review evidence until the next separately authorized credentialed run. No Issue #83 validation run grants deployment, seed, Terraform plan/apply, or AWS mutation authorization.

## CI workflow path ownership and required checks

CI uses separate workflows with GitHub-native top-level `pull_request.paths` and `push.paths` filters. A docs-only change such as `README.md` or `docs/**` matches no automatic workflow, so GitHub Actions starts no run. The frontend, backend, Compose, Terraform, and workflow-validation paths are listed directly in their workflow files and verified by `tests/ci/test_workflow_paths.py`.

| Changed path | Automatic checks |
| --- | --- |
| `README.md`, `docs/**`, other Markdown | No workflow run |
| `frontend/**`, root npm manifests/lockfiles | Frontend checks |
| `backend/**`, root Python manifests/lockfiles | Backend checks |
| Compose files, Dockerfiles and `.dockerignore` files, `.env.example`, `observability/**` | Compose validation and readiness smoke; Dockerfiles under frontend/backend also run their component checks |
| `infra/terraform/**` | Terraform format and validation |
| `openapi.yaml` | Frontend, backend, and Compose checks |
| `.github/workflows/**`, `scripts/ci/**`, `tests/ci/**` | Workflow syntax/security validation and path tests; changes to frontend/backend/Compose/Terraform workflow files also run that affected workflow |
| Mixed paths | Union of matching workflows |
| Manual `CI manual full suite` dispatch | Frontend, backend, Compose, Terraform, and workflow validation reusable workflows |

The production frontend deployment workflow runs on `main` for frontend code, shared API contract, frontend root manifests, or its own workflow definition. Documentation-only changes do not trigger deployment. Manual production deployment remains restricted to `main` by its job condition.

There is currently no `main` branch protection rule. Because docs-only changes intentionally produce no status checks, requiring the component workflow contexts directly would risk blocking PRs when their workflows do not run. This PR does not configure branch protection; if required checks are enabled later, use a GitHub ruleset or external policy that supports path-aware requirements, or revisit the no-workflow-on-docs requirement. The manual full-suite workflow is available for on-demand checks and does not run for routine docs-only changes.

Actionlint is downloaded as a versioned release with its SHA-256 verified. Actionlint 1.7.12 does not yet recognize GitHub's `queue` concurrency key, so only that exact schema diagnostic is ignored; all other workflow diagnostics remain errors.

- **Stage 0:** Review specification acceptance criteria, API consistency, security assumptions and stage gates.
- **Stage 1:** CI runs frontend formatting/lint, Vitest and React Testing Library, a production build, and Playwright browser tests for principal discovery, detail/share, contribution, and responsive behavior. Cover loading, error and empty states.
- **Stage 2:** Exercise instrumented user journeys and synthetic API/dependency failures; verify telemetry correlation, dashboards and recovery signals.
- **Stage 3:** CI installs the backend test extra, runs Ruff lint checks, applies Alembic migrations to a disposable PostgreSQL service, and runs pytest including PostgreSQL-backed persistence and migration checks. The real-browser frontend/API/database flow remains documented in `backend/README.md` as an additional local verification.
- **Stage 4:** CI validates `docker compose config`, builds and starts the complete local stack, waits for service health checks, smoke-checks the frontend, API, and Grafana, and removes containers and volumes even when a preceding step fails. Issue #135 Terraform CI must format and validate every implemented bootstrap, development, production, and reusable-module directory without AWS credentials or remote-state mutation. Module tests also verify that development and production Lightsail names derive from the single suffix map, preserve the container-service name, and use only `cert` for certificate resource names. A validation result is not a plan, apply, or deployment. The Issue #43 cloud MVP keeps hosted telemetry and alerting disabled; hosted telemetry is deferred to #59. Backup/restore and recovery/rollback drills are deferred to #44 after development and production deployment. Migrations must remain compatible with the currently deployed application during a rollout.

Issue #43's full-stack release acceptance requires evidence of successful PR CI, automatic deployment of a merged main release to development, development health/smoke checks tied to an immutable release identifier, and a manually initiated production promotion that validates the release was tested in development and promotes the same backend image digest. Record frontend version, migrations, and deployment outcome; migrations must remain compatible with the currently deployed application. Do not require or claim telemetry, backup/HA, restore, or rollback guarantees for this MVP; those reviews are deferred to #59 and #44. These deployment scenarios are documented acceptance requirements only. The checked-in pre-Issue-#135 workflows and historical deployment records do not demonstrate the new greenfield path. DSQL compatibility/runtime credentials, exact-plan evidence, and explicit provisioning approval remain deployment gates.

Tests must verify approved behavior, avoid relying on invented place data, and never use production personal data. Report only checks actually executed.

