#Requires -Version 7
<#
.SYNOPSIS  Packages and deploys the collector code to the Flex Consumption function app (zip deploy, Entra auth).
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$FunctionApp,
  [string]$ResourceGroup,
  [string]$EnvFile = (Join-Path $PSScriptRoot '..\.env')
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$cfg = Import-AolEnv -Path $EnvFile
Assert-AolSubscription -SubscriptionId $cfg.AOL_SUBSCRIPTION_ID
if (-not $ResourceGroup) { $ResourceGroup = $cfg.AOL_RESOURCE_GROUP }

$root = Split-Path $PSScriptRoot -Parent
$app = Join-Path $root 'dist\app'
if (Test-Path $app) { Remove-Item $app -Recurse -Force }
New-Item -ItemType Directory $app | Out-Null
Copy-Item (Join-Path $root 'src\collector') (Join-Path $app 'collector') -Recurse
Copy-Item (Join-Path $root 'src\analytics') (Join-Path $app 'analytics') -Recurse
Copy-Item (Join-Path $root 'src\collector\function_app.py') (Join-Path $app 'function_app.py')
Copy-Item (Join-Path $root 'kql') (Join-Path $app 'kql') -Recurse
Copy-Item (Join-Path $root 'config') (Join-Path $app 'config') -Recurse
Copy-Item (Join-Path $root 'reference') (Join-Path $app 'reference') -Recurse
Copy-Item (Join-Path $root 'requirements.txt') (Join-Path $app 'requirements.txt')
@'
{ "version": "2.0", "extensionBundle": { "id": "Microsoft.Azure.Functions.ExtensionBundle", "version": "[4.*, 5.0.0)" }, "logging": { "logLevel": { "default": "Information", "Azure.Core": "Warning", "Azure": "Warning" } } }
'@ | Set-Content (Join-Path $app 'host.json') -Encoding utf8
Get-ChildItem $app -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force

$zip = Join-Path $root 'dist\app.zip'
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path (Join-Path $app '*') -DestinationPath $zip
Write-Host "Packaged $zip"

az functionapp deployment source config-zip --resource-group $ResourceGroup --name $FunctionApp --src $zip --subscription $cfg.AOL_SUBSCRIPTION_ID --build-remote true -o none
if ($LASTEXITCODE) { throw 'zip deploy failed' }
Write-Host 'Deployed. Triggers:'
az functionapp function list --resource-group $ResourceGroup --name $FunctionApp --subscription $cfg.AOL_SUBSCRIPTION_ID --query '[].name' -o tsv
