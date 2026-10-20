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
root="$script_dir/../infra/terraform/environments/$environment"
terraform -chdir="$root" init -input=false -reconfigure \
  -backend-config="bucket=$PAWLOCAL_TF_STATE_BUCKET" \
  -backend-config="key=pawlocal/$environment/terraform.tfstate" \
  -backend-config="region=$AWS_REGION" \
  -backend-config='encrypt=true' \
  -backend-config='use_lockfile=true'
export TF_VAR_aws_region="$AWS_REGION"
export TF_VAR_domain_name="$PAWLOCAL_DOMAIN_NAME"
export TF_VAR_certificate_arn="$PAWLOCAL_CERTIFICATE_ARN"
export TF_VAR_github_repository="$GITHUB_REPOSITORY"
export TF_VAR_terraform_state_bucket_name="$PAWLOCAL_TF_STATE_BUCKET"

current_targets="$(terraform -chdir="$root" output -json environment_targets)"
aws_account_id="$(CURRENT_TARGETS="$current_targets" python3 - "$environment" <<'PY'
import json,os,re
import sys
targets=json.loads(os.environ['CURRENT_TARGETS'])
account_id=(targets.get(sys.argv[1]) or {}).get('aws_account_id')
if not isinstance(account_id,str) or not re.fullmatch(r'[0-9]{12}',account_id):
    raise SystemExit('Terraform state has no valid AWS account ID')
print(account_id)
PY
)"
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
target,release_image=sys.argv[1:]
print(json.dumps({target:release_image},separators=(',',':')))
PY
)"

plan="$(mktemp "${RUNNER_TEMP:-/tmp}/pawlocal-container-${environment}.XXXXXX.tfplan")"
trap 'rm -f "$plan"' EXIT
if ! terraform -chdir="$root" plan -input=false -lock-timeout=5m -no-color -out="$plan" > "${RUNNER_TEMP:-/tmp}/pawlocal-release-plan.txt" 2>&1; then
  die "Terraform container deployment plan failed; raw output was withheld"
fi
if ! terraform -chdir="$root" show -json "$plan" 2>"${RUNNER_TEMP:-/tmp}/pawlocal-release-show-error.txt" |
  python3 "$script_dir/validate-lightsail-container-plan.py" --environment "$environment" --image "$image" --aws-account-id "$aws_account_id"; then
  die "Terraform container deployment review failed; raw output was withheld"
fi
if ! terraform -chdir="$root" apply -input=false -lock-timeout=5m -auto-approve "$plan" > "${RUNNER_TEMP:-/tmp}/pawlocal-release-apply.txt" 2>&1; then
  die "Terraform container deployment apply failed; raw output was withheld"
fi
python3 -m pip install --disable-pip-version-check boto3==1.35.99
python3 "$script_dir/verify-lightsail-container-deployment.py" --environment "$environment" --image "$image"
printf 'Terraform recorded and deployed %s image %s\n' "$environment" "$image"
