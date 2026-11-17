# Azure Outage Ledger - build prompt

How to use: open this folder in VS Code (poc/ is already here), start Copilot Chat in Agent mode, and paste everything below the line. The prompt makes the agent write AGENTS.md itself, so later sessions inherit the facts and rules.

---

## ROLE
You are a senior Azure platform and data engineer. Build "Azure Outage Ledger" (repo name: azure-outage-ledger) in this folder. Be concise and evidence-first; no marketing language.

## GOAL
A customer wants to know the planned and unplanned outages of Azure IaaS and PaaS services, and the downtime to expect, from history. No Microsoft tool does this. Build a low-cost utility, deployed in the customer's own tenant, that:
1. Keeps a durable ledger of Service Health events, Resource Health downtime and public Azure PIRs. Azure itself keeps only 90 days to 1 year.
2. Separates planned from unplanned, IaaS from PaaS, and event window (exposure) from downtime (resource unavailable).
3. Reports observed availability against SLA and an evidence-based expected-downtime range (P50/P90 per year) with sample size and confidence.
4. Costs single-digit US dollars per month: serverless, Analytics-plan tables only, no always-on compute, no Application Insights, no Premium plans, private endpoints only if parameterised.
v1 front end = Azure Workbook plus a quarterly static HTML/XLSX report. A custom web app is out of scope.

## DEFAULTS (use unless I say otherwise)
Scope: every subscription the deploying identity can read, listed in config/subscriptions.json. Workspace: new and dedicated (aol-law), 730-day retention, 0.5 GB/day cap. Resource prefix: aol. Modules: public PIRs on, VM annotations on, quarterly report on. Region: the sandbox resource group's region. Taxonomy: your proposal in reference/service_catalog.csv, SLA values blank.

## HOW TO WORK
1. First reply only: a one-page plan, the repo tree, key risks, and at most 5 clarifying questions, each with the default you will use if I do not answer. Then stop.
2. After I approve: write Part A verbatim to AGENTS.md and Part E to docs/method.md, then build in the phases of Part G. After each phase report files changed, commands run with real output, what you verified, and what is left. Then stop and wait for "continue".
3. Never invent data, API fields, SLA percentages or portal steps. Everything under "Verify first" must be checked against the sandbox or Microsoft Learn and recorded with evidence in docs/decisions.md.
4. Azure safety: read-only commands by default; run `az account show` and confirm the subscription before any deployment; run `what-if` first; deploy only to the sandbox subscription in .env (ask me for it); never delete or overwrite an existing diagnostic setting; ask before granting any role or touching a customer subscription; no secrets in files, logs or chat.
5. Stack: Python (latest GA version supported by Azure Functions Flex Consumption), Bicep, KQL, PowerShell 7, pytest, ruff. Ask before adding any other service or language.
6. The dev machine is Windows on ARM64 (Python 3.13 arm64, PowerShell 7 and Azure CLI installed): prefer pure-Python or ARM64-wheel dependencies, and verify a tool runs before relying on it.

## PART A - STANDING RULES AND VALIDATED FACTS (write verbatim to AGENTS.md)

### A1. Definitions
- Unplanned = Service Health ServiceIssue events (Activity Log incidentType Incident), plus Resource Health downtime not explained by a planned event. Planned = Service Health PlannedMaintenance (incidentType Maintenance), or a VM annotation with category Planned.
- Event window (impactStart to impactMitigation) is exposure, not customer downtime. Planned windows are scheduled windows (observed: 14 days = 336 h), never downtime. Downtime = minutes a resource was Unavailable per Resource Health. Never add exposure and downtime into one number.
- User-initiated and VM-initiated unavailability (stop, deallocate) is excluded from downtime. Degraded is reported separately from Unavailable.
- "Expected downtime" = observed history plus a planning range that always shows sample size, window and confidence. It is evidence, not a forecast or guarantee.
- The IaaS / PaaS / Network / Identity / AI / Data taxonomy is an editable file (reference/service_catalog.csv), proposed by you and confirmed by the customer. SLA percentages are never invented: blank until supplied with sla_source_url and sla_verified_on.

### A2. Validated facts (tested on live Azure 16-17 Nov 2026, or confirmed in Microsoft Learn)
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
- Functions: use Flex Consumption (Linux Consumption retires 30 Sep 2028). Timer triggers on Linux Flex ignore WEBSITE_TIME_ZONE/TZ: use UTC cron.
- SLA maths test vectors: 99.9% = 8.76 h/yr; 99.95% = 4.38 h/yr; 99.99% = 52.56 min/yr; serial 99.95% x 99.99% = 99.940005% = 5.26 h/yr; two 99.9% in parallel = 99.9999% = 31.5 s/yr.

