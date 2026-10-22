from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

SCRIPT = Path(".github/scripts/bootstrap-workflow.py")
spec = importlib.util.spec_from_file_location("bootstrap_workflow", SCRIPT)
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def plan_fixture(actions=None):
    plan = {"format_version": "1.2", "terraform_version": "1.14.3", "complete": True,
            "errored": False, "applyable": actions is not None,
            "planned_values": {"root_module": {}},
            "prior_state": {"values": {"root_module": {}}}, "configuration": {"root_module": {}},
            "resource_changes": [], "resource_drift": [], "output_changes": {}, "variables": {}}
    if actions is not None:
        plan["resource_changes"] = [{"address": 'aws_iam_role.configuration_reader["development"]',
            "type": "aws_iam_role", "name": "configuration_reader", "mode": "managed",
            "change": {"actions": actions, "before": {"policy": "PRIVATE_PAYLOAD"},
                       "after_unknown": {"arn": False}, "after_sensitive": {"policy": True}}}]
    return plan


def configuration_fixture():
    env = {"GITHUB_REPOSITORY": "alanlima/pawlocal", "GITHUB_REF": "refs/heads/main",
           "GITHUB_EVENT_NAME": "push", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "a" * 40,
           "GITHUB_RUN_ID": "5", "GITHUB_REPOSITORY_ID": "1423024931", "GITHUB_REPOSITORY_OWNER_ID": "4245961",
           "PAWLOCAL_AWS_ACCOUNT_ID": "111111111111", "AWS_REGION": "ap-southeast-2",
           "PAWLOCAL_TF_STATE_BUCKET": "existing-state", "PLAN_TRANSFER_BUCKET": "pawlocal-terraform-plans-111111111111",
           "BOOTSTRAP_KEY_ID": "fixture-id", "BOOTSTRAP_SECRET_KEY": "fixture-secret", "TF_WORKSPACE": "default"}
    inputs = {name: "fixture" for name in bootstrap.INPUTS}
    inputs.update(aws_region="ap-southeast-2", project_name="pawlocal", terraform_state_bucket_name="existing-state",
                  github_repository="alanlima/pawlocal", github_owner_id="4245961", github_repository_id="1423024931",
                  manage_github_oidc_provider="true", development_lightsail_principal_arn="", production_lightsail_principal_arn="")
    for name in bootstrap.INPUTS:
        if name.startswith("import_"):
            inputs[name] = "false"
    env.update({"TF_VAR_" + name: value for name, value in inputs.items()})
    return env


