// Reader on the subscription for the collector identity (Azure Resource Graph + Service Health REST + Activity Log).
targetScope = 'subscription'

param principalId string

var reader = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'

resource assignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, principalId, reader)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', reader)
  }
}
