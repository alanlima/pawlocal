# Proposed monitoring secret lifecycle (#241)

**Status: PROPOSED; owner decision and independent review pending.** This document proposes a resolution to a design gap under [#223](https://github.com/alanlima/pawlocal/issues/223), not evidence of live acceptance. It creates no parameter, permission, credential, workflow or Terraform state. Runtime monitoring and incident activation remain blocked on approved source population. DEC-013 proposes an exception to wording that Terraform never receives a secret payload: Terraform may receive an ephemeral in-memory value through a write-only field, but must never persist it in a plan, state, artifact or diagnostic.

## Ownership and exact sources

Use the existing matching application state; IAM changes remain in the bootstrap/application owners already agreed. No fourth state, CLI/SDK resource mutation, ordinary Terraform secret variable, `data.aws_ssm_parameter` value, output, placeholder, automatic adoption or import is proposed. Paths below show the default `pawlocal` project; receiver paths follow its approved project prefix.

| Source suffix under `/{project}/{environment}/secrets/` | Source owner / runtime consumer | Additional handoff |
|---|---|---|
| `grafana/otlp-token` | Application state; backend matching DSQL runtime role reads this exact source | None to GitHub or browser |
| `grafana/webhook-hmac` | Application state; matching receiver reads this exact source | Trusted Grafana contact-point setup receives it through the approved secure setup channel; no GitHub synchronization |
| `oncall/dispatch-app-private-key` | Application state; matching receiver reads this exact source | None to GitHub; dispatch App identity/installation IDs are public configuration |
| `grafana/query-token` | Application state, if separately approved | Proposed exact-source read and encrypted write to the matching existing main-only on-call GitHub Environment secret; absent from active public YAML/reader permissions |

OTLP is an ingestion credential. The query credential must be a separately approved **Grafana stack service-account Bearer token** with actual read authority for the configured Alertmanager and fixed `/api/ds/query` signals; a Cloud Access Policy token cannot simply be substituted for Grafana stack API authentication. Viewer is a candidate role, not proof of per-environment isolation on the shared stack. Prove each signal's actual scope before production reads; withhold signals that cannot be authorized. Exact datasource UIDs are approved discovered configuration, not invented defaults. OpenAI and publisher credentials remain separate protected GitHub scopes.

## Proposed protected handoff

Initial creation and rotation require an owner-operated, isolated, ephemeral setup runner using explicitly approved short-lived plan/apply identities. The owner supplies the exact selected source values through a secure interactive channel into process memory; the reviewed setup controller passes sensitive **ephemeral** Terraform variables without command-line payloads, files, logging, shell tracing or persisted runner artifacts. This runner/identity/channel is a proposed setup mechanism, not an already configured or authorized workflow. Its reproducible implementation and identity acquisition must be reviewed before use. No persistent GitHub copy of OTLP, HMAC or receiver private-key values is required. A GitHub-hosted alternative requiring temporary secret copies is not selected by this proposal.

The controller freezes that operation's in-memory input set from plan through saved-plan apply. Public source names, selected override names, existing ownership, approved metadata and monotonic write revision identify the reviewed operation. No payload hash, fingerprint, version field in the mapping YAML, or new source registry is added. Provider `value_wo_version` is a write trigger, distinct from SSM's returned parameter version.

**A saved plan does not bind ephemeral bytes.** A different re-supplied value can be applied to the same plan. Approval of a plan therefore cannot by itself approve its secret contents. If the secure input session is lost, stop and create/review a fresh setup operation; do not rehydrate arbitrary values under the prior approval. Do not publish the saved binary or JSON plan merely because secret exclusion was tested: ordinary plan metadata still follows existing private-plan policy.

## Creation, maintenance and rotation

The future configuration uses public, reviewed maps/sets for resource identities and revisions. Never derive `for_each` or identity keys from ephemeral inputs. The exact override-name set must match nonempty ephemeral input keys; missing/extra/blank values fail before mutation.

1. **Initial creation:** only explicitly selected sources receive owner overrides; no ephemeral read is attempted for those sources. The managed SecureString uses `value_wo` and an approved `value_wo_version`. Initial default no-overwrite behavior rejects an existing unmanaged source. Inventory and state ownership must pass before planning; an orphaned source is a collision requiring a separate decision, not an adoption opportunity.
2. **Ordinary maintenance:** existing managed sources not selected for override are read using `ephemeral "aws_ssm_parameter"` with their exact **literal ARN**. That current value feeds the same managed resource's `value_wo`; do not reference the managed resource's ARN from its own upstream read, which creates a graph cycle. Stable public identity determines the graph. No permanent GitHub copy or owner re-entry is required for each normal plan/refresh. Failed decryption/read, absent source or empty current value fails closed; never replace with empty text or a generated placeholder.
3. **Refresh/no-op:** the provider reads decrypted values into memory, then clears its ordinary state value when write-only configuration remains active. Maintain nonempty `value_wo` and the stored `has_value_wo` marker. Inspect state after every tested lifecycle transition; sensitive marking alone does not prevent state storage. Do not remove write-only configuration from an existing resource.
4. **Rotation:** explicitly select an override, obtain the approved new value, and advance the public write revision monotonically. Preflight compares reviewed current ownership/revision with the last successful operation; unchanged/stale revisions cannot authorize a new override. Revalidate runtime acceptance and cache expiry before retiring the old upstream credential. Rotation is not an incident-agent capability.
5. **Metadata update:** pinned provider code only reads `value_wo` for an update when `value_wo_version` changes. A description/key/tier update with an unchanged revision may send an empty ordinary value. Therefore preflight must reject such changes unless the approved write revision also advances, using either the current ephemeral value or an explicit rotation override. Do not assume ordinary metadata reconciliation is safe automatically.
6. **Disablement/teardown:** disable consumers through their approved release/configuration lifecycle first. Retain source ownership while inactive; do not delete credentials as an automatic side effect of a missing input. Actual deletion needs a separately approved Terraform plan and revocation order after consumers stop. A future `prevent_destroy` guard requires an explicit reviewed teardown change.

State-free values also prevent Terraform comparing intended bytes with out-of-band changes. Ordinary maintenance preserves the currently read value; it does not prove the original approved content. Enforce sole-write ownership, audit mutations and verify actual consumer acceptance. An unexpected source version or ownership change stops setup for investigation.

## Authority change that needs approval

Both matching **plan and apply identities** need decrypted `ssm:GetParameter` on the exact approved source ARNs for refresh and ephemeral maintenance, not just write rights. This expands secret visibility beyond runtime roles and must be explicitly reviewed. Keep this separate from the public tag-conditioned configuration reader. No `GetParametersByPath`, history, wildcard secret namespace, public authorization tag or secret copier admission is implied.

The matching apply identity needs exact managed-source creation/update/tag/deletion permissions consistent with approved lifecycle and existing permission-boundary intersection. Pinned provider refresh also uses `DescribeParameters` metadata and tag reads; the existing region-limited metadata ceiling must be checked rather than claiming a resource-scoped metadata permission. Customer-key operations require exact key ARN, SSM ViaService, exact `PARAMETER_ARN` encryption context and the actual key policy/grants. The source and key must be in the approved account/region. Default AWS-managed SSM encryption needs no invented customer-key ARN.

Initial runner access, upstream credential provisioning, trusted contact-point setup, query handoff, exact role/key changes and billable operations all need the corresponding one-time setup decision. Runtime agents receive none of these setup/write credentials. This proposal changes no unattended runtime contract under #239.

## Offline proof and acceptance limits

The checked-in opt-in [real-provider fixture](../../tests/ci/test_monitoring_secret_lifecycle.py) pins Terraform **1.14.3** and AWS **6.69.1**, uses synthetic values/fake credentials, and serves SSM only on loopback. Non-loopback proxy requests are rejected. It exercises creation, refresh, same-value no-op, rotation, missing re-supply, differing re-supply, denied reads and empty-source failure. It inspects binary plan ZIP members, rendered JSON plans, JSON state/backups and captured diagnostics for synthetic payloads. The real-provider lifecycle passed locally on 2026-10-23 (123.8 seconds). Two additional pure transition-contract tests demonstrate stale-override and metadata-update rejection; this example guard is not wired to any production setup controller. It is not a deployment module and introduces no live root configuration.

```powershell
terraform -chdir=infra/terraform/iam-bootstrap init -backend=false -lockfile=readonly
$env:PAWLOCAL_RUN_SECRET_LIFECYCLE_FIXTURE = '1'
python tests/ci/test_monitoring_secret_lifecycle.py -v
```

Initialize only with the repository's pinned lock file. The test itself uses an isolated temporary local backend/provider mirror, never an application backend or AWS credentials. Provider installation may download the pinned public binary; all fixture AWS API traffic is local. The normal workflow unit suite runs the two transition-contract tests and skips the opt-in provider case. Terraform CI explicitly runs the provider case after pinned bootstrap-provider initialization; no live backend is used.

A failed missing-input apply can advance the local state serial; replan after such failure instead of retrying a stale saved plan. The differing-byte proof uses a fresh plan and confirms this limitation, not a permitted setup procedure.

The local fixture cannot establish real IAM/KMS enforcement, secure owner input acquisition, upstream token validity, actual Grafana scoping, HMAC rollout continuity or consumer recovery. Those remain implementation and live acceptance requirements. No new live setup or permission approval is implied by this proposal or test result.

## Primary contract sources

- [Pinned AWS 6.69.1 write-only SSM resource](https://github.com/hashicorp/terraform-provider-aws/blob/v6.69.1/website/docs/r/ssm_parameter.html.markdown).
- [Pinned ephemeral SSM resource](https://github.com/hashicorp/terraform-provider-aws/blob/v6.69.1/website/docs/ephemeral-resources/ssm_parameter.html.markdown).
- [Pinned provider read/update implementation](https://github.com/hashicorp/terraform-provider-aws/blob/v6.69.1/internal/service/ssm/parameter.go), especially `resourceParameterRead` and `resourceParameterUpdate`.
- [Pinned ephemeral implementation](https://github.com/hashicorp/terraform-provider-aws/blob/v6.69.1/internal/service/ssm/parameter_ephemeral.go).
- [HashiCorp ephemeral values](https://developer.hashicorp.com/terraform/language/manage-sensitive-data/ephemeral) and [write-only arguments](https://developer.hashicorp.com/terraform/language/manage-sensitive-data/write-only).