class ConfigurationAndStateTests(unittest.TestCase):
    def test_complete_configuration_validates_without_exposing_values(self):
        with patch.object(bootstrap.os, "environ", configuration_fixture()):
            bootstrap.validate("plan")

    def test_missing_configuration_reports_exact_name(self):
        for name, expected in (("BOOTSTRAP_KEY_ID", "PAWLOCAL_BOOTSTRAP_AWS_ACCESS_KEY_ID"),
                               ("PLAN_TRANSFER_BUCKET", "PAWLOCAL_TERRAFORM_PLAN_BUCKET"),
                               ("TF_VAR_route53_zone_id", "TF_VAR_route53_zone_id")):
            env = configuration_fixture()
            del env[name]
            with patch.object(bootstrap.os, "environ", env), self.subTest(name=name), self.assertRaisesRegex(bootstrap.Stop, "MISSING_" + expected):
                bootstrap.validate("plan")

    def test_untrusted_event_rerun_import_unbound_input_and_backend_change_rejected(self):
        for name, value in (("GITHUB_EVENT_NAME", "pull_request"), ("GITHUB_RUN_ATTEMPT", "2"),
                            ("GITHUB_REF", "refs/heads/untrusted"),
                            ("TF_VAR_import_existing_github_oidc_provider", "true"),
                            ("TF_VAR_unbound", "value"), ("TF_VAR_terraform_state_bucket_name", "other")):
            with patch.object(bootstrap.os, "environ", configuration_fixture() | {name: value}), self.subTest(name=name), self.assertRaises(bootstrap.Stop):
                bootstrap.validate("plan")


    def state_fixture(self):
        return {"version": 4, "lineage": "fixture-existing-lineage", "serial": 8,
                "resources": [{"mode": "managed", "type": "aws_iam_role", "name": "configuration_reader", "instances": []}]}

    def test_generation_reads_exact_version_of_fixed_backend_key(self):
        client = Mock()
        client.head_object.return_value = {"VersionId": "immutable-state-version"}
        client.get_object.return_value = {"Body": io.BytesIO(json.dumps(self.state_fixture()).encode())}
        with patch.object(bootstrap.os, "environ", configuration_fixture()), patch.object(bootstrap, "aws", return_value=client):
            generation, state = bootstrap.generation()
        self.assertEqual(generation, {"lineage": "fixture-existing-lineage", "serial": 8, "version": "immutable-state-version"})
        client.get_object.assert_called_once_with(Bucket="existing-state", Key=bootstrap.STATE_KEY, VersionId="immutable-state-version")

    def test_empty_foreign_unversioned_or_changed_state_rejected(self):
        for case in ("empty", "foreign", "unversioned", "changed", "module"):
            state = self.state_fixture()
            if case == "empty":
                state["resources"] = []
            elif case == "foreign":
                state["resources"][0].update(type="aws_instance", name="application")
            elif case == "module":
                state["resources"][0]["module"] = "module.foreign"
            client = Mock()
            client.head_object.side_effect = [{"VersionId": "null" if case == "unversioned" else "v1"}, {"VersionId": "v2" if case == "changed" else "v1"}]
            client.get_object.return_value = {"Body": io.BytesIO(json.dumps(state).encode())}
            with patch.object(bootstrap.os, "environ", configuration_fixture()), patch.object(bootstrap, "aws", return_value=client), self.subTest(case=case), self.assertRaises(bootstrap.Stop):
                bootstrap.generation()

    def test_wrong_account_or_wrong_user_stops_before_state_access(self):
        for account, arn in (("222222222222", "arn:aws:iam::222222222222:user/pawlocal-terraform-bootstrap-actions"),
                             ("111111111111", "arn:aws:iam::111111111111:user/another-user")):
            sts = Mock()
            sts.get_caller_identity.return_value = {"Account": account, "Arn": arn}
            with patch.object(bootstrap.os, "environ", configuration_fixture()), patch.object(bootstrap, "trusted_run"), \
                 patch.object(bootstrap, "run", side_effect=[Mock(stdout=("a" * 40).encode()), Mock(stdout=b"")]), \
                 patch.object(bootstrap, "aws", return_value=sts), patch.object(bootstrap, "generation") as generation, self.subTest(account=account, arn=arn):
                with self.assertRaisesRegex(bootstrap.Stop, "BOOTSTRAP_IDENTITY_MISMATCH"):
                    bootstrap.preflight()
                generation.assert_not_called()

    def test_exact_identity_existing_private_buckets_and_state_pass_preflight(self):
        client = Mock()
        client.get_caller_identity.return_value = {"Account": "111111111111", "Arn": "arn:aws:iam::111111111111:user/pawlocal-terraform-bootstrap-actions"}
        client.get_bucket_versioning.return_value = {"Status": "Enabled"}
        client.get_bucket_encryption.return_value = {"ServerSideEncryptionConfiguration": {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}}
        client.get_public_access_block.return_value = {"PublicAccessBlockConfiguration": dict.fromkeys(("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"), True)}
        state = {"outputs": {"plan_transfer_bucket_name": {"value": "pawlocal-terraform-plans-111111111111"}}}
        with patch.object(bootstrap.os, "environ", configuration_fixture()), patch.object(bootstrap, "trusted_run"), \
             patch.object(bootstrap, "run", side_effect=[Mock(stdout=("a" * 40).encode()), Mock(stdout=b"")]), \
             patch.object(bootstrap, "aws", return_value=client), patch.object(bootstrap, "generation", return_value=({"serial": 1}, state)):
            self.assertEqual(bootstrap.preflight(), {"serial": 1})


