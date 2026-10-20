# Terraform role policy design

This root creates role trust, role policies, the private saved-plan transfer bucket, and the fixed application identity policies. It does not make AWS calls in this document; the role grants are proposals until independently reviewed and applied through the approved Terraform path.

## Environment plan and apply roles

Development and production have separate plan/apply roles and separate state keys. Plan roles receive read-only application discovery and can upload a saved plan only beneath `plans/development/` or `plans/production/`. Apply roles can read only the matching saved-plan prefix and state key. Their AWS service grants are limited to the actions below. Resource deletes and recovery permissions are intentionally absent, so Terraform plans that require destroy/replacement will fail closed pending a separately reviewed recovery design.

| Service | Allowed environment apply actions | Resource and condition boundary |
|---|---|---|
| S3 frontend bucket | `CreateBucket`, `PutBucketTagging`, ownership/public access/encryption controls, bucket policy | Bucket names must begin `pawlocal-development-` or `pawlocal-production-`; controls and policy writes require existing `project=pawlocal` and matching `environment` tags. S3 bucket tagging is scoped by that name prefix because the S3 tagging API does not provide a reliable request-tag condition for bucket tags. Object deployment permissions belong to the separate fixed frontend publisher roles. |
| Aurora DSQL | `CreateCluster`, `UpdateCluster`, `PutClusterPolicy`, `TagResource` | Create uses the DSQL cluster ARN pattern and requires `project=pawlocal`, the matching environment, and approved tag keys. Updates require matching existing project/environment tags. Cluster deletion is not granted. |
| Lightsail | `CreateContainerService`, `CreateCertificate`, dependent `TagResource`, `UpdateContainerService`, `CreateContainerServiceDeployment` | Create APIs require `Resource="*"` in the AWS authorization model; requests require project/environment tags and the approved tag-key set. The dependent tag action is limited to the exact environment service and certificate ARNs and matching request tags. Updates and deployments are limited to the exact environment service ARN and existing tags. Create-time name limits are unavailable in IAM, so these create grants can create other same-tagged Lightsail services/certificates and carry cost risk. |
| CloudFront | `CreateDistribution`, `CreateFunction`, `TagResource` for the named function, `UpdateDistribution`, `UpdateFunction`, `PublishFunction` | Create APIs require `Resource="*"`; creation is gated by project/environment request tags and the fixed approved tag-key set. Function tagging is scoped to its exact environment-specific name. Distribution tagging is intentionally absent: AWS requires `TagResource` for `CreateDistributionWithTags`, and Terraform AWS provider 6.69.1 calls that API even when the tag list is empty. The generated distribution ARN is unavailable until after create, while granting distribution `TagResource` on `distribution/*` would let the role retag an existing resource. An exact-ARN handoff can scope later tag updates but cannot authorize initial creation. OAC permissions stay on the separate staged exact-ARN flow. CloudFront distribution creation therefore remains blocked pending an explicit safe ownership/permission decision. |
| Cognito | `CreateUserPool`, `UpdateUserPool`, create/update pool client and domain, `TagResource` | Pool creation requires project/environment request tags. Follow-on actions require matching project/environment resource tags on a user-pool ARN. Delete operations are not granted. |
| Route 53 | `ChangeResourceRecordSets` | Exact configured hosted-zone ARN. Change actions are limited to CREATE/UPSERT, record names to the environment API/frontend hostnames and one validation-label wildcard beneath the API hostname, and record types to A/AAAA/CNAME. DELETE is not granted. |

Terraform resource replacement may require delete permissions, which are deliberately not part of these app deployment grants. The saved plan must be inspected for create/update/delete/replace actions, and an unapproved replacement must not be applied.

### CloudFront distribution decision required

The current environment roles cannot safely create the CloudFront distributions while maintaining independent development and production access. The exact distribution ARN is unknown until `CreateDistributionWithTags` returns, but that call requires `cloudfront:TagResource`. Granting `TagResource` on `distribution/*` with only request-tag conditions also authorizes a separate tag request against an existing distribution. An exact ARN handoff can narrow later updates, but cannot authorize initial creation. The current policy therefore omits distribution `TagResource` and leaves distribution creation blocked.

Architecture choices for a later decision:

1. Accept a temporary `distribution/*` `TagResource` grant for a protected one-time creation path, with documented cross-environment retag access during that window.
2. Redesign ownership so a separate Terraform authority creates and owns the distribution, or isolate development and production in separate AWS accounts.
3. Keep distribution creation blocked until AWS or provider behavior supports safe ARN-level authorization at creation time.

This draft preserves the existing environment-isolation requirement and selects none of these changes.

## Identity state and app runtime identities

The identity state key is `pawlocal/identity/terraform.tfstate`. Its plan role can read the exact development and production state objects for foundation outputs and can write only its own lock; its apply role can write only the identity state and lock. Both use an identity-specific saved-plan prefix.

The IAM bootstrap state owns the three application roles and their trust documents: development and production frontend publisher roles trust only their exact GitHub Environment OIDC subject, and the development DSQL runtime role trusts the exact Lightsail principal plus the `development-seed` OIDC subject. The runtime role is created only after its exact Lightsail `principal_arn` is supplied from the foundation output. All three roles receive the bootstrap-owned `pawlocal-app-role-boundary` at creation.

The identity apply role cannot create roles, change trust documents, set or remove permissions boundaries, pass roles, or delete roles. It can attach/detach only the matching bootstrap-owned managed policy to each exact role. This keeps GitHub trust and role ownership in the separately controlled bootstrap state while the identity state owns only policy attachments.

The bootstrap-owned fixed policies grant only:

- Development/prod publisher: S3 list on its exact frontend bucket; get/put/delete objects under that bucket; CloudFront invalidations on its exact distribution.
- Development runtime: `dsql:DbConnect` on its exact DSQL cluster.
- Permissions boundary: the union of those exact allowed actions/resources, acting only as a ceiling.

After environment foundation outputs exist, pass the exact bucket, distribution, and development DSQL cluster ARNs into the bootstrap state. Empty values use nonexistent sentinel ARNs and provide no useful access. Apply and review that bootstrap policy update before the identity state attaches the policies.

## Explicit prerequisites and gaps

- Aurora DSQL automatically creates the service-linked role `AWSServiceRoleForAuroraDsql` when a cluster is first created. The bootstrap state manages it with `aws_iam_service_linked_role`; it is excluded from app roles and legacy recovery ownership. If it already exists, set `import_existing_dsql_service_linked_role=true` for the reviewed bootstrap plan. A conditional Terraform `import` block targets the fixed service-linked-role ARN; leave the variable false when the role does not exist. Review the import plan before applying.
- The Lightsail create grants use `Resource="*"` with request tags because those create APIs do not support a resource ARN or a create-time name condition. The fixed MVP budget and protected apply approval remain required; a tighter IAM boundary is not available for that create call.
- The existing fullstack module still defines app IAM roles in PR #113's current code. The planned recovery destroy must remove these legacy roles before bootstrap creates the new bootstrap-owned roles. Environment applies cannot succeed until the identity root consumes bootstrap role and policy outputs and manages only policy attachments.
- No recovery/delete role grants are included. Exact legacy resource IDs, DSQL deletion protection handling, and non-empty/versioned S3 cleanup require a separate reviewed plan.
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
