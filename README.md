# Azure Outage Ledger

A low-cost utility, deployed in the customer's own tenant, that keeps a **durable ledger** of Azure Service Health events, Resource Health downtime and public Azure PIRs, separates **planned from unplanned** and **exposure (event window) from downtime (resource unavailable)**, and reports **observed availability against SLA** plus an **evidence-based expected-downtime range** (P50/P90 per year, always with sample size, window and confidence).

Azure itself only keeps 90 days to 1 year. The ledger keeps 730 days by default. Front end: an Azure Workbook plus a quarterly static HTML/XLSX report.

> Planning ranges are evidence from history, not a forecast or a guarantee. Read [docs/method.md](docs/method.md) and the caveats below before quoting numbers.

## One-click deployment

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2FSaby007%2Fazure-outage-ledger%2Fmain%2Finfra%2Fazuredeploy.json)

Click the button, sign in, pick the subscription and a region, review the parameters and select **Review + create**. One deployment creates, in your own subscription:

| What | Detail |
|------|--------|
| Resource group | `rg-azure-outage-ledger` (name is a parameter) |
| Log Analytics workspace + 9 custom tables | dedicated, 730-day retention, 0.5 GB/day cap |
| Direct DCR | Logs Ingestion API endpoint, no DCE |
| 10 KQL functions + the **Azure Outage Ledger Workbook** | ten tabs; open it from Azure Monitor -> Workbooks |
| Function app (Flex Consumption) | managed identity, identity-only storage, no Application Insights; **code deployed automatically** from [release/app.zip](release/app.zip) |
| Roles | Reader on the subscription, Monitoring Metrics Publisher on the DCR, Log Analytics Reader on the workspace, storage data roles |
| Activity Log export | ServiceHealth + ResourceHealth to the new workspace (diagnostic setting `aol-export`) |
| Stale-ingest alert | optional email via `alertEmail` |

On first start the Function loads the service catalog, public PIRs, the Service Health history (365 days through REST), the Resource Health history (89 days) and the resource inventory, then runs daily. **Expect data in the Workbook 10-20 minutes after the deployment finishes**; the *Data health* tab shows progress. The planning ranges appear after the first daily forecast run (03:15 UTC).

Requirements: **Owner** on the subscription (or Contributor plus User Access Administrator), because the template creates role assignments, and the `Microsoft.Web`, `Microsoft.Insights`, `Microsoft.OperationalInsights` and `Microsoft.Storage` resource providers registered (they are on by default in most subscriptions).

**Before you click**
- If the subscription already has a diagnostic setting named `aol-export` that points elsewhere, set `activityLogExportName` to another name (the template would overwrite it). Subscriptions are limited to 5 diagnostic settings.
- Some organisations block public access on storage accounts with Azure Policy. Flex Consumption needs the function app's storage to be reachable, so such a policy makes the code deployment step fail while everything else deploys. Ask for a policy exemption for the storage account, or deploy the code later from a machine that can reach it with `scripts\deploy-code.ps1`.
- Public PIR collection uses an undocumented Microsoft endpoint. Turn `enablePirs` off if that is not acceptable for your organisation.
- More subscriptions: pass them in `additionalSubscriptionIds`, then run `scripts\grant-reader.ps1` and `scripts\enable-export.ps1` for each one (see "Add a subscription").

Rebuild the button's files after changing the source: `az bicep build --file infra\azuredeploy.bicep --outfile infra\azuredeploy.json` and `scripts\build-package.ps1`, then commit `infra/azuredeploy.json` and `release/app.zip`.

## Architecture

```mermaid
flowchart LR
  subgraph Sources
    AL["Activity Log<br/>ServiceHealth + ResourceHealth"]
    ARG["Azure Resource Graph<br/>ServiceHealthResources, HealthResources, resources"]
    REST["Service Health REST<br/>(365-day backfill)"]
    PIR["Public PIRs<br/>(optional, monthly)"]
    REF["reference/service_catalog.csv"]
  end
  AL -- "diagnostic setting aol-export" --> AA[("AzureActivity<br/>raw, free ingestion")]
  ARG --> FN["Function app (Flex Consumption)<br/>timers, managed identity"]
  REST --> BF["backfill CLI"]
  PIR --> FN
  FN -- "Logs Ingestion API<br/>Direct DCR" --> T[("Custom tables _CL<br/>Analytics plan")]
  BF --> T
  REF -- "tools/load_reference.py" --> T
  AA --> F["KQL functions AzOutage_*"]
  T --> F
  F --> WB["Azure Workbook"]
  F --> FC["Daily forecast job"]
  FC --> T
  F --> RP["Quarterly HTML + XLSX report"]
```

Flow: sources -> collectors -> Log Analytics -> KQL functions -> Workbook, report, forecast. Details in [docs/architecture.md](docs/architecture.md).

## What it measures

