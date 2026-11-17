// Direct DCR (no DCE): exposes its own logsIngestion endpoint. Identity needs Monitoring Metrics Publisher (rbac.bicep).
param location string
param name string
param workspaceId string
param tags object = {}

var schema = loadJsonContent('../schemas/tables.json')

resource dcr 'Microsoft.Insights/dataCollectionRules@2023-03-11' = {
  name: name
  location: location
  kind: 'Direct'
  tags: tags
  properties: {
    streamDeclarations: toObject(schema.tables, t => 'Custom-${t.name}', t => {
      columns: concat(schema.common, t.columns)
    })
    destinations: {
      logAnalytics: [
        {
          name: 'law'
          workspaceResourceId: workspaceId
        }
      ]
    }
    dataFlows: [for t in schema.tables: {
      streams: ['Custom-${t.name}']
      destinations: ['law']
      transformKql: 'source'
      outputStream: 'Custom-${t.name}'
    }]
  }
}

output id string = dcr.id
output name string = dcr.name
output immutableId string = dcr.properties.immutableId
output logsIngestionEndpoint string = dcr.properties.endpoints.logsIngestion
