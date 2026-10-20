# Current-stack Terraform Actions

This temporary workflow operates the existing combined Terraform root at `infra/terraform/` and its current state key, `pawlocal/terraform.tfstate`. It has no development-to-production promotion path. Use it only from `main`. It shares the `pawlocal-lightsail-deploy` GitHub Actions concurrency group with the full-stack development release, production promotion, and development rollback jobs, so none can invalidate a saved plan during an approval wait.

## GitHub Environment configuration

Create/configure these two GitHub Environments and restrict both to the `main` branch:

- `infrastructure-plan`: no required reviewer. It runs Terraform plans only and stores the AWS credentials needed to read the current state and inspect resources.
- `infrastructure-apply`: require the repository owner as a reviewer. It gates every Terraform apply, including the teardown preparation apply and the final destroy.

Set the following Environment variables in **both** environments:

- `AWS_REGION` — `ap-southeast-2` for the current stack.
- `PAWLOCAL_AWS_ACCOUNT_ID` — expected 12-digit AWS account ID; the workflow rejects a plan for another account.
- `PAWLOCAL_TF_STATE_BUCKET` — existing Terraform state bucket.
- `PAWLOCAL_DOMAIN_NAME` — current Route 53 zone name.
- `PAWLOCAL_CERTIFICATE_ARN` — current CloudFront certificate ARN.
- `PAWLOCAL_DEPLOY_SSH_PUBLIC_KEYS_JSON` — development/production public key map matching the current state.
- `PAWLOCAL_BASELINE_SSH_CIDR_BLOCKS_JSON` — development/production CIDR map matching the current state.
- `PAWLOCAL_BACKEND_IMAGE_DIGESTS_JSON` — development/production immutable image digest map matching the current state.

Set these Environment secrets in **both** environments, using the same values:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

Use an AWS principal authorized to read and update the existing Terraform state and to manage only the current PawLocal infrastructure. The credential values are supplied to Terraform through the AWS provider environment; they are not Terraform variables and are not placed in plans or artifacts. Do not print or copy them into workflow logs or repository files.

## Dispatch and approval sequence

1. Open **Actions → Terraform current stack operations → Run workflow** and select `main`.
2. For `apply`, choose `apply` and enter `APPLY PAWLOCAL`. Review the sanitized plan summary, then approve the `infrastructure-apply` job to apply the exact one-day artifact plan.
3. For full teardown, choose `destroy` and enter `DESTROY PAWLOCAL`. Review and approve the teardown-preparation plan. This step only persists Terraform's default-off `force_destroy_on_teardown` setting; its guard permits changes only to the known frontend buckets and DSQL clusters and rejects creates, deletes, replacements, or other updates.
4. After preparation succeeds, review the fresh destroy summary and approve the second `infrastructure-apply` job. The exact saved destroy plan empties app-owned frontend buckets and removes the current root's resources, including deletion-protected Aurora DSQL clusters.

The repository is public, so workflow artifacts are downloadable by anyone with repository read access. Before upload, the workflow encrypts each binary plan with AES-256-CBC and PBKDF2, using `AWS_SECRET_ACCESS_KEY` as the passphrase. That secret stays in the Environment secret store and is not written into the plan metadata or artifact. The apply job decrypts the plan in its ephemeral runner and verifies its SHA-256 against the separate workflow job output before applying it. Artifacts expire after one day.

Before a plan can be uploaded for approval, a shared gate requires Terraform to mark it applyable and complete, rejects errors or deferred changes, and verifies the target AWS account. Apply plans are checked against the caller identity in their planned values; full destroy plans are checked against the caller identity in the plan's prior state because their planned values represent an empty state. The destroy plan must contain only deletions from resources declared in the current root or its `fullstack` module. Its review summary includes selected non-secret AWS identifiers (such as resource IDs, ARNs, bucket names, and cluster identifiers) so the owner can confirm the physical targets before approving. Unknown Terraform addresses or deletions without a reviewable identifier stop the workflow.

Plans are bound to the run, attempt, commit, operation, account, and state key, and applied with Terraform backend locking. The workflow invokes no AWS CLI and makes no infrastructure change outside Terraform.

The destroy operation permanently deletes the current app infrastructure and objects in its app-owned frontend buckets. Run it only when the reviewed destroy plan shows the intended current stack.