class PlanInputTests(unittest.TestCase):
    def variable_fixture(self):
        environment = configuration_fixture()
        return {name: {"value": environment["TF_VAR_" + name]} for name in bootstrap.INPUTS}

    def test_all_original_environment_strings_match_including_bool_inputs(self):
        variables = self.variable_fixture()
        with patch.object(bootstrap.os, "environ", configuration_fixture()):
            bootstrap.verify_plan_inputs({"variables": variables})
            canonical = bootstrap.effective_inputs()
        self.assertEqual(len(variables), 14)
        self.assertTrue(all(type(variables[name]["value"]) is str for name in bootstrap.BOOLEAN_INPUTS))
        self.assertTrue(all(type(canonical[name]) is bool for name in bootstrap.BOOLEAN_INPUTS))

    def test_missing_extra_malformed_and_nonstring_plan_inputs_fail_closed(self):
        cases = []
        missing = self.variable_fixture(); del missing["domain_name"]; cases.append(missing)
        extra = self.variable_fixture(); extra["unbound"] = {"value": "extra"}; cases.append(extra)
        for value in (None, {}, {"value": None}, {"value": False}, {"value": 0}, {"value": []}):
            malformed = self.variable_fixture(); malformed["import_existing_github_oidc_provider"] = value
            cases.append(malformed)
        for variables in cases:
            with patch.object(bootstrap.os, "environ", configuration_fixture()), self.subTest(variables=variables), \
                 self.assertRaisesRegex(bootstrap.Stop, "EFFECTIVE_PLAN_INPUT_MISMATCH"):
                bootstrap.verify_plan_inputs({"variables": variables})

    def test_every_changed_input_string_is_rejected(self):
        for name in bootstrap.INPUTS:
            changed = self.variable_fixture()
            changed[name]["value"] += "changed"
            with patch.object(bootstrap.os, "environ", configuration_fixture()), self.subTest(name=name), \
                 self.assertRaisesRegex(bootstrap.Stop, "EFFECTIVE_PLAN_INPUT_MISMATCH"):
                bootstrap.verify_plan_inputs({"variables": changed})

    @unittest.skipUnless(shutil.which("terraform"), "Terraform executable required for provider-free serialization fixture")
    def test_real_terraform_saved_plan_retains_raw_tf_var_strings(self):
        terraform = shutil.which("terraform")
        version = subprocess.run([terraform, "version", "-json"], capture_output=True, check=True)
        if json.loads(version.stdout)["terraform_version"] != "1.14.3":
            self.skipTest("Serialization fixture uses the workflow-pinned Terraform 1.14.3")
        fixture = configuration_fixture()
        environment = {name: value for name, value in os.environ.items()
                       if not name.startswith(("TF_", "CHECKPOINT_"))}
        environment.update({name: value for name, value in fixture.items() if name.startswith("TF_VAR_")})
        environment.update(TF_IN_AUTOMATION="true", TF_INPUT="false", CHECKPOINT_DISABLE="true")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment["TF_DATA_DIR"] = str(root / ".terraform")
            declarations = "\n".join('variable "' + name + '" { type = ' +
                ("bool" if name in bootstrap.BOOLEAN_INPUTS else "string") + " }" for name in bootstrap.INPUTS)
            output = 'output "inputs" { value = {' + ", ".join(name + " = var." + name for name in bootstrap.INPUTS) + "} }"
            (root / "main.tf").write_text(declarations + "\n" + output, encoding="utf-8")
            for command in (("init", "-backend=false", "-input=false"),
                            ("plan", "-input=false", "-out=tfplan"), ("show", "-json", "tfplan")):
                result = subprocess.run([terraform, *command], cwd=root, env=environment, capture_output=True)
                self.assertEqual(result.returncode, 0, "Provider-free Terraform " + command[0] + " failed")
            plan = json.loads(result.stdout)
        self.assertEqual(plan["variables"], self.variable_fixture())
        with patch.object(bootstrap.os, "environ", fixture):
            bootstrap.verify_plan_inputs(plan)


