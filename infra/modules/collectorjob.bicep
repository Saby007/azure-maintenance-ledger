// Scheduled collector as an Azure Container Apps Job (consumption). No storage account is used, so it also works in
// subscriptions where policy disables public access on storage. The job downloads the collector package from a public URL
// at each run, installs its dependencies and runs `python -m collector.job collect`. Authentication is the job's managed identity.
param location string
param prefix string
param workspaceId string
param packageUri string
param tags object = {}
@description('Environment variables for the collector.')
param appSettings object = {}
@description('UTC cron schedule. Hourly: the job only does what is due (see src/collector/job.py).')
param cron string = '15 * * * *'
param image string = 'mcr.microsoft.com/azurelinux/base/python:3.12'

var script = '''
set -e
cd /tmp
python3 -m pip install -q --no-cache-dir --disable-pip-version-check requests
python3 -c "import os,requests,zipfile;r=requests.get(os.environ['AOL_PACKAGE_URL'],timeout=120);r.raise_for_status();open('app.zip','wb').write(r.content);zipfile.ZipFile('app.zip').extractall('app')"
cd app
python3 -m pip install -q --no-cache-dir --disable-pip-version-check -r requirements.txt
PYTHONPATH=. python3 -m collector.job collect
'''

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-env'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: { destination: 'azure-monitor' }
    zoneRedundant: false
  }
}

resource envLogs 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'to-workspace'
  scope: env
  properties: {
    workspaceId: workspaceId
    logs: [
      { category: 'ContainerAppConsoleLogs', enabled: true }
      { category: 'ContainerAppSystemLogs', enabled: true }
    ]
  }
}

resource job 'Microsoft.App/jobs@2024-03-01' = {
  name: '${prefix}-collect'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    environmentId: env.id
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: 1800
      replicaRetryLimit: 0
      scheduleTriggerConfig: {
        cronExpression: cron
        parallelism: 1
        replicaCompletionCount: 1
      }
    }
    template: {
      containers: [
        {
          name: 'collector'
          image: image
          resources: { cpu: json('0.5'), memory: '1Gi' }
          command: ['/bin/sh', '-c']
          args: [script]
          env: [for k in objectKeys(union({ AOL_PACKAGE_URL: packageUri }, appSettings)): {
            name: k
            value: union({ AOL_PACKAGE_URL: packageUri }, appSettings)[k]
          }]
        }
      ]
    }
  }
}

output jobName string = job.name
output principalId string = job.identity.principalId
