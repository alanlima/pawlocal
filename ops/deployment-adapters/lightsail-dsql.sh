#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

die() { printf '%s\n' "$1" >&2; exit 2; }
_PAWLOCAL_TEMP_DIR=""
_PAWLOCAL_DOCKER_LOGGED_IN=false

cleanup() {
  if [[ "$_PAWLOCAL_DOCKER_LOGGED_IN" == true ]]; then
    docker logout ghcr.io >/dev/null 2>&1 || true
  fi
  if [[ -n "$_PAWLOCAL_TEMP_DIR" ]]; then rm -rf "$_PAWLOCAL_TEMP_DIR"; fi
}
trap cleanup EXIT

need() {
  local name="$1"
  [[ -n "${!name:-}" ]] || die "Required deployment setting is missing: ${name}"
}

read_manifest() {
  python3 - "$1" <<'PY'
import json, re, sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if value.get("telemetry_enabled") is not False:
    raise SystemExit("The selected release must keep telemetry disabled")
if value.get("schema_version") != 2:
    raise SystemExit("Unsupported release manifest schema")
if not re.fullmatch(r"[0-9a-f]{40}", value.get("commit", "")):
    raise SystemExit("Release commit must be a full SHA")
image = value.get("backend_image", "")
if not re.fullmatch(r"ghcr\.io/[a-z0-9_.-]+/pawlocal-api@sha256:[a-f0-9]{64}", image):
    raise SystemExit("Backend image must be the expected digest-pinned GHCR image")
chain = value.get("migration_chains", {}).get("aurora_dsql")
if not isinstance(chain, dict) or chain.get("runner") != "dsql_baseline" or chain.get("migration_id") != "dsql_0001_initial":
    raise SystemExit("Aurora DSQL migration metadata is missing or unsupported")
print("\t".join([value["commit"], image, value["backend_image_digest"], chain["runner"], chain["migration_id"]]))
PY
}

