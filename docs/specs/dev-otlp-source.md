# Draft DEV OTLP source boundary (#241)

Status: isolated code and offline proof only. No live source, permission, setup channel, or apply is approved by this document. The full four-source #241 work remains a separate draft. DEV ingestion and Faro are the current scope; alerts and production setup remain excluded.

The existing canonical `/pawlocal/development/secrets/grafana/otlp-token` is an unmanaged String. Importing/adopting it can persist its payload with the pinned provider, so this design leaves it untouched. The proposed new Standard SecureString is `/pawlocal/development/secrets/grafana/otlp-token-v1`, owned by the existing development application state at `module.dev_otlp_source.aws_ssm_parameter.token[0]`. There is no new service or Terraform state.

## Public interface

The isolated development root accepts these inputs:

| Input | Default | Meaning |
| --- | --- | --- |
| `dev_otlp_source_managed` | `false` | Stable source ownership; independent of telemetry export enablement |
| `dev_otlp_source_write_revision` | `1` | Positive integer write-only revision; normal plans cannot rotate it |
| `dev_otlp_source_creation` | `null` | Explicit first-creation selection: `{legacy_version=1, legacy_last_modified="<reviewed server timestamp>"}` |
| `dev_otlp_source_creation_value` | `null` | Sensitive ephemeral private input, only in child process environment |

After creation, retain `managed=true`, revision one and `creation=null`, even when telemetry exports are disabled. Maintenance reads only the exact new source through the provider ephemeral resource. No legacy fallback is implemented. `prevent_destroy` prevents input removal from deleting the source.

The public runtime pointer proposed for the lead's separate changes is `otlp_token_parameter_name` / `PAWLOCAL_GRAFANA_OTLP_TOKEN_PARAMETER_NAME`. This isolated change does not wire it, alter IAM, or enable telemetry.

## Protected handoff contract

`ops/monitoring/dev_otlp_source.py` provides an injected-client `creation_environment` context manager. One exact unversioned legacy ARN GetParameter response supplies the current Value, Type, Version and LastModifiedDate atomically. The current response must be version one; a historical version-one selector is forbidden because it would conceal newer-version drift. The helper rejects any mismatch to the reviewed public tuple, unexpected ARN, malformed/empty value, or Terraform debug tracing. It yields a child environment containing only the sensitive ephemeral Terraform variable and removes that dictionary entry when the context exits. Python cannot guarantee memory zeroization. Normal Terraform stdout/stderr must remain intact; SDK responses and private input must never be printed.

The metadata-only CLI accepts `--selection-json`, `--target-metadata-json`, optional `--source-metadata-json`, and optional internal `--plan-json`. Selection JSON has exactly `managed`, `write_revision`, and `creation` keys. Source JSON contains metadata only, never Value. The trusted carrier must obtain fresh exact-target metadata before planning and before applying, reject collisions/pagination/errors, bind the public selection and saved plan to the protected run, compare current ownership, then invoke the guard. This library is not that carrier and is not sufficient authority to run an apply.

The guard binds public inputs to planned metadata, rejects import/delete/replacement/rotation and unknown maintenance metadata, and permits initial creation only for the exact new resource with no unrelated managed change except existing local Cognito packaging. Computed provider identity fields on creation are deliberately allowed. Existing normal release guards must still reject any source changes. A reviewed setup plan is the only candidate exception.

Prefer plan and apply inside the same helper context. Separate jobs must each validate the identical immutable service version and timestamp atomically; a binary plan digest does not bind ephemeral bytes. Any legacy drift, recreation or target collision stops setup. Never adopt or overwrite a collision.

## Future review and execution sequence

1. Independently review this module/helper/proof and the lead's public pointer and bootstrap changes. Validate the existing DEV account, region, app-state ownership, exact source metadata and target absence read-only.
2. Review a concrete bootstrap saved plan: temporary canonical GetParameter for existing DEV plan/apply identities only; exact new-source maintenance reads, apply creation/update/tag rights and runtime read rights. Intersect existing permission boundaries. No history/by-path, namespace wildcard, resource policy, old writes, new trust or KMS key is proposed. Verify effective default-managed-key authorization with the actual scoped roles rather than inferring it from policy absence.
3. Obtain owner approval of the exact destination, reviewed public legacy tuple, role changes, private carrier and operational-log continuity, saved plan and costs. Standard SSM adds no new fixed service resource; request/KMS and telemetry usage costs still require concrete review. This document is not cost approval.
4. In the protected runner, freshly verify target absence and legacy tuple, use atomic private input, generate the one-source saved plan against the existing DEV app configuration, inspect private plan/state internally and independently review public plan summary. Recheck all bindings and current source metadata before the exact saved-plan apply with native Terraform lock/staleness checks.
5. Persist only the stable public management selection and new runtime pointer. Remove creation selection/private input, prove exact maintenance no-op, and apply the separately reviewed bootstrap cleanup removing temporary legacy read grants. Verify DEV ingestion/Faro without alerts; never silently revert to the old source.

No live step above is performed by this isolated draft.

## Offline verification

Run the focused checks with `python -m unittest discover -s tests/ci -p test_dev_otlp_source.py -v`. Set `PAWLOCAL_RUN_SECRET_LIFECYCLE_FIXTURE=1` to include the actual Terraform 1.14.3 / AWS 6.69.1 module proof after initializing the pinned `iam-bootstrap` provider locally. The fixture uses fake credentials, synthetic payloads and loopback endpoints only, denies non-loopback proxy traffic, checks default-off zero SSM calls, atomic legacy String input, write-only creation, exact maintenance no-op, denied reads and wrong-type failure. It scans binary plan ZIP members, rendered JSON, state/backups and captured diagnostic streams for synthetic payloads. Programmatic JSON remains internal; normal operational diagnostics are emitted in full. This is offline evidence, not live acceptance.
