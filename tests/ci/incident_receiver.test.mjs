import assert from 'node:assert/strict';
import { createHmac, generateKeyPairSync, verify } from 'node:crypto';
import { test } from 'node:test';
import { createHandler } from '../../infra/terraform/modules/pawlocal-environment/lambda/incident-receiver/index.mjs';

const TIME = Date.parse('2026-10-23T10:00:00Z');
const HMAC = 'hmac-test-fixture-32-bytes-minimum';
const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const KEY = privateKey.export({ type: 'pkcs8', format: 'pem' });
const env = {
  PAWLOCAL_PROJECT_NAME: 'pawlocal', PAWLOCAL_DISPATCH_REPOSITORY: 'alanlima/pawlocal',
  PAWLOCAL_ONCALL_ENVIRONMENT: 'development', PAWLOCAL_ONCALL_ALLOWED_SERVICES: '["pawlocal-api"]',
  PAWLOCAL_ONCALL_ALLOWED_ALERTS: '["pawlocal-development-search-detail-failure"]',
  PAWLOCAL_DISPATCH_APP_ID: '1', PAWLOCAL_DISPATCH_INSTALLATION_ID: '2', PAWLOCAL_DISPATCH_REPOSITORY_ID: '3',
};
const permissions = { actions: 'write', metadata: 'read' };
const alert = overrides => ({
  status: 'firing', labels: { environment: 'development', service: 'pawlocal-api', alertname: 'pawlocal-development-search-detail-failure', release: 'a'.repeat(40), route: '/api/v1/places' },
  startsAt: '2026-10-23T09:00:00Z', endsAt: '0001-01-01T00:00:00Z', fingerprint: '1234567890abcdef',
  annotations: { summary: 'private customer data must never cross into GitHub' }, generatorURL: 'https://untrusted.example/?secret=value', ...overrides,
});
const payload = alerts => ({ status: 'firing', alerts: alerts ?? [alert()], truncatedAlerts: 0 });
function event(value = payload(), timestamp = String(TIME / 1000)) {
  const body = typeof value === 'string' ? value : JSON.stringify(value);
  return {
    requestContext: { http: { method: 'POST' } }, rawPath: '/', rawQueryString: '', isBase64Encoded: false, body,
    headers: { 'content-type': 'application/json', 'x-grafana-alerting-timestamp': timestamp, 'x-grafana-alerting-signature': createHmac('sha256', HMAC).update(`${timestamp}:${body}`).digest('hex') },
  };
}
function harness({ overrides = {}, environment = env, secret = HMAC, httpFailure = false } = {}) {
  const calls = []; const logs = []; const parameters = [];
  const http = async (url, options) => {
    calls.push({ url, options });
    if (httpFailure) throw new Error('never expose private token and response');
    const path = new URL(url).pathname;
    if (path in overrides) return overrides[path]();
    if (path === '/app') return Response.json({ id: 1, permissions });
    if (path === `/repos/${environment.PAWLOCAL_DISPATCH_REPOSITORY}/installation`) return Response.json({ id: 2, app_id: 1, account: { login: environment.PAWLOCAL_DISPATCH_REPOSITORY.split('/')[0] }, repository_selection: 'selected', permissions });
    if (path === '/app/installations/2/access_tokens') return Response.json({ token: 'private-installation-token', permissions, repository_selection: 'selected' }, { status: 201 });
    if (path === `/repos/${environment.PAWLOCAL_DISPATCH_REPOSITORY}/actions/workflows/incident-responder.yml/dispatches`) return new Response(null, { status: 204 });
    assert.fail(`Unexpected outbound request ${path}`);
  };
  return {
    calls, logs, parameters,
    handler: createHandler({ env: environment, now: () => TIME, http, log: value => logs.push(value), getParameter: async name => {
      parameters.push(name); return name.endsWith('/webhook-hmac') ? secret : KEY;
    } }),
  };
}

test('valid signed grouped firing/resolved reaches fixed main dispatch and strips private fields', async () => {
  const h = harness();
  const resolved = alert({ fingerprint: 'abcdef1234567890', status: 'resolved', endsAt: '2026-10-23T09:30:00Z' });
  const result = await h.handler(event(payload([alert(), resolved])));
  assert.equal(result.statusCode, 204);
  assert.deepEqual(h.parameters, ['/pawlocal/development/secrets/grafana/webhook-hmac', '/pawlocal/development/secrets/oncall/dispatch-app-private-key']);
  const outbound = JSON.parse(h.calls.at(-1).options.body);
  assert.equal(outbound.ref, 'main'); assert.equal(outbound.inputs.environment, 'development');
  assert.equal(outbound.inputs.schema_version, '1');
  const normalized = JSON.parse(outbound.inputs.alerts_json);
  assert.equal(normalized.length, 2); assert.equal(normalized[1].status, 'resolved');
  assert.equal(normalized[0].starts_at, '2026-10-23T09:00:00.000Z');
  assert.match(normalized[0].incident_key, /^[a-f0-9]{64}$/);
  assert.ok(!JSON.stringify(outbound).includes('private customer'));
  assert.ok(!JSON.stringify(outbound).includes('untrusted.example'));
  assert.equal(h.calls.at(-1).options.redirect, 'error');
  assert.deepEqual(JSON.parse(h.calls[2].options.body), { repository_ids: [3], permissions: { actions: 'write' } });
  const jwt = h.calls[0].options.headers.Authorization.slice(7).split('.');
  assert.deepEqual(JSON.parse(Buffer.from(jwt[0], 'base64url')), { alg: 'RS256', typ: 'JWT' });
  const claims = JSON.parse(Buffer.from(jwt[1], 'base64url'));
  assert.deepEqual(claims, { iat: TIME / 1000 - 60, exp: TIME / 1000 + 300, iss: '1' });
  assert.ok(verify('RSA-SHA256', Buffer.from(jwt.slice(0, 2).join('.')), publicKey, Buffer.from(jwt[2], 'base64url')));
  assert.ok(!JSON.stringify(h.logs).includes('private-installation-token'));
  assert.ok(!JSON.stringify(h.logs).includes(HMAC));
});

