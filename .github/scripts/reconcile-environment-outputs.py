#!/usr/bin/env python3
"""Reconcile allowlisted Terraform outputs without exposing their values.

Raw output values exist only in runner-local state and plan files. Console output,
evidence records, and deployment payloads contain names, statuses, and digests only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RECORD_TYPE = "pawlocal_generated_output_reconciliation"
RECORD_SCHEMA_VERSION = 1
ALLOWED_ENVIRONMENTS = {"development", "production"}
ALLOWED_TARGET_TEMPLATES = {
    "{environment}",
    "{environment}-plan",
    "{environment}-apply",
}
EXPECTED_ENVIRONMENT_CONFIG = {
    "development": {
        "reconciliation_environment": "development-reconcile",
        "evidence_environment": "development",
        "environment_state_key": "pawlocal/development/terraform.tfstate",
    },
    "production": {
        "reconciliation_environment": "production-reconcile",
        "evidence_environment": "production",
        "environment_state_key": "pawlocal/production/terraform.tfstate",
    },
}
FORBIDDEN_GENERATED_VARIABLES = {
    "AWS_REGION",
    "PAWLOCAL_TF_STATE_BUCKET",
    "PAWLOCAL_DOMAIN_NAME",
    "PAWLOCAL_ROUTE53_ZONE_ID",
    "PAWLOCAL_CLOUDFRONT_CERTIFICATE_ARN",
    "PAWLOCAL_DEPLOY_ADAPTER_PATH",
    "PAWLOCAL_TERRAFORM_DIAGNOSTIC_LOGS",
}
EXPECTED_MAPPING_SIGNATURES = {
    ("bootstrap", "terraform_role_arns", ("{environment}-plan",), ("{environment}-plan", "{environment}-apply"), "PAWLOCAL_TERRAFORM_PLAN_ROLE_ARN"),
    ("bootstrap", "terraform_role_arns", ("{environment}-apply",), ("{environment}-apply",), "PAWLOCAL_TERRAFORM_APPLY_ROLE_ARN"),
    ("bootstrap", "aws_account_id", (), ("{environment}-plan", "{environment}-apply"), "PAWLOCAL_AWS_ACCOUNT_ID"),
    ("bootstrap", "plan_transfer_bucket_name", (), ("{environment}-plan", "{environment}-apply"), "PAWLOCAL_TERRAFORM_PLAN_BUCKET"),
    ("bootstrap", "identity_app_role_arns", ("{environment}_frontend",), ("{environment}",), "PAWLOCAL_DEPLOY_ROLE_ARN"),
    ("bootstrap", "identity_app_role_arns", ("{environment}_runtime",), ("{environment}-plan", "{environment}-apply"), "PAWLOCAL_RUNTIME_ROLE_ARN"),
    ("environment", "environment_targets", ("frontend_url",), ("{environment}",), "PAWLOCAL_PUBLIC_BASE_URL"),
    ("environment", "environment_targets", ("api_health_url",), ("{environment}",), "PAWLOCAL_API_HEALTH_URL"),
    ("environment", "environment_targets", ("frontend_bucket",), ("{environment}",), "PAWLOCAL_FRONTEND_BUCKET"),
    ("environment", "environment_targets", ("cloudfront_distribution_id",), ("{environment}",), "PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID"),
    ("environment", "environment_targets", ("cloudfront_distribution_arn",), ("{environment}-plan", "{environment}-apply"), "PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ARN"),
    ("environment", "environment_targets", ("cloudfront_oac_arn",), ("{environment}-plan", "{environment}-apply"), "PAWLOCAL_CLOUDFRONT_OAC_ARN"),
    ("environment", "environment_targets", ("cognito_client_id",), ("{environment}",), "VITE_COGNITO_CLIENT_ID"),
    ("environment", "environment_targets", ("api_base_url",), ("{environment}",), "VITE_API_BASE_URL"),
    ("environment", "environment_targets", ("cognito_domain",), ("{environment}",), "VITE_COGNITO_DOMAIN"),
    ("environment", "environment_targets", ("cognito_redirect_uri",), ("{environment}",), "VITE_COGNITO_REDIRECT_URI"),
    ("environment", "environment_targets", ("cognito_logout_uri",), ("{environment}",), "VITE_COGNITO_LOGOUT_URI"),
    ("environment", "environment_targets", ("cognito_scopes",), ("{environment}",), "VITE_COGNITO_SCOPES"),
}
EXPECTED_LEGACY_VARIABLES = {
    "PAWLOCAL_BASELINE_SSH_CIDR_BLOCKS_JSON", "PAWLOCAL_CERTIFICATE_ARN",
    "PAWLOCAL_COGNITO_APP_CLIENT_ID", "PAWLOCAL_COGNITO_ISSUER", "PAWLOCAL_DEPLOY_HOST",
    "PAWLOCAL_DEPLOY_KNOWN_HOSTS", "PAWLOCAL_DEPLOY_MODE", "PAWLOCAL_DEPLOY_SSH_PUBLIC_KEYS_JSON",
    "PAWLOCAL_DOMAIN_NAME", "PAWLOCAL_DSQL_DATABASE_ROLE", "PAWLOCAL_DSQL_ENDPOINT",
    "PAWLOCAL_TERRAFORM_ROLE_ARN", "PAWLOCAL_TF_STATE_BUCKET",
}
EXPECTED_LEGACY_SECRETS = {
    "PAWLOCAL_DEPLOY_SSH_PRIVATE_KEY", "PAWLOCAL_DSQL_ACCESS_KEY_ID",
    "PAWLOCAL_DSQL_SECRET_ACCESS_KEY",
}
EXPECTED_DESTROY_INVALIDATION_VARIABLES = {
    "PAWLOCAL_RUNTIME_ROLE_ARN", "PAWLOCAL_PUBLIC_BASE_URL", "PAWLOCAL_API_HEALTH_URL",
    "PAWLOCAL_FRONTEND_BUCKET", "PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID",
    "PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ARN", "PAWLOCAL_CLOUDFRONT_OAC_ARN",
    "VITE_COGNITO_CLIENT_ID", "VITE_API_BASE_URL", "VITE_COGNITO_DOMAIN",
    "VITE_COGNITO_REDIRECT_URI", "VITE_COGNITO_LOGOUT_URI", "VITE_COGNITO_SCOPES",
}
ACTIVE_RELEASE_FILES = (
    ".github/workflows/fullstack-release.yml",
    ".github/workflows/deploy-production.yml",
    ".github/workflows/rollback-development.yml",
    ".github/workflows/frontend-production-deploy.yml",
    "ops/run-deployment-adapter.sh",
    "ops/deployment-adapters/lightsail-dsql.sh",
)


class ReconciliationError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def read_json(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconciliationError("Required JSON input is unavailable or invalid") from exc


def write_private_json(path: str | Path, value: Any) -> None:
    output = Path(path)
    output.write_bytes(canonical(value) + b"\n")
    try:
        output.chmod(0o600)
    except OSError:
        pass


def load_allowlist(path: str | Path) -> dict[str, Any]:
    allowlist = read_json(path)
    if allowlist.get("schema_version") != 1:
        raise ReconciliationError("Unsupported allowlist schema")
    environments = allowlist.get("environments")
    if environments != EXPECTED_ENVIRONMENT_CONFIG:
        raise ReconciliationError("Allowlist environment metadata does not match the fixed state boundaries")
    if allowlist.get("bootstrap_state_key") != "pawlocal/iam-bootstrap/terraform.tfstate":
        raise ReconciliationError("Allowlist bootstrap state does not match the fixed boundary")
    mappings = allowlist.get("mappings")
    if not isinstance(mappings, list) or not mappings:
        raise ReconciliationError("Allowlist mappings are missing")
    seen: set[tuple[str, str]] = set()
    mapped_variables: set[str] = set()
    signatures: set[tuple[Any, ...]] = set()
    optional_signatures: set[tuple[Any, ...]] = set()
    for mapping in mappings:
        if not set(mapping) <= {"source", "output", "path", "targets", "variable", "optional_first_stage"}:
            raise ReconciliationError("Allowlist mapping contains an unknown field")
        if mapping.get("source") not in {"bootstrap", "environment"}:
            raise ReconciliationError("Allowlist contains an unknown source")
        if not isinstance(mapping.get("output"), str) or not mapping["output"]:
            raise ReconciliationError("Allowlist contains an invalid output key")
        variable = mapping.get("variable")
        if not isinstance(variable, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]+", variable):
            raise ReconciliationError("Allowlist contains an invalid variable name")
        if variable in FORBIDDEN_GENERATED_VARIABLES:
            raise ReconciliationError("Allowlist contains an operator-controlled variable")
        mapped_variables.add(variable)
        targets = mapping.get("targets")
        if not isinstance(targets, list) or not targets or not set(targets) <= ALLOWED_TARGET_TEMPLATES:
            raise ReconciliationError("Allowlist contains an unknown target")
        if not isinstance(mapping.get("path"), list):
            raise ReconciliationError("Allowlist contains an invalid output path")
        signatures.add(
            (
                mapping["source"], mapping["output"], tuple(mapping["path"]),
                tuple(mapping["targets"]), variable,
            )
        )
        if mapping.get("optional_first_stage") is True:
            optional_signatures.add((mapping["source"], mapping["output"], tuple(mapping["path"]), variable))
        elif "optional_first_stage" in mapping:
            raise ReconciliationError("Allowlist optional marker is invalid")
        for target in targets:
            key = (target, variable)
            if key in seen:
                raise ReconciliationError("Allowlist contains a duplicate target variable")
            seen.add(key)
    if signatures != EXPECTED_MAPPING_SIGNATURES:
        raise ReconciliationError("Allowlist does not match the fixed output mapping")
    if optional_signatures != {("bootstrap", "identity_app_role_arns", ("{environment}_runtime",), "PAWLOCAL_RUNTIME_ROLE_ARN")}:
        raise ReconciliationError("Allowlist staged handoff marker does not match the fixed runtime mapping")
    invalidation = set(allowlist.get("destroy_invalidation_variables") or [])
    if (
        invalidation != EXPECTED_DESTROY_INVALIDATION_VARIABLES
        or len(allowlist.get("destroy_invalidation_variables") or []) != len(invalidation)
        or not invalidation <= mapped_variables
    ):
        raise ReconciliationError("Destroy invalidation is not a subset of generated variables")
    legacy_variables = allowlist.get("legacy_variables") or []
    legacy_secrets = allowlist.get("legacy_secrets") or []
    if (
        set(legacy_variables) != EXPECTED_LEGACY_VARIABLES
        or len(legacy_variables) != len(set(legacy_variables))
        or set(legacy_secrets) != EXPECTED_LEGACY_SECRETS
        or len(legacy_secrets) != len(set(legacy_secrets))
    ):
        raise ReconciliationError("Legacy cleanup allowlist is incomplete")
    if set(legacy_variables) & mapped_variables:
        raise ReconciliationError("Legacy and generated variables overlap")
    return allowlist


def state_revision(state: dict[str, Any]) -> dict[str, Any]:
    lineage = state.get("lineage")
    serial = state.get("serial")
    if not isinstance(lineage, str) or not lineage or not isinstance(serial, int) or serial < 0:
        raise ReconciliationError("Terraform state identity is missing")
    return {"lineage": lineage, "serial": serial}


def state_output(state: dict[str, Any], output: str, path: list[str], environment: str) -> Any:
    outputs = state.get("outputs")
    entry = outputs.get(output) if isinstance(outputs, dict) else None
    if not isinstance(entry, dict) or "value" not in entry or entry.get("sensitive") is True:
        raise ReconciliationError("Required non-secret Terraform output is missing")
    value = entry["value"]
    for raw_key in path:
        key = raw_key.format(environment=environment)
        if not isinstance(value, dict) or key not in value:
            raise ReconciliationError("Required non-secret Terraform output path is missing")
        value = value[key]
    return value


def ensure_string(value: Any, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value:
        raise ReconciliationError("Required non-secret Terraform output value is empty")
    return value


def validate_generated_scalar(variable: str, value: str | None) -> None:
    if value is None:
        return
    if any(ord(character) < 32 for character in value):
        raise ReconciliationError("Generated output contains a control character")
    if variable == "PAWLOCAL_AWS_ACCOUNT_ID" and not re.fullmatch(r"[0-9]{12}", value):
        raise ReconciliationError("Generated account output has an invalid format")
    if variable.endswith("_ARN") and not value.startswith("arn:"):
        raise ReconciliationError("Generated ARN output has an invalid format")
    url_paths = {
        "PAWLOCAL_PUBLIC_BASE_URL": {"", "/"},
        "PAWLOCAL_API_HEALTH_URL": {"/health"},
        "VITE_API_BASE_URL": {"/api/v1"},
        "VITE_COGNITO_DOMAIN": {"", "/"},
        "VITE_COGNITO_REDIRECT_URI": {"/auth/callback"},
        "VITE_COGNITO_LOGOUT_URI": {"/"},
    }
    if variable in url_paths:
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment or parsed.path not in url_paths[variable]:
            raise ReconciliationError("Generated URL output is not canonical")
    if variable == "VITE_COGNITO_SCOPES" and value != "openid email profile":
        raise ReconciliationError("Generated Cognito scopes are not canonical")


def initial_evidence(environment: str, mode: str, backend_fingerprint: str) -> dict[str, Any]:
    return {
        "record_type": RECORD_TYPE,
        "record_schema_version": RECORD_SCHEMA_VERSION,
        "environment": environment,
        "mode": mode,
        "source_commit": os.environ.get("GITHUB_SHA", ""),
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        "backend_fingerprint": backend_fingerprint,
        "status": "preparing",
        "ready": False,
        "staged_handoff_complete": False,
        "bootstrap_state_revision": "",
        "environment_state_revision": "",
        "configuration_digest": "",
        "verified_configuration_digest": "",
        "results": [],
        "failure": False,
    }


def validate_environment_marker(state: dict[str, Any], environment: str) -> None:
    marker = state_output(state, "environment_targets", ["environment"], environment)
    if marker != environment:
        raise ReconciliationError("Terraform state environment marker does not match the selected environment")


def build_plan(
    allowlist: dict[str, Any],
    environment: str,
    mode: str,
    bootstrap_state: dict[str, Any],
    environment_state: dict[str, Any],
) -> dict[str, Any]:
    if environment not in ALLOWED_ENVIRONMENTS:
        raise ReconciliationError("Unknown environment")
    if mode not in {"reconcile", "invalidate"}:
        raise ReconciliationError("Unknown reconciliation mode")
    bootstrap_revision = state_revision(bootstrap_state)
    environment_revision = state_revision(environment_state)
    entries: list[dict[str, Any]] = []
    optional_missing = False
    if mode == "reconcile":
        validate_environment_marker(environment_state, environment)
        environment_principal = ensure_string(
            state_output(environment_state, "environment_targets", ["lightsail_principal_arn"], environment)
        )
        bootstrap_principal = ensure_string(
            state_output(bootstrap_state, "runtime_lightsail_principal_arns", [environment], environment),
            optional=True,
        )
        bootstrap_runtime = ensure_string(
            state_output(bootstrap_state, "identity_app_role_arns", [f"{environment}_runtime"], environment),
            optional=True,
        )
        environment_runtime = ensure_string(
            state_output(environment_state, "environment_targets", ["runtime_role_arn"], environment),
            optional=True,
        )
        principal_handoff_matches = bootstrap_principal == environment_principal
        runtime_handoff_matches = (
            principal_handoff_matches
            and bootstrap_runtime is not None
            and environment_runtime == bootstrap_runtime
        )
        optional_missing = not runtime_handoff_matches
        for mapping in allowlist["mappings"]:
            source_state = bootstrap_state if mapping["source"] == "bootstrap" else environment_state
            value = ensure_string(
                state_output(source_state, mapping["output"], mapping["path"], environment),
                optional=bool(mapping.get("optional_first_stage")),
            )
            if mapping.get("optional_first_stage") and not principal_handoff_matches:
                value = None
            validate_generated_scalar(mapping["variable"], value)
            for target_template in mapping["targets"]:
                entries.append(
                    {
                        "target": target_template.format(environment=environment),
                        "variable": mapping["variable"],
                        "value": value,
                    }
                )
    else:
        resources = environment_state.get("resources")
        if not isinstance(resources, list) or resources:
            raise ReconciliationError("Destroy invalidation requires a confirmed empty environment state")
        invalidation = set(allowlist["destroy_invalidation_variables"])
        for mapping in allowlist["mappings"]:
            if mapping["variable"] not in invalidation:
                continue
            for target_template in mapping["targets"]:
                entries.append(
                    {
                        "target": target_template.format(environment=environment),
                        "variable": mapping["variable"],
                        "value": None,
                    }
                )
    return {
        "schema_version": 1,
        "environment": environment,
        "mode": mode,
        "bootstrap_revision": bootstrap_revision,
        "environment_revision": environment_revision,
        "optional_first_stage_missing": optional_missing,
        "entries": entries,
    }


def plan_configuration_digest(plan: dict[str, Any]) -> str:
    return digest(
        [
            {
                "target": item["target"],
                "variable": item["variable"],
                "value_digest": digest(item["value"]),
            }
            for item in plan["entries"]
        ]
    )


def validate_plan_shape(allowlist: dict[str, Any], plan: dict[str, Any], environment: str) -> None:
    if (
        plan.get("schema_version") != 1
        or plan.get("environment") != environment
        or plan.get("mode") not in {"reconcile", "invalidate"}
        or not isinstance(plan.get("bootstrap_revision"), dict)
        or not isinstance(plan.get("environment_revision"), dict)
        or not isinstance(plan.get("entries"), list)
    ):
        raise ReconciliationError("Mutation plan metadata is invalid")
    state_revision(plan["bootstrap_revision"])
    state_revision(plan["environment_revision"])
    invalidation = set(allowlist["destroy_invalidation_variables"])
    expected_pairs: list[tuple[str, str]] = []
    optional_variables: set[str] = set()
    for mapping in allowlist["mappings"]:
        if plan["mode"] == "invalidate" and mapping["variable"] not in invalidation:
            continue
        if mapping.get("optional_first_stage"):
            optional_variables.add(mapping["variable"])
        expected_pairs.extend(
            (target.format(environment=environment), mapping["variable"])
            for target in mapping["targets"]
        )
    actual_pairs: list[tuple[str, str]] = []
    for entry in plan["entries"]:
        if not isinstance(entry, dict) or set(entry) != {"target", "variable", "value"}:
            raise ReconciliationError("Mutation plan entry is invalid")
        target = entry["target"]
        variable = entry["variable"]
        value = entry["value"]
        if not isinstance(target, str) or not isinstance(variable, str):
            raise ReconciliationError("Mutation plan target is invalid")
        if value is not None and not isinstance(value, str):
            raise ReconciliationError("Mutation plan value is invalid")
        if plan["mode"] == "invalidate" and value is not None:
            raise ReconciliationError("Invalidation plan must only remove generated values")
        if plan["mode"] == "reconcile" and value is None and variable not in optional_variables:
            raise ReconciliationError("Required reconciliation value is absent")
        validate_generated_scalar(variable, value)
        actual_pairs.append((target, variable))
    if actual_pairs != expected_pairs:
        raise ReconciliationError("Mutation plan does not match the fixed output mapping")


@dataclass
class ApiResponse:
    status: int
    data: Any


class GitHubClient:
    def __init__(self, token: str, api_url: str = "https://api.github.com") -> None:
        if not token:
            raise ReconciliationError("GitHub authentication is unavailable")
        self.token = token
        self.api_url = api_url.rstrip("/")

    def request(self, method: str, path: str, payload: Any = None, allowed: tuple[int, ...] = (200,)) -> ApiResponse:
        body = canonical(payload) if payload is not None else None
        request = urllib.request.Request(
            self.api_url + path,
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                data = json.loads(raw) if raw else None
                result = ApiResponse(response.status, data)
        except urllib.error.HTTPError as exc:
            exc.read()
            result = ApiResponse(exc.code, None)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ReconciliationError("GitHub API request failed") from exc
        if result.status not in allowed:
            raise ReconciliationError(f"GitHub API request failed with status {result.status}")
        return result


def variable_path(repository: str, environment: str, variable: str | None = None) -> str:
    owner, repo = repository.split("/", 1)
    base = f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/environments/{urllib.parse.quote(environment)}/variables"
    return base if variable is None else base + "/" + urllib.parse.quote(variable)


def get_variable(client: GitHubClient, repository: str, target: str, name: str) -> str | None:
    response = client.request("GET", variable_path(repository, target, name), allowed=(200, 404))
    if response.status == 404:
        return None
    value = response.data.get("value") if isinstance(response.data, dict) else None
    if not isinstance(value, str):
        raise ReconciliationError("GitHub variable read-back was invalid")
    return value


def set_variable(client: GitHubClient, repository: str, target: str, name: str, value: str | None) -> str:
    current = get_variable(client, repository, target, name)
    if value is None:
        if current is None:
            return "absent"
        client.request("DELETE", variable_path(repository, target, name), allowed=(204,))
        if get_variable(client, repository, target, name) is not None:
            raise ReconciliationError("GitHub variable deletion read-back did not match")
        return "deleted"
    if current == value:
        return "no-change"
    if current is None:
        client.request("POST", variable_path(repository, target), {"name": name, "value": value}, allowed=(201,))
        status = "created"
    else:
        client.request("PATCH", variable_path(repository, target, name), {"name": name, "value": value}, allowed=(204,))
        status = "updated"
    if get_variable(client, repository, target, name) != value:
        raise ReconciliationError("GitHub variable write read-back did not match")
    return status


def list_secret_names(client: GitHubClient, repository: str, environment: str) -> set[str]:
    owner, repo = repository.split("/", 1)
    path = f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/environments/{urllib.parse.quote(environment)}/secrets?per_page=100"
    response = client.request("GET", path)
    secrets = response.data.get("secrets") if isinstance(response.data, dict) else None
    if not isinstance(secrets, list):
        raise ReconciliationError("GitHub secret inventory response was invalid")
    return {item["name"] for item in secrets if isinstance(item, dict) and isinstance(item.get("name"), str)}


def delete_secret(client: GitHubClient, repository: str, environment: str, name: str) -> str:
    names = list_secret_names(client, repository, environment)
    if name not in names:
        return "absent"
    owner, repo = repository.split("/", 1)
    path = f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/environments/{urllib.parse.quote(environment)}/secrets/{urllib.parse.quote(name)}"
    client.request("DELETE", path, allowed=(204,))
    if name in list_secret_names(client, repository, environment):
        raise ReconciliationError("GitHub secret deletion read-back did not match")
    return "deleted"


def safe_result(target: str, name: str, kind: str, status: str) -> dict[str, str]:
    return {"target": target, "name": name, "kind": kind, "status": status}


def prove_legacy_unused(allowlist: dict[str, Any], root: Path) -> dict[str, Any]:
    names = set(allowlist["legacy_variables"]) | set(allowlist["legacy_secrets"])
    references: dict[str, list[str]] = {}
    for relative in ACTIVE_RELEASE_FILES:
        path = root / relative
        if not path.is_file():
            raise ReconciliationError("Required active release file is missing")
        text = path.read_text(encoding="utf-8")
        for name in sorted(names):
            if name in text:
                references.setdefault(name, []).append(relative)
    if references:
        raise ReconciliationError("Legacy cleanup is blocked because an active release path still consumes an allowlisted name")
    return {
        "schema_version": 1,
        "files_digest": digest(
            {relative: hashlib.sha256((root / relative).read_bytes()).hexdigest() for relative in ACTIVE_RELEASE_FILES}
        ),
        "legacy_names_digest": digest(sorted(names)),
        "unused": True,
    }


def command_prepare(args: argparse.Namespace) -> int:
    allowlist = load_allowlist(args.allowlist)
    backend_fingerprint = digest(
        {
            "bucket": args.backend_bucket,
            "bootstrap_key": allowlist["bootstrap_state_key"],
            "environment_key": allowlist["environments"][args.environment]["environment_state_key"],
        }
    )
    evidence = initial_evidence(args.environment, args.mode, backend_fingerprint)
    try:
        bootstrap = read_json(args.bootstrap_state)
        environment_state = read_json(args.environment_state)
        plan = build_plan(allowlist, args.environment, args.mode, bootstrap, environment_state)
        evidence.update(
            {
                "status": "prepared",
                "bootstrap_state_revision": digest(plan["bootstrap_revision"]),
                "environment_state_revision": digest(plan["environment_revision"]),
                "configuration_digest": plan_configuration_digest(plan),
                "staged_handoff_complete": not plan["optional_first_stage_missing"],
            }
        )
        write_private_json(args.plan, plan)
    except ReconciliationError:
        evidence.update({"status": "invalid-input", "failure": True})
        write_private_json(args.evidence, evidence)
        print("Reconciliation preparation failed closed", file=sys.stderr)
        return 1
    write_private_json(args.evidence, evidence)
    print(f"Prepared {args.environment} {args.mode}; configuration digest {evidence['configuration_digest'][:19]}...")
    return 0


def command_prove_legacy(args: argparse.Namespace) -> int:
    allowlist = load_allowlist(args.allowlist)
    proof = prove_legacy_unused(allowlist, Path(args.root))
    write_private_json(args.proof, proof)
    print(f"Legacy release usage proof: {proof['files_digest'][:19]}...")
    return 0


def command_mutate(args: argparse.Namespace) -> int:
    allowlist = load_allowlist(args.allowlist)
    plan = read_json(args.plan)
    evidence = read_json(args.evidence)
    validate_plan_shape(allowlist, plan, args.environment)
    if (
        evidence.get("environment") != args.environment
        or evidence.get("status") != "prepared"
        or evidence.get("configuration_digest") != plan_configuration_digest(plan)
    ):
        raise ReconciliationError("Mutation inputs do not match the checked-in allowlist")
    client = GitHubClient(args.token, args.api_url)
    results: list[dict[str, str]] = []
    failed = False
    for entry in plan["entries"]:
        target = entry["target"]
        name = entry["variable"]
        try:
            status = set_variable(client, args.repository, target, name, entry["value"])
        except ReconciliationError:
            status = "failed"
            failed = True
        results.append(safe_result(target, name, "generated-variable", status))
        print(f"{target} {name}: {status}")
    evidence["results"] = results
    evidence["failure"] = bool(evidence.get("failure")) or failed
    evidence["status"] = "mutation-failed" if failed else "mutated"
    write_private_json(args.evidence, evidence)
    return 1 if failed else 0


def command_verify(args: argparse.Namespace) -> int:
    allowlist = load_allowlist(args.allowlist)
    plan = read_json(args.plan)
    evidence = read_json(args.evidence)
    try:
        validate_plan_shape(allowlist, plan, args.environment)
        bootstrap = read_json(args.bootstrap_state)
        environment_state = read_json(args.environment_state)
        rebuilt_plan = build_plan(allowlist, args.environment, plan["mode"], bootstrap, environment_state)
        if canonical(rebuilt_plan) != canonical(plan):
            raise ReconciliationError("Terraform outputs no longer match the mutation plan")
        if state_revision(bootstrap) != plan["bootstrap_revision"] or state_revision(environment_state) != plan["environment_revision"]:
            raise ReconciliationError("Terraform state changed during reconciliation")
        configuration_digest = plan_configuration_digest(plan)
        if evidence.get("configuration_digest") != configuration_digest:
            raise ReconciliationError("Reconciliation evidence does not match the mutation plan")
        client = GitHubClient(args.token, args.api_url)
        mismatches: list[dict[str, str]] = []
        for entry in plan["entries"]:
            try:
                current = get_variable(client, args.repository, entry["target"], entry["variable"])
                matches = current == entry["value"]
            except ReconciliationError:
                matches = False
            if not matches:
                mismatches.append(safe_result(entry["target"], entry["variable"], "generated-variable", "mismatch"))
        if mismatches:
            evidence["results"].extend(mismatches)
            evidence["failure"] = True
        if evidence.get("failure"):
            evidence.update({"status": "failed", "ready": False})
        elif plan["mode"] == "invalidate":
            evidence.update({"status": "invalidated", "ready": False, "staged_handoff_complete": False})
        elif plan["optional_first_stage_missing"]:
            evidence.update({"status": "incomplete-first-stage", "ready": False, "staged_handoff_complete": False})
        else:
            evidence.update({"status": "ready", "ready": True, "staged_handoff_complete": True})
        if not evidence.get("failure"):
            evidence["verified_configuration_digest"] = configuration_digest
    except ReconciliationError:
        evidence.update({"status": "failed", "ready": False, "failure": True})
    write_private_json(args.evidence, evidence)
    print(f"{args.environment} reconciliation status: {evidence['status']}")
    print(f"State revision digest: {evidence.get('environment_state_revision', '')[:19]}...")
    return 1 if evidence.get("failure") else 0


def active_release_run_ids(client: GitHubClient, repository: str) -> set[str]:
    owner, repo = repository.split("/", 1)
    active: set[str] = set()
    workflow_names = (
        "fullstack-release.yml",
        "deploy-production.yml",
        "rollback-development.yml",
        "frontend-production-deploy.yml",
    )
    for workflow in workflow_names:
        quoted = urllib.parse.quote(workflow)
        for status in ("in_progress", "queued", "waiting", "pending"):
            path = (
                f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}"
                f"/actions/workflows/{quoted}/runs?status={status}&per_page=100"
            )
            response = client.request("GET", path)
            runs = response.data.get("workflow_runs") if isinstance(response.data, dict) else None
            if not isinstance(runs, list):
                raise ReconciliationError("GitHub workflow inventory response was invalid")
            active.update(str(run["id"]) for run in runs if isinstance(run, dict) and "id" in run)
    return active


def command_cleanup_legacy(args: argparse.Namespace) -> int:
    allowlist = load_allowlist(args.allowlist)
    evidence = read_json(args.evidence)
    proof = read_json(args.legacy_proof)
    expected_proof = prove_legacy_unused(allowlist, Path(args.root))
    if proof != expected_proof or evidence.get("environment") != args.environment:
        raise ReconciliationError("Legacy cleanup inputs do not match the checked-in proof")
    if evidence.get("failure") or evidence.get("status") not in {"ready", "incomplete-first-stage", "invalidated"}:
        raise ReconciliationError("Legacy cleanup requires a verified reconciliation boundary")
    client = GitHubClient(args.token, args.api_url)
    active = active_release_run_ids(client, args.repository)
    active.discard(os.environ.get("GITHUB_RUN_ID", ""))
    if active:
        raise ReconciliationError("Legacy cleanup is blocked while a release or rollback workflow is active")
    results = list(evidence.get("results") or [])
    failed = False
    for name in allowlist["legacy_variables"]:
        try:
            status = set_variable(client, args.repository, args.environment, name, None)
        except ReconciliationError:
            status = "failed"
            failed = True
        results.append(safe_result(args.environment, name, "legacy-variable", status))
        print(f"{args.environment} {name}: {status}")
    for name in allowlist["legacy_secrets"]:
        try:
            status = delete_secret(client, args.repository, args.environment, name)
        except ReconciliationError:
            status = "failed"
            failed = True
        results.append(safe_result(args.environment, name, "legacy-secret", status))
        print(f"{args.environment} {name}: {status}")
    evidence["results"] = results
    evidence["failure"] = bool(evidence.get("failure")) or failed
    if failed:
        evidence.update({"status": "failed", "ready": False})
    else:
        evidence["legacy_cleanup_digest"] = digest(
            {"variables": sorted(allowlist["legacy_variables"]), "secrets": sorted(allowlist["legacy_secrets"])}
        )
    write_private_json(args.evidence, evidence)
    return 1 if failed else 0


def deployment_base(repository: str) -> str:
    owner, repo = repository.split("/", 1)
    return f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/deployments"


def publish_record(client: GitHubClient, repository: str, payload: dict[str, Any], state: str) -> None:
    environment = payload["environment"]
    response = client.request(
        "POST",
        deployment_base(repository),
        {
            "ref": payload.get("source_commit") or os.environ.get("GITHUB_SHA", ""),
            "environment": environment,
            "auto_merge": False,
            "required_contexts": [],
            "production_environment": environment == "production",
            "payload": payload,
            "description": "Generated output readiness record",
        },
        allowed=(201,),
    )
    deployment_id = response.data.get("id") if isinstance(response.data, dict) else None
    if not isinstance(deployment_id, int):
        raise ReconciliationError("GitHub deployment record response was invalid")
    client.request(
        "POST",
        deployment_base(repository) + f"/{deployment_id}/statuses",
        {
            "state": state,
            "environment": environment,
            "log_url": os.environ.get("RUN_URL", ""),
            "description": "Generated output readiness recorded",
            "auto_inactive": False,
        },
        allowed=(201,),
    )


def command_publish(args: argparse.Namespace) -> int:
    evidence = read_json(args.evidence)
    if evidence.get("record_type") != RECORD_TYPE or evidence.get("environment") != args.environment:
        raise ReconciliationError("Evidence record is invalid")
    payload = {key: value for key, value in evidence.items() if key != "results"}
    client = GitHubClient(args.token, args.api_url)
    publish_record(client, args.repository, payload, "failure" if evidence.get("failure") else "success")
    print(f"Published {args.environment} readiness record: {evidence.get('status')}")
    return 0


def command_pending(args: argparse.Namespace) -> int:
    if args.environment not in ALLOWED_ENVIRONMENTS:
        raise ReconciliationError("Unknown environment")
    allowlist = load_allowlist(args.allowlist)
    backend_fingerprint = digest(
        {
            "bucket": args.backend_bucket,
            "bootstrap_key": allowlist["bootstrap_state_key"],
            "environment_key": allowlist["environments"][args.environment]["environment_state_key"],
        }
    )
    payload = initial_evidence(args.environment, "pending-terraform", backend_fingerprint)
    payload.update({"status": "pending-terraform", "failure": False})
    client = GitHubClient(args.token, args.api_url)
    publish_record(client, args.repository, payload, "pending")
    print(f"Invalidated older {args.environment} readiness before Terraform mutation")
    return 0


def latest_status(client: GitHubClient, repository: str, deployment_id: int) -> dict[str, Any] | None:
    response = client.request("GET", deployment_base(repository) + f"/{deployment_id}/statuses?per_page=100")
    statuses = response.data
    if not isinstance(statuses, list) or not statuses:
        return None
    return statuses[0] if isinstance(statuses[0], dict) else None


def command_gate(args: argparse.Namespace) -> int:
    if args.environment not in ALLOWED_ENVIRONMENTS:
        raise ReconciliationError("Unknown environment")
    client = GitHubClient(args.token, args.api_url)
    query = urllib.parse.urlencode({"environment": args.environment, "per_page": 100})
    response = client.request("GET", deployment_base(args.repository) + "?" + query)
    deployments = response.data
    if not isinstance(deployments, list):
        raise ReconciliationError("GitHub readiness inventory response was invalid")
    records = []
    for deployment in deployments:
        if not isinstance(deployment, dict):
            continue
        payload = deployment.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        if isinstance(payload, dict) and payload.get("record_type") == RECORD_TYPE:
            records.append((deployment, payload))
    if not records:
        raise ReconciliationError("No generated-output readiness record exists")
    deployment, payload = max(records, key=lambda item: int(item[0].get("id", 0)))
    status = latest_status(client, args.repository, int(deployment["id"]))
    deployment_creator = deployment.get("creator")
    status_creator = status.get("creator") if isinstance(status, dict) else None
    publisher_login = deployment_creator.get("login") if isinstance(deployment_creator, dict) else None
    publisher_is_protected_app = (
        isinstance(publisher_login, str)
        and publisher_login.endswith("[bot]")
        and publisher_login != "github-actions[bot]"
        and deployment_creator.get("type") == "Bot"
        and isinstance(status_creator, dict)
        and status_creator.get("login") == publisher_login
    )
    valid = (
        payload.get("record_schema_version") == RECORD_SCHEMA_VERSION
        and payload.get("environment") == args.environment
        and payload.get("source_commit") == args.expected_source_commit
        and payload.get("ready") is True
        and payload.get("status") == "ready"
        and payload.get("staged_handoff_complete") is True
        and isinstance(payload.get("backend_fingerprint"), str)
        and payload["backend_fingerprint"].startswith("sha256:")
        and isinstance(payload.get("bootstrap_state_revision"), str)
        and payload["bootstrap_state_revision"].startswith("sha256:")
        and isinstance(payload.get("environment_state_revision"), str)
        and payload["environment_state_revision"].startswith("sha256:")
        and isinstance(payload.get("configuration_digest"), str)
        and payload["configuration_digest"].startswith("sha256:")
        and payload.get("verified_configuration_digest") == payload.get("configuration_digest")
        and isinstance(payload.get("legacy_cleanup_digest"), str)
        and payload["legacy_cleanup_digest"].startswith("sha256:")
        and isinstance(status, dict)
        and status.get("state") == "success"
        and publisher_is_protected_app
    )
    if not valid:
        raise ReconciliationError("The latest generated-output readiness record is not eligible")
    print(f"Current {args.environment} generated-output readiness is verified")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    subparsers = result.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--allowlist", required=True)
    prepare.add_argument("--environment", required=True, choices=sorted(ALLOWED_ENVIRONMENTS))
    prepare.add_argument("--mode", required=True, choices=("reconcile", "invalidate"))
    prepare.add_argument("--bootstrap-state", required=True)
    prepare.add_argument("--environment-state", required=True)
    prepare.add_argument("--backend-bucket", required=True)
    prepare.add_argument("--plan", required=True)
    prepare.add_argument("--evidence", required=True)
    prepare.set_defaults(func=command_prepare)

    proof = subparsers.add_parser("prove-legacy-unused")
    proof.add_argument("--allowlist", required=True)
    proof.add_argument("--root", required=True)
    proof.add_argument("--proof", required=True)
    proof.set_defaults(func=command_prove_legacy)

    mutate = subparsers.add_parser("mutate")
    mutate.add_argument("--allowlist", required=True)
    mutate.add_argument("--environment", required=True, choices=sorted(ALLOWED_ENVIRONMENTS))
    mutate.add_argument("--repository", required=True)
    mutate.add_argument("--token", required=True)
    mutate.add_argument("--plan", required=True)
    mutate.add_argument("--evidence", required=True)
    mutate.set_defaults(func=command_mutate)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--allowlist", required=True)
    verify.add_argument("--environment", required=True, choices=sorted(ALLOWED_ENVIRONMENTS))
    verify.add_argument("--repository", required=True)
    verify.add_argument("--token", required=True)
    verify.add_argument("--plan", required=True)
    verify.add_argument("--evidence", required=True)
    verify.add_argument("--bootstrap-state", required=True)
    verify.add_argument("--environment-state", required=True)
    verify.set_defaults(func=command_verify)

    cleanup = subparsers.add_parser("cleanup-legacy")
    cleanup.add_argument("--allowlist", required=True)
    cleanup.add_argument("--environment", required=True, choices=sorted(ALLOWED_ENVIRONMENTS))
    cleanup.add_argument("--repository", required=True)
    cleanup.add_argument("--token", required=True)
    cleanup.add_argument("--root", required=True)
    cleanup.add_argument("--legacy-proof", required=True)
    cleanup.add_argument("--evidence", required=True)
    cleanup.set_defaults(func=command_cleanup_legacy)

    publish = subparsers.add_parser("publish")
    publish.add_argument("--environment", required=True, choices=sorted(ALLOWED_ENVIRONMENTS))
    publish.add_argument("--repository", required=True)
    publish.add_argument("--token", required=True)
    publish.add_argument("--evidence", required=True)
    publish.set_defaults(func=command_publish)

    pending = subparsers.add_parser("pending")
    pending.add_argument("--environment", required=True, choices=sorted(ALLOWED_ENVIRONMENTS))
    pending.add_argument("--allowlist", required=True)
    pending.add_argument("--repository", required=True)
    pending.add_argument("--token", required=True)
    pending.add_argument("--backend-bucket", required=True)
    pending.set_defaults(func=command_pending)

    gate = subparsers.add_parser("gate")
    gate.add_argument("--environment", required=True, choices=sorted(ALLOWED_ENVIRONMENTS))
    gate.add_argument("--repository", required=True)
    gate.add_argument("--token", required=True)
    gate.add_argument("--expected-source-commit", required=True)
    gate.set_defaults(func=command_gate)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        return args.func(args)
    except ReconciliationError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
