"""Allowlisted Parameter Store -> GitHub Environment reconciliation.

Reports contain names/statuses only. Audit warns about missing values;
enforce validates all selected values before writing. Existing release gates remain.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

import yaml
from job_summary import Report


class ReconciliationError(Exception):
    """A reconciliation failure with operational context for Actions logs."""

    mutation_rejected = False


PREFLIGHT_FIELDS = frozenset(
    {
        "PAWLOCAL_TERRAFORM_PLAN_ROLE_ARN",
        "PAWLOCAL_TERRAFORM_APPLY_ROLE_ARN",
        "PAWLOCAL_AWS_ACCOUNT_ID",
        "PAWLOCAL_TERRAFORM_PLAN_BUCKET",
        "PAWLOCAL_RUNTIME_ROLE_ARN",
        "PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ARN",
        "PAWLOCAL_CLOUDFRONT_OAC_ARN",
    }
)
FRONTEND_FIELDS = frozenset(
    {
        "PAWLOCAL_DEPLOY_ROLE_ARN",
        "PAWLOCAL_PUBLIC_BASE_URL",
        "PAWLOCAL_API_HEALTH_URL",
        "PAWLOCAL_FRONTEND_BUCKET",
        "PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID",
        "VITE_API_BASE_URL",
        "VITE_COGNITO_DOMAIN",
        "VITE_COGNITO_CLIENT_ID",
        "VITE_COGNITO_REDIRECT_URI",
        "VITE_COGNITO_LOGOUT_URI",
        "VITE_COGNITO_SCOPES",
    }
)


def inventory_mappings(environment):
    return load_mappings(
        Path(__file__).with_name("parameter-mapping.yaml"), environment
    )


def validate_values(values, environment):
    """Validate canonical public formats without logging values or inventing IDs."""
    account = values.get("PAWLOCAL_AWS_ACCOUNT_ID")
    if account is not None and not re.fullmatch(r"[0-9]{12}", account):
        raise ReconciliationError("Invalid account configuration")
    role_suffixes = {
        "PAWLOCAL_TERRAFORM_PLAN_ROLE_ARN": "terraform-plan",
        "PAWLOCAL_TERRAFORM_APPLY_ROLE_ARN": "terraform-apply",
        "PAWLOCAL_RUNTIME_ROLE_ARN": "dsql-runtime",
        "PAWLOCAL_DEPLOY_ROLE_ARN": "github-deploy",
    }
    for name, value in values.items():
        if not value or any(character in value for character in ("\n", "\r", "\x00")):
            raise ReconciliationError("Invalid public configuration value")
        if name == "VITE_COGNITO_CLIENT_ID" and not re.fullmatch(
            r"[A-Za-z0-9_-]+", value
        ):
            raise ReconciliationError("Invalid public client ID")
        if name == "PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID" and not re.fullmatch(
            r"[A-Z0-9]+", value
        ):
            raise ReconciliationError("Invalid distribution ID")
        if name == "PAWLOCAL_FRONTEND_BUCKET" and (
            not value.startswith(f"pawlocal-{environment}-")
            or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", value)
        ):
            raise ReconciliationError("Invalid matching frontend bucket")
        if name in role_suffixes:
            role = re.fullmatch(
                rf"arn:aws:iam::([0-9]{{12}}):role/pawlocal-{environment}-{role_suffixes[name]}",
                value,
            )
            if role is None or (account and role[1] != account):
                raise ReconciliationError("Role account or environment mismatch")
        if name in {
            "PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ARN",
            "PAWLOCAL_CLOUDFRONT_OAC_ARN",
        }:
            resource = (
                "distribution"
                if name.endswith("DISTRIBUTION_ARN")
                else "origin-access-control"
            )
            arn = re.fullmatch(
                rf"arn:aws:cloudfront::([0-9]{{12}}):{resource}/[A-Z0-9]+", value
            )
            if arn is None or (account and arn[1] != account):
                raise ReconciliationError("CloudFront account or ARN mismatch")
        if (
            name == "PAWLOCAL_TERRAFORM_PLAN_BUCKET"
            and account
            and value != f"pawlocal-terraform-plans-{account}"
        ):
            raise ReconciliationError("Plan bucket account mismatch")
        if name in {
            "PAWLOCAL_PUBLIC_BASE_URL",
            "PAWLOCAL_API_HEALTH_URL",
            "VITE_API_BASE_URL",
            "VITE_COGNITO_DOMAIN",
            "VITE_COGNITO_REDIRECT_URI",
            "VITE_COGNITO_LOGOUT_URI",
        }:
            try:
                url = urlsplit(value)
                invalid = (
                    url.scheme != "https"
                    or not url.hostname
                    or url.username
                    or url.password
                    or url.query
                    or url.fragment
                    or url.port
                )
            except ValueError:
                raise ReconciliationError("Invalid HTTPS configuration") from None
            if invalid:
                raise ReconciliationError("Invalid HTTPS configuration")
            if name == "VITE_COGNITO_DOMAIN":
                if url.path or not re.fullmatch(
                    rf"pawlocal-{environment}-[a-z0-9-]+\.auth\.[a-z0-9-]+\.amazoncognito\.com",
                    url.hostname,
                ):
                    raise ReconciliationError("Invalid matching Cognito origin")
            else:
                frontend = (
                    "pawlocal-dev" if environment == "development" else "pawlocal"
                )
                api = "api-dev" if environment == "development" else "api"
                expected_label = (
                    api
                    if name in {"VITE_API_BASE_URL", "PAWLOCAL_API_HEALTH_URL"}
                    else frontend
                )
                expected_path = {
                    "VITE_API_BASE_URL": "/api/v1",
                    "PAWLOCAL_API_HEALTH_URL": "/health",
                    "VITE_COGNITO_REDIRECT_URI": "/auth/callback",
                    "VITE_COGNITO_LOGOUT_URI": "/",
                }.get(name, "")
                if (
                    not url.hostname.startswith(f"{expected_label}.")
                    or url.path != expected_path
                ):
                    raise ReconciliationError("Public URL environment or path mismatch")
                base = values.get("PAWLOCAL_PUBLIC_BASE_URL")
                if (
                    base
                    and url.hostname.split(".", 1)[1]
                    != urlsplit(base).hostname.split(".", 1)[1]
                ):
                    raise ReconciliationError("Public URL domain mismatch")
        if name == "VITE_COGNITO_SCOPES" and (
            "openid" not in value.split(" ")
            or len(value.split(" ")) != len(set(value.split(" ")))
            or not re.fullmatch(r"[a-z]+(?: [a-z]+)*", value)
        ):
            raise ReconciliationError("Invalid OAuth scopes")


def configuration_outputs(values):
    # These projections are existing release consumer contracts, not mapping
    # inventories. Reconciliation does not require an unrelated consumer's keys.
    configuration = {
        name: value
        for name, value in values.items()
        if name in PREFLIGHT_FIELDS | FRONTEND_FIELDS
    }
    frontend = (
        {name: values[name] for name in sorted(FRONTEND_FIELDS)}
        if FRONTEND_FIELDS <= values.keys()
        else {}
    )
    return {"configuration": configuration, "frontend_config": frontend}


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ReconciliationError("Invalid mapping: duplicate or non-string field")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping
)


@dataclass(frozen=True)
class Mapping:
    store_key: str
    github_environment: str
    env_name: str
    secret: bool
    validations: tuple[str, ...]


def load_mappings(path: Path, environment: str) -> list[Mapping]:
    if environment not in ("development", "production"):
        raise ReconciliationError("Unsupported environment")
    try:
        document = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueLoader)
    except (OSError, yaml.YAMLError):
        raise ReconciliationError("Cannot read valid mapping YAML") from None
    if (
        not isinstance(document, dict)
        or set(document) != {"mappings"}
        or not isinstance(document["mappings"], list)
    ):
        raise ReconciliationError("Invalid mapping document")
    resolved = {"development": [], "production": []}
    destinations = set()
    fields = {
        "store_key",
        "environment",
        "github_environment",
        "env_name",
        "secret",
        "validations",
    }
    for entry in document["mappings"]:
        if (
            not isinstance(entry, dict)
            or not set(entry) <= fields
            or not fields.difference({"secret", "validations"}) <= set(entry)
        ):
            raise ReconciliationError("Invalid mapping fields")
        environments = entry["environment"]
        if (
            not isinstance(environments, list)
            or not environments
            or any(not isinstance(e, str) or e not in resolved for e in environments)
            or len(set(environments)) != len(environments)
        ):
            raise ReconciliationError("Invalid mapping environment selection")
        secret = entry.get("secret", False)
        rules = entry.get("validations", [])
        if (
            type(secret) is not bool
            or not isinstance(rules, list)
            or any(rule != "required" for rule in rules)
            or len(set(rules)) != len(rules)
        ):
            raise ReconciliationError("Invalid secret flag or validation rule")
        if not isinstance(entry["env_name"], str) or not re.fullmatch(
            r"[A-Z][A-Z0-9_]*", entry["env_name"]
        ):
            raise ReconciliationError("Invalid GitHub configuration name")
        for selected in environments:
            substituted = []
            for field in ("store_key", "github_environment"):
                raw = entry[field]
                if not isinstance(raw, str):
                    raise ReconciliationError("Invalid source or target")
                value = raw.replace("{environment}", selected)
                if "{" in value or "}" in value:
                    raise ReconciliationError("Unsupported substitution")
                substituted.append(value)
            source, target = substituted
            classification = "secrets" if secret else "config"
            if not re.fullmatch(
                rf"/pawlocal/{selected}/{classification}/[a-z][a-z0-9]*(?:-[a-z0-9]+)*/[a-z][a-z0-9]*(?:-[a-z0-9]+)*",
                source,
            ):
                raise ReconciliationError("Forbidden source path or classification")
            recovery_targets = ("production-destroy-prepare", "production-destroy")
            recovery_sources = {
                "iam/terraform-apply-role-arn": "PAWLOCAL_TERRAFORM_APPLY_ROLE_ARN",
                "aws/account-id": "PAWLOCAL_AWS_ACCOUNT_ID",
                "terraform/plan-bucket": "PAWLOCAL_TERRAFORM_PLAN_BUCKET",
            }
            if target in recovery_targets:
                suffix = source.removeprefix("/pawlocal/production/config/")
                if (
                    selected != "production"
                    or secret
                    or recovery_sources.get(suffix) != entry["env_name"]
                ):
                    raise ReconciliationError("Forbidden production recovery mapping")
            elif (
                target not in (selected, f"{selected}-plan", f"{selected}-apply")
                and target != f"oncall-{selected}"
            ):
                raise ReconciliationError("Forbidden GitHub Environment target")
            destination = (selected, target, entry["env_name"])
            if destination in destinations:
                raise ReconciliationError("Duplicate GitHub destination")
            destinations.add(destination)
            resolved[selected].append(
                Mapping(source, target, entry["env_name"], secret, tuple(rules))
            )
    return resolved[environment]


class ParameterStore:
    def __init__(self, client):
        self.client = client

    def read(self, mapping: Mapping) -> str | None:
        try:
            parameter = self.client.get_parameter(
                Name=mapping.store_key, WithDecryption=mapping.secret
            )["Parameter"]
        except Exception as error:
            if (
                getattr(error, "response", {}).get("Error", {}).get("Code")
                == "ParameterNotFound"
            ):
                return None
            raise ReconciliationError(
                f"Parameter Store access failed: {error}"
            ) from error
        expected = "SecureString" if mapping.secret else "String"
        if (
            parameter.get("Type") != expected
            or not isinstance(parameter.get("Value"), str)
            or not parameter["Value"]
        ):
            raise ReconciliationError("Parameter type or value is invalid")
        return parameter["Value"]


def parameter_store():
    import boto3

    return ParameterStore(boto3.client("ssm"))


class GitHub:
    def __init__(self, repository: str, token: str, transport=urlopen):
        if repository != "alanlima/pawlocal" or not token:
            raise ReconciliationError(
                "Repository or scoped GitHub credential is invalid"
            )
        self.repository, self.token, self.transport = repository, token, transport

    def request(self, method: str, path: str, payload=None, missing=False):
        data = None if payload is None else json.dumps(payload).encode()
        request = Request(
            f"https://api.github.com/repos/{self.repository}/{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            with self.transport(request, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as error:
            if missing and error.code == 404:
                return None
            failure = ReconciliationError(f"GitHub API request failed: {error}")
            failure.mutation_rejected = 400 <= error.code < 500 and error.code != 408
            raise failure from error
        except (URLError, OSError, ValueError) as error:
            raise ReconciliationError(
                f"GitHub API transport or response failed: {error}"
            ) from error

    def mutate(self, method, path, payload=None, progress=None):
        if progress:
            progress("possible")
        try:
            self.request(method, path, payload)
        except ReconciliationError as error:
            if progress and error.mutation_rejected:
                progress("none")
            raise
        if progress:
            progress("accepted")

    def variable(self, mapping: Mapping, value: str, progress=None) -> str:
        root = f"environments/{quote(mapping.github_environment, safe='')}/variables"
        path = f"{root}/{quote(mapping.env_name, safe='')}"
        current = self.request("GET", path, missing=True)
        if current is not None and (
            not isinstance(current, dict)
            or current.get("name") != mapping.env_name
            or not isinstance(current.get("value"), str)
        ):
            raise ReconciliationError("GitHub variable response is invalid")
        status = "unchanged"
        if current is None:
            self.mutate(
                "POST", root, {"name": mapping.env_name, "value": value}, progress
            )
            status = "created"
        elif current.get("value") != value:
            self.mutate(
                "PATCH", path, {"name": mapping.env_name, "value": value}, progress
            )
            status = "updated"
        readback = self.request("GET", path)
        if (
            not isinstance(readback, dict)
            or readback.get("name") != mapping.env_name
            or readback.get("value") != value
        ):
            raise ReconciliationError("GitHub variable read-back failed")
        return status

    def secret(self, mapping: Mapping, value: str, progress=None) -> str:
        from nacl.public import PublicKey, SealedBox

        root = f"environments/{quote(mapping.github_environment, safe='')}/secrets"
        try:
            key = self.request("GET", f"{root}/public-key")
            encrypted = SealedBox(
                PublicKey(base64.b64decode(key["key"], validate=True))
            ).encrypt(value.encode())
            payload = {
                "encrypted_value": base64.b64encode(encrypted).decode(),
                "key_id": key["key_id"],
            }
        except (KeyError, ValueError, TypeError):
            raise ReconciliationError("GitHub secret encryption failed") from None
        self.mutate(
            "PUT", f"{root}/{quote(mapping.env_name, safe='')}", payload, progress
        )
        return "secret-write-accepted"


def reconcile(
    mappings: list[Mapping],
    store: ParameterStore,
    github: GitHub,
    report=print,
    mode="audit",
    environment="development",
    summary=None,
):
    if mode not in ("audit", "enforce"):
        raise ReconciliationError("Unsupported reconciliation mode")
    completed = 0
    if summary:
        summary.reason = (
            "Target Environment validation failed; no destination writes started."
        )
    # Never let a variable/secret write implicitly establish an unprotected target.
    # Validate all exact targets first, even when their sources will be absent.
    missing_targets = set()
    for target in sorted({mapping.github_environment for mapping in mappings}):
        target_path = f"environments/{quote(target, safe='')}"
        metadata = github.request("GET", target_path, missing=True)
        if metadata is None:
            missing_targets.add(target)
            report(f"WARNING missing-target {target}; source reads and writes skipped")
            if summary:
                for mapping in mappings:
                    if mapping.github_environment == target:
                        row = summary.row(mapping)
                        row.status = "Missing target"
                        row.diagnostic = "Missing target"
                        row.reason = "Target Environment does not exist; source was not read and target was not created."
            continue
        if target.startswith("oncall-"):
            if metadata.get("deployment_branch_policy") != {
                "protected_branches": False,
                "custom_branch_policies": True,
            }:
                raise ReconciliationError(
                    "On-call target must restrict deployments to exact main"
                )
            policies = github.request(
                "GET", f"{target_path}/deployment-branch-policies"
            )
            branches = policies.get("branch_policies", [])
            if (
                policies.get("total_count") != 1
                or len(branches) != 1
                or branches[0].get("name") != "main"
                or branches[0].get("type") != "branch"
            ):
                raise ReconciliationError(
                    "On-call target must allow only main branch, with no tag policy"
                )
    loaded = []
    values = {}
    if summary:
        summary.reason = "Source validation failed; no destination writes started."
    for mapping in mappings:
        if mapping.github_environment in missing_targets:
            continue
        try:
            value = store.read(mapping)
        except ReconciliationError:
            if summary:
                summary.row(mapping).diagnostic = "Source read failed"
                summary.row(
                    mapping
                ).reason = "Source read failed; no destination writes started."
            report(
                f"FAILED source {mapping.github_environment}/{mapping.env_name}; no writes started"
            )
            raise
        if value is None:
            if summary:
                row = summary.row(mapping)
                row.diagnostic = "Missing source"
                row.reason = "Parameter does not exist; destination write skipped."
                row.status = "Missing source"
            report(
                f"WARNING missing-source {mapping.github_environment}/{mapping.env_name}"
            )
            continue
        loaded.append((mapping, value))
        if not mapping.secret:
            if mapping.env_name in values and values[mapping.env_name] != value:
                raise ReconciliationError("Conflicting configuration destinations")
            values[mapping.env_name] = value
    validate_values(
        {
            name: value
            for name, value in values.items()
            if name in PREFLIGHT_FIELDS | FRONTEND_FIELDS
        },
        environment,
    )
    if summary:
        summary.reason = "Destination operation failed; completed actions remain; remaining writes were not attempted."
        for row in summary.rows.values():
            if row.diagnostic == "Missing optional source":
                row.status = row.diagnostic
    for mapping, value in loaded:
        name = f"{mapping.github_environment}/{mapping.env_name}"
        try:
            progress = (
                (lambda stage, current=mapping: summary.progress(current, stage))
                if summary
                else None
            )
            status = (
                github.secret(mapping, value, progress=progress)
                if mapping.secret
                else github.variable(mapping, value, progress=progress)
            )
            if summary:
                row = summary.row(mapping)
                row.status = {
                    "created": "Created",
                    "updated": "Updated",
                    "unchanged": "Unchanged",
                    "secret-write-accepted": "Secret write accepted",
                }[status]
                row.reason = (
                    "Encrypted write accepted; content cannot be compared or read back."
                    if mapping.secret
                    else "Variable comparison and readback matched."
                )
                row.mutation = (
                    "secret-accepted"
                    if mapping.secret
                    else "verified"
                    if status in {"created", "updated"}
                    else "none"
                )
            completed += 1
            report(f"{status} {name}")
        except Exception:
            if summary:
                summary.failure(
                    mapping,
                    "Destination operation failed; remaining writes not attempted.",
                )
            report(
                f"FAILED {name}; completed-targets={completed}; rerun after correcting the failure"
            )
            raise
    report(
        "Audit completed; this does not establish release readiness"
        if mode == "audit"
        else "Reconciliation completed; release consumers must check their required configuration"
    )
    return values


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--environment", required=True, choices=("development", "production")
    )
    parser.add_argument("--mode", default="audit", choices=("audit", "enforce"))
    arguments = parser.parse_args(argv)
    summary = Report(arguments.environment, arguments.mode, "parameter-mapping.yaml")
    status = 0
    try:
        summary.clear()
        inventory = inventory_mappings("development") + inventory_mappings("production")
        mappings = inventory_mappings(arguments.environment)
        summary.inventory_for(inventory, mappings)
        github = GitHub(
            os.environ.get("GITHUB_REPOSITORY", ""),
            os.environ.get("PAWLOCAL_CONFIG_GITHUB_TOKEN", ""),
        )
        values = reconcile(
            mappings,
            parameter_store(),
            github,
            mode=arguments.mode,
            environment=arguments.environment,
            summary=summary,
        )
        if arguments.mode == "enforce" and os.environ.get("GITHUB_OUTPUT"):
            summary.reason = "Workflow output writing failed; completed destination actions remain. Publication is blocked."
            outputs = configuration_outputs(values)
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                output.writelines(
                    f"{name}={json.dumps(value, separators=(',', ':'))}\n"
                    for name, value in outputs.items()
                )
        summary.succeeded()
    except ReconciliationError as error:
        print(str(error), file=sys.stderr)
        status = 1
    except Exception as error:  # noqa: BLE001 - keep standard operational errors
        print(
            f"Reconciliation failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        status = 1
    try:
        summary.write()
    except Exception as error:  # noqa: BLE001 - summary failure never authorizes publication
        print(f"Cannot write configuration summary: {error}", file=sys.stderr)
        status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
