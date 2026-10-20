# Terraform role policy design

This root creates role trust, role policies, the private saved-plan transfer bucket, and the fixed application identity policies. It does not make AWS calls in this document; the role grants are proposals until independently reviewed and applied through the approved Terraform path.

## Environment plan and apply roles

Development and production have separate plan/apply roles and separate state keys. Plan roles receive read-only application discovery and can upload a saved plan only beneath `plans/development/` or `plans/production/`. Apply roles can read only the matching saved-plan prefix and state key. Their AWS service grants are limited to the actions below. Destructive recovery permissions are out of scope for this release and are not included in this root.

| Service | Allowed environment apply actions | Resource and condition boundary |
|---|---|---|
| S3 frontend bucket | `CreateBucket`, `PutBucketTagging`, ownership/public access/encryption controls, bucket policy | Bucket names must begin `pawlocal-development-` or `pawlocal-production-`; controls and policy writes require existing `project=pawlocal` and matching `environment` tags. S3 bucket tagging is scoped by that name prefix because the S3 tagging API does not provide a reliable request-tag condition for bucket tags. Object deployment permissions belong to the separate fixed frontend publisher roles. |
| Aurora DSQL | `CreateCluster`, `UpdateCluster`, `PutClusterPolicy`, `TagResource` | Create uses the DSQL cluster ARN pattern and requires `project=pawlocal`, the matching environment, and approved tag keys. Updates require matching existing project/environment tags. Cluster deletion is not granted. |
| Lightsail | `CreateContainerService`, `CreateCertificate`, dependent `TagResource`, `UpdateContainerService`, `CreateContainerServiceDeployment` | Create APIs require `Resource="*"` in the AWS authorization model; requests require project/environment tags and the approved tag-key set. The dependent tag action is limited to the exact environment service and certificate ARNs and matching request tags. Updates and deployments are limited to the exact environment service ARN and existing tags. Create-time name limits are unavailable in IAM, so these create grants can create other same-tagged Lightsail services/certificates and carry cost risk. |
| CloudFront | `CreateDistribution`, `CreateFunction`, `TagResource`, `UpdateDistribution`, `UpdateFunction`, `PublishFunction` | Create APIs require `Resource="*"`; creation is gated by project/environment request tags and the fixed approved tag-key set. Function tagging is scoped to its exact environment-specific name. Distribution tagging is scoped to this AWS account's `distribution/*` ARN family and requires `project=pawlocal`, the current apply role's environment value, and the approved tag-key set. `UpdateDistribution` is also allowed on this account's `distribution/*` ARN family when the existing resource has `project=pawlocal` and the apply role's environment value. This leaves a cross-environment configuration risk described below, which the owner explicitly accepts for the MVP. OAC permissions stay on the separate staged exact-ARN flow. |
| Cognito | `CreateUserPool`, `UpdateUserPool`, create/update pool client and domain, `TagResource` | Pool creation requires project/environment request tags. Follow-on actions require matching project/environment resource tags on a user-pool ARN. Delete operations are not granted. |
| Route 53 | `ChangeResourceRecordSets` | Exact configured hosted-zone ARN. Change actions are limited to CREATE/UPSERT, record names to the environment API/frontend hostnames and one validation-label wildcard beneath the API hostname, and record types to A/AAAA/CNAME. DELETE is not granted. |

Terraform resource replacement may require delete permissions, which are deliberately not part of these app deployment grants. The saved plan must be inspected for create/update/delete/replace actions, and an unapproved replacement must not be applied.

### CloudFront distribution tagging tradeoff accepted for MVP

Terraform AWS provider 6.69.1 calls `CreateDistributionWithTags` even when its tag list is empty, and AWS requires `cloudfront:TagResource` for that request. The distribution ARN is generated during creation, so the apply policy scopes tagging to `arn:aws:cloudfront::<account>:distribution/*` and requires the expected PawLocal project and environment request tags plus the approved tag-key set.

These conditions do not prove that an existing distribution belongs to the role's environment. A development apply can retag a production distribution with `environment=development`, then use its account-wide, tag-conditioned `UpdateDistribution` grant to change the production distribution's full CloudFront configuration. The production apply role can do the equivalent to development. The owner explicitly accepts this cross-environment tagging and configuration risk as the lower-effort MVP tradeoff. OAC permissions continue to use the one-environment-at-a-time exact-ARN handoff.


## Identity state and app runtime identities

The identity state key is `pawlocal/identity/terraform.tfstate`. Its plan role can read the exact development and production state objects for foundation outputs and can write only its own lock; its apply role can write only the identity state and lock. Both use an identity-specific saved-plan prefix.

Development-plan and production-plan roles can inspect inline and attached policy metadata only on their corresponding exact Terraform apply role ARN, for the pre-approval promotion verifier. The verifier must inspect the `pawlocal-<environment>-terraform-application-services` inline policy where the CloudFront `TagResource` and `UpdateDistribution` statements live, and fail closed if unexpected managed policies are attached. IAM role-detail actions are excluded from wildcard discovery permissions; only `iam:ListRoles` remains there. Production Terraform refresh has a separate exact-role read statement for its application roles. Environment plan/apply roles receive S3 bucket refresh reads (including `ListBucket` for `HeadBucket` and `GetBucketAcl`) only on bucket ARNs with their matching `pawlocal-<environment>-` prefix. CloudFront `DescribeFunction` is limited to the fixed SPA function ARN for that role's environment. Identity-plan can read the identity state but only identity-apply can write it; both retain access only to the identity lock and identity saved-plan transfer prefix.

