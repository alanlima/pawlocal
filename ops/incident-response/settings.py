"""Read-only verification of one-time autonomous runtime settings."""

from quota import Denied

RUNTIME_ENVIRONMENTS = (
    "development",
    "development-plan",
    "development-apply",
    "production",
    "production-plan",
    "production-apply",
    "oncall-development",
    "oncall-production",
)


def environment_ready(client, name):
    if name not in RUNTIME_ENVIRONMENTS:
        raise Denied("unsupported runtime environment")
    environment = client.request("GET", "/environments/" + name)
    # A one-time reviewed setup must remove runtime human review and constrain
    # deployment branches. Do not silently bypass or edit those settings.
    rules = environment.get("protection_rules")
    if (
        not isinstance(rules, list)
        or any(rule.get("type") != "branch_policy" for rule in rules)
        or len(rules) > 1
        or environment.get("deployment_branch_policy")
        != {"protected_branches": False, "custom_branch_policies": True}
    ):
        raise Denied("automatic production environment protection setup missing")
    policies = client.request(
        "GET", "/environments/" + name + "/deployment-branch-policies?per_page=100"
    )
    rows = policies.get("branch_policies", [])
    if (
        policies.get("total_count") != 1
        or len(rows) != 1
        or rows[0].get("name") != "main"
        or rows[0].get("type") != "branch"
    ):
        raise Denied("production environment must admit only the main branch")


def production_ready(client):
    environment_ready(client, "production")


def runtime_ready(client):
    # Never inspect or weaken separately gated bootstrap, destroy or setup
    # targets. Every target actually entered by automated release is checked.
    for name in RUNTIME_ENVIRONMENTS:
        environment_ready(client, name)
