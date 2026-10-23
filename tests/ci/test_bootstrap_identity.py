"""Offline authorization and credential-failure checks for owner setup tooling."""
from __future__ import annotations

from copy import deepcopy
import ast
import fnmatch
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "ops" / "iam-bootstrap"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, DIRECTORY / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


policy = load("bootstrap_identity_policy", "policy.py")
with patch.dict(sys.modules, {"policy": policy}):
    setup = load("bootstrap_identity_setup", "setup-bootstrap-identity.py")
CONFIG = {"account_id": "111111111111", "region": "ap-southeast-2", "state_bucket": "fixture-state-bucket"}


def permits(document, action, resource, context=None):
    """Small allow-only evaluator for this generator's StringEquals documents."""
    for statement in document["Statement"]:
        if statement["Effect"] != "Allow":
            continue
        if not any(fnmatch.fnmatchcase(action, a) for a in statement["Action"]):
            continue
        if not any(fnmatch.fnmatchcase(resource, r) for r in statement["Resource"]):
            continue
        conditions = statement.get("Condition", {}).get("StringEquals", {})
        if all((context or {}).get(k) in (v if isinstance(v, list) else [v]) for k, v in conditions.items()):
            return True
    return False


def explicitly_denied(document, action, resource):
    for statement in document["Statement"]:
        if statement["Effect"] != "Deny" or not any(
                fnmatch.fnmatchcase(action, a) for a in statement["Action"]):
            continue
        if "NotResource" in statement:
            if not any(fnmatch.fnmatchcase(resource, r) for r in statement["NotResource"]):
                return True
        elif any(fnmatch.fnmatchcase(resource, r) for r in statement["Resource"]):
            return True
    return False


class FakeCLI:
    def __init__(self):
        self.calls = []
        self.keys = []
        self.fail_upload = False
        self.fail_creation_after_commit = False
        self.break_gate = False
        self.user_exists = True
        self.tags = setup.TAGS.copy()
        self.missing_boundary = False
        self.missing_grant = False
        self.changed_policy = None

    def aws(self, service, operation, **kwargs):
        self.calls.append((operation, kwargs))
        if operation == "get-user":
            if not self.user_exists:
                return None
            user = {"Arn": f"arn:aws:iam::{CONFIG['account_id']}:user/{policy.USER}",
                    "Path": "/", "Tags": [{"Key": k, "Value": v} for k, v in self.tags.items()]}
            if not self.missing_boundary:
                user["PermissionsBoundary"] = {"PermissionsBoundaryArn": f"arn:aws:iam::{CONFIG['account_id']}:policy/{policy.BOUNDARY}"}
            return {"User": user}
        if operation == "list-attached-user-policies":
            names = policy.POLICIES[:1] if self.missing_grant else policy.POLICIES
            return {"AttachedPolicies": [{"PolicyArn": f"arn:aws:iam::{CONFIG['account_id']}:policy/{name}"} for name in names]}
        if operation == "get-policy":
            return {"Policy": {"Arn": kwargs["PolicyArn"], "DefaultVersionId": "v1"}}
        if operation == "get-policy-version":
            name = kwargs["PolicyArn"].split("/")[-1]
            filename = {policy.BOUNDARY: "boundary.json", policy.POLICIES[0]: "permissions-iam.json",
                        policy.POLICIES[1]: "permissions-storage.json"}[name]
            document = policy.render(CONFIG)[filename]
            if name == self.changed_policy:
                document = {"Version": "2012-10-17", "Statement": []}
            return {"PolicyVersion": {"IsDefaultVersion": True, "Document": document}}
        if operation == "create-user":
            self.user_exists = True
            return {}
        if operation == "get-login-profile":
            return None
        if operation == "list-access-keys":
            return {"AccessKeyMetadata": deepcopy(self.keys)}
        if operation == "create-access-key":
            self.keys.append({"AccessKeyId": "NEW-KEY-SENTINEL", "Status": "Active"})
            if self.fail_creation_after_commit:
                raise setup.SetupError("safe timeout")
            return {"AccessKey": {"AccessKeyId": "NEW-KEY-SENTINEL", "SecretAccessKey": "SECRET-SENTINEL"}}
        if operation == "delete-access-key":
            self.keys = [k for k in self.keys if k["AccessKeyId"] != kwargs["AccessKeyId"]]
        if operation == "sts":
            raise AssertionError("unexpected operation")
        return {}

    def api(self, path):
        if path == f"repos/{setup.REPO}":
            return {"id": setup.REPO_ID, "owner": {"id": setup.OWNER_ID}}
        if path.endswith("/deployment-branch-policies"):
            return {"branch_policies": [{"name": "main", "type": "branch"}]}
        if path.endswith("/secrets"):
            return {"secrets": [{"name": n} for n in setup.SECRETS]}
        apply = path.endswith("iam-bootstrap-apply")
        return {
            "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True},
            "can_admins_bypass": self.break_gate,
            "protection_rules": [{"type": "required_reviewers", "prevent_self_review": False,
                                  "reviewers": [{"type": "User", "reviewer": {"id": setup.OWNER_ID}}]}] if apply else [],
        }

    def secret(self, environment, name, value):
        self.calls.append(("secret", {"environment": environment, "name": name}))
        if self.fail_upload:
            raise RuntimeError("SECRET-SENTINEL provider diagnostic")


