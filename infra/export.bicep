// Per-subscription Activity Log export. ServiceHealth + ResourceHealth only. Run once per subscription.
// Never reuse the name of an existing setting for a different workspace (scripts/enable-export.ps1 checks first).
targetScope = 'subscription'

param workspaceId string
param settingName string = 'aol-export'

resource export 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: settingName
  properties: {
    workspaceId: workspaceId
    logs: [
      { category: 'ServiceHealth', enabled: true }
      { category: 'ResourceHealth', enabled: true }
    ]
  }
}

output settingId string = export.id
