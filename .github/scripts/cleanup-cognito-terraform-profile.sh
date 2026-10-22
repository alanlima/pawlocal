#!/usr/bin/env bash
set -euo pipefail

[[ -n "${RUNNER_TEMP:-}" ]] || {
  echo 'RUNNER_TEMP is required for safe delegated-profile cleanup.' >&2
  exit 1
}
[[ "${TF_VAR_project_name:-}" =~ ^[A-Za-z0-9._-]{1,8}$ ]] || {
  echo 'TF_VAR_project_name must match the Terraform project_name contract.' >&2
  exit 1
}

if [[ -z "${AWS_CONFIG_FILE:-}" ]]; then
  exit 0
fi

case "$AWS_CONFIG_FILE" in
  "${RUNNER_TEMP}"/"${TF_VAR_project_name}"-cognito-deployment-*.config)
    rm -f -- "$AWS_CONFIG_FILE"
    ;;
  *)
    echo 'Refusing to remove a delegated profile outside the workflow-owned temporary path.' >&2
    exit 1
    ;;
esac