class BootstrapPolicyTests(unittest.TestCase):
    def setUp(self):
        self.documents = policy.render(CONFIG)
        self.graph = policy.inventory(CONFIG)

    def effective(self, action, resource, context=None, direct_resource_grant=False):
        grant = any(permits(doc, action, resource, context)
                    for name, doc in self.documents.items() if name != "boundary.json")
        boundary = self.documents["boundary.json"]
        return (direct_resource_grant or grant and permits(boundary, action, resource, context)) and not explicitly_denied(boundary, action, resource)

    def test_inventory_and_managed_policy_limits(self):
        self.assertEqual(len(self.graph["roles"]), 26)
        self.assertEqual(len(self.graph["policies"]), 10)
        self.assertEqual(len(self.graph["parameters"]), 12)
        for document in self.documents.values():
            self.assertLessEqual(len(policy.compact(document)), 6144)
        self.assertEqual(self.documents, policy.render(dict(reversed(list(CONFIG.items())))))

    def test_exact_bootstrap_state_and_lock_permissions(self):
        state = self.graph["state_bucket"] + "/" + policy.STATE_KEY
        self.assertTrue(self.effective("s3:GetObject", state))
        self.assertTrue(self.effective("s3:PutObject", state))
        self.assertFalse(self.effective("s3:DeleteObject", state))
        self.assertTrue(self.effective("s3:DeleteObject", state + ".tflock"))
        for scope in ("development", "production", "identity", "other"):
            target = self.graph["state_bucket"] + f"/pawlocal/{scope}/terraform.tfstate"
            self.assertFalse(self.effective("s3:GetObject", target))
            self.assertFalse(self.effective("s3:PutObject", target))
        self.assertTrue(self.effective("s3:ListBucket", self.graph["state_bucket"], {"s3:prefix": policy.STATE_KEY}))
        self.assertFalse(self.effective("s3:ListBucket", self.graph["state_bucket"], {"s3:prefix": "pawlocal/"}))

    def test_transfer_does_not_expose_application_plans(self):
        bucket = self.graph["transfer_bucket"]
        self.assertTrue(self.effective("s3:ListBucket", bucket))  # HeadBucket/key metadata exception.
        self.assertTrue(self.effective("s3:PutObject", bucket + "/plans/iam-bootstrap/1/1/tfplan"))
        for env in ("development", "production", "unknown"):
            self.assertFalse(self.effective("s3:GetObject", bucket + f"/plans/{env}/1/tfplan"))
        self.assertFalse(self.effective("s3:DeleteBucket", bucket))

    def test_only_explicit_bootstrap_owned_parameters(self):
        for arn in self.graph["parameters"]:
            self.assertTrue(self.effective("ssm:PutParameter", arn))
        for suffix in ("api/base-url", "app/secret", "iam/new-role-arn", "other"):
            arn = f"arn:aws:ssm:ap-southeast-2:{CONFIG['account_id']}:parameter/pawlocal/development/config/{suffix}"
            self.assertFalse(self.effective("ssm:GetParameter", arn))
            self.assertFalse(self.effective("ssm:PutParameter", arn))
        self.assertTrue(self.effective("ssm:DescribeParameters", "*", {"aws:RequestedRegion": "ap-southeast-2"}))
        self.assertFalse(self.effective("ssm:DescribeParameters", "*", {"aws:RequestedRegion": "us-east-1"}))

    def test_oncall_exact_inventory_is_enableable_without_application_or_secret_grants(self):
        iam = f"arn:aws:iam::{CONFIG['account_id']}:"
        for environment in policy.ENVIRONMENTS:
            for suffix in ("oncall-terraform-plan", "oncall-terraform-apply", "oncall-receiver"):
                arn = iam + f"role/pawlocal-{environment}-{suffix}"
                for action in ("iam:CreateRole", "iam:PutRolePolicy", "iam:DeleteRole", "iam:PutRolePermissionsBoundary"):
                    self.assertTrue(self.effective(action, arn), (action, arn))
                self.assertFalse(self.effective("iam:PassRole", arn))
            for suffix in ("oncall-terraform-apply-boundary", "oncall-runtime-boundary"):
                arn = iam + f"policy/pawlocal-{environment}-{suffix}"
                self.assertTrue(self.effective("iam:CreatePolicy", arn))
                self.assertTrue(self.effective("iam:CreatePolicyVersion", arn))
            for suffix in ("config/oncall/webhook-url", "config/api/base-url", "config/observability/enabled", "secrets/grafana/webhook-hmac", "secrets/oncall/dispatch-app-private-key"):
                arn = f"arn:aws:ssm:{CONFIG['region']}:{CONFIG['account_id']}:parameter/pawlocal/{environment}/{suffix}"
                for action in ("ssm:GetParameter", "ssm:PutParameter", "ssm:DeleteParameter", "ssm:PutResourcePolicy"):
                    self.assertFalse(self.effective(action, arn), (action, arn))
        for name in ("pawlocal-staging-oncall-receiver", "pawlocal-development-oncall-other"):
            self.assertFalse(self.effective("iam:CreateRole", iam + "role/" + name))
        self.assertEqual(len(self.documents["permissions-storage.json"]["Statement"][-2]["Resource"]), 12)

    def test_no_external_identity_escalation_or_application_mutation(self):
        arn = f"arn:aws:iam::{CONFIG['account_id']}:"
        for action in ("iam:CreateAccessKey", "iam:PutUserPermissionsBoundary", "iam:AttachUserPolicy"):
            self.assertFalse(self.effective(action, arn + "user/" + policy.USER))
        for name in (policy.BOUNDARY, *policy.POLICIES, "AdministratorAccess", "pawlocal-development-application"):
            self.assertFalse(self.effective("iam:CreatePolicyVersion", arn + "policy/" + name))
        self.assertFalse(self.effective("iam:PutRolePolicy", arn + "role/unrelated"))
        self.assertFalse(self.effective("iam:PassRole", self.graph["roles"][0]))
        self.assertFalse(self.effective("sts:AssumeRole", self.graph["roles"][0]))
        self.assertFalse(self.effective("lightsail:CreateContainerServiceDeployment", "*"))
        # Boundary read compression must not grant new effective reads.
        self.assertFalse(self.effective("s3:GetObjectAcl", self.graph["transfer_bucket"] + "/plans/iam-bootstrap/1/1/tfplan"))

    def test_service_linked_role_requires_exact_service(self):
        self.assertTrue(self.effective("iam:CreateServiceLinkedRole", self.graph["slr"],
                                       {"iam:AWSServiceName": "dsql.amazonaws.com"}))
        self.assertFalse(self.effective("iam:CreateServiceLinkedRole", self.graph["slr"],
                                        {"iam:AWSServiceName": "ec2.amazonaws.com"}))

    def test_direct_user_resource_policies_cannot_escape_explicit_boundary_denies(self):
        for action in ("sts:AssumeRole", "sts:AssumeRoleWithSAML", "sts:AssumeRoleWithWebIdentity", "iam:PassRole"):
            self.assertFalse(self.effective(action, self.graph["roles"][0], direct_resource_grant=True))
        for scope in ("development", "production"):
            target = self.graph["transfer_bucket"] + f"/plans/{scope}/1/tfplan"
            for action in ("s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:DeleteObject"):
                self.assertFalse(self.effective(action, target, direct_resource_grant=True))
        state = self.graph["state_bucket"] + "/" + policy.STATE_KEY
        self.assertFalse(self.effective("s3:DeleteObject", state, direct_resource_grant=True))
        self.assertFalse(self.effective("s3:DeleteObjectVersion", state, direct_resource_grant=True))
        self.assertFalse(self.effective("s3:DeleteBucket", self.graph["transfer_bucket"], direct_resource_grant=True))
        self.assertTrue(self.effective("s3:GetObject", state, direct_resource_grant=True))

    def test_invalid_config_rejected(self):
        for key, value in (("account_id", "*"), ("region", "us-east-1"), ("state_bucket", "a/*")):
            with self.assertRaises(ValueError):
                policy.render({**CONFIG, key: value})


