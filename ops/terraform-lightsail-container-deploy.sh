#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

die() { printf '%s\n' "$1" >&2; exit 2; }
need() { [[ -n "${!1:-}" ]] || die "Required Terraform deployment setting is missing: $1"; }

environment="${1:-}"
manifest="${2:-}"
case "$environment" in development|production) ;; *) die "Usage: $0 <development|production> <release-manifest>" ;; esac
[[ -f "$manifest" ]] || die "Release manifest is missing"
for name in AWS_REGION PAWLOCAL_TF_STATE_BUCKET PAWLOCAL_DOMAIN_NAME PAWLOCAL_CERTIFICATE_ARN TF_VAR_github_owner_id TF_VAR_github_repository_id GITHUB_REPOSITORY GITHUB_WORKSPACE; do need "$name"; done

image="$(python3 - "$manifest" <<'PY'
import json,re,sys
v=json.load(open(sys.argv[1],encoding='utf-8'))
image=v.get('backend_image','')
if not re.fullmatch(r'ghcr\.io/alanlima/pawlocal-api@sha256:[0-9a-f]{64}', image):
    raise SystemExit('Release backend image must be a digest-pinned public GHCR image')
if v.get('telemetry_enabled') is not False:
    raise SystemExit('Telemetry must remain disabled')
print(image)
PY
)"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root="$script_dir/../infra/terraform"
terraform -chdir="$root" init -input=false -reconfigure \
  -backend-config="bucket=$PAWLOCAL_TF_STATE_BUCKET" \
  -backend-config='key=pawlocal/terraform.tfstate' \
  -backend-config="region=$AWS_REGION" \
  -backend-config='encrypt=true' \
  -backend-config='use_lockfile=true'
export TF_VAR_aws_region="$AWS_REGION"
export TF_VAR_domain_name="$PAWLOCAL_DOMAIN_NAME"
export TF_VAR_certificate_arn="$PAWLOCAL_CERTIFICATE_ARN"
export TF_VAR_github_repository="$GITHUB_REPOSITORY"
export TF_VAR_terraform_state_bucket_name="$PAWLOCAL_TF_STATE_BUCKET"
export TF_VAR_dsql_bootstrap_python=/usr/bin/python3

current_targets="$(terraform -chdir="$root" output -json environment_targets)"
if [[ -n "${GITHUB_ENV:-}" ]]; then
  TARGETS_JSON="$current_targets" python3 - "$environment" "$GITHUB_ENV" <<'PY'
import json,os,sys
import re
environment,github_env=sys.argv[1:]
targets=json.loads(os.environ['TARGETS_JSON'])
target=targets.get(environment) or {}
bucket=target.get('frontend_bucket')
distribution=target.get('distribution_id')
if not isinstance(bucket,str) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]',bucket):
    raise SystemExit(f'Terraform state has no valid frontend bucket for {environment}')
if not isinstance(distribution,str) or not re.fullmatch(r'[A-Z0-9]+',distribution):
    raise SystemExit(f'Terraform state has no frontend publication target for {environment}')
with open(github_env,'a',encoding='utf-8') as output:
    output.write(f'PAWLOCAL_FRONTEND_BUCKET={bucket}\n')
    output.write(f'PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID={distribution}\n')
PY
fi
export TF_VAR_backend_image_digests="$(CURRENT_TARGETS="$current_targets" python3 - "$environment" "$image" <<'PY'
import json,os,sys
current=json.loads(os.environ['CURRENT_TARGETS'])
target,release_image=sys.argv[1:]
images={}
for env in ('development','production'):
    value=current[env].get('api_backend_image')
    if not isinstance(value,str) or '@sha256:' not in value:
        raise SystemExit(f'{env} has no Terraform-tracked backend image; complete the reviewed initial migration first')
    images[env]=release_image if env==target else value
print(json.dumps(images,separators=(',',':')))
PY
)"

plan="$(mktemp "${RUNNER_TEMP:-/tmp}/pawlocal-container-${environment}.XXXXXX.tfplan")"
trap 'rm -f "$plan"' EXIT
terraform -chdir="$root" plan -input=false -lock-timeout=5m -out="$plan"
terraform -chdir="$root" show -json "$plan" |
  python3 ops/validate-lightsail-container-plan.py --environment "$environment" --image "$image"
terraform -chdir="$root" apply -input=false -lock-timeout=5m -auto-approve "$plan"
service_json="$(aws lightsail get-container-services --service-name "pawlocal-${environment}-api" --query 'containerServices[0]' --output json)"
printf '%s' "$service_json" | TARGET_IMAGE="$image" python3 -c '
import json,os,sys
service=json.load(sys.stdin)
deployment=service.get("currentDeployment") or {}
containers=deployment.get("containers") or {}
container=containers.get("pawlocal-api") or {}
if service.get("state") != "RUNNING" or deployment.get("state") != "ACTIVE":
    raise SystemExit("Lightsail service does not report a running active deployment")
if container.get("image") != os.environ["TARGET_IMAGE"]:
    raise SystemExit("Lightsail active deployment image does not match the selected release digest")
'
printf '%s\n' "Verified active Lightsail $environment service image digest"
printf 'Terraform recorded and deployed %s image %s\n' "$environment" "$image"
