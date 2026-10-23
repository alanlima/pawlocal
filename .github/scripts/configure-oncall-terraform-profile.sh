#!/usr/bin/env bash
set -euo pipefail

# Called after the Cognito helper created the workflow-owned shared config.
# Append a profile definition without assuming it: default-disabled plans must
# not need a new role or any new credentials. An enabled saved plan selects this
# stable profile; the matching apply/destroy job supplies its write-role session.
[[ "${AWS_PARTITION:-}" == 'aws' ]]
[[ "${PAWLOCAL_AWS_ACCOUNT_ID:-}" =~ ^[0-9]{12}$ ]]
[[ "${PAWLOCAL_ENVIRONMENT:-}" =~ ^(development|production)$ ]]
[[ "${COGNITO_TERRAFORM_PURPOSE:-}" =~ ^(plan|apply)$ ]]
[[ "${TF_VAR_project_name:-}" =~ ^[A-Za-z0-9._-]{1,8}$ ]]
[[ -n "${AWS_REGION:-}" && -n "${RUNNER_TEMP:-}" && -z "${AWS_PROFILE:-}" ]]
script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python "$script_directory/validate-oncall-configuration.py"
expected_file="${RUNNER_TEMP}/${TF_VAR_project_name}-cognito-deployment-${GITHUB_JOB:-terraform}.config"
[[ "${AWS_CONFIG_FILE:-}" == "$expected_file" && -f "$expected_file" ]]
profile="${TF_VAR_project_name}-oncall-deployment"
role="arn:aws:iam::${PAWLOCAL_AWS_ACCOUNT_ID}:role/pawlocal-${PAWLOCAL_ENVIRONMENT}-oncall-terraform-${COGNITO_TERRAFORM_PURPOSE}"
echo "::add-mask::${role}"
umask 077
{
  printf '\n[profile %s]\n' "$profile"
  printf 'role_arn = %s\n' "$role"
  printf 'credential_source = Environment\n'
  printf 'role_session_name = pawlocal-%s-oncall-%s\n' "$PAWLOCAL_ENVIRONMENT" "$COGNITO_TERRAFORM_PURPOSE"
  printf 'duration_seconds = 3600\n'
  printf 'region = %s\n' "$AWS_REGION"
} >> "$expected_file"
echo "Prepared optional delegated on-call Terraform ${COGNITO_TERRAFORM_PURPOSE} profile for ${PAWLOCAL_ENVIRONMENT}."
