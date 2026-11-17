// Azure Outage Ledger - ONE-CLICK deployment (subscription scope).
// Creates the resource group, the workspace + tables + DCR + KQL functions + Workbook + alert + Function app, deploys the collector
// code from a public package, grants the Function identity Reader on this subscription and exports the Activity Log
// (ServiceHealth + ResourceHealth) to the new workspace. Compiled to infra/azuredeploy.json for the "Deploy to Azure" button.
targetScope = 'subscription'

@description('Azure region for the resource group and all resources.')
param location string = deployment().location

@description('Name of the resource group to create.')
param resourceGroupName string = 'rg-azure-outage-ledger'

@description('Short prefix for resource names (3-8 lowercase letters or digits).')
@minLength(3)
@maxLength(8)
param prefix string = 'aol'

@description('new = create a dedicated workspace (recommended). existing = reuse a workspace you name below (same subscription).')
@allowed(['new', 'existing'])
param workspaceMode string = 'new'

@description('Only for workspaceMode = existing: workspace name.')
param existingWorkspaceName string = ''

@description('Only for workspaceMode = existing: resource group of that workspace.')
param existingWorkspaceResourceGroup string = ''

@description('Data retention in days (the ledger keeps history Azure itself ages out).')
@minValue(90)
@maxValue(730)
param retentionDays int = 730

@description('Workspace daily ingestion cap in GB. Keeps cost bounded.')
param dailyCapGb string = '0.5'

@description('Email for the "no successful ingest in 36 h" alert. Leave empty to create the alert without an email action.')
param alertEmail string = ''

@description('Extra subscription ids to read (comma separated). This subscription is always included. Grant Reader and enable the export for each extra subscription with the scripts in the repo.')
param additionalSubscriptionIds string = ''

@description('Collect public Azure post-incident reviews (PIRs) monthly. Uses an undocumented public endpoint: confirm acceptable use with your organisation.')
param enablePirs bool = true

@description('Collect VM planned/unplanned annotations from Azure Resource Graph.')
param enableVmAnnotations bool = true

@description('Create a monthly cost budget alert (needs alertEmail).')
param enableBudget bool = false

@description('Public URL of the collector code package (zip).')
param codePackageUri string = 'https://raw.githubusercontent.com/Saby007/azure-outage-ledger/main/release/app.zip'

@description('Export this subscription\'s Activity Log (ServiceHealth + ResourceHealth) to the new workspace.')
param enableActivityLogExport bool = true

@description('Name of the diagnostic setting created on the subscription. WARNING: a setting with this name that already points elsewhere is overwritten, so change the name if one exists.')
param activityLogExportName string = 'aol-export'

@description('Grant the collector identity Reader on this subscription (needs Owner or User Access Administrator).')
param grantReaderOnSubscription bool = true

var tags = { app: 'azure-outage-ledger' }
var subscriptionList = empty(additionalSubscriptionIds) ? subscription().subscriptionId : '${subscription().subscriptionId},${additionalSubscriptionIds}'

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module core 'main.bicep' = {
  name: 'aol-core'
  scope: rg
  params: {
    location: location
    prefix: prefix
    workspaceMode: workspaceMode
    existingWorkspaceName: existingWorkspaceName
    existingWorkspaceResourceGroup: empty(existingWorkspaceResourceGroup) ? resourceGroupName : existingWorkspaceResourceGroup
    retentionDays: retentionDays
    dailyCapGb: dailyCapGb
    alertEmail: alertEmail
    subscriptionIds: subscriptionList
    codePackageUri: codePackageUri
    enablePirs: enablePirs
    enableVmAnnotations: enableVmAnnotations
    enableBudget: enableBudget
  }
}

module reader 'modules/reader-sub.bicep' = if (grantReaderOnSubscription) {
  name: 'aol-reader'
  params: {
    principalId: core.outputs.functionPrincipalId
  }
}

module activityLogExport 'export.bicep' = if (enableActivityLogExport) {
  name: 'aol-activity-log-export'
  params: {
    workspaceId: core.outputs.workspaceResourceId
    settingName: activityLogExportName
  }
}

output resourceGroup string = resourceGroupName
output workspaceResourceId string = core.outputs.workspaceResourceId
output functionAppName string = core.outputs.functionAppName
output nextSteps string = 'Open Azure Monitor > Workbooks > "Azure Outage Ledger". Data appears after the first run (about 10-20 minutes). See the Data health tab.'
