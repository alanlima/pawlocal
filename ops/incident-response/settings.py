import sys
"""Read-only verification of one-time autonomous runtime settings."""

import importlib.util
import re
from pathlib import Path

from quota import Denied, strict_json

RUNTIME_ENVIRONMENTS = (
    "development",
    "development-plan",
    "development-apply",
    "production",
    "production-plan",
    "production-apply",
    "oncall-development",
    "oncall-production",
)


def check_environment(client, name):
    if name not in RUNTIME_ENVIRONMENTS:
        return False, "unsupported runtime environment"
    environment = client.request("GET", "/environments/" + name)
    rules = environment.get("protection_rules")
    dbp = environment.get("deployment_branch_policy")
    reasons = []
    if not isinstance(rules, list):
        reasons.append("protection_rules is not a list")
    else:
        reviewers = [r for r in rules if r.get("type") == "required_reviewers"]
        other_rules = [r for r in rules if r.get("type") not in ("branch_policy", "required_reviewers")]
        if reviewers:
            reasons.append("Has Required Reviewers (must be removed for unattended release per Step 4e)")
        if other_rules:
            reasons.append(f"Unexpected protection rules: {[r.get('type') for r in other_rules]}")
        if len(rules) > 1:
            reasons.append(f"Multiple protection rules configured (count={len(rules)})")
    if dbp != {"protected_branches": False, "custom_branch_policies": True}:
        reasons.append(f"deployment_branch_policy mismatch: {dbp} (must be 'Selected branches')")

    policies = client.request(
        "GET", "/environments/" + name + "/deployment-branch-policies?per_page=100"
    )
    rows = policies.get("branch_policies", [])
    if (
        policies.get("total_count") != 1
        or len(rows) != 1
        or rows[0].get("name") != "main"
        or rows[0].get("type") != "branch"
    ):
        reasons.append("Deployment branches must allow only 'main'")

    if reasons:
        return False, "; ".join(reasons)
    return True, "Branch: main, 0 reviewers"


def environment_ready(client, name):
    ok, details = check_environment(client, name)
    if not ok:
        msg = f"automatic production environment protection setup missing for {name!r}: {details}"
        print(f"[runtime_ready] FAIL: {msg}", file=sys.stderr)
        raise Denied(msg)


def production_ready(client):
    environment_ready(client, "production")


def runtime_ready(client):
    results = []
    failed = []
    for name in RUNTIME_ENVIRONMENTS:
        ok, details = check_environment(client, name)
        status = "OK" if ok else "FAIL"
        results.append((name, status, details))
        if not ok:
            failed.append(name)

    # Format and print the environment audit table
    table_lines = [
        "\n[runtime_ready] Environment Protection Audit:",
        "| Environment | Status | Details |",
        "|---|---|---|",
    ]
    for name, status, details in results:
        table_lines.append(f"| {name} | {status} | {details} |")
    print("\n".join(table_lines) + "\n", file=sys.stderr)

    if failed:
        raise Denied(
            f"automatic production environment protection setup missing for: {', '.join(failed)}. See audit table above."
        )


def bindings_ready(trusted):
    # Reuse the producer's complete public schema; it performs no API calls.
    validator_path = (
        Path(__file__).resolve().parents[2] / "observability/grafana/cloud/provision.py"
    )
    specification = importlib.util.spec_from_file_location(
        "oncall_binding_validator", validator_path
    )
    validator = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(validator)
    value = strict_json(
        (Path(trusted) / "observability/grafana/cloud/bindings.json").read_bytes()
    )
    try:
        validator.validate_manifest(value)
    except validator.ProvisionError as error:
        raise Denied("canonical approved hosted binding schema required") from error
    for environment in ("development", "production"):
        selected = value["environments"][environment]
        prefix = "pawlocal-dev" if environment == "development" else "pawlocal"
        if selected.get("enabled") is not True or not re.fullmatch(
            r"https://" + prefix + r"\.[a-z0-9.-]+/?",
            str(selected.get("frontend_origin", "")),
        ):
            raise Denied(
                "both environment bindings must be configured and approved before full-loop admission"
            )
