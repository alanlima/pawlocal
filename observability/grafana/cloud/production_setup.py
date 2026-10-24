"""PROD-only launcher for the existing folder/Faro provisioner; no alert owner."""

import importlib.util
import json
import os
import sys
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "grafana_production_provision", Path(__file__).with_name("provision.py")
)
provision = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provision)


def execute(mode, stack_url, region, raw_manifest, expected_origin, credentials, transport=None, datasource_uids_json=""):
    if mode not in {"discover", "plan", "apply"}:
        raise provision.ProvisionError("Unsupported production setup mode")
    if len(raw_manifest.encode("utf-8")) > 16384:
        raise provision.ProvisionError("Public manifest exceeds bounded input")
    if mode == "discover":
        if raw_manifest.strip() or expected_origin:
            raise provision.ProvisionError("Discovery accepts stack metadata inputs only")
        if not stack_url or not region:
            raise provision.ProvisionError("Discovery requires actual stack URL and region")
        client = provision.Provisioner(transport or provision.Transport(), credentials)
        return client.discover(stack_url, region, datasource_uids_json)
    if stack_url or region or datasource_uids_json or not expected_origin:
        raise provision.ProvisionError("Plan/apply require manifest and reviewed production origin")
    provision.https_url(expected_origin, origin=True)

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise provision.ProvisionError("Duplicate public manifest field")
            value[key] = item
        return value

    try:
        document = json.loads(raw_manifest, object_pairs_hook=unique)
    except (ValueError, TypeError) as error:
        raise provision.ProvisionError("Invalid public manifest JSON") from error
    provision.validate_manifest(document)
    production = document["environments"]["production"]
    if not production["enabled"] or production["frontend_origin"] != expected_origin:
        raise provision.ProvisionError("Enabled production manifest must match reviewed origin")
    client = provision.Provisioner(transport or provision.Transport(), credentials)
    return client.reconcile("production", production, apply=mode == "apply")


def main():
    try:
        result = execute(
            os.environ.get("SETUP_MODE", "discover"),
            os.environ.get("STACK_URL", ""),
            os.environ.get("STACK_REGION", ""),
            os.environ.get("PUBLIC_BINDINGS_JSON", ""),
            os.environ.get("EXPECTED_FRONTEND_ORIGIN", ""),
            os.environ,
            datasource_uids_json=os.environ.get("DATASOURCE_UIDS_JSON", ""),
        )
        # Provisioner result is its explicit public-only handoff, never raw API data.
        output = Path(os.environ["RUNNER_TEMP"]) / "grafana-production-public.json"
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
    except provision.ProvisionError as error:
        category = "configuration"
        status = None
        if isinstance(error, provision.TransportError):
            category = error.category if error.category in {
                "http-error", "network", "invalid-json", "response-too-large", "redirect"
            } else "internal-error"
            if type(error.http_status) is int and 100 <= error.http_status <= 599:
                status = error.http_status
        print(
            f"Production Grafana setup failed: {error}; category={category}, http_status={status}; no automatic mutation retry.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
