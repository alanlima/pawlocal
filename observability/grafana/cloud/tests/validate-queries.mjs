import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import vm from 'node:vm';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const prefix = process.argv[2];
assert(prefix, 'Pass the isolated install prefix for @prometheus-io/lezer-promql@0.315.1');
const { parser } = require(resolve(prefix, 'node_modules/@prometheus-io/lezer-promql'));
let queries = 0;
function promql(expression) {
  expression = expression.replaceAll('$environment', 'development').replaceAll('$service', 'pawlocal-api').replaceAll('$release', '.+');
  const tree = parser.parse(expression);
  tree.iterate({ enter(node) { assert(!node.type.isError, `Invalid PromQL: ${expression}`); } });
  queries++;
}
for (const name of readdirSync(resolve(root, 'dashboards'))) {
  const dashboard = JSON.parse(readFileSync(resolve(root, 'dashboards', name), 'utf8'));
  for (const panel of dashboard.panels) {
    if (panel.datasource.type === 'prometheus') for (const target of panel.targets) promql(target.expr);
  }
}
const ruleQuery = JSON.parse(execFileSync('python', ['-c', 'import json;from experience import alert_rule;print(json.dumps(alert_rule("metrics")["data"][0]["model"]["expr"]))'], { cwd: root, encoding: 'utf8' }));
promql(ruleQuery);

const source = readFileSync(resolve(root, 'search-detail.js'), 'utf8')
  .replace("import http from 'k6/http';", '')
  .replace("import { check, fail } from 'k6';", '')
  .replace('__API_BASE_JSON__', JSON.stringify('https://approved-api.test.org/api/v1'))
  .replace('export const options', 'globalThis.options')
  .replace('export default function ()', 'globalThis.journey = function ()');
const id = '11111111-1111-4111-8111-111111111111';
function execute(responses) {
  const calls = [];
  const context = vm.createContext({
    http: { get(url, options) { calls.push({ url, options }); const value = responses.shift(); return { status: value.status ?? 200, body: JSON.stringify(value.body), json() { return value.body; } }; } },
    check(value, checks) { return Object.values(checks).every(test => test(value)); },
    fail(message) { throw new Error(message); },
  });
  new vm.Script(source).runInContext(context);
  context.journey();
  return { context, calls };
}
const normal = execute([{ body: { items: [{ id }] } }, { body: { id } }]);
assert.equal(normal.calls.length, 2);
assert.equal(normal.calls[0].url, 'https://approved-api.test.org/api/v1/places?page_size=1');
assert.equal(normal.calls[1].options.tags.name, '/api/v1/places/{place_id}');
assert(!normal.context.options.systemTags.includes('url'));
assert.throws(() => execute([{ body: { items: [] } }]));
assert.throws(() => execute([{ status: 500, body: 'upstream-data-must-not-be-logged' }]));
assert.throws(() => execute([{ body: { items: [{ id: 'https://foreign.test/' }] } }]));
assert.throws(() => execute([{ body: { items: [{ id }] } }, { body: { id: 'different' } }]));
console.log(`Parsed ${queries} PromQL queries; synthetic JS execution and bounded-route/privacy cases passed.`);
