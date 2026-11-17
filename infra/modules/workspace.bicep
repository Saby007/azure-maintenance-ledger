// Workspace: new (dedicated, default) or existing. Existing must be in the same subscription.
param location string
param name string
@allowed(['new', 'existing'])
param mode string = 'new'
param existingName string = ''
param existingResourceGroup string = resourceGroup().name
param retentionDays int = 730
@description('Daily ingestion cap in GB. -1 disables the cap.')
param dailyCapGb string = '0.5'
param tags object = {}

resource created 'Microsoft.OperationalInsights/workspaces@2023-09-01' = if (mode == 'new') {
  name: name
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: retentionDays
    workspaceCapping: { dailyQuotaGb: json(dailyCapGb) }
    features: { enableLogAccessUsingOnlyResourcePermissions: true }
  }
}

resource existing 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = if (mode == 'existing') {
  name: existingName
  scope: resourceGroup(existingResourceGroup)
}

output id string = mode == 'new' ? created.id : existing.id
output name string = mode == 'new' ? created.name : existing.name
output customerId string = mode == 'new' ? created!.properties.customerId : existing!.properties.customerId
output resourceGroup string = mode == 'new' ? resourceGroup().name : existingResourceGroup
