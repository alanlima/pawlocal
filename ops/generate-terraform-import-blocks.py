#!/usr/bin/env python3
"""Generate private Terraform import blocks from a state snapshot on stdin.

This tool writes only configuration-driven `import` blocks. It does not alter
state or call AWS. Import identifiers are account-specific and must stay in an
ignored local file; never commit or print that generated file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SHARED_ADDRESSES = {
    "aws_iam_openid_connect_provider.github[0]": "aws_iam_openid_connect_provider.github[0]",
    "aws_iam_role.github_deploy": "aws_iam_role.github_deploy",
    "aws_iam_role_policy.github_deploy": "aws_iam_role_policy.github_deploy",
    'module.fullstack.aws_iam_role.github_deploy["development"]': "aws_iam_role.github_deploy_development",
    'module.fullstack.aws_iam_role_policy.github_deploy["development"]': "aws_iam_role_policy.github_deploy_development",
    'module.fullstack.aws_iam_role.github_terraform_deploy["development"]': 'aws_iam_role.github_terraform_deploy["development"]',
    'module.fullstack.aws_iam_role.github_terraform_deploy["production"]': 'aws_iam_role.github_terraform_deploy["production"]',
    'module.fullstack.aws_iam_role_policy.github_terraform_deploy["development"]': 'aws_iam_role_policy.github_terraform_deploy["development"]',
    'module.fullstack.aws_iam_role_policy.github_terraform_deploy["production"]': 'aws_iam_role_policy.github_terraform_deploy["production"]',
}


def quote_hcl(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def address_for(resource: dict, instance: dict) -> str:
    prefix = f'{resource["module"]}.' if resource.get("module") else ""
    address = f'{prefix}{resource["type"]}.{resource["name"]}'
    key = instance.get("index_key")
    if key is not None:
        address += f"[{json.dumps(key)}]"
    return address


def import_id(resource: dict, instance: dict) -> str:
    attributes = instance.get("attributes", {})
    value = attributes.get("id")
    # The AWS provider stores the DSQL identifier but does not populate `id`.
    if value in (None, "") and resource["type"] in {"aws_dsql_cluster", "aws_dsql_cluster_policy"}:
        value = attributes.get("identifier")
    if not isinstance(value, str) or not value:
        raise ValueError(f'No import identifier for {address_for(resource, instance)}')
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layer", choices=("shared", "app", "legacy"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    state = json.load(sys.stdin)
    found_shared: set[str] = set()
    found_app: set[str] = set()
    blocks: list[tuple[str, str, str]] = []

    for resource in state.get("resources", []):
        if resource.get("mode", "managed") != "managed":
            continue
        for instance in resource.get("instances", []):
            source = address_for(resource, instance)
            target = SHARED_ADDRESSES.get(source, source)
            layer = "shared" if source in SHARED_ADDRESSES else "app"
            (found_shared if layer == "shared" else found_app).add(source)
            if layer == args.layer or args.layer == "legacy":
                destination = source if args.layer == "legacy" else target
                blocks.append((destination, import_id(resource, instance), source))

    if found_shared != set(SHARED_ADDRESSES):
        missing = sorted(set(SHARED_ADDRESSES) - found_shared)
        unexpected = sorted(found_shared - set(SHARED_ADDRESSES))
        raise SystemExit(f"State address inventory mismatch; missing={missing}, unexpected={unexpected}")
    if len(found_app) != 46:
        raise SystemExit(f"Expected 46 app-managed instances in serial {state.get('serial')}, found {len(found_app)}")
    if args.layer == "legacy" and len(blocks) != 55:
        raise SystemExit(f"Expected 55 total managed instances in serial {state.get('serial')}, found {len(blocks)}")

    lines = [
        "# Generated from the reviewed PawLocal state snapshot.",
        "# Contains account-specific import identifiers; do not commit this file.",
        "",
    ]
    for target, identifier, source in sorted(blocks):
        lines.extend(
            [
                "import {",
                f"  to = {target}",
                f"  id = {quote_hcl(identifier)}",
                "}",
                "",
            ]
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"Generated {len(blocks)} {args.layer} import blocks from state serial {state.get('serial')}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"Cannot generate Terraform import blocks: {exc}", file=sys.stderr)
        raise SystemExit(2)