class BootstrapSetupTests(unittest.TestCase):
    def test_key_operations_require_complete_boundary_and_grants_before_creation_or_upload(self):
        for rotate in (False, True):
            for failure in ("boundary", "grant", "boundary-document", "grant-document"):
                cli = FakeCLI()
                if rotate:
                    cli.keys = [{"AccessKeyId": "OLD", "Status": "Active"}]
                cli.missing_boundary = failure == "boundary"
                cli.missing_grant = failure == "grant"
                cli.changed_policy = policy.BOUNDARY if failure == "boundary-document" else policy.POLICIES[0] if failure == "grant-document" else None
                with self.assertRaises(setup.SetupError):
                    setup.upload_new_key(cli, CONFIG, rotate=rotate)
                self.assertNotIn("create-access-key", [op for op, _ in cli.calls])
                self.assertNotIn("secret", [op for op, _ in cli.calls])
                self.assertNotIn("delete-access-key", [op for op, _ in cli.calls])

    def test_inspection_allows_incomplete_setup_without_issuing_credentials(self):
        cli = FakeCLI()
        cli.missing_boundary = True
        cli.missing_grant = True
        setup.inspect_user(cli, CONFIG)
        self.assertNotIn("create-access-key", [op for op, _ in cli.calls])

    def test_reviewed_complete_policy_allows_rotation_without_revoking_old_key(self):
        cli = FakeCLI()
        cli.keys = [{"AccessKeyId": "OLD", "Status": "Active"}]
        with redirect_stdout(io.StringIO()):
            setup.upload_new_key(cli, CONFIG, rotate=True)
        self.assertEqual(len(cli.keys), 2)
        self.assertEqual(len([op for op, _ in cli.calls if op == "secret"]), 4)
        self.assertNotIn("delete-access-key", [op for op, _ in cli.calls])

    def test_permissions_changed_after_issuance_revoke_new_key_before_upload(self):
        class DriftingCLI(FakeCLI):
            def aws(self, service, operation, **kwargs):
                result = super().aws(service, operation, **kwargs)
                if operation == "create-access-key":
                    self.missing_boundary = True
                return result
        cli = DriftingCLI()
        cli.keys = [{"AccessKeyId": "OLD", "Status": "Active"}]
        with self.assertRaises(setup.SetupError):
            setup.upload_new_key(cli, CONFIG, rotate=True)
        self.assertEqual(cli.keys, [{"AccessKeyId": "OLD", "Status": "Active"}])
        self.assertNotIn("secret", [op for op, _ in cli.calls])

    def test_protected_environment_checked_before_key_issue(self):
        cli = FakeCLI()
        cli.break_gate = True
        with self.assertRaises(setup.SetupError):
            setup.upload_new_key(cli, CONFIG)
        self.assertNotIn("create-access-key", [op for op, _ in cli.calls])

    def test_existing_user_is_reused_and_unknown_owner_rejected(self):
        cli = FakeCLI()
        setup.create_user(cli, CONFIG)
        self.assertNotIn("create-user", [op for op, _ in cli.calls])
        cli.tags["owner"] = "unrelated"
        with self.assertRaises(setup.SetupError):
            setup.create_user(cli, CONFIG)

    def test_successful_issue_is_not_duplicated_on_retry(self):
        cli = FakeCLI()
        setup.upload_new_key(cli, CONFIG)
        self.assertEqual(len(cli.keys), 1)
        self.assertEqual(len([op for op, _ in cli.calls if op == "secret"]), 4)
        with self.assertRaises(setup.SetupError):
            setup.upload_new_key(cli, CONFIG)
        self.assertEqual(len([op for op, _ in cli.calls if op == "create-access-key"]), 1)

    def test_partial_upload_revokes_new_key_and_suppresses_provider_secret(self):
        cli = FakeCLI()
        cli.fail_upload = True
        with self.assertRaises(setup.SetupError) as error:
            setup.upload_new_key(cli, CONFIG)
        self.assertNotIn("SECRET-SENTINEL", str(error.exception))
        self.assertEqual(cli.keys, [])
        self.assertIn("update-access-key", [op for op, _ in cli.calls])

    def test_ambiguous_create_timeout_preserves_unknown_key_for_owner_recovery(self):
        cli = FakeCLI()
        cli.keys = [{"AccessKeyId": "OLD", "Status": "Active"}]
        cli.fail_creation_after_commit = True
        with self.assertRaises(setup.SetupError) as error:
            setup.upload_new_key(cli, CONFIG, rotate=True)
        self.assertEqual({key["AccessKeyId"] for key in cli.keys}, {"OLD", "NEW-KEY-SENTINEL"})
        self.assertIn("no keys revoked", str(error.exception))
        self.assertFalse(any(op in ("update-access-key", "delete-access-key", "secret") for op, _ in cli.calls))

    def test_key_limit_race_preserves_the_other_invocations_replacement(self):
        class QuotaRaceCLI(FakeCLI):
            def aws(self, service, operation, **kwargs):
                if operation == "create-access-key":
                    self.calls.append((operation, kwargs))
                    self.keys.append({"AccessKeyId": "OTHER-OWNER-KEY", "Status": "Active"})
                    raise setup.SetupError("Definitive two-key limit failure")
                return super().aws(service, operation, **kwargs)
        cli = QuotaRaceCLI()
        cli.keys = [{"AccessKeyId": "OLD", "Status": "Active"}]
        with self.assertRaises(setup.SetupError):
            setup.upload_new_key(cli, CONFIG, rotate=True)
        self.assertEqual({key["AccessKeyId"] for key in cli.keys}, {"OLD", "OTHER-OWNER-KEY"})
        self.assertFalse(any(op in ("update-access-key", "delete-access-key", "secret") for op, _ in cli.calls))

    def test_two_ambiguous_additions_are_never_bulk_revoked(self):
        class AmbiguousRaceCLI(FakeCLI):
            def aws(self, service, operation, **kwargs):
                if operation == "create-access-key":
                    self.calls.append((operation, kwargs))
                    self.keys.extend([{"AccessKeyId": name, "Status": "Active"}
                                      for name in ("UNKNOWN-ONE", "UNKNOWN-TWO")])
                    raise setup.SetupError("Ambiguous create timeout")
                return super().aws(service, operation, **kwargs)
        cli = AmbiguousRaceCLI()
        with self.assertRaises(setup.SetupError):
            setup.upload_new_key(cli, CONFIG)
        self.assertEqual({key["AccessKeyId"] for key in cli.keys}, {"UNKNOWN-ONE", "UNKNOWN-TWO"})
        self.assertFalse(any(op in ("update-access-key", "delete-access-key", "secret") for op, _ in cli.calls))

    def test_own_upload_failure_revokes_only_returned_key_despite_concurrent_addition(self):
        class UploadRaceCLI(FakeCLI):
            def secret(self, environment, name, value):
                self.keys.append({"AccessKeyId": "OTHER-OWNER-KEY", "Status": "Active"})
                raise RuntimeError("SECRET-SENTINEL")
        cli = UploadRaceCLI()
        with self.assertRaises(setup.SetupError):
            setup.upload_new_key(cli, CONFIG)
        self.assertEqual(cli.keys, [{"AccessKeyId": "OTHER-OWNER-KEY", "Status": "Active"}])
        mutations = [kwargs["AccessKeyId"] for op, kwargs in cli.calls
                     if op in ("update-access-key", "delete-access-key")]
        self.assertEqual(mutations, ["NEW-KEY-SENTINEL", "NEW-KEY-SENTINEL"])

    def test_missing_secret_in_success_response_revokes_confirmed_owned_key_only(self):
        class MissingSecretCLI(FakeCLI):
            def aws(self, service, operation, **kwargs):
                result = super().aws(service, operation, **kwargs)
                if operation == "create-access-key":
                    result["AccessKey"].pop("SecretAccessKey")
                return result
        cli = MissingSecretCLI()
        with self.assertRaises(setup.SetupError):
            setup.upload_new_key(cli, CONFIG)
        self.assertEqual(cli.keys, [])
        mutations = [kwargs["AccessKeyId"] for op, kwargs in cli.calls
                     if op in ("update-access-key", "delete-access-key")]
        self.assertEqual(mutations, ["NEW-KEY-SENTINEL", "NEW-KEY-SENTINEL"])

    def test_cli_errors_never_expose_raw_diagnostics(self):
        failed = subprocess.CompletedProcess([], 1, "SECRET-SENTINEL", "SECRET-SENTINEL")
        with patch.object(subprocess, "run", return_value=failed):
            with self.assertRaises(setup.SetupError) as error:
                setup.CLI().run(["aws", "iam", "create-access-key"])
        self.assertNotIn("SECRET-SENTINEL", str(error.exception))

    def test_only_typed_missing_login_profile_is_treated_as_absent(self):
        missing = subprocess.CompletedProcess([], 1, "", "An error occurred (NoSuchEntity) SECRET-SENTINEL")
        with patch.object(subprocess, "run", return_value=missing):
            self.assertIsNone(setup.CLI().aws("iam", "get-login-profile", UserName=policy.USER, missing_ok=True))
        denied = subprocess.CompletedProcess([], 1, "", "An error occurred (AccessDenied) SECRET-SENTINEL")
        with patch.object(subprocess, "run", return_value=denied):
            with self.assertRaises(setup.SetupError):
                setup.CLI().aws("iam", "get-login-profile", UserName=policy.USER, missing_ok=True)

    def test_secret_upload_uses_stdin_and_debug_is_disabled(self):
        success = subprocess.CompletedProcess([], 0, "", "")
        with patch.object(subprocess, "run", return_value=success) as run:
            setup.CLI().secret("iam-bootstrap-plan", setup.SECRETS[1], "SECRET-SENTINEL")
        args, kwargs = run.call_args
        self.assertNotIn("SECRET-SENTINEL", " ".join(args[0]))
        self.assertEqual(kwargs["input"], "SECRET-SENTINEL")
        self.assertNotIn("GH_DEBUG", kwargs["env"])

    def test_owner_cli_forbids_unlisted_infrastructure_and_actions_execution(self):
        with patch.object(subprocess, "run") as run:
            with self.assertRaises(setup.SetupError):
                setup.CLI().aws("s3api", "delete-bucket", Bucket="unrelated")
            run.assert_not_called()
        with patch.dict(setup.os.environ, {"GITHUB_ACTIONS": "true"}):
            with self.assertRaises(setup.SetupError):
                setup.main()

    def test_secret_upload_ignores_opaque_success_output(self):
        success = subprocess.CompletedProcess([], 0, "Updated secret: opaque non-JSON success", "")
        with patch.object(subprocess, "run", return_value=success):
            setup.CLI().secret("iam-bootstrap-plan", setup.SECRETS[1], "SECRET-SENTINEL")