test('base64 verifies original bytes rather than parsed/reserialized JSON', async () => {
  const raw = JSON.stringify(payload(), null, 2);
  const value = event(raw); value.isBase64Encoded = true; value.body = Buffer.from(raw).toString('base64');
  assert.equal((await harness().handler(value)).statusCode, 204);
  value.body = Buffer.from(JSON.stringify(payload())).toString('base64');
  assert.equal((await harness().handler(value)).statusCode, 401);
});

for (const [name, mutate, expected] of [
  ['method', e => { e.requestContext.http.method = 'GET'; }, 405],
  ['path', e => { e.rawPath = '/other'; }, 404],
  ['query', e => { e.rawQueryString = 'secret=x'; }, 400],
  ['media type', e => { e.headers['content-type'] = 'text/plain'; }, 415],
  ['compression', e => { e.headers['content-encoding'] = 'gzip'; }, 415],
  ['signature', e => { e.headers['x-grafana-alerting-signature'] = 'f'.repeat(64); }, 401],
  ['missing signature', e => { delete e.headers['x-grafana-alerting-signature']; }, 401],
  ['duplicate header', e => { e.headers['X-Grafana-Alerting-Signature'] = e.headers['x-grafana-alerting-signature']; }, 400],
  ['invalid base64', e => { e.isBase64Encoded = true; e.body = '!malformed'; }, 400],
  ['invalid encoding type', e => { e.isBase64Encoded = 'true'; }, 400],
  ['incorrect length', e => { e.headers['content-length'] = '1'; }, 400],
]) test(`rejects ${name} without outbound dispatch`, async () => {
  const h = harness(); const e = event(); mutate(e);
  assert.equal((await h.handler(e)).statusCode, expected); assert.equal(h.calls.length, 0);
});

for (const offset of [-301, 31]) test(`rejects timestamp offset ${offset}`, async () => {
  const h = harness();
  assert.equal((await h.handler(event(payload(), String(TIME / 1000 + offset)))).statusCode, 401);
  assert.equal(h.parameters.length, 0);
});

for (const [name, value, expected] of [
  ['invalid JSON', '{oops', 400], ['too many alerts', payload(Array.from({ length: 21 }, () => alert())), 400],
  ['empty group', payload([]), 400], ['truncation', { ...payload(), truncatedAlerts: 1 }, 400],
  ['resolved group with firing alert', { ...payload(), status: 'resolved' }, 400],
  ['environment', payload([alert({ labels: { ...alert().labels, environment: 'production' } })]), 403],
  ['service', payload([alert({ labels: { ...alert().labels, service: 'unapproved' } })]), 403],
  ['alert name', payload([alert({ labels: { ...alert().labels, alertname: 'unapproved' } })]), 403],
  ['injected release', payload([alert({ labels: { ...alert().labels, release: '$(run-command)' } })]), 400],
  ['invalid start date', payload([alert({ startsAt: 'not-a-date' })]), 400],
  ['nonexistent calendar day', payload([alert({ startsAt: '2026-02-31T00:00:00Z' })]), 400],
  ['invalid resolution', payload([alert({ status: 'resolved', endsAt: '2026-10-22T00:00:00Z' })]), 400],
  ['duplicate group alert', payload([alert(), alert()]), 400],
]) test(`rejects ${name} before App key lookup`, async () => {
  const h = harness(); assert.equal((await h.handler(event(value))).statusCode, expected);
  assert.equal(h.calls.length, 0); assert.equal(h.parameters.length, 1);
});

