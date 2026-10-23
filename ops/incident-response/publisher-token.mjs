// Trusted job only; no candidate checkout/import/command is executed here.
import { createPrivateKey, sign } from 'node:crypto';
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';

const allowed = { contents: 'write', pull_requests: 'write', issues: 'write' };
const repositoryId = 1423024931;
const repository = 'alanlima/pawlocal';
const environment = process.env;
const deadline = Number(environment.INCIDENT_DEADLINE) * 1000;
const maximumLifetime = environment.PAWLOCAL_CREDENTIAL_PHASE === 'merge' ? 3600000 : 1200000;
function narrow(permissions) {
  return permissions && typeof permissions === 'object' &&
    Object.keys(allowed).every(key => permissions[key] === allowed[key]) &&
    Object.entries(permissions).every(([key, value]) => allowed[key] === value || (key === 'metadata' && value === 'read'));
}
async function main() {
  if (environment.GITHUB_REPOSITORY !== repository || environment.GITHUB_REF !== 'refs/heads/main' || environment.GITHUB_RUN_ATTEMPT !== '1' ||
      !Number.isSafeInteger(deadline) || deadline <= Date.now() || deadline > Date.now() + maximumLifetime) throw new Error('Trusted phase deadline required');
  const appId = environment.PAWLOCAL_PUBLISHER_APP_ID;
  const installationId = environment.PAWLOCAL_PUBLISHER_INSTALLATION_ID;
  if (![appId, installationId].every(value => typeof value === 'string' && /^[1-9][0-9]{0,15}$/.test(value) && Number.isSafeInteger(Number(value)))) throw new Error('Public publisher identities unconfigured');
  const key = createPrivateKey(environment.PAWLOCAL_ONCALL_PUBLISHER_APP_PRIVATE_KEY || '');
  if (key.asymmetricKeyType !== 'rsa' || key.asymmetricKeyDetails.modulusLength < 2048) throw new Error('Publisher RSA key invalid');
  const seconds = Math.floor(Date.now() / 1000);
  const encode = value => Buffer.from(JSON.stringify(value)).toString('base64url');
  const unsigned = `${encode({ alg: 'RS256', typ: 'JWT' })}.${encode({ iat: seconds - 60, exp: seconds + 300, iss: appId })}`;
  const jwt = `${unsigned}.${sign('RSA-SHA256', Buffer.from(unsigned), key).toString('base64url')}`;
  async function request(path, body) {
    if (Date.now() >= deadline) throw new Error('Admission expired');
    const response = await fetch(`https://api.github.com${path}`, {
      method: body ? 'POST' : 'GET', redirect: 'error', signal: AbortSignal.timeout(Math.min(10000, deadline - Date.now())),
      headers: { Authorization: `Bearer ${jwt}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) throw new Error('Publisher authorization failed');
    const reader = response.body.getReader();
    let chunks = [], length = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.length;
      if (length > 32768) { await reader.cancel(); throw new Error('Publisher response bound'); }
      chunks.push(Buffer.from(value));
    }
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  }
  const app = await request('/app');
  if (String(app.id) !== appId || !narrow(app.permissions)) throw new Error('Publisher App identity/permission mismatch');
  const installation = await request(`/repos/${repository}/installation`);
  if (String(installation.id) !== installationId || String(installation.app_id) !== appId || installation.account?.login !== 'alanlima' || installation.repository_selection !== 'selected' || !narrow(installation.permissions)) throw new Error('Publisher installation mismatch');
  const token = await request(`/app/installations/${installationId}/access_tokens`, { repository_ids: [repositoryId], permissions: allowed });
  if (!narrow(token.permissions) || token.repository_selection !== 'selected' || typeof token.token !== 'string' || token.token.length < 20 || token.token.length > 1024) throw new Error('Publisher token scope mismatch');
  writeFileSync(join(environment.RUNNER_TEMP, 'oncall-publisher-token.json'), JSON.stringify({ token: token.token }), { mode: 0o600, flag: 'wx' });
}
main().catch(() => { console.error('Publisher credential admission denied'); process.exitCode = 1; });
