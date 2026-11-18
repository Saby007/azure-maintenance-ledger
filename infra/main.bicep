// Azure Maintenance Ledger - resource-group deployment. The per-subscription Activity Log export is infra/export.bicep.
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
@description('Comma-separated subscription ids the collector reads. Empty = config/subscriptions.json in the package.')
param subscriptionIds string = ''
@description('Public URL of the collector code package (zip) the scheduled job downloads at each run. Pin it to a commit or tag URL to control updates.')
param packageUri string = 'https://raw.githubusercontent.com/Saby007/azure-maintenance-ledger/main/release/app.zip'

@description('Module flags')
param deployCollector bool = true
param deployKqlFunctions bool = true
param deployWorkbook bool = true
param enableStaleAlert bool = true
param enableBudget bool = false
param budgetAmountUsd int = 10
param enablePirs bool = true
param enableVmAnnotations bool = true

var tags = { app: 'azure-maintenance-ledger' }
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

module collector 'modules/collectorjob.bicep' = if (deployCollector) {
  name: 'collector-job'
  params: {
    location: location
    prefix: prefix
    workspaceId: workspace.outputs.id
    packageUri: packageUri
    tags: tags
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

module rbac 'modules/rbac.bicep' = if (deployCollector) {
  name: 'rbac'
  params: {
    principalId: collector.?outputs.principalId ?? ''
    dcrName: dcr.outputs.name
  }
}

module rbacWorkspace 'modules/rbac-workspace.bicep' = if (deployCollector) {
  name: 'rbac-workspace'
  scope: resourceGroup(workspaceResourceGroup)
  params: {
    principalId: collector.?outputs.principalId ?? ''
    workspaceName: workspace.outputs.name
  }
}

var kqlFiles = [
  { name: 'AzMaintenance_Catalog', parameters: 'includeSynthetic:bool=false', query: loadTextContent('../kql/AzMaintenance_Catalog.kql') }
  { name: 'AzMaintenance_Events', parameters: 'includeSynthetic:bool=false', query: loadTextContent('../kql/AzMaintenance_Events.kql') }
  { name: 'AzMaintenance_EventServices', parameters: 'includeSynthetic:bool=false', query: loadTextContent('../kql/AzMaintenance_EventServices.kql') }
  { name: 'AzMaintenance_Planned', parameters: 'includeSynthetic:bool=false', query: loadTextContent('../kql/AzMaintenance_Planned.kql') }
  { name: 'AzMaintenance_ResourceIntervals', parameters: 'includeSynthetic:bool=false', query: loadTextContent('../kql/AzMaintenance_ResourceIntervals.kql') }
  { name: 'AzMaintenance_Availability', parameters: 'windowDays:int=365, includeUserInitiated:bool=false, includeSynthetic:bool=false', query: loadTextContent('../kql/AzMaintenance_Availability.kql') }
  { name: 'AzMaintenance_PirBaseline', parameters: 'includeSynthetic:bool=false', query: loadTextContent('../kql/AzMaintenance_PirBaseline.kql') }
  { name: 'AzMaintenance_Forecast', parameters: 'includeSynthetic:bool=false', query: loadTextContent('../kql/AzMaintenance_Forecast.kql') }
  { name: 'AzMaintenance_DataHealth', parameters: 'includeSynthetic:bool=false', query: loadTextContent('../kql/AzMaintenance_DataHealth.kql') }
  { name: 'AzMaintenance_CompositeSla', parameters: 'slas:dynamic, mode:string="serial"', query: loadTextContent('../kql/AzMaintenance_CompositeSla.kql') }
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

output workspaceResourceId string = workspace.outputs.id
output workspaceCustomerId string = workspace.outputs.customerId
output dcrImmutableId string = dcr.outputs.immutableId
output dcrEndpoint string = dcr.outputs.logsIngestionEndpoint
output collectorJobName string = collector.?outputs.jobName ?? ''
output collectorPrincipalId string = collector.?outputs.principalId ?? ''