validate_environment() {
  case "$1" in
    development)
      need PAWLOCAL_DEPLOY_HOST
      need PAWLOCAL_FRONTEND_BUCKET
      need PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID
      need PAWLOCAL_DSQL_ENDPOINT
      need PAWLOCAL_DSQL_DATABASE_ROLE
      need PAWLOCAL_COGNITO_ISSUER
      need PAWLOCAL_COGNITO_APP_CLIENT_ID
      need PAWLOCAL_DEPLOY_SSH_PRIVATE_KEY
      need PAWLOCAL_DEPLOY_KNOWN_HOSTS
      ;;
    production)
      need PAWLOCAL_DEPLOY_HOST
      need PAWLOCAL_FRONTEND_BUCKET
      need PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID
      need PAWLOCAL_DSQL_ENDPOINT
      need PAWLOCAL_DSQL_DATABASE_ROLE
      need PAWLOCAL_COGNITO_ISSUER
      need PAWLOCAL_COGNITO_APP_CLIENT_ID
      need PAWLOCAL_DEPLOY_SSH_PRIVATE_KEY
      need PAWLOCAL_DEPLOY_KNOWN_HOSTS
      ;;
    *) die "Environment must be development or production" ;;
  esac
  need AWS_REGION
  need PAWLOCAL_DATABASE_PROVIDER
  [[ "$PAWLOCAL_DATABASE_PROVIDER" == aurora_dsql ]] || die "This adapter only accepts the approved aurora_dsql provider"
  [[ "$AWS_REGION" =~ ^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$ ]] || die "AWS_REGION is not a supported region name"
  [[ "$PAWLOCAL_DSQL_ENDPOINT" =~ ^[a-zA-Z0-9.-]+\.dsql\.${AWS_REGION}\.on\.aws$ ]] || die "PAWLOCAL_DSQL_ENDPOINT does not match the configured AWS region"
  [[ "$PAWLOCAL_DSQL_DATABASE_ROLE" =~ ^[a-zA-Z_][a-zA-Z0-9_]{0,62}$ ]] || die "PAWLOCAL_DSQL_DATABASE_ROLE is invalid"
  [[ "$PAWLOCAL_COGNITO_ISSUER" =~ ^https://cognito-idp\.${AWS_REGION}\.amazonaws\.com/${AWS_REGION}_[A-Za-z0-9]+$ ]] || die "PAWLOCAL_COGNITO_ISSUER does not match the configured AWS region"
  [[ "$PAWLOCAL_COGNITO_APP_CLIENT_ID" =~ ^[A-Za-z0-9]+$ ]] || die "PAWLOCAL_COGNITO_APP_CLIENT_ID is invalid"
}

prepare_ssh() {
  local temp_dir="$1"
  printf '%s\n' "$PAWLOCAL_DEPLOY_SSH_PRIVATE_KEY" > "$temp_dir/deploy_key"
  chmod 0600 "$temp_dir/deploy_key"
  printf '%s\n' "$PAWLOCAL_DEPLOY_KNOWN_HOSTS" > "$temp_dir/known_hosts"
  chmod 0600 "$temp_dir/known_hosts"
}

ssh_command() {
  local key_file="$1" known_hosts="$2"
  shift 2
  ssh -i "$key_file" \
    -o BatchMode=yes \
    -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile="$known_hosts" \
    -o ConnectTimeout=15 \
    "pawlocal-deploy@${PAWLOCAL_DEPLOY_HOST}" "$@"
}

deploy() {
  local environment="$1" manifest="$2" frontend_archive="$3"
  validate_environment "$environment"
  need PAWLOCAL_DSQL_ACCESS_KEY_ID
  need PAWLOCAL_DSQL_SECRET_ACCESS_KEY
  [[ "$PAWLOCAL_DSQL_ACCESS_KEY_ID" =~ ^[A-Z0-9]{16,128}$ ]] || die "PAWLOCAL_DSQL_ACCESS_KEY_ID is invalid"
  [[ "$PAWLOCAL_DSQL_SECRET_ACCESS_KEY" =~ ^[A-Za-z0-9/+=]{32,256}$ ]] || die "PAWLOCAL_DSQL_SECRET_ACCESS_KEY is invalid"
  [[ -f "$manifest" && -f "$frontend_archive" ]] || die "Manifest and frontend archive must exist"
  read -r commit image image_digest migration_runner migration_id < <(read_manifest "$manifest" | tr '\t' ' ')
  [[ "$migration_runner" == dsql_baseline ]] || die "Unsupported DSQL migration runner"
  [[ "$image_digest" == "sha256:${image##*@sha256:}" ]] || die "Image digest fields do not match"

  local archive_digest temp_dir key_file known_hosts
  archive_digest="sha256:$(sha256sum "$frontend_archive" | cut -d ' ' -f1)"
  manifest_frontend_digest="$(python3 - "$manifest" <<'PY'
import json,sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["frontend"]["artifact_digest"])
PY
)"
  [[ "$archive_digest" == "$manifest_frontend_digest" ]] || die "Frontend archive digest does not match the release manifest"
  temp_dir="$(mktemp -d)"
  _PAWLOCAL_TEMP_DIR="$temp_dir"
  prepare_ssh "$temp_dir"
  key_file="$temp_dir/deploy_key"
  known_hosts="$temp_dir/known_hosts"

  need GITHUB_ACTOR
  need GITHUB_TOKEN
  printf '%s' "$GITHUB_TOKEN" | docker login ghcr.io --username "$GITHUB_ACTOR" --password-stdin >/dev/null
  _PAWLOCAL_DOCKER_LOGGED_IN=true
  docker pull "$image" >/dev/null
  docker save "$image" | ssh_command "$key_file" "$known_hosts" "sudo /usr/local/sbin/pawlocal-load-image '$image'"

  # The key values travel only over SSH stdin. They never appear in an argument,
  # Terraform value, release artifact, or command output.
  printf 'aws_access_key_id=%s\naws_secret_access_key=%s\n' \
    "$PAWLOCAL_DSQL_ACCESS_KEY_ID" "$PAWLOCAL_DSQL_SECRET_ACCESS_KEY" |
    ssh_command "$key_file" "$known_hosts" "sudo /usr/local/sbin/pawlocal-set-dsql-credentials"
  printf '%s\n%s\n%s\n%s\n%s\n%s\n' aurora_dsql "$AWS_REGION" "$PAWLOCAL_DSQL_ENDPOINT" "$PAWLOCAL_DSQL_DATABASE_ROLE" "$PAWLOCAL_COGNITO_ISSUER" "$PAWLOCAL_COGNITO_APP_CLIENT_ID" |
    ssh_command "$key_file" "$known_hosts" "sudo /usr/local/sbin/pawlocal-set-app-config"

  local app_dir
  app_dir="$temp_dir/frontend"
  mkdir -p "$app_dir"
  tar -xzf "$frontend_archive" -C "$app_dir"
  aws s3 sync "$app_dir" "s3://${PAWLOCAL_FRONTEND_BUCKET}/" --delete --no-progress
  aws s3 cp "$frontend_archive" "s3://${PAWLOCAL_FRONTEND_BUCKET}/releases/${commit}/${archive_digest#sha256:}.tar.gz" --no-progress
  aws cloudfront create-invalidation --distribution-id "$PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID" --paths '/*' >/dev/null

  ssh_command "$key_file" "$known_hosts" \
    "sudo /usr/local/sbin/pawlocal-deploy '$environment' '$image' aurora_dsql '$migration_id'"
  printf 'Deployed %s release %s with image %s; telemetry_enabled=false\n' "$environment" "$commit" "$image_digest"
}

