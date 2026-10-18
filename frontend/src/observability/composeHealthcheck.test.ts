import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const compose = readFileSync(resolve(process.cwd(), '../docker-compose.yml'), 'utf8')
const lokiDockerfile = readFileSync(
  resolve(process.cwd(), '../observability/healthcheck-images/loki.Dockerfile'),
  'utf8',
)
const tempoDockerfile = readFileSync(
  resolve(process.cwd(), '../observability/healthcheck-images/tempo.Dockerfile'),
  'utf8',
)

describe('Loki Compose readiness check', () => {
  it('probes the running Loki readiness endpoint with the embedded BusyBox client', () => {
    const lokiService = compose.match(
      /\x20{2}loki:\r?\n([\s\S]*?)(?=\r?\n\x20{2}[a-z][\w-]*:\r?\n|\r?\nvolumes:)/,
    )?.[1]

    expect(lokiService).toContain('observability/healthcheck-images/loki.Dockerfile')
    expect(lokiService).toContain('"/busybox-bin", "wget"')
    expect(lokiService).toContain('http://127.0.0.1:3100/ready')
    expect(lokiService).not.toContain('-verify-config')
    expect(lokiDockerfile).toContain('FROM grafana/loki:3.5.3')
    expect(lokiDockerfile).toContain('COPY --from=healthcheck /bin/busybox /busybox-bin')
  })

  it('probes the running Tempo readiness endpoint with a file path outside the base image directory', () => {
    const tempoService = compose.match(
      /\x20{2}tempo:\r?\n([\s\S]*?)(?=\r?\n\x20{2}[a-z][\w-]*:\r?\n|\r?\nvolumes:)/,
    )?.[1]

    expect(tempoService).toContain('"/busybox-bin", "wget"')
    expect(tempoService).toContain('http://127.0.0.1:3200/ready')
    expect(tempoDockerfile).toContain('FROM grafana/tempo:2.8.2')
    expect(tempoDockerfile).toContain('COPY --from=healthcheck /bin/busybox /busybox-bin')
  })
})

describe('combined Stage 3.1 Compose wiring', () => {
  it('connects the HTTP frontend to the healthy backend and PostgreSQL with telemetry enabled', () => {
    const serviceBlock = (service: string) =>
      compose.match(
        new RegExp(`^  ${service}:\\r?\\n([\\s\\S]*?)(?=^  [a-z][\\w-]*:\\r?\\n|^volumes:)`, 'm'),
      )?.[1]
    const frontendService = serviceBlock('frontend')
    const backendService = serviceBlock('backend')
    const postgresService = serviceBlock('postgres')

    expect(frontendService).toContain('VITE_USE_MOCK_BACKEND: "false"')
    expect(frontendService).toContain('VITE_API_BASE_URL: /api/v1')
    expect(frontendService).toContain('VITE_API_PROXY_TARGET: http://backend:8000')
    expect(frontendService).toContain('condition: service_healthy')
    expect(backendService).toContain('dockerfile: backend/Dockerfile')
    expect(backendService).toContain('http://otel-collector:4318')
    expect(backendService).toContain(
      'PAWLOCAL_DEMO_FAULTS_ENABLED: ${PAWLOCAL_DEMO_FAULTS_ENABLED:-true}',
    )
    expect(backendService).toContain('alembic -c alembic.ini upgrade head')
    expect(backendService).toContain('http://127.0.0.1:8000/health')
    expect(postgresService).toContain('postgres:17.6-alpine')
    expect(postgresService).toContain('pg_isready')
    expect(compose).toContain('postgres-data:/var/lib/postgresql/data')
  })
})
