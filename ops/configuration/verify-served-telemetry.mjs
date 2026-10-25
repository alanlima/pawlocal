// Observe the actual served build. Requests are intercepted; no telemetry is posted.
// Journey logs/measurements are unsampled; trace sampling remains unchanged.
export async function verifyServedTelemetry(browser, config, environment, commit) {
  if (!['development', 'production'].includes(environment) || !/^[0-9a-f]{40}$/.test(commit ?? ''))
    throw new Error('Missing served release identity')
  const mode = config.VITE_TELEMETRY_ENABLED
  if (!['true', 'false'].includes(mode)) throw new Error('Missing verified frontend mode')
  const expected = mode === 'true' ? config.VITE_FARO_COLLECTOR_URL : null
  if (mode === 'true' && !expected) throw new Error('Missing verified collector')
  const context = await browser.newContext({ extraHTTPHeaders: { 'Cache-Control': 'no-cache' } })
  let observed = 0
  let invalid = false
  try {
    await context.route('**/*', async (route) => {
      const request = route.request()
      const url = new URL(request.url())
      if (url.hostname.endsWith('.grafana.net') || /\/v1\/(traces|metrics|logs)$/.test(url.pathname)) {
        if (request.method() !== 'OPTIONS') {
          observed += 1
          invalid ||= mode !== 'true' || request.url() !== expected || request.method() !== 'POST'
          try {
            const payload = request.postDataJSON()
            const transportId = request.headers()['x-faro-session-id']
            invalid ||= payload?.meta?.app?.name !== 'pawlocal-frontend' ||
              payload?.meta?.app?.environment !== environment || payload?.meta?.app?.version !== commit
            invalid ||= !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(transportId ?? '') ||
              payload?.meta?.sdk?.name !== '@grafana/faro-web-sdk' ||
              !/^\d+\.\d+\.\d+$/.test(payload?.meta?.sdk?.version ?? '') ||
              Object.keys(payload?.meta?.sdk ?? {}).some((key) => !['name', 'version'].includes(key)) ||
              Object.keys(payload?.meta ?? {}).some((key) => !['app', 'sdk'].includes(key))
          } catch { invalid = true }
        }
        await route.fulfill({ status: 204, headers: {
          'access-control-allow-origin': new URL(config.PAWLOCAL_PUBLIC_BASE_URL).origin,
          'access-control-allow-methods': 'POST, OPTIONS',
          'access-control-allow-headers': '*',
        } })
      } else await route.continue()
    })
    const page = await context.newPage()
    await page.goto(config.PAWLOCAL_PUBLIC_BASE_URL, { waitUntil: 'networkidle', timeout: 30000 })
    // Landing performs the public place search; export/batching timers are bounded.
    await page.waitForTimeout(4000)
    if (invalid || (mode === 'true' ? observed === 0 : observed !== 0))
      throw new Error('Served telemetry mode or collector mismatch')
    console.log('Served frontend telemetry mode and collector verified; export intercepted, ingestion unclaimed.')
  } finally { await context.close() }
}
