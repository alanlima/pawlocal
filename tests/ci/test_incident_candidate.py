import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parents[2] / "ops/incident-response"
sys.path.insert(0, str(DIRECTORY))
SPEC = importlib.util.spec_from_file_location(
    "incident_candidate", DIRECTORY / "candidate.py"
)
candidate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(candidate)


class CandidateTests(unittest.TestCase):
    def metadata(self):
        return {"base_sha": "a" * 40, "alert": {"incident_key": "b" * 64}}

    def test_narrow_file_bytes_bind_base_and_incident(self):
        with tempfile.TemporaryDirectory() as directory:
            base, edited = Path(directory) / "base", Path(directory) / "edited"
            base.mkdir()
            edited.mkdir()
            name = "backend/tests/test_incident_regression.py"
            candidate.materialize(
                {name: b"def test_regression(): assert True\n"}, edited
            )
            raw = candidate.export(base, edited, self.metadata())
            self.assertEqual(
                candidate.load(raw, self.metadata())[name],
                b"def test_regression(): assert True\n",
            )
            with self.assertRaises(candidate.Denied):
                candidate.load(raw, self.metadata() | {"base_sha": "c" * 40})

    def test_unapproved_auth_infra_workflow_dependency_and_missing_regression_deny(
        self,
    ):
        for name in (
            ".github/workflows/test.yml",
            "infra/main.tf",
            "backend/pawlocal/api/auth.py",
            "frontend/package.json",
            "backend/migrations/dsql/0001_initial/001_places.sql",
            "backend/pawlocal/dsql_post_apply_setup.py",
            "frontend/.env.production",
            "backend/data/places.json",
            "backend/pawlocal/application/places.py",
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                base, edited = Path(directory) / "base", Path(directory) / "edited"
                base.mkdir()
                edited.mkdir()
                target = edited / name
                target.parent.mkdir(parents=True)
                target.write_text("fixture")
                with self.assertRaises(candidate.Denied):
                    candidate.export(base, edited, self.metadata())

    def test_transport_cannot_skip_fixed_frontend_regression(self):
        value = {
            "schema": 1,
            "base_sha": "a" * 40,
            "incident_key": "b" * 64,
            "files": {"frontend/src/services/HttpPlaceService.ts": "Zml4dHVyZQ=="},
        }
        with self.assertRaises(candidate.Denied):
            candidate.load(json.dumps(value).encode(), self.metadata())

    @unittest.skipIf(
        sys.platform == "win32",
        "Symlink creation needs Windows privilege; exercised on Ubuntu",
    )
    def test_symlink_target_never_reads_private_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "secret"
            outside.write_text("SENTINEL")
            target = root / "candidate" / "backend/tests/test_incident_regression.py"
            target.parent.mkdir(parents=True)
            target.symlink_to(outside)
            with self.assertRaises(candidate.Denied):
                candidate.files(root / "candidate")
            with self.assertRaises(candidate.Denied):
                candidate.safe_bytes(
                    root / "candidate", "backend/tests/test_incident_regression.py", 100
                )
            target.unlink()
            target.parent.rmdir()
            target.parent.symlink_to(outside.parent, target_is_directory=True)
            with self.assertRaises(candidate.Denied):
                candidate.safe_bytes(root / "candidate", "backend/tests/secret", 100)


    def test_arbitrary_backend_and_frontend_files_allowed_with_regression(self):
        with tempfile.TemporaryDirectory() as directory:
            base, edited = Path(directory) / "base", Path(directory) / "edited"
            base.mkdir()
            edited.mkdir()
            files_to_test = {
                "backend/pawlocal/api/places.py": b"# api places\n",
                "backend/pawlocal/main.py": b"# main\n",
                "backend/tests/test_incident_regression.py": b"def test_reg(): pass\n",
            }
            candidate.materialize(files_to_test, edited)
            raw = candidate.export(base, edited, self.metadata())
            loaded = candidate.load(raw, self.metadata())
            self.assertEqual(loaded["backend/pawlocal/api/places.py"], b"# api places\n")
            self.assertEqual(loaded["backend/pawlocal/main.py"], b"# main\n")

        with tempfile.TemporaryDirectory() as directory:
            base, edited = Path(directory) / "base", Path(directory) / "edited"
            base.mkdir()
            edited.mkdir()
            frontend_files = {
                "frontend/src/App.tsx": b"// app\n",
                "frontend/src/components/Header.tsx": b"// header\n",
                "frontend/src/incident-regression.test.tsx": b"test('reg', () => {});\n",
            }
            candidate.materialize(frontend_files, edited)
            raw = candidate.export(base, edited, self.metadata())
            loaded = candidate.load(raw, self.metadata())
            self.assertEqual(loaded["frontend/src/App.tsx"], b"// app\n")
            self.assertEqual(loaded["frontend/src/components/Header.tsx"], b"// header\n")

    def test_cross_layer_requires_both_regressions(self):
        with tempfile.TemporaryDirectory() as directory:
            base, edited = Path(directory) / "base", Path(directory) / "edited"
            base.mkdir()
            edited.mkdir()
            mixed = {
                "backend/pawlocal/api/places.py": b"# api places\n",
                "frontend/src/App.tsx": b"// app\n",
                "backend/tests/test_incident_regression.py": b"def test_reg(): pass\n",
            }
            candidate.materialize(mixed, edited)
            with self.assertRaises(candidate.Denied):
                candidate.export(base, edited, self.metadata())


if __name__ == "__main__":
    unittest.main()
