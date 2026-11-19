#Requires -Version 7
<#
.SYNOPSIS  Deploys the Azure Maintenance Ledger resource-group template to the sandbox subscription in .env.
.DESCRIPTION
  Confirms the active subscription equals AML_SUBSCRIPTION_ID, ensures the resource group, then runs what-if.
  -WhatIf stops after what-if. Without it, deployment proceeds after what-if (use -NoConfirm to skip the prompt).
  Extra Bicep parameters can be passed with -Parameters, e.g. -Parameters @('deployWorkbook=false').
#>
[CmdletBinding()]
param(
  [switch]$WhatIf,
  [switch]$NoConfirm,
  [string[]]$Parameters = @(),
  [string]$EnvFile = (Join-Path $PSScriptRoot '..\.env')
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$cfg = Import-AmlEnv -Path $EnvFile
Assert-AmlSubscription -SubscriptionId $cfg.AML_SUBSCRIPTION_ID

$rg = $cfg.AML_RESOURCE_GROUP
$loc = $cfg.AML_LOCATION
$template = Join-Path $PSScriptRoot '..\infra\main.bicep'

az bicep build --file $template --stdout 1>$null
if ($LASTEXITCODE) { throw 'bicep build failed' }

if (-not (az group exists --name $rg --subscription $cfg.AML_SUBSCRIPTION_ID | ConvertFrom-Json)) {
  Write-Host "Creating resource group $rg in $loc"
  az group create --name $rg --location $loc --subscription $cfg.AML_SUBSCRIPTION_ID --tags app=azure-maintenance-ledger -o none
}

$common = @('--resource-group', $rg, '--subscription', $cfg.AML_SUBSCRIPTION_ID, '--template-file', $template,
  '--parameters', "location=$loc", "prefix=$($cfg.AML_PREFIX)") + $Parameters

Write-Host '== what-if =='
az deployment group what-if @common
if ($LASTEXITCODE) { throw 'what-if failed' }
if ($WhatIf) { return }

if (-not $NoConfirm) {
  if ((Read-Host 'Deploy these changes? (yes/no)') -ne 'yes') { Write-Host 'Cancelled.'; return }
}
az deployment group create @common --name aml-main --query properties.outputs -o json
if ($LASTEXITCODE) { throw 'deployment failed' }
