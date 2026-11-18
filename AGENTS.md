# Azure Maintenance Ledger - standing rules and validated facts

## A1. Definitions
- Unplanned = Service Health ServiceIssue events (Activity Log incidentType Incident), plus Resource Health downtime not explained by a planned event. Planned = Service Health PlannedMaintenance (incidentType Maintenance), or a VM annotation with category Planned.
- Event window (impactStart to impactMitigation) is exposure, not customer downtime. Planned windows are scheduled windows (observed: 14 days = 336 h), never downtime. Downtime = minutes a resource was Unavailable per Resource Health. Never add exposure and downtime into one number.
- User-initiated and VM-initiated unavailability (stop, deallocate) is excluded from downtime. Degraded is reported separately from Unavailable.
- "Expected downtime" = observed history plus a planning range that always shows sample size, window and confidence. It is evidence, not a forecast or guarantee.
- The IaaS / PaaS / Network / Identity / AI / Data taxonomy is an editable file (reference/service_catalog.csv), proposed by you and confirmed by the customer. SLA percentages are never invented: blank until supplied with sla_source_url and sla_verified_on.

## A2. Validated facts (tested on live Azure 16-17 Nov 2026, or confirmed in Microsoft Learn)
Retention
- Service Health: the portal keeps events 90 days after they go inactive; REST returns up to 1 year but defaults to the last 3 days (by lastUpdateTime) unless queryStartTime is set. Planned maintenance moves to history at its end date or 50 days after start.
- Resource Health: 30 days in the portal. Events reach the Activity Log when an annotation is submitted, a resource transitions to or from Unhealthy, or it stays Unhealthy > 15 min. Transitions to Unknown, and VM blips < 35 s, are not recorded.
- AzureActivity table: ingestion is free and the first 90 days of retention are free. Retention beyond 90 days: the docs are ambiguous (data with _IsBillable == false is not charged for retention), so measure it. Analytics-plan tables are not charged per query.
- ServiceHealth events reach a subscription only if it has a resource the event could impact.

Azure Resource Graph (ARG)
- Table ServiceHealthResources, type microsoft.resourcehealth/events (and .../events/impactedresources). ImpactStartTime, ImpactMitigationTime and LastUpdateTime are .NET ticks (long): use `todatetime(tolong(properties.X))`. properties.Impact is a JSON string: `parse_json(tostring(properties.Impact))` gives ImpactedService and ImpactedRegions[].ImpactedRegion/Status. Observed EventType: ServiceIssue, PlannedMaintenance, HealthAdvisory, SecurityAdvisory. Status: Active/Resolved.
- The same TrackingId can appear once per subscription (duplicate rows seen with two subscriptions in scope). Count events with dcount(tracking_id); dedupe rows by (subscription_id, tracking_id, last_update).
- ARG depth is not guaranteed: in a test tenant the oldest LastUpdateTime was ~7 months old (oldest ImpactStart ~20 months). Snapshot daily.
- HealthResources (VMs only): availabilitystatuses and resourceannotations. Annotation fields: category (Planned|Unplanned|Not Applicable|Null), context (Platform-Initiated|User-initiated|VM-initiated), annotationName, reason, occurredTime. Latest state plus 14-day change tracking only.
- Limits: 1,000 rows per page (paginate with $skipToken); ~15 queries per 5 s per user (back off on 429); at most 1,000 subscriptions per request (batch, or use managementGroups scope).

Activity Log event shapes (observed)
- ResourceHealth: status Active|Updated|Resolved; properties title, details, currentHealthStatus, previousHealthStatus, type (Downtime|Unknown), cause (PlatformInitiated|UserInitiated|Unknown); resourceType and resourceId present. Observed pair: Active (Available -> Unavailable, type Downtime) then Resolved (Unavailable -> Available) 5 min later. No Planned/Unplanned flag in observed events (the docs sample shows healthEventCategory; do not rely on it).
- ServiceHealth: properties include trackingId, incidentType (docs: ActionRequired|Incident|Maintenance|Information|Security), stage, service, region, title, impactStartTime, impactedServices (JSON string), endTime, maintenanceId, maintenanceType, eventTags, isHIR. impactMitigationTime was 'None' on an Active event. Each update is a separate record.

Public PIRs (undocumented endpoint: treat as fragile)
- GET https://azure.status.microsoft/en-us/statushistoryapi/?serviceSlug=all&regionSlug=all&startDate=all&page={n}&shdrefreshflag=true returns an HTML fragment with 10 PIRs per page. 8 pages = 80 PIRs, 2021-11-09 to 2026-09-30. Selectors: div.incident-history-item; span.hide-text (MM/DD/YYYY); div.incident-history-title; div.incident-history-tracking-id; div.incident-history-collapse (body text).
- Only broad-impact incidents get public PIRs: 24 in 2022, 13 in 2023, 15 in 2024, 13 in 2025, 9 in 2026 so far. Titles changed from "RCA - ..." to "Post Incident Review (PIR) - ...".
- A regex on the first "Between/From <time> ... <date>" sentence parsed 77 of 80 windows: median 8.6 h, mean 13.3 h, P90 29.2 h, max 72 h. Known unparsed: 1VT1-LX0, FTVR-L9Z, VVTQ-J98 (regression fixtures; resolve via reference/pir_overrides.csv). Reuse poc/fetch_pirs.py, poc/analyze_pirs.py and poc/pirs.json.

