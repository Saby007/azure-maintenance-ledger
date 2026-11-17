// Least-privilege role for the collector identity on the DCR (Reader on target subscriptions is granted by scripts/grant-reader.ps1).
param principalId string
param dcrName string

var metricsPublisher = '3913510d-42f4-4e42-8a64-420c390055eb'

resource dcr 'Microsoft.Insights/dataCollectionRules@2023-03-11' existing = {
  name: dcrName
}

resource publisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(dcr.id, principalId, metricsPublisher)
  scope: dcr
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', metricsPublisher)
  }
}
