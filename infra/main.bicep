// Azure Outage Ledger - resource-group deployment. The per-subscription Activity Log export is infra/export.bicep.
targetScope = 'resourceGroup'

param location string = resourceGroup().location
param prefix string = 'aol'
@allowed(['new', 'existing'])
param workspaceMode string = 'new'
param existingWorkspaceName string = ''
param existingWorkspaceResourceGroup string = resourceGroup().name
param retentionDays int = 730
@description('Workspace daily ingestion cap in GB (-1 = none).')
param dailyCapGb string = '0.5'
param alertEmail string = ''
param pythonVersion string = '3.14'
@description('Comma-separated subscription ids the collector reads. Empty = config/subscriptions.json in the package.')
param subscriptionIds string = ''
@description('Public URL of the collector code package (zip). Empty = do not deploy code (use scripts/deploy-code.ps1).')
param codePackageUri string = ''

@description('Module flags')
param deployFunctionApp bool = true
param deployKqlFunctions bool = true
param deployWorkbook bool = true
param enableStaleAlert bool = true
param enableBudget bool = false
param budgetAmountUsd int = 10
param enablePirs bool = true
param enableVmAnnotations bool = true

var tags = { app: 'azure-outage-ledger' }
var workspaceName = workspaceMode == 'new' ? '${prefix}-law' : existingWorkspaceName
var workspaceResourceGroup = workspaceMode == 'new' ? resourceGroup().name : existingWorkspaceResourceGroup

module workspace 'modules/workspace.bicep' = {
  name: 'workspace'
  params: {
    location: location
    name: workspaceName
    mode: workspaceMode
    existingName: existingWorkspaceName
    existingResourceGroup: existingWorkspaceResourceGroup
    retentionDays: retentionDays
    dailyCapGb: dailyCapGb
    tags: tags
  }
}

module tables 'modules/tables.bicep' = {
  name: 'tables'
  scope: resourceGroup(workspaceResourceGroup)
  params: {
    workspaceName: workspace.outputs.name
    retentionDays: retentionDays
  }
}

module dcr 'modules/dcr.bicep' = {
  name: 'dcr'
  params: {
    location: location
    name: '${prefix}-dcr'
    workspaceId: workspace.outputs.id
    tags: tags
  }
  dependsOn: [tables]
}

var enabledSources = concat(
  ['servicehealth_events', 'inventory', 'forecast'],
  enablePirs ? ['public_pirs'] : [],
  enableVmAnnotations ? ['vm_annotations'] : []
)

module func 'modules/functionapp.bicep' = if (deployFunctionApp) {
  name: 'functionapp'
  params: {
    location: location
    prefix: prefix
    tags: tags
    pythonVersion: pythonVersion
    appSettings: {
      AOL_DCR_ENDPOINT: dcr.outputs.logsIngestionEndpoint
      AOL_DCR_IMMUTABLE_ID: dcr.outputs.immutableId
      AOL_WORKSPACE_ID: workspace.outputs.customerId
      AOL_ENABLE_PIRS: string(enablePirs)
      AOL_ENABLE_VM_ANNOTATIONS: string(enableVmAnnotations)
      AOL_SUBSCRIPTIONS: subscriptionIds
    }
  }
}

module rbac 'modules/rbac.bicep' = if (deployFunctionApp) {
  name: 'rbac'
  params: {
    principalId: func.?outputs.principalId ?? ''
    dcrName: dcr.outputs.name
  }
}

module rbacWorkspace 'modules/rbac-workspace.bicep' = if (deployFunctionApp) {
  name: 'rbac-workspace'
  scope: resourceGroup(workspaceResourceGroup)
  params: {
    principalId: func.?outputs.principalId ?? ''
    workspaceName: workspace.outputs.name
  }
}

var kqlFiles = [
  { name: 'AzOutage_Catalog', parameters: 'includeSynthetic:bool=false', query: loadTextContent('../kql/AzOutage_Catalog.kql') }
  { name: 'AzOutage_Events', parameters: 'includeSynthetic:bool=false', query: loadTextContent('../kql/AzOutage_Events.kql') }
  { name: 'AzOutage_EventServices', parameters: 'includeSynthetic:bool=false', query: loadTextContent('../kql/AzOutage_EventServices.kql') }
  { name: 'AzOutage_Planned', parameters: 'includeSynthetic:bool=false', query: loadTextContent('../kql/AzOutage_Planned.kql') }
  { name: 'AzOutage_ResourceIntervals', parameters: 'includeSynthetic:bool=false', query: loadTextContent('../kql/AzOutage_ResourceIntervals.kql') }
  { name: 'AzOutage_Availability', parameters: 'windowDays:int=365, includeUserInitiated:bool=false, includeSynthetic:bool=false', query: loadTextContent('../kql/AzOutage_Availability.kql') }
  { name: 'AzOutage_PirBaseline', parameters: 'includeSynthetic:bool=false', query: loadTextContent('../kql/AzOutage_PirBaseline.kql') }
  { name: 'AzOutage_Forecast', parameters: 'includeSynthetic:bool=false', query: loadTextContent('../kql/AzOutage_Forecast.kql') }
  { name: 'AzOutage_DataHealth', parameters: 'includeSynthetic:bool=false', query: loadTextContent('../kql/AzOutage_DataHealth.kql') }
  { name: 'AzOutage_CompositeSla', parameters: 'slas:dynamic, mode:string="serial"', query: loadTextContent('../kql/AzOutage_CompositeSla.kql') }
]

module kql 'modules/kqlfunctions.bicep' = if (deployKqlFunctions) {
  name: 'kqlfunctions'
  scope: resourceGroup(workspaceResourceGroup)
  params: {
    workspaceName: workspace.outputs.name
    functions: [for f in kqlFiles: {
      name: f.name
      displayName: f.name
      query: f.query
      parameters: f.parameters
    }]
  }
  dependsOn: [tables]
}

module workbook 'modules/workbook.bicep' = if (deployWorkbook) {
  name: 'workbook'
  params: {
    location: location
    workbookId: guid(resourceGroup().id, prefix, 'aol-workbook')
    workspaceId: workspace.outputs.id
    serializedTemplate: loadTextContent('../workbook/workbook.deploy.json')
    tags: tags
  }
}

module alert 'modules/alert.bicep' = if (enableStaleAlert) {
  name: 'stale-alert'
  params: {
    location: location
    prefix: prefix
    workspaceId: workspace.outputs.id
    enabledSources: enabledSources
    alertEmail: alertEmail
    tags: tags
  }
  dependsOn: [tables]
}

module budget 'modules/budget.bicep' = if (enableBudget && !empty(alertEmail)) {
  name: 'budget'
  params: {
    amount: budgetAmountUsd
    contactEmail: alertEmail
  }
}

// Code is deployed last: the dependencies give the function identity's storage/DCR/workspace roles time to propagate.
module codeDeploy 'modules/codedeploy.bicep' = if (deployFunctionApp && !empty(codePackageUri)) {
  name: 'code-deploy'
  params: {
    functionAppName: func.?outputs.appName ?? ''
    packageUri: codePackageUri
  }
  dependsOn: [rbac, rbacWorkspace, tables, kql, workbook, alert]
}

output workspaceResourceId string = workspace.outputs.id
output workspaceCustomerId string = workspace.outputs.customerId
output dcrImmutableId string = dcr.outputs.immutableId
output dcrEndpoint string = dcr.outputs.logsIngestionEndpoint
output functionAppName string = func.?outputs.appName ?? ''
output functionPrincipalId string = func.?outputs.principalId ?? ''
output stateAccountUrl string = func.?outputs.stateAccountUrl ?? ''
