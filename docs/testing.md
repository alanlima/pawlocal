# Testing strategy

This document describes the automated checks and additional operational evidence expected for each stage. Pull request CI runs the applicable frontend, backend, Compose, and Terraform checks described below; it does not provision cloud infrastructure.

## CI path ownership and required status

The `CI` workflow runs on every pull request and every push to `main`; it deliberately has no workflow-level path filter so a docs-only PR still receives a completed required status. A lightweight detector maps changed paths to component checks, and the stable aggregate job is named **`CI / Required CI status`**. Configure the `main` branch protection rule or ruleset to require that context. Do not require the conditionally skipped component jobs individually. The aggregate succeeds when path detection succeeds and each applicable job succeeds; intentionally skipped jobs count as acceptable. A failed, canceled, or skipped detector fails the aggregate. The repository currently has no `main` branch protection rule; this change documents the context but does not change repository settings.

Path ownership is implemented in `scripts/ci/classify_changed_paths.py` and covered by `tests/ci/test_changed_paths.py`.

| Changed path | CI checks |
| --- | --- |
| `README.md`, `docs/**`, or any Markdown file | Required status only; component and workflow validation jobs are skipped |
| `frontend/**` | Frontend |
| `backend/**` | Backend |
| `docker-compose.yml`, `.env.example`, `observability/**` | Compose |
| `.dockerignore`, root Compose files, root Dockerfile | Compose |
| Root `package.json` or npm/pnpm/yarn lockfile | Frontend |
| Root `pyproject.toml`, `requirements.txt`, Poetry or uv lockfile | Backend |
| `infra/terraform/**` | Terraform |
| `openapi.yaml` | Frontend, backend, and Compose |
| `.github/workflows/ci.yml` | Frontend, backend, Compose, Terraform, and workflow validation |
| `.github/workflows/frontend-deploy.yml`, `.github/workflows/frontend-production-deploy.yml` | Workflow validation and Frontend |
| Other `.github/workflows/**` | Workflow validation |
| `scripts/ci/**`, `tests/ci/**` | Workflow validation and path-case tests |
| Mixed paths | Union of the checks owned by each path |
| Manual `workflow_dispatch` | Full validation suite |

The production frontend deployment remains a separate workflow. A push to `main` that changes `frontend/**` or the production deployment workflow runs the deploy workflow; documentation-only changes do not match its trigger paths. Manual production deployment dispatch remains available separately and is restricted to `main` at the job level.

Workflow changes run Actionlint syntax/security checks and the path-case tests. Actionlint is downloaded as a versioned release with its published SHA-256 verified. Actionlint 1.7.12 does not yet recognize GitHub's `queue` concurrency key, so only that exact schema diagnostic is ignored; all other workflow diagnostics remain errors.

- **Stage 0:** Review specification acceptance criteria, API consistency, security assumptions and stage gates.
- **Stage 1:** CI runs frontend formatting/lint, Vitest and React Testing Library, a production build, and Playwright browser tests for principal discovery, detail/share, contribution, and responsive behavior. Cover loading, error and empty states.
- **Stage 2:** Exercise instrumented user journeys and synthetic API/dependency failures; verify telemetry correlation, dashboards and recovery signals.
- **Stage 3:** CI installs the backend test extra, runs Ruff lint checks, applies Alembic migrations to a disposable PostgreSQL service, and runs pytest including PostgreSQL-backed persistence and migration checks. The real-browser frontend/API/database flow remains documented in `backend/README.md` as an additional local verification.
- **Stage 4:** CI validates `docker compose config`, builds and starts the complete local stack, waits for service health checks, smoke-checks the frontend, API, and Grafana, and removes containers and volumes even when a preceding step fails. Terraform CI checks formatting, initializes providers with the remote backend disabled, and validates configuration without AWS credentials, planning, or applying. Production alerting, incident response, rollback/recovery drills, and operational acceptance still require separate evidence.

Tests must verify approved behavior, avoid relying on invented place data, and never use production personal data. Report only checks actually executed.

