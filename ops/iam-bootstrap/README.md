# Bootstrap Actions identity setup

Issue [#191](https://github.com/alanlima/pawlocal/issues/191) authorizes one external account prerequisite: `pawlocal-terraform-bootstrap-actions`. Its owner is `alanlima`; the lifecycle tag records this exception. Run this tooling from the owner's workstation using an independently authorized IAM/assumed-role CLI identity and authenticated `gh`. Never use root credentials or run this setup inside Actions. It does not apply Terraform or change application infrastructure.

Python 3.11+, AWS CLI v2, and GitHub CLI are required. Keep the operator session, terminal history and diagnostics private. The script captures subprocess output and disables CLI debug environment flags; it never writes credentials to disk, arguments, environment variables, receipts or logs. New credentials pass from the AWS response in memory to `gh secret set` through standard input. GitHub only exposes secret-name metadata for read-back, so a successful protected workflow is the credential verification.

## Configuration and review

Copy `config.example.json` to an operator-local file outside the repository; replace the three values with the existing reviewed account, region and state bucket. These identifiers are not secrets, but should not appear in public reports. The transfer bucket is fixed from the actual bootstrap naming rule: `pawlocal-terraform-plans-<account>`. The state key is fixed to `pawlocal/iam-bootstrap/terraform.tfstate` and cannot be overridden.

```powershell
python ops/iam-bootstrap/policy.py --config C:\private\bootstrap-config.json --output-dir C:\private\bootstrap-policy-review
python ops/iam-bootstrap/setup-bootstrap-identity.py --config C:\private\bootstrap-config.json inspect
```

`inspect` is the default and performs read-only checks. Before **every** operation, the CLI checks the AWS account and both existing GitHub Environments. It never creates or weakens Environment protection. `iam-bootstrap-plan` must allow only the `main` branch, with no reviewers. `iam-bootstrap-apply` must allow only `main`, require `alanlima` (immutable ID `4245961`), disable administrator bypass and allow owner self-review while the owner is the sole reviewer. Repository ID `1423024931` is checked too.

Review all three generated documents before installing: `permissions-iam.json`, `permissions-storage.json` and `boundary.json`. Exact grants exceed IAM's [6,144-character managed-policy limit](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_iam-quotas.html), so they are split into two customer-managed policies. The independently owner-controlled boundary compresses IAM Get/List and S3 Get reads with wildcards and coalesces S3 ceiling statements on the same exact resource inventory. Its service-linked-role ceiling shares the IAM role list; the exact identity grant still permits only its GetRole and constrained creation. Effective identity-based permissions remain the intersection with explicit grants; allow mutation actions are always enumerated. Each document is size-checked. Generated account-specific policies stay outside Git.

Same-account resource policies granting the user ARN directly can bypass an implicit boundary deny. The boundary therefore explicitly denies all `sts:AssumeRole*` and `iam:PassRole`, all S3 actions outside the exact approved buckets/state/lock/bootstrap-plan objects, and every `s3:Delete*` action except on the exact lock. This also blocks direct-resource-policy bucket deletion. An edited bucket policy cannot directly grant application-plan reads, and an edited role trust cannot directly let this user assume it. This is not a complete safeguard against malicious IAM policy authorship: the identity necessarily edits owned role trust/inline policies and could delegate to another principal/repository outside its boundary. Protected workflow code and independent review of actual trust/policy plan content remain indispensable.

The inventory contains exactly 20 role names, six bootstrap-managed boundary policies, the one GitHub OIDC provider, the DSQL service-linked role, 12 possible bootstrap-owned non-secret SSM parameters, the existing transfer bucket and the bootstrap state/lock objects. Optional runtime roles/parameters are included so an approved Foundation handoff can create them. No wildcard role/policy/parameter names, application state or application plan prefixes, application-owned parameter values, `PassRole`, `AssumeRole`, user/key administration, external boundary administration, or AWS application-service mutations are granted. Role trust/inline-policy editing is necessarily privileged within this exact graph; independently review policy content in each protected Terraform plan.

The pinned AWS provider refreshes parameter metadata with `DescribeParameters`, which [does not support resource scoping](https://docs.aws.amazon.com/service-authorization/latest/reference/list_awssystemsmanager.html). One isolated `Resource: "*"` Allow statement permits only that action and only `ap-southeast-2`. The [v6.69.1 provider supplies `Name Equals`](https://github.com/hashicorp/terraform-provider-aws/blob/v6.69.1/internal/service/ssm/parameter.go), but IAM cannot enforce the filter; this exposes account-region parameter metadata, never arbitrary parameter values. `sts:GetCallerIdentity` is the only other wildcard-resource Allow statement. No IAM List action is granted on wildcard resources: role/policy/provider list/tag reads use exact supported resource types. If provider behavior changes, derive and review the policy again.

Transfer-bucket permissions refresh/configure the existing bucket's tags, encryption, public-access block, ownership, versioning, TLS policy and lifecycle. They do not create/delete a bucket or read application plans. Native backend locking permits delete only on the exact `.tflock`; state delete is absent. DSQL service-linked role creation is constrained by `iam:AWSServiceName=dsql.amazonaws.com`; deletion and its account-wide status polling are omitted. Bootstrap retirement/replacement outside these ceilings needs a new reviewed policy change. No KMS grant is assumed: stop and derive an exact grant if the existing backend uses customer-managed KMS encryption.

The existing transfer bucket has one additional metadata exception: exact-bucket `s3:ListBucket` is required by the pinned provider's [HeadBucket refresh](https://github.com/hashicorp/terraform-provider-aws/blob/v6.69.1/internal/service/s3/bucket.go). HeadBucket has no prefix request field, and IAM cannot grant it separately from ListBucket. This therefore permits listing application-plan **key names and object metadata** in that shared bucket. Object contents remain restricted to `plans/iam-bootstrap/*`; the state bucket keeps its exact state/lock prefix condition. Do not describe this identity as having zero visibility of application-plan names.

## Explicit owner operations

The single user already provisioned for #191 is reused. `create-user` returns safely if that exact tagged user already exists; an unexpected path, owner tag, group, inline policy, console login, managed policy or boundary fails closed. It never adopts another user. Initial creation and policy installation are separate explicit operations:

```powershell
python ops/iam-bootstrap/setup-bootstrap-identity.py --config C:\private\bootstrap-config.json create-user
python ops/iam-bootstrap/setup-bootstrap-identity.py --config C:\private\bootstrap-config.json install-policies --reviewed-dir C:\private\bootstrap-policy-review
```

Installation compares the reviewed files with the deterministic generator, creates/compares only its three named policies, installs the boundary **before** attaching grants, and never changes Terraform state. Existing policies must have the exact ownership tags. A different existing version requires a fresh review and the explicit `--replace-policy-version` option. Old versions are preserved; if the five-version quota is reached, an owner must review version retirement separately. The workflow user has no permission to modify these external policies or its own boundary.

Only for initial setup when **no key exists**:

```powershell
python ops/iam-bootstrap/setup-bootstrap-identity.py --config C:\private\bootstrap-config.json issue-key
```

This issues one key and uploads `PAWLOCAL_BOOTSTRAP_AWS_ACCESS_KEY_ID` and `PAWLOCAL_BOOTSTRAP_AWS_SECRET_ACCESS_KEY` to both bootstrap Environments. It refuses to issue another key when a prior key exists, including after a successful retry. There is no secret export or console login. No GitHub handoff credential is stored for the bootstrap workflow.

## Publish configuration-reader roles explicitly

The owner setup tool publishes actual bootstrap reader-role outputs to the existing release and apply Environments. The Actions workflow plans/applies IAM only; existing application configuration reconciliation continues to use its reader-role variable. Publication is a separate explicit operation after initial setup or a successful approved IAM apply that changes reader outputs. It never happens during `inspect`, user creation, policy installation or key issuance.

Use the workstation's existing authenticated `gh` session with permission to read and update repository Environment variables. No token is copied from a repository secret, added to a new stored secret, or provided as a script input. GitHub's Environment-variable API needs **Environments: write** for a fine-grained credential; ordinary `gh auth login` authorization must already permit these repository operations. A bootstrap AWS credential is not needed for this owner-operated command: it uses the same independent authorized CLI identity as setup.

```powershell
python ops/iam-bootstrap/setup-bootstrap-identity.py --config C:\private\bootstrap-config.json publish-reader-roles
```

The command reads **only** the fixed existing `pawlocal/iam-bootstrap/terraform.tfstate` S3 object. `aws s3 cp ... -` captures JSON directly into process memory without a state file, Terraform initialization or Terraform apply. It verifies state/account identity, reads the two actual `configuration_reader_role_arns` values, rejects missing/sensitive/wrong-account/wrong-environment outputs, and confirms both roles exist through `iam:GetRole`. Expected names validate the outputs; publication values are never constructed from names.

Before any write it verifies all four target Environments already exist and reads their current variables. The only publication mapping is:

| Actual bootstrap output | Existing GitHub Environments | Variable |
|---|---|---|
| `configuration_reader_role_arns.development` | `development`, `development-apply` | `PAWLOCAL_CONFIG_READER_ROLE_ARN` |
| `configuration_reader_role_arns.production` | `production`, `production-apply` | `PAWLOCAL_CONFIG_READER_ROLE_ARN` |

It compares first, creates missing variables or updates changed variables, and reads each value back. The GitHub wrapper rejects writes to other targets or variable names and never creates Environments or edits their protection. Output contains target names and `created`/`updated`/`unchanged` statuses only; role identifiers, raw state and raw API failures stay private. Run this owner operation while configuration writers are idle. GitHub variable writes are not transactional: a partial failure leaves previously verified targets updated, reports publication incomplete, and an explicit retry converges without rewriting unchanged targets. This does not invoke application reconciliation or deployment, and it does not bypass the required owner approval before the Actions IAM apply job.

## Rotation, failure and retirement

Record creation date, operator, rotation deadline (at most 90 days), last-use audit and verified workflow run externally without credential values. Audit with IAM `get-access-key-last-used` and CloudTrail; investigate unusual use outside the bootstrap workflow.

```powershell
python ops/iam-bootstrap/setup-bootstrap-identity.py --config C:\private\bootstrap-config.json rotate-key
# Inspect a fresh bootstrap run summary and verify it is a successful genuine no-op.
python ops/iam-bootstrap/setup-bootstrap-identity.py --config C:\private\bootstrap-config.json retire-old-key --verified-noop-run 123456789
```

Rotation requires exactly one active key, issues a second, uploads it to both Environments and leaves the old key active. The retirement command requires exactly two keys and a successful `main` bootstrap workflow run started after the new key's creation; the owner must confirm the summary says genuine no-op. It deactivates/deletes only the older key. GitHub secret uploads are not transactional. If upload fails or AWS creation has an ambiguous timeout, the script discovers and revokes only newly issued keys. Existing keys remain untouched, but partially uploaded Environments may refer to the revoked key. Inspect both targets, then explicitly repeat the appropriate issue/rotation operation. If cleanup itself fails, revoke the new key immediately through the external owner identity. Re-running read-only `inspect` never creates keys.

On suspected exposure, revoke immediately using the independent owner identity; inspect CloudTrail, rotate, and verify a fresh plan. On retirement, first disable the workflow and remove both Environment credential secrets, then owner-revoke all keys, detach both grants, remove the boundary and delete only this dedicated user. Remove its three external managed policies only after confirming no other attachments. Account-user retirement and bootstrap infrastructure retirement are separate reviewed operations; this script never destroys Terraform resources or edits state.