seed_development() {
  local environment="$1" manifest="$2"
  [[ "$environment" == development ]] || die "The one-off seed operation is restricted to development"
  validate_environment "$environment"
  [[ -f "$manifest" ]] || die "Release manifest must exist"
  read -r commit image image_digest migration_runner migration_id < <(read_manifest "$manifest" | tr '\t' ' ')
  [[ "$migration_runner" == dsql_baseline && "$migration_id" == dsql_0001_initial ]] || die "Unsupported DSQL migration selection"
  [[ "$image_digest" == "sha256:${image##*@sha256:}" ]] || die "Image digest fields do not match"

  local temp_dir key_file known_hosts
  temp_dir="$(mktemp -d)"
  _PAWLOCAL_TEMP_DIR="$temp_dir"
  prepare_ssh "$temp_dir"
  key_file="$temp_dir/deploy_key"
  known_hosts="$temp_dir/known_hosts"

  # The host verifies that this digest is the active development release and
  # runs the seed module in that same image. Credentials remain in the host's
  # protected credentials file; no secret is sent back over this SSH command.
  ssh_command "$key_file" "$known_hosts" \
    "sudo /usr/local/sbin/pawlocal-deploy seed-development '$image'"
  printf 'Development seed completed for release %s (%s)\n' "$commit" "$image_digest"
}