class ClassificationTests(unittest.TestCase):
    def test_only_complete_genuine_noop_bypasses_gate(self):
        changes, counts, rows = bootstrap.classify(plan_fixture())
        self.assertFalse(changes)
        self.assertFalse(any(counts.values()))
        self.assertEqual(rows, [])

    def test_genuine_noop_with_state_only_dependency_metadata_bypasses_gate(self):
        plan = plan_fixture(["no-op"])
        plan["applyable"] = False
        item = {"address": 'aws_iam_role.configuration_reader["development"]', "mode": "managed",
                "type": "aws_iam_role", "name": "configuration_reader", "index": "development",
                "provider_name": "registry.terraform.io/hashicorp/aws", "schema_version": 0,
                "values": {"name": "pawlocal-development-configuration-reader"}, "sensitive_values": {}}
        plan["planned_values"]["root_module"]["resources"] = [copy.deepcopy(item)]
        prior = copy.deepcopy(item)
        prior["depends_on"] = ["aws_iam_openid_connect_provider.github"]
        plan["prior_state"]["values"]["root_module"]["resources"] = [prior]
        self.assertFalse(bootstrap.classify(plan)[0])

    def test_prior_only_cached_data_resources_do_not_imply_managed_state_change(self):
        plan = plan_fixture()
        plan["applyable"] = False
        plan["prior_state"]["values"]["root_module"]["resources"] = [{
            "address": "data.aws_caller_identity.current", "mode": "data",
            "type": "aws_caller_identity", "name": "current", "values": {"account_id": "PRIVATE_DATA"}}]
        self.assertFalse(bootstrap.classify(plan)[0])

    def test_genuine_remote_drift_with_nonapplyable_noop_requires_owner_review(self):
        plan = plan_fixture(["no-op"])
        plan["applyable"] = False
        plan["resource_drift"] = copy.deepcopy(plan_fixture(["update"])["resource_changes"])
        with self.assertRaisesRegex(bootstrap.Stop, "DRIFT_REQUIRES_REVIEW"):
            bootstrap.classify(plan)

    def test_each_supported_change_requires_approval(self):
        for actions in (["create"], ["update"], ["delete"], ["delete", "create"], ["create", "delete"], ["read"]):
            with self.subTest(actions=actions):
                changes, counts, rows = bootstrap.classify(plan_fixture(actions))
                self.assertTrue(changes)
                self.assertEqual(sum(counts.values()), 1)
                self.assertNotIn("PRIVATE_PAYLOAD", repr(rows))

    def test_sensitive_and_unknown_markers_do_not_report_false_dictionary_as_true(self):
        _, _, rows = bootstrap.classify(plan_fixture(["update"]))
        self.assertFalse(rows[0][2])
        self.assertTrue(rows[0][3])

    def test_refresh_drift_output_move_cannot_be_called_noop(self):
        for kind in ("drift", "output", "move"):
            plan = plan_fixture(["no-op"])
            if kind == "drift":
                plan["resource_drift"] = copy.deepcopy(plan_fixture(["update"])["resource_changes"])
            elif kind == "output":
                plan["output_changes"] = {"configuration_reader_role_arns": {"actions": ["update"]}}
            else:
                plan["resource_changes"][0].update(address='aws_iam_policy.identity_app_role_boundary["development"]',
                    type="aws_iam_policy", name="identity_app_role_boundary", previous_address="aws_iam_policy.identity_app_role_boundary")
            self.assertTrue(bootstrap.classify(plan)[0], kind)

    def test_unsupported_actions_and_imports_fail_closed(self):
        for actions in (["forget"], ["create", "forget"], [], ["future"], [None]):
            with self.subTest(actions=actions), self.assertRaises(bootstrap.Stop):
                bootstrap.classify(plan_fixture(actions))
        plan = plan_fixture(["no-op"])
        plan["resource_changes"][0]["change"]["importing"] = {"id": "PRIVATE_IMPORT"}
        with self.assertRaisesRegex(bootstrap.Stop, "IMPORT_NOT_AUTHORIZED"):
            bootstrap.classify(plan)

    def test_incomplete_unknown_schema_or_deferred_fails_closed(self):
        for key, value in (("complete", False), ("errored", True), ("format_version", "9"),
                           ("terraform_version", "1.15.0"), ("applyable", None),
                           ("deferred_changes", [{"PRIVATE": "PRIVATE"}]), ("planned_values", {})):
            plan = plan_fixture()
            plan[key] = value
            with self.subTest(key=key), self.assertRaises(bootstrap.Stop):
                bootstrap.classify(plan)

    def test_unknown_noop_attributes_fail_closed(self):
        plan = plan_fixture(["no-op"])
        plan["resource_changes"][0]["change"]["after_unknown"] = {"arn": True}
        with self.assertRaisesRegex(bootstrap.Stop, "UNRESOLVED_NOOP_RESOURCE"):
            bootstrap.classify(plan)

    def test_unrelated_resource_and_value_injected_address_rejected(self):
        for update in ({"type": "aws_lambda_function", "name": "unrelated", "address": "aws_lambda_function.unrelated"},
                       {"address": 'aws_iam_role.configuration_reader["PRIVATE\\nINJECTION"]'},
                       {"mode": "future"}):
            plan = plan_fixture(["create"])
            plan["resource_changes"][0].update(update)
            with self.subTest(update=update), self.assertRaises(bootstrap.Stop):
                bootstrap.classify(plan)

    def test_non_applyable_changes_fail_closed(self):
        plan = plan_fixture(["update"])
        plan["applyable"] = False
        with self.assertRaisesRegex(bootstrap.Stop, "NON_APPLYABLE_CHANGES"):
            bootstrap.classify(plan)

    def test_unreported_state_changes_cannot_be_noop(self):
        plan = plan_fixture()
        plan["planned_values"]["outputs"] = {"unreported": {"value": "PRIVATE"}}
        with self.assertRaisesRegex(bootstrap.Stop, "NON_APPLYABLE_CHANGES"):
            bootstrap.classify(plan)

    def test_provider_actions_and_unresolved_checks_fail_closed(self):
        for field in ("action_invocations", "deferred_action_invocations"):
            plan = plan_fixture()
            plan[field] = [{"address": "action.aws_lambda_invoke.unreviewed"}]
            with self.subTest(field=field), self.assertRaisesRegex(bootstrap.Stop, "PROVIDER_ACTION_NOT_SUPPORTED"):
                bootstrap.classify(plan)
        for status in ("unknown", "fail", "error", None):
            plan = plan_fixture()
            plan["checks"] = [{"status": status}]
            with self.subTest(status=status), self.assertRaisesRegex(bootstrap.Stop, "PLAN_CHECK_NOT_PASSED"):
                bootstrap.classify(plan)


