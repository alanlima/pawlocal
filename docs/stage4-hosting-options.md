# Stage 4 hosting and cost proposal

**Status:** Human direction recorded 2026-10-18; technical validation and cost approval remain open. No resources are provisioned or approved for spending.
**Pricing checked:** 2026-10-18. Prices are USD before tax; Sydney/Australia regions are used where published.

## Direction under review

- **Application host:** AWS Lightsail. Run FastAPI as a Docker container on a Linux instance, keep Docker Compose for local development, and keep the existing S3/CloudFront frontend.
- **Database candidate:** Aurora DSQL in `ap-southeast-2` is preferred for investigation only. It is not yet a PostgreSQL drop-in for PawLocal; compatibility blockers and the required validation are in [the DSQL compatibility note](dsql-compatibility-validation.md).
- **Environments:** separate development and production data, credentials, configuration, deployment targets, and clusters. Promote the same tested application image from development to production.
- **Not selected:** DynamoDB and Lambda. Conventional PostgreSQL alternatives must be compared if DSQL's material compatibility issues cannot be resolved.
- This direction authorizes documentation and investigation only. It does not approve a spend envelope, provisioning, `terraform apply`, or production migration. DRAFT-002 remains open.

## Workload and estimate assumptions

- Two always-available application environments, each with 10,000 API requests, 10 GB outbound API data transfer, and 1 GB of logical database storage per month.
- The mock-backed frontend stays on the existing static AWS S3/CloudFront deployment; its separate estimate is tracked in [Issue #25](https://github.com/alanlima/pawlocal/issues/25).
- Lightsail sizing below is a comparison starting point only: 1 GB for development and 2 GB for production, each running the API container and a lightweight collector. Neither has been measured; choose sizes after capturing memory/CPU under representative loads.
- Grafana Cloud Free is assumed to remain within its shared account limits. Both environments share one AWS account's DSQL free allowance; do not count it twice.
- The DSQL cost model uses AWS Price List data for `ap-southeast-2`, effective 2026-07-01: $0.000009/DPU ($9 per million) and $0.36/GB-month, plus the published monthly allowance of 100,000 DPUs and 1 GB-month of storage per AWS account/management account. Request counts are not a proxy for DPU usage. Captured price list version: [`20260911124522/ap-southeast-2`](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AuroraDSQL/20260911124522/ap-southeast-2/index.json).
- GitHub Actions build minutes/registry, independent availability probes, Lightsail backup storage/restore, DSQL backup/restore, support, tax, AUD conversion, and measured DPU consumption are unknown or account-dependent; they are not silently priced at zero.

## Current monthly estimate

The AWS subtotal below is a provisional floor for the selected direction under the stated free-tier assumption, not a price ceiling or spending recommendation.

| Environment | Lightsail application VM | DSQL storage allocation | DSQL activity | Grafana Cloud | Provisional subtotal |
| --- | ---: | ---: | --- | ---: | ---: |
| Development | $7.00 (1 GB) | $0.18 (illustrative half of one billed GB-month) | First 100k DPUs shared by both environments are free; overage unmeasured | $0 if within shared Free limits | **$7.18 + its share of DPU overage and unpriced items** |
| Production | $12.00 (2 GB) | $0.18 (illustrative half of one billed GB-month) | Shared allowance; overage unmeasured | $0 if within shared Free limits | **$12.18 + its share of DPU overage and unpriced items** |
| **Both environments** | **$19.00** | **$0.36** (2 GB-month total less 1 GB free) | **TBD from measured workload** | **$0 conditional on shared limits** | **$19.36 + DPU overage, backup/restore, external monitoring, build/registry, and other unpriced items** |

The $19.36 figure assumes 2 GB total average DSQL storage, 100,000 or fewer combined monthly DPUs, and the Grafana account remaining within its shared allowance. Each additional DPU is $0.000009 at the published Sydney list rate; additional DSQL storage is $0.36/GB-month. Obtain a measured sample-query DPU result and updated AWS pricing-calculator estimate before deciding a monthly envelope. The Lightsail instances include local SSD and transfer allowance; 10 GB/environment is within the published instance data-transfer allowance. Re-check the [Aurora DSQL price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AuroraDSQL/current/region_index.json) and captured version before approval.

The previous $24 development / $44 production Lightsail sizes and approximately $71 combined estimate assumed a local PostgreSQL server and the full self-hosted observability stack. They are withdrawn for this revised architecture.

## Alternatives retained for comparison

| Option | Development | Production | Both environments | Recovery and operations |
| --- | ---: | ---: | ---: | --- |
| **AWS Lightsail + Aurora DSQL + Grafana Cloud Free** | $7.18 provisional priced subtotal, plus shared DPU overage and unknowns | $12.18 provisional priced subtotal, plus shared DPU overage and unknowns | **$19.36 provisional priced floor**, subject to the assumptions above | Self-managed VM/container patching and recovery; DSQL is multi-AZ managed, but app hosting remains one VM/environment. DSQL compatibility, backup/restore and IAM from Lightsail need validation. |
| DigitalOcean App Platform + Managed PostgreSQL + Grafana Cloud | About $17 at full runtime under the documented small-app plans | About $30 for full runtime and one small database node | About $47 full runtime; **at least about $292** if production requires an Advanced Edition primary plus standby | Low-ops app/database. New Standard Edition clusters cannot add standby nodes for new accounts from 2026-10-15 (all accounts from 2026-11-30); HA Advanced starts at $130/node. App Platform Scale to Zero may reduce eligible inactive web-service compute but adds cold-start behavior; verify account/plan eligibility and do not assume it. |
| Fly Machines + Managed Postgres + Grafana Cloud | $38 Basic DB + storage + collector + stopped/running Sydney app Machine | $38 Basic DB + storage + collector + stopped/running Sydney app Machine | **At least $76 + $0.56 assumed DB storage**, plus two collectors, app Machines/rootfs and traffic | Managed Postgres starts at $38/cluster plus $0.28/GB-month storage; each cluster includes HA/backups. Compute varies by Machine size and Sydney region. The prior $85.94/$99.31 total is withdrawn because it used an older, unverified machine/collector estimate. |

| Option | OpenTelemetry / hosted telemetry fit | Terraform and CI/CD fit |
| --- | --- | --- |
| AWS Lightsail + Aurora DSQL | Proposed lightweight collector per environment exporting to Grafana Cloud; validate OTLP export, quotas, residency and failure alerting. | Terraform is already used for the frontend AWS stack; backend resources, image registry, short-lived deploy credentials, artifact promotion and rollback workflow are not implemented or costed. |
| DigitalOcean App Platform + Managed PostgreSQL | Grafana Cloud is the common target; verify the selected app topology can run the collector and export OTLP without exposing ingestion credentials. | Provider resource coverage, secrets flow, image promotion and rollback require a prototype; no deployment workflow is included in the estimate. |
| Fly Machines + Managed Postgres | A collector can be evaluated alongside each app Machine; validate export, residency, quotas and behavior when an app Machine is stopped. | Provider tooling, secrets flow, immutable image promotion and rollback require a prototype; no deployment workflow is included in the estimate. |

DigitalOcean and Fly are evaluated alternatives, not selected targets. DigitalOcean's prior $92.90 HA scenario used Standard standbys that are no longer available for new accounts and will be unavailable to all accounts after 2026-11-30. At current Advanced pricing, two $130 database nodes plus the $32 app/collector/development subtotal makes the two-environment total about $292 before any additional costs. DigitalOcean App Platform's official documentation also describes Scale to Zero/Inactivity Sleep; actual availability, minimums and cold-start impact remain account/configuration-specific. Fly's minimum database/storage subtotal is priced, but its full Sydney app/collector estimate needs region-specific Machine sizing.

Fly's summary is a lower-bound component estimate, not a completed full-app estimate. A stopped API Machine is unavailable until it starts again and may introduce cold-start latency; it does not meet the always-available assumption above. Price always-on Sydney Machines separately before comparing Fly on an availability-equivalent basis. Its pricing is in USD, with Sydney Machine rates and data transfer varying by region. Refresh the exact Sydney development and production sizing with the provider calculator if Fly returns to consideration.

## Open acceptance evidence

Issue #41's requested provider fit, full low-traffic estimate and DSQL sample-query cost are not complete. The table above records the tooling and telemetry questions still requiring prototypes; the AWS amount is only a priced floor. Close those gaps with an availability-equivalent cost comparison, implementation/rollback estimates, and measured DSQL usage after a separately approved disposable test environment is available. Keep DRAFT-002 and Issue #41 open until the evidence and the separate cost/provisioning approval are recorded.

## DSQL compatibility and integration gate

The current backend has not been validated against Aurora DSQL. Repository inspection found that the persisted PostgreSQL `ARRAY` facilities column and emitted Alembic index DDL require changes or a DSQL-specific migration path. The current SQLAlchemy engine also uses the standard psycopg dialect; AWS's SQLAlchemy DSQL dialect/connector and IAM token lifecycle are not configured. See the matrix and gated runbook in [dsql-compatibility-validation.md](dsql-compatibility-validation.md).

Before confirming DSQL, inspect the actual schema, repositories and migrations; adapt where needed; then run a clean migration, an upgrade migration, and the existing repository integration journey against a separately approved DSQL test cluster. The validation must cover search filters/count/pagination, favourites idempotency, duplicate review rejection, contribution/report persistence, referential integrity, rating aggregation, concurrent writes/conflict retries, connection refresh, and measured query DPUs. Local PostgreSQL passing is not evidence of DSQL compatibility. No DSQL cluster was created or queried for this proposal because no resource/cost approval was granted.

If these compatibility blockers are material, compare RDS for PostgreSQL and encrypted Lightsail managed PostgreSQL on Sydney pricing, database HA, backup/restore, connectivity, and the existing application's PostgreSQL fit before changing the human's preferred direction.

## Deployment, data and observability boundaries

- Treat Lightsail instances and containers as replaceable. Keep application state out of the VM filesystem; store uploads in external object storage if/when uploads exist. The current MVP has no uploaded media implementation.
- DSQL data is external to the VM. Separate the dev/prod database endpoints, users/roles and access policies. Define backup retention and complete a restore drill with explicit RPO/RTO before production.
- Lightsail's standard IAM guidance describes EC2 instance profiles for EC2 apps; Lightsail does not expose that EC2 attachment workflow. Do not assume the app can obtain an instance role automatically. Select and validate a short-lived credential/role-assumption design before using DSQL from the VM; never bake static access keys into an image.
- Run Grafana Cloud Free for hosted dashboards/alerts and a lightweight Alloy or OpenTelemetry Collector per environment. Validate combined dev/prod quotas, account region/data residency, labels/cardinality, pipeline failure/no-data alerts, and a secure browser telemetry relay with no private ingestion token in browser code.
- Hosted alert delivery must reach an authenticated receiver that persists and deduplicates incidents before queueing any agent work. A webhook by itself does not launch an agent. Agent hosting and model usage are separate, unpriced follow-up work.
- Build and deploy the same immutable image from dev to prod. Identify the registry, GitHub Actions minutes, deploy credentials and rollback path before implementation; current estimate assumes existing CI capacity and does not assert that registry/build cost is zero.

## Sources checked 2026-10-18

- [AWS Lightsail Linux instance bundle prices](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-bundles.html), [snapshot pricing](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-faq-snapshots.html), and [Lightsail IAM guidance](https://docs.aws.amazon.com/lightsail/latest/userguide/security_iam.html).
- [AWS Aurora DSQL pricing](https://aws.amazon.com/rds/aurora/dsql/pricing/), [Sydney region availability](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/what-is-aurora-dsql.html), [AWS DSQL IAM authentication](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/authentication-authorization.html), [SQL compatibility](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with.html), and [concurrency behavior](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with-concurrency-control.html).
- [AWS DSQL SQLAlchemy adapter](https://github.com/awslabs/aurora-dsql-orms/tree/main/python/sqlalchemy), [DigitalOcean App Platform pricing](https://docs.digitalocean.com/products/app-platform/details/pricing/), [DigitalOcean PostgreSQL pricing](https://docs.digitalocean.com/products/databases/postgresql/details/pricing/), and [Scale to Zero documentation](https://docs.digitalocean.com/products/app-platform/how-to/scale-app/).
- [Fly Machine pricing](https://fly.io/docs/about/pricing/), [Fly Managed Postgres pricing](https://fly.io/mpg), and [Grafana Cloud Free plan](https://grafana.com/get/).
