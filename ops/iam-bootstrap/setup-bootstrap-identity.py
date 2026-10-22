"""Owner-operated #191 account prerequisite; never run from GitHub Actions.

Default inspect is read-only. Every mutation requires an explicit command.
Credentials exist only in process memory and gh secret set's standard input.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from policy import BOUNDARY, POLICIES, STATE_KEY, USER, compact, render, validate_config

REPO = "alanlima/pawlocal"
OWNER_ID = 4245961
REPO_ID = 1423024931
ENVIRONMENTS = ("iam-bootstrap-plan", "iam-bootstrap-apply")
READER_TARGETS = {"development": "development", "development-apply": "development",
                  "production": "production", "production-apply": "production"}
READER_VARIABLE = "PAWLOCAL_CONFIG_READER_ROLE_ARN"
SECRETS = ("PAWLOCAL_BOOTSTRAP_AWS_ACCESS_KEY_ID", "PAWLOCAL_BOOTSTRAP_AWS_SECRET_ACCESS_KEY")
TAGS = {"project": "pawlocal", "purpose": "terraform-iam-bootstrap", "owner": "alanlima",
        "lifecycle": "external-account-bootstrap-issue-191"}
AWS_OPERATIONS = {
    "sts": frozenset({"get-caller-identity"}),
    "iam": frozenset({
        "get-user", "get-role", "get-login-profile", "list-groups-for-user", "list-user-policies",
        "list-attached-user-policies", "create-user", "get-policy", "create-policy",
        "list-policy-tags", "get-policy-version", "create-policy-version",
        "put-user-permissions-boundary", "attach-user-policy", "list-access-keys",
        "create-access-key", "update-access-key", "delete-access-key",
    }),
}


class SetupError(Exception):
    """Fixed, value-free diagnostic safe for the operator's terminal."""


