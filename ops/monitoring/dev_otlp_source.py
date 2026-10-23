"""DRAFT one-source DEV input boundary. No AWS writes, identity setup or runner.

The protected caller owns fresh metadata acquisition and exact plan/run binding.
Private input comes only from an atomic GetParameter response into child-process
environment; it is never accepted as an argument, file, output or plan value.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path

LEGACY = "/pawlocal/development/secrets/grafana/otlp-token"
TARGET = LEGACY + "-v1"
ADDRESS = "module.dev_otlp_source.aws_ssm_parameter.token[0]"
PRIVATE_VARIABLE = "TF_VAR_dev_otlp_source_creation_value"
DESCRIPTION = "Terraform-owned PawLocal development OTLP ingestion credential."
TAGS = {"project": "pawlocal", "environment": "development", "managedby": "terraform"}


def require(condition):
    if not condition:
        raise ValueError("DEV OTLP source boundary rejected the operation")


def stamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(isinstance(value, datetime) and value.tzinfo is not None)
    return value.astimezone(timezone.utc)


def selection(value):
    require(isinstance(value, dict) and set(value) == {"managed", "write_revision", "creation"})
    require(type(value["managed"]) is bool and type(value["write_revision"]) is int and value["write_revision"] >= 1)
    creation = value["creation"]
    if creation is not None:
        require(value["managed"] and value["write_revision"] == 1 and isinstance(creation, dict)
                and set(creation) == {"legacy_version", "legacy_last_modified"}
                and type(creation["legacy_version"]) is int and creation["legacy_version"] == 1)
        stamp(creation["legacy_last_modified"])
    return value


def source_metadata(actual, chosen):
    creation = selection(chosen)["creation"]
    require(creation is not None and isinstance(actual, dict) and "Value" not in actual)
    require(actual.get("Name") == LEGACY and actual.get("Type") == "String"
            and type(actual.get("Version")) is int and actual["Version"] == creation["legacy_version"]
            and stamp(actual.get("LastModifiedDate")) == stamp(creation["legacy_last_modified"]))


def target_metadata(response, chosen):
    selection(chosen)
    require(isinstance(response, dict) and not response.get("NextToken") and isinstance(response.get("Parameters"), list))
    items = response["Parameters"]
    require(all(isinstance(item, dict) and item.get("Name") == TARGET and "Value" not in item for item in items))
    if chosen["creation"] is not None:
        require(items == [])
    elif chosen["managed"]:
        require(len(items) == 1 and items[0].get("Type") == "SecureString"
                and type(items[0].get("Version")) is int and items[0]["Version"] == 1)


@contextmanager
def creation_environment(client, chosen, account_id, region):
    """Atomic metadata/value verification, private child env, no resupply path."""
    selection(chosen)
    require(chosen["creation"] is not None and isinstance(account_id, str) and account_id.isascii()
            and account_id.isdigit() and len(account_id) == 12)
    require(isinstance(region, str) and re.fullmatch(r"[a-z]{2}-[a-z]+-\d", region) is not None)
    require(not any(os.environ.get(key) for key in ("TF_LOG", "TF_LOG_PATH", "TF_LOG_CORE", "TF_LOG_PROVIDER")))
    arn = f"arn:aws:ssm:{region}:{account_id}:parameter{LEGACY}"
    try:
        # Read CURRENT atomically: a historical :1 selector would conceal a
        # newer version while the old version remained available.
        parameter = client.get_parameter(Name=arn, WithDecryption=False)["Parameter"]
    except Exception:
        # A private input response/exception is not Terraform operational output.
        raise ValueError("Protected DEV OTLP creation input unavailable") from None
    require(parameter.get("ARN") == arn)
    source_metadata({key: value for key, value in parameter.items() if key != "Value"}, chosen)
    token = parameter.get("Value")
    require(isinstance(token, str) and bool(token.strip()) and not any(char in token for char in "\r\n\x00"))
    child = dict(os.environ)
    child[PRIVATE_VARIABLE] = token
    try:
        yield child
    finally:
        child.pop(PRIVATE_VARIABLE, None)
        # Python does not guarantee secure memory erasure. The runner must be
        # ephemeral; no claim of byte zeroization or a saved-plan byte binding.


def plan_guard(plan, chosen, address=ADDRESS):
    selection(chosen)
    variables = plan.get("variables", {})
    for field in ("managed", "write_revision", "creation"):
        require("dev_otlp_source_" + field in variables)
        actual = variables["dev_otlp_source_" + field].get("value")
        # Terraform show retains TF_VAR primitive input lexemes as strings,
        # even when the root variable has a bool/number constraint.
        if field == "managed" and type(actual) is str:
            require(actual in ("true", "false"))
            actual = actual == "true"
        if field == "write_revision" and type(actual) is str:
            require(re.fullmatch(r"[1-9][0-9]*", actual) is not None)
            actual = int(actual)
        require(type(actual) is type(chosen[field]) and actual == chosen[field])
    require(variables.get("environment", {}).get("value", "development") == "development")
    changes = []
    for item in plan.get("resource_changes", []):
        change = item.get("change", {})
        values = [value for value in (change.get("before"), change.get("after")) if isinstance(value, dict)]
        relevant = item.get("address") == address or any(value.get("name") in (LEGACY, TARGET) for value in values)
        if not relevant:
            if chosen["creation"] is not None and item.get("mode", "managed") == "managed":
                # Ordinary app configuration must stay unchanged during this
                # source-only operation. Existing local Cognito packaging may
                # rebuild under the standard saved-plan runner contract.
                local_package = item.get("address") in {
                    "module.pawlocal.module.cognito_pre_sign_up.local_file.archive_plan[0]",
                    "module.pawlocal.module.cognito_pre_sign_up.null_resource.archive[0]",
                }
                require(change.get("actions") == ["no-op"] or local_package)
            continue
        require(item.get("address") == address and item.get("type") == "aws_ssm_parameter" and item.get("index") == 0)
        require(item.get("importing") is None and change.get("importing") is None)
        require(all(value.get("name") == TARGET and value.get("type") == "SecureString" and value.get("tier") == "Standard"
                    and value.get("description") == DESCRIPTION and value.get("tags") == TAGS
                    and value.get("overwrite") is None and all(value.get(key) in (None, "") for key in ("value", "insecure_value", "value_wo"))
                    and all("configuration-access" not in (value.get(key) or {}) for key in ("tags", "tags_all")) for value in values))
        after = change.get("after")
        require(isinstance(after, dict) and after.get("value_wo_version") == chosen["write_revision"])
        if chosen["creation"] is not None:
            require(change.get("actions") == ["create"] and change.get("before") is None)
            unknown = change.get("after_unknown", {})
            require(isinstance(unknown, dict) and all(not marker or key in {
                "arn", "data_type", "has_value_wo", "id", "insecure_value", "key_id", "region", "tags_all", "value", "version"
            } for key, marker in unknown.items()))
        else:
            require(change.get("actions") == ["no-op"] and change.get("before") == after and after.get("has_value_wo") is True
                    and after.get("version") == 1 and not change.get("after_unknown"))
        changes.append(item)
    require(len(changes) == (1 if chosen["managed"] else 0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-json", type=Path, required=True)
    parser.add_argument("--target-metadata-json", type=Path, required=True)
    parser.add_argument("--source-metadata-json", type=Path)
    parser.add_argument("--plan-json", type=Path)
    args = parser.parse_args()
    chosen = selection(json.loads(args.selection_json.read_text()))
    target_metadata(json.loads(args.target_metadata_json.read_text()), chosen)
    if chosen["creation"] is not None:
        require(args.source_metadata_json is not None)
        source_metadata(json.loads(args.source_metadata_json.read_text()), chosen)
    if args.plan_json:
        plan_guard(json.loads(args.plan_json.read_text()), chosen)
    print("DEV OTLP public source boundary passed; live setup remains separately approval-gated")


if __name__ == "__main__":
    main()