| Term | Meaning |
|------|---------|
| Unplanned | Service Health `ServiceIssue`, plus Resource Health downtime not explained by a planned event |
| Planned | Service Health `PlannedMaintenance`, or a VM annotation with category Planned |
| Exposure | the event window (impact start to mitigation); **not** downtime |
| Downtime | minutes a resource was Unavailable per Resource Health (user-initiated excluded) |
| Expected downtime | observed history + a P50/P90 planning range with n, window and confidence |

## Deploy from the command line (sandbox or customer tenant)

The button above is the simplest route. For development, or to deploy into an existing resource group, use the scripts. Prerequisites: PowerShell 7, Azure CLI with Bicep, Python 3.11+ (3.13 tested). Sign in with `az login` to an identity that can create resources and diagnostic settings.

```powershell
copy .env.example .env                      # set AOL_SUBSCRIPTION_ID / AOL_RESOURCE_GROUP / AOL_LOCATION
az account show                              # confirm the subscription
.\scripts\deploy.ps1 -WhatIf                 # review
.\scripts\deploy.ps1                         # deploy (prints outputs: workspace id, DCR endpoint, ...)
# put workspace customer id, DCR endpoint and immutable id from the outputs into .env

.\scripts\enable-export.ps1 -WorkspaceResourceId <workspaceResourceId>   # Activity Log export, never overwrites existing settings
python tools\load_reference.py                                           # service catalog (edit reference/service_catalog.csv first)
.\scripts\backfill.ps1                                                   # PIRs, ARG, REST 365 d, Activity Log 89 d, inventory
python -m collector.backfill --only forecast                             # planning ranges
```

Your identity needs Monitoring Metrics Publisher on the DCR to ingest from your machine. For the Function app: `.\scripts\grant-reader.ps1 -PrincipalId <functionPrincipalId> [-Apply]` (Reader on each subscription), then `.\scripts\deploy-code.ps1 -FunctionApp <name>`.

The Workbook is deployed by `deploy.ps1` (Azure portal -> Monitor -> Workbooks -> "Azure Outage Ledger"). Viewers need Reader on the workbook and Log Analytics Reader on the workspace.

### Add a subscription

1. Add `{ "id": "<guid>", "name": "<label>" }` to [config/subscriptions.json](config/subscriptions.json).
2. `.\scripts\enable-export.ps1 -WorkspaceResourceId <id>` (checks existing diagnostic settings first; skips at the 5-setting limit).
3. `.\scripts\grant-reader.ps1 -PrincipalId <function identity> -Apply` (asks for confirmation).
4. `.\scripts\backfill.ps1` to load its history. The Data health page shows "subscriptions covered vs configured".

### Reports and checks

```powershell
python -m reporting.render_report --days 90            # reports\*.html and *.xlsx (self-contained, no CDN)
python tools\run_kql_checks.py [--synthetic]           # every function + workbook query against the workspace
python tools\seed_fixtures.py                          # synthetic rows (is_synthetic=true) for the checks
python tools\check_idempotency.py                      # two more collector runs add 0 rows to the deduplicated output
.\scripts\cost-report.ps1                              # billable GB and monthly estimate
pytest ; ruff check . ; python tools\build_workbook.py --check
```

Runbook: [docs/runbook.md](docs/runbook.md). Cost: [docs/cost.md](docs/cost.md). Evidence and decisions: [docs/decisions.md](docs/decisions.md).

## Caveats

- History starts when collection starts (plus whatever REST/ARG/Activity Log still hold). See the Data health page for coverage dates.
- Resource Health does not record transitions to Unknown or short blips, and is not a billing-grade availability measure.
- Resource Health intervals that stay open for more than 3 days are treated as stale (usually deleted resources) and excluded; see D-07 in the decisions file.
- Planned/unplanned classification of Resource Health intervals cannot use region (not present on those rows); VM annotations take precedence.
- Public PIRs come from an undocumented endpoint and cover broad-impact incidents only; they are labelled Azure-wide.
- SLA percentages are blank until you supply them with a source URL and verification date.
- Policies in managed subscriptions may block the Function app's storage (see D-17); the same collectors run from `python -m collector.backfill`.

## Uninstall

1. Remove the Activity Log export: `az monitor diagnostic-settings subscription delete --name aol-export --subscription <id> --yes` (leave any other setting alone).
2. Delete the resource group (`az group delete -n <rg>`), which removes the workspace (and the ledger), DCR, Function app, storage and Workbook.
3. Remove the Reader role assignments created for the Function identity (they disappear with the identity, but check subscription scope).

## Layout

`AGENTS.md` (rules and validated facts) | `config/` | `docs/` | `infra/` (Bicep) | `kql/` (workspace functions, `arg/`, `workbook/`, `queries/`, `report/`) | `src/collector` (Functions, sources, backfill CLI) | `src/analytics` (intervals, classify, availability, forecast, SLA) | `src/reporting` | `tools/` | `workbook/` | `reference/` | `scripts/` | `tests/` | `poc/` (original proof of concept)
