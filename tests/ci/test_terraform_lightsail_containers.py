from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = ROOT / "ops/validate-lightsail-container-plan.py"
SPEC = importlib.util.spec_from_file_location("container_plan_validator", VALIDATOR_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class TerraformLightsailContainerTests(unittest.TestCase):
    image = "ghcr.io/alanlima/pawlocal-api@sha256:" + "a" * 64

    @staticmethod
    def plan(address: str, actions: list[str], image: str) -> dict:
        return {"resource_changes": [{"address": address, "change": {
            "actions": actions, "after": {"container": [{"image": image}]}
        }}]}

    def test_accepts_only_selected_environment_container_deployment(self) -> None:
        address = 'module.fullstack.aws_lightsail_container_service_deployment_version.api["development"]'
        VALIDATOR.validate(self.plan(address, ["update"], self.image), "development", self.image)

    def test_accepts_selected_immutable_container_deployment_replacement(self) -> None:
        address = 'module.fullstack.aws_lightsail_container_service_deployment_version.api["development"]'
        VALIDATOR.validate(self.plan(address, ["delete", "create"], self.image), "development", self.image)

    def test_rejects_unrelated_infrastructure_changes(self) -> None:
        plan = self.plan('module.fullstack.aws_lightsail_container_service.api["development"]', ["update"], self.image)
        with self.assertRaisesRegex(ValueError, "outside the selected"):
            VALIDATOR.validate(plan, "development", self.image)

    def test_rejects_changes_to_both_environments(self) -> None:
        plan = self.plan('module.fullstack.aws_lightsail_container_service_deployment_version.api["development"]', ["update"], self.image)
        plan["resource_changes"].append(self.plan('module.fullstack.aws_lightsail_container_service_deployment_version.api["production"]', ["update"], self.image)["resource_changes"][0])
        with self.assertRaisesRegex(ValueError, "outside the selected"):
            VALIDATOR.validate(plan, "development", self.image)

    def test_rejects_wrong_image_and_destroy(self) -> None:
        address = 'module.fullstack.aws_lightsail_container_service_deployment_version.api["production"]'
        with self.assertRaisesRegex(ValueError, "image digest"):
            VALIDATOR.validate(self.plan(address, ["update"], "other"), "production", self.image)
        with self.assertRaisesRegex(ValueError, "create, update, or replacement"):
            VALIDATOR.validate(self.plan(address, ["delete"], self.image), "production", self.image)

    def test_release_workflows_do_not_use_ssh_or_manual_ingress(self) -> None:
        for filename in ("fullstack-release.yml", "deploy-production.yml", "rollback-development.yml"):
            workflow = (ROOT / ".github/workflows" / filename).read_text(encoding="utf-8")
            self.assertIn("terraform-lightsail-container-deploy.sh", workflow)
            self.assertNotIn("terraform-lightsail-ingress.sh", workflow)
            self.assertNotIn("PAWLOCAL_DEPLOY_SSH_PRIVATE_KEY", workflow)
            self.assertNotIn("PAWLOCAL_DSQL_ACCESS_KEY_ID", workflow)

    def test_container_release_records_running_image_digest(self) -> None:
        deploy = (ROOT / "ops/terraform-lightsail-container-deploy.sh").read_text(encoding="utf-8")
        adapter = (ROOT / "ops/deployment-adapters/lightsail-dsql.sh").read_text(encoding="utf-8")
        self.assertIn("get-container-services", deploy)
        self.assertIn("currentDeployment", deploy)
        self.assertIn("PAWLOCAL_RELEASE_IMAGE_DIGEST", (ROOT / "infra/terraform/fullstack/main.tf").read_text(encoding="utf-8"))
        self.assertIn("running_image_digest", adapter)

    def test_development_rollback_requires_prior_verified_release(self) -> None:
        workflow = (ROOT / ".github/workflows/rollback-development.yml").read_text(encoding="utf-8")
        self.assertIn("PAWLOCAL_DEPLOY_ADAPTER_PATH: ${{ vars.PAWLOCAL_DEPLOY_ADAPTER_PATH }}", workflow)
        self.assertIn("No successful main-branch full-stack release", workflow)
        self.assertIn("no successful verified development deployment", workflow)
        self.assertIn("terraform-lightsail-container-deploy.sh development", workflow)
        self.assertIn("validate-release-metadata.py", workflow)


if __name__ == "__main__":
    unittest.main()
