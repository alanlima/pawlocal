#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

die() { printf '%s\n' "$1" >&2; exit 2; }
need() { [[ -n "${!1:-}" ]] || die "Required Terraform ingress setting is missing: $1"; }

operation="${1:-}"
environment="${2:-}"
case "$operation:$environment" in
  open:development|open:production|restore:development|restore:production) ;;
  *) die "Usage: $0 <open|restore> <development|production>" ;;
esac

for name in AWS_REGION PAWLOCAL_TF_STATE_BUCKET PAWLOCAL_DOMAIN_NAME \
  PAWLOCAL_CERTIFICATE_ARN PAWLOCAL_DEPLOY_SSH_PUBLIC_KEYS_JSON \
  PAWLOCAL_BASELINE_SSH_CIDR_BLOCKS_JSON TF_VAR_github_owner_id \
  TF_VAR_github_repository_id GITHUB_REPOSITORY; do
  need "$name"
done

need PAWLOCAL_RUNNER_IPV4_CIDR
python3 - "$PAWLOCAL_RUNNER_IPV4_CIDR" <<'PY'
import ipaddress, sys
try:
    network = ipaddress.ip_network(sys.argv[1], strict=True)
except ValueError as exc:
    raise SystemExit(f"Invalid runner CIDR: {exc}")
if network.version != 4 or network.prefixlen != 32:
    raise SystemExit("Runner ingress must be exactly one IPv4 /32")
PY

terraform_root="${GITHUB_WORKSPACE:?GITHUB_WORKSPACE must be set}/infra/terraform"
terraform -chdir="$terraform_root" init -input=false -reconfigure \
  -backend-config="bucket=$PAWLOCAL_TF_STATE_BUCKET" \
  -backend-config="key=pawlocal/terraform.tfstate" \
  -backend-config="region=$AWS_REGION" \
  -backend-config="encrypt=true" \
  -backend-config="use_lockfile=true"

export TF_VAR_aws_region="$AWS_REGION"
export TF_VAR_domain_name="$PAWLOCAL_DOMAIN_NAME"
export TF_VAR_certificate_arn="$PAWLOCAL_CERTIFICATE_ARN"
export TF_VAR_github_repository="$GITHUB_REPOSITORY"
export TF_VAR_terraform_state_bucket_name="$PAWLOCAL_TF_STATE_BUCKET"
export TF_VAR_deploy_ssh_public_keys="$PAWLOCAL_DEPLOY_SSH_PUBLIC_KEYS_JSON"
export TF_VAR_ssh_cidr_blocks="$PAWLOCAL_BASELINE_SSH_CIDR_BLOCKS_JSON"
# This local-exec-only input is not exercised by the targeted public-port plan.
export TF_VAR_dsql_bootstrap_python=/usr/bin/python3
export TF_VAR_manage_github_oidc_provider=false

unset TF_VAR_temporary_ssh_environment TF_VAR_temporary_ssh_cidr
if [[ "$operation" == open ]]; then
  export TF_VAR_temporary_ssh_environment="$environment"
  export TF_VAR_temporary_ssh_cidr="$PAWLOCAL_RUNNER_IPV4_CIDR"
fi

target="module.fullstack.aws_lightsail_instance_public_ports.api[\"$environment\"]"
plan_file="$(mktemp "${RUNNER_TEMP:-/tmp}/pawlocal-ingress-${environment}.XXXXXX.tfplan")"
trap 'rm -f "$plan_file"' EXIT

# The workflow only needs restoration after an apply could have changed AWS/state.
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  printf 'ingress_state_may_have_changed=false\n' >> "$GITHUB_OUTPUT"
fi

terraform -chdir="$terraform_root" plan -input=false -lock-timeout=5m \
  -target="$target" -out="$plan_file"
terraform -chdir="$terraform_root" show -json "$plan_file" |
  python3 ops/validate-lightsail-ingress-plan.py \
    --operation "$operation" \
    --environment "$environment" \
    --runner-cidr "$PAWLOCAL_RUNNER_IPV4_CIDR" \
    --baseline-cidrs-json "$PAWLOCAL_BASELINE_SSH_CIDR_BLOCKS_JSON"
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  printf 'ingress_state_may_have_changed=true\n' >> "$GITHUB_OUTPUT"
fi
terraform -chdir="$terraform_root" apply -input=false -lock-timeout=5m \
  -auto-approve "$plan_file"

if [[ "$operation" == open ]]; then
  printf 'Terraform temporarily enabled SSH to the %s Lightsail instance from %s\n' \
    "$environment" "$PAWLOCAL_RUNNER_IPV4_CIDR"
else
  printf 'Terraform restored the %s Lightsail SSH baseline CIDRs\n' "$environment"
fi
