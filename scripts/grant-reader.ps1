#Requires -Version 7
<#
.SYNOPSIS  Prints (default) or applies (-Apply, after confirmation) the Reader role assignments the collector identity needs.
.DESCRIPTION
  The collector job's system-assigned identity needs Reader on every subscription in config/subscriptions.json
  (Azure Resource Graph + Service Health REST). Nothing is granted without -Apply and an explicit 'yes'.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$PrincipalId,
  [switch]$Apply,
  [string]$Config = (Join-Path $PSScriptRoot '..\config\subscriptions.json')
)
$ErrorActionPreference = 'Stop'
$subs = (Get-Content $Config -Raw | ConvertFrom-Json).subscriptions
Write-Host 'Role assignments required:'
foreach ($s in $subs) { Write-Host "  Reader  ->  principal $PrincipalId  on  /subscriptions/$($s.id)  ($($s.name))" }
if (-not $Apply) { Write-Host "`nRun again with -Apply to create them."; return }
if ((Read-Host 'Create these role assignments? (yes/no)') -ne 'yes') { Write-Host 'Cancelled.'; return }
foreach ($s in $subs) {
  az role assignment create --assignee-object-id $PrincipalId --assignee-principal-type ServicePrincipal --role Reader --scope "/subscriptions/$($s.id)" -o none
  if ($LASTEXITCODE) { Write-Warning "failed for $($s.id)" } else { Write-Host "granted on $($s.id)" }
}
