import datetime as dt
import importlib.util
import json
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[2] / "ops/incident-response/quota.py"
SPEC = importlib.util.spec_from_file_location("incident_quota", MODULE_PATH)
quota = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = quota
SPEC.loader.exec_module(quota)


class QuotaTests(unittest.TestCase):
    def profile(self, **changes):
        # Fictional fixture model/rates are never a configured runtime default.
        value = {
            "model": "fixture-model",
            "effort": "medium",
            "service_tier": "default",
            "input_rate": 2_000_000,
            "output_rate": 10_000_000,
            "monthly_microdollars": 20_000_000,
            "monthly_runs": 20,
            "promotion_seconds": 3600,
            "recovery_seconds": 600,
            "rule_uids": {
                "development": "fixture-development",
                "production": "fixture-production",
            },
            "requests_per_role": 4,
            "input_per_request": 100_000,
            "output_per_request": 10_000,
            "input_per_role": 200_000,
            "output_per_role": 20_000,
            "approval": "fixture/approval",
            "approved_month": dt.datetime.now(dt.UTC).strftime("%Y-%m"),
            "rates_source": "https://developers.openai.com/api/docs/pricing",
            "rates_reviewed_at": (
                dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": (dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }
        return quota.Profile.load(json.dumps(value | changes))

    def test_unset_or_partial_profile_fails_closed(self):
        for raw in ("", "null", "{}", '{"model":"fixture"}', '{"model":NaN}'):
            with self.subTest(raw=raw), self.assertRaises(quota.Denied):
                quota.Profile.load(raw)

    def test_both_roles_are_reserved_using_conservative_rates(self):
        profile = self.profile()
        self.assertEqual(profile.reservation, 1_200_000)
        entry = quota.reserve(profile, [], "2026-10", "123", 1)
        self.assertEqual(entry["microdollars"], 1_200_000)
        self.assertEqual(entry["profile"], profile.digest)

    def test_exhausted_month_denies_and_unknown_usage_never_refunds(self):
        profile = self.profile(monthly_microdollars=1_200_000)
        reserved = quota.reserve(profile, [], "2026-10", "123", 1)
        # Even a timeout before model output leaves the original reservation.
        with self.assertRaises(quota.Denied):
            quota.reserve(profile, [reserved], "2026-10", "124", 1)
        self.assertEqual(
            quota.reserve(profile, [reserved], "2026-11", "124", 1)["microdollars"],
            1_200_000,
        )

    def test_rerun_duplicate_and_malformed_ledger_deny(self):
        profile = self.profile()
        entry = quota.reserve(profile, [], "2026-10", "123", 1)
        for ledger, run, attempt in (
            ([entry], "123", 1),
            ([], "124", 2),
            ([], "124", True),
            ([entry | {"run_id": 123}], "123", 1),
            ([entry | {"month": "invalid"}], "124", 1),
            ([entry, entry], "124", 1),
            ([{}], "124", 1),
        ):
            with (
                self.subTest(ledger=ledger, attempt=attempt),
                self.assertRaises(quota.Denied),
            ):
                quota.reserve(profile, ledger, "2026-10", run, attempt)

    def test_serial_admission_prevents_over_admission(self):
        profile = self.profile(monthly_microdollars=2_400_000)
        ledger = []
        for run in ("1", "2"):
            ledger.append(quota.reserve(profile, ledger, "2026-10", run, 1))
        with self.assertRaises(quota.Denied):
            quota.reserve(profile, ledger, "2026-10", "3", 1)

    def test_monthly_run_count_denies_even_when_cost_headroom_remains(self):
        profile = self.profile(monthly_runs=1)
        entry = quota.reserve(profile, [], "2026-10", "1", 1)
        with self.assertRaises(quota.Denied):
            quota.reserve(profile, [entry], "2026-10", "2", 1)
        self.assertLess(entry["microdollars"], profile.monthly_microdollars)

    def test_per_request_and_cumulative_bounds_charge_before_forward(self):
        budget = quota.RequestBudget(self.profile())
        with self.assertRaisesRegex(quota.Denied, "per-request input quota exhausted"):
            budget.admit(100001)
        self.assertEqual(budget.admit(100000), 5000)
        self.assertEqual(budget.admit(100000), 5000)
        with self.assertRaisesRegex(quota.Denied, "cumulative input quota exhausted"):
            budget.admit(1)
        self.assertEqual(
            (budget.requests, budget.inputs, budget.outputs), (2, 200000, 10000)
        )

    def test_existing_profile_allows_four_turns_without_increasing_any_envelope(self):
        profile = self.profile(output_per_request=16000, output_per_role=32000)
        reservation = profile.reservation
        # The former full-per-request allocation exhausted this profile at turn 3.
        self.assertEqual(profile.output_per_role // profile.output_per_request, 2)
        for role in ("fixer", "reviewer"):
            with self.subTest(role=role):
                budget = quota.RequestBudget(profile)
                for count in range(1, 5):
                    self.assertEqual(budget.admit(1000), 8000)
                    self.assertEqual(budget.outputs, count * 8000)
                with self.assertRaises(quota.Denied):
                    budget.admit(0)
                self.assertEqual(budget.outputs, 32000)
        self.assertEqual(profile.reservation, reservation)
        self.assertEqual(
            (profile.monthly_microdollars, profile.monthly_runs), (20000000, 20)
        )
        expected = 2 * (200000 * profile.input_rate + 32000 * profile.output_rate)
        self.assertEqual(reservation, (expected + 999999) // 1000000)

    def test_rounding_never_adds_tokens_and_tiny_envelope_fails_closed(self):
        budget = quota.RequestBudget(self.profile(output_per_role=20003))
        self.assertEqual([budget.admit(0) for _ in range(4)], [5000] * 4)
        self.assertEqual(budget.outputs, 20000)
        with self.assertRaises(quota.Denied):
            budget.admit(0)
        budget = quota.RequestBudget(self.profile(output_per_role=3))
        with self.assertRaisesRegex(quota.Denied, "cumulative output quota exhausted"):
            budget.admit(0)
        self.assertEqual((budget.requests, budget.outputs), (0, 0))

    def test_request_count_cannot_be_bypassed_with_empty_inputs(self):
        budget = quota.RequestBudget(
            self.profile(output_per_request=1, output_per_role=4)
        )
        for _ in range(4):
            self.assertEqual(budget.admit(0), 1)
        with self.assertRaises(quota.Denied):
            budget.admit(0)

    def test_exact_output_and_request_boundaries_remain_charged_on_denial(self):
        budget = quota.RequestBudget(
            self.profile(output_per_request=1, output_per_role=4)
        )
        for _ in range(4):
            self.assertEqual(budget.admit(0), 1)
        self.assertEqual((budget.requests, budget.outputs), (4, 4))
        with self.assertRaisesRegex(quota.Denied, "request count quota exhausted"):
            budget.admit(0)
        self.assertEqual((budget.requests, budget.outputs), (4, 4))
        # Output cannot be reserved when even a single fair-share token is unavailable.
        tiny = quota.RequestBudget(self.profile(output_per_role=3))
        with self.assertRaisesRegex(quota.Denied, "cumulative output quota exhausted"):
            tiny.admit(0)
        self.assertEqual((tiny.requests, tiny.inputs, tiny.outputs), (0, 0, 0))

    def test_boolean_negative_and_unreviewed_limits_deny(self):
        for changed in (
            {"monthly_microdollars": True},
            {"input_rate": 0},
            {"requests_per_role": 65},
            {"input_per_request": 272001},
            {"service_tier": "priority"},
            {"approval": ""},
            {"input_per_role": 400001},
            {"promotion_seconds": 3601},
            {"recovery_seconds": 599},
            {"recovery_seconds": 901},
            {"promotion_seconds": 1400},
            {"rule_uids": {"development": "fixture"}},
        ):
            with self.subTest(changed=changed), self.assertRaises(quota.Denied):
                self.profile(**changed)

    def test_approved_64_calls_and_64000_output_are_actual_bounded_allocations(self):
        profile = self.profile(
            requests_per_role=64,
            output_per_request=64000,
            output_per_role=4096000,
            input_per_request=200000,
            input_per_role=2400000,
        )
        budget = quota.RequestBudget(profile)
        for _ in range(64):
            self.assertEqual(budget.admit(37500), 64000)
        self.assertEqual(
            (budget.requests, budget.inputs, budget.outputs), (64, 2400000, 4096000)
        )
        with self.assertRaisesRegex(quota.Denied, "request count quota exhausted"):
            budget.admit(0)
        for changes in ({"requests_per_role": 65}, {"output_per_request": 64001}):
            with self.subTest(changes=changes), self.assertRaises(quota.Denied):
                self.profile(**changes)

    def test_empty_or_omitted_rule_uids_is_valid(self):
        empty_profile = self.profile(rule_uids={})
        self.assertEqual(empty_profile.rule_uids, {})

    def test_stale_future_missing_or_unapproved_rate_provenance_denies(self):
        for changes in (
            {"approved_month": "2000-01"},
            {"rates_source": "https://untrusted.example/pricing"},
            {"rates_reviewed_at": "2099-01-01T00:00:00Z"},
            {"expires_at": "2000-01-01T00:00:00Z"},
            {"expires_at": ""},
            {"expires_at": "2099-01-01T00:00:00Z"},
        ):
            with self.subTest(changes=changes), self.assertRaises(quota.Denied):
                self.profile(**changes)


if __name__ == "__main__":
    unittest.main()
