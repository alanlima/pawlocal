# Terraform role policy design

This root owns the shared GitHub OIDC provider, GitHub role identity/trust, baseline permissions, permissions boundaries, runtime identities, and the private saved-plan transfer bucket. Development and production roots own application resources and only their matching managed policies and attachments. Configuration is not evidence of an apply.

## Environment plan roles

Each plan role trusts only its exact `<environment>-plan` GitHub Environment subject; those Environments are restricted to `main`. It can read the matching state, manage only that state's lock object, perform provider refresh reads, and upload only to `plans/<environment>/`. It has no application-service mutation actions and no IAM write actions.

## Environment apply roles

Each apply role trusts only its protected `<environment>-apply` GitHub Environment. Bootstrap grants state/plan access and narrowly scoped IAM policy administration so the environment root can create/update its fixed-name application, frontend-publish, and runtime policies. Attachment actions are restricted twice: to the exact matching role ARN and to the exact matching policy ARN through `iam:PolicyARN`.

The bootstrap-owned boundary is the effective maximum. It does not allow role creation/deletion, trust changes, permissions-boundary changes, `PassRole`, OIDC changes, another environment's state, policies, attachments, DNS names, or named resources.

AWS limits a managed-policy document to 6,144 non-whitespace bytes. The repository enforces a stricter 6,050-byte budget against each rendered, minified environment apply boundary and verifies the environment-owned application policy against the AWS limit. The previous 5,500-byte target was raised only to accommodate the provider's required DSQL create-time authorization for the complete eight-tag cluster payload; the 6,144-byte AWS limit remains independently tested. Boundary statements omit non-authorizing SIDs and use read-only service patterns; the matching identity policy retains the provider's exact read actions. The boundary requires the matching project/environment authorization tags, while the environment-owned identity policy requires the approved tag-key set. S3 creation additionally requires every metadata tag value in both the create and dependent tag authorization. Because effective permissions are the intersection, this compaction does not add mutation authority or weaken cross-environment isolation. Before a DSQL cluster is handed back, the boundary exposes only the application and frontend-publish policy names; the exact runtime policy and attachment are added only after the matching cluster ARN exists.

| Service | Maximum environment authority |
|---|---|
| S3 | `CreateBucket` and its provider-required `TagResource` authorization are both restricted to the matching `pawlocal-<environment>-` prefix, exact tag keys, and the complete expected tag values. An untagged provider fallback therefore remains denied. `PutBucketTagging` and the provider's exact name-scoped pre-tag reads remain available to finish the create handoff; delete/configuration mutation still requires matching resource tags. No broad `s3:Get*` is granted. |
| Aurora DSQL | Tagged `CreateCluster` and its dependent `TagResource` authorization require the exact eight-key cluster payload: the six common application tags plus the environment-specific `Name` and fixed database `purpose`. A missing, extra, or incorrect tag fails closed. Update/delete/policy actions require matching resource tags. Runtime connection policy is an environment-owned exact-cluster policy attached only to the bootstrap runtime role. |
| Lightsail | Tagged container-service and certificate creation includes the dependent `TagResource` authorization. The certificate action uses AWS's required `Certificate/*` pre-creation resource form; the service remains exact-name scoped. Both require matching request tags and absent authorization tags. Update/deployment/delete requires matching resource tags, and `UntagResource` is never granted. |
| CloudFront | First-stage distribution creation and exact-name function creation include the provider-required `TagResource` authorization. Distribution tagging is limited to untagged distributions and exists only while both generated ARNs are empty; function tagging remains exact-name scoped. OAC creation follows the same temporary stage. After both distribution/OAC ARNs are returned to bootstrap, distribution create/wildcard-tag authorization disappears and update/delete is limited to those exact resources. `UntagResource` is never granted. |
| Cognito | Tagged user-pool creation includes the dependent `TagResource` authorization against AWS's required `userpool/*` pre-creation resource form, with matching request tags and absent authorization tags. Follow-on management requires matching resource tags. |
| Route 53 | Changes are limited to the configured zone, the environment frontend/API/validation names, and A/AAAA/CNAME types. |

The normal workflow plan guard rejects deletes and replacements except the provider's expected immutable Lightsail deployment-version replacement. A future destructive infrastructure change requires separate scope and authorization; the boundary alone is not authorization to apply it.

## Publisher and runtime identities

Bootstrap declaratively imports only the read-only-inventory-verified development publisher role when `import_existing_development_deploy_role=true`. The production publisher is created normally. Both trust only their matching release GitHub Environment and use their matching bootstrap-owned environment boundary. Environment roots create the exact frontend publication policy and attachment after their frontend resources exist.

The three app-specific managed policies present in the populated bootstrap state (development frontend, production frontend, and development runtime) have explicit `removed` blocks with `destroy = true`; the reviewed bootstrap plan must delete exactly those three policies rather than preserve duplicate ownership. The additional `identity_production_runtime` removed address is defensive because that resource existed only on an unapplied change and must be a no-op against the populated state. Bootstrap retains only identity, trust, baseline, boundary, and shared plan-transfer ownership. Environment roots are the sole owners of application, frontend-publish, and runtime policies and matching attachments.

The reviewed bootstrap plan must also delete exactly the two legacy `environment_service_apply` inline role policies. Those deletions intentionally remove the former inline application authority now replaced by bootstrap boundaries and environment-owned policies. The existing development app-role boundary keeps its state-compatible description so the policy updates in place; no other delete or replacement is allowed.

The first bootstrap apply partially completed before the environment apply boundaries were created, and the remote state serial advanced. Its saved plan is stale and must never be retried. After the size-safe boundary change is merged, normal refresh should produce only two environment apply-boundary creates and eight dependent environment Terraform role/inline-policy updates. If it contains any import, delete, replacement, application resource, unrelated resource, or additional drift, stop for a new review instead of applying it.

Development and production runtime roles are created only after bootstrap receives the exact Lightsail `principal_arn` from the matching foundation output. Each boundary contains only that environment's exact DSQL cluster ARN handed back through reviewed bootstrap inputs. The environment root creates the exact DSQL connection policy and attachment. This staged handoff avoids wildcard cross-environment runtime access and manual state operations.

## Saved plan handling

Plan roles upload opaque plans and metadata only beneath their environment prefix. Apply roles can only read that prefix. Metadata binds the plan SHA-256 to repository ID, commit, run, attempt, environment, state key, and a one-way account/backend/region fingerprint. GitHub summaries contain only resource type/action/count. Raw provider logs, raw plan JSON, plan binaries, Terraform state, credentials, secret values, account identifiers, and resource identifiers are not public evidence.

## Mandatory gates

- Bootstrap changes run locally only after independent review of a fresh exact saved plan and only under the owner's explicit bootstrap authorization.
- Application plans/applies run only through protected GitHub Environments.
- Development verification precedes production eligibility.
- Billable application provisioning still needs explicit cost approval.
- DSQL runtime identity and credential refresh require live development verification before production.
- An unrelated account-level personal workload is out of scope and must not appear in plan changes or evidence.
