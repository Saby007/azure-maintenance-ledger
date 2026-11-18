// Azure Maintenance Ledger - ONE-CLICK deployment (subscription scope).
// Creates the resource group, the workspace + tables + DCR + KQL functions + Workbook + alert + a scheduled Container Apps Job (the
// collector; it uses no storage account, so it works where policy blocks public access on storage), grants the job identity Reader on
// this subscription and exports the Activity Log
// (ServiceHealth + ResourceHealth) to the new workspace. Compiled to infra/azuredeploy.json for the "Deploy to Azure" button.
targetScope = 'subscription'

@description('Azure region for the resource group and all resources.')
param location string = deployment().location

@description('Name of the resource group to create.')
param resourceGroupName string = 'rg-azure-maintenance-ledger'

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

@description('Public URL of the collector code package (zip) that the scheduled job downloads at each run. Pin it to a commit or tag URL to control updates.')
param packageUri string = 'https://raw.githubusercontent.com/Saby007/azure-maintenance-ledger/main/release/app.zip'

@description('Export this subscription\'s Activity Log (ServiceHealth + ResourceHealth) to the new workspace.')
param enableActivityLogExport bool = true

@description('Name of the diagnostic setting created on the subscription. WARNING: a setting with this name that already points elsewhere is overwritten, so change the name if one exists.')
param activityLogExportName string = 'aol-export'

@description('Grant the collector job identity Reader on this subscription (needs Owner or User Access Administrator).')
param grantReaderOnSubscription bool = true

var tags = { app: 'azure-maintenance-ledger' }
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
    packageUri: packageUri
    enablePirs: enablePirs
    enableVmAnnotations: enableVmAnnotations
    enableBudget: enableBudget
  }
}

module reader 'modules/reader-sub.bicep' = if (grantReaderOnSubscription) {
  name: 'aol-reader'
  params: {
    principalId: core.outputs.collectorPrincipalId
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
output collectorJobName string = core.outputs.collectorJobName
output nextSteps string = 'Open Azure Monitor > Workbooks > "Azure Maintenance Ledger". The collector job runs hourly at :15 UTC and the first run loads the history, so data appears within about 90 minutes. See the Data health tab.'
