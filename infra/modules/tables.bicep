// Custom tables (Analytics plan) from infra/schemas/tables.json. Deployed into the workspace's resource group.
param workspaceName string
param retentionDays int = 730

var schema = loadJsonContent('../schemas/tables.json')

resource ws 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

@batchSize(1)
resource tbl 'Microsoft.OperationalInsights/workspaces/tables@2022-10-01' = [for t in schema.tables: {
  parent: ws
  name: t.name
  properties: {
    plan: 'Analytics'
    retentionInDays: retentionDays
    totalRetentionInDays: retentionDays
    schema: {
      name: t.name
      columns: concat(schema.common, t.columns)
    }
  }
}]

output tableNames array = [for t in schema.tables: t.name]
