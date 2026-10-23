import { createHash, createHmac, createPrivateKey, sign, timingSafeEqual } from 'node:crypto';

const WORKFLOW = 'incident-responder.yml';
const REF = 'main';
const API = 'https://api.github.com';
const MAX_BODY = 65_536;
const MAX_ALERTS = 20;
const MAX_RESPONSE = 32_768;
const SIGNATURE_HEADER = 'x-grafana-alerting-signature';
const TIMESTAMP_HEADER = 'x-grafana-alerting-timestamp';
const STATUS = new Set(['firing', 'resolved']);
const ISO_DATE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/;

class Rejection extends Error {
  constructor(status, code) { super(code); this.status = status; this.code = code; }
}
const reject = (status, code) => { throw new Rejection(status, code); };
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const bounded = (value, max) => typeof value === 'string' && value.length > 0 && value.length <= max;

function date(value, zeroAllowed = false) {
  if (!bounded(value, 40) || !ISO_DATE.test(value)) reject(400, 'invalid_date');
  const time = Date.parse(value);
  if (!Number.isFinite(time) || (!zeroAllowed && time < 0)) reject(400, 'invalid_date');
  const [year, month, day] = value.slice(0, 10).split('-').map(Number);
  const maxDay = new Date(Date.UTC(year < 100 ? 2000 + year : year, month, 0)).getUTCDate();
  if (month < 1 || month > 12 || day < 1 || day > maxDay) reject(400, 'invalid_date');
  return new Date(time).toISOString();
}

export function configuration(env = process.env) {
  const environment = env.PAWLOCAL_ONCALL_ENVIRONMENT;
  const project = env.PAWLOCAL_PROJECT_NAME;
  const repository = env.PAWLOCAL_DISPATCH_REPOSITORY;
  if (!/^[A-Za-z0-9._-]{1,8}$/.test(project ?? '') || !/^[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9_.-]{1,100}$/.test(repository ?? '') || ['.', '..'].includes(repository.split('/')[1])) reject(503, 'unconfigured');
  if (!['development', 'production'].includes(environment)) reject(503, 'unconfigured');
  const parseList = (value, pattern) => {
    let list;
    try { list = JSON.parse(value); } catch { reject(503, 'unconfigured'); }
    if (!Array.isArray(list) || list.length < 1 || list.length > 10 ||
        !list.every(item => bounded(item, 100) && pattern.test(item)) || new Set(list).size !== list.length) {
      reject(503, 'unconfigured');
    }
    return new Set(list);
  };
  if (!/^[1-9][0-9]{0,15}$/.test(env.PAWLOCAL_DISPATCH_APP_ID ?? '') ||
      !/^[1-9][0-9]{0,15}$/.test(env.PAWLOCAL_DISPATCH_INSTALLATION_ID ?? '') ||
      !/^[1-9][0-9]{0,15}$/.test(env.PAWLOCAL_DISPATCH_REPOSITORY_ID ?? '') ||
      !Number.isSafeInteger(Number(env.PAWLOCAL_DISPATCH_REPOSITORY_ID)) ||
      Number(env.PAWLOCAL_DISPATCH_REPOSITORY_ID) < 1) reject(503, 'unconfigured');
  return {
    environment, project, repository, repositoryOwner: repository.split('/')[0],
    services: parseList(env.PAWLOCAL_ONCALL_ALLOWED_SERVICES, /^[a-z][a-z0-9-]*$/),
    alerts: parseList(env.PAWLOCAL_ONCALL_ALLOWED_ALERTS, /^[a-z][a-z0-9-]*$/),
    appId: env.PAWLOCAL_DISPATCH_APP_ID,
    installationId: env.PAWLOCAL_DISPATCH_INSTALLATION_ID,
    repositoryId: env.PAWLOCAL_DISPATCH_REPOSITORY_ID,
    hmacParameter: `/${project}/${environment}/secrets/grafana/webhook-hmac`,
    keyParameter: `/${project}/${environment}/secrets/oncall/dispatch-app-private-key`,
  };
}