### A3. Verify first (not yet tested)
1. AzureActivity column names for ResourceHealth/ServiceHealth rows (run getschema and a sample; Properties vs Properties_d, EventDataId, CorrelationId).
2. impactedresources property names (the docs list a misspelt "staus").
3. Whether the `scan` operator works in Azure Monitor Logs; otherwise sessionise with serialize + prev()/next().
4. Flex Consumption: supported Python versions, free grant, identity-based storage access and the roles it needs, instance-size and max-instance settings.
5. Custom tables (Microsoft.OperationalInsights/workspaces/tables) and Direct-DCR stream declarations in Bicep.
6. Existing diagnostic settings (and the per-subscription limit) on each target subscription before adding one.
7. Acceptable use of the public status-history endpoint with the customer. Keep the PIR module optional behind an interface so it can be replaced by a manual CSV import.
8. Retention billing of AzureActivity beyond 90 days (raise retention in the sandbox, then check Usage and _IsBillable).

### A4. Engineering rules
- Python: typed, ruff clean, pytest for all logic; retries with exponential backoff and jitter; structured logs with no PII; UTC ISO-8601 everywhere (convert ticks inside the ARG query).
- Ingestion is idempotent and append-only: row_key = sha256(source|subscription_id|key|last_update); watermarks in Table Storage; KQL functions dedupe with `arg_max(ingested_utc, *) by row_key`.
- All KQL lives in kql/*.kql with a header (purpose, inputs, outputs) and is deployed as workspace functions (savedSearches with functionAlias). No inline KQL in Python except text loaded from those files.
- Synthetic test rows carry is_synthetic=true and every production function filters them out.
- Security: managed identity only; no keys, SAS tokens or connection strings; storage shared-key access disabled where supported; least privilege (Reader on the target scope, Monitoring Metrics Publisher on the DCR, Log Analytics Reader for reporting).
- Cost: dedicated or existing workspace (parameter); Analytics-plan tables; retention parameter; workspace daily cap; budget alert; Flex Consumption on-demand only (no always-ready), smallest instance size; no Application Insights.
- No customer data in the repo. Fixtures are public PIRs or synthetic. .gitignore covers .env, local.settings.json and exports.
- Be polite to the status site: >= 1 s between requests, identify the tool in User-Agent, cache raw HTML, monthly after the backfill.

## PART B - SCOPE
MUST: Activity Log export (ServiceHealth + ResourceHealth only) to the workspace; ARG collectors for Service Health events and impacted resources; daily inventory counts (denominators); backfill (ARG, REST with queryStartTime = now - 365 d, public PIRs); Resource Health interval builder; planned/unplanned classification; observed availability vs SLA; expected-downtime planner; Workbook; data-health tab and alert; IaC and deploy scripts; tests; README and runbook.
SHOULD: VM annotation collector (Planned/Unplanned for IaaS); one-time Activity Log backfill (last 89 days) into AzResourceHealthEvents_CL; quarterly HTML + XLSX report; composite SLA calculator.
COULD: aggregated JSON export so a web UI can be added later; Teams/email data-health notification.
WON'T (v1): custom web app, real-time alerting (document Service Health alerts instead), ITSM integration, multi-tenant, forecasts presented as guarantees.

## PART C - ARCHITECTURE AND SCHEDULE
Flow: sources -> collectors -> Log Analytics -> KQL functions -> Workbook, report, forecast.
- Activity Log (ServiceHealth, ResourceHealth) -> subscription diagnostic setting -> AzureActivity (raw, free ingestion).
- ARG ServiceHealthResources, HealthResources and resources(count) -> Function timers -> Logs Ingestion API (Direct DCR) -> custom tables.
- Public PIR pages -> monthly Function -> AzPublicPirs_CL.
- reference/service_catalog.csv -> tools/load_reference.py -> AzServiceCatalog_CL.
- KQL functions: AzOutage_Events(), AzOutage_EventServices(), AzOutage_ResourceIntervals(), AzOutage_Availability(windowDays:int), AzOutage_Planned(), AzOutage_PirBaseline(), AzOutage_DataHealth(). Event source precedence: arg > rest > activitylog.
- Schedules (UTC, idempotent): Service Health + impacted resources daily 02:15; inventory counts daily 02:45; forecast daily 03:15; VM annotations every 6 h (feature flag); public PIRs monthly on day 2 at 03:00. Every run writes a row to AzOutageIngestHealth_CL. Log alert: no successful run of any enabled collector in 36 h -> action group (parameter).

## PART D - DATA MODEL
Every custom table (Analytics plan) also has TimeGenerated (= ingestion time), ingested_utc, row_key, is_synthetic.
- AzSvcHealthEvents_CL: subscription_id, tracking_id, event_type, status, level, title, summary, impact_start_utc, impact_end_utc, last_update_utc, platform_initiated, tags, services (dynamic), regions (dynamic), source (arg|rest|activitylog).
- AzSvcHealthImpacted_CL: subscription_id, tracking_id, resource_id, resource_type, resource_name, region, maintenance_start_utc, maintenance_end_utc, status.
- AzVmAnnotations_CL: subscription_id, resource_id, region, annotation_name, category, context, reason, availability_state, previous_availability_state, occurred_utc, summary.
- AzResourceHealthEvents_CL (Activity Log backfill, same shape as the AzureActivity ResourceHealth rows): event_data_id, resource_id, resource_type, subscription_id, status, current_status, previous_status, type, cause, event_utc.
- AzInventoryCounts_CL: snapshot_date, subscription_id, resource_type, region, resource_count.
- AzPublicPirs_CL: tracking_id, published_date, title, body_text, window_start_utc, window_end_utc, duration_h, parse_status (ok|manual|unparsed), parse_note, category, source_url, raw_hash.
- AzServiceCatalog_CL: service_name, arm_resource_types, category, sla_percent, sla_source_url, sla_verified_on, notes.
- AzOutageForecast_CL: computed_utc, scope_level (service_region|service|category), scope_key, window_days, n_events, events_per_year, mean_annual_h, p50_annual_h, p90_annual_h, duration_basis (resource_health|service_health), confidence (insufficient|low|medium|high), baseline (customer|public_pir).
- AzOutageIngestHealth_CL: run_id, source, started_utc, finished_utc, rows_read, rows_written, watermark_utc, status, errors (dynamic).

## PART E - METHOD (also write to docs/method.md)
1. Intervals. Resource Health: per resourceId, order events by time; open an interval when currentHealthStatus becomes Unavailable (type Downtime) from a non-Unavailable state; close it on Available. Ignore duplicate Active/Updated rows and Unknown states. Open intervals end at now() and are flagged open. Merge overlapping intervals per resource before summing. Exclude cause = UserInitiated.
2. Classification. Service Health: ServiceIssue/Incident -> unplanned; PlannedMaintenance/Maintenance -> planned. Resource Health interval: VM annotation category if present; else planned if it overlaps a PlannedMaintenance window for the same subscription, service and region; else unplanned. Always store classification_basis (vm_annotation | overlaps_planned_event | default).
3. Event counting. One event per TrackingId in totals (dcount). Expand services and regions only for per-service and per-region views, and never sum those rows into a total.
4. Observed availability = 1 - sum(merged downtime minutes) / (resource_count x window minutes), with resource_count from the latest AzInventoryCounts_CL. Mark as approximate when resources were created or deleted in the window.
5. SLA allowance = (1 - sla) x window minutes, only where sla_percent is set; otherwise show "SLA not set".
6. Planning range (analytics/forecast.py, run daily). Scope fallback: service+region, then service, then category. Window W = trailing 365 days (minimum 90). n = distinct unplanned events; lambda = n / (W/365). Durations = Resource Health impact minutes per event where available, else Service Health exposure minutes; label which. Simulate 10,000 years: N ~ Poisson(lambda), sum N durations drawn with replacement; report mean, P50 and P90 annual hours. Confidence (heuristic, configurable in config/forecast.yaml): insufficient if n < 3 or W < 90 d; low if n is 3-5 or W < 365 d; medium if n is 6-11; high if n >= 12 and W >= 365 d. For insufficient and low, also show the public-PIR baseline, labelled "Azure-wide, not your estate". Never print a single number without n, window and confidence.
7. Planned maintenance: report notices per year, scheduled window, notice lead time (publication to window start), and realised downtime from Resource Health overlap (or "not measured").
8. Composite SLA: serial = product of availabilities; redundant = 1 - product of (1 - availability). Python (analytics/sla.py) and KQL must both pass the A2 test vectors.
9. PIR windows: parse the first "Between/From <time> ... <date>" sentence: two HH:MM UTC times and one or two dates ("30 September 2026" and "September 30, 2026"); if there is one date and end < start, roll the end to the next day; reject windows longer than 14 days; set parse_status ok or unparsed; reference/pir_overrides.csv can supply a window (parse_status manual).

## PART F - WORKBOOK AND REPORT
Workbook: generated by tools/build_workbook.py into workbook/workbook.template.json (diffable) and deployed by Bicep. Parameters: TimeRange, Subscriptions, Category, Service, Region, IncludeUserInitiated (default off). Pages:
1. Overview: events in 12 months (planned vs unplanned), exposure hours, observed downtime minutes, availability, open events.
2. Timeline: events and downtime by month, planned vs unplanned.
3. Services: IaaS/PaaS table with events, exposure P50/P90, downtime, availability vs SLA.
4. Regions.
5. Resources: drill-down to downtime intervals.
6. Planned maintenance: upcoming and history, notice lead time, reboot required for VMs.
7. Public PIR benchmark (labelled Azure-wide).
8. Expected-downtime planner: service, region, horizon; P50/P90, confidence, SLA allowance, composite SLA inputs.
9. Data health: last ingest per source, coverage start dates, parse failures, subscriptions covered vs configured.
10. Method and caveats.
Every tile shows an empty-state message, never a raw query error.
Report: src/reporting/render_report.py produces a self-contained HTML (inline CSS/JS/SVG, no CDN) and an XLSX (summary sheet plus one sheet per function), from the AzOutage_* functions via azure-monitor-query. Methodology and caveats on page 1.

## PART G - REPO LAYOUT, IAC AND PHASES
Layout: AGENTS.md, README.md, .env.example, config/ (subscriptions.json, forecast.yaml), docs/ (architecture, method, decisions, runbook, cost), infra/ (main.bicep, modules/, schemas/, parameters example), kql/, src/collector/ (function_app.py, sources/, ingest.py, state.py, health.py), src/analytics/ (intervals.py, classify.py, availability.py, forecast.py, sla.py), src/reporting/, tools/ (build_workbook.py, load_reference.py, seed_fixtures.py, run_kql_checks.py), workbook/, reference/ (service_catalog.csv, pir_overrides.csv), scripts/, tests/ (unit/, fixtures/), poc/ (existing), .github/workflows/ci.yml (ruff, pytest, bicep build, secret scan; no deploy job).
IaC (Bicep, no Terraform): main.bicep with modules for workspace, tables, DCR (kind Direct), function app (Flex Consumption, system-assigned identity, storage with shared-key off where supported), RBAC, per-subscription Activity Log export (targetScope subscription, ServiceHealth + ResourceHealth only, setting name aol-export), workbook, KQL functions, optional alert and budget. Parameters: location, prefix, workspace mode (new|existing), retention days, daily cap, alert email, module flags.
Scripts: deploy.ps1 (what-if switch), enable-export.ps1 (loops config/subscriptions.json; inspects existing diagnostic settings first; skips with a warning at the limit), grant-reader.ps1 (prints the role assignments; applies only with -Apply after confirmation), backfill.ps1, cost-report.ps1 (billable GB from Usage and a monthly estimate).

Phases (stop after each):
- P0 Foundation and first data: scaffold; AGENTS.md and docs/method.md; infra for workspace, tables, DCR and Activity Log export; PIR fetch, parse and ingest (productionise poc/, with tests); KQL functions v1 (events, PIR baseline, data health); deploy to the sandbox; show one real query result.
- P1 Collectors and Workbook v1: Function app (ARG events, impacted resources, inventory; state; health rows); backfill CLI (ARG, REST with queryStartTime = now - 365 d, PIRs); Resource Health interval builder and classification; VM annotation module behind a flag; Workbook pages 1-6, 9, 10; stale-ingest alert; unit and KQL fixture tests.
- P2 Planning ranges and reporting: forecast module and planner page; service catalog and composite SLA calculator; PIR benchmark page; Activity Log backfill (89 days); quarterly HTML + XLSX report; cost report; README, runbook and diagrams; final acceptance run.
- P3 (only if I ask): aggregated JSON export and a web UI.

## PART H - ACCEPTANCE CRITERIA
1. `bicep build` and lint are clean; `what-if` shows only expected resources; a second deploy makes no changes.
2. Count parity: after backfill, distinct tracking_id in the ledger >= distinct tracking_id returned by ARG for the same scope (script prints both, plus the REST count).
3. Idempotency: running each collector twice adds 0 rows to the deduplicated function output.
4. PIR parser: >= 77 of the 80 poc fixtures parse (target >= 95%); the 3 known unparsed resolve via overrides; tests cover both title styles and both date formats.
5. Interval tests pass for: open incident, duplicate Active, out-of-order rows, user-initiated excluded, Unknown skipped, overlapping merge, interval crossing the window edge.
6. SLA test vectors pass in Python and KQL.
7. Forecast: unit tests with a seeded RNG; every output row has n, window and confidence; thin history shows "insufficient".
8. Workbook deploys; tools/run_kql_checks.py runs every workbook query against the sandbox with seeded synthetic data and none errors; empty states render.
9. Security: no secrets or keys in the repo (secret scan in CI); managed identity only; least-privilege RBAC documented.
10. Cost: after 7 days, a billable-GB report from Usage and a monthly estimate in docs/cost.md; flag anything above US$10/month.
11. README: Mermaid architecture diagram, deploy and runbook, how to add subscriptions, caveats, uninstall.

Begin with the first reply described in HOW TO WORK, item 1.
