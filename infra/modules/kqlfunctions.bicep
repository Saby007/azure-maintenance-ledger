// Workspace functions (savedSearches with functionAlias) from kql/*.kql.
param workspaceName string
param functions array // [{ name, displayName, query, parameters }]

resource ws 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

@batchSize(1)
resource fn 'Microsoft.OperationalInsights/workspaces/savedSearches@2020-08-01' = [for f in functions: {
  parent: ws
  name: toLower(f.name)
  properties: {
    category: 'AzureOutageLedger'
    displayName: f.displayName
    query: f.query
    functionAlias: f.name
    functionParameters: f.parameters
    version: 2
  }
}]
