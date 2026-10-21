[CmdletBinding()]
param(
    [string]$BootstrapTerraformRoot = (Join-Path $PSScriptRoot '..\infra\terraform\iam-bootstrap'),
    [string]$DevelopmentTerraformRoot = (Join-Path $PSScriptRoot '..\infra\terraform\environments\development'),
    [string]$PythonPath = (Join-Path $PSScriptRoot '..\backend\.venv\Scripts\python.exe'),
    [string]$TerraformStateBucketName = $env:TF_VAR_terraform_state_bucket_name,
    [string]$TerraformCommand = 'terraform',
    [string]$AwsCommand = 'aws'
)

$ErrorActionPreference = 'Stop'
$BootstrapTerraformRoot = (Resolve-Path $BootstrapTerraformRoot).Path
$DevelopmentTerraformRoot = (Resolve-Path $DevelopmentTerraformRoot).Path
$python = (Resolve-Path $PythonPath).Path
$terraform = (Get-Command $TerraformCommand -ErrorAction Stop).Path
$aws = (Get-Command $AwsCommand -ErrorAction Stop).Path
$approvedRegion = 'ap-southeast-2'

if ($TerraformStateBucketName -notmatch '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$' -or
    $TerraformStateBucketName.Contains('..') -or
    $TerraformStateBucketName.Contains('.-') -or
    $TerraformStateBucketName.Contains('-.')) {
    throw 'The expected Terraform state bucket name is missing or invalid.'
}
if (-not [string]::IsNullOrWhiteSpace($env:TF_DATA_DIR)) {
    throw 'TF_DATA_DIR must be unset so the reviewed Terraform roots own their backend metadata.'
}