class PublicationCLI:
    def __init__(self):
        self.roles = {environment: f"arn:aws:iam::{CONFIG['account_id']}:role/pawlocal-{environment}-configuration-reader"
                      for environment in ("development", "production")}
        self.state = {"version": 4, "serial": 7, "lineage": "fixture-lineage", "outputs": {
            "aws_account_id": {"value": CONFIG["account_id"]},
            "configuration_reader_role_arns": {"sensitive": False, "value": self.roles},
        }}
        self.variables = {target: {} for target in setup.READER_TARGETS}
        self.writes = []
        self.missing_target = None
        self.fail_write = None
        self.fail_readback = None
        self.role_missing = False
        self.calls = []

    def read_bootstrap_state(self, config):
        return deepcopy(self.state)

    def aws(self, service, operation, **kwargs):
        self.calls.append((service, operation))
        if service != "iam" or operation != "get-role":
            raise AssertionError("publication requires only role reads")
        if self.role_missing:
            return {}
        return {"Role": {"Arn": f"arn:aws:iam::{CONFIG['account_id']}:role/{kwargs['RoleName']}"}}

    def api(self, path, method="GET", payload=None):
        target = path.split("/environments/")[1].split("/")[0]
        if target not in setup.READER_TARGETS:
            raise AssertionError("publication escaped target allowlist")
        if method in ("POST", "PATCH"):
            if target == self.fail_write:
                raise RuntimeError("SECRET-SENTINEL")
            self.writes.append((target, method, deepcopy(payload)))
            self.variables[target][setup.READER_VARIABLE] = payload["value"]
            return {}
        if "/variables?" in path:
            entries = [{"name": k, "value": v} for k, v in self.variables[target].items()]
            return {"total_count": len(entries), "variables": entries}
        if "/variables/" in path:
            return {"name": setup.READER_VARIABLE,
                    "value": "WRONG-SENTINEL" if target == self.fail_readback else self.variables[target].get(setup.READER_VARIABLE)}
        return {"name": target, "id": None if target == self.missing_target else 123}


