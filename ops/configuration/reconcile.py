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


class ReconciliationError(Exception):
    """A fixed, value-free error safe for public reports."""


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


def select_mappings(mappings, selection):
    if selection == "all":
        return mappings
    if selection != "preflight":
        raise ReconciliationError("Unsupported mapping selection")
    selected = [
        m
        for m in mappings
        if m.env_name in PREFLIGHT_FIELDS
        and m.github_environment.endswith(("-plan", "-apply"))
    ]
    if {m.env_name for m in selected} != PREFLIGHT_FIELDS or any(
        m.secret for m in selected
    ):
        raise ReconciliationError("Incomplete preflight mapping")
    return selected


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


def configuration_outputs(values, selection):
    allowed = PREFLIGHT_FIELDS | FRONTEND_FIELDS
    configuration = {name: value for name, value in values.items() if name in allowed}
    frontend = {}
    if selection == "all":
        if not FRONTEND_FIELDS <= configuration.keys():
            raise ReconciliationError("Incomplete frontend configuration")
        frontend = {name: configuration[name] for name in sorted(FRONTEND_FIELDS)}
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
            elif target not in (selected, f"{selected}-plan", f"{selected}-apply"):
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
        except Exception as error:  # noqa: BLE001 - never render SDK payloads
            if (
                getattr(error, "response", {}).get("Error", {}).get("Code")
                == "ParameterNotFound"
            ):
                return None
            raise ReconciliationError("Parameter Store access failed") from None
        expected = "SecureString" if mapping.secret else "String"
        if (
            parameter.get("Type") != expected
            or not isinstance(parameter.get("Value"), str)
            or not parameter["Value"]
        ):
            raise ReconciliationError("Parameter type or value is invalid")
        return parameter["Value"]


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
            raise ReconciliationError("GitHub API request failed") from None
        except (URLError, OSError, ValueError):
            raise ReconciliationError(
                "GitHub API transport or response failed"
            ) from None

    def variable(self, mapping: Mapping, value: str) -> str:
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
            self.request("POST", root, {"name": mapping.env_name, "value": value})
            status = "created"
        elif current.get("value") != value:
            self.request("PATCH", path, {"name": mapping.env_name, "value": value})
            status = "updated"
        readback = self.request("GET", path)
        if (
            not isinstance(readback, dict)
            or readback.get("name") != mapping.env_name
            or readback.get("value") != value
        ):
            raise ReconciliationError("GitHub variable read-back failed")
        return status

    def secret(self, mapping: Mapping, value: str) -> str:
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
        self.request("PUT", f"{root}/{quote(mapping.env_name, safe='')}", payload)
        return "secret-write-accepted"


def reconcile(
    mappings: list[Mapping],
    store: ParameterStore,
    github: GitHub,
    report=print,
    mode="audit",
    environment="development",
    selection=None,
):
    if mode not in ("audit", "enforce"):
        raise ReconciliationError("Unsupported reconciliation mode")
    completed = 0
    # Never let a variable/secret write implicitly establish an unprotected target.
    # Validate all exact targets first, even when their sources will be absent.
    for target in sorted({mapping.github_environment for mapping in mappings}):
        github.request("GET", f"environments/{quote(target, safe='')}")
    loaded = []
    values = {}
    for mapping in mappings:
        try:
            value = store.read(mapping)
        except ReconciliationError:
            report(
                f"FAILED source {mapping.github_environment}/{mapping.env_name}; no writes started"
            )
            raise
        if value is None:
            report(
                f"WARNING missing-source {mapping.github_environment}/{mapping.env_name}"
            )
            if mode == "enforce" and "required" in mapping.validations:
                raise ReconciliationError("Required configuration is missing")
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
    if mode == "enforce" and selection is not None:
        configuration_outputs(values, selection)
    for mapping, value in loaded:
        name = f"{mapping.github_environment}/{mapping.env_name}"
        try:
            status = (
                github.secret(mapping, value)
                if mapping.secret
                else github.variable(mapping, value)
            )
            completed += 1
            report(f"{status} {name}")
        except ReconciliationError:
            report(
                f"FAILED {name}; completed-targets={completed}; rerun after correcting the failure"
            )
            raise
    report(
        "Audit completed; this does not establish release readiness"
        if mode == "audit"
        else "Enforced preflight completed; publication remains blocked until successful apply and full reconciliation"
        if selection == "preflight"
        else "Publication configuration values verified; existing apply and promotion gates still apply"
    )
    return values


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--environment", required=True, choices=("development", "production")
    )
    parser.add_argument("--mode", default="audit", choices=("audit", "enforce"))
    parser.add_argument("--selection", default="all", choices=("all", "preflight"))
    parser.add_argument(
        "--mapping",
        type=Path,
        default=Path(__file__).with_name("parameter-mapping.yaml"),
    )
    arguments = parser.parse_args(argv)
    try:
        mappings = select_mappings(
            load_mappings(arguments.mapping, arguments.environment), arguments.selection
        )
        github = GitHub(
            os.environ.get("GITHUB_REPOSITORY", ""),
            os.environ.get("PAWLOCAL_CONFIG_GITHUB_TOKEN", ""),
        )
        import boto3

        values = reconcile(
            mappings,
            ParameterStore(boto3.client("ssm")),
            github,
            mode=arguments.mode,
            environment=arguments.environment,
            selection=arguments.selection if arguments.mode == "enforce" else None,
        )
        if arguments.mode == "enforce" and os.environ.get("GITHUB_OUTPUT"):
            outputs = configuration_outputs(values, arguments.selection)
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                output.writelines(
                    f"{name}={json.dumps(value, separators=(',', ':'))}\n"
                    for name, value in outputs.items()
                )
    except ReconciliationError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - final non-disclosure boundary
        # SDK/library exceptions can contain response payloads. Never render them.
        print(
            "Reconciliation failed; inspect configuration and permissions privately",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