class ReviewedLifecycleTests(unittest.TestCase):
    def opaque_hcl_corpus(self):
        fake = '''}
resource "aws_iam_role" "ghost" {}
removed {
  from = aws_iam_role.ghost_removed
  lifecycle { destroy = true }
}
moved {
  from = aws_iam_role.ghost_moved
  to = aws_iam_role.real
}
'''
        actual = '\nresource "aws_iam_role" "real" {}\n'
        return {
            "heredoc": 'locals {\n text = <<EOF\n' + fake + 'EOF\n}\n' + actual,
            "indented-heredoc": 'locals {\n text = <<-EOF\n' + fake + '    EOF\n}\n' + actual,
            "quoted-strings": r'''locals {
  text = "resource \"aws_iam_role\" \"ghost\" {}"
  template = "${jsonencode({ text = "}" })}"
}
''' + actual,
            "nested-blocks": '''container {
  resource "aws_iam_role" "ghost" {}
  removed { from = aws_iam_role.ghost_removed }
  moved {
    from = aws_iam_role.ghost_moved
    to = aws_iam_role.real
  }
}
''' + actual,
            "comments": '''# resource "aws_iam_role" "ghost" {}
// removed { from = aws_iam_role.ghost_removed }
/* moved {
 from = aws_iam_role.ghost_moved
 to = aws_iam_role.real
} */
''' + actual,
            "root-attribute-spoof": '''resource = [{ "\\"aws_iam_role\\"" = { "\\"ghost\\"" = { __is_block__ = true } } }]
removed = [{ from = "${aws_iam_role.ghost_removed}", __is_block__ = true }]
''' + actual,
        }

    def test_only_actual_literal_root_blocks_authorize_inventory(self):
        for name, text in self.opaque_hcl_corpus().items():
            with tempfile.TemporaryDirectory() as directory, self.subTest(name=name):
                root = Path(directory)
                (root / "main.tf").write_text(text, encoding="utf-8")
                with patch.object(bootstrap, "ROOT", root):
                    self.assertEqual(bootstrap.source_declarations(), ({"aws_iam_role.real"}, set(), {}))

    def test_opaque_fake_declarations_cannot_admit_foreign_state(self):
        for corpus_name, text in self.opaque_hcl_corpus().items():
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "main.tf").write_text(text, encoding="utf-8")
                for resource in ("ghost", "ghost_removed", "ghost_moved", "real"):
                    state = {"version": 4, "lineage": "existing", "serial": 8,
                        "resources": [{"mode": "managed", "type": "aws_iam_role", "name": resource,
                                       "instances": [{"attributes": {}}]}]}
                    client = Mock()
                    client.head_object.return_value = {"VersionId": "v1"}
                    client.get_object.return_value = {"Body": io.BytesIO(json.dumps(state).encode())}
                    with patch.object(bootstrap, "ROOT", root), patch.object(bootstrap.os, "environ", configuration_fixture()), \
                         patch.object(bootstrap, "aws", return_value=client), self.subTest(corpus=corpus_name, resource=resource):
                        if resource == "real":
                            self.assertEqual(bootstrap.generation()[0]["serial"], 8)
                        else:
                            with self.assertRaisesRegex(bootstrap.Stop, "STATE_OUTSIDE_BOOTSTRAP"):
                                bootstrap.generation()

    def test_actual_removed_policy_address_is_admitted_for_approved_delete(self):
        address = "aws_iam_policy.identity_development_frontend"
        self.assertIn(address, bootstrap.source_inventory())
        plan = plan_fixture(["delete"])
        item = plan["resource_changes"][0]
        item.update(address=address, type="aws_iam_policy", name="identity_development_frontend")
        plan["prior_state"]["values"]["root_module"]["resources"] = [{
            key: item[key] for key in ("address", "type", "name", "mode")}]
        changes, counts, _ = bootstrap.classify(plan)
        self.assertTrue(changes)
        self.assertEqual(counts["delete"], 1)

    def test_actual_removed_policy_in_existing_state_passes_structural_ownership(self):
        state = {"version": 4, "lineage": "fixture-existing-lineage", "serial": 8,
                 "resources": [{"mode": "managed", "type": "aws_iam_policy", "name": "identity_development_frontend",
                                "instances": [{"attributes": {}}]}]}
        client = Mock()
        client.head_object.return_value = {"VersionId": "immutable-state-version"}
        client.get_object.return_value = {"Body": io.BytesIO(json.dumps(state).encode())}
        with patch.object(bootstrap.os, "environ", configuration_fixture()), patch.object(bootstrap, "aws", return_value=client):
            self.assertEqual(bootstrap.generation()[0]["serial"], 8)

    def test_literal_moved_old_instance_is_narrowly_admitted_and_requires_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tf").write_text('''resource "aws_iam_role" "renamed" {}
moved {
  from = aws_iam_role.previous["development"]
  to = aws_iam_role.renamed["development"]
}
''', encoding="utf-8")
            with patch.object(bootstrap, "ROOT", root):
                self.assertTrue(bootstrap.owned_address('aws_iam_role.previous["development"]'))
                self.assertFalse(bootstrap.owned_address('aws_iam_role.previous["production"]'))
                self.assertFalse(bootstrap.owned_address("aws_iam_role.previous"))
                self.assertFalse(bootstrap.owned_address("aws_iam_role.unrelated"))
                plan = plan_fixture(["no-op"])
                plan["resource_changes"][0].update(address='aws_iam_role.renamed["development"]', name="renamed",
                    previous_address='aws_iam_role.previous["development"]')
                self.assertEqual(bootstrap.classify(plan)[1]["moves"], 1)
                plan["resource_changes"][0]["previous_address"] = 'aws_iam_role.previous["production"]'
                with self.assertRaisesRegex(bootstrap.Stop, "MOVE_NOT_DECLARED"):
                    bootstrap.classify(plan)

    def test_undeclared_previous_address_and_module_refactor_are_rejected(self):
        plan = plan_fixture(["no-op"])
        plan["resource_changes"][0]["previous_address"] = "aws_iam_role.unrelated"
        with self.assertRaisesRegex(bootstrap.Stop, "MOVE_NOT_DECLARED"):
            bootstrap.classify(plan)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tf").write_text('''removed {
  from = module.unrelated.aws_iam_role.old
  lifecycle { destroy = true }
}
''', encoding="utf-8")
            with patch.object(bootstrap, "ROOT", root), self.assertRaisesRegex(bootstrap.Stop, "UNSUPPORTED_REFACTOR_FROM"):
                bootstrap.source_inventory()

    def test_commented_refactors_do_not_authorize_unrelated_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.tf").write_text('''# removed {
