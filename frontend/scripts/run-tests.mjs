import { spawnSync } from 'node:child_process'

const testEnv = { ...process.env }
for (const name of [
  'VITE_RELEASE_ENV',
  'VITE_API_BASE_URL',
  'VITE_COGNITO_DOMAIN',
  'VITE_COGNITO_CLIENT_ID',
  'VITE_COGNITO_REDIRECT_URI',
  'VITE_COGNITO_LOGOUT_URI',
  'VITE_COGNITO_SCOPES',
]) {
  delete testEnv[name]
}
testEnv.VITE_USE_MOCK_BACKEND = 'true'
testEnv.VITE_TELEMETRY_ENABLED = 'false'

for (const args of [
  ['node_modules/vitest/vitest.mjs', 'run'],
  ['--test', 'scripts/validate-release-config.test.mjs'],
]) {
  const [command, ...commandArgs] = args
  const result = spawnSync(process.execPath, [command, ...commandArgs], {
    env: testEnv,
    stdio: 'inherit',
  })
  if (result.error) throw result.error
  if (result.status !== 0) process.exit(result.status ?? 1)
}
