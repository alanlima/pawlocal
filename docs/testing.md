# Testing strategy

This document describes planned checks; the repository has no application code yet and no checks have been run.

- **Stage 0:** Review specification acceptance criteria, API consistency, security assumptions and stage gates.
- **Stage 1:** Vitest and React Testing Library for components and service behavior; Playwright for principal discovery, detail/share and contribution journeys. Cover loading, error and empty states.
- **Stage 2:** Exercise instrumented user journeys and synthetic API/dependency failures; verify telemetry correlation, dashboards and recovery signals.
- **Stage 3:** pytest unit and API/integration tests, PostgreSQL-backed persistence/migration checks, plus end-to-end frontend/API/database flows.
- **Stage 4:** Reproducible Docker Compose startup, CI checks, controlled recovery/rollback demonstration and operational acceptance evidence.

Tests must verify approved behavior, avoid relying on invented place data, and never use production personal data. Report only checks actually executed.

