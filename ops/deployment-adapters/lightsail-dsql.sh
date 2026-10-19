#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

die() { printf '%s\n' "$1" >&2; exit 2; }
need() { [[ -n "${!1:-}" ]] || die "Required deployment setting is missing: $1"; }

manifest_value() {
  python3 - "$1" "$2" <<'PY'
import json,sys
from pathlib import Path
value=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
item=value
for key in sys.argv[2].split('.'):
    item=item[key]
print(item)
PY
}

validate_manifest() {
  python3 ops/validate-release-metadata.py --manifest "$1"
}

publish_frontend() {
  local environment="$1" manifest="$2" archive="$3"
  [[ -f "$manifest" && -f "$archive" ]] || die "Release manifest and frontend archive must exist"
  validate_manifest "$manifest"
  local digest commit expected
  digest="sha256:$(sha256sum "$archive" | cut -d ' ' -f1)"
  expected="$(manifest_value "$manifest" frontend.artifact_digest)"
  commit="$(manifest_value "$manifest" commit)"
  [[ "$digest" == "$expected" ]] || die "Frontend archive digest does not match release manifest"
  local bucket distribution
  if [[ "$environment" == development ]]; then
    need PAWLOCAL_FRONTEND_BUCKET
    need PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID
    bucket="$PAWLOCAL_FRONTEND_BUCKET"
    distribution="$PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID"
  elif [[ "$environment" == production ]]; then
    need PAWLOCAL_FRONTEND_BUCKET
    need PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID
    bucket="$PAWLOCAL_FRONTEND_BUCKET"
    distribution="$PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID"
  else
    die "Environment must be development or production"
  fi
  local app_dir
  app_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/pawlocal-frontend.XXXXXX")"
  trap 'rm -rf "$app_dir"' EXIT
  tar -xzf "$archive" -C "$app_dir"
  aws s3 sync "$app_dir" "s3://${bucket}/" --delete --no-progress
  aws s3 cp "$archive" "s3://${bucket}/releases/${commit}/${digest#sha256:}.tar.gz" --no-progress
  aws cloudfront create-invalidation --distribution-id "$distribution" --paths '/*' >/dev/null
  printf 'Published %s frontend artifact %s\n' "$environment" "$digest"
}

verify_release() {
  local environment="$1" manifest="$2" evidence="$3"
  need PAWLOCAL_API_HEALTH_URL
  need PAWLOCAL_PUBLIC_BASE_URL
  [[ -f "$manifest" ]] || die "Release manifest must exist"
  validate_manifest "$manifest"
  local health_response
  health_response="$(mktemp "${RUNNER_TEMP:-/tmp}/pawlocal-health.XXXXXX")"
  trap 'rm -f "$health_response"' EXIT
  curl --fail --silent --show-error --location "$PAWLOCAL_API_HEALTH_URL" --output "$health_response"
  local running_image_digest
  running_image_digest="$(python3 - "$health_response" "$environment" "$manifest" <<'PY'
import json,sys
from pathlib import Path
health=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
environment=sys.argv[2]
manifest=json.loads(Path(sys.argv[3]).read_text(encoding='utf-8'))
expected=manifest['backend_image_digest']
if health.get('status') != 'ok' or health.get('environment') != environment:
    raise SystemExit('API health response does not match the selected environment')
if health.get('image_digest') != expected:
    raise SystemExit('API health response image digest does not match the selected release')
print(health['image_digest'])
PY
)"
  local places_url response
  places_url="$(python3 ops/api_smoke_url.py "$PAWLOCAL_API_HEALTH_URL")"
  response="$(mktemp "${RUNNER_TEMP:-/tmp}/pawlocal-api-smoke.XXXXXX")"
  trap 'rm -f "$response"' EXIT
  curl --fail --silent --show-error --location --header 'Cache-Control: no-cache' "$places_url" --output "$response"
  python3 - "$response" <<'PY'
import json,sys
from pathlib import Path
page=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
if not isinstance(page,dict) or not isinstance(page.get('items'),list):
    raise SystemExit('Public places query did not return a valid place page')
if not isinstance(page.get('total'),int) or not isinstance(page.get('page'),int):
    raise SystemExit('Public places query returned invalid pagination')
PY
  curl --fail --silent --show-error --location "$PAWLOCAL_PUBLIC_BASE_URL" | grep -qi '<html'
  mkdir -p "$(dirname "$evidence")"
  python3 - "$environment" "$manifest" "$evidence" "$running_image_digest" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
environment,manifest_path,evidence_path=sys.argv[1:]
manifest=json.loads(Path(manifest_path).read_text(encoding='utf-8'))
frontend=manifest.get('frontend',{})
Path(evidence_path).write_text(json.dumps({
  'schema_version':1,'environment':environment,'commit':manifest['commit'],
  'backend_image_digest':manifest['backend_image_digest'],
  'running_image_digest':sys.argv[4],
  'frontend_artifact_digest':frontend['artifact_digest'],
  'database_provider':'aurora_dsql','migration_runner':'dsql_baseline',
  'migration_id':manifest['migration_chains']['aurora_dsql']['migration_id'],
  'telemetry_enabled':False,
  'public_endpoint_health':{'frontend':True,'api':True},
  'database_query_smoke':{'route':'/api/v1/places','result':'valid_place_page'},
  'verified_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
},indent=2)+'\n',encoding='utf-8')
PY
  python3 ops/validate-release-metadata.py --manifest "$manifest" --evidence "$evidence" --environment "$environment" --database-provider aurora_dsql
}

operation="${1:-}"
shift || true
case "$operation" in
  deploy)
    [[ $# == 6 && "$1" == --environment && "$3" == --manifest && "$5" == --frontend-archive ]] || die "Usage: $0 deploy --environment <environment> --manifest <path> --frontend-archive <path>"
    publish_frontend "$2" "$4" "$6"
    ;;
  verify)
    [[ $# == 6 && "$1" == --environment && "$3" == --manifest && "$5" == --evidence ]] || die "Usage: $0 verify --environment <environment> --manifest <path> --evidence <path>"
    verify_release "$2" "$4" "$6"
    ;;
  seed)
    die "Seeding is unavailable until a container-compatible, audited seed mechanism is implemented"
    ;;
  *) die "Operation must be deploy, verify, or seed" ;;
esac
