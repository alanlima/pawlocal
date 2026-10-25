import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';

const fixture = new URL('./fixtures/codex-action-c05cfd7/', import.meta.url);
const provenance = JSON.parse(readFileSync(new URL('provenance.json', fixture), 'utf8'));
const validator = readFileSync(new URL('checkActorPermissions.ts', fixture), 'utf8');
const workflow = readFileSync(new URL('../../.github/workflows/incident-responder.yml', import.meta.url), 'utf8').replaceAll('\r\n', '\n');
// Execute the pinned validator itself. Imported infrastructure is stubbed so an
// unexpected permission lookup fails instead of contacting GitHub.
const code = stripTypeScriptTypes(validator).replace(/^import .*;$/gm, '').replace('export async function', 'async function');
const validate = vm.runInNewContext(`${code}\nensureActorHasWriteAccess`, {
  core: { info() {} }, retry: {}, process: { env: {} },
  Octokit: { plugin: () => class { constructor() { throw new Error('unexpected network lookup'); } } },
});
const job = name => workflow.split(`\n  ${name}:\n`)[1].split(/\n  [a-z][\w-]*:\n/)[0];
const expression = (text, key) => text.match(new RegExp(`^\\s+${key}: (.+)$`, 'm'))[1];
function evaluate(value, mode, actor, configuredActor = 'dispatcher[bot]', candidate = 'a'.repeat(64)) {
  return vm.runInNewContext(value.replace(/^\$\{\{ | \}\}$/g, ''), {
    needs: { preflight: { outputs: { enforce_guards: mode, admitted: 'true' } }, fixer: { outputs: { candidate_sha256: candidate }, result: 'failure' }, checks: { result: 'failure' }, reviewer: { result: 'failure' } },
    github: { actor, ref: 'refs/heads/main', run_attempt: 1 },
    vars: { PAWLOCAL_ONCALL_DISPATCH_ACTOR: configuredActor }, always: () => true,
    endsWith: (value, suffix) => value.toLowerCase().endsWith(suffix.toLowerCase()),
  });
}
function options(name, mode, actor, configuredActor) {
  return { actor, repository: 'alanlima/pawlocal',
    allowBotUsers: evaluate(expression(job(name), 'allow-bot-users'), mode, actor, configuredActor),
    allowUsers: evaluate(expression(job(name), 'allow-users'), mode, actor, configuredActor) };
}

test('fixture is exact pinned source and workflow uses that action revision', () => {
  for (const [file, metadata] of Object.entries(provenance.files)) {
    const bytes = readFileSync(new URL(file, fixture));
    assert.equal(createHash('sha256').update(bytes).digest('hex'), metadata.sha256);
    assert.equal(createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex'), metadata.git_blob);
  }
  for (const name of ['fixer', 'reviewer']) assert.ok(job(name).includes(`openai/codex-action@${provenance.commit}`));
});

test('pinned action rejects the old bot wildcard even with a valid user override', async () => {
  const result = await validate({ actor: 'dispatcher[bot]', repository: 'alanlima/pawlocal', allowBotUsers: '*', allowUsers: 'dispatcher[bot]' });
  assert.equal(result.status, 'rejected');
  assert.match(result.reason, /allow-bot-users does not support/);
});

for (const name of ['fixer', 'reviewer']) {
  test(`${name} preserves configured bot admission and permission fallback in both modes`, async () => {
    for (const mode of ['', 'false', 'true']) {
      assert.equal((await validate(options(name, mode, 'dispatcher[bot]'))).status, 'approved');
      const unconfigured = options(name, mode, 'dispatcher[bot]', '');
      assert.equal(unconfigured.allowUsers, '');
      assert.equal((await validate(unconfigured)).status, 'rejected');
      for (const actor of ['another-app[bot]', 'Another-App[BOT]']) {
        const input = options(name, mode, actor);
        assert.equal(input.allowBotUsers, 'dispatcher[bot]');
        assert.equal(input.allowUsers, '');
        assert.equal((await validate(input)).status, 'rejected');
        for (const [permission, expected] of [['read', 'rejected'], ['write', 'approved']]) {
          assert.equal((await validate({ ...input, token: 'fixture', octokit: { repos: { getCollaboratorPermissionLevel: async () => ({ data: { permission } }) } } })).status, expected);
        }
      }
    }
  });
  test(`${name} disabled mode admits actual human without permission lookup`, async () => {
    for (const mode of ['', 'false']) {
      const input = options(name, mode, 'ordinary-user');
      assert.equal(input.allowBotUsers, 'dispatcher[bot]');
      assert.equal(input.allowUsers, 'ordinary-user');
      assert.equal((await validate(input)).status, 'approved');
    }
  });
  test(`${name} enabled mode preserves configured bot and real human permissions`, async () => {
    assert.equal((await validate(options(name, 'true', 'dispatcher[bot]'))).status, 'approved');
    for (const configured of ['dispatcher[bot]', '']) {
      assert.equal((await validate(options(name, 'true', 'other-app[bot]', configured))).status, 'rejected');
    }
    for (const [permission, expected] of [['read', 'rejected'], ['write', 'approved']]) {
      const input = options(name, 'true', 'ordinary-user');
      assert.equal(input.allowUsers, '');
      assert.equal((await validate({ ...input, token: 'fixture', octokit: { repos: { getCollaboratorPermissionLevel: async () => ({ data: { permission } }) } } })).status, expected);
    }
  });
}

test('missing fixer candidate skips publication while finalizer remains eligible', () => {
  for (const mode of ['true', 'false']) {
    assert.equal(evaluate(expression(job('publisher'), 'if'), mode, 'dispatcher[bot]', undefined, ''), false);
    assert.equal(evaluate(expression(job('finalize'), 'if'), mode, 'dispatcher[bot]'), true);
  }
  // Existing candidate permits disabled-policy publication despite failed
  // checks/review jobs; candidate availability is an operational prerequisite.
  assert.equal(evaluate(expression(job('publisher'), 'if'), 'false', 'dispatcher[bot]'), true);
});
