import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const compose = readFileSync(resolve(process.cwd(), '../docker-compose.yml'), 'utf8')
const lokiDockerfile = readFileSync(
  resolve(process.cwd(), '../observability/healthcheck-images/loki.Dockerfile'),
  'utf8',
)

describe('Loki Compose readiness check', () => {
  it('probes the running Loki readiness endpoint with the embedded BusyBox client', () => {
    const lokiService = compose.match(
      /\x20{2}loki:\r?\n([\s\S]*?)(?=\r?\n\x20{2}[a-z][\w-]*:\r?\n|\r?\nvolumes:)/,
    )?.[1]

    expect(lokiService).toContain('observability/healthcheck-images/loki.Dockerfile')
    expect(lokiService).toContain('"/busybox", "wget"')
    expect(lokiService).toContain('http://127.0.0.1:3100/ready')
    expect(lokiService).not.toContain('-verify-config')
    expect(lokiDockerfile).toContain('FROM grafana/loki:3.5.3')
    expect(lokiDockerfile).toContain('COPY --from=healthcheck /bin/busybox /busybox')
  })
})