class CLI:
    def run(self, args, payload=None, missing_ok=False, expect_json=True):
        environment = dict(os.environ)
        # Do not allow credentials or gh HTTP traffic to appear in debug logs.
        for key in ("GH_DEBUG", "DEBUG", "AWS_CLI_AUTO_PROMPT"):
            environment.pop(key, None)
        environment["AWS_CLI_AUTO_PROMPT"] = "off"
        try:
            result = subprocess.run(args, input=payload, text=True, capture_output=True,
                                    env=environment, timeout=120, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise SetupError("Command unavailable or timed out; diagnostics withheld") from None
        if result.returncode:
            if missing_ok and "(NoSuchEntity)" in result.stderr:
                return None
            raise SetupError("Command failed; diagnostics withheld")
        if not expect_json:
            return {}
        try:
            return json.loads(result.stdout) if result.stdout.strip() else {}
        except (ValueError, TypeError):
            raise SetupError("Invalid command response; diagnostics withheld") from None

    def aws(self, service, operation, **kwargs):
        if operation not in AWS_OPERATIONS.get(service, ()):
            raise SetupError("AWS operation is outside the owner setup allowlist")
        missing_ok = kwargs.pop("missing_ok", False)
        args = ["aws", service, operation, "--output", "json", "--no-cli-pager"]
        # Payload contains identifiers/policies only, never credential values.
        if kwargs:
            args += ["--cli-input-json", compact(kwargs)]
        return self.run(args, missing_ok=missing_ok)

    def api(self, path, method="GET", payload=None):
        if method != "GET":
            allowed = {
                (verb, f"repos/{REPO}/environments/{target}/variables" +
                 ("/" + READER_VARIABLE if verb == "PATCH" else ""))
                for target in READER_TARGETS for verb in ("POST", "PATCH")
            }
            if (method, path) not in allowed or not isinstance(payload, dict) or set(payload) != {"name", "value"} or payload["name"] != READER_VARIABLE:
                raise SetupError("GitHub mutation is outside the reader-variable allowlist")
        elif payload is not None:
            raise SetupError("Unexpected GitHub read payload")
        args = ["gh", "api", path, "--method", method]
        if payload is not None:
            args += ["--input", "-"]
        return self.run(args, payload=compact(payload) if payload is not None else None)

    def read_bootstrap_state(self, config):
        validate_config(config)
        # S3 copy is read-only, and '-' means stdout: no plaintext state file.
        source = f"s3://{config['state_bucket']}/{STATE_KEY}"
        return self.run(["aws", "s3", "cp", source, "-", "--only-show-errors", "--no-cli-pager"])

    def secret(self, environment, name, value):
        # gh normally prints a success message: do not parse or emit it.
        args = ["gh", "secret", "set", name, "--repo", REPO, "--env", environment]
        self.run(args, payload=value, expect_json=False)


def verify_environments(cli):
    repo = cli.api(f"repos/{REPO}")
    if repo.get("id") != REPO_ID or repo.get("owner", {}).get("id") != OWNER_ID:
        raise SetupError("Unexpected GitHub repository identity")
    for name in ENVIRONMENTS:
        path = f"repos/{REPO}/environments/{name}"
        env = cli.api(path)
        if env.get("deployment_branch_policy") != {
                "protected_branches": False, "custom_branch_policies": True}:
            raise SetupError("Bootstrap Environment branch protection differs")
        branches = cli.api(path + "/deployment-branch-policies").get("branch_policies", [])
        if len(branches) != 1 or branches[0].get("name") != "main" or branches[0].get("type") != "branch":
            raise SetupError("Bootstrap Environment must allow only main branches")
        reviewers = [rule for rule in env.get("protection_rules", [])
                     if rule.get("type") == "required_reviewers"]
        if name.endswith("apply"):
            if env.get("can_admins_bypass") is not False or len(reviewers) != 1:
                raise SetupError("Apply Environment must require owner approval without bypass")
            rule = reviewers[0]
            identities = [(r.get("type"), r.get("reviewer", {}).get("id"))
                          for r in rule.get("reviewers", [])]
            if identities != [("User", OWNER_ID)] or rule.get("prevent_self_review") is not False:
                raise SetupError("Apply Environment must allow the sole owner to approve dispatch")
        elif reviewers:
            raise SetupError("Plan Environment unexpectedly requires approval")


def verify_operator(cli, config):
    caller = cli.aws("sts", "get-caller-identity")
    if caller.get("Account") != config["account_id"]:
        raise SetupError("Unexpected AWS account")
    arn = caller.get("Arn", "")
    if arn.endswith(":root") or arn.endswith(":user/" + USER):
        raise SetupError("Use an authorized owner operator identity, never root or workflow user")


def inspect_user(cli, config, required=True):
    response = cli.aws("iam", "get-user", UserName=USER, missing_ok=not required)
    if response is None:
        return None
    user = response.get("User", {})
    if user.get("Arn") != f"arn:aws:iam::{config['account_id']}:user/{USER}" or user.get("Path") != "/":
        raise SetupError("Existing bootstrap user identity differs")
    tags = {item["Key"]: item["Value"] for item in user.get("Tags", [])}
    if any(tags.get(k) != v for k, v in TAGS.items()):
        raise SetupError("Existing bootstrap user ownership tags differ")
    if cli.aws("iam", "get-login-profile", UserName=USER, missing_ok=True) is not None:
        raise SetupError("Bootstrap user must have no console login")
    if cli.aws("iam", "list-groups-for-user", UserName=USER).get("Groups"):
        raise SetupError("Bootstrap user must have no groups")
    if cli.aws("iam", "list-user-policies", UserName=USER).get("PolicyNames"):
        raise SetupError("Bootstrap user must have no inline policies")
    expected = {f"arn:aws:iam::{config['account_id']}:policy/{name}" for name in POLICIES}
    attached = cli.aws("iam", "list-attached-user-policies", UserName=USER).get("AttachedPolicies", [])
    if any(item.get("PolicyArn") not in expected for item in attached):
        raise SetupError("Bootstrap user has an unexpected managed policy")
    boundary = user.get("PermissionsBoundary", {}).get("PermissionsBoundaryArn")
    if boundary and boundary != f"arn:aws:iam::{config['account_id']}:policy/{BOUNDARY}":
        raise SetupError("Bootstrap user has an unexpected permissions boundary")
    return user


def create_user(cli, config):
    if inspect_user(cli, config, required=False) is None:
        cli.aws("iam", "create-user", UserName=USER,
                Tags=[{"Key": key, "Value": value} for key, value in TAGS.items()])
    inspect_user(cli, config)
    print("Verified one project bootstrap user; no console login or unrelated grants")


def install_policies(cli, config, directory, replace=False):
    inspect_user(cli, config)
    expected = render(config)
    for filename, document in expected.items():
        supplied = json.loads((directory / filename).read_text(encoding="utf-8"))
        if supplied != document:
            raise SetupError("Reviewed policy files differ from deterministic configuration")
    # Boundary is installed first, and attached before granting either policy.
    for filename, name in [("boundary.json", BOUNDARY),
                           ("permissions-iam.json", POLICIES[0]),
                           ("permissions-storage.json", POLICIES[1])]:
        arn = f"arn:aws:iam::{config['account_id']}:policy/{name}"
        policy = cli.aws("iam", "get-policy", PolicyArn=arn, missing_ok=True)
        if policy is None:
            cli.aws("iam", "create-policy", PolicyName=name, PolicyDocument=compact(expected[filename]),
                    Tags=[{"Key": k, "Value": v} for k, v in TAGS.items()])
        else:
            metadata = policy["Policy"]
            tags = cli.aws("iam", "list-policy-tags", PolicyArn=arn).get("Tags", [])
            owner_tags = {item["Key"]: item["Value"] for item in tags}
            if any(owner_tags.get(k) != v for k, v in TAGS.items()):
                raise SetupError("Existing policy ownership differs; refusing adoption")
            version = cli.aws("iam", "get-policy-version", PolicyArn=arn,
                              VersionId=metadata["DefaultVersionId"])["PolicyVersion"]["Document"]
            if version != expected[filename]:
                if not replace:
                    raise SetupError("Policy differs; review changes and explicitly replace policy version")
                # Do not silently delete historical versions when the AWS five-version cap is reached.
                cli.aws("iam", "create-policy-version", PolicyArn=arn,
                        PolicyDocument=compact(expected[filename]), SetAsDefault=True)
        if name == BOUNDARY:
            cli.aws("iam", "put-user-permissions-boundary", UserName=USER, PermissionsBoundary=arn)
        else:
            cli.aws("iam", "attach-user-policy", UserName=USER, PolicyArn=arn)
    inspect_user(cli, config)
    print("Installed the reviewed boundary and two exact bootstrap grants")


def access_keys(cli):
    return cli.aws("iam", "list-access-keys", UserName=USER).get("AccessKeyMetadata", [])


def upload_new_key(cli, config, rotate=False):
    verify_environments(cli)
    inspect_user(cli, config)
    before = access_keys(cli)
    if (not rotate and before) or (rotate and (len(before) != 1 or before[0]["Status"] != "Active")):
        raise SetupError("Existing keys require inspection; no duplicate key issued")
    previous = {item["AccessKeyId"] for item in before}
    try:
        key = cli.aws("iam", "create-access-key", UserName=USER)["AccessKey"]
        if key.get("AccessKeyId") in previous or not key.get("SecretAccessKey"):
            raise SetupError("Invalid new key response")
        for environment in ENVIRONMENTS:
            verify_environments(cli)
            cli.secret(environment, SECRETS[0], key["AccessKeyId"])
            cli.secret(environment, SECRETS[1], key["SecretAccessKey"])
            metadata = cli.api(f"repos/{REPO}/environments/{environment}/secrets")
            if not set(SECRETS).issubset({item["name"] for item in metadata.get("secrets", [])}):
                raise SetupError("Uploaded secret metadata missing")
        after = access_keys(cli)
        if {item["AccessKeyId"] for item in after} != previous | {key["AccessKeyId"]}:
            raise SetupError("Access-key inventory changed concurrently")
    except Exception:
        # Also handles an ambiguous timeout after AWS created the key: discover
        # and revoke only newly issued keys, never a pre-existing rotation key.
        try:
            for item in access_keys(cli):
                if item["AccessKeyId"] not in previous:
                    cli.aws("iam", "update-access-key", UserName=USER,
                            AccessKeyId=item["AccessKeyId"], Status="Inactive")
                    cli.aws("iam", "delete-access-key", UserName=USER, AccessKeyId=item["AccessKeyId"])
        except Exception:
            raise SetupError("Upload incomplete; emergency operator key revocation required") from None
        raise SetupError("Upload incomplete; new key revoked; inspect both Environments before explicit retry") from None
    print("Credential uploaded to both protected Environments; names verified, values withheld")
    if rotate:
        print("Old key remains active; verify a fresh no-op run before explicit retirement")


def retire_old_key(cli, config, confirmed_run):
    verify_environments(cli)
    inspect_user(cli, config)
    run = cli.api(f"repos/{REPO}/actions/runs/{confirmed_run}")
    # Human inspects the summary for genuine no-op; API verifies main workflow,
    # successful terminal run and that it started after replacement key issue.
    if (run.get("head_branch") != "main" or run.get("conclusion") != "success"
            or run.get("path") != ".github/workflows/terraform-iam-bootstrap.yml"):
        raise SetupError("Retirement requires a successful main bootstrap workflow run")
    keys = sorted(access_keys(cli), key=lambda k: k["CreateDate"])
    if len(keys) != 2 or datetime.fromisoformat(run.get("run_started_at", "").replace("Z", "+00:00")) <= datetime.fromisoformat(keys[-1]["CreateDate"].replace("Z", "+00:00")):
        raise SetupError("Retirement requires exactly two keys and a later verified run")
    cli.aws("iam", "update-access-key", UserName=USER, AccessKeyId=keys[0]["AccessKeyId"], Status="Inactive")
    cli.aws("iam", "delete-access-key", UserName=USER, AccessKeyId=keys[0]["AccessKeyId"])
    print("Retired the older key; one replacement key remains")


def publish_reader_roles(cli, config):
    """Explicit, idempotent owner publication from actual bootstrap outputs."""
    state = cli.read_bootstrap_state(config)
    outputs = state.get("outputs", {})
    reader_output = outputs.get("configuration_reader_role_arns", {})
    roles = reader_output.get("value")
    if (state.get("version") != 4 or not isinstance(state.get("serial"), int)
            or not isinstance(state.get("lineage"), str) or not state["lineage"]
            or outputs.get("aws_account_id", {}).get("value") != config["account_id"]
            # Terraform state v4 omits false (json sensitive,omitempty).
            # Identity comparison also rejects null, strings and integer zero.
            or reader_output.get("sensitive", False) is not False
            or not isinstance(roles, dict) or set(roles) != {"development", "production"}):
        raise SetupError("Bootstrap reader outputs or state identity are invalid")
    # Never synthesize publication values. Expected names only validate the
    # actual outputs and existence of the matching bootstrap-owned roles.
    for environment, arn in roles.items():
        name = f"pawlocal-{environment}-configuration-reader"
        if arn != f"arn:aws:iam::{config['account_id']}:role/{name}":
            raise SetupError("Bootstrap reader output does not match account and environment")
        role = cli.aws("iam", "get-role", RoleName=name).get("Role", {})
        if role.get("Arn") != arn:
            raise SetupError("Bootstrap reader role no longer exists or differs")
    pending = []
    # Validate every destination and read every existing value before any write.
    for target, environment in READER_TARGETS.items():
        base = f"repos/{REPO}/environments/{target}"
        metadata = cli.api(base)
        if metadata.get("name") != target or not isinstance(metadata.get("id"), int):
            raise SetupError("Reader publication target is missing or differs")
        variables = {}
        page = 1
        while True:
            response = cli.api(base + f"/variables?per_page=100&page={page}")
            entries = response.get("variables")
            if not isinstance(entries, list) or not isinstance(response.get("total_count"), int):
                raise SetupError("Invalid GitHub variable inventory")
            for entry in entries:
                if entry.get("name") == READER_VARIABLE:
                    if READER_VARIABLE in variables:
                        raise SetupError("Duplicate reader variable inventory")
                    variables[READER_VARIABLE] = entry.get("value")
            if page * 100 >= response["total_count"]:
                break
            if not entries or page >= 100:
                raise SetupError("Incomplete GitHub variable inventory")
            page += 1
        pending.append((target, base, roles[environment], variables))
    try:
        for target, base, value, variables in pending:
            if READER_VARIABLE not in variables:
                cli.api(base + "/variables", "POST", {"name": READER_VARIABLE, "value": value})
                status = "created"
            elif variables[READER_VARIABLE] != value:
                cli.api(base + "/variables/" + READER_VARIABLE, "PATCH",
                        {"name": READER_VARIABLE, "value": value})
                status = "updated"
            else:
                status = "unchanged"
            result = cli.api(base + "/variables/" + READER_VARIABLE)
            if result.get("name") != READER_VARIABLE or result.get("value") != value:
                raise SetupError("Reader variable read-back failed")
            print(f"{target}: {READER_VARIABLE} {status}; read-back verified")
    except Exception:
        print("Reader publication incomplete; earlier verified targets remain valid; repeat explicit publication after repair")
        raise SetupError("Reader publication failed; values and raw diagnostics withheld") from None
    print("Reader roles published to all four existing Environments; no infrastructure changed")


def main():
    if os.environ.get("GITHUB_ACTIONS"):
        raise SetupError("Owner identity setup cannot run in GitHub Actions")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    subcommands = parser.add_subparsers(dest="operation")
    subcommands.add_parser("inspect")
    subcommands.add_parser("create-user")
    install = subcommands.add_parser("install-policies")
    install.add_argument("--reviewed-dir", required=True, type=Path)
    install.add_argument("--replace-policy-version", action="store_true")
    subcommands.add_parser("issue-key")
    subcommands.add_parser("rotate-key")
    subcommands.add_parser("publish-reader-roles")
    retire = subcommands.add_parser("retire-old-key")
    retire.add_argument("--verified-noop-run", required=True, type=int)
    args = parser.parse_args()
    config = validate_config(json.loads(args.config.read_text(encoding="utf-8")))
    cli = CLI()
    verify_operator(cli, config)
    verify_environments(cli)
    if args.operation == "create-user":
        create_user(cli, config)
    elif args.operation == "install-policies":
        install_policies(cli, config, args.reviewed_dir, args.replace_policy_version)
    elif args.operation in ("issue-key", "rotate-key"):
        upload_new_key(cli, config, rotate=args.operation == "rotate-key")
    elif args.operation == "retire-old-key":
        retire_old_key(cli, config, args.verified_noop_run)
    elif args.operation == "publish-reader-roles":
        publish_reader_roles(cli, config)
    else:
        user = inspect_user(cli, config, required=False)
        print("Bootstrap user exists; ownership verified" if user else "Bootstrap user does not exist")
        if user:
            print(f"Access-key count: {len(access_keys(cli))}; credential values withheld")
        print("Both GitHub Environment protections verified; read-only inspection complete")


def entrypoint():
    try:
        main()
    except SetupError as error:
        # SetupError constructors are fixed source literals, verified by tests;
        # they identify the failed phase without exposing CLI/library content.
        print("Bootstrap identity setup: " + str(error), file=sys.stderr)
        return 1
    except Exception:
        # CLI/library exceptions can embed credentials or local variables.
        print("Bootstrap identity operation failed; values and raw diagnostics withheld", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(entrypoint())