# from = aws_iam_role.unrelated
# }
/* moved {
  from = aws_iam_role.also_unrelated
  to = aws_iam_role.new
} */
resource "aws_iam_role" "reviewed" {}
''', encoding="utf-8")
            with patch.object(bootstrap, "ROOT", root):
                self.assertEqual(bootstrap.source_inventory(), {"aws_iam_role.reviewed"})


class PlanExecutionTests(unittest.TestCase):
    def test_exit_code_disagreement_in_either_direction_never_reports_noop_or_uploads(self):
        for exit_code, actions in ((2, None), (0, ["update"])):
            plan = plan_fixture(actions)
            with patch.object(bootstrap, "preflight", return_value={"serial": 1}), \
                 patch.object(bootstrap, "init"), patch.object(bootstrap, "generation", return_value=({"serial": 1}, {})), \
                 patch.object(bootstrap, "effective_inputs", return_value={}), \
                 patch.object(bootstrap, "tf", side_effect=[Mock(returncode=exit_code), Mock(stdout=json.dumps(plan).encode())]), \
                 patch.object(bootstrap, "aws") as aws, patch.object(bootstrap, "output") as output, \
                 patch.object(bootstrap, "summary") as summary, tempfile.TemporaryDirectory() as directory, \
                 patch.object(bootstrap, "PRIVATE", Path(directory)), self.subTest(exit_code=exit_code, actions=actions):
                with self.assertRaisesRegex(bootstrap.Stop, "EXIT_CODE_PLAN_DISAGREEMENT"):
                    bootstrap.make_plan()
            aws.assert_not_called()
            output.assert_not_called()
            summary.assert_not_called()

    def test_noop_never_uploads_or_requests_approval(self):
        plan = plan_fixture()
        with patch.object(bootstrap, "preflight", return_value={"serial": 1}), \
             patch.object(bootstrap, "init"), patch.object(bootstrap, "generation", return_value=({"serial": 1}, {})), \
             patch.object(bootstrap, "effective_inputs", return_value={}), \
             patch.object(bootstrap, "tf", side_effect=[Mock(returncode=0), Mock(stdout=json.dumps(plan).encode())]), \
             patch.object(bootstrap, "aws") as aws, patch.object(bootstrap, "output") as output, \
             patch.object(bootstrap, "summary") as summary, tempfile.TemporaryDirectory() as directory, \
             patch.object(bootstrap, "PRIVATE", Path(directory)):
            bootstrap.make_plan()
        aws.assert_not_called()
        output.assert_called_once_with("has_changes", "false")
        self.assertIn("no approval", summary.call_args.args[1])

    def test_generation_change_during_plan_prevents_publish(self):
        with patch.object(bootstrap, "preflight", return_value={"serial": 1}), patch.object(bootstrap, "init"), \
             patch.object(bootstrap, "generation", side_effect=[({"serial": 1}, {}), ({"serial": 2}, {})]), \
             patch.object(bootstrap, "tf", return_value=Mock(returncode=2)), patch.object(bootstrap, "aws") as aws:
            with self.assertRaisesRegex(bootstrap.Stop, "STATE_CHANGED_DURING_PLAN"):
                bootstrap.make_plan()
        aws.assert_not_called()

    def test_invalid_manifest_never_reaches_terraform_apply(self):
        bucket = Mock()
        bucket.get_object.side_effect = [
            {"Body": io.BytesIO(json.dumps({"plan_version": "v1", "schema": 0}).encode())},
            {"Body": io.BytesIO(b"private binary")},
        ]
        with patch.object(bootstrap, "preflight", return_value={"serial": 1}), \
             patch.object(bootstrap, "init"), \
             patch.object(bootstrap, "aws", return_value=bucket), patch.object(bootstrap, "binding", return_value={}), \
             patch.object(bootstrap, "tf") as tf, patch.dict(os.environ, {
                 "EXPECTED_MANIFEST_VERSION": "v2", "PLAN_TRANSFER_BUCKET": "private", "GITHUB_RUN_ID": "5"}):
            with self.assertRaisesRegex(bootstrap.Stop, "INVALID_MANIFEST"):
                bootstrap.apply_plan()
        tf.assert_not_called()


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.binary = b"private plan"
        self.binding = {"commit": "a" * 40, "run_id": "123", "attempt": "1", "input_digest": "first",
                        "backend": {"bucket": "existing", "key": bootstrap.STATE_KEY}, "source_digest": "lock-and-source"}
        self.state = {"lineage": "existing", "serial": 5, "version": "s3-version"}
        self.manifest = {"schema": 1, "binding": self.binding, "state_generation": self.state,
                         "created": 1000, "expires": 1000 + bootstrap.TTL,
                         "plan_sha256": bootstrap.digest(self.binary), "plan_version": "immutable-version"}
        self.environment = patch.dict(os.environ, {"EXPECTED_PLAN_SHA256": bootstrap.digest(self.binary)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def check(self, manifest=None, **kwargs):
        bootstrap.check_manifest(manifest or self.manifest, kwargs.get("binding", self.binding),
            kwargs.get("state", self.state), kwargs.get("binary", self.binary), now=kwargs.get("now", 1001))

    def test_matching_exact_plan_accepted(self):
        self.check()

    def test_commit_run_attempt_backend_input_source_mismatches_rejected(self):
        for name in self.binding:
            changed = copy.deepcopy(self.binding)
            changed[name] = "changed"
            with self.subTest(name=name), self.assertRaisesRegex(bootstrap.Stop, "PLAN_BINDING_CHANGED"):
                self.check(binding=changed)

    def test_each_state_generation_change_rejected(self):
        for name in self.state:
            changed = self.state | {name: "changed"}
            with self.subTest(name=name), self.assertRaisesRegex(bootstrap.Stop, "STALE_PLAN"):
                self.check(state=changed)

    def test_expired_future_and_tampered_plan_rejected(self):
        for now in (999, 1000 + bootstrap.TTL):
            with self.assertRaisesRegex(bootstrap.Stop, "PLAN_EXPIRED"):
                self.check(now=now)
        with self.assertRaisesRegex(bootstrap.Stop, "PLAN_DIGEST_MISMATCH"):
            self.check(binary=b"replacement")
        for field, value in (("plan_version", "null"), ("schema", 2), ("expires", 1000 + bootstrap.TTL + 1)):
            manifest = self.manifest | {field: value}
            with self.subTest(field=field), self.assertRaises(bootstrap.Stop):
                self.check(manifest)


class DiagnosticsTests(unittest.TestCase):



    def test_normal_terraform_logs_are_preserved_on_success_and_failure(self):
        for exit_code in (0, 1):
            result = Mock(returncode=exit_code, stdout=b"Normal plan resource context\n", stderr=b"Actual provider error: API_OPERATION\n")
            with patch.object(bootstrap, "run", return_value=result), contextlib.redirect_stdout(io.StringIO()) as stdout, \
                 contextlib.redirect_stderr(io.StringIO()) as stderr, self.subTest(exit_code=exit_code):
                if exit_code:
                    with self.assertRaisesRegex(bootstrap.Stop, "TERRAFORM_PLAN_FAILED"):
                        bootstrap.tf("plan")
                else:
                    self.assertIs(bootstrap.tf("plan"), result)
                self.assertEqual(stdout.getvalue(), result.stdout.decode())
                self.assertEqual(stderr.getvalue(), result.stderr.decode())

    def test_programmatic_show_json_is_returned_privately_without_log_dump(self):
        result = Mock(returncode=0, stdout=b'{"planned_values":{"PRIVATE_PLAN_SENTINEL":true}}', stderr=b"Useful Terraform show error context")
        with patch.object(bootstrap, "run", return_value=result), contextlib.redirect_stdout(io.StringIO()) as stdout, \
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertIs(bootstrap.tf("show", "-json", "private-plan"), result)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), result.stderr.decode())

    def test_runtime_error_context_is_logged_while_summary_retains_fixed_code(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.md"
            with patch.object(bootstrap, "PRIVATE", Path(directory) / "private"), \
                 patch.object(bootstrap, "make_plan", side_effect=Exception("AccessDenied: missing s3:ListBucket on the state bucket")), \
                 patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}), \
                 patch("sys.argv", [str(SCRIPT), "plan"]), contextlib.redirect_stdout(io.StringIO()) as console, \
                 contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(bootstrap.main(), 1)
            text = summary.read_text() + console.getvalue()
            self.assertIn("AccessDenied: missing s3:ListBucket", stderr.getvalue())
            self.assertIn("OPERATION_FAILED", text)
            self.assertIn("fresh **plan**", text)

    def test_github_http_error_preserves_status_without_dumping_response_or_token(self):
        error = bootstrap.urllib.error.HTTPError("https://api.github.com/repos/alanlima/pawlocal/actions", 403,
            "Forbidden", {}, io.BytesIO(b"PRIVATE_GITHUB_RESPONSE_BODY"))
        with patch.object(bootstrap.urllib.request, "urlopen", side_effect=error), \
             patch.dict(os.environ, {"GH_TOKEN": "PRIVATE_GITHUB_TOKEN"}), contextlib.redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaisesRegex(bootstrap.Stop, "GITHUB_REQUEST_FAILED"):
                bootstrap.api("/repos/alanlima/pawlocal/actions")
        self.assertIn("403: Forbidden", stderr.getvalue())
        self.assertNotIn("PRIVATE_GITHUB_TOKEN", stderr.getvalue())
        self.assertNotIn("PRIVATE_GITHUB_RESPONSE_BODY", stderr.getvalue())

    def test_partial_apply_reports_recovery_without_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.md"
            with patch.object(bootstrap, "PRIVATE", Path(directory) / "private"), patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}):
                bootstrap.save("apply-status.json", {"started": True, "applied": False})
                bootstrap.failure_summary("apply", "COMMAND_FAILED")
            self.assertIn("partially changed AWS", summary.read_text())
            self.assertIn("Do not replay", summary.read_text())


    def test_collision_does_not_silently_adopt_existing_ssm_parameter(self):
        plan = {"resource_changes": [{"type": "aws_ssm_parameter", "change": {"actions": ["create"],
            "after": {"name": "/pawlocal/development/config/aws/account-id"}}}]}
        with patch.object(bootstrap, "aws", return_value=Mock()):
            with self.assertRaisesRegex(bootstrap.Stop, "SSM_NAME_COLLISION"):
                bootstrap.collision_check(plan)

    def test_trusted_run_rejects_newer_run_and_changed_main(self):
        env = {"GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "5"}
        current = {"run_attempt": 1, "head_sha": "a" * 40, "head_branch": "main", "status": "in_progress", "event": "push"}
        with patch.dict(os.environ, env), patch.object(bootstrap, "api", side_effect=[{"object": {"sha": "a" * 40}}, current, {"workflow_runs": [{"id": 5}, {"id": 6}]}]):
            with self.assertRaisesRegex(bootstrap.Stop, "NEWER_RUN"):
                bootstrap.trusted_run()
        with patch.dict(os.environ, env), patch.object(bootstrap, "api", return_value={"object": {"sha": "b" * 40}}):
            with self.assertRaisesRegex(bootstrap.Stop, "MAIN_CHANGED"):
                bootstrap.trusted_run()


class WorkflowContractTests(unittest.TestCase):
    def test_dependency_installation_finishes_before_aws_credentials_are_available(self):
        import yaml
        workflow = yaml.safe_load(Path(".github/workflows/terraform-iam-bootstrap.yml").read_text())
        for name in ("plan", "apply"):
            job = workflow["jobs"][name]
            steps = job["steps"]
            setup_python = next(index for index, step in enumerate(steps) if step.get("uses", "").startswith("actions/setup-python@"))
            dependencies = next(index for index, step in enumerate(steps) if "pip install" in step.get("run", ""))
            terraform = next(index for index, step in enumerate(steps) if step.get("uses", "").startswith("hashicorp/setup-terraform@"))
            credentials = next(index for index, step in enumerate(steps) if step.get("uses", "").startswith("aws-actions/configure-aws-credentials@"))
            with self.subTest(job=name):
                self.assertEqual(dependencies, setup_python + 1)
                self.assertLess(dependencies, credentials)
                self.assertLess(terraform, credentials)
                self.assertNotIn("secrets.", json.dumps(job.get("env", {})))
                self.assertNotIn("secrets.", json.dumps(steps[dependencies]))
                self.assertNotIn("secrets.", json.dumps(steps[terraform]))

    def test_workflow_keeps_human_gate_and_noop_bypass(self):
        text = Path(".github/workflows/terraform-iam-bootstrap.yml").read_text()
        self.assertIn("environment: iam-bootstrap-apply", text)
        self.assertIn("needs.plan.outputs.has_changes == 'true'", text)
        self.assertIn("environment: iam-bootstrap-plan", text)
        self.assertNotIn("id-token: write", text)
        self.assertNotIn("upload-artifact", text)
        self.assertNotIn("pull_request", text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertNotIn("pawlocal-configuration-", text)
        self.assertNotIn("PAWLOCAL_CONFIG_GITHUB_TOKEN", text)
        self.assertNotIn("handoff", text)
        self.assertNotIn("inputs:", text)
        self.assertEqual(text.count("if: failure() || cancelled()"), 2)
        self.assertEqual(text.count("if: always()"), 2)
        self.assertEqual(text.count("Report incomplete setup or execution"), 2)

    def test_runtime_never_replans_in_apply_and_never_uses_unsafe_flags(self):
        text = SCRIPT.read_text()
        apply_body = text.split("def apply_plan():", 1)[1].split("def failure_summary", 1)[0]
        self.assertNotIn('tf("plan"', apply_body)
        self.assertIn('tf("apply", "-input=false", "-lock-timeout=5m", str(path))', apply_body)
        for forbidden in ("-refresh=false", "-auto-approve", "-target=", "-replace=", "-migrate-state", "force-unlock"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