test('enforces decoded byte limit before SSM or dispatch', async () => {
  const h = harness(); const e = event('x'.repeat(65_537));
  assert.equal((await h.handler(e)).statusCode, 413); assert.equal(h.parameters.length, 0);
});
test('unconfigured or weak secret fails closed', async () => {
  assert.equal((await harness({ environment: {} }).handler(event())).statusCode, 503);
  assert.equal((await harness({ secret: 'weak' }).handler(event())).statusCode, 503);
  assert.equal((await harness({ environment: { ...env, PAWLOCAL_DISPATCH_REPOSITORY_ID: '9007199254740993' } }).handler(event())).statusCode, 503);
});
test('request-wide deadline prevents dispatch after secret lookup', async () => {
  const controller = new AbortController(); const calls = [];
  const handler = createHandler({ env, now: () => TIME, deadlineSignal: () => controller.signal, log: () => {},
    getParameter: async () => { controller.abort(); return HMAC; },
    http: async (...args) => { calls.push(args); return new Response(null, { status: 204 }); },
  });
  assert.equal((await handler(event())).statusCode, 502); assert.equal(calls.length, 0);
});
for (const [name, overrides] of [
  ['broad App permissions', { '/app': () => Response.json({ id: 1, permissions: { ...permissions, contents: 'write' } }) }],
  ['different App ID', { '/app': () => Response.json({ id: 9, permissions }) }],
  ['wrong installation', { '/repos/alanlima/pawlocal/installation': () => Response.json({ id: 4, app_id: 1, account: { login: 'alanlima' }, repository_selection: 'selected', permissions }) }],
  ['broad installation', { '/repos/alanlima/pawlocal/installation': () => Response.json({ id: 2, app_id: 1, account: { login: 'alanlima' }, repository_selection: 'all', permissions }) }],
  ['broad token', { '/app/installations/2/access_tokens': () => Response.json({ token: 'secret', permissions: { ...permissions, pull_requests: 'write' }, repository_selection: 'selected' }, { status: 201 }) }],
]) test(`denies ${name}`, async () => {
  const h = harness({ overrides });
  assert.notEqual((await h.handler(event())).statusCode, 204);
  assert.ok(!h.calls.some(call => call.url.endsWith('/dispatches')));
});
for (const status of [200, 202, 301, 401, 429, 500]) test(`downstream HTTP ${status} is never successful acknowledgement`, async () => {
  const h = harness({ overrides: { '/repos/alanlima/pawlocal/actions/workflows/incident-responder.yml/dispatches': () => new Response('sensitive failure body', { status }) } });
  const result = await h.handler(event());
  assert.equal(result.statusCode, 502); assert.ok(!result.body.includes('sensitive'));
});
test('network uncertainty fails and does not leak dependency error contents', async () => {
  const h = harness({ httpFailure: true });
  const result = await h.handler(event()); assert.equal(result.statusCode, 502);
  assert.ok(!JSON.stringify(h.logs).includes('private token')); assert.ok(!result.body.includes('private token'));
});
test('in-window replays can dispatch twice; receiver does not claim persistent replay state', async () => {
  const h = harness(); assert.equal((await h.handler(event())).statusCode, 204);
  assert.equal((await h.handler(event())).statusCode, 204);
  const calls = h.calls.filter(call => call.url.endsWith('/dispatches'));
  assert.equal(calls.length, 2);
  assert.equal(JSON.parse(calls[0].options.body).inputs.alerts_json, JSON.parse(calls[1].options.body).inputs.alerts_json);
});


test('new API labels do not restrict configured alerts and raw route hints never leave receiver', async () => {
  for (const route of ['/api/v2/new-feature', '/api/v1/places/customer-id', 'https://private.example/?search=customer']) {
    const h = harness();
    assert.equal((await h.handler(event(payload([alert({ labels: { ...alert().labels, route } })])))).statusCode, 204);
    const dispatched = JSON.parse(h.calls.at(-1).options.body);
    assert.ok(!JSON.stringify(dispatched).includes(route));
    assert.ok(!Object.hasOwn(JSON.parse(dispatched.inputs.alerts_json)[0], 'route'));
  }
});

test('trusted repository and project come from deployment environment, never alert labels', async () => {
  const environment = { ...env, PAWLOCAL_PROJECT_NAME: 'petdemo', PAWLOCAL_DISPATCH_REPOSITORY: 'example/review-demo' };
  const h = harness({ environment });
  const labels = { ...alert().labels, repository: 'attacker/other' };
  assert.equal((await h.handler(event(payload([alert({ labels })])))).statusCode, 204);
  assert.deepEqual(h.parameters, ['/petdemo/development/secrets/grafana/webhook-hmac', '/petdemo/development/secrets/oncall/dispatch-app-private-key']);
  assert.match(h.calls.at(-1).url, /^https:\/\/api\.github\.com\/repos\/example\/review-demo\/actions\/workflows\/incident-responder\.yml\/dispatches$/);
  assert.ok(!JSON.stringify(JSON.parse(h.calls.at(-1).options.body)).includes('attacker/other'));
});

for (const repository of ['', 'https://github.com/example/repo', '../repo', 'example/..', 'example/repo/extra', 'example/repo?ref=main']) {
  test(`invalid configured repository ${repository} fails before secret retrieval`, async () => {
    const h = harness({ environment: { ...env, PAWLOCAL_DISPATCH_REPOSITORY: repository } });
    assert.equal((await h.handler(event())).statusCode, 503);
    assert.deepEqual(h.parameters, []);
    assert.deepEqual(h.calls, []);
  });
}
