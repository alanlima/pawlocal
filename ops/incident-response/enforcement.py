"""Temporary owner-approved incident policy switch (#375 / DEC-017).

Operational decoding, actual API acknowledgements and credential isolation are
not policy verdicts. Call sites choose which decisions this switch controls.
"""

import os
import sys
import time

FLAG = "PAWLOCAL_ONCALL_ENFORCE_GUARDS"
CATEGORIES = (
    "admission",
    "authorization",
    "readiness",
    "continuity",
    "deduplication",
    "budget",
    "stop",
    "deadline",
    "candidate",
    "checks",
    "review",
    "publication",
    "merge",
    "release",
    "recovery",
    "receipts",
)
_reported = set()


def enabled():
    value = os.environ.get(FLAG, "false")
    if value not in {"", "false", "true"}:
        raise ValueError(f"{FLAG} must be true or false")
    return value == "true"


def skipped(category):
    if category not in CATEGORIES:
        raise ValueError("unknown incident policy category")
    if category not in _reported:
        print(f"[incident-enforcement] disabled: {category}", file=sys.stderr)
        _reported.add(category)


def policy(condition, reason, category):
    if enabled():
        if not condition:
            from quota import Denied

            raise Denied(reason)
    else:
        skipped(category)


def evidence():
    active = enabled()
    return {
        "enabled": active,
        "disabled_categories": [] if active else list(CATEGORIES),
    }


def operational_deadline():
    """Finite transport timeout arithmetic; Actions still terminates its jobs."""
    skipped("deadline")
    return int(time.time()) + 7 * 86400
