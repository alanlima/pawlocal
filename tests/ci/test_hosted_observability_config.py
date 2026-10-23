"""Reject private/ambiguous operator bindings before saved Terraform plans."""

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "hosted_operator", ROOT / ".github/scripts/validate-hosted-observability.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
PUBLIC = {
    "enabled": False,
    "stack_url": "https://fixture.grafana.net/",
    "otlp_endpoint": "https://gateway.grafana.net/otlp",
    "otlp_instance_id": "12345",
    "faro_collector_url": "https://faro.grafana.net/collect/public-key",
}


@pytest.mark.parametrize("enabled", [False, True])
def test_public_modes_and_null_are_valid(enabled):
    module.validate("null", "111111111111", "ap-southeast-2")
    module.validate(
        json.dumps({**PUBLIC, "enabled": enabled}), "111111111111", "ap-southeast-2"
    )


@pytest.mark.parametrize(
    "override",
    [
        {"token": "private-sentinel"},
        {"enabled": "false"},
        {"enabled": 0},
        {"otlp_endpoint": "https://user:private@gateway.grafana.net/otlp"},
        {"otlp_endpoint": "https://gateway.grafana.net/otlp?token=private"},
        {"faro_collector_url": "https://foreign.example.test/collect/public"},
        {"otlp_instance_id": "private-user-identity"},
        {
            "kms_key_arn": "arn:aws:kms:ap-southeast-2:222222222222:key/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        },
    ],
)
def test_private_or_inconsistent_bindings_are_denied_even_when_disabled(override):
    with pytest.raises((ValueError, TypeError)):
        module.validate(
            json.dumps({**PUBLIC, **override}), "111111111111", "ap-southeast-2"
        )


def test_duplicate_field_is_denied():
    with pytest.raises(ValueError, match="Duplicate"):
        module.validate(
            '{"enabled": false, "enabled": true}', "111111111111", "ap-southeast-2"
        )


@pytest.mark.parametrize(
    "filename", ["terraform-environment.yml", "terraform-environment-destroy.yml"]
)
def test_each_saved_plan_validates_operator_object_first(filename):
    workflow = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())
    selected = 0
    for job in workflow["jobs"].values():
        if "TF_VAR_hosted_observability" not in job.get("env", {}):
            continue
        selected += 1
        steps = job["steps"]
        validation = next(
            i
            for i, step in enumerate(steps)
            if "validate-hosted-observability.py" in step.get("run", "")
        )
        plan = next(
            i for i, step in enumerate(steps) if " plan " in step.get("run", "")
        )
        assert validation < plan
        assert "|| 'null'" in job["env"]["TF_VAR_hosted_observability"]
    assert selected == (1 if filename == "terraform-environment.yml" else 2)
