# Testing strategy

This document describes the automated checks and additional operational evidence expected for each stage. Pull request CI runs the applicable frontend, backend, Compose, and Terraform checks described below; it does not provision cloud infrastructure.

- **Stage 0:** Review specification acceptance criteria, API consistency, security assumptions and stage gates.
- **Stage 1:** CI runs frontend formatting/lint, Vitest and React Testing Library, a production build, and Playwright browser tests for principal discovery, detail/share, contribution, and responsive behavior. Cover loading, error and empty states.
- **Stage 2:** Exercise instrumented user journeys and synthetic API/dependency failures; verify telemetry correlation, dashboards and recovery signals.
- **Stage 3:** CI installs the backend test extra, runs Ruff lint checks, applies Alembic migrations to a disposable PostgreSQL service, and runs pytest including PostgreSQL-backed persistence and migration checks. The real-browser frontend/API/database flow remains documented in `backend/README.md` as an additional local verification.
- **Stage 4:** CI validates `docker compose config`, builds and starts the complete local stack, waits for service health checks, smoke-checks the frontend, API, and Grafana, and removes containers and volumes even when a preceding step fails. Terraform CI checks formatting, initializes providers with the remote backend disabled, and validates configuration without AWS credentials, planning, or applying. Production alerting, incident response, rollback/recovery drills, and operational acceptance still require separate evidence.

Tests must verify approved behavior, avoid relying on invented place data, and never use production personal data. Report only checks actually executed.

