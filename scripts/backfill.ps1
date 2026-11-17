#Requires -Version 7
<#
.SYNOPSIS  One-time / on-demand backfill (public PIRs, ARG events, REST events back 365 days, Activity Log 89 days, inventory).
.DESCRIPTION
  Wraps `python -m collector.backfill`. Requires: az login, Reader on the subscriptions, Monitoring Metrics Publisher on the DCR,
  and AOL_DCR_ENDPOINT / AOL_DCR_IMMUTABLE_ID in .env. Use -DryRun to count rows without uploading.
#>
[CmdletBinding()]
param(
  [switch]$DryRun,
  [string]$Only = 'pirs,arg,rest,activity,inventory',
  [string]$PirFile
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }
$env:PYTHONPATH = Join-Path $root 'src'
$a = @('-m', 'collector.backfill', '--only', $Only)
if ($DryRun) { $a += '--dry-run' }
if ($PirFile) { $a += @('--pir-file', $PirFile) }
& $py @a
exit $LASTEXITCODE