The IAM bootstrap state owns the three application roles and their trust documents: development and production frontend publisher roles trust only their exact GitHub Environment OIDC subject, and the development DSQL runtime role trusts the exact Lightsail principal plus the `development-seed` OIDC subject. The runtime role is created only after its exact Lightsail `principal_arn` is supplied from the foundation output. All three roles receive the bootstrap-owned `pawlocal-app-role-boundary` at creation.

The identity apply role cannot create roles, change trust documents, set or remove permissions boundaries, pass roles, or delete roles. It can attach/detach only the matching bootstrap-owned managed policy to each exact role. This keeps GitHub trust and role ownership in the separately controlled bootstrap state while the identity state owns only policy attachments.

The bootstrap-owned fixed policies grant only:

- Development/prod publisher: S3 list on its exact frontend bucket; get/put/delete objects under that bucket; CloudFront invalidations on its exact distribution.
- Development runtime: `dsql:DbConnect` on its exact DSQL cluster.
- Permissions boundary: the union of those exact allowed actions/resources, acting only as a ceiling.

After environment foundation outputs exist, pass the exact bucket, distribution, and development DSQL cluster ARNs into the bootstrap state. Empty values use nonexistent sentinel ARNs and provide no useful access. Apply and review that bootstrap policy update before the identity state attaches the policies.

## Explicit prerequisites and gaps

- Aurora DSQL automatically creates the service-linked role `AWSServiceRoleForAuroraDsql` when a cluster is first created. The bootstrap state manages it with `aws_iam_service_linked_role`; it is excluded from app-role policies. If it already exists, set `import_existing_dsql_service_linked_role=true` for the reviewed bootstrap plan. A conditional Terraform `import` block targets the fixed service-linked-role ARN; leave the variable false when the role does not exist. Review the import plan before applying.
- The Lightsail create grants use `Resource="*"` with request tags because those create APIs do not support a resource ARN or a create-time name condition. The fixed MVP budget and protected apply approval remain required; a tighter IAM boundary is not available for that create call.
- The existing fullstack module still defines app IAM roles in PR #113's current code. Environment applies cannot succeed until the identity root consumes bootstrap role and policy outputs and manages only policy attachments.
- Destructive recovery and legacy-stack teardown are out of scope for this release. This root creates no recovery plan/apply roles and grants no application-resource deletion or DSQL deletion-protection update permissions.
- GitHub's immutable OIDC subject customization and GitHub Environment protections must be verified before publishing role ARNs.

## AWS references

- [Amazon CloudFront service authorization](https://docs.aws.amazon.com/service-authorization/latest/reference/list_cloudfront.html)
- [CloudFront CreateDistributionWithTags required permissions](https://docs.aws.amazon.com/cloudfront/latest/APIReference/API_CreateDistributionWithTags.html)
- [Terraform AWS provider 6.69.1 distribution create implementation](https://github.com/hashicorp/terraform-provider-aws/blob/v6.69.1/internal/service/cloudfront/distribution.go#L1013-L1046)
- [Amazon Lightsail service authorization](https://docs.aws.amazon.com/service-authorization/latest/reference/list_lightsail.html)
- [Aurora DSQL service authorization](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazondsql.html)
- [Aurora DSQL service-linked role](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with-service-linked-roles.html)
- [Amazon Cognito User Pools service authorization](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazoncognitouserpools.html)
- [Amazon S3 service authorization](https://docs.aws.amazon.com/service-authorization/latest/reference/list_s3.html)
- [Route 53 service authorization](https://docs.aws.amazon.com/service-authorization/latest/reference/list_route53.html)

## Legacy combined-state GitHub Actions roles

The `legacy_terraform_role_arns` output contains a dedicated plan role for `infrastructure-plan` and a dedicated apply role for `infrastructure-apply`. Both trust the exact immutable repository and Environment subject. The plan role can read the legacy key `pawlocal/terraform.tfstate`, manage only its `.tflock`, read provider resources, and upload plan bytes plus metadata to the bootstrap transfer bucket under `plans/legacy/`. The apply role can write that state key, manage its lock, and read plans from that exact prefix. Terraform apply and destroy jobs both use this apply role behind the protected GitHub Environment.

The apply role receives only actions used by the current combined Terraform root, not `AdministratorAccess`. It can manage PawLocal-named S3 buckets/objects, the exact DSQL cluster class selected by region and environment/purpose tags, tagged PawLocal Cognito pools, PawLocal IAM role names, Route 53 records in the configured zone and approved DNS names, and the named PawLocal Lightsail services/certificates. It has no permissions for backups, recovery, restore, telemetry, CloudTrail audit resources, or arbitrary IAM managed policies.

Two documented MVP exceptions remain account-wide because the current Terraform resources cannot be safely selected by resource name/tag in IAM: CloudFront distribution IDs and OAC IDs are generated, and the distributions currently have no tags; Lightsail container-service creation also requires `Resource: "*"` and the service resource currently sends no tags. The role therefore can create CloudFront distributions/functions/OACs and update/delete any CloudFront distribution or OAC in the account; its Lightsail create grants can create services/certificates. The plan role also has read-only `Resource: "*"` discovery permissions required by provider refresh. Review these exact policy statements and the AWS authorization conditions before the local bootstrap apply. The role is restricted by OIDC to `infrastructure-apply`, whose branch rules and required reviewer provide the operational gate; this does not reduce the IAM resource scope.

The app root detaches the existing GitHub OIDC provider with `removed { destroy = false }`. After that app change is applied through the protected GitHub workflow, the bootstrap adopts the provider through the conditional Terraform `import` block. This keeps GitHub Actions trust available through full-stack destroy. Do not perform manual state edits or import commands.
