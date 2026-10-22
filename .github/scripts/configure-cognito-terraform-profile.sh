#!/usr/bin/env bash
set -euo pipefail

required_names=(
  AWS_PARTITION
  AWS_REGION
  COGNITO_TERRAFORM_PURPOSE
  PAWLOCAL_AWS_ACCOUNT_ID
  PAWLOCAL_ENVIRONMENT
  RUNNER_TEMP
  TF_VAR_project_name
)

for name in "${required_names[@]}"; do
  [[ -n "${!name:-}" ]] || {
    echo "Missing delegated Cognito profile input: ${name}" >&2
    exit 1
  }
done

[[ "$AWS_PARTITION" == "aws" ]] || {
  echo 'The delegated Cognito profile supports only the approved aws partition.' >&2
  exit 1
}
[[ "$PAWLOCAL_AWS_ACCOUNT_ID" =~ ^[0-9]{12}$ ]] || {
  echo 'PAWLOCAL_AWS_ACCOUNT_ID must contain exactly 12 digits.' >&2
  exit 1
}
[[ "$PAWLOCAL_ENVIRONMENT" =~ ^(development|production)$ ]] || {
  echo 'PAWLOCAL_ENVIRONMENT must be development or production.' >&2
  exit 1
}
[[ "$COGNITO_TERRAFORM_PURPOSE" =~ ^(plan|apply)$ ]] || {
  echo 'COGNITO_TERRAFORM_PURPOSE must be plan or apply.' >&2
  exit 1
}
[[ "$TF_VAR_project_name" =~ ^[A-Za-z0-9._-]{1,8}$ ]] || {
  echo 'TF_VAR_project_name must match the Terraform project_name contract.' >&2
  exit 1
}
[[ -z "${AWS_PROFILE:-}" ]] || {
  echo 'AWS_PROFILE must remain unset so the default Terraform provider keeps the environment credentials.' >&2
  exit 1
}

COGNITO_DEPLOYMENT_PROFILE="${TF_VAR_project_name}-cognito-deployment"
export COGNITO_DEPLOYMENT_PROFILE
expected_config_file="${RUNNER_TEMP}/${COGNITO_DEPLOYMENT_PROFILE}-${GITHUB_JOB:-terraform}.config"
[[ -z "${AWS_CONFIG_FILE:-}" || "$AWS_CONFIG_FILE" == "$expected_config_file" ]] || {
  echo 'AWS_CONFIG_FILE must use the workflow-owned temporary path.' >&2
  exit 1
}
AWS_CONFIG_FILE="$expected_config_file"
export AWS_CONFIG_FILE

role_name="pawlocal-${PAWLOCAL_ENVIRONMENT}-cognito-terraform-${COGNITO_TERRAFORM_PURPOSE}"
role_arn="arn:${AWS_PARTITION}:iam::${PAWLOCAL_AWS_ACCOUNT_ID}:role/${role_name}"
session_name="pawlocal-${PAWLOCAL_ENVIRONMENT}-cognito-${COGNITO_TERRAFORM_PURPOSE}"

[[ "$role_name" =~ ^pawlocal-(development|production)-cognito-terraform-(plan|apply)$ ]] || exit 1
[[ "$role_arn" == "arn:${AWS_PARTITION}:iam::${PAWLOCAL_AWS_ACCOUNT_ID}:role/${role_name}" ]] || exit 1
[[ "$session_name" =~ ^[A-Za-z0-9+=,.@_-]{2,64}$ ]] || exit 1

echo "::add-mask::${role_arn}"
umask 077
{
  printf '[profile %s]\n' "$COGNITO_DEPLOYMENT_PROFILE"
  printf 'role_arn = %s\n' "$role_arn"
  printf 'credential_source = Environment\n'
  printf 'role_session_name = %s\n' "$session_name"
  printf 'duration_seconds = 3600\n'
  printf 'region = %s\n' "$AWS_REGION"
} > "$AWS_CONFIG_FILE"

if [[ -n "${GITHUB_ENV:-}" ]]; then
  printf 'AWS_CONFIG_FILE=%s\n' "$AWS_CONFIG_FILE" >> "$GITHUB_ENV"
  printf 'COGNITO_DEPLOYMENT_PROFILE=%s\n' "$COGNITO_DEPLOYMENT_PROFILE" >> "$GITHUB_ENV"
  printf 'COGNITO_DELEGATED_ROLE_ARN=%s\n' "$role_arn" >> "$GITHUB_ENV"
fi

caller_identity="$(aws sts get-caller-identity --profile "$COGNITO_DEPLOYMENT_PROFILE" --query '[Account,Arn]' --output text)"
caller_account="${caller_identity%%$'\t'*}"
caller_arn="${caller_identity#*$'\t'}"
expected_caller_arn="arn:${AWS_PARTITION}:sts::${PAWLOCAL_AWS_ACCOUNT_ID}:assumed-role/${role_name}/${session_name}"

[[ "$caller_account" == "$PAWLOCAL_AWS_ACCOUNT_ID" ]] || {
  echo 'Delegated Cognito profile returned the wrong AWS account.' >&2
  exit 1
}
[[ "$caller_arn" == "$expected_caller_arn" ]] || {
  echo 'Delegated Cognito profile returned an unexpected caller identity.' >&2
  exit 1
}

echo "::add-mask::${caller_arn}"
echo "Verified delegated Cognito Terraform ${COGNITO_TERRAFORM_PURPOSE} identity for ${PAWLOCAL_ENVIRONMENT}."
