import assert from 'node:assert/strict';
import { generateKeyPairSync, verify } from 'node:crypto';
import { test } from 'node:test';
import { mint } from '../../ops/incident-response/publisher-token.mjs';

const keys = generateKeyPairSync('rsa', { modulusLength: 2048 });
const appPermissions = { contents: 'write', pull_requests: 'write', issues: 'write', statuses: 'write', administration: 'read' };

function fixture(purpose, change = {}) {
  const env = { PAWLOCAL_ONCALL_ENFORCE_GUARDS: 'true', GITHUB_REPOSITORY: 'alanlima/pawlocal', GITHUB_REF: 'refs/heads/main', GITHUB_RUN_ATTEMPT: '1',
    INCIDENT_DEADLINE: String(Math.floor(Date.now() / 1000) + 600), PAWLOCAL_CREDENTIAL_PHASE: purpose,
    PAWLOCAL_PUBLISHER_APP_ID: '1', PAWLOCAL_PUBLISHER_INSTALLATION_ID: '2', RUNNER_TEMP: '/fixture',
    PAWLOCAL_ONCALL_PUBLISHER_APP_PRIVATE_KEY: keys.privateKey.export({ type: 'pkcs8', format: 'pem' }) };
  const calls = [], writes = [];
  async function fetcher(url, options) {
    calls.push({ url, options });
    const jwt = options.headers.Authorization.slice('Bearer '.length).split('.');
    assert(verify('RSA-SHA256', Buffer.from(`${jwt[0]}.${jwt[1]}`), keys.publicKey, Buffer.from(jwt[2], 'base64url')));
    let value;
    if (url.endsWith('/app')) value = { id: 1, permissions: change.app || appPermissions };
    else if (url.endsWith('/installation')) value = { id: 2, app_id: 1, account: { login: 'alanlima' }, repository_selection: 'selected', permissions: appPermissions };
    else value = { token: 'fixture-token-placeholder-only-00000000', repository_selection: 'selected', permissions: change.token || JSON.parse(options.body).permissions };
    return new Response(JSON.stringify(value), { status: 200 });
  }
  return { env, calls, writes, run: () => mint(env, fetcher, (...args) => writes.push(args)) };
}

test('status credential is independently downscoped to statuses write only', async () => {
  const value = fixture('status');
  await value.run();
  const body = JSON.parse(value.calls.at(-1).options.body);
  assert.deepEqual(body, { repository_ids: [1423024931], permissions: { statuses: 'write' } });
  assert(value.writes[0][0].endsWith('oncall-status-token.json'));
  assert.deepEqual(JSON.parse(value.writes[0][1]).permissions, { statuses: 'write' });
  assert.deepEqual(value.writes[0][2], { mode: 0o600, flag: 'wx' });
});

test('readiness credential is independently downscoped to Administration read only', async () => {
  const value = fixture('readiness');
  await value.run();
  const body = JSON.parse(value.calls.at(-1).options.body);
  assert.deepEqual(body, { repository_ids: [1423024931], permissions: { administration: 'read' } });
  assert(value.writes[0][0].endsWith('oncall-readiness-token.json'));
  assert.deepEqual(JSON.parse(value.writes[0][1]).permissions, { administration: 'read' });
  assert.deepEqual(value.writes[0][2], { mode: 0o600, flag: 'wx' });
});

for (const purpose of ['publish', 'merge']) test(`${purpose} credential omits Administration capability`, async () => {
  const value = fixture(purpose);
  await value.run();
  assert.deepEqual(JSON.parse(value.calls.at(-1).options.body).permissions, { contents: 'write', pull_requests: 'write', issues: 'write' });
  assert(value.writes[0][0].endsWith('oncall-publisher-token.json'));
});

test('Administration write or a broad readiness token is denied before credential handoff', async () => {
  for (const change of [{ app: { ...appPermissions, administration: 'write' } }, { token: appPermissions }, { token: { administration: 'write' } }]) {
    const value = fixture('readiness', change);
    await assert.rejects(value.run());
    assert.deepEqual(value.writes, []);
  }
});

test('an unconfigured Administration-read App or unknown purpose cannot mint', async () => {
  const missing = fixture('readiness', { app: { contents: 'write', pull_requests: 'write', issues: 'write' } });
  await assert.rejects(missing.run());
  assert.deepEqual(missing.writes, []);
  const unknown = fixture('arbitrary');
  await assert.rejects(unknown.run());
  assert.deepEqual(unknown.calls, []);
});

test('status credential permits rerun attempts while publish and merge remain attempt 1 only', async () => {
  const rerunStatus = fixture('status');
  rerunStatus.env.GITHUB_RUN_ATTEMPT = '2';
  await rerunStatus.run();
  assert(rerunStatus.writes[0][0].endsWith('oncall-status-token.json'));

  const rerunPublish = fixture('publish');
  rerunPublish.env.GITHUB_RUN_ATTEMPT = '2';
  await assert.rejects(rerunPublish.run());

  const rerunMerge = fixture('merge');
  rerunMerge.env.GITHUB_RUN_ATTEMPT = '2';
  await assert.rejects(rerunMerge.run());
});

for (const mode of [undefined, '', 'false']) test(`disabled token policy (${String(mode)}) tolerates rerun, deadline and App policy mismatch`, async () => {
  const value = fixture('publish', { app: { contents: 'write' } });
  value.env.PAWLOCAL_ONCALL_ENFORCE_GUARDS = mode;
  value.env.GITHUB_RUN_ATTEMPT = '2';
  value.env.INCIDENT_DEADLINE = '1';
  await value.run();
  assert.equal(value.writes.length, 1);
  assert.deepEqual(JSON.parse(value.calls.at(-1).options.body).permissions, { contents: 'write', pull_requests: 'write', issues: 'write' });
});
test('invalid enforcement mode fails before any credential request', async () => {
  const value = fixture('publish');
  value.env.PAWLOCAL_ONCALL_ENFORCE_GUARDS = 'TRUE';
  await assert.rejects(value.run(), /must be true or false/);
  assert.equal(value.calls.length, 0);
});
