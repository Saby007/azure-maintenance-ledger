// Flex Consumption function app, system-assigned identity, identity-only storage (shared key off). No App Insights.
param location string
param prefix string
param tags object = {}
param pythonVersion string = '3.14'
@description('Smallest instance size.')
param instanceMemoryMB int = 512
param maximumInstanceCount int = 10
param appSettings object = {}

var suffix = uniqueString(resourceGroup().id, prefix)
var storageName = take('${prefix}st${suffix}', 24)
var planName = '${prefix}-plan'
var appName = '${prefix}-func-${suffix}'
var deployContainer = 'app-package'

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    defaultToOAuthAuthentication: true
  }
}

resource blob 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blob
  name: deployContainer
}

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: planName
  location: location
  tags: tags
  kind: 'functionapp'
  sku: { name: 'FC1', tier: 'FlexConsumption' }
  properties: { reserved: true }
}

var baseSettings = {
  AzureWebJobsStorage__accountName: storage.name
  AOL_STATE_ACCOUNT_URL: 'https://${storage.name}.table.${environment().suffixes.storage}'
}

resource app 'Microsoft.Web/sites@2023-12-01' = {
  name: appName
  location: location
  tags: tags
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}${deployContainer}'
          authentication: { type: 'SystemAssignedIdentity' }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: maximumInstanceCount
        instanceMemoryMB: instanceMemoryMB
      }
      runtime: { name: 'python', version: pythonVersion }
    }
    siteConfig: {
      appSettings: [for k in objectKeys(union(baseSettings, appSettings)): {
        name: k
        value: union(baseSettings, appSettings)[k]
      }]
    }
  }
  dependsOn: [container]
}

// Storage Blob Data Owner (deployment package + timer leases), Table Data Contributor (watermarks),
// Queue Data Contributor (host internals).
var storageRoles = [
  'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
  '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
  '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
]

resource roles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for r in storageRoles: {
  name: guid(storage.id, app.id, r)
  scope: storage
  properties: {
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', r)
  }
}]

output appName string = app.name
output principalId string = app.identity.principalId
output storageName string = storage.name
output stateAccountUrl string = baseSettings.AOL_STATE_ACCOUNT_URL
