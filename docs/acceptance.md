# Acceptance status (sandbox, 17 Nov 2026)

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | `bicep build` and lint clean; what-if only expected resources; second deploy no changes | Met | `az bicep build`/`lint` clean; first what-if listed 20 expected creates; after deploy a second what-if shows no create/modify (2 "unsupported" = role assignments whose principal id is only known at deploy time) |
| 2 | Count parity (ledger >= ARG) | Met | `python tools\check_parity.py`: ARG 15, REST 53 (365 d), ledger 53 distinct tracking ids |
| 3 | Idempotency | Met | `python tools\check_idempotency.py`: second run of pirs/arg/rest/activity/inventory appended raw rows but every `AzMaintenance_*` function returned identical row counts (Events 53, EventServices 1803, ResourceIntervals 82, PirBaseline 79, Catalog 60, Planned 7, inventory 48) |
| 4 | PIR parser | Met | `tests/unit/test_pirs.py`: 79/80 fixtures parse on their own, 80/80 with overrides, both title styles and both date formats; 0 of 79 live PIRs unparsed |
| 5 | Interval tests | Met | `tests/unit/test_intervals.py` (open, duplicate Active, out-of-order, user-initiated excluded, Unknown skipped, overlapping merge, edge clipping, stale open) and the same cases in KQL on synthetic data |
| 6 | SLA vectors in Python and KQL | Met | `tests/unit/test_sla_classify.py`; `tools/run_kql_checks.py` (`AzMaintenance_CompositeSla`) |
| 7 | Forecast | Met | `tests/unit/test_forecast.py` (seeded RNG; every row has n, window, confidence; thin history = insufficient) |
| 8 | Workbook deploys; queries run without error; empty states | Met with a gap | Deployed (10 pages); `tools\run_kql_checks.py --synthetic`: 53/53 (all functions, all workbook queries, SLA vectors, synthetic scenario assertions). Every tile has an empty-state message in the template. **Not opened in the portal** (see decisions D-14) |
| 9 | Security | Met | `tools\secret_scan.py` 0 findings, wired into CI; managed identity only; storage shared key off; RBAC in docs/architecture.md |
| 10 | Cost after 7 days | **Open** | ledger is hours old; see docs/cost.md |
| 11 | README | Met | Mermaid diagram, deploy, runbook, add subscriptions, caveats, uninstall |

Open items: (a) the collector job's first-run bootstrap inside Azure has to be confirmed end to end after the next deployment (D-21); (b) ServiceHealth rows in `AzureActivity` and VM annotations unverified with live rows (D-16, A3.1); (c) 7-day cost measurement; (d) `AzureActivity` retention billing beyond 90 days.
