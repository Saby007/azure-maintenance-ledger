#Requires -Version 7
<#
.SYNOPSIS  Billable GB per table from the Usage table and a monthly cost estimate for the ledger workspace.
.DESCRIPTION
  Read-only. Uses the Log Analytics query API. The estimate uses -PricePerGb (default 2.76 USD, pay-as-you-go
  Analytics ingestion; confirm for your region/agreement) and ignores the free 5 GB/month allowance on new workspaces
  only if -IncludeFreeGrant is not set. AzureActivity ingestion is free; only custom-table GB are billed.
  Fixed costs (storage account, Flex Consumption executions) are listed from the Cost Management API when available.
#>
[CmdletBinding()]
param(
  [string]$EnvFile = (Join-Path $PSScriptRoot '..\.env'),
  [int]$Days = 7,
  [double]$PricePerGb = 2.76
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$cfg = Import-AolEnv -Path $EnvFile
$ws = $cfg.AOL_WORKSPACE_ID
if (-not $ws) { throw 'AOL_WORKSPACE_ID (workspace customer id) missing in .env' }

$q = @"
Usage
| where TimeGenerated > ago(${Days}d) and IsBillable == true
| summarize billable_gb = round(sum(Quantity) / 1024.0, 6) by DataType
| order by billable_gb desc
"@
$rows = @(az monitor log-analytics query -w $ws --analytics-query $q -o json 2>$null | ConvertFrom-Json) |
  ForEach-Object { [pscustomobject]@{ DataType = $_.DataType; billable_gb = [double]$_.billable_gb } }
$total = ($rows | Measure-Object billable_gb -Sum).Sum
if (-not $total) { $total = 0 }
$monthly = $total / $Days * 30
$cost = $monthly * $PricePerGb
$rows | ForEach-Object { '{0,-28} {1,12:N6} GB' -f $_.DataType, $_.billable_gb } | Write-Host
"Billable GB over $Days days : {0:N6}" -f $total
"Projected monthly GB        : {0:N6}" -f $monthly
"Projected ingestion cost    : USD {0:N2}/month at USD {1}/GB (excludes storage account and function executions)" -f $cost, $PricePerGb
if ($cost -gt 10) { Write-Warning 'Projected ingestion cost is above US$10/month.' }
