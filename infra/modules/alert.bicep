// Stale-ingest log alert: no successful run of any enabled collector in 36 h. Action group only if an email is given.
param location string
param prefix string
param workspaceId string
param enabledSources array
param alertEmail string = ''
param tags object = {}

resource ag 'Microsoft.Insights/actionGroups@2023-01-01' = if (!empty(alertEmail)) {
  name: '${prefix}-ag'
  location: 'global'
  tags: tags
  properties: {
    groupShortName: take('${prefix}ledger', 12)
    enabled: true
    emailReceivers: [
      {
        name: 'owner'
        emailAddress: alertEmail
        useCommonAlertSchema: true
      }
    ]
  }
}

var sourceList = join(map(enabledSources, s => '"${s}"'), ',')
var query = '''
let enabled = dynamic([{0}]);
let ok = AzMaintenanceIngestHealth_CL
| where ingested_utc > ago(36h) and status in ("success", "partial") and is_synthetic != true
| summarize last_ok = max(finished_utc) by source;
print source = enabled
| mv-expand source to typeof(string)
| join kind=leftouter ok on source
| where isnull(last_ok)
'''

resource rule 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: '${prefix}-stale-ingest'
  location: location
  tags: tags
  properties: {
    displayName: 'Azure Maintenance Ledger - no successful ingest in 36 h'
    description: 'A collector enabled for this ledger has not reported success for 36 hours.'
    severity: 2
    enabled: true
    evaluationFrequency: 'PT1H'
    windowSize: 'P2D'
    scopes: [workspaceId]
    skipQueryValidation: true
    criteria: {
      allOf: [
        {
          query: replace(query, '{0}', sourceList)
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
        }
      ]
    }
    actions: !empty(alertEmail) ? { actionGroups: [ag.id] } : null
  }
}