function Initialize-And-ValidateTerraformBackend {
    param(
        [string]$Root,
        [string]$StateKey,
        [string]$StateLabel
    )

    Push-Location $Root
    try {
        $initOutput = & $terraform init `
            -input=false `
            -reconfigure `
            -no-color `
            "-backend-config=bucket=$TerraformStateBucketName" `
            "-backend-config=key=$StateKey" `
            "-backend-config=region=$approvedRegion" `
            '-backend-config=encrypt=true' `
            '-backend-config=use_lockfile=true' 2>&1
        $initStatus = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($initStatus -ne 0) {
        throw "Could not initialize the approved $StateLabel Terraform backend."
    }

    $metadataPath = Join-Path (Join-Path $Root '.terraform') 'terraform.tfstate'
    if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
        throw "The $StateLabel Terraform backend metadata is missing."
    }
    try {
        $metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json -ErrorAction Stop
    } catch {
        throw "The $StateLabel Terraform backend metadata is invalid."
    }

    $config = $metadata.backend.config
    if ($metadata.backend.type -ne 's3' -or
        $config.bucket -ne $TerraformStateBucketName -or
        $config.key -ne $StateKey -or
        $config.region -ne $approvedRegion -or
        $config.encrypt -ne $true -or
        $config.use_lockfile -ne $true) {
        throw "The $StateLabel Terraform backend does not match the approved state identity."
    }

    Push-Location $Root
    try {
        $workspace = & $terraform workspace show 2>$null | Out-String
        $workspaceStatus = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($workspaceStatus -ne 0 -or $workspace.Trim() -ne 'default') {
        throw "The $StateLabel Terraform backend is not using the approved default workspace."
    }
}

function Read-TerraformJsonOutput {
    param(
        [string]$Root,
        [string]$OutputName,
        [string]$StateLabel
    )

    Push-Location $Root
    try {
        $raw = & $terraform output -json $OutputName 2>$null | Out-String
        $status = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($status -ne 0 -or [string]::IsNullOrWhiteSpace($raw)) {
        throw "Could not read required output from the $StateLabel Terraform state."
    }
    try {
        return $raw | ConvertFrom-Json -ErrorAction Stop
    } catch {
        throw "Required output from the $StateLabel Terraform state is invalid."
    }
}

function Require-OutputString {
    param(
        [object]$Value,
        [string]$Name
    )

    if ($Value -isnot [string] -or [string]::IsNullOrWhiteSpace($Value)) {
        throw "Required Terraform output $Name is missing or invalid."
    }
    return [string]$Value
}

Initialize-And-ValidateTerraformBackend `
    -Root $BootstrapTerraformRoot `
    -StateKey 'pawlocal/iam-bootstrap/terraform.tfstate' `
    -StateLabel 'IAM bootstrap'
Initialize-And-ValidateTerraformBackend `
    -Root $DevelopmentTerraformRoot `
    -StateKey 'pawlocal/development/terraform.tfstate' `
    -StateLabel 'development environment'

$identityRoles = Read-TerraformJsonOutput `
    -Root $BootstrapTerraformRoot `
    -OutputName 'identity_app_role_arns' `
    -StateLabel 'IAM bootstrap'
$bootstrapAccountId = Require-OutputString `
    (Read-TerraformJsonOutput `
        -Root $BootstrapTerraformRoot `
        -OutputName 'aws_account_id' `
        -StateLabel 'IAM bootstrap') `
    'aws_account_id'
$development = Read-TerraformJsonOutput `
    -Root $DevelopmentTerraformRoot `
    -OutputName 'environment_targets' `
    -StateLabel 'development environment'

$environment = Require-OutputString $development.environment 'environment_targets.environment'
$developmentAccountId = Require-OutputString $development.aws_account_id 'environment_targets.aws_account_id'
$developmentRegion = Require-OutputString $development.aws_region 'environment_targets.aws_region'
$runtimeRoleArn = Require-OutputString $identityRoles.development_runtime 'identity_app_role_arns.development_runtime'
$configuredRuntimeRoleArn = Require-OutputString $development.runtime_role_arn 'environment_targets.runtime_role_arn'
$clusterArn = Require-OutputString $development.dsql_cluster_arn 'environment_targets.dsql_cluster_arn'
$endpoint = Require-OutputString $development.dsql_endpoint 'environment_targets.dsql_endpoint'
$databaseRole = Require-OutputString $development.dsql_database_role 'environment_targets.dsql_database_role'
$legacyPrincipalArn = Require-OutputString $development.lightsail_principal_arn 'environment_targets.lightsail_principal_arn'

if ($environment -ne 'development') {
    throw 'The selected environment state is not development.'
}
if ($bootstrapAccountId -notmatch '^\d{12}$' -or $developmentAccountId -ne $bootstrapAccountId) {
    throw 'Bootstrap and development Terraform states do not identify the same AWS account.'
}
if ($developmentRegion -ne $approvedRegion) {
    throw 'The development Terraform state does not identify the approved AWS region.'
}
if ($runtimeRoleArn -notmatch '^arn:(?<partition>aws(?:-us-gov|-cn)?):iam::(?<account>\d{12}):role/pawlocal-development-dsql-runtime$') {
    throw 'The bootstrap runtime role is not the exact development runtime role.'
}
$partition = $Matches.partition
$managedAccountId = $Matches.account
if ($managedAccountId -ne $bootstrapAccountId -or $configuredRuntimeRoleArn -ne $runtimeRoleArn) {
    throw 'The bootstrap and development runtime-role handoff does not match.'
}
$partitionPattern = [regex]::Escape($partition)
$accountPattern = [regex]::Escape($managedAccountId)
if ($clusterArn -notmatch "^arn:${partitionPattern}:dsql:(?<region>[a-z0-9-]+):${accountPattern}:cluster/(?<cluster>[a-z0-9]+)$") {
    throw 'The development DSQL cluster output is invalid or belongs to another account.'
}
$clusterRegion = $Matches.region
$clusterIdentifier = $Matches.cluster
if ($developmentRegion -ne $clusterRegion -or $endpoint -ne "${clusterIdentifier}.dsql.${clusterRegion}.on.aws") {
    throw 'The development DSQL endpoint, region, and cluster outputs do not match.'
}
if ($databaseRole -ne 'pawlocal_development_app') {
    throw 'The development database role output is not the approved application role.'
}
if ($legacyPrincipalArn -notmatch "^arn:${partitionPattern}:iam::\d{12}:(?:role|user)/(?:[A-Za-z0-9+=,.@_-]+/)*[A-Za-z0-9+=,.@_-]+$") {
    throw 'The development Lightsail principal output is invalid.'
}

$accountId = & $aws sts get-caller-identity --query Account --output text 2>$null | Out-String
$accountStatus = $LASTEXITCODE
$accountId = $accountId.Trim()
if ($accountStatus -ne 0 -or $accountId -notmatch '^\d{12}$') {
    throw 'Could not identify the active AWS operator account.'
}
if ($accountId -ne $managedAccountId) {
    throw 'Active AWS operator account does not match the Terraform-managed PawLocal account.'
}
$legacyUserArn = "arn:${partition}:iam::${managedAccountId}:user/pawlocal/pawlocal-development-dsql-app"

Push-Location (Join-Path $PSScriptRoot '..\backend')
try {
    $bootstrapOutput = & $python -m pawlocal.dsql_role_bootstrap `
        --endpoint $endpoint `
        --region $developmentRegion `
        --database-role $databaseRole `
        --iam-principal-arn $runtimeRoleArn `
        --legacy-iam-user-arn $legacyUserArn `
        --legacy-iam-principal-arn $legacyPrincipalArn 2>&1
    $bootstrapStatus = $LASTEXITCODE
    if ($bootstrapStatus -ne 0) { throw 'Development DSQL application-role bootstrap failed.' }
} finally {
    Pop-Location
}

Write-Output 'Development DSQL application-role bootstrap completed.'
