#Requires -Version 7
<#
.SYNOPSIS  Enables the aol-export Activity Log export (ServiceHealth + ResourceHealth) on every subscription in config/subscriptions.json.
.DESCRIPTION
  Inspects existing diagnostic settings first and NEVER changes or deletes a setting it does not own:
    - setting 'aol-export' already points at this workspace  -> skipped (idempotent)
    - setting 'aol-export' points at another workspace       -> stops with an error for that subscription
    - subscription already has 5 settings (the limit)        -> skipped with a warning
  Requires the identity running the script to be allowed to create diagnostic settings on each subscription.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$WorkspaceResourceId,
  [switch]$WhatIf,
  [string]$Config = (Join-Path $PSScriptRoot '..\config\subscriptions.json'),
  [string]$SettingName = 'aol-export'
)
$ErrorActionPreference = 'Stop'
$limit = 5
$template = Join-Path $PSScriptRoot '..\infra\export.bicep'
$subs = (Get-Content $Config -Raw | ConvertFrom-Json).subscriptions

foreach ($s in $subs) {
  Write-Host "== $($s.id) ($($s.name))"
  $existing = az monitor diagnostic-settings subscription list --subscription $s.id --query 'value[].{n:name,ws:workspaceId}' -o json | ConvertFrom-Json
  $mine = $existing | Where-Object { $_.n -eq $SettingName }
  if ($mine -and $mine.ws -ieq $WorkspaceResourceId) { Write-Host "  $SettingName already present; skipped"; continue }
  if ($mine) { Write-Error "  $SettingName exists but targets another workspace ($($mine.ws)). Not overwriting."; continue }
  if (@($existing).Count -ge $limit) { Write-Warning "  $($s.id) already has $limit diagnostic settings (limit). Skipped."; continue }
  Write-Host "  existing settings (untouched): $((@($existing) | ForEach-Object n) -join ', ')"
  $args2 = @('--location', 'centralindia', '--subscription', $s.id, '--template-file', $template, '--parameters', "workspaceId=$WorkspaceResourceId", "settingName=$SettingName")
  if ($WhatIf) { az deployment sub what-if @args2 --result-format ResourceIdOnly; continue }
  az deployment sub create @args2 --name "aol-export" -o none
  if ($LASTEXITCODE) { Write-Warning "  export deployment failed for $($s.id)" } else { Write-Host '  enabled' }
}
