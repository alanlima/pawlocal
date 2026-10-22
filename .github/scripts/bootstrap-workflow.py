"""Protected IAM bootstrap runtime with owner-approved MVP operational logging.

Only the approved bootstrap root is executable. This module also owns the strict,
pure manifest/classification checks exercised by offline CI.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path("infra/terraform/iam-bootstrap")
STATE_KEY = "pawlocal/iam-bootstrap/terraform.tfstate"
REPOSITORY = "alanlima/pawlocal"
WORKFLOW = "terraform-iam-bootstrap.yml"
TTL = 6 * 60 * 60
PRIVATE = Path(os.environ.get("RUNNER_TEMP", ".tmp")) / "iam-bootstrap"
INPUTS = (
    "aws_region", "project_name", "terraform_state_bucket_name", "github_repository",
    "github_owner_id", "github_repository_id", "route53_zone_id", "domain_name",
    "manage_github_oidc_provider", "development_lightsail_principal_arn",
    "production_lightsail_principal_arn", "import_existing_github_oidc_provider",
    "import_existing_development_deploy_role", "import_existing_dsql_service_linked_role",
)
BOOLEAN_INPUTS = {"manage_github_oidc_provider", *(x for x in INPUTS if x.startswith("import_"))}
ACTIONS = {("no-op",), ("read",), ("create",), ("update",), ("delete",),
           ("delete", "create"), ("create", "delete")}
RESOURCE_TYPES = {"aws_iam_role", "aws_iam_role_policy", "aws_iam_policy", "aws_iam_openid_connect_provider",
                  "aws_iam_service_linked_role", "aws_ssm_parameter", "aws_s3_bucket",
                  "aws_s3_bucket_public_access_block", "aws_s3_bucket_ownership_controls", "aws_s3_bucket_policy",
                  "aws_s3_bucket_server_side_encryption_configuration", "aws_s3_bucket_versioning",
                  "aws_s3_bucket_lifecycle_configuration"}
ADDRESS = r'[a-z0-9_]+\.[a-z0-9_]+(?:\[(?:[0-9]+|"[A-Za-z0-9_/.-]+")\])?'


class Stop(RuntimeError):
    """Contains only a fixed, non-sensitive diagnostic identifier."""


def require(condition, code):
    if not condition:
        raise Stop(code)


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(value).hexdigest()


def private_path(name):
    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    return PRIVATE / name


def save(name, value):
    path = private_path(name)
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def load(name):
    return json.loads(private_path(name).read_text(encoding="utf-8"))


def summary(title, text):
    with open(os.environ.get("GITHUB_STEP_SUMMARY", os.devnull), "a", encoding="utf-8") as stream:
        stream.write(f"## IAM bootstrap — {title}\n\n{text}\n\n")


def output(name, value):
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a", encoding="utf-8") as stream:
        stream.write(f"{name}={value}\n")


def run(arguments, *, cwd=None, allowed=(0,)):
    # Do not use subprocess check=True: its exception can contain raw command inputs.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("TF_CLI_ARGS", "TF_LOG")) and key not in {
               "TF_VAR_FILE", "AWS_PROFILE", "AWS_CONFIG_FILE", "GH_TOKEN",
               "BOOTSTRAP_KEY_ID", "BOOTSTRAP_SECRET_KEY"}}
    env.update(TF_LOG="", TF_IN_AUTOMATION="true", TF_INPUT="false")
    result = subprocess.run(arguments, cwd=cwd, env=env, capture_output=True, check=False)
    require(allowed is None or result.returncode in allowed, "COMMAND_FAILED")
    return result


def tf(*arguments, allowed=(0,)):
    result = run(["terraform", *arguments], cwd=ROOT, allowed=None)
    # Temporary owner-approved MVP exception: preserve ordinary Terraform logs
    # for diagnosis. Programmatic show JSON and direct state reads stay private.
    if arguments[0] in {"init", "plan", "apply", "workspace"}:
        sys.stdout.write(result.stdout.decode("utf-8", errors="replace"))
        sys.stderr.write(result.stderr.decode("utf-8", errors="replace"))
    elif arguments[0] == "show":
        sys.stderr.write(result.stderr.decode("utf-8", errors="replace"))
    if result.returncode not in allowed:
        operation = arguments[0].upper() if arguments[0] in {"init", "plan", "show", "apply", "workspace"} else "COMMAND"
        raise Stop(f"TERRAFORM_{operation}_FAILED") from None
    return result


def api(path):
    require(path.startswith(f"/repos/{REPOSITORY}/"), "GITHUB_TARGET_REJECTED")
    request = urllib.request.Request("https://api.github.com" + path,
        headers={"Authorization": "Bearer " + os.environ.get("GH_TOKEN", ""),
                 "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        print(str(error), file=sys.stderr)
        raise Stop("GITHUB_REQUEST_FAILED") from None


def aws(service):
    import boto3
    return boto3.client(service, region_name=os.environ["AWS_REGION"])


def effective_inputs():
    result = {}
    for name in INPUTS:
        key = "TF_VAR_" + name
        require(key in os.environ, "MISSING_" + key)
        value = os.environ[key]
        require(value == value.strip(), "INVALID_" + key)
        if name in BOOLEAN_INPUTS:
            require(value in {"true", "false"}, "INVALID_" + key)
            value = value == "true"
        elif not name.endswith("lightsail_principal_arn"):
            require(bool(value), "MISSING_" + key)
        result[name] = value
    require(result["project_name"] == "pawlocal" and result["github_repository"] == REPOSITORY,
            "PROJECT_IDENTITY_MISMATCH")
    require(str(result["github_repository_id"]) == os.environ.get("GITHUB_REPOSITORY_ID"), "REPOSITORY_ID_MISMATCH")
    require(str(result["github_owner_id"]) == os.environ.get("GITHUB_REPOSITORY_OWNER_ID"), "OWNER_ID_MISMATCH")
    require(all(result[name] is False for name in INPUTS if name.startswith("import_")), "IMPORT_NOT_AUTHORIZED")
    require(result["terraform_state_bucket_name"] == os.environ.get("PAWLOCAL_TF_STATE_BUCKET"), "BACKEND_INPUT_MISMATCH")
    require(result["aws_region"] == os.environ.get("AWS_REGION"), "REGION_INPUT_MISMATCH")
    # Terraform auto-loaded files and extra TF_VAR values can change effective inputs.
    require(not any(ROOT.glob("*.tfvars*")) and not any(ROOT.glob("*.auto.tfvars*")), "UNBOUND_VARIABLE_FILE")
    require({key[7:] for key in os.environ if key.startswith("TF_VAR_")} == set(INPUTS), "UNBOUND_TERRAFORM_INPUT")
    return result


def validate(mode):
    require(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY and os.environ.get("GITHUB_REF") == "refs/heads/main", "TRUSTED_MAIN_REQUIRED")
    require(os.environ.get("GITHUB_EVENT_NAME") in {"push", "workflow_dispatch"}, "TRUSTED_EVENT_REQUIRED")
    require(os.environ.get("GITHUB_RUN_ATTEMPT") == "1", "FRESH_DISPATCH_REQUIRED")
    require(re.fullmatch(r"[0-9a-f]{40}", os.environ.get("GITHUB_SHA", "")), "INVALID_COMMIT")
    require(re.fullmatch(r"[0-9]+", os.environ.get("GITHUB_RUN_ID", "")), "INVALID_RUN")
    require(re.fullmatch(r"[0-9]{12}", os.environ.get("PAWLOCAL_AWS_ACCOUNT_ID", "")), "INVALID_ACCOUNT_CONFIGURATION")
    require(os.environ.get("AWS_REGION") == "ap-southeast-2", "INVALID_REGION_CONFIGURATION")
    for key in ("PAWLOCAL_TF_STATE_BUCKET", "PLAN_TRANSFER_BUCKET", "BOOTSTRAP_KEY_ID", "BOOTSTRAP_SECRET_KEY"):
        displayed = {"BOOTSTRAP_KEY_ID": "PAWLOCAL_BOOTSTRAP_AWS_ACCESS_KEY_ID",
                     "BOOTSTRAP_SECRET_KEY": "PAWLOCAL_BOOTSTRAP_AWS_SECRET_ACCESS_KEY",
                     "PLAN_TRANSFER_BUCKET": "PAWLOCAL_TERRAFORM_PLAN_BUCKET"}.get(key, key)
        require(bool(os.environ.get(key)), "MISSING_" + displayed)
    require(os.environ["PLAN_TRANSFER_BUCKET"] == f"pawlocal-terraform-plans-{os.environ['PAWLOCAL_AWS_ACCOUNT_ID']}", "TRANSFER_BUCKET_MISMATCH")
    require(os.environ.get("TF_WORKSPACE") == "default", "DEFAULT_WORKSPACE_REQUIRED")
    require(not os.environ.get("AWS_SESSION_TOKEN"), "STATIC_CREDENTIAL_EXPECTED")
    effective_inputs()


def trusted_run():
    commit = api(f"/repos/{REPOSITORY}/git/ref/heads/main")
    require(commit["object"]["sha"] == os.environ["GITHUB_SHA"], "MAIN_CHANGED_FRESH_PLAN_REQUIRED")
    run_id = int(os.environ["GITHUB_RUN_ID"])
    current = api(f"/repos/{REPOSITORY}/actions/runs/{run_id}")
    require(current.get("run_attempt") == 1 and current.get("head_sha") == os.environ["GITHUB_SHA"]
            and current.get("head_branch") == "main" and current.get("status") == "in_progress"
            and current.get("event") in {"push", "workflow_dispatch"}, "RUN_NO_LONGER_ELIGIBLE")
    runs = api(f"/repos/{REPOSITORY}/actions/workflows/{WORKFLOW}/runs?branch=main&per_page=100")["workflow_runs"]
    require(bool(runs) and max(item["id"] for item in runs) == run_id, "NEWER_RUN_FRESH_PLAN_REQUIRED")


@lru_cache(maxsize=64)
def parsed_source(text):
    # Use the pinned parser's root block structure, never tokens found in strings,
    # heredocs, comments or nested blocks. Cache by content, not file path/mtime.
    import hcl2
    from lark import Tree
    try:
        parsed = hcl2.parses_to_tree(text)
        result = {category: [] for category in ("resource", "removed", "moved")}
        for block in parsed.children[0].children:
            if not isinstance(block, Tree) or block.data != "block":
                continue
            category = str(block.children[0].children[0])
            if category in result:
                # Serialize only actual root block nodes, so even a root
                # attribute shaped like the parser's output cannot spoof one.
                root = Tree("start", [Tree("body", [block])])
                section = hcl2.serialize(hcl2.transform(root))
                result[category].extend(section[category])
        return result
    except Exception:
        raise Stop("INVALID_BOOTSTRAP_HCL") from None


def literal_refactor_reference(block, key):
    value = block.get(key)
    # python-hcl2 v8 preserves literal strings with their quotes and serializes
    # actual traversal expressions as ${...}. Accept only fixed root traversals.
    require(isinstance(value, str) and value.startswith("${") and value.endswith("}"), "UNSUPPORTED_REFACTOR_" + key.upper())
    address = value[2:-1]
    require(re.fullmatch(ADDRESS, address), "UNSUPPORTED_REFACTOR_" + key.upper())
    require(address.split(".", 1)[0] in RESOURCE_TYPES, "REFACTOR_OUTSIDE_BOOTSTRAP")
    return address


def source_declarations():
    current, removed, moved = set(), set(), {}
    for path in ROOT.glob("*.tf"):
        source = parsed_source(path.read_text(encoding="utf-8"))
        for declaration in source.get("resource", []):
            require(isinstance(declaration, dict) and len(declaration) == 1, "UNSUPPORTED_RESOURCE_DECLARATION")
            for raw_type, resources in declaration.items():
                require(isinstance(resources, dict) and len(resources) == 1, "UNSUPPORTED_RESOURCE_DECLARATION")
                for raw_name, block in resources.items():
                    require(isinstance(block, dict) and block.get("__is_block__") is True, "UNSUPPORTED_RESOURCE_DECLARATION")
                    try:
                        kind, name = json.loads(raw_type), json.loads(raw_name)
                    except (TypeError, ValueError):
                        raise Stop("NONLITERAL_RESOURCE_LABEL") from None
                    require(isinstance(kind, str) and isinstance(name, str)
                            and re.fullmatch(r"[a-z0-9_]+", kind) and re.fullmatch(r"[a-z0-9_]+", name), "NONLITERAL_RESOURCE_LABEL")
                    current.add(f"{kind}.{name}")
        for category in ("removed", "moved"):
            for block in source.get(category, []):
                require(isinstance(block, dict) and block.get("__is_block__") is True, "UNSUPPORTED_REFACTOR_DECLARATION")
                previous = literal_refactor_reference(block, "from")
                if category == "removed":
                    removed.add(previous)
                else:
                    require(previous not in moved, "DUPLICATE_REFACTOR_SOURCE")
                    moved[previous] = literal_refactor_reference(block, "to")
    return current, removed, moved


def source_inventory():
    current, removed, moved = source_declarations()
    return current | removed | set(moved)


def address_matches(address, declaration):
    return address == declaration or ("[" not in declaration and address.startswith(declaration + "["))


def owned_address(address):
    return bool(re.fullmatch(ADDRESS, address)) and any(address_matches(address, item) for item in source_inventory())


def reviewed_move(previous, address):
    require(isinstance(previous, str) and re.fullmatch(ADDRESS, previous), "INVALID_PREVIOUS_ADDRESS")
    for source, target in source_declarations()[2].items():
        if address_matches(previous, source):
            suffix = previous[len(source):] if "[" not in source else ""
            if address == target + suffix:
                return True
    return False


def check_address(item):
    kind, name = item.get("type"), item.get("name")
    mode = item.get("mode")
    require(mode in {"managed", "data"}, "UNKNOWN_RESOURCE_MODE")
    if mode == "managed":
        require(kind in RESOURCE_TYPES and owned_address(item.get("address", "")), "RESOURCE_OUTSIDE_BOOTSTRAP")
    else:
        require(kind in {"aws_iam_policy_document", "aws_iam_openid_connect_provider", "aws_caller_identity", "aws_partition"}, "DATA_OUTSIDE_BOOTSTRAP")
    prefix = "data." if mode == "data" else ""
    address = item.get("address", "")
    require(re.fullmatch(re.escape(f"{prefix}{kind}.{name}") + r'(?:\[(?:[0-9]+|"[A-Za-z0-9_/.-]+")\])?', address), "INVALID_RESOURCE_ADDRESS")
    return address


def generation():
    client = aws("s3")
    bucket = os.environ["PAWLOCAL_TF_STATE_BUCKET"]
    head = client.head_object(Bucket=bucket, Key=STATE_KEY)
    version = head.get("VersionId")
    require(bool(version) and version != "null", "EXISTING_VERSIONED_STATE_REQUIRED")
    state = json.loads(client.get_object(Bucket=bucket, Key=STATE_KEY, VersionId=version)["Body"].read())
    require(state.get("version") == 4 and isinstance(state.get("lineage"), str) and bool(state["lineage"])
            and type(state.get("serial")) is int and state["serial"] >= 0
            and isinstance(state.get("resources"), list) and bool(state["resources"]), "EXISTING_STATE_REQUIRED")
    for item in state["resources"]:
        require(not item.get("module"), "STATE_OUTSIDE_BOOTSTRAP")
        require(item.get("mode") in {"managed", "data"}, "UNKNOWN_STATE_MODE")
        if item.get("mode") == "managed":
            base = f"{item.get('type')}.{item.get('name')}"
            require(item.get("type") in RESOURCE_TYPES, "STATE_OUTSIDE_BOOTSTRAP")
            instances = item.get("instances", [])
            require(isinstance(instances, list), "INVALID_STATE_INSTANCES")
            for instance in instances or [{}]:
                index = instance.get("index_key")
                require(index is None or type(index) in {str, int}, "INVALID_STATE_INDEX")
                address = base if index is None else base + "[" + json.dumps(index) + "]"
                require(owned_address(address), "STATE_OUTSIDE_BOOTSTRAP")
    require(client.head_object(Bucket=bucket, Key=STATE_KEY).get("VersionId") == version, "STATE_CHANGED_RETRY")
    return {"lineage": state["lineage"], "serial": state["serial"], "version": version}, state


def preflight():
    trusted_run()
    require(run(["git", "rev-parse", "HEAD"]).stdout.decode().strip() == os.environ["GITHUB_SHA"], "CHECKOUT_MISMATCH")
    require(not run(["git", "status", "--porcelain", "--untracked-files=no"]).stdout, "CHECKOUT_MODIFIED")
    identity = aws("sts").get_caller_identity()
    expected = f"arn:aws:iam::{os.environ['PAWLOCAL_AWS_ACCOUNT_ID']}:user/pawlocal-terraform-bootstrap-actions"
    require(identity.get("Account") == os.environ["PAWLOCAL_AWS_ACCOUNT_ID"] and identity.get("Arn") == expected, "BOOTSTRAP_IDENTITY_MISMATCH")
    for bucket in (os.environ["PAWLOCAL_TF_STATE_BUCKET"], os.environ["PLAN_TRANSFER_BUCKET"]):
        client = aws("s3")
        require(client.get_bucket_versioning(Bucket=bucket).get("Status") == "Enabled", "BUCKET_VERSIONING_REQUIRED")
        require(bool(client.get_bucket_encryption(Bucket=bucket).get("ServerSideEncryptionConfiguration", {}).get("Rules")), "BUCKET_ENCRYPTION_REQUIRED")
    block = aws("s3").get_public_access_block(Bucket=os.environ["PLAN_TRANSFER_BUCKET"])["PublicAccessBlockConfiguration"]
    require(all(block.get(key) is True for key in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")), "PRIVATE_TRANSFER_REQUIRED")
    state_generation, state = generation()
    require(state.get("outputs", {}).get("plan_transfer_bucket_name", {}).get("value") == os.environ["PLAN_TRANSFER_BUCKET"], "TRANSFER_STATE_MISMATCH")
    return state_generation


def init():
    tf("init", "-input=false", "-reconfigure", "-lockfile=readonly",
       f"-backend-config=bucket={os.environ['PAWLOCAL_TF_STATE_BUCKET']}",
       f"-backend-config=key={STATE_KEY}", f"-backend-config=region={os.environ['AWS_REGION']}",
       "-backend-config=encrypt=true", "-backend-config=use_lockfile=true")
    require(tf("workspace", "show").stdout.decode().strip() == "default", "DEFAULT_WORKSPACE_REQUIRED")


def classify(plan):
    require(isinstance(plan, dict) and plan.get("format_version") == "1.2"
            and plan.get("terraform_version") == "1.14.3" and plan.get("complete") is True
            and plan.get("errored") is False and type(plan.get("applyable")) is bool,
            "INCOMPLETE_OR_UNKNOWN_PLAN")
    require(not plan.get("deferred_changes"), "DEFERRED_PLAN_REJECTED")
    require(not plan.get("action_invocations") and not plan.get("deferred_action_invocations"), "PROVIDER_ACTION_NOT_SUPPORTED")
    checks = plan.get("checks", [])
    require(isinstance(checks, list) and all(isinstance(check, dict) and check.get("status") == "pass" for check in checks), "PLAN_CHECK_NOT_PASSED")
    require(isinstance(plan.get("planned_values"), dict) and isinstance(plan.get("prior_state"), dict)
            and isinstance(plan.get("configuration"), dict), "INCOMPLETE_PLAN_VALUES")
    require(isinstance(plan["planned_values"].get("root_module"), dict)
            and isinstance(plan["prior_state"].get("values", {}).get("root_module"), dict)
            and isinstance(plan["configuration"].get("root_module"), dict), "INCOMPLETE_PLAN_ROOT")
    changes = plan.get("resource_changes", [])
    drift = plan.get("resource_drift", [])
    outputs = plan.get("output_changes", {})
    require(isinstance(changes, list) and isinstance(drift, list) and isinstance(outputs, dict), "INVALID_PLAN_CHANGES")
    for root in (plan["planned_values"]["root_module"], plan["prior_state"]["values"]["root_module"]):
        require(not root.get("child_modules"), "MODULE_OUTSIDE_BOOTSTRAP")
        require(isinstance(root.get("resources", []), list), "INVALID_PLAN_RESOURCES")
        for item in root.get("resources", []):
            check_address(item)
    counts = {"create": 0, "update": 0, "delete": 0, "replace": 0, "read": 0, "drift": len(drift), "outputs": 0, "moves": 0, "imports": 0, "state": 0}
    rows = []
    for offset, item in enumerate(changes + drift):
        require(isinstance(item, dict) and isinstance(item.get("change"), dict), "INVALID_RESOURCE_CHANGE")
        address = check_address(item)
        change = item["change"]
        actions = change.get("actions")
        require(isinstance(actions, list) and all(isinstance(x, str) for x in actions) and tuple(actions) in ACTIONS, "UNKNOWN_PLAN_ACTION")
        require(actions != ["no-op"] or not contains_true(change.get("after_unknown")), "UNRESOLVED_NOOP_RESOURCE")
        if change.get("importing") is not None:
            raise Stop("IMPORT_NOT_AUTHORIZED")
        if item.get("previous_address"):
            require(reviewed_move(item["previous_address"], address), "MOVE_NOT_DECLARED")
            counts["moves"] += 1
        is_drift = offset >= len(changes)
        if not is_drift and actions != ["no-op"]:
            if len(actions) == 2:
                counts["replace"] += 1
            else:
                counts[actions[0]] += 1
            rows.append((address, "/".join(actions), contains_true(change.get("after_unknown")), contains_true(change.get("before_sensitive")) or contains_true(change.get("after_sensitive"))))
        elif is_drift:
            rows.append((address, "drift: " + "/".join(actions), contains_true(change.get("after_unknown")), contains_true(change.get("before_sensitive")) or contains_true(change.get("after_sensitive"))))
    for change in outputs.values():
        require(isinstance(change, dict) and isinstance(change.get("actions"), list)
                and tuple(change["actions"]) in ACTIONS, "UNKNOWN_OUTPUT_CHANGE")
        if change["actions"] != ["no-op"] or contains_true(change.get("after_unknown")):
            counts["outputs"] += 1
    # Even a read action, refresh-only drift, move, or output delta needs approval.
    if not any(counts.values()) and semantic_values(plan["planned_values"]) != semantic_values(plan["prior_state"]["values"]):
        counts["state"] = 1
    has_changes = any(counts.values())
    require(not has_changes or plan["applyable"] is True, "NON_APPLYABLE_CHANGES")
    return has_changes, counts, rows


def semantic_values(values):
    # jsonstate includes depends_on metadata which jsonplan deliberately omits.
    # Compare value-bearing fields only; metadata differences cannot imply drift.
    fields = ("address", "mode", "type", "name", "index", "provider_name", "schema_version",
              "values", "sensitive_values", "identity", "identity_schema_version")
    resources = [{key: resource[key] for key in fields if key in resource}
                 for resource in values.get("root_module", {}).get("resources", [])]
    return {"outputs": values.get("outputs", {}), "resources": sorted(resources, key=lambda item: item["address"])}


def contains_true(value):
    if isinstance(value, dict):
        return any(contains_true(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_true(item) for item in value)
    return value is True


def binding():
    sources = {str(path): digest(path.read_bytes()) for path in sorted(ROOT.glob("*.tf"))}
    sources[str(ROOT / ".terraform.lock.hcl")] = digest((ROOT / ".terraform.lock.hcl").read_bytes())
    return {"repository": REPOSITORY, "repository_id": os.environ["GITHUB_REPOSITORY_ID"],
            "commit": os.environ["GITHUB_SHA"], "run_id": os.environ["GITHUB_RUN_ID"], "attempt": "1",
            "backend": {"bucket": os.environ["PAWLOCAL_TF_STATE_BUCKET"], "key": STATE_KEY,
                        "region": os.environ["AWS_REGION"], "workspace": "default"},
            "transfer_bucket": os.environ["PLAN_TRANSFER_BUCKET"],
            "input_digest": digest(effective_inputs()), "source_digest": digest(sources)}


def check_manifest(manifest, expected, state_generation, plan, *, now=None):
    require(isinstance(manifest, dict) and manifest.get("schema") == 1, "INVALID_MANIFEST")
    require(manifest.get("binding") == expected, "PLAN_BINDING_CHANGED")
    require(manifest.get("state_generation") == state_generation, "STALE_PLAN_FRESH_DISPATCH_REQUIRED")
    now = int(time.time()) if now is None else now
    created, expires = manifest.get("created"), manifest.get("expires")
    require(type(created) is int and type(expires) is int and created <= now < expires
            and expires - created == TTL, "PLAN_EXPIRED_OR_INVALID_TIME")
    require(manifest.get("plan_sha256") == digest(plan) and manifest.get("plan_sha256") == os.environ.get("EXPECTED_PLAN_SHA256"), "PLAN_DIGEST_MISMATCH")
    require(isinstance(manifest.get("plan_version"), str) and manifest["plan_version"] not in {"", "null"}, "PLAN_VERSION_REQUIRED")


def prefix():
    return f"plans/iam-bootstrap/{os.environ['GITHUB_RUN_ID']}/1"


def collision_check(plan):
    for item in plan.get("resource_changes", []):
        if item.get("type") != "aws_ssm_parameter" or item["change"]["actions"] != ["create"]:
            continue
        name = item["change"].get("after", {}).get("name")
        require(isinstance(name, str) and re.fullmatch(r"/pawlocal/(development|production)/config/(iam/(terraform-plan-role-arn|terraform-apply-role-arn|frontend-publish-role-arn|runtime-role-arn)|aws/account-id|terraform/plan-bucket)", name), "SSM_OWNERSHIP_UNRESOLVED")
        try:
            aws("ssm").get_parameter(Name=name)
        except Exception as error:
            require(getattr(error, "response", {}).get("Error", {}).get("Code") == "ParameterNotFound", "SSM_COLLISION_CHECK_FAILED")
        else:
            raise Stop("SSM_NAME_COLLISION")


def make_plan():
    initial = preflight()
    init()
    require(generation()[0] == initial, "STATE_CHANGED_BEFORE_PLAN")
    path = private_path("tfplan").resolve()
    result = tf("plan", "-input=false", "-lock-timeout=5m", "-detailed-exitcode", f"-out={path}", allowed=(0, 2))
    require(generation()[0] == initial, "STATE_CHANGED_DURING_PLAN")
    plan = json.loads(tf("show", "-json", str(path)).stdout)
    require({name: value.get("value") for name, value in plan.get("variables", {}).items()} == effective_inputs(), "EFFECTIVE_PLAN_INPUT_MISMATCH")
    has_changes, counts, rows = classify(plan)
    require((result.returncode == 2) == has_changes, "EXIT_CODE_PLAN_DISAGREEMENT")
    collision_check(plan)
    table = "| Action | Count |\n|---|---:|\n" + "\n".join(f"| {key} | {value} |" for key, value in counts.items())
    if not has_changes:
        output("has_changes", "false")
        summary("No changes", "The refreshed bootstrap plan is a complete no-op. Apply is skipped; no approval is needed.\n\n" + table)
        return
    binary = path.read_bytes()
    client = aws("s3")
    response = client.put_object(Bucket=os.environ["PLAN_TRANSFER_BUCKET"], Key=prefix() + "/tfplan", Body=binary, ServerSideEncryption="AES256", IfNoneMatch="*")
    require(response.get("VersionId") not in {None, "", "null"}, "PLAN_VERSION_REQUIRED")
    now = int(time.time())
    manifest = {"schema": 1, "binding": binding(), "state_generation": initial, "created": now, "expires": now + TTL,
                "plan_sha256": digest(binary), "plan_version": response["VersionId"], "counts": counts}
    published = client.put_object(Bucket=os.environ["PLAN_TRANSFER_BUCKET"], Key=prefix() + "/manifest.json",
        Body=json.dumps(manifest).encode(), ServerSideEncryption="AES256", IfNoneMatch="*")
    require(published.get("VersionId") not in {None, "", "null"}, "MANIFEST_VERSION_REQUIRED")
    output("has_changes", "true")
    output("plan_sha256", digest(binary))
    output("manifest_version", published["VersionId"])
    details = "\n\n| Resource | Action | Unknown attributes | Sensitive attributes |\n|---|---|---|---|\n" + "\n".join(f"| `{address}` | {action} | {'yes' if unknown else 'no'} | {'yes' if sensitive else 'no'} |" for address, action, unknown, sensitive in rows)
    summary("Approval required", "The private saved plan is ready for independent review. Approve **iam-bootstrap-apply** within six hours to apply this exact plan. Counts do not establish least privilege: inspect private policy/trust changes before approval.\n\n" + table + details + f"\n\nPrivate transfer keys in the configured plan bucket: `{prefix()}/tfplan` and `{prefix()}/manifest.json`. Plans are never uploaded as GitHub artifacts.\n\nPlan SHA-256: `{digest(binary)}`. A changed main commit, configuration, state, or newer run requires a fresh dispatch.")


def apply_plan():
    initial = preflight()
    init()
    client = aws("s3")
    version = os.environ.get("EXPECTED_MANIFEST_VERSION", "")
    require(version not in {"", "null"}, "MANIFEST_VERSION_REQUIRED")
    manifest = json.loads(client.get_object(Bucket=os.environ["PLAN_TRANSFER_BUCKET"], Key=prefix() + "/manifest.json", VersionId=version)["Body"].read())
    require(isinstance(manifest.get("plan_version"), str) and manifest["plan_version"] not in {"", "null"}, "PLAN_VERSION_REQUIRED")
    binary = client.get_object(Bucket=os.environ["PLAN_TRANSFER_BUCKET"], Key=prefix() + "/tfplan", VersionId=manifest["plan_version"])["Body"].read()
    check_manifest(manifest, binding(), initial, binary)
    path = private_path("approved.tfplan").resolve()
    path.write_bytes(binary)
    plan = json.loads(tf("show", "-json", str(path)).stdout)
    require({name: value.get("value") for name, value in plan.get("variables", {}).items()} == effective_inputs(), "EFFECTIVE_PLAN_INPUT_MISMATCH")
    require(classify(plan)[0], "CHANGING_PLAN_REQUIRED")
    collision_check(plan)
    trusted_run()
    check_manifest(manifest, binding(), generation()[0], binary)
    # Terraform's native state lock also checks staleness. Do not regenerate/retry.
    save("apply-status.json", {"started": True, "applied": False})
    tf("apply", "-input=false", "-lock-timeout=5m", str(path))
    save("apply-status.json", {"started": True, "applied": True})
    summary("AWS apply complete", "The exact approved saved plan applied successfully. If a reader-role identity changed, run the owner setup script with **publish-reader-roles**, then continue the existing configuration reconciliation workflow. This workflow does not publish GitHub variables.")


def failure_summary(command, code):
    applied = False
    started = False
    if private_path("apply-status.json").exists():
        status = load("apply-status.json")
        applied, started = applied or status.get("applied", False), status.get("started", False)
    status = "AWS apply succeeded." if applied else ("Apply started and may have partially changed AWS. Do not replay the saved plan." if started else "No successful AWS apply is claimed by this job.")
    explanation = {
        "TERRAFORM_INIT_FAILED": "Terraform could not initialize the existing bootstrap backend and locked providers. Read the Terraform init output in the failed step for the actual cause.",
        "TERRAFORM_PLAN_FAILED": "The refreshed Terraform plan failed. Read the Terraform plan output in the failed step for the actual cause, then create a fresh plan.",
        "TERRAFORM_SHOW_FAILED": "Terraform could not decode the private saved plan. Verify the locked Terraform version and dispatch a fresh plan.",
        "TERRAFORM_APPLY_FAILED": "Terraform could not finish the approved apply. Read its Terraform output and inspect AWS/state readback to determine partial changes; never retry this saved plan.",
        "TERRAFORM_WORKSPACE_FAILED": "Terraform could not verify the default bootstrap workspace. Check the existing backend configuration.",
        "JOB_SETUP_OR_EXECUTION_INCOMPLETE": "Runner setup, credential setup, or a workflow step did not complete. Check the failed step name and the required Environment configuration; this summary makes no success claim.",
        "OPERATION_FAILED": "An AWS/API or private runtime operation failed. Verify the dedicated identity's scoped permissions, connectivity, and backend availability; private response details are withheld.",
    }.get(code, "The execution safety check did not pass. Correct the named condition before dispatching a fresh plan.")
    if code.startswith("MISSING_"):
        explanation = f"Configure the required Environment variable or secret **`{code[8:]}`**. Its value is omitted."
    summary("Incomplete", f"**{command} stopped safely** (`{code}`). {status}\n\n{explanation}\n\nFor failed or partial apply, dispatch a fresh **plan** and review it again. If a reader-role identity changed after a successful apply, use the owner setup script **publish-reader-roles**, then the existing configuration reconciliation workflow. Ordinary Terraform operation output is available in the step logs under the temporary MVP logging exception. Programmatic plan JSON stdout and direct state/API payloads remain internal; Terraform show errors are available in the step logs.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "plan", "apply", "report", "cleanup"))
    parser.add_argument("--mode", choices=("plan", "apply"), default="plan")
    args = parser.parse_args()
    if args.command == "cleanup":
        import shutil
        shutil.rmtree(PRIVATE, ignore_errors=True)
        return 0
    if args.command == "report":
        if os.environ.get("JOB_STATUS") != "success":
            failure_summary(args.mode, "JOB_SETUP_OR_EXECUTION_INCOMPLETE")
        return 0
    try:
        if args.command == "validate":
            validate(args.mode)
        elif args.command == "plan":
            make_plan()
        elif args.command == "apply":
            apply_plan()
    except Exception as error:
        if not isinstance(error, Stop):
            print(str(error), file=sys.stderr)
        code = str(error) if isinstance(error, Stop) else "OPERATION_FAILED"
        failure_summary(args.command, code)
        print(f"::error::IAM bootstrap stopped ({code}). See the job summary for next steps.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
