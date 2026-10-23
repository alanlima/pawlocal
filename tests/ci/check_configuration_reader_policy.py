"""Evaluate the real provider-compiled #237 policies from terraform test JSON.

This deliberately supports only this narrow single-statement policy contract;
unknown operators/schema fail rather than approximating broader IAM behavior.
"""

import fnmatch
import json
import sys
from pathlib import Path


def evaluate(document, action, resource, tags):
    statements = document["Statement"]
    assert len(statements) == 1
    statement = statements[0]
    assert statement["Effect"] == "Allow"
    assert set(statement["Condition"]) == {"StringEquals"}
    conditions = statement["Condition"]["StringEquals"]
    assert set(conditions) == {
        "aws:ResourceTag/project",
        "aws:ResourceTag/environment",
        "aws:ResourceTag/configuration-access",
    }
    actions = statement["Action"]
    resources = statement["Resource"]
    actions = [actions] if isinstance(actions, str) else actions
    resources = [resources] if isinstance(resources, str) else resources
    assert actions == ["ssm:GetParameter"] and len(resources) == 1
    return (
        action in actions
        and any(fnmatch.fnmatchcase(resource, arn) for arn in resources)
        and all(
            tags.get(key.removeprefix("aws:ResourceTag/")) == expected
            for key, expected in conditions.items()
        )
    )


def check(path):
    policies = {}
    summaries = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        event = json.loads(line)
        if event.get("type") == "test_summary":
            summaries.append(event["test_summary"])
        if event.get("@testrun") != "configuration_readers_are_exact_and_isolated":
            continue
        for change in event.get("test_plan", {}).get("resource_changes", []):
            if (
                change["type"] == "aws_iam_role_policy"
                and change["name"] == "configuration_reader"
            ):
                policies[change["index"]] = json.loads(
                    change["change"]["after"]["policy"]
                )
    assert summaries and all(summary["failed"] == 0 for summary in summaries)
    assert set(policies) == {"development", "production"}
    cases = 0
    for environment, document in policies.items():
        prefix = "arn:aws:ssm:ap-southeast-2:111111111111:parameter/"
        # A newly named public key outside all suffix inventories requires no IAM edit.
        arn = prefix + "new-arbitrary-public-setting"
        tags = {
            "project": "pawlocal",
            "environment": environment,
            "configuration-access": "github-public",
        }
        assert evaluate(document, "ssm:GetParameter", arn, tags)
        cases += 1
        for key in tags:
            for other in (None, "wrong"):
                candidate = dict(tags)
                if other is None:
                    del candidate[key]
                else:
                    candidate[key] = other
                assert not evaluate(document, "ssm:GetParameter", arn, candidate)
                cases += 1
        for private in ("runtime", "private", "oncall-secret"):
            assert not evaluate(
                document,
                "ssm:GetParameter",
                prefix + "pawlocal/" + environment + "/secrets/grafana/webhook-hmac",
                tags | {"configuration-access": private},
            )
            cases += 1
        for foreign in (
            arn.replace(":111111111111:", ":222222222222:"),
            arn.replace(":ap-southeast-2:", ":us-east-1:"),
        ):
            assert not evaluate(document, "ssm:GetParameter", foreign, tags)
            cases += 1
        other = "production" if environment == "development" else "development"
        assert not evaluate(
            document, "ssm:GetParameter", arn, tags | {"environment": other}
        )
        cases += 1
        for action in (
            "ssm:GetParameters",
            "ssm:GetParametersByPath",
            "ssm:GetParameterHistory",
            "ssm:DescribeParameters",
            "ssm:PutParameter",
            "ssm:DeleteParameter",
            "ssm:AddTagsToResource",
            "ssm:RemoveTagsFromResource",
            "kms:Decrypt",
        ):
            assert not evaluate(document, action, arn, tags)
            cases += 1
    assert (
        abs(
            len(json.dumps(policies["development"]))
            - len(json.dumps(policies["production"]))
        )
        <= 1
    )
    print(f"Compiled tag-based reader policies: {cases} admission/denial cases passed")


if __name__ == "__main__":
    check(sys.argv[1])
