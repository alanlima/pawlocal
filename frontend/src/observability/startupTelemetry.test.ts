import { afterEach, expect, it, vi } from 'vitest'

const { render, exporter, stop } = vi.hoisted(() => ({
  render: vi.fn(),
  exporter: vi.fn(),
  stop: vi.fn(),
}))
vi.mock('react-dom/client', () => ({ default: { createRoot: () => ({ render }) } }))
vi.mock('../app/App', () => ({ default: () => null }))
vi.mock('../styles.css', () => ({}))
vi.mock('../app/appFooter.css', () => ({}))
vi.mock('../app/responsiveArtwork.css', () => ({}))
vi.mock('./cloudTelemetry', () => ({
  cloudExporter: exporter,
  cloudSampler: () => undefined,
  stopCloudTelemetry: stop,
  cloudOutcome: vi.fn(),
}))

afterEach(() => {
  vi.unstubAllEnvs()
  vi.restoreAllMocks()
})

it('mounts the application when hosted exporter initialization fails before React starts', async () => {
  vi.resetModules()
  vi.stubEnv('VITE_RELEASE_ENV', 'development')
  vi.stubEnv('VITE_TELEMETRY_ENABLED', 'true')
  exporter.mockImplementation(() => {
    throw new Error('synthetic Faro startup failure')
  })
  document.body.innerHTML = '<div id="root"></div>'
  await expect(import('../main')).resolves.toBeDefined()
  expect(render).toHaveBeenCalledOnce()
  expect(stop).toHaveBeenCalledOnce()
})
