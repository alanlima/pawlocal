[CmdletBinding()]
param(
    [string]$TerraformRoot = (Join-Path $PSScriptRoot '..\infra\terraform'),
    [string]$PythonPath = (Join-Path $PSScriptRoot '..\backend\.venv\Scripts\python.exe')
)

$ErrorActionPreference = 'Stop'
$terraformRoot = (Resolve-Path $TerraformRoot).Path
$python = (Resolve-Path $PythonPath).Path

Push-Location $terraformRoot
try {
    $targetsJson = terraform output -json environment_targets
    if ($LASTEXITCODE -ne 0) { throw 'Could not read environment_targets from Terraform state.' }
    $targets = $targetsJson | ConvertFrom-Json
} finally {
    Pop-Location
}

$development = $targets.development
if (-not $development.dsql_endpoint -or -not $development.dsql_database_role -or
    -not $development.dsql_app_iam_principal_arn -or -not $development.api_runtime_principal_arn -or
    -not $development.aws_account_id) {
    throw 'Terraform outputs are missing required development DSQL bootstrap values.'
}

$accountId = aws sts get-caller-identity --query Account --output text
if ($LASTEXITCODE -ne 0 -or $accountId -notmatch '^\d{12}$') {
    throw 'Could not identify the active AWS operator account.'
}
if ($accountId -ne $development.aws_account_id) {
    throw 'Active AWS operator account does not match the Terraform-managed PawLocal account.'
}
$legacyUserArn = "arn:aws:iam::${accountId}:user/pawlocal/pawlocal-development-dsql-app"

Push-Location (Join-Path $PSScriptRoot '..\backend')
try {
    & $python -m pawlocal.dsql_role_bootstrap `
        --endpoint $development.dsql_endpoint `
        --region 'ap-southeast-2' `
        --database-role $development.dsql_database_role `
        --iam-principal-arn $development.dsql_app_iam_principal_arn `
        --legacy-iam-user-arn $legacyUserArn `
        --legacy-iam-principal-arn $development.api_runtime_principal_arn
    if ($LASTEXITCODE -ne 0) { throw "Development DSQL role bootstrap failed with exit code $LASTEXITCODE." }
} finally {
    Pop-Location
}
