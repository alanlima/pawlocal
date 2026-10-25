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
test('Environment overrides resolve only inside a runner step and controller jobs use its snapshot', () => {
  const incident = workflow('incident-responder');
  assert.ok(!incident.includes('\nenv:\n'));
  assert.match(incident, /environment: oncall-\$\{\{ inputs.environment \}\}/);
  assert.match(incident, /id: enforcement\n        env:\n          PAWLOCAL_ONCALL_ENFORCE_GUARDS: \$\{\{ vars\.PAWLOCAL_ONCALL_ENFORCE_GUARDS \|\| 'false' \}\}/);
  assert.match(incident, /enforce_guards: \$\{\{ steps.enforcement.outputs.enforce_guards \}\}/);
  assert.equal((incident.match(/PAWLOCAL_ONCALL_ENFORCE_GUARDS: \$\{\{ needs.preflight.outputs.enforce_guards \}\}/g) || []).length, 8);
  assert.ok(!incident.includes("if: vars.PAWLOCAL_ONCALL_ENFORCE_GUARDS"));
  assert.match(incident, /allow-bot-users: \$\{\{ vars\.PAWLOCAL_ONCALL_DISPATCH_ACTOR/);
});
test('shared authorization resolves origin Environment and ordinary approval pins true', async () => {
  const auth = workflow('change-authorization');
  assert.match(auth, /environment: oncall-\$\{\{ needs.incident-origin.outputs.environment \}\}/);
  assert.match(auth, /PAWLOCAL_ONCALL_ENFORCE_GUARDS: \$\{\{ needs.classify.outputs.enforce_guards \}\}/);
  assert.match(auth.split('  ordinary-approval:')[1], /PAWLOCAL_ONCALL_ENFORCE_GUARDS: 'true'/);
  const origin = auth.split('          script: |\n')[1].split('\n  incident-enforcement:')[0]
    .split('\n').map(line => line.startsWith('            ') ? line.slice(12) : line).join('\n');
  const resolve = new Function('context', 'core', origin);
  for (const [branch, expected] of [['incident/development/key', 'development'], ['incident/production/key', 'production'], ['feature/other', ''], ['incident/other/key', '']]) {
    let actual; resolve({ payload: { pull_request: { head: { ref: branch } } } }, { setOutput: (_, value) => { actual = value; } });
    assert.equal(actual, expected);
  }
});
test('production passes resolved origin mode through reusable Terraform and ordinary calls default true', () => {
  const production = workflow('deploy-production');
  assert.match(production, /incident_environment:\n/);
  assert.match(production, /enforce_guards: \$\{\{ needs.workflow-binding.outputs.enforce_guards \}\}/);
  assert.match(production, /PAWLOCAL_ONCALL_ENFORCE_GUARDS: \$\{\{ needs.workflow-binding.outputs.enforce_guards \}\}/);
  assert.match(source, /enforce_guards:\n[^]*?default: 'true'/);
  assert.match(source, /PAWLOCAL_ONCALL_ENFORCE_GUARDS: \$\{\{ inputs.enforce_guards \|\| 'true' \}\}/);
});