export function rawRequest(event, now) {
  if (event?.requestContext?.http?.method !== 'POST') reject(405, 'method_not_allowed');
  if (event.rawPath !== '/') reject(404, 'not_found');
  if (event.rawQueryString) reject(400, 'query_not_supported');
  if (!record(event.headers) || !bounded(event.body, MAX_BODY * 2)) reject(400, 'invalid_request');
  const headers = new Map();
  for (const [name, value] of Object.entries(event.headers)) {
    const key = name.toLowerCase();
    if (headers.has(key) || typeof value !== 'string') reject(400, 'invalid_headers');
    headers.set(key, value);
  }
  if (!/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(headers.get('content-type') ?? '')) reject(415, 'unsupported_media_type');
  if (headers.has('content-encoding')) reject(415, 'compressed_body_not_supported');
  const timestamp = headers.get(TIMESTAMP_HEADER);
  const signature = headers.get(SIGNATURE_HEADER);
  if (!/^\d{1,12}$/.test(timestamp ?? '') || !/^[a-f0-9]{64}$/.test(signature ?? '')) reject(401, 'invalid_signature');
  const age = Math.floor(now / 1000) - Number(timestamp);
  if (age > 300 || age < -30) reject(401, 'expired_signature');
  let bytes;
  if (event.isBase64Encoded === true) {
    if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(event.body)) reject(400, 'invalid_base64');
    bytes = Buffer.from(event.body, 'base64');
  } else if (event.isBase64Encoded === false || event.isBase64Encoded === undefined) {
    bytes = Buffer.from(event.body, 'utf8');
  } else reject(400, 'invalid_request');
  if (bytes.length > MAX_BODY) reject(413, 'payload_too_large');
  if (headers.has('content-length') && (!/^\d+$/.test(headers.get('content-length')) || Number(headers.get('content-length')) !== bytes.length)) {
    reject(400, 'invalid_length');
  }
  return { bytes, timestamp, signature };
}

export function verifySignature(request, secret) {
  if (!bounded(secret, 4096) || Buffer.byteLength(secret) < 32) reject(503, 'unconfigured_secret');
  const expected = createHmac('sha256', secret).update(request.timestamp).update(':').update(request.bytes).digest();
  if (!timingSafeEqual(expected, Buffer.from(request.signature, 'hex'))) reject(401, 'invalid_signature');
}

export function normalize(bytes, config) {
  let payload;
  try { payload = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); } catch { reject(400, 'invalid_json'); }
  if (!record(payload) || !STATUS.has(payload.status) || !Array.isArray(payload.alerts) ||
      payload.alerts.length < 1 || payload.alerts.length > MAX_ALERTS ||
      (payload.truncatedAlerts !== undefined && payload.truncatedAlerts !== 0)) reject(400, 'invalid_payload');
  if ((payload.status === 'resolved' && payload.alerts.some(alert => alert?.status !== 'resolved')) ||
      (payload.status === 'firing' && !payload.alerts.some(alert => alert?.status === 'firing'))) reject(400, 'inconsistent_group_status');
  const seen = new Set();
  return payload.alerts.map(alert => {
    if (!record(alert) || !STATUS.has(alert.status) || !record(alert.labels) ||
        Object.keys(alert.labels).length > 32 || !/^[a-f0-9]{16,64}$/.test(alert.fingerprint ?? '')) reject(400, 'invalid_alert');
    if (!Object.entries(alert.labels).every(([key, value]) => bounded(key, 64) && bounded(value, 256))) reject(400, 'invalid_labels');
    const { environment, service, alertname, release } = alert.labels;
    if (environment !== config.environment || !config.services.has(service) || !config.alerts.has(alertname)) reject(403, 'alert_not_allowed');
    if (release !== undefined && !/^(?:[a-f0-9]{40}|sha256:[a-f0-9]{64})$/.test(release)) reject(400, 'invalid_release');
    const startsAt = date(alert.startsAt);
    const endsAt = date(alert.endsAt, true);
    if (alert.status === 'resolved' && Date.parse(endsAt) < Date.parse(startsAt)) reject(400, 'invalid_resolution');
    const incidentKey = createHash('sha256').update(JSON.stringify([environment, alert.fingerprint, startsAt])).digest('hex');
    if (seen.has(incidentKey)) reject(400, 'duplicate_group_entry');
    seen.add(incidentKey);
    // Only these bounded fields cross into GitHub. Never forward annotations,
    // messages, URLs, values, query strings or arbitrary customer labels.
    return {
      incident_key: incidentKey, fingerprint: alert.fingerprint, status: alert.status,
      starts_at: startsAt, ends_at: endsAt, environment, service, alert_name: alertname,
      ...(release === undefined ? {} : { release }),
    };
  });
}

async function responseJson(response) {
  const reader = response.body?.getReader();
  if (!reader) reject(502, 'github_invalid_response');
  const chunks = []; let size = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > MAX_RESPONSE) { await reader.cancel(); reject(502, 'github_invalid_response'); }
      chunks.push(value);
    }
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch { reject(502, 'github_invalid_response'); }
}

function dispatchOnly(permissions) {
  return record(permissions) && permissions.actions === 'write' &&
    Object.entries(permissions).every(([key, value]) => key === 'actions' || (key === 'metadata' && value === 'read'));
}

