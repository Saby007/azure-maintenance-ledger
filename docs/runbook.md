# Runbook

## Daily health

1. Open the Workbook -> **9 Data health**. Every enabled source should show `OK` with a last success within 36 h; "PIR window parse failures" should be 0; "subscriptions covered vs configured" should match.
2. The log alert `aol-stale-ingest` fires when an enabled collector has no `success`/`partial` run for 36 h (`servicehealth_events`, `inventory`, `forecast`, plus `public_pirs`, `vm_annotations` when enabled). Set `alertEmail` at deploy to create the action group.

## Symptoms

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| Source STALE | timer failed or function cannot reach storage/ARG | Function app -> Monitor -> Invocations; check the identity still has Reader and the storage roles; re-run locally: `python -m collector.backfill --only arg,inventory` |
| No `AzureActivity` ServiceHealth/ResourceHealth rows | export missing, or no events yet | `az monitor diagnostic-settings subscription list`; rows only arrive when a new event occurs. Backfill the last 89 days: `--only activity` |
| ARG returns 429 | > ~15 queries / 5 s | the client backs off automatically; re-run later |
| PIR count dropped to 0 | endpoint changed (undocumented) | use a manual import: `python -m collector.backfill --only pirs --pir-file my_pirs.csv` (columns date `MM/DD/YYYY`, title, tracking_id, text) |
| A PIR has `parse_status = unparsed` | new sentence style | add the window to `reference/pir_overrides.csv`, re-run `--only pirs` (overrides always win) |
| Availability looks too low | open Resource Health intervals | Resources page, filter `is_open`; stale ones (> 3 days) are excluded automatically |
| "SLA not set" everywhere | catalog has no SLA values | fill `sla_percent`, `sla_source_url`, `sla_verified_on` in `reference/service_catalog.csv`, then `python tools\load_reference.py` |
| Workbook query error | function missing or renamed | `python tools\run_kql_checks.py`; redeploy with `scripts\deploy.ps1` |

## Routine tasks

- **Backfill / re-ingest**: safe to repeat; rows are idempotent (`row_key`) and the functions deduplicate. `python tools\check_idempotency.py` proves it.
- **Change the taxonomy or SLA table**: edit `reference/service_catalog.csv`, then `python tools\load_reference.py` (a new load replaces the previous one in `AzOutage_Catalog()`).
- **Recompute planning ranges**: `python -m collector.backfill --only forecast` (also runs daily in the Function app).
- **Regenerate the Workbook** after editing `kql/workbook/*.kql` or `tools/build_workbook.py`: `python tools\build_workbook.py` then `scripts\deploy.ps1`.
- **Quarterly report**: `python -m reporting.render_report --days 90`.
- **Cost check**: `scripts\cost-report.ps1` (billable GB from `Usage`, monthly estimate); flag anything above US$10/month.

## Deleting the data

Custom-table rows can be removed with the workspace purge API or by dropping the table; shorten retention (`retentionDays`) to age data out. Synthetic rows (`is_synthetic = true`) are harmless and filtered from every production function.
