# AWS deployment and full-stack release status

The tracked `infra/terraform/` directory is the sole Terraform root and uses the existing `pawlocal/terraform.tfstate` backend key. It preserves the existing root-state production frontend bucket, CloudFront distribution, and DNS record resource addresses, and calls `fullstack/` as a child module with no backend. The child module creates development frontend resources only. Production frontend publishing uses the root's existing bucket, distribution, and deploy-role outputs. The API has its own `api.pawlocal.<domain>` hostname and Terraform-managed Route 53 A record to the API Lightsail static IP; it does not use the frontend CloudFront distribution. No duplicate production frontend bucket, distribution, or alias is declared.

The owner selected Lightsail + Aurora DSQL and approved the MVP budget. Terraform manages app infrastructure and IAM users; the owner authorized one-off CLI creation of each DSQL access key only after Terraform creates its IAM user. Key values are held in their matching GitHub environment secrets and the requested protected Desktop TXT file, then delivered over SSH stdin to a root-owned runtime credential file on the matching Lightsail instance. They never enter Terraform inputs, outputs, state, plans, repository files, images, user data, or logs. The branch also adds environment-specific Cognito pools/clients to Terraform because cloud builds and API token validation require them. No cloud resources or DSQL credentials have been provisioned. Backup, HA, RPO/RTO, restore, recovery, and rollback are deferred to [Issue #44](https://github.com/alanlima/pawlocal/issues/44). See the [hosting proposal](stage4-hosting-options.md) for cost and compatibility gates.

Issue #43's policy is PR CI, automatic development deployment after successful main CI, and separate manual production promotion of the same backend digest after development verification. The plan restricts SSH to the current workstation's observed IPv4 `/32` (`115.186.228.28/32`), so a standard GitHub-hosted runner cannot reach either Lightsail API. The deploy jobs therefore run only when the matching environment variable `PAWLOCAL_DEPLOY_MODE=github-actions` is configured. Leave it unset for the initial local development deployment; do not configure it until a fixed-egress runner is in place. The local procedure below is for development verification only; production remains gated on a GitHub-recognized dev deployment and fixed-egress promotion runner. Terraform changes are under review and unapplied; no keys, deployments, or seed have been performed. Telemetry stays disabled for the initial release; enablement is deferred to [Issue #59](https://github.com/alanlima/pawlocal/issues/59). Backup, HA, RPO/RTO, restore, recovery, and rollback are outside MVP scope and deferred to [Issue #44](https://github.com/alanlima/pawlocal/issues/44).

## Architecture

The build output in `frontend/dist/` is stored in a private S3 bucket. CloudFront serves it through Origin Access Control (OAC), redirects HTTP requests to HTTPS, and returns `index.html` for SPA paths. Route 53 A and AAAA alias records map `pawlocal.<configured-domain>` to the current distribution. For the proposed separate dev/prod sites, the naming convention is `pawlocal-dev.<domain>` and `pawlocal.<domain>` respectively; this convention does not configure or authorize DNS, certificates, or distributions. The existing ACM wildcard certificate is supplied by ARN; ACM certificates used by CloudFront must be in `us-east-1`. Terraform does not request or validate a new certificate.

The root domain, frontend certificate ARN, repository identity, immutable GitHub owner/repository IDs, AWS region, restricted SSH CIDRs, and deployment public keys are supplied as local Terraform inputs. The API subdomain certificate is issued by Caddy; Terraform manages its DNS A record to the Lightsail static IP. Do not commit real `terraform.tfvars`, backend configuration, account identifiers, credentials, or other account-specific values. The tracked `terraform.tfvars.example` contains placeholders only. The backend bucket name is supplied to `terraform init` from the operator's local environment; the state key remains `pawlocal/terraform.tfstate`.

Existing production frontend resources continue to receive the root provider tags (`component=frontend`, `workload=static-site`). Child-module application resources use a separate provider alias with `component=fullstack-mvp`, `workload=application`, and `environment=mvp`; tags do not change the existing production resource addresses or state ownership. Some AWS resource types do not expose tag attributes.

## Prerequisites

- Terraform 1.10 or later and AWS credentials with permission for a reviewed Terraform plan/apply against the existing root state.
- The existing, versioned and encrypted S3 bucket reserved for Terraform state. Supply its name locally; the backend key is `pawlocal/terraform.tfstate` in `ap-southeast-2`. S3 lock files are enabled.
- A public Route 53 hosted zone, an issued ACM certificate in `us-east-1` covering `pawlocal.<configured-domain>` and `pawlocal-dev.<configured-domain>`, owner-selected restricted SSH CIDRs, and review of the integrated plan before any apply.
- The account's GitHub Actions OIDC provider and scoped deployment roles. By default, Terraform reads the existing account-wide provider. Do not switch ownership of that provider without a separate reviewed decision. Publishing roles are limited to static object writes and CloudFront invalidation; they do not manage infrastructure resources or DNS.
- If DSQL audit-event capture is enabled, an owner-selected audit bucket name and positive retention period are required. Capture defaults off until those choices are made. The alert email destination is also unset.

## Initialize and review Terraform

From the repository root in PowerShell:

```powershell
Copy-Item infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
# Edit the ignored local file with the domain, certificate ARN, and repository.
$env:PAWLOCAL_TF_STATE_BUCKET = "<existing Terraform state bucket name>"
Set-Location infra/terraform
terraform init `
  -backend-config="bucket=$env:PAWLOCAL_TF_STATE_BUCKET" `
  -backend-config="key=pawlocal/terraform.tfstate" `
  -backend-config="region=ap-southeast-2" `
  -backend-config="encrypt=true" `
  -backend-config="use_lockfile=true"
terraform fmt -check
terraform validate
terraform plan -out=pawlocal.tfplan
```

The plan must use the existing root backend and must retain the current production resources at their existing Terraform addresses. Verify the production CloudFront distribution remains frontend-only and that the API Route 53 record targets its Lightsail static IP. Reject any plan that proposes replacing or destroying the existing production bucket, distribution, DNS aliases, or state backend. Do not move, import, remove, or manually edit state bindings. Apply is outside this implementation task and requires a separate review of the exact integrated plan and owner authorization.

## Existing static-site configuration

The following values belong to the existing static-site workflow only; they are not inputs to the Issue #43 full-stack adapter:

| Variable | Value |
| --- | --- |
| `AWS_ROLE_ARN` | Terraform output `github_deploy_role_arn` |
| `AWS_REGION` | Terraform input `aws_region` |
| `FRONTEND_BUCKET` | Terraform output `site_bucket_name` |
| `FRONTEND_DISTRIBUTION_ID` | Terraform output `cloudfront_distribution_id` |

The legacy static-site workflow is retained separately from the full-stack flow and is not evidence that the full application has been deployed. Do not use it as the Issue #43 release path.

The workflows use separate development and production GitHub environments, validate dev health before marking deployment successful, and require production promotion to reference a verified commit and release manifest. They reuse the immutable backend image digest and build the frontend separately for each environment from the selected commit because Vite embeds public Cognito settings. No client secret is embedded. Production promotions are serialized without canceling an active deployment. Release/deployment records capture commit, image digest, frontend artifact digest, selected database provider, migration runner and identifier, telemetry state, public endpoint health, and a public `GET /api/v1/places` database-query smoke. That query verifies the route returns a valid place-page response and does not claim persistence. An authenticated create-then-read persistence journey remains a manual live-development gate until a Cognito test identity is available. Before configuring publishing variables, obtain values from the integrated Terraform root output `terraform output -json environment_targets`: development uses the child-module targets; production uses the existing root-state production bucket, distribution, and deploy role. The workflows do not run Terraform or alter infrastructure. The first release is deployed locally through the same reviewed adapter because the approved SSH allowlist is the operator workstation `/32`; no deploy-job setting should enable GitHub-hosted deployment until fixed egress is configured.

## Initial local deployment procedure

Use this path only from the workstation whose public address matches the Terraform SSH CIDR. It does not change AWS infrastructure; Terraform remains the sole owner of infrastructure. Required local tools are Git Bash, Docker, AWS CLI authenticated to the account, GitHub CLI authenticated to this repository, Terraform, Node.js, Python, `curl`, and `jq`. The deployment adapter requires a full release manifest, frontend archive, local AWS publishing permission for the target bucket/distribution, GitHub Container Registry read access, the target SSH private key, a verified `known_hosts` entry, and the environment's DSQL access-key variables. Do not enable telemetry.

1. Apply only the independently reviewed plan from the existing root state. After Terraform completes, capture the public target map without sharing sensitive plan output:

   ```powershell
   terraform -chdir=infra/terraform output -json environment_targets | Set-Content -Encoding utf8 $env:TEMP\pawlocal-targets.json
   $targets = Get-Content -Raw $env:TEMP\pawlocal-targets.json | ConvertFrom-Json
   ```

2. In AWS Console → Lightsail, open the new API instance's browser SSH session. Run `sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` there and note the SHA256 fingerprint. From the workstation, run `ssh-keyscan -t ed25519 <static-ip>` and compare its fingerprint with the console value using `ssh-keygen -lf -`. Only use the matching key line as `PAWLOCAL_DEPLOY_KNOWN_HOSTS`; do not accept an unverified first connection.

3. After the successful `main` full-stack workflow finishes its CI and image-publish jobs, download its `pawlocal-backend-release` artifact with `gh run download <run-id> --name pawlocal-backend-release --dir release`. This contains the immutable backend image digest and migration identifiers. Do not rebuild the backend image.

4. In Git Bash, choose `environment=development` or `production`, read the corresponding public settings from the Terraform output, and build/package the frontend and complete manifest. This example builds development; replace `development` with `production` for the manual promotion:

   ```bash
   environment=development
   target="$(terraform -chdir=infra/terraform output -json environment_targets | jq -c ".${environment}")"
   export VITE_RELEASE_ENV="$environment" VITE_USE_MOCK_BACKEND=false VITE_TELEMETRY_ENABLED=false
   export VITE_API_BASE_URL="https://$(jq -r .api_hostname <<<"$target")/api/v1"
   export VITE_COGNITO_DOMAIN="$(jq -r .cognito_domain <<<"$target")"
   export VITE_COGNITO_CLIENT_ID="$(jq -r .cognito_client_id <<<"$target")"
   export VITE_COGNITO_REDIRECT_URI="$(jq -r .cognito_redirect_uri <<<"$target")"
   export VITE_COGNITO_LOGOUT_URI="$(jq -r .cognito_logout_uri <<<"$target")"
   export VITE_COGNITO_SCOPES="$(jq -r .cognito_scopes <<<"$target")"
   export VITE_APP_COMMIT="$(jq -r .commit release/backend-release.json)"
   (cd frontend && npm ci && npm run build)
   mkdir -p release
   tar --sort=name --mtime='@0' --owner=0 --group=0 --numeric-owner \
     -czf "release/frontend-${environment}.tar.gz" -C frontend/dist .
   frontend_digest="sha256:$(sha256sum "release/frontend-${environment}.tar.gz" | cut -d ' ' -f1)"
   jq --arg env "$environment" --arg digest "$frontend_digest" \
     '. + {frontend:{environment:$env,artifact_digest:$digest}}' \
     release/backend-release.json > release/release-manifest.json
   python ops/validate-release-metadata.py --manifest release/release-manifest.json
   ```

5. Populate and export the target settings in the same Git Bash session. Before setting `PAWLOCAL_DEPLOY_KNOWN_HOSTS`, obtain the SSH host-key fingerprint in the Lightsail browser console and compare it with the `ssh-keyscan` result for the target's `.static_ip` using `ssh-keygen -lf - -E sha256`. Set the SSH private-key variable from the generated local keypair (`dev` or `prod` in the protected plan-input directory). Read the matching DSQL access-key ID and secret key into shell variables with `read -rs`; do not place values in commands, files other than the specifically authorized Desktop copy, or logs.

   ```bash
   export PAWLOCAL_DEPLOY_HOST="$(jq -r .static_ip <<<"$target")"
   export PAWLOCAL_FRONTEND_BUCKET="$(jq -r .frontend_bucket <<<"$target")"
   export PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID="$(jq -r .distribution_id <<<"$target")"
   export PAWLOCAL_DSQL_ENDPOINT="$(jq -r .dsql_endpoint <<<"$target")"
   export PAWLOCAL_DSQL_DATABASE_ROLE="$(jq -r .dsql_database_role <<<"$target")"
   export PAWLOCAL_COGNITO_ISSUER="$(jq -r .cognito_issuer <<<"$target")"
   export PAWLOCAL_COGNITO_APP_CLIENT_ID="$(jq -r .cognito_client_id <<<"$target")"
   export PAWLOCAL_PUBLIC_BASE_URL="$(jq -r .frontend_url <<<"$target")"
   export PAWLOCAL_API_HEALTH_URL="$(jq -r .api_health_url <<<"$target")"
   export PAWLOCAL_DEPLOY_SSH_PRIVATE_KEY="$(<"$PLAN_INPUT_DIR/$([[ "$environment" == development ]] && echo dev || echo prod)")"
   export PAWLOCAL_DEPLOY_KNOWN_HOSTS="$(<"$VERIFIED_KNOWN_HOSTS_FILE")"
   read -rsp 'DSQL access-key ID: ' PAWLOCAL_DSQL_ACCESS_KEY_ID; echo; export PAWLOCAL_DSQL_ACCESS_KEY_ID
   read -rsp 'DSQL secret access key: ' PAWLOCAL_DSQL_SECRET_ACCESS_KEY; echo; export PAWLOCAL_DSQL_SECRET_ACCESS_KEY
   export GITHUB_TOKEN="$(gh auth token)" GITHUB_ACTOR="$(gh api user --jq .login)"
   export AWS_REGION=ap-southeast-2 PAWLOCAL_DATABASE_PROVIDER=aurora_dsql
   export PAWLOCAL_DEPLOY_ADAPTER_PATH=ops/deployment-adapters/lightsail-dsql.sh
   ```

   Set `PLAN_INPUT_DIR` to the protected directory containing the generated SSH keypairs. Save the verified SSH key line in a file referenced by `VERIFIED_KNOWN_HOSTS_FILE`; the file must contain the exact target IP and the fingerprint-verified key. Confirm `aws sts get-caller-identity` succeeds before publishing to S3/CloudFront.

   Set `GITHUB_TOKEN` from `gh auth token`, `GITHUB_ACTOR` from `gh api user --jq .login`, `AWS_REGION=ap-southeast-2`, `PAWLOCAL_DATABASE_PROVIDER=aurora_dsql`, and `PAWLOCAL_DEPLOY_ADAPTER_PATH=ops/deployment-adapters/lightsail-dsql.sh`. Then run:

   ```bash
   bash ops/run-deployment-adapter.sh deploy --environment development --manifest release/release-manifest.json --frontend-archive release/frontend-development.tar.gz
   bash ops/run-deployment-adapter.sh verify --environment development --manifest release/release-manifest.json --evidence release/development-verification.json
   ```

   Check the adapter's verified development evidence. Do not repeat this local procedure for production; production promotion stays gated until the protected workflow can reach Lightsail through fixed egress.

6. Review and record the commit, image digest, frontend archive digest, DSQL migration, public frontend/API health, and `/api/v1/places` query evidence. Keep the local secrets in environment variables for the adapter run; never add them to manifests, command arguments, state, repository files, or logs.

This local process does not create a GitHub-hosted successful deployment record. The protected production-promotion workflow therefore remains unavailable until fixed egress is configured for both deploy jobs. Do not promote production manually around that gate without an explicit owner decision changing the release procedure. Do not claim development is live until the adapter's verification passes against public endpoints.

### Access-key rotation

Rotate each environment's DSQL key every 90 days. Use the one-off CLI exception to create a replacement key for the existing Terraform-managed IAM user while the current key remains active. Update that environment's GitHub secrets and protected Desktop credential file, deploy through the approved adapter so the host receives the replacement, and verify the environment's public API and DSQL query. Then deactivate and delete the old key through the CLI, confirm the replacement is the only active key, and record the rotation date without recording key values. Never place access-key secret material in Terraform state or plans. Configure and verify the CloudTrail authentication alert before issuing the first application key; its destination and event-retention choices remain owner inputs.

## Full-stack release operation and current blockers

A fresh existing-state plan reports 40 creates, 4 in-place updates, and no destroys. An independent plan review confirms production frontend ownership remains at its existing Terraform addresses and the DSQL access key is absent from plan/state. Apply, access-key creation, deployment, and seed have not yet occurred. Telemetry is off, with enablement deferred to Issue #59; Issue #44 owns deferred backup/HA/recovery/rollback review after MVP cloud deployment.

### Intended production promotion

1. Open GitHub → **Actions** → **Deploy Production** → **Run workflow**.
2. Select the approved `main` ref and enter/select the release commit SHA that has already passed required CI and completed development deployment plus health/smoke verification.
3. Let the workflow validate that the SHA belongs to permitted `main` history, required CI passed, and the same release was successfully verified in development. A free-text SHA alone is not sufficient evidence.
4. Run preflight checks against production configuration and health endpoints. Apply only reviewed DSQL-compatible database migrations when needed. Use expand/contract migrations that remain backward-compatible with the currently deployed application throughout rollout; do not rename/drop columns or tighten constraints until all deployed code versions no longer depend on the old shape. Database recovery and rollback procedures are deferred to Issue #44; stop promotion and escalate if a migration or deployment fails.
5. Deploy the exact backend image digest used in development and the environment-specific frontend built from the same commit. Do not rebuild the backend image for production. Keep production concurrency serialized and do not cancel an active deployment.
6. Run health checks and end-to-end smoke checks against the public production endpoints and confirm the user journey works with production data/API configuration. If checks fail, stop promotion and record the failing checks and deployed identifiers. Do not claim an MVP recovery or rollback guarantee; the recovery review is deferred to Issue #44. Record the commit SHA, backend image digest, frontend artifact/version, selected database provider and migration runner/identifier, health/smoke results, and deployment outcome.

Backup, HA, RPO/RTO, restore, recovery, and rollback procedures are not part of this MVP workflow. They are deferred for review to Issue #44 after the MVP is deployed to cloud.

## Legacy static-site Terraform notes

The following operational notes apply only if the separate static-site Terraform stack is intentionally used. They do not verify or operate the Issue #43 full-stack release:

- Visit the Terraform `site_url` output over HTTPS after CloudFront reports `Deployed` and DNS has propagated.
- Reload a nested place URL directly to verify SPA fallback.
- Inspect Actions logs for any static-site publish activity. Do not print credentials or Terraform variable values in logs.

The legacy static-site workflow is not the MVP full-stack deployment path. Do not use its mock-backed demo behavior as production validation. The current Issue #43 workflows use environment-specific builds with mock mode false and telemetry disabled. API requests target the separate environment API endpoint (`https://api-dev.<domain>/api/v1` or `https://api.<domain>/api/v1`), not a frontend CloudFront `/api/*` behavior. The API allows browser requests only from its matching frontend origin.

## Cost and cleanup

### Estimate (USD/month)

The draft plan creates one private S3 site bucket, one CloudFront distribution, two Route 53 aliases in the existing public hosted zone, and an IAM deploy role. It uses the account's existing OIDC provider by default; creating the provider is optional and controlled by `manage_github_oidc_provider`. There is no always-on compute, NAT gateway, new hosted zone, WAF configuration, logging, or new certificate.

| Scenario | Estimated incremental monthly cost | Assumptions |
| --- | ---: | --- |
| Idle | About $0.00001 | One 208 KB build stored in S3 Standard in Sydney; the backend state bucket and Route 53 zone already exist. |
| Light traffic | About $0.005 | 10,000 S3 GETs (a conservative cache-miss estimate), 3 S3 PUTs, and the same 208 KB bundle. CloudFront viewer traffic remains within the account's shared free allowance of 1 TB and 10 million HTTP(S) requests/month. |

The S3 estimate uses the current AWS Price List for Asia Pacific (Sydney): $0.025/GB-month for first-tier Standard storage, $0.00000044 per GET, and $0.0000055 per PUT. The current CloudFront pay-as-you-go page lists 1 TB of data transfer and 10 million HTTP(S) requests per month in its always-free tier. Those allowances are shared across the AWS account, so other distributions may consume them. If exceeded, CloudFront charges vary by viewer geography; Australia/New Zealand is currently $0.114/GB for the next 9 TB and HTTPS requests are $0.0125 per 10,000. Route 53 alias A/AAAA queries to CloudFront do not incur query charges; the existing hosted-zone charge continues independently. The estimate excludes taxes, changes in AWS prices, and usage outside these assumptions.

Sources: [CloudFront pay-as-you-go pricing](https://aws.amazon.com/cloudfront/pricing/pay-as-you-go/), [S3 pricing](https://aws.amazon.com/s3/pricing/), [Route 53 pricing](https://aws.amazon.com/route53/pricing/). Re-check current prices and account-level usage before apply; the project already has a monthly AWS budget, and a budget limit does not prevent charges.

Do not run `terraform destroy` against this shared root: it also owns the existing production frontend and DNS. Any later teardown must use a separately reviewed Terraform change that explicitly preserves those production resources and the existing state backend. Do not move, import, remove, or manually edit state bindings.
