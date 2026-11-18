#Requires -Version 7
<#
.SYNOPSIS  Builds release\app.zip, the collector code package that the scheduled Container Apps Job downloads at each run.
.DESCRIPTION
  Layout: collector\, analytics\, kql\, config\, reference\ and requirements.txt at the root (the job extracts the zip and runs
  `python -m collector.job collect` from that folder). Entry names use forward slashes. Commit release\app.zip after changing
  anything under src\, kql\, config\ or reference\ - the job downloads it from the repo.
#>
[CmdletBinding()]
param([string]$Output = (Join-Path (Split-Path $PSScriptRoot -Parent) 'release\app.zip'))
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$root = Split-Path $PSScriptRoot -Parent
$stage = Join-Path $root 'dist\app'
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory $stage -Force | Out-Null

Copy-Item (Join-Path $root 'src\collector') (Join-Path $stage 'collector') -Recurse
Copy-Item (Join-Path $root 'src\analytics') (Join-Path $stage 'analytics') -Recurse
foreach ($d in 'kql', 'config', 'reference') { Copy-Item (Join-Path $root $d) (Join-Path $stage $d) -Recurse }
# openpyxl is only needed for the quarterly report, not for the collector job
(Get-Content (Join-Path $root 'requirements.txt') | Where-Object { $_ -notmatch '^\s*openpyxl' }) | Set-Content (Join-Path $stage 'requirements.txt') -Encoding utf8
Get-ChildItem $stage -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
Get-ChildItem $stage -Recurse -File -Include *.pyc | Remove-Item -Force

New-Item -ItemType Directory (Split-Path $Output -Parent) -Force | Out-Null
if (Test-Path $Output) { Remove-Item $Output }
$zip = [System.IO.Compression.ZipFile]::Open($Output, 'Create')
try {
  $base = (Resolve-Path $stage).Path.TrimEnd('\') + '\'
  Get-ChildItem $stage -Recurse -File | Sort-Object FullName | ForEach-Object {
    $rel = $_.FullName.Substring($base.Length).Replace('\', '/')
    [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $_.FullName, $rel, 'Optimal')
  }
} finally { $zip.Dispose() }
$z = [System.IO.Compression.ZipFile]::OpenRead($Output)
"Built $Output ($([math]::Round((Get-Item $Output).Length / 1KB)) KB, $($z.Entries.Count) files)"
$z.Entries | Where-Object { $_.FullName -in 'collector/job.py', 'requirements.txt' } | ForEach-Object { "  $($_.FullName)" }
$z.Dispose()
Remove-Item (Join-Path $root 'dist') -Recurse -Force
