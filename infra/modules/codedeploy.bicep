// Deploys the collector code to the Flex Consumption app from a public zip package URL (OneDeploy extension) with remote build.
// Depends (in main.bicep) on the role assignments and the slower modules so the identity's storage roles have propagated.
param functionAppName string
param packageUri string

resource app 'Microsoft.Web/sites@2023-12-01' existing = {
  name: functionAppName
}

resource onedeploy 'Microsoft.Web/sites/extensions@2023-12-01' = {
  parent: app
  name: 'onedeploy'
  #disable-next-line BCP187 // the extension's properties are not in the published type definition but are documented for OneDeploy
  properties: {
    packageUri: packageUri
    remoteBuild: true
  }
}
