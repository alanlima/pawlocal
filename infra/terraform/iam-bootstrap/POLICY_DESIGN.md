# Terraform role policy design

This root owns the shared GitHub OIDC provider, GitHub role identity/trust, baseline permissions, permissions boundaries, runtime identities, and the private saved-plan transfer bucket. Development and production roots own application resources and only their matching managed policies and attachments. Configuration is not evidence of an apply.

## Environment plan roles

Each plan role trusts only its exact `<environment>-plan` GitHub Environment subject; those Environments are restricted to `main`. It can read the matching state, manage only that state's lock object, perform provider refresh reads, and upload only to `plans/<environment>/`. It has no application-service mutation actions and no IAM write actions.

## Environment apply roles

Each apply role trusts only its protected `<environment>-apply` GitHub Environment. Bootstrap grants state/plan access and narrowly scoped IAM policy administration so the environment root can create/update its fixed-name application, frontend-publish, and runtime policies. Attachment actions are restricted twice: to the exact matching role ARN and to the exact matching policy ARN through `iam:PolicyARN`.

The bootstrap-owned boundary is the effective maximum. It does not allow role creation/deletion, trust changes, permissions-boundary changes, `PassRole`, OIDC changes, another environment's state, policies, attachments, DNS names, or named resources.

| Service | Maximum environment authority |
|---|---|
| S3 | Create only a bucket with the matching `pawlocal-<environment>-` prefix; later management requires matching project/environment tags. |
| Aurora DSQL | Create requires matching request tags; update/delete/policy actions require matching resource tags. Runtime connection policy is an environment-owned exact-cluster policy attached only to the bootstrap runtime role. |
| Lightsail | Create requires matching request tags. Update/deployment/delete requires matching resource tags. `TagResource` is limited to the exact environment service/certificate names, requires the two authorization request tags, and is allowed only while both resource tags are absent. `UntagResource` is never granted. |
| CloudFront | Create is permitted for the greenfield foundation. Function management uses the exact environment name. Distribution and OAC update/delete permissions are absent until the generated exact ARNs are returned to bootstrap and independently reviewed. No distribution retag permission exists. |
| Cognito | Create requires matching request tags; follow-on management requires matching resource tags. |
| Route 53 | Changes are limited to the configured zone, the environment frontend/API/validation names, and A/AAAA/CNAME types. |

The normal workflow plan guard rejects deletes and replacements except the provider's expected immutable Lightsail deployment-version replacement. A future destructive infrastructure change requires separate scope and authorization; the boundary alone is not authorization to apply it.

## Publisher and runtime identities

Bootstrap declaratively imports only the read-only-inventory-verified development publisher role when `import_existing_development_deploy_role=true`. The production publisher is created normally. Both trust only their matching release GitHub Environment and use their matching bootstrap-owned environment boundary. Environment roots create the exact frontend publication policy and attachment after their frontend resources exist.

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
