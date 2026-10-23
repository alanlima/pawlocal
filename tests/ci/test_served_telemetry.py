"""Exercise served-mode verification against browser request/route fixtures."""
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ServedTelemetryTests(unittest.TestCase):
    def test_observed_export_required_and_wrong_or_disabled_export_denied(self):
        script = r"""
import { verifyServedTelemetry } from MODULE;
const collector = 'https://faro.grafana.net/collect/public';
const commit = 'a'.repeat(40);
const config = {PAWLOCAL_PUBLIC_BASE_URL:'https://pawlocal-dev.example.test',VITE_TELEMETRY_ENABLED:'true',VITE_FARO_COLLECTOR_URL:collector};
async function exercise(mode, requests, shouldPass) {
  let handler, closed=false;
  const context = {
    route: async (_, callback) => {handler=callback},
    close: async () => {closed=true},
    newPage: async () => ({goto:async()=>{
      for(const [url,version=commit] of requests) await handler({
        request:()=>({url:()=>url,method:()=> 'POST',postDataJSON:()=>({meta:{app:{name:'pawlocal-frontend',environment:'development',version}}})}),
        fulfill:async()=>{},continue:async()=>{},
      });
    },waitForTimeout:async()=>{}}),
  };
  let passed=true;
  try {await verifyServedTelemetry({newContext:async()=>context},{...config,VITE_TELEMETRY_ENABLED:mode},'development',commit)} catch {passed=false}
  if(passed!==shouldPass || !closed) throw new Error('verification contract failed');
}
await exercise('true',[[collector]],true);
await exercise('true',[],false);
await exercise('true',[[collector,'b'.repeat(40)]],false);
await exercise('true',[['https://other.grafana.net/collect/foreign']],false);
await exercise('false',[],true);
await exercise('false',[[collector]],false);
await exercise('true',[['https://otlp.grafana.net/v1/traces']],false);
""".replace('MODULE', json.dumps((ROOT / 'ops/configuration/verify-served-telemetry.mjs').as_uri()))
        result = subprocess.run(['node', '--input-type=module', '-e', script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
