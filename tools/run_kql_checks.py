"""Runs every workbook query and every AzMaintenance_* function against the sandbox workspace and fails on any error.

  python tools/run_kql_checks.py [--synthetic] [--workspace <customerId>]

Queries are rendered with wbkql.TEST_TOKENS (all filters = All). With --synthetic the queries run with includeSynthetic=true so
rows loaded by tools/seed_fixtures.py are visible. Also verifies the SLA test vectors in KQL (AzMaintenance_CompositeSla).
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import wbkql  # noqa: E402

from collector.backfill import load_env  # noqa: E402
from collector.forecast_job import LogsReader  # noqa: E402

FUNCTIONS = [
    "AzMaintenance_Catalog({s})",
    "AzMaintenance_Events({s})",
    "AzMaintenance_EventServices({s})",
    "AzMaintenance_Planned({s})",
    "AzMaintenance_ResourceIntervals({s})",
    "AzMaintenance_Availability(365, false, {s})",
    "AzMaintenance_Availability(90, true, {s})",
    "AzMaintenance_PirBaseline({s})",
    "AzMaintenance_Forecast({s})",
    "AzMaintenance_DataHealth({s})",
]

SLA_VECTORS = [
    ("serial", [99.95, 99.99], 99.940005, 5.26, 0.01),
    ("redundant", [99.9, 99.9], 99.9999, 31.5 / 3600, 0.001),
    ("serial", [99.9], 99.9, 8.76, 0.001),
    ("serial", [99.95], 99.95, 4.38, 0.001),
    ("serial", [99.99], 99.99, 52.56 / 60, 0.001),
]


def check(reader: LogsReader, label: str, query: str, results: list) -> list[dict]:
    try:
        rows = reader.rows(query, days=800)
        results.append((label, "ok", len(rows)))
        return rows
    except Exception as exc:  # report, keep going
        results.append((label, "FAIL", str(exc)[:600]))
        return []


def assert_synthetic(reader: LogsReader, results: list) -> None:
    """Logic checks against the rows loaded by tools/seed_fixtures.py (scoped to the synthetic subscription)."""
    sub = "00000000-0000-0000-0000-00000000a0a0"

    def expect(label: str, cond: bool, info: object) -> None:
        results.append((f"assert:{label}", "ok" if cond else "FAIL", info))

    iv = reader.rows(f"AzMaintenance_ResourceIntervals(true) | where subscription_id == '{sub}'")
    expect("intervals present", len(iv) >= 7, len(iv))
    by_res = {r["resource_id"].rsplit("/", 1)[-1]: r for r in iv}
    expect("vm1 duplicate rows merged = 30 min", abs(by_res["vm1"]["minutes"] - 30) < 0.01, by_res["vm1"]["minutes"])
    expect("vm2 user-initiated flagged", by_res["vm2"]["user_initiated"] is True, by_res["vm2"]["user_initiated"])
    expect("vm3 Unknown skipped = 45 min", abs(by_res["vm3"]["minutes"] - 45) < 0.01, by_res["vm3"]["minutes"])
    expect("vm4 open and not stale", by_res["vm4"]["is_open"] and not by_res["vm4"]["stale_open"], by_res["vm4"]["minutes"])
    expect("vm5 open and stale", by_res["vm5"]["is_open"] and by_res["vm5"]["stale_open"], by_res["vm5"]["minutes"])
    expect("vm6 classified Planned by overlap", by_res["vm6"]["class"] == "Planned", by_res["vm6"]["classification_basis"])
    expect("sql1 mapped to Azure SQL Database", by_res["sql1"]["service_name"] == "Azure SQL Database", by_res["sql1"]["service_name"])

    ev = reader.rows(f"AzMaintenance_Events(true) | where subscription_id == '{sub}' | summarize n = dcount(tracking_id) by class")
    counts = {r["class"]: r["n"] for r in ev}
    expect("event counts (4 unplanned, 2 planned, 1 advisory)", counts == {"Unplanned": 4, "Planned": 2, "Advisory": 1}, counts)
    u1 = reader.rows(f"AzMaintenance_Events(true) | where subscription_id == '{sub}' and tracking_id == 'SYN-U1'")
    expect("source precedence arg > rest, one row", len(u1) == 1 and u1[0]["source"] == "arg" and abs(u1[0]["exposure_h"] - 2.0) < 0.01, u1[0]["source"] if u1 else None)
    es = reader.rows(f"AzMaintenance_EventServices(true) | where subscription_id == '{sub}' and tracking_id == 'SYN-U2' | summarize rows = count(), events = dcount(tracking_id)")
    expect("per-region expansion does not inflate event count", es and es[0]["rows"] == 2 and es[0]["events"] == 1, es)

    pl = {r["tracking_id"]: r for r in reader.rows(f"AzMaintenance_Planned(true) | where subscription_id == '{sub}'")}
    expect("planned lead time 5 d", abs(pl["SYN-P1"]["lead_time_days"] - 5.0) < 0.05, pl["SYN-P1"]["lead_time_days"])
    expect("planned realised downtime 15 min", abs((pl["SYN-P1"]["realised_downtime_min"] or 0) - 15) < 0.01, pl["SYN-P1"]["realised_downtime_min"])
    expect("upcoming flag", pl["SYN-P2"]["upcoming"] is True and pl["SYN-P1"]["upcoming"] is False, "ok")

    av = reader.rows("AzMaintenance_Availability(365, false, true) | where service_name == 'Azure SQL Database'")
    expect("availability row for synthetic SQL (60 min of 5 resources)", bool(av) and av[0]["downtime_min"] >= 60 and av[0]["sla_status"] == "SLA not set", av[:1])

    fc = reader.rows("AzMaintenance_Forecast(true) | where scope_level == 'service' and scope_key == 'Virtual Machines'")
    expect("forecast row carries n, window, confidence", bool(fc) and all(fc[0].get(k) is not None for k in ("n_events", "window_days", "confidence")) and fc[0]["confidence"] in ("insufficient", "low", "medium", "high"), fc[:1])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--workspace")
    a = ap.parse_args()
    load_env(ROOT / ".env")
    ws = a.workspace or os.environ["AOL_WORKSPACE_ID"]
    reader = LogsReader(ws)
    s = "true" if a.synthetic else "false"
    results: list[tuple[str, str, object]] = []


    for f in FUNCTIONS:
        check(reader, f.format(s=s), f.format(s=s) + " | take 20", results)
    for name in wbkql.all_names():
        check(reader, f"workbook:{name}", wbkql.render(name, synthetic=a.synthetic), results)
        # the page must render a result or a clean empty set: nothing to assert beyond "no error"

    # The portal expands "All" into the full quoted value list inside the query text: reproduce that.
    expanded = {}
    for token, pname in (("{Subscriptions}", "p_subscriptions"), ("{Category}", "p_category"), ("{Service}", "p_service"), ("{Region}", "p_region")):
        vals = [r["value"] for r in reader.rows(wbkql.render(pname, synthetic=a.synthetic), days=800)]
        unsafe = [v for v in vals if any(c in v for c in "'\"\\")]
        results.append((f"filter values safe:{pname}", "ok" if not unsafe else "FAIL", f"{len(vals)} values" if not unsafe else unsafe[:5]))
        expanded[token] = ",".join("'" + v + "'" for v in vals) or "'*'"
    for name in wbkql.all_names():
        if not name.startswith("p_"):
            check(reader, f"workbook(expanded filters):{name}", wbkql.render(name, synthetic=a.synthetic, **expanded), results)

    for mode, slas, exp_pct, exp_h, tol in SLA_VECTORS:
        q = f"AzMaintenance_CompositeSla(dynamic({slas}), '{mode}')"
        rows = check(reader, f"sla:{mode}{slas}", q, results)
        if rows:
            ok = abs(rows[0]["availability_pct"] - exp_pct) < 1e-6 and abs(rows[0]["allowance_h_per_year"] - exp_h) < tol
            results[-1] = (results[-1][0], "ok" if ok else "FAIL", rows[0] if not ok else "vector matches")

    if a.synthetic:
        try:
            assert_synthetic(reader, results)
        except Exception as exc:  # missing seed rows etc.
            results.append(("assert:synthetic scenario", "FAIL", f"{type(exc).__name__}: {exc}"[:400]))

    fails = [r for r in results if r[1] != "ok"]
    for label, status, info in results:
        print(f"{status:4}  {label:55}  {info}")
    print(f"\n{len(results) - len(fails)}/{len(results)} checks passed at {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M}Z (synthetic={a.synthetic})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
