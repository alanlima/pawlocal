# Production Terraform lifecycle

This runbook defines the only supported steady-state production application
lifecycle: foundation, runtime-trust handoff, convergence, release, destroy,
and clean redeploy. It does not provide a recovery or break-glass path and does
not authorize disposition of resources outside the production application
state.

Every apply and destroy remains subject to explicit owner approval, the saved
plan shown by GitHub Actions, and independent review. Do not use this runbook
while the production state is locked, incomplete, or inconsistent with the
read-only cloud inventory.

## Protected configuration

The normal plan and apply environments keep the configuration documented in
`terraform-greenfield-operations.md`. Configure two additional protected
environments:

- `production-destroy-prepare` approves the exact teardown-control plan.
- `production-destroy` approves the exact full-destroy plan.

Both destroy environments expose only the matching region, account, remote
state bucket, private plan-transfer bucket, and exact apply-role variables
needed to initialize and apply an already reviewed plan. They require human
reviewers. They do not store application outputs or credentials.

The normal Terraform environment workflow and the destroy workflow share the
`pawlocal-terraform-production` concurrency domain. A second Terraform run
waits; it never cancels a production mutation.

Before enabling destroy, apply the independently reviewed bootstrap plan that
adds the dedicated teardown policy to the exact set of policies the production
Terraform apply identity may attach to itself. The permissions boundary allows
matching frontend-object deletion, but the identity receives that effective
permission only through the temporary Terraform policy and attachment created
by the reviewed teardown-preparation plan.

## Normal create and release sequence

1. Dispatch `terraform-environment.yml` from a reviewed `main` commit with:
   `environment=production`, `phase=foundation`, empty image and release
   commit, and `release_only=false`.
2. Review and approve the exact foundation plan. Foundation always forces the
   runtime role, backend image, and generated CloudFront handoff inputs empty.
   The default-off teardown variable remains false.
3. Manually copy the reviewed foundation outputs into the matching protected
   environment variables. This temporary operator step is tracked by deferred
   Issue #155; do not put the values in an issue, pull request, fixture, or
   runbook.
4. Use the separately reviewed Issue #135 bootstrap plan to bind the generated
   Lightsail principal to the matching runtime role. No application state or
   cloud resource is edited manually.
5. Manually refresh the matching protected environment variables from the
   reviewed bootstrap and application outputs.
6. Dispatch `terraform-environment.yml` with `phase=converge`, a full
   development-verified commit, its immutable backend image digest, and
   `release_only=false`. Review the plan as a full-infrastructure convergence,
   not a release-only promotion.
7. After successful convergence and a manual refresh of the reviewed generated
   environment values, use `deploy-production.yml` for subsequent
   development-verified versions. It passes `phase=release`.
8. Verify frontend HTML, API health, database-backed discovery, authenticated
   persistence, and the selected image identity. Rerun the normal environment
   plan with the same inputs and require zero managed changes.

A first clean environment therefore needs a reviewed convergence before a
later release can demonstrate a genuinely release-only replacement. Do not
label the convergence plan as a production promotion.

## Standard destroy sequence

Dispatch `terraform-environment-destroy.yml` from the reviewed `main` commit
with `environment=production`, the immutable image currently represented by
the state, and the exact confirmation phrase shown by the workflow.

The workflow performs these fail-closed stages:

1. The read-only plan identity pulls the existing production application
   state. Missing state fails. A present, already-empty state skips destructive
   jobs.
2. Terraform creates a preparation plan with the default-off teardown switch
   enabled. A repository validator permits only the frontend bucket cleanup
   flag, the DSQL deletion controls, and the bounded temporary policy and
   attachment that let Terraform delete frontend objects.
3. `production-destroy-prepare` supplies the first explicit approval. The job
   uses the existing project metadata helper to recheck commit, repository,
   run/attempt, environment, backend target fingerprint, state key, and plan
   digest before applying only that saved plan.
4. The read-only identity pulls the advanced state and creates a fresh full
   destroy plan. Validation requires delete-only actions for every managed
   address in the prior production application state and rejects root,
   bootstrap, development, unknown, missing, or extra resources.
5. `production-destroy` supplies the second explicit approval. The job repeats
   all identity checks and applies only the exact reviewed destroy plan.
6. Terraform pulls the same state again. Missing state fails; the run succeeds
   only when the state contains no resources or outputs.

After the empty-state proof, remove or clear only the generated production
target variables through the normal protected GitHub Environment settings.
This manual configuration step is tracked by deferred Issue #155 and is not an
AWS or Terraform-state mutation. Keep static operator inputs and unrelated
variables intact.

Opaque plans and their metadata use private transfer storage. Existing project
metadata binds each exact plan to its source commit, repository, run and
attempt, environment, state key, backend target fingerprint, and plan digest.
Terraform rejects a saved plan when its state has changed before apply.

## Accepted MVP gap

Issue #148 is deferred and the normal environment workflow still invokes its
plan summarizer with `--skip-enforcement`. The foundation and release plans
therefore rely on the protected exact-plan review rather than an automated
ownership allowlist. This runbook and Issue #168 must not be treated as proof
that release-only validation rejects every non-deployment change. That
acceptance item remains open until the owner resumes #148 or explicitly changes
it. The dedicated preparation/destroy checks in this workflow do not replace
the deferred normal-plan guard.

## Failure behavior

- Do not unlock state, import resources, edit state, or delete resources
  manually. Diagnose a lock or ownership mismatch read-only and return it to a
  separately approved scope.
- A failed preparation apply requires a fresh run from the current state after
  the reviewed code or external prerequisite is fixed.
- A failed destroy requires a fresh run after the underlying provider failure
  is reviewed.
- If the destroy succeeded but the runner stopped before the empty-state
  proof, the next standard run proves the existing state is empty and skips
  mutation. Missing state is never treated as empty.
- If plan metadata or digest validation fails, or Terraform reports that the
  saved plan is stale, generate a new plan; never reuse the old artifact.

## Clean redeploy and cost effects

After the empty-state proof and manual removal of stale generated environment
values, repeat the normal create and release sequence from the foundation
phase. Refresh the protected environment values from the new reviewed outputs
before convergence or release.

Destroy removes all resources owned by the production application state,
including the container service and database that carry ongoing workload cost.
It does not remove the standalone IAM bootstrap state, development resources,
the remote-state/plan-transfer storage, or external domain and certificate
inputs. A later foundation recreates billable production resources and needs a
new explicit cost/apply approval.

Passing CI proves workflow and policy behavior only. It is not evidence that a
destroy, redeploy, public endpoint check, authenticated persistence check, or
zero-change production plan ran.