class ReaderPublicationTests(unittest.TestCase):
    def test_real_terraform_state_omits_non_sensitive_flag(self):
        # Terraform 1.14.3 outputStateV4 Sensitive bool uses json omitempty.
        cli = PublicationCLI()
        del cli.state["outputs"]["configuration_reader_role_arns"]["sensitive"]
        with redirect_stdout(io.StringIO()):
            setup.publish_reader_roles(cli, CONFIG)
        self.assertEqual(len(cli.writes), 4)

    def test_explicit_invalid_sensitive_flags_fail_closed(self):
        for sensitive in (True, None, "false", 0, 1):
            cli = PublicationCLI()
            cli.state["outputs"]["configuration_reader_role_arns"]["sensitive"] = sensitive
            with self.assertRaises(setup.SetupError):
                setup.publish_reader_roles(cli, CONFIG)
            self.assertEqual(cli.writes, [])

    def test_cli_reports_fixed_phase_diagnostic_but_suppresses_foreign_errors(self):
        output = io.StringIO()
        with patch.object(setup, "main", side_effect=setup.SetupError("Bootstrap reader outputs or state identity are invalid")), redirect_stderr(output):
            self.assertEqual(setup.entrypoint(), 1)
        self.assertIn("Bootstrap reader outputs or state identity are invalid", output.getvalue())
        output = io.StringIO()
        with patch.object(setup, "main", side_effect=RuntimeError("SECRET-SENTINEL")), redirect_stderr(output):
            self.assertEqual(setup.entrypoint(), 1)
        self.assertNotIn("SECRET-SENTINEL", output.getvalue())
        tree = ast.parse((DIRECTORY / "setup-bootstrap-identity.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "SetupError":
                self.assertEqual(len(node.args), 1)
                self.assertIsInstance(node.args[0], ast.Constant)
                self.assertIsInstance(node.args[0].value, str)

    def test_creation_update_and_idempotent_retry_only_touch_exact_four_destinations(self):
        cli = PublicationCLI()
        cli.variables["production"] = {setup.READER_VARIABLE: "OLD", "UNRELATED": "PRESERVE"}
        output = io.StringIO()
        with redirect_stdout(output):
            setup.publish_reader_roles(cli, CONFIG)
            setup.publish_reader_roles(cli, CONFIG)
        self.assertEqual(len(cli.writes), 4)
        self.assertEqual({target for target, _, _ in cli.writes}, set(setup.READER_TARGETS))
        self.assertEqual(cli.variables["production"]["UNRELATED"], "PRESERVE")
        self.assertEqual({payload["name"] for _, _, payload in cli.writes}, {setup.READER_VARIABLE})
        for target, environment in setup.READER_TARGETS.items():
            self.assertEqual(cli.variables[target][setup.READER_VARIABLE], cli.roles[environment])
        for arn in cli.roles.values():
            self.assertNotIn(arn, output.getvalue())
        self.assertNotIn("fixture-lineage", output.getvalue())

    def test_missing_last_target_or_reader_role_prevents_all_writes(self):
        for failure in ("target", "role"):
            cli = PublicationCLI()
            cli.missing_target = "production-apply" if failure == "target" else None
            cli.role_missing = failure == "role"
            with self.assertRaises(setup.SetupError):
                setup.publish_reader_roles(cli, CONFIG)
            self.assertEqual(cli.writes, [])

    def test_wrong_account_environment_or_sensitive_outputs_prevent_all_writes(self):
        for change in ("account", "environment", "missing", "sensitive"):
            cli = PublicationCLI()
            reader = cli.state["outputs"]["configuration_reader_role_arns"]
            if change == "account":
                cli.state["outputs"]["aws_account_id"]["value"] = "222222222222"
            elif change == "environment":
                reader["value"]["development"] = cli.roles["production"]
            elif change == "missing":
                del reader["value"]["production"]
            else:
                reader["sensitive"] = True
            with self.assertRaises(setup.SetupError):
                setup.publish_reader_roles(cli, CONFIG)
            self.assertEqual(cli.writes, [])

    def test_partial_failure_then_retry_converges_without_rewriting_completed_targets(self):
        cli = PublicationCLI()
        cli.fail_write = "production"
        output = io.StringIO()
        with redirect_stdout(output):
            with self.assertRaises(setup.SetupError) as error:
                setup.publish_reader_roles(cli, CONFIG)
            self.assertEqual(len(cli.writes), 2)
            cli.fail_write = None
            setup.publish_reader_roles(cli, CONFIG)
        self.assertEqual(len(cli.writes), 4)
        self.assertNotIn("SECRET-SENTINEL", str(error.exception))
        self.assertIn("publication incomplete", output.getvalue())

    def test_readback_mismatch_is_failure_and_values_stay_private(self):
        cli = PublicationCLI()
        cli.fail_readback = "development"
        output = io.StringIO()
        with redirect_stdout(output):
            with self.assertRaises(setup.SetupError):
                setup.publish_reader_roles(cli, CONFIG)
        self.assertEqual(len(cli.writes), 1)
        self.assertNotIn("WRONG-SENTINEL", output.getvalue())

    def test_s3_reader_is_fixed_state_key_stdout_only_and_config_validated(self):
        success = subprocess.CompletedProcess([], 0, json.dumps({"outputs": {}}), "")
        with patch.object(subprocess, "run", return_value=success) as run:
            setup.CLI().read_bootstrap_state(CONFIG)
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["aws", "s3", "cp", f"s3://{CONFIG['state_bucket']}/{policy.STATE_KEY}",
                                   "-", "--only-show-errors", "--no-cli-pager"])
        self.assertTrue(kwargs["capture_output"])
        with patch.object(subprocess, "run") as run:
            with self.assertRaises(ValueError):
                setup.CLI().read_bootstrap_state({**CONFIG, "state_bucket": "bad/*"})
            run.assert_not_called()

    def test_github_wrapper_cannot_write_unrelated_targets_or_variable_names(self):
        for path, method, payload in (
                (f"repos/{setup.REPO}/environments/unrelated/variables", "POST", {"name": setup.READER_VARIABLE, "value": "x"}),
                (f"repos/{setup.REPO}/environments/development/variables", "POST", {"name": "UNRELATED", "value": "x"}),
                (f"repos/{setup.REPO}/environments/development", "PUT", {})):
            with patch.object(subprocess, "run") as run:
                with self.assertRaises(setup.SetupError):
                    setup.CLI().api(path, method, payload)
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
