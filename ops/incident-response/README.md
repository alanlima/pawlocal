# Signed incident receiver — Issue #227

This independent adapter accepts Grafana Alerting notifications and requests only the deployment-configured repository → `incident-responder.yml` → `main`. It implements the amended [#42](https://github.com/alanlima/pawlocal/issues/42) contract in [receiver-openapi.yaml](receiver-openapi.yaml); it adds no FastAPI route. Resources and identities are **disabled by default**. No live App, AWS apply, Grafana contact point or dispatch is verified by the code/tests alone.

## Contract and failure behaviour

The Function URL accepts only `POST /`, uncompressed JSON up to 64 KiB and 20 alerts. Configure Grafana's HMAC header `X-Grafana-Alerting-Signature` and timestamp header `X-Grafana-Alerting-Timestamp`. Signing is `HMAC-SHA256(timestamp + ':' + original body bytes)`; accept up to 300 seconds old and 30 seconds future skew. Lambda reconstructs base64 body bytes before verification. Both grouped firing and resolved alerts are authenticated and validated; truncated groups and inconsistent group status fail closed. Only firing child alerts are dispatched. A valid resolved-only notification is acknowledged with HTTP 204 without reading the App key or calling GitHub, independently of incident enforcement mode.

Only environment/service/alert-name allow-listed records cross the boundary. Annotations, messages, dashboard/query URLs, values and arbitrary labels are dropped. Release labels accept only a full commit SHA or immutable image digest; route labels are ignored and omitted from dispatch. New APIs therefore do not require a receiver route allow-list, and raw customer path identifiers never cross this boundary. Metadata logs contain fixed outcomes and counts only. Source-side telemetry privacy remains required.

The handler reads two exact SSM SecureStrings at runtime:

- `/pawlocal/<environment>/secrets/grafana/webhook-hmac` — at least 32 UTF-8 bytes.
- `/pawlocal/<environment>/secrets/oncall/dispatch-app-private-key` — RSA private PEM, at least 2048 bits.

It checks App identity and actions-only permissions, exact repository installation and selected-repository scope before minting a short-lived token limited to the configured numeric repository ID and Actions write. The receiver's App must be **separate from the content/PR publisher App**, not just a token downscope from a publisher-capable private key. Actions write can authorize other repository workflows; the handler's fixed target is an application control, not a GitHub per-workflow permission claim.

For firing notifications it returns **204 only when GitHub returns exactly 204** from dispatch; resolved-only notifications return 204 without dispatch. Other downstream status, timeout or uncertainty returns non-2xx. Configure and demonstrate actual Grafana notification retry behaviour before activation. There is no persistent receiver replay ledger or AWS queue. Duplicate in-window notifications can dispatch twice; #228 trusted workflow preflight must serialize and check deterministic incident issue/PR markers, current alert state and closed outcomes before any model call. It must also check resolution before publication.

Four fixed GitHub calls and two SSM lookups have two-second request bounds plus a shared 15-second abort deadline; Lambda timeout is 20 seconds. Failed/uncertain delivery may require owner inspection and replay after notification retries or GitHub queue/cancellation loss. Never interpret dispatch accepted as a completed repair.

## Resource ownership and opt-in

Bootstrap owns identities/trust/boundaries. `oncall_environments = []` creates none. Enable only an independently reviewed selected environment after an approved bootstrap plan/apply. Bootstrap creates a receiver execution role with an immutable boundary and matching delegated `pawlocal-<environment>-oncall-terraform-{plan,apply}` roles trusting only their corresponding existing Terraform role.

The application root's `oncall_receiver = null` creates no receiver resources. A reviewed public operator object can opt in:

```hcl
oncall_receiver = {
  app_id           = "123"
  installation_id  = "456"
  repository_id    = "789"
  repository       = "example/repository"
  allowed_services = ["pawlocal-api"]
  allowed_alerts   = ["pawlocal-development-search-detail-failure"]
  # Optional existing KMS key ARN; never creates a key or stores a secret value.
  # kms_key_arn = "<exact reviewed key ARN in this account and region>"
}
```

The numbers above are illustrative, not configured App identities. The public `repository` is an explicit trusted deployment input, validated as `owner/repo`; signed alert labels cannot change it. `project_name` supplies resource names, IAM policy ARNs, public/secret SSM prefixes and the runtime `PAWLOCAL_PROJECT_NAME`. The external bootstrap identity setup tool remains scoped to the PawLocal default inventory; a non-default project requires an independently reviewed matching external policy/configuration inventory before activation, not just passing module tests. Obtain actual public IDs through approved App setup. Terraform consumes no PEM/HMAC values. For protected workflows, `PAWLOCAL_ONCALL_RECEIVER_CONFIG` is this public object as JSON in the matching plan Environment. Its default is `null`; this operator input intentionally stays outside SSM synchronization. Plan binds the object into the saved plan; apply uses that plan, not a reconstructed configuration. Both jobs append the same provider-profile name to the existing private shared config, using the exact matching read/write role; cleanup removes the shared file. The profile is only assumed when enabled resources need it, so default-disabled CI/releases require no new credentials. Production destroy planning uses the same protected operator object and matching purpose profiles. Keep the object configured until an approved Terraform removal/teardown has removed receiver state.

Environment state owns the official Lambda module `8.12.0` (Node.js 24, 128 MiB, 20-second timeout, reserved concurrency 2), 14-day log group, exact-role inline runtime grants, Function URL, its public String `/pawlocal/<environment>/config/oncall/webhook-url`, and two URL-only public invocation permissions. The #225 shared collision-check/base-plan read integration must land before enabling this producer. No environment root creates an IAM role. Normal saved plans schedule the module-local packaging sidecars on the fresh apply runner; teardown plans do not rebuild packages. Initial infrastructure activation still requires owner-reviewed plan/apply. The configured incident runtime follows the automated machine gates in #228.

The delegated apply role needs regional `logs:DescribeLogGroups` and `ssm:DescribeParameters` metadata because the provider cannot authorize that action by log-group ARN; it has no log-content access or SecureString retrieval. Public-parameter reads and writes name only the exact webhook URL. It can add a public permission on the exact matching function and manage inline policies on the exact receiver role. IAM cannot constrain an inline-policy name; the bootstrap boundary limits every grant. Review actual URL-only permission conditions and absence of unexpected survivors in the saved plan. These are trusted Terraform permissions, never coding-agent permissions.

## KMS selection and activation proof

No new customer-managed KMS key is required or provisioned. With no explicit ARN, code adds no `kms:Decrypt` wildcard and relies on default `aws/ssm` key policy plus exact SSM retrieval permissions. AWS documents that the managed key grants account principals decryption; its interaction with this role's boundary/key/account policies is **not live-verified here**. Prove decryption under the exact deployed receiver identity before routing alerts. Do not claim local policy tests establish AWS runtime access.

If explicit key access is required, supply the **same exact existing key ARN** in the environment object and bootstrap `oncall_receiver_kms_key_arns` entry. It may identify an already existing managed or customer-managed key; no new paid key is implied. Both policies then allow only that ARN through matching regional SSM and encryption context for the two exact parameter ARNs. The existing key policy must allow this use. A customer key offers a separate decrypt control; default `aws/ssm` relies on SSM access control rather than per-principal key-policy customization. A mismatch fails closed and requires a reviewed new plan, not wider decrypt grants.

## Verification and operations

Run `node --test tests/ci/incident_receiver.test.mjs` at repository root. Terraform CI runs these tests on Node.js 24, plus mocked policy/configuration plans. Tests cover genuine RSA JWT signing, narrow App/install/token policy responses, raw-body HMAC, invalid/expired/oversized/grouped payloads, route/private-field controls, all non-204 acknowledgements, uncertainty, request-wide cancellation and explicitly repeatable in-window delivery. HTTP and SSM are injected mocks; no real secret or dispatch is exercised.

Before live activation, require #223 configuration and reviewed identities, #226 G1, protected workflow #228 admission/deduplication, actual App/API authorization, secret lifecycle approval, matching saved-plan review and owner apply. Demonstrate fresh signed firing/resolved delivery and failure/retry behaviour, then #229 G2 before production-origin runs.

Disable by removing the Grafana contact point route and closing trusted workflow admission; inspect in-flight runs before publication. Infrastructure removal is a reviewed Terraform change, never a direct Lambda/URL mutation. Rotate HMAC and App keys through the separately approved SSM owner lifecycle, test signing/dispatch before retiring old values and record only metadata. The handler deliberately re-reads secrets per request rather than caching stale keys. If downstream is unavailable, inspect fixed outcome codes and GitHub run/incident metadata; do not paste raw signed bodies, keys or token responses into issues.

Sources: [Grafana HMAC](https://grafana.com/docs/grafana-cloud/observe-and-act/alert-and-measure-reliability/alerting/configure-notifications/manage-contact-points/integrations/webhook-notifier/), [GitHub App JWT](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app), [installation token schema](https://docs.github.com/en/rest/apps/apps#create-an-installation-access-token-for-an-app), [Function URL access](https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html), [Node.js runtime/SDK](https://docs.aws.amazon.com/lambda/latest/dg/lambda-nodejs.html), [SSM default-key permissions](https://docs.aws.amazon.com/systems-manager/latest/userguide/ps-restrict-decryption.html), [IAM boundary evaluation](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_boundaries.html).
