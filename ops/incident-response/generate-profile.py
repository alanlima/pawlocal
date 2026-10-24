#!/usr/bin/env python3
"""Generate a ready-to-paste PAWLOCAL_ONCALL_MODEL_PROFILE JSON.

Usage:
    python ops/incident-response/generate-profile.py \\
        --dev-rule-uid <grafana-dev-alert-rule-uid> \\
        --prod-rule-uid <grafana-prod-alert-rule-uid>

All other fields use the recommended o4-mini/medium defaults and
auto-compute the current month, review timestamp and 30-day expiry.

The output is a single-line JSON string suitable for pasting directly
into a GitHub Environment variable.
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

# Add current directory for quota import
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))
from quota import Profile


def main():
    parser = argparse.ArgumentParser(
        description="Generate PAWLOCAL_ONCALL_MODEL_PROFILE JSON"
    )
    parser.add_argument(
        "--dev-rule-uid",
        default="",
        help="Optional Grafana alert rule UID for dev (default: empty, matches dynamically by alert_name)",
    )
    parser.add_argument(
        "--prod-rule-uid",
        default="",
        help="Optional Grafana alert rule UID for prod (default: empty, matches dynamically by alert_name)",
    )
    parser.add_argument(
        "--approval",
        default="alanlima/pawlocal/issues/269",
        help="Approval reference (default: alanlima/pawlocal/issues/269)",
    )
    parser.add_argument(
        "--model",
        default="o4-mini",
        help="Model name (default: o4-mini)",
    )
    parser.add_argument(
        "--effort",
        default="medium",
        choices=["minimal", "low", "medium", "high", "xhigh"],
        help="Reasoning effort (default: medium)",
    )
    parser.add_argument(
        "--monthly-budget-usd",
        type=float,
        default=20.0,
        help="Monthly spending ceiling in USD (default: 20.00)",
    )
    parser.add_argument(
        "--monthly-runs",
        type=int,
        default=20,
        help="Maximum incident runs per month (default: 20)",
    )
    args = parser.parse_args()

    now = dt.datetime.now(dt.UTC)
    reviewed_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    expires_at = (now + dt.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    approved_month = now.strftime("%Y-%m")

    profile = {
        "model": args.model,
        "effort": args.effort,
        "service_tier": "default",
        "input_rate": 1100000,
        "output_rate": 4400000,
        "monthly_microdollars": int(args.monthly_budget_usd * 1_000_000),
        "monthly_runs": args.monthly_runs,
        "promotion_seconds": 3600,
        "recovery_seconds": 720,
        "rule_uids": (
            {
                "development": args.dev_rule_uid,
                "production": args.prod_rule_uid,
            }
            if (args.dev_rule_uid or args.prod_rule_uid)
            else {}
        ),
        "requests_per_role": 4,
        "input_per_request": 100000,
        "output_per_request": 16000,
        "input_per_role": 200000,
        "output_per_role": 32000,
        "approval": args.approval,
        "approved_month": approved_month,
        "rates_source": "https://platform.openai.com/docs/pricing",
        "rates_reviewed_at": reviewed_at,
        "expires_at": expires_at,
    }

    output = json.dumps(profile, separators=(",", ":"))
    print(output)

    # Validate it actually passes the gate
    Profile.load(output, now=now.timestamp())
    print("\n✓ Profile passes quota.py validation", file=sys.stderr)


if __name__ == "__main__":
    main()