export async function dispatch(alerts, config, privateKey, now, http = fetch, signal) {
  let key;
  try { key = createPrivateKey(privateKey); } catch { reject(503, 'invalid_app_key'); }
  if (key.asymmetricKeyType !== 'rsa' || key.asymmetricKeyDetails.modulusLength < 2048) reject(503, 'invalid_app_key');
  const encode = value => Buffer.from(JSON.stringify(value)).toString('base64url');
  const unsigned = `${encode({ alg: 'RS256', typ: 'JWT' })}.${encode({ iat: Math.floor(now / 1000) - 60, exp: Math.floor(now / 1000) + 300, iss: config.appId })}`;
  const jwt = `${unsigned}.${sign('RSA-SHA256', Buffer.from(unsigned), key).toString('base64url')}`;
  const request = async (path, token, method = 'GET', body) => {
    signal?.throwIfAborted();
    const response = await http(`${API}${path}`, {
      method, redirect: 'error', signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(2000)]) : AbortSignal.timeout(2000),
      headers: { Accept: 'application/vnd.github+json', Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', 'User-Agent': 'pawlocal-incident-receiver', 'X-GitHub-Api-Version': '2022-11-28' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    signal?.throwIfAborted();
    return response;
  };
  const appResponse = await request('/app', jwt);
  if (appResponse.status !== 200) reject(502, 'github_app_unavailable');
  const app = await responseJson(appResponse);
  if (String(app.id) !== config.appId || !dispatchOnly(app.permissions)) reject(503, 'app_permissions_not_allowed');
  const installationResponse = await request(`/repos/${config.repository}/installation`, jwt);
  if (installationResponse.status !== 200) reject(502, 'github_installation_unavailable');
  const installation = await responseJson(installationResponse);
  if (String(installation.id) !== config.installationId || String(installation.app_id) !== config.appId ||
      installation.account?.login?.toLowerCase() !== config.repositoryOwner.toLowerCase() || installation.repository_selection !== 'selected' ||
      !dispatchOnly(installation.permissions)) reject(503, 'installation_not_allowed');
  const tokenResponse = await request(`/app/installations/${config.installationId}/access_tokens`, jwt, 'POST', {
    repository_ids: [Number(config.repositoryId)], permissions: { actions: 'write' },
  });
  if (tokenResponse.status !== 201) reject(502, 'github_token_unavailable');
  const token = await responseJson(tokenResponse);
  if (!bounded(token.token, 1024) || !dispatchOnly(token.permissions) || token.repository_selection !== 'selected') reject(502, 'github_invalid_token');
  const response = await request(`/repos/${config.repository}/actions/workflows/${WORKFLOW}/dispatches`, token.token, 'POST', {
    ref: REF, inputs: { environment: config.environment, schema_version: '1', alerts_json: JSON.stringify(alerts) },
  });
  if (response.status !== 204) reject(502, 'github_dispatch_failed');
}

async function parameter(name, { signal } = {}) {
  const { SSMClient, GetParameterCommand } = await import('@aws-sdk/client-ssm');
  const client = new SSMClient({ maxAttempts: 1 });
  try {
    const result = await client.send(new GetParameterCommand({ Name: name, WithDecryption: true }), { abortSignal: signal ? AbortSignal.any([signal, AbortSignal.timeout(2000)]) : AbortSignal.timeout(2000) });
    if (result.Parameter?.Type !== 'SecureString' || !bounded(result.Parameter.Value, 16_384)) reject(503, 'unconfigured_secret');
    return result.Parameter.Value;
  } finally { client.destroy(); }
}

export function createHandler({ env = process.env, now = Date.now, getParameter = parameter, http = fetch, log = message => console.info(message), deadlineSignal = () => AbortSignal.timeout(15_000) } = {}) {
  return async event => {
    try {
      const config = configuration(env);
      // One request-wide bound covers both SSM reads and every GitHub request,
      // in addition to two-second per-request limits and Lambda's 20s timeout.
      const signal = deadlineSignal();
      const time = now();
      const request = rawRequest(event, time);
      verifySignature(request, await getParameter(config.hmacParameter, { signal }));
      signal.throwIfAborted();
      const alerts = normalize(request.bytes, config);
      const key = await getParameter(config.keyParameter, { signal });
      signal.throwIfAborted();
      await dispatch(alerts, config, key, time, http, signal);
      log(JSON.stringify({ event: 'oncall_receiver', outcome: 'dispatch_accepted', alerts: alerts.length }));
      return { statusCode: 204, body: '' };
    } catch (error) {
      const status = error instanceof Rejection ? error.status : 502;
      const code = error instanceof Rejection ? error.code : 'dependency_unavailable';
      log(JSON.stringify({ event: 'oncall_receiver', outcome: code }));
      return { statusCode: status, headers: { 'content-type': 'application/json' }, body: JSON.stringify({ error: code }) };
    }
  };
}

export const handler = createHandler();
