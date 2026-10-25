"""Exercise Terraform's real update/destroy scheduling using only built-in resources."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

FIXTURE = Path(__file__).parent / "fixtures/certificate-detach-ordering"


@unittest.skipUnless(shutil.which("terraform"), "Terraform executable is required")
class CertificateDetachOrderingTests(unittest.TestCase):
    def test_detach_before_destroy_requires_retaining_the_existing_certificate(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            shutil.copytree(FIXTURE, directory, dirs_exist_ok=True)
            trace = directory / "trace.log"
            environment = {**os.environ, "TF_LOG_CORE": "TRACE", "TF_LOG_PATH": str(trace)}
            for arguments in (("init", "-backend=false", "-input=false"), ("test", "-no-color")):
                result = subprocess.run(["terraform", *arguments], cwd=directory, env=environment, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            log = trace.read_text(encoding="utf-8")

            def applying(run):
                return log.split("TestFileRunner: starting apply for " + run, 1)[1].split("TestFileRunner: completed apply for " + run, 1)[0]

            direct = applying("unsafe_direct_removal")
            # Negative control reproduces the production failure's Terraform
            # behavior: the referenced certificate is destroyed before service
            # update. Attribute references alone do not establish safe teardown.
            certificate = direct.index('vertex "terraform_data.certificate (destroy)": starting visit')
            service = direct.index('vertex "terraform_data.service": starting visit (*terraform.NodeApplyableResourceInstance)')
            self.assertLess(certificate, service)
            detach = applying("retain_and_detach")
            self.assertIn("Starting apply for terraform_data.service", detach)
            self.assertNotIn('vertex "terraform_data.certificate (destroy)": starting visit', detach)
            cleanup = applying("delete_unused_certificate")
            self.assertIn('vertex "terraform_data.certificate (destroy)": starting visit', cleanup)
            self.assertNotIn("Starting apply for terraform_data.service", cleanup)


if __name__ == "__main__":
    unittest.main()
