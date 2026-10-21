from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from pawlocal import dsql_post_apply_setup
from pawlocal.dsql_post_apply_setup import (
    SetupConfiguration,
    execute_setup,
    validate_apply_identity,
)


def _configuration(environment="development"):
    return SetupConfiguration(
        environment=environment,
        endpoint="cluster.dsql.ap-southeast-2.on.aws",
        region="ap-southeast-2",
        database_role=f"pawlocal_{environment}_app",
        runtime_role_arn=(
            f"arn:aws:iam::123456789012:role/pawlocal-{environment}-dsql-runtime"
        ),
    )


def test_configuration_rejects_cross_environment_identity():
    configuration = _configuration()
    configuration = SetupConfiguration(
        **{
            **configuration.__dict__,
            "runtime_role_arn": (
                "arn:aws:iam::123456789012:role/pawlocal-production-dsql-runtime"
            ),
        }
    )

    with pytest.raises(ValueError, match="cross-environment"):
        configuration.validate()


def test_apply_identity_is_exact_environment_and_account():
    configuration = _configuration()
    validate_apply_identity(
        configuration,
        "arn:aws:sts::123456789012:assumed-role/"
        "pawlocal-development-terraform-apply/github-actions",
    )

    with pytest.raises(RuntimeError, match="matching protected apply role"):
        validate_apply_identity(
            configuration,
            "arn:aws:sts::123456789012:assumed-role/"
            "pawlocal-production-terraform-apply/github-actions",
        )


def test_two_phase_setup_orders_admin_before_application_postconditions(monkeypatch):
    calls = []
    monkeypatch.setattr(
        dsql_post_apply_setup,
        "ensure_app_role",
        lambda *_args: calls.append("admin"),
    )
    monkeypatch.setattr(
        dsql_post_apply_setup,
        "run_dsql_migrations",
        lambda *_args: calls.append("baseline"),
    )
    monkeypatch.setattr(
        dsql_post_apply_setup,
        "verify_dsql_baseline",
        lambda *_args, **_kwargs: calls.append("postconditions"),
    )

    execute_setup(_configuration(), object(), object())

    assert calls == ["admin", "baseline", "postconditions"]


@pytest.mark.parametrize("environment", ["development", "production"])
def test_two_phase_setup_accepts_matching_environment_identity(environment):
    configuration = _configuration(environment)
    configuration.validate()
    validate_apply_identity(
        configuration,
        f"arn:aws:sts::123456789012:assumed-role/"
        f"pawlocal-{environment}-terraform-apply/github-actions",
    )


def test_retry_after_admin_failure_reruns_both_phases(monkeypatch):
    calls = []
    attempts = {"admin": 0}

    def ensure(*_args):
        calls.append("admin")
        attempts["admin"] += 1
        if attempts["admin"] == 1:
            raise RuntimeError("admin phase failed")

    monkeypatch.setattr(dsql_post_apply_setup, "ensure_app_role", ensure)
    monkeypatch.setattr(
        dsql_post_apply_setup,
        "run_dsql_migrations",
        lambda *_args: calls.append("baseline"),
    )
    monkeypatch.setattr(
        dsql_post_apply_setup,
        "verify_dsql_baseline",
        lambda *_args, **_kwargs: calls.append("postconditions"),
    )

    with pytest.raises(RuntimeError, match="admin phase failed"):
        execute_setup(_configuration(), object(), object())
    execute_setup(_configuration(), object(), object())

    assert calls == ["admin", "admin", "baseline", "postconditions"]


def test_retry_after_application_failure_reasserts_admin_first(monkeypatch):
    calls = []
    attempts = {"baseline": 0}

    def migrate(*_args):
        calls.append("baseline")
        attempts["baseline"] += 1
        if attempts["baseline"] == 1:
            raise RuntimeError("partial application phase")

    monkeypatch.setattr(
        dsql_post_apply_setup,
        "ensure_app_role",
        lambda *_args: calls.append("admin"),
    )
    monkeypatch.setattr(dsql_post_apply_setup, "run_dsql_migrations", migrate)
    monkeypatch.setattr(
        dsql_post_apply_setup,
        "verify_dsql_baseline",
        lambda *_args, **_kwargs: calls.append("postconditions"),
    )

    with pytest.raises(RuntimeError, match="partial application phase"):
        execute_setup(_configuration(), object(), object())
    execute_setup(_configuration(), object(), object())

    assert calls == [
        "admin",
        "baseline",
        "admin",
        "baseline",
        "postconditions",
    ]


def test_main_sanitizes_partial_failure_and_returns_nonzero(monkeypatch, capsys):
    configuration = _configuration()
    monkeypatch.setattr(
        SetupConfiguration,
        "from_environment",
        classmethod(lambda _cls: configuration),
    )

    boto3 = ModuleType("boto3")
    boto3.client = lambda _name: SimpleNamespace(
        get_caller_identity=lambda: {
            "Arn": "arn:aws:sts::123456789012:assumed-role/"
            "pawlocal-development-terraform-apply/github-actions"
        }
    )
    monkeypatch.setitem(sys.modules, "boto3", boto3)

    class Engine:
        def dispose(self):
            pass

    monkeypatch.setattr(
        dsql_post_apply_setup,
        "_create_engines",
        lambda _configuration: (Engine(), Engine()),
    )
    monkeypatch.setattr(
        dsql_post_apply_setup,
        "ensure_app_role",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        dsql_post_apply_setup,
        "run_dsql_migrations",
        lambda *_args: (_ for _ in ()).throw(
            RuntimeError("sensitive endpoint and SQL must not be printed")
        ),
    )

    assert dsql_post_apply_setup.main() == 1
    output = capsys.readouterr().err
    assert "environment=development" in output
    assert "phase=application" in output
    assert "class=RuntimeError" in output
    assert "sensitive endpoint" not in output
