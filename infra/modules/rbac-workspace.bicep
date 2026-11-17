// Log Analytics Reader for the collector identity (forecast reads the workspace) and the reporting identity.
param principalId string
param workspaceName string

var logAnalyticsReader = '73c42c96-874c-492b-b04d-ab87d138a893'

resource ws 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

resource laReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(ws.id, principalId, logAnalyticsReader)
  scope: ws
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', logAnalyticsReader)
  }
}
