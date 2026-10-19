#!/usr/bin/env python3
"""Fail closed unless a targeted plan changes only the selected SSH /32."""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
from collections.abc import Iterable
from typing import Any


def _normalize(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _port_blocks(resource: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = resource.get("port_info")
    if not isinstance(blocks, list):
        raise ValueError("Target firewall resource has no decoded port_info before/after state")
    return blocks


def _matches_exact_tcp(block: dict[str, Any], port: int) -> bool:
    return (
        str(block.get("protocol", "")).lower() == "tcp"
        and block.get("from_port") == port
        and block.get("to_port") == port
    )


def _web_ports(blocks: Iterable[dict[str, Any]]) -> dict[int, list[str]]:
    values: dict[int, list[str]] = {80: [], 443: []}
    for block in blocks:
        for port in values:
            if _matches_exact_tcp(block, port):
                # Compare only requested firewall semantics. AWS provider computed
                # aliases can be unknown during a plan and are not security rules.
                semantic = {key: (block.get(key) or []) if key in (
                    "cidrs", "ipv6_cidrs", "cidr_list_aliases"
                ) else block.get(key) for key in (
                    "protocol", "from_port", "to_port", "cidrs", "ipv6_cidrs", "cidr_list_aliases"
                )}
                values[port].append(_normalize(semantic))
    if not values[80] or not values[443]:
        raise ValueError("Both existing TCP/80 and TCP/443 rules must remain present")
    return values


def _ssh_cidrs(blocks: Iterable[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for block in blocks:
        protocol = str(block.get("protocol", "")).lower()
        start, end = block.get("from_port"), block.get("to_port")
        if protocol == "tcp" and isinstance(start, int) and isinstance(end, int) and start <= 22 <= end:
            if start != 22 or end != 22:
                raise ValueError("A broad TCP rule overlaps SSH port 22")
            aliases = block.get("cidr_list_aliases") or []
            if aliases:
                raise ValueError("SSH ingress may not include Lightsail CIDR aliases")
            ipv6_cidrs = block.get("ipv6_cidrs") or []
            if ipv6_cidrs:
                raise ValueError("SSH ingress may not include IPv6 CIDRs")
            cidrs = block.get("cidrs") or []
            if not isinstance(cidrs, list) or not all(isinstance(value, str) for value in cidrs):
                raise ValueError("SSH CIDRs are not a valid list")
            result.update(cidrs)
    return result


def _other_rules(blocks: Iterable[dict[str, Any]]) -> list[str]:
    result = []
    for block in blocks:
        if _matches_exact_tcp(block, 22) or _matches_exact_tcp(block, 80) or _matches_exact_tcp(block, 443):
            continue
        result.append(_normalize(block))
    return sorted(result)


def _validate_runner_cidr(value: str) -> str:
    network = ipaddress.ip_network(value, strict=True)
    if network.version != 4 or network.prefixlen != 32:
        raise ValueError("The runner ingress must be one IPv4 /32")
    return str(network)


def validate(plan: dict[str, Any], operation: str, environment: str, runner_cidr: str, baseline_json: str) -> None:
    runner_cidr = _validate_runner_cidr(runner_cidr)
    baseline_by_environment = json.loads(baseline_json)
    if not isinstance(baseline_by_environment, dict) or environment not in baseline_by_environment:
        raise ValueError("The baseline SSH CIDR map must contain the selected environment")
    baseline = baseline_by_environment[environment]
    if not isinstance(baseline, list) or not baseline or not all(isinstance(value, str) for value in baseline):
        raise ValueError("The selected environment needs a nonempty baseline IPv4 CIDR list")
    baseline_set = set()
    for value in baseline:
        network = ipaddress.ip_network(value, strict=True)
        if network.version != 4 or network.prefixlen == 0:
            raise ValueError("Baseline SSH CIDRs must be restricted IPv4 networks")
        baseline_set.add(str(network))
    if runner_cidr in baseline_set:
        raise ValueError("Runner CIDR is already in the baseline; refusing ambiguous ingress state")

    expected_address = f'module.fullstack.aws_lightsail_instance_public_ports.api["{environment}"]'
    changes = [
        item
        for item in plan.get("resource_changes", [])
        if item.get("change", {}).get("actions") != ["no-op"]
    ]
    if len(changes) != 1:
        raise ValueError(f"Expected exactly one changed firewall resource, found {len(changes)}")
    resource_change = changes[0]
    if resource_change.get("address") != expected_address:
        raise ValueError(f"Only {expected_address} may change")
    change = resource_change.get("change", {})
    actions = change.get("actions")
    recovery_create = operation == "restore" and actions == ["create"]
    if actions not in (["update"], ["delete", "create"]) and not recovery_create:
        raise ValueError("The selected firewall must be an update, provider-required replacement, or restore-only recreation")
    before = change.get("before")
    after = change.get("after")
    if not isinstance(after, dict):
        raise ValueError("The plan must include proposed firewall rules")
    after_unknown = change.get("after_unknown", {})
    if isinstance(after_unknown, dict) and after_unknown.get("port_info"):
        raise ValueError("The plan contains unknown firewall rules and cannot be validated safely")

    expected_instance = f"pawlocal-{environment}-api"
    if after.get("instance_name") != expected_instance:
        raise ValueError("The plan targets an unexpected Lightsail instance")
    if recovery_create:
        if before is not None:
            raise ValueError("A create-only recovery plan must not claim prior firewall state")
        after_blocks = _port_blocks(after)
        if _ssh_cidrs(after_blocks) != baseline_set:
            raise ValueError("Restore-only recreation must install exactly the baseline SSH CIDRs")
        _web_ports(after_blocks)
        if any(
            _matches_exact_tcp(block, port) and (block.get("cidr_list_aliases") or [])
            for block in after_blocks for port in (80, 443)
        ):
            raise ValueError("Restore-only recreation may not include web port aliases")
        if _other_rules(after_blocks):
            raise ValueError("Restore-only recreation may contain only SSH, HTTP, and HTTPS rules")
        return

    if not isinstance(before, dict):
        raise ValueError("The plan must include prior firewall rules")
    if before.get("instance_name") != expected_instance:
        raise ValueError("The prior firewall belongs to an unexpected Lightsail instance")
    before_blocks, after_blocks = _port_blocks(before), _port_blocks(after)

    if _web_ports(before_blocks) != _web_ports(after_blocks):
        raise ValueError("The plan changes public TCP/80 or TCP/443 rules")
    if _other_rules(before_blocks) != _other_rules(after_blocks):
        raise ValueError("The plan changes a non-SSH, non-web public port rule")

    before_ssh, after_ssh = _ssh_cidrs(before_blocks), _ssh_cidrs(after_blocks)
    expected_after = baseline_set | {runner_cidr} if operation == "open" else baseline_set
    if operation == "open":
        if before_ssh != baseline_set:
            raise ValueError("Before opening, SSH ingress must exactly match baseline CIDRs; clean up stale runner CIDRs first")
        if after_ssh != expected_after:
            raise ValueError("Open plan must add only this runner /32 to the selected environment baseline")
    else:
        if before_ssh != (baseline_set | {runner_cidr}):
            raise ValueError("Before restoring, SSH ingress must exactly match baseline plus this run's /32")
        if after_ssh != baseline_set:
            raise ValueError("Restore plan must remove only this run's /32 and retain the baseline")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operation", choices=("open", "restore"), required=True)
    parser.add_argument("--environment", choices=("development", "production"), required=True)
    parser.add_argument("--runner-cidr", required=True)
    parser.add_argument("--baseline-cidrs-json", required=True)
    args = parser.parse_args()

    try:
        plan = json.load(sys.stdin)
        validate(plan, args.operation, args.environment, args.runner_cidr, args.baseline_cidrs_json)
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        print(f"Refusing Terraform ingress plan: {exc}", file=sys.stderr)
        return 2
    print(f"Validated exactly one {args.operation} firewall change for {args.environment}; web and other port rules are unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