Platform
- Subscription-scope Bicep: Microsoft.Insights/diagnosticSettings@2021-05-01-preview with logs [{category:'ServiceHealth',enabled:true},{category:'ResourceHealth',enabled:true}] only.
- Logs Ingestion API: a DCR with kind 'Direct' exposes its own logsIngestion endpoint (no DCE unless Private Link). The identity needs Monitoring Metrics Publisher on the DCR.
- Workbook: Microsoft.Insights/workbooks@2023-06-01, kind 'shared', required category, displayName and serializedData (JSON string); sourceId = workspace resource ID; name = deterministic GUID. Viewers need Reader on the workbook and on the resources it queries.
- Collector hosting (supersedes the Flex Consumption rule, see docs/decisions.md D-17/D-21): Azure Container Apps Job on the consumption profile, no storage account (a tenant policy can force public network access off on storage, which breaks Azure Functions). Schedules are UTC cron. If Functions are ever used again: Flex Consumption (Linux Consumption retires 30 Sep 2028); timer triggers on Linux Flex ignore WEBSITE_TIME_ZONE/TZ.
- SLA maths test vectors: 99.9% = 8.76 h/yr; 99.95% = 4.38 h/yr; 99.99% = 52.56 min/yr; serial 99.95% x 99.99% = 99.940005% = 5.26 h/yr; two 99.9% in parallel = 99.9999% = 31.5 s/yr.

## A3. Verify first (not yet tested) - record evidence in docs/decisions.md
1. AzureActivity column names for ResourceHealth/ServiceHealth rows (run getschema and a sample; Properties vs Properties_d, EventDataId, CorrelationId).
2. impactedresources property names (the docs list a misspelt "staus").
3. Whether the `scan` operator works in Azure Monitor Logs; otherwise sessionise with serialize + prev()/next().
4. Flex Consumption (no longer used by the collector, see D-17/D-21): supported Python versions, free grant, identity-based storage access and the roles it needs, instance-size and max-instance settings.
5. Custom tables (Microsoft.OperationalInsights/workspaces/tables) and Direct-DCR stream declarations in Bicep.
6. Existing diagnostic settings (and the per-subscription limit) on each target subscription before adding one.
7. Acceptable use of the public status-history endpoint with the customer. Keep the PIR module optional behind an interface so it can be replaced by a manual CSV import.
8. Retention billing of AzureActivity beyond 90 days (raise retention in the sandbox, then check Usage and _IsBillable).

## A4. Engineering rules
- Python: typed, ruff clean, pytest for all logic; retries with exponential backoff and jitter; structured logs with no PII; UTC ISO-8601 everywhere (convert ticks inside the ARG query).
- Ingestion is idempotent and append-only: row_key = sha256(source|subscription_id|key|last_update); watermarks and step markers in the ingest-health table (state:<key> rows), not Table Storage; KQL functions dedupe with `arg_max(ingested_utc, *) by row_key`.
- All KQL lives in kql/*.kql with a header (purpose, inputs, outputs) and is deployed as workspace functions (savedSearches with functionAlias). No inline KQL in Python except text loaded from those files.
- Synthetic test rows carry is_synthetic=true and every production function filters them out.
- Security: managed identity only; no keys, SAS tokens or connection strings; storage shared-key access disabled where supported; least privilege (Reader on the target scope, Monitoring Metrics Publisher on the DCR, Log Analytics Reader for reporting).
- Cost: dedicated or existing workspace (parameter); Analytics-plan tables; retention parameter; workspace daily cap; budget alert; Container Apps Job on the consumption profile (no always-on compute, no storage account), smallest size; no Application Insights.
- No customer data in the repo. Fixtures are public PIRs or synthetic. .gitignore covers .env, local.settings.json and exports.
- Be polite to the status site: >= 1 s between requests, identify the tool in User-Agent, cache raw HTML, monthly after the backfill.

## Working rules
- Azure safety: read-only by default; confirm `az account show`; run `what-if` before any deployment; deploy only to the sandbox subscription in .env; never delete or overwrite an existing diagnostic setting; ask before granting roles or touching a customer subscription; no secrets in files, logs or chat.
- Stack: Python, Bicep, KQL, PowerShell 7, pytest, ruff. Dev machine is Windows ARM64: prefer pure-Python / ARM64-wheel dependencies.