verify() {
  local environment="$1" manifest="$2" evidence="$3"
  validate_environment "$environment"
  need PAWLOCAL_API_HEALTH_URL
  need PAWLOCAL_PUBLIC_BASE_URL
  [[ -f "$manifest" ]] || die "Release manifest must exist"
  read -r commit image image_digest migration_runner migration_id < <(read_manifest "$manifest" | tr '\t' ' ')
  [[ "$migration_runner" == dsql_baseline ]] || die "Unsupported DSQL migration runner"

  local temp_dir
  temp_dir="$(mktemp -d)"
  _PAWLOCAL_TEMP_DIR="$temp_dir"
  prepare_ssh "$temp_dir"
  local key_file="$temp_dir/deploy_key" known_hosts="$temp_dir/known_hosts"

  curl --fail --silent --show-error --location "${PAWLOCAL_API_HEALTH_URL:?}" >/dev/null
  local places_url
  places_url="$(python3 ops/api_smoke_url.py "$PAWLOCAL_API_HEALTH_URL")" || die "Could not derive the public places query URL"
  local places_response="$temp_dir/places-response.json"
  curl --fail --silent --show-error --location --header 'Cache-Control: no-cache' \
    "$places_url" --output "$places_response"
  python3 - "$places_response" <<'PY'
import json,sys
from pathlib import Path

page = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not isinstance(page, dict) or not isinstance(page.get("items"), list):
    raise SystemExit("Public /places query did not return a place-page response")
if not isinstance(page.get("total"), int) or not isinstance(page.get("page"), int):
    raise SystemExit("Public /places query returned an invalid place-page response")
PY
  curl --fail --silent --show-error --location "${PAWLOCAL_PUBLIC_BASE_URL:?}" | grep -qi '<html'
  local release_record
  release_record="$(ssh_command "$key_file" "$known_hosts" "sudo cat /var/lib/pawlocal/current-release.txt")"
  grep -Fxq "environment=${environment}" <<<"$release_record" || die "Runtime environment does not match"
  grep -Fxq "image=${image}" <<<"$release_record" || die "Runtime image does not match the release manifest"
  grep -Fxq "provider=aurora_dsql" <<<"$release_record" || die "Runtime database provider does not match"
  grep -Fxq "migration_id=${migration_id}" <<<"$release_record" || die "Runtime migration identity does not match"
  grep -Fxq "telemetry_enabled=false" <<<"$release_record" || die "Runtime telemetry must be disabled"

  local frontend_digest verified_at
  frontend_digest="$(python3 - "$manifest" <<'PY'
import json,sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["frontend"]["artifact_digest"])
PY
)"
  verified_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$(dirname "$evidence")"
  python3 - "$environment" "$commit" "$image_digest" "$frontend_digest" "$migration_runner" "$migration_id" "$evidence" "$verified_at" <<'PY'
import json,sys
environment,commit,image_digest,frontend_digest,runner,migration_id,path,verified_at=sys.argv[1:]
with open(path,"w",encoding="utf-8") as f:
    json.dump({
        "schema_version":1,
        "environment":environment,
        "commit":commit,
        "backend_image_digest":image_digest,
        "frontend_artifact_digest":frontend_digest,
        "database_provider":"aurora_dsql",
        "migration_runner":runner,
        "migration_id":migration_id,
        "telemetry_enabled":False,
        "public_endpoint_health":{"frontend":True,"api":True},
        "database_query_smoke":{"route":"/api/v1/places","result":"valid_place_page"},
        "verified_at":verified_at,
    },f,indent=2)
    f.write("\n")
PY
  python3 ops/validate-release-metadata.py --manifest "$manifest" --evidence "$evidence" --environment "$environment" --database-provider aurora_dsql
}

main() {
  [[ $# -ge 3 ]] || die "Usage: $0 <deploy|verify|seed> --environment development|production --manifest <path> [--frontend-archive <path>|--evidence <path>]"
  local operation="$1" environment="" manifest="" extra=""
  shift
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --environment) environment="${2:-}"; shift 2 ;;
      --manifest) manifest="${2:-}"; shift 2 ;;
      --frontend-archive|--evidence) extra="${2:-}"; shift 2 ;;
      *) die "Unknown argument: $1" ;;
    esac
  done
  [[ -n "$environment" && -n "$manifest" ]] || die "Missing required adapter arguments"
  if [[ "$operation" != seed ]]; then
    [[ -n "$extra" ]] || die "Missing required adapter arguments"
  fi
  case "$operation" in
    deploy) deploy "$environment" "$manifest" "$extra" ;;
    verify) verify "$environment" "$manifest" "$extra" ;;
    seed) seed_development "$environment" "$manifest" ;;
    *) die "Operation must be deploy, verify, or seed" ;;
  esac
}

main "$@"
