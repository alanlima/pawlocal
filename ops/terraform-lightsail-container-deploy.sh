#!/usr/bin/env bash
set -euo pipefail

echo "Direct local container deployment is disabled." >&2
echo "Use .github/workflows/terraform-environment.yml so the matching environment root applies the exact reviewed saved plan." >&2
exit 2
