# Cost

Target: single-digit US dollars per month. Serverless, Analytics-plan tables only, no always-on compute, no Application Insights, no Premium plans, no private endpoints (unless parameterised).

## Cost drivers

| Item | Basis | Expected |
|------|-------|----------|
| `AzureActivity` (ServiceHealth + ResourceHealth export) | ingestion free; first 90 days of retention free; retention beyond 90 days **not yet measured** (docs ambiguous, see decisions A3.8) | US$0 for the first 90 days |
| Custom tables (9) | pay-as-you-go ingestion; Analytics plan; 730-day retention (data beyond 31 days is billed per GB-month) | see "Measured" |
| Function app (Flex Consumption, 512 MB, on-demand) | 5 timers; a few invocations per day | inside the monthly free grant (not measured, see below) |
| Storage account (package + watermark table) | a few MB, a few thousand transactions | cents |
| Scheduled-query alert (hourly) | one rule | roughly US$0.5-1.5/month; confirm current Azure Monitor pricing |
| Workbook, budget, KQL functions, DCR | no charge | US$0 |
| Workspace daily cap | 0.5 GB/day hard cap | bounds the worst case: 15 GB/month |

## Measured so far (sandbox, first day, 17 Nov 2026)

Sources: `scripts/cost-report.ps1` (Usage table, `IsBillable == true`).

| Table | Billable GB (first day) |
|-------|--------------------------|
| AzPublicPirs_CL (79 PIRs, full body text) | ~0.0006 |
| AzOutageIngestHealth_CL | ~0.000001 |
| Others (events, inventory, Resource Health backfill, catalog, forecast) | not yet reported by `Usage` at the time of writing (Usage lags ingestion by hours); each is a few hundred KB |

Projection (before pricing): the full backfill (79 PIRs, 68 events, 407 Resource Health rows, 47 inventory rows, 45 catalog rows, 366 forecast rows) is well under 5 MB. Daily steady state per subscription: 47 inventory rows (~16 KB), changed events only (watermark), 4-6 health rows. Even a 100-subscription estate with ~500 type/region combinations each is ~17 MB/day (~0.5 GB/month, ~US$1.4/month at US$2.76/GB).

## What is still open

- **Acceptance 10 (7-day measurement) is not met yet**: the ledger is hours old. After 7 days run `scripts\cost-report.ps1 -Days 7`, paste the result here and flag anything above US$10/month.
- Function executions and storage transactions are not measured because the Function app cannot run in the sandbox (policy blocks its storage; decisions D-17).
- `AzureActivity` retention billing beyond 90 days needs real rows and time (A3.8).
- If private networking is added for locked-down subscriptions (VNet integration + 3 private endpoints), budget roughly US$20+/month for the endpoints alone; that exceeds the target and is deliberately not part of the default deployment.
