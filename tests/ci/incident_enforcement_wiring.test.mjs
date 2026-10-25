import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const workflow = name => readFileSync(new URL(`../../.github/workflows/${name}.yml`, import.meta.url), 'utf8').replaceAll('\r\n', '\n');
const source = workflow('terraform-environment');
const script = source.split('          script: |\n')[1].split('\n  reconcile-preflight:')[0]
  .split('\n').map(line => line.startsWith('            ') ? line.slice(12) : line).join('\n');
const execute = new (Object.getPrototypeOf(async function () {}).constructor)('process', 'github', 'core', 'context', script);
function fixture(mode, incident = 'true', commit = 'a'.repeat(40)) {
  let compared = 0;
  const logs = [];
  return { logs, compared: () => compared, run: () => execute({ env: { PAWLOCAL_ONCALL_ENFORCE_GUARDS: mode, INCIDENT_RELEASE: incident,
    RELEASE_COMMIT: commit, BACKEND_IMAGE: `ghcr.io/alanlima/pawlocal-api@sha256:${'b'.repeat(64)}` } },
  { rest: { repos: { compareCommitsWithBasehead: async () => { compared++; throw new Error('real comparison API failure'); } } } },
  { info: value => logs.push(value), summary: { addRaw: value => { logs.push(value); return { write: async () => {} }; } } }, { repo: {} }) };
}
for (const mode of [undefined, '', 'false']) test(`incident eligibility skips policy with mode ${String(mode)}`, async () => {
  const value = fixture(mode); await value.run(); assert.equal(value.compared(), 0);
  assert.ok(value.logs.some(line => line.includes('verification skipped')));
});
test('enabled incident and ordinary release retain real development eligibility calls', async () => {
  for (const args of [['true', 'true'], ['false', 'false']]) {
    const value = fixture(...args); await assert.rejects(value.run(), /real comparison API failure/); assert.equal(value.compared(), 1);
  }
});
test('invalid flag and unusable commit remain operational failures', async () => {
  await assert.rejects(fixture('TRUE').run(), /must be true or false/);
  await assert.rejects(fixture('false', 'true', 'invalid').run(), /full development-verified commit/);
});
test('trusted workflow consumers receive flag and ordinary approval pins enforcement on', () => {
  for (const name of ['incident-responder', 'change-authorization', 'deploy-production', 'terraform-environment']) {
    assert.match(workflow(name), /PAWLOCAL_ONCALL_ENFORCE_GUARDS: \$\{\{ vars\.PAWLOCAL_ONCALL_ENFORCE_GUARDS \|\| 'false' \}\}/);
  }
  assert.match(workflow('change-authorization').split('  ordinary-approval:')[1], /PAWLOCAL_ONCALL_ENFORCE_GUARDS: 'true'/);
});
