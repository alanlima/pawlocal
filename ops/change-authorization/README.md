# Trusted change authorization — #245

Implementation work is stacked on the frozen #248 controller. No protection,
Environment, App permission, credential or AWS setting is changed by this source
work. Keep incident activation disabled until the complete gate is independently
reviewed and one-time setup has positive execution/readback evidence.

The [entrypoint inventory](../../docs/change-authorization-entrypoints.md) is the
coverage baseline. An `audit` reconciliation can write GitHub configuration;
frontend verification can publish AWS assets. Both require authorization.

## Implementation units

1. A credential-free immutable-main classifier reads the actual PR and determines
   whether to verify incident receipts or enter protected ordinary approval.
   The privileged authorizer never checks out, imports, installs or executes PR
   content. Machine candidates execute under the protected main-only `incident-change-authorization`
   environment without human approval; ordinary changes execute under `ordinary-change-approval`
   requiring owner review. Both provision `PAWLOCAL_ONCALL_PUBLISHER_APP_PRIVATE_KEY`
   for status token minting downscoped strictly to `{ statuses: 'write' }`.
   A status-only publisher App token posts `PawLocal change authorization`
   only after rechecking exact head/base. The required status pins the App issuer.
2. A trusted operation receipt proves actual entry workflow/run/attempt and
   immutable source, environment, operation and selected release. An incident
   receipt must authenticate controller publication/merge provenance. Production
   additionally requires the exact verified development pair and stable recovery
   receipt. Ordinary main push releases reuse the authorized merged PR and remain
   automatic; manual infrastructure/production operations retain protected owner
   approval. Inputs, actor names and labels are never proof.
3. Every credential/reconciliation/publisher path consumes matching proof before
   access. Plan authority is separate from apply authority: authenticate operation,
   obtain bounded plan access, create the saved plan, then strictly validate scope
   and binding before requesting apply credentials. Machine release validation
   never uses the ordinary historical `--skip-enforcement` exception.
4. Bind saved-plan metadata to authorization proof, phase, selected release/image,
   environment/state, run/attempt and binary digest. Exercise forged lineage,
   stale approval, changed head/base, alternate workflow/caller and credential-job
   dependency failures. Bootstrap, destruction and data seeding cannot use machine
   incident authority.

An ordinary approval authorizes only the exact reviewed head and base. A change
while waiting invalidates it. Unknown provenance, unsupported policy, inaccessible
evidence and uncertain status delivery fail closed. No bypass actor or new AWS
resource is required.
