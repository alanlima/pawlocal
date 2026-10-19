#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <deploy|verify> [adapter arguments...]" >&2
  exit 2
fi
case "$1" in
  deploy|verify|seed) ;;
  *)
    echo "The deployment adapter only accepts deploy, verify, or seed operations." >&2
    exit 2
    ;;
esac

adapter_path="${PAWLOCAL_DEPLOY_ADAPTER_PATH:-}"
case "$adapter_path" in
  ops/deployment-adapters/*.sh) ;;
  *)
    echo "PAWLOCAL_DEPLOY_ADAPTER_PATH must name a reviewed script under ops/deployment-adapters/." >&2
    exit 2
    ;;
esac

if [[ ! -f "$adapter_path" || ! -x "$adapter_path" ]]; then
  echo "The selected deployment adapter is not present and executable: $adapter_path" >&2
  exit 2
fi

resolved_adapter="$(realpath -e "$adapter_path")"
resolved_root="$(realpath -e ops/deployment-adapters)"
case "$resolved_adapter" in
  "$resolved_root"/*) ;;
  *)
    echo "The deployment adapter resolved outside ops/deployment-adapters/." >&2
    exit 2
    ;;
esac

exec "$resolved_adapter" "$@"
