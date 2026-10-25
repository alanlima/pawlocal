from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import yaml

from test_action_runtime_policy import step_action_references, validate_action_reference
from test_workflow_paths import matches

ROOT = Path('.')
WORKFLOWS = ROOT / '.github/workflows'
CATALOGUE = json.loads((ROOT / '.github/workflow-catalogue.json').read_text(encoding='utf-8'))


def load(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding='utf-8'))


def events(workflow):
    return workflow.get('on', workflow.get(True))


class WorkflowCatalogueTests(unittest.TestCase):
    def test_flat_workflows_and_tracked_legacy_exceptions(self):
        files = {p.name for p in WORKFLOWS.iterdir() if p.suffix in {'.yml', '.yaml'}}
        self.assertEqual(files, set(CATALOGUE['workflows']))
        self.assertEqual(CATALOGUE['issue'], 272)
        self.assertEqual(len(CATALOGUE['legacy_filenames']), 22)
        for path in WORKFLOWS.rglob('*'):
            self.assertFalse(path.is_dir(), 'GitHub workflows must stay flat')
            if path.suffix not in {'.yml', '.yaml'}:
                continue
            if path.name not in CATALOGUE['legacy_filenames']:
                self.assertRegex(path.name, r'^(quality|release|infrastructure|operations|automation|retired)-[a-z0-9]+(?:-[a-z0-9]+)*[.]yml$')

    def test_display_names_match_documented_registry_without_changing_jobs(self):
        reference = Path('docs/github-actions.md').read_text(encoding='utf-8')
        for name, expected in CATALOGUE['workflows'].items():
            with self.subTest(workflow=name):
                actual = load(name)['name']
                self.assertEqual(actual, expected)
                self.assertRegex(actual, r'^(Quality|Release|Infrastructure|Operations|Automation|Retired) \u00b7 [A-Z][a-z-]+ .+')
                self.assertIn(actual, reference)
        release = load('fullstack-release.yml')['jobs']
        self.assertEqual(release['backend']['name'], 'Backend checks')
        self.assertEqual(release['frontend']['name'], 'Frontend checks and HTTP-mode build')
        self.assertEqual(load('backend-ci.yml')['jobs']['backend']['name'], 'Backend checks')
        self.assertIn('frontend', load('frontend-deploy.yml')['jobs'])

    def test_quality_has_no_configuration_sync_or_credentials(self):
        suite = load('ci.yml')
        self.assertEqual(set(events(suite)), {'workflow_dispatch'})
        self.assertIsNone(events(suite)['workflow_dispatch'])
        self.assertEqual(len(suite['jobs']), 5)
        for job in suite['jobs'].values():
            callee = load(job['uses'].rsplit('/', 1)[1])
            self.assertTrue(callee['name'].startswith('Quality '))
            self.assertNotIn('secrets', job)
            self.assertNotIn('environment', job)
        ops = load('reconcile-environment.yml')
        self.assertIn('workflow_dispatch', events(ops))
        self.assertEqual(ops['jobs']['reconcile']['environment'], "${{ format('{0}-apply', inputs.environment) }}")
        self.assertFalse(ops['concurrency']['cancel-in-progress'])

    def test_automatic_component_owner_preserves_union_coverage(self):
        for component in ['frontend-deploy.yml', 'backend-ci.yml']:
            self.assertEqual(set(events(load(component))), {'workflow_call'})
        paths = ['frontend/src/App.tsx', 'backend/pawlocal/main.py', 'openapi.yaml',
                 'package.json', 'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock',
                 'pyproject.toml', 'requirements.txt', 'poetry.lock', 'uv.lock',
                 '.github/workflows/frontend-deploy.yml', '.github/workflows/backend-ci.yml',
                 '.github/workflows/deploy-production.yml', '.github/workflows/frontend-production-deploy.yml',
                 '.github/actions/setup-frontend-toolchain/action.yml']
        release = load('fullstack-release.yml')
        self.assertIsNone(events(release)['pull_request'])
        for event in ['pull_request', 'push']:
            for path in paths:
                with self.subTest(event=event, path=path):
                    self.assertTrue(matches('fullstack-release.yml', path, event))
        self.assertTrue(matches('terraform-ci.yml', '.github/actions/setup-terraform-toolchain/action.yml'))
        self.assertTrue(matches('workflow-validation.yml', '.github/workflow-catalogue.json'))
        self.assertTrue(matches('fullstack-release.yml', 'frontend/README.md', 'pull_request'))
        self.assertFalse(matches('fullstack-release.yml', 'frontend/README.md', 'push'))
        self.assertTrue(matches('workflow-validation.yml', 'docs/github-actions.md'))

    def test_literal_caller_names_follow_current_display_names(self):
        group = load('terraform-environment.yml')['concurrency']['group']
        callers = json.loads(re.search(r"fromJSON\('([^']+)'\)", group)[1])
        self.assertEqual(callers, [load('fullstack-release.yml')['name'], load('deploy-production.yml')['name'], load('release-rollback-production.yml')['name']])
        self.assertIn("format('pawlocal-terraform-{0}', inputs.environment)", group)
        self.assertFalse(load('terraform-environment.yml')['concurrency']['cancel-in-progress'])
        cleanup = load('cleanup-destroyed-configuration.yml')
        guard = next(s['run'] for s in cleanup['jobs']['cleanup']['steps'] if 'CALLER_WORKFLOW' in s.get('run', ''))
        self.assertIn("'" + load('terraform-environment-destroy.yml')['name'] + "'", guard)
        self.assertNotIn('workflow_dispatch', events(cleanup))

    def test_composite_contracts_and_actual_callers(self):
        expected = {
            'setup-frontend-toolchain': {'frontend-deploy.yml', 'fullstack-release.yml', 'deploy-production.yml', 'workflow-validation.yml'},
            'setup-terraform-toolchain': {'terraform-ci.yml', 'terraform-environment.yml', 'terraform-iam-bootstrap.yml', 'terraform-environment-destroy.yml', 'workflow-validation.yml'},
        }
        for action, callers in expected.items():
            actual = set()
            metadata = yaml.safe_load((Path('.github/actions') / action / 'action.yml').read_text(encoding='utf-8'))
            self.assertEqual(metadata['runs']['using'], 'composite')
            self.assertNotRegex(json.dumps(metadata), r'secrets[.]|aws-actions|terraform (plan|apply)|id-token|environment:')
            for file in WORKFLOWS.glob('*.yml'):
                workflow = load(file.name)
                for job in workflow['jobs'].values():
                    for step in job.get('steps', []):
                        if step.get('uses', '').endswith('/' + action):
                            actual.add(file.name)
                            if action == 'setup-terraform-toolchain':
                                self.assertIn(step['with']['terraform-version'], ['1.14.3', '${{ env.TERRAFORM_VERSION }}'])
            self.assertEqual(actual, callers)
        frontend = yaml.safe_load(Path('.github/actions/setup-frontend-toolchain/action.yml').read_text(encoding='utf-8'))
        install = frontend['runs']['steps'][1]
        self.assertEqual(install, {'name': 'Install frontend dependencies', 'shell': 'bash', 'working-directory': 'frontend', 'run': 'npm ci'})
        production = load('deploy-production.yml')['jobs']['verify-production']['steps']
        self.assertTrue(any(s.get('uses') == './.configuration-tools/.github/actions/setup-frontend-toolchain' for s in production))
        terraform = yaml.safe_load(Path('.github/actions/setup-terraform-toolchain/action.yml').read_text(encoding='utf-8'))
        self.assertIs(terraform['runs']['steps'][0]['with']['terraform_wrapper'], False)

    def test_nested_external_action_runtime_cannot_escape_policy(self):
        composite = {'runs': {'using': 'composite', 'steps': [{'uses': 'actions/setup-node@v6'}]}}
        references = list(step_action_references(composite))
        self.assertEqual(len(references), 1)
        with self.assertRaisesRegex(AssertionError, 'must use'):
            validate_action_reference(*references[0])
        composite['runs']['steps'][0]['uses'] = 'unreviewed/action@v1'
        with self.assertRaisesRegex(AssertionError, 'unreviewed'):
            validate_action_reference(*list(step_action_references(composite))[0])

    def test_retired_workflows_remain_non_deploying(self):
        for name in ['frontend-production-deploy.yml', 'rollback-development.yml', 'terraform-current-stack-operations.yml']:
            workflow = load(name)
            self.assertEqual(workflow['permissions'], {'contents': 'read'})
            self.assertEqual(set(workflow['jobs']), {'disabled'})
            for step in workflow['jobs']['disabled']['steps']:
                self.assertNotIn('uses', step)
                self.assertNotRegex(step.get('run', ''), r'aws |terraform |gh workflow')
