import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const dashboard = JSON.parse(
  readFileSync(
    resolve(process.cwd(), '../observability/grafana/dashboards/pawlocal-overview.json'),
    'utf8',
  ),
) as {
  panels: { title: string; targets?: { expr: string }[] }[]
}
const datasources = readFileSync(
  resolve(process.cwd(), '../observability/grafana/provisioning/datasources/datasources.yaml'),
  'utf8',
)

describe('Grafana trace drill-down configuration', () => {
  it('keeps the original JSON log line for the derived trace ID matcher', () => {
    const logPanel = dashboard.panels.find(
      (panel) => panel.title === 'Frontend outcomes and correlated trace IDs',
    )
    const query = logPanel?.targets?.[0]?.expr
    const matcher = datasources.match(/matcherRegex:\s+'([^']+)'/)?.[1]
    const traceId = '0123456789abcdef0123456789abcdef'

    expect(query).toContain('| json')
    expect(query).not.toContain('line_format')
    expect(matcher).toBeDefined()
    expect(
      JSON.stringify({ event: 'search_error', traceId }).match(new RegExp(matcher!))?.[1],
    ).toBe(traceId)
  })
})
