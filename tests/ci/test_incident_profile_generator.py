import contextlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

DIRECTORY = Path(__file__).resolve().parents[2] / "ops/incident-response"
sys.path.insert(0, str(DIRECTORY))
SPEC = importlib.util.spec_from_file_location(
    "incident_profile_generator", DIRECTORY / "generate-profile.py"
)
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


class ProfileGeneratorTests(unittest.TestCase):
    def generate(self, *arguments):
        output, errors = io.StringIO(), io.StringIO()
        with (
            patch.object(sys, "argv", ["generate-profile.py", *arguments]),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
        ):
            generator.main()
        return json.loads(output.getvalue())

    def test_default_model_prices_and_all_envelopes_match_owner_selection(self):
        value = self.generate()
        self.assertEqual(
            (
                value["model"],
                value["effort"],
                value["input_rate"],
                value["output_rate"],
            ),
            ("gpt-5.4-mini", "medium", 750000, 4500000),
        )
        self.assertEqual(
            {
                name: value[name]
                for name in (
                    "monthly_microdollars",
                    "monthly_runs",
                    "requests_per_role",
                    "input_per_request",
                    "output_per_request",
                    "input_per_role",
                    "output_per_role",
                )
            },
            {
                "monthly_microdollars": 20000000,
                "monthly_runs": 20,
                "requests_per_role": 4,
                "input_per_request": 100000,
                "output_per_request": 16000,
                "input_per_role": 200000,
                "output_per_role": 32000,
            },
        )
        profile = generator.Profile.load(json.dumps(value))
        self.assertEqual(profile.reservation, 588000)
        self.assertEqual(value["rule_uids"], {})
        self.assertEqual(
            value["rates_source"], "https://developers.openai.com/api/docs/pricing"
        )

    def test_nondefault_model_uses_only_explicit_paired_rates(self):
        value = self.generate(
            "--model",
            "fixture-model",
            "--input-rate",
            "1000000",
            "--output-rate",
            "2000000",
        )
        self.assertEqual(
            (value["model"], value["input_rate"], value["output_rate"]),
            ("fixture-model", 1000000, 2000000),
        )
        self.assertEqual(value["monthly_microdollars"], 20000000)

    def test_default_model_can_use_explicit_reviewed_pair(self):
        value = self.generate("--input-rate", "800000", "--output-rate", "4600000")
        self.assertEqual((value["input_rate"], value["output_rate"]), (800000, 4600000))

    def test_model_without_rates_and_partial_or_invalid_rates_emit_no_profile(self):
        for arguments in (
            ("--model", "fixture-model"),
            ("--input-rate", "1"),
            ("--output-rate", "2"),
            ("--input-rate", "0", "--output-rate", "2"),
            ("--input-rate", "-1", "--output-rate", "2"),
        ):
            output, errors = io.StringIO(), io.StringIO()
            with (
                self.subTest(arguments=arguments),
                patch.object(sys, "argv", ["generate-profile.py", *arguments]),
                contextlib.redirect_stdout(output),
                contextlib.redirect_stderr(errors),
                self.assertRaises(SystemExit) as error,
            ):
                generator.main()
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(output.getvalue(), "")
            self.assertIn("error:", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
