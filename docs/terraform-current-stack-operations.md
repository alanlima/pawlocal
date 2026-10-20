# Historical current-stack Terraform Actions (non-actionable)

> **Do not dispatch this workflow or follow the commands below for Issue #135.** This file preserves the former combined-state procedure as audit evidence only. Run 39480644777 applied part of its destroy plan and then failed; [PR #134](https://github.com/alanlima/pawlocal/pull/134) remains open, and the resulting AWS/state inventory has not yet been independently verified. Issue #135 requires clean bootstrap, development, and production states and will provide new operator instructions only after implementation.

Historically, this temporary workflow operated the former combined Terraform root at `infra/terraform/` and its state key, `pawlocal/terraform.tfstate`. The details below describe that retired design; they do not establish current live resources or authorize another apply or destroy.

## Historical GitHub Environment configuration

Create/configure these two GitHub Environments and restrict both to the `main` branch:

- `infrastructure-plan`: no required reviewer. It runs Terraform plans and stores the short-lived AWS credentials needed to read the current state and inspect resources.
- `infrastructure-apply`: require the repository owner as a reviewer. It gates every Terraform apply, including the teardown preparation apply and the final destroy.

Set these non-secret Environment variables in **both** environments:

- `AWS_REGION` — `ap-southeast-2` for the current stack.
- `PAWLOCAL_AWS_ACCOUNT_ID` — expected 12-digit AWS account ID; the workflow rejects a plan for another account.
- `PAWLOCAL_TF_STATE_BUCKET` — existing Terraform state bucket.
- `PAWLOCAL_DOMAIN_NAME` — current Route 53 zone name.
- `PAWLOCAL_CERTIFICATE_ARN` — current CloudFront certificate ARN.

Also configure these role and plan-transfer variables, only after the reviewed IAM bootstrap has been applied:

- `infrastructure-plan`: `PAWLOCAL_TERRAFORM_PLAN_ROLE_ARN` and `PAWLOCAL_TERRAFORM_PLAN_BUCKET`.
- `infrastructure-apply`: `PAWLOCAL_TERRAFORM_APPLY_ROLE_ARN` and `PAWLOCAL_TERRAFORM_PLAN_BUCKET`.

The plan-role ARN is used by `plan` and `destroy-plan`. The apply-role ARN is used by `apply`, `prepare-destroy`, and `destroy`. The private transfer bucket is used in both Environments for the exact plan file and metadata. Do not put role ARNs or bucket names in Secrets; they are non-secret Environment variables. Do not configure static AWS access-key secrets.

For every plan or apply operation, the Environment variables required are `AWS_REGION`, `PAWLOCAL_AWS_ACCOUNT_ID`, `PAWLOCAL_TF_STATE_BUCKET`, `PAWLOCAL_DOMAIN_NAME`, `PAWLOCAL_CERTIFICATE_ARN`, and `PAWLOCAL_TERRAFORM_PLAN_BUCKET`. Plan jobs (`plan` and `destroy-plan`) also require `PAWLOCAL_TERRAFORM_PLAN_ROLE_ARN` in `infrastructure-plan`. Apply jobs (`apply`, `prepare-destroy`, and `destroy`) require `PAWLOCAL_TERRAFORM_APPLY_ROLE_ARN` in `infrastructure-apply`. These are Environment variables, not repository-level variables. Each job validates that its role ARN belongs to the configured account and that the plan bucket value is present before attempting OIDC authentication. Missing values therefore fail before Terraform runs; configure the values only after the bootstrap outputs have been reviewed and applied.

Do not configure SSH public-key/CIDR maps or a manually supplied backend image digest map. After Terraform initializes, each AWS-enabled job reads `terraform output -json environment_targets`, extracts development and production `api_backend_image` values, validates both as immutable PawLocal GHCR digests, and exports `TF_VAR_backend_image_digests`. If the output is missing or invalid, the workflow stops before planning or applying.

Each AWS-enabled job requests `id-token: write` and uses `aws-actions/configure-aws-credentials@v5` to assume its Environment role through GitHub OIDC. The action's `allowed-account-ids` input checks the live account against `PAWLOCAL_AWS_ACCOUNT_ID`; a following step also compares the action's `aws-account-id` output before Terraform runs. Credentials are short-lived and remain in the runner environment. Do not print them or copy them into files or artifacts.

## Historical dispatch and approval sequence

1. Open **Actions → Terraform current stack operations → Run workflow** and select `main`.
2. For `apply`, choose `apply` and enter `APPLY PAWLOCAL`. Review the sanitized plan summary, then approve the `infrastructure-apply` job to apply the exact saved plan from the private S3 transfer bucket.
3. For full teardown, choose `destroy` and enter `DESTROY PAWLOCAL`. Review and approve the teardown-preparation plan. This step only persists Terraform's default-off `force_destroy_on_teardown` setting; its guard permits changes only to the known frontend buckets and DSQL clusters and rejects creates, deletes, replacements, or other updates.
4. After preparation succeeds, review the fresh destroy summary and approve the second `infrastructure-apply` job. The exact saved destroy plan empties app-owned frontend buckets and removes the current root's resources, including deletion-protected Aurora DSQL clusters.

The exact binary plan and metadata are transferred through the private bootstrap-owned S3 bucket with server-side AES-256 encryption. Plan roles can upload only under `plans/legacy/`; the apply role can read only that prefix. The bucket lifecycle expires current and noncurrent objects after one day. Each apply job verifies the plan metadata and SHA-256 against the producing job's output before applying it.

The destroy-preparation job also creates a read-only `terraform plan -refresh-only` snapshot and compares it with the normal plan. Its summary reports only resource labels, action types, attribute paths, aggregate policy fingerprints and allowlisted DSQL encryption fields; it never fingerprints raw policy or KMS identifier values. For policy and encryption attributes, it reads Terraform's `after_unknown` and `after_sensitive` metadata and labels values as absent, unknown/computed, sensitive, or present; it withholds summaries for values Terraform marks unknown or sensitive. The strict guard still permits only the approved `force_destroy` settings; any other planned mutation blocks the job before plan upload or apply. The publisher-role state handoff is staged separately from the later OIDC-provider transfer.

Before any Terraform command, the assumed-role account is checked by `configure-aws-credentials` and by the workflow's account guard. Before a plan can be uploaded for approval, the Terraform plan gate requires Terraform to mark it applyable and complete, rejects errors or deferred changes, and verifies the target AWS account. Apply plans are checked against the caller identity in their planned values; full destroy plans are checked against the caller identity in the plan's prior state because their planned values represent an empty state. The destroy plan must contain only deletions from resources declared in the current root or its `fullstack` module. Its review summary includes selected non-secret AWS identifiers (such as resource IDs, ARNs, bucket names, and cluster identifiers) so the owner can confirm the physical targets before approving. Unknown Terraform addresses or deletions without a reviewable identifier stop the workflow.

Plans are bound to the run, attempt, commit, operation, account, and state key, and applied with Terraform backend locking. The workflow invokes no AWS CLI and makes no infrastructure change outside Terraform.

The historical destroy operation was destructive and its last run completed only partially. Do not dispatch it again as part of Issue #135; use read-only inspection to establish the actual remaining AWS resources and state bindings.
