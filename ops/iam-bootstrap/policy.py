"""Render the external #191 identity's exact bootstrap permissions; no AWS calls."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

USER = "pawlocal-terraform-bootstrap-actions"
POLICIES = (USER + "-iam", USER + "-storage")
BOUNDARY = USER + "-boundary"
STATE_KEY = "pawlocal/iam-bootstrap/terraform.tfstate"
ENVIRONMENTS = ("development", "production")
SUFFIXES = (
    "iam/terraform-plan-role-arn", "iam/terraform-apply-role-arn", "aws/account-id",
    "terraform/plan-bucket", "iam/frontend-publish-role-arn", "iam/runtime-role-arn",
)


def compact(value: dict) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def validate_config(config: dict) -> dict:
    if set(config) != {"account_id", "region", "state_bucket"}:
        raise ValueError("Configuration requires only account_id, region, state_bucket")
    patterns = {"account_id": r"[0-9]{12}", "region": r"ap-southeast-2",
                "state_bucket": r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]"}
    if any(not isinstance(config[k], str) or not re.fullmatch(p, config[k])
           for k, p in patterns.items()):
        raise ValueError("Invalid identity policy configuration")
    if config["state_bucket"] == "pawlocal-terraform-plans-" + config["account_id"]:
        raise ValueError("State and transfer buckets must differ")
    return config


def inventory(config: dict) -> dict:
    validate_config(config)
    iam = f"arn:aws:iam::{config['account_id']}:"
    role_names = ["pawlocal-legacy-terraform-plan", "pawlocal-legacy-terraform-apply",
                  "pawlocal-identity-terraform-plan", "pawlocal-identity-terraform-apply"]
    policy_names = ["pawlocal-app-role-boundary", "pawlocal-production-app-role-boundary"]
    for env in ENVIRONMENTS:
        role_names += [f"pawlocal-{env}-{suffix}" for suffix in (
            "terraform-plan", "terraform-apply", "github-deploy", "dsql-runtime",
            "configuration-reader", "cognito-terraform-plan", "cognito-terraform-apply",
            "cognito-pre-signup")]
        policy_names += [f"pawlocal-{env}-terraform-apply-boundary",
                         f"pawlocal-{env}-cognito-terraform-apply-boundary"]
    return {
        "roles": [iam + "role/" + name for name in sorted(role_names)],
        "policies": [iam + "policy/" + name for name in sorted(policy_names)],
        "oidc": iam + "oidc-provider/token.actions.githubusercontent.com",
        "slr": iam + "role/aws-service-role/dsql.amazonaws.com/AWSServiceRoleForAuroraDsql",
        "parameters": [f"arn:aws:ssm:{config['region']}:{config['account_id']}:parameter/"
                       f"pawlocal/{env}/config/{suffix}"
                       for env in ENVIRONMENTS for suffix in SUFFIXES],
        "state_bucket": "arn:aws:s3:::" + config["state_bucket"],
        "transfer_bucket": "arn:aws:s3:::pawlocal-terraform-plans-" + config["account_id"],
    }


def render(config: dict) -> dict:
    """Identity and independently owned boundary share a deterministic ceiling.

    Mixed IAM resource kinds in one statement are intentional: AWS authorizes
    each action against its supported resource kind. No role/user wildcard.
    """
    graph = inventory(config)
    statements = []

    def allow(actions, resources, condition=None):
        statement = {"Effect": "Allow", "Action": actions, "Resource": resources}
        if condition:
            statement["Condition"] = condition
        statements.append(statement)

    allow(["sts:GetCallerIdentity"], ["*"])
    allow([
        "iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies",
        "iam:ListAttachedRolePolicies", "iam:ListRoleTags", "iam:ListInstanceProfilesForRole",
        "iam:CreateRole", "iam:UpdateRole", "iam:UpdateAssumeRolePolicy",
        "iam:DeleteRole", "iam:PutRolePolicy", "iam:DeleteRolePolicy",
        "iam:TagRole", "iam:UntagRole", "iam:PutRolePermissionsBoundary",
        "iam:DeleteRolePermissionsBoundary",
        "iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListPolicyVersions", "iam:ListPolicyTags",
        "iam:CreatePolicy", "iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion",
        "iam:DeletePolicyVersion", "iam:DeletePolicy", "iam:TagPolicy", "iam:UntagPolicy",
        "iam:GetOpenIDConnectProvider", "iam:ListOpenIDConnectProviderTags",
        "iam:CreateOpenIDConnectProvider", "iam:DeleteOpenIDConnectProvider",
        "iam:AddClientIDToOpenIDConnectProvider", "iam:RemoveClientIDFromOpenIDConnectProvider",
        "iam:UpdateOpenIDConnectProviderThumbprint", "iam:TagOpenIDConnectProvider",
        "iam:UntagOpenIDConnectProvider",
    ], graph["roles"] + graph["policies"] + [graph["oidc"]])
    allow(["iam:GetRole"], [graph["slr"]])
    allow(["iam:CreateServiceLinkedRole"], [graph["slr"]],
          {"StringEquals": {"iam:AWSServiceName": "dsql.amazonaws.com"}})
    # DeleteServiceLinkedRole and its wildcard deletion-status polling are
    # deliberately excluded: retirement is a separately reviewed operation.
    state = graph["state_bucket"] + "/" + STATE_KEY
    lock = state + ".tflock"
    plan = graph["transfer_bucket"] + "/plans/iam-bootstrap/*"
    allow(["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject"], [state, lock, plan])
    allow(["s3:DeleteObject"], [lock])
    allow(["s3:ListBucket"], [graph["state_bucket"]],
          {"StringEquals": {"s3:prefix": [STATE_KEY, STATE_KEY + ".tflock"]}})
    allow(["s3:GetBucketLocation", "s3:GetBucketVersioning", "s3:GetEncryptionConfiguration"],
          [graph["state_bucket"]])
    # HeadBucket is authorized by ListBucket, with no prefix available. This
    # reveals key metadata in the shared transfer bucket but grants no object
    # values outside the bootstrap prefix above.
    allow(["s3:ListBucket"], [graph["transfer_bucket"]])
    allow([
        "s3:GetBucketLocation", "s3:GetBucketVersioning", "s3:GetEncryptionConfiguration",
        "s3:GetBucketAcl", "s3:GetBucketCORS", "s3:GetBucketLogging", "s3:GetBucketPolicy",
        "s3:GetBucketPolicyStatus", "s3:GetBucketPublicAccessBlock", "s3:GetBucketTagging",
        "s3:GetBucketWebsite", "s3:GetBucketRequestPayment", "s3:GetAccelerateConfiguration",
        "s3:GetBucketObjectLockConfiguration", "s3:GetBucketOwnershipControls",
        "s3:GetLifecycleConfiguration", "s3:GetReplicationConfiguration", "s3:ListTagsForResource",
        "s3:PutBucketTagging", "s3:TagResource", "s3:UntagResource",
        "s3:PutBucketPolicy", "s3:PutBucketPublicAccessBlock", "s3:PutBucketOwnershipControls",
        "s3:PutEncryptionConfiguration", "s3:PutBucketVersioning", "s3:PutLifecycleConfiguration",
    ], [graph["transfer_bucket"]])
    allow(["ssm:GetParameter", "ssm:PutParameter", "ssm:DeleteParameter",
           "ssm:ListTagsForResource", "ssm:AddTagsToResource", "ssm:RemoveTagsFromResource"],
          graph["parameters"])
    allow(["ssm:DescribeParameters"], ["*"],
          {"StringEquals": {"aws:RequestedRegion": config["region"]}})
    policy = {"Version": "2012-10-17", "Statement": statements}
    # A single exact grant exceeds IAM's 6144-character managed-policy limit.
    # Split grants by service. Only the boundary compresses read actions; the
    # intersection with the explicit grants is the reviewed effective scope.
    iam_statements = [s for s in statements if s["Action"][0].split(":")[0] in ("iam", "sts")]
    storage_statements = [s for s in statements if s not in iam_statements]
    boundary = json.loads(compact(policy))
    # IAM resource policies cannot grant IAM administrative API permissions;
    # keep the service-linked role's read in the same ceiling resource list.
    # Its identity grant still authorizes only GetRole and constrained creation.
    boundary["Statement"][1]["Resource"].append(graph["slr"])
    boundary["Statement"].pop(2)
    s3_statements = [s for s in boundary["Statement"] if s["Action"][0].startswith("s3:")]
    boundary["Statement"] = [s for s in boundary["Statement"] if s not in s3_statements]
    # Coalesce S3 read/object ceiling statements to leave room for explicit
    # denies. Exact identity grants retain action and state-list conditions.
    # Bucket configuration mutations remain only on the transfer bucket.
    config_actions = [a for s in s3_statements for a in s["Action"]
                      if not a.startswith("s3:Get") and a not in (
                          "s3:ListBucket", "s3:ListTagsForResource", "s3:PutObject", "s3:DeleteObject")]
    boundary["Statement"] += [
        {"Effect": "Allow", "Action": ["s3:Get*", "s3:ListBucket", "s3:ListTagsForResource",
                                         "s3:PutObject", "s3:DeleteObject"],
         "Resource": [graph["state_bucket"], graph["transfer_bucket"], state, lock, plan]},
        {"Effect": "Allow", "Action": sorted(set(config_actions)), "Resource": [graph["transfer_bucket"]]},
        {"Effect": "Deny", "Action": ["sts:AssumeRole*", "iam:PassRole"], "Resource": ["*"]},
        {"Effect": "Deny", "Action": ["s3:*"],
         "NotResource": [graph["state_bucket"], graph["transfer_bucket"], state, lock, plan]},
        {"Effect": "Deny", "Action": ["s3:Delete*"], "NotResource": [lock]},
    ]
    for statement in boundary["Statement"]:
        actions = statement["Action"]
        reads = {a for a in actions if a.startswith(("iam:Get", "iam:List", "s3:Get"))}
        if len(reads) > 1:
            statement["Action"] = [a for a in actions if a not in reads] + sorted({
                a.split(":")[0] + ":" + ("Get*" if ":Get" in a else "List*") for a in reads
            })
    documents = {
        "permissions-iam.json": {"Version": "2012-10-17", "Statement": iam_statements},
        "permissions-storage.json": {"Version": "2012-10-17", "Statement": storage_statements},
        "boundary.json": boundary,
    }
    for document in documents.values():
        if len(compact(document)) > 6144:
            raise ValueError(f"Managed policy exceeds 6144-character limit ({len(compact(document))})")
    return documents


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    documents = render(json.loads(args.config.read_text(encoding="utf-8")))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, document in documents.items():
        (args.output_dir / name).write_text(compact(document) + "\n", encoding="utf-8")
    print("Rendered permissions and boundary; review both before installing")


if __name__ == "__main__":
    main()
