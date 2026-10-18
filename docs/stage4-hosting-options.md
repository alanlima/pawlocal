# Stage 4 hosting and cost proposal

**Status:** Proposal for human review; no hosting choice or spending is approved.
**Pricing checked:** 2026-10-18. Prices are USD before tax.

## Workload assumptions

- Two separate, always-available environments: development and production.
- Each environment handles about 10,000 API requests and 10 GB of API egress per month, with 1 GB of PostgreSQL data.
- The frontend remains on the existing static AWS S3/CloudFront deployment. Its incremental estimate is tracked separately in [Issue #25](https://github.com/alanlima/pawlocal/issues/25).
- GitHub Actions builds and deploys application images. New registry charges, domain costs, taxes, provider credits, and account-specific discounts are excluded.
- The managed-platform options use one 512 MiB OpenTelemetry Collector per environment and one shared Grafana Cloud Free account. This assumes usage stays below the listed free allowances and does not price a secure browser telemetry relay.
- Costs are illustrative monthly list-price estimates. API memory, telemetry volume/cardinality, database recovery requirements, and actual data transfer have not been measured.

## Estimated monthly costs

| Option | Development | Production | Both environments | Operating model |
| --- | ---: | ---: | ---: | --- |
| DigitalOcean App Platform + Managed PostgreSQL + Grafana Cloud | $17.00 | $30.15 | **$47.15** | Low-operations managed app and database; fixed services remain billed while idle. |
| Fly Machines + Managed Postgres + Grafana Cloud | $42.97 with API stopped; $47.06 running | $42.97 with API stopped; $51.45 running | **$85.94 idle**; about **$99.31** with both APIs running full time and 20 GB total egress | API machines can stop/start; managed database and collectors remain provisioned. |
| AWS Lightsail Linux with the existing Compose stack | $24 compute | $44 compute | **About $71** including an illustrative $3 for 60 GB of snapshots | Self-managed API, PostgreSQL, and current observability stack on one VM per environment. |

### DigitalOcean

- Development: $5 App Platform API (512 MiB), $5 collector (512 MiB), and $7 development PostgreSQL database (512 MiB), totaling $17.
- Production: $10 API (1 GiB), $5 collector (512 MiB), and $15.15 for the smallest listed standard managed PostgreSQL node (1 GiB RAM, minimum 10 GiB disk), totaling $30.15.
- The estimate assumes 10 GB of egress per environment is within the pooled app allowance. The production database is a single node. A two-node HA database at the 2 GiB tier is about $60.90/month for the database alone, raising the combined two-environment estimate to about $92.90/month.
- App Platform lists Sydney availability. App services do not scale to zero. Managed PostgreSQL backups and restore-to-new-cluster behavior need a recovery drill; development databases have a separate backup caveat.

### Fly.io

- Development with the API stopped: $38 Managed Postgres, $0.28 for 1 GB database storage, $4.39 for the always-on collector, and $0.30 for 2 GB stopped-machine root storage, totaling about $42.97. With the 512 MiB API running for the full month, the estimate is $47.06.
- Production with the API stopped has the same $42.97 baseline. With the 1 GiB API running for the full month, the estimate is $51.45.
- With both APIs running for the full 730-hour month, the API compute adds $13.17. Assuming 20 GB total egress at $0.04/GB adds $0.80, for about $99.31 across both environments.
- Managed Postgres includes high availability, automated backups, and connection pooling. Validate database operational responsibilities and maintenance controls. The managed database remains a fixed cost even while API machines stop.

### AWS Lightsail

- Development: a $24 Linux VM (4 GB RAM) sized for the current Compose stack.
- Production: a $44 Linux VM (8 GB RAM) sized for the same stack.
- Illustrative snapshot storage is 60 GB total at $0.05/GB-month ($3). This does not include an off-host PostgreSQL backup target, request charges, or external monitoring.
- The existing Compose Prometheus/Loki/Tempo/Grafana stack can remain, but a VM failure also removes local monitoring. Both environments are single-VM failure domains and require more patching and backup operations.

## Comparison and current proposal

DigitalOcean is the lowest-operations candidate if a single-node production database meets the recovery and availability requirements. If production database HA is required, its monthly estimate nearly doubles to about $92.90 across both environments. Fly has a higher fixed database baseline but includes database HA and backups, and its API compute can stop when unused. Lightsail has a low predictable VM price and preserves the current Compose stack, with greater self-management and recovery responsibility.

No option is selected. Before approving one, decide whether production needs database HA, set recovery point/time objectives, validate API memory and telemetry volume, and review a provider-calculator estimate plus a tested backup/restore and user-journey alert path. DRAFT-002 remains open until those choices and an explicit cost envelope are approved.

## Telemetry and unknown costs

Grafana Cloud Free currently lists up to 10,000 metric series, 50 GB each of logs and traces, and 14-day retention. The estimate assumes both managed-platform environments fit within those shared account limits. Confirm the Australia region, user/incident-management quotas, data residency, browser telemetry relay design, cardinality, and retention before relying on it for production alerts.

For Lightsail, persistent Prometheus/Loki/Tempo storage, off-host database backups, backup restore time, and monitoring from outside the VM are unpriced. Across all options, taxes/AUD conversion, measured resource usage, availability targets, deployment registry charges, and support-plan costs may change totals.

## Official pricing and operations sources

- [DigitalOcean App Platform pricing](https://docs.digitalocean.com/products/app-platform/details/pricing/) and [regional availability](https://docs.digitalocean.com/products/app-platform/details/availability/).
- [DigitalOcean Managed PostgreSQL pricing](https://www.digitalocean.com/pricing/managed-databases), [PostgreSQL regions](https://docs.digitalocean.com/products/databases/postgresql/details/availability/), and [restoring from backups](https://docs.digitalocean.com/products/databases/postgresql/how-to/restore-from-backups/).
- [Fly.io pricing](https://fly.io/pricing/), [regions](https://docs.fly.io/reference/regions), [Managed Postgres features](https://fly.io/docs/mpg/), and [machine autostop/autostart](https://fly.io/docs/reference/fly-proxy-autostop-autostart/).
- [AWS Lightsail pricing](https://aws.amazon.com/lightsail/pricing/), [bundle details](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-bundles.html), and [snapshot pricing](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-faq-snapshots.html).
- [Grafana Cloud plans](https://grafana.com/get/) and [regional availability](https://grafana.com/docs/grafana-cloud/platform/security-and-account-management/account-management/regional-availability/).
