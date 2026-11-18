"""Seeds deterministic SYNTHETIC rows (is_synthetic=true) so every KQL function and workbook query can be exercised and checked.

  python tools/seed_fixtures.py [--dry-run]

Every production function filters these rows out (includeSynthetic=false); tools/run_kql_checks.py --synthetic includes them
and asserts the expected results below. Times are relative to 'now' so the scenario always falls in the default window.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from analytics import forecast  # noqa: E402
from collector.backfill import DryRunIngestor, load_env  # noqa: E402
from collector.ingest import Ingestor, row_key, stamp, utc_iso  # noqa: E402
from collector.sources.rest import resource_type_from_id  # noqa: E402

SUB = "00000000-0000-0000-0000-00000000a0a0"
PRE = f"/subscriptions/{SUB}/resourcegroups/rg-synthetic/providers"


def res(rtype: str, name: str) -> str:
    return f"{PRE}/{rtype}/{name}".lower()


def build(now: dt.datetime) -> dict[str, list[dict]]:
    t0 = now - dt.timedelta(days=30)

    def m(base: dt.datetime, minutes: float) -> dt.datetime:
        return base + dt.timedelta(minutes=minutes)

    # ---- Resource Health events: (resource, time, status, current, previous, cause, type)
    rh_spec = [
        # vm1: duplicate Updated row, 30 min unplanned
        (res("Microsoft.Compute/virtualMachines", "vm1"), m(t0, -60), "Resolved", "Available", "Available", "Unknown", "Unknown"),
        (res("Microsoft.Compute/virtualMachines", "vm1"), t0, "Active", "Unavailable", "Available", "PlatformInitiated", "Downtime"),
        (res("Microsoft.Compute/virtualMachines", "vm1"), m(t0, 1), "Updated", "Unavailable", "Unavailable", "PlatformInitiated", "Downtime"),
        (res("Microsoft.Compute/virtualMachines", "vm1"), m(t0, 30), "Resolved", "Available", "Unavailable", "PlatformInitiated", "Downtime"),
        # vm2: user initiated 20 min -> excluded
        (res("Microsoft.Compute/virtualMachines", "vm2"), m(t0, 2 * 1440), "Active", "Unavailable", "Available", "UserInitiated", "Downtime"),
        (res("Microsoft.Compute/virtualMachines", "vm2"), m(t0, 2 * 1440 + 20), "Resolved", "Available", "Unavailable", "UserInitiated", "Downtime"),
        # vm3: Unknown in the middle is skipped, 45 min
        (res("Microsoft.Compute/virtualMachines", "vm3"), m(t0, 3 * 1440), "Active", "Unavailable", "Available", "PlatformInitiated", "Downtime"),
        (res("Microsoft.Compute/virtualMachines", "vm3"), m(t0, 3 * 1440 + 5), "Updated", "Unknown", "Unavailable", "Unknown", "Unknown"),
        (res("Microsoft.Compute/virtualMachines", "vm3"), m(t0, 3 * 1440 + 45), "Resolved", "Available", "Unavailable", "PlatformInitiated", "Downtime"),
        # vm4: open, recent (not stale)
        (res("Microsoft.Compute/virtualMachines", "vm4"), now - dt.timedelta(minutes=30), "Active", "Unavailable", "Available", "PlatformInitiated", "Downtime"),
        # vm5: open and stale (> 3 days) -> excluded
        (res("Microsoft.Compute/virtualMachines", "vm5"), now - dt.timedelta(days=10), "Active", "Unavailable", "Available", "PlatformInitiated", "Downtime"),
        # vm6: 15 min inside the planned maintenance window -> Planned
        (res("Microsoft.Compute/virtualMachines", "vm6"), m(t0, 5 * 1440 + 10), "Active", "Unavailable", "Available", "PlatformInitiated", "Downtime"),
        (res("Microsoft.Compute/virtualMachines", "vm6"), m(t0, 5 * 1440 + 25), "Resolved", "Available", "Unavailable", "PlatformInitiated", "Downtime"),
        # sql1: 60 min, spans the window of an unplanned SQL event
        (res("Microsoft.Sql/servers", "srv1/databases/sql1"), m(t0, 4 * 1440), "Active", "Unavailable", "Available", "PlatformInitiated", "Downtime"),
        (res("Microsoft.Sql/servers", "srv1/databases/sql1"), m(t0, 4 * 1440 + 60), "Resolved", "Available", "Unavailable", "PlatformInitiated", "Downtime"),
    ]
    rh_rows = []
    for i, (rid, ts, status, cur, prev, cause, typ) in enumerate(rh_spec):
        eid = f"synthetic-rh-{i:03d}"
        rtype = resource_type_from_id(rid)
        row = {"event_data_id": eid, "resource_id": rid, "resource_type": rtype, "subscription_id": SUB, "status": status,
               "current_status": cur, "previous_status": prev, "health_type": typ, "cause": cause, "event_utc": utc_iso(ts)}
        rh_rows.append(stamp(row, row_key("synthetic-rh", SUB, eid, row["event_utc"]), now=now, synthetic=True))

    # ---- Service Health events
    def ev(tid, etype, status, services, regions, start, end, upd, source="arg"):
        row = {"subscription_id": SUB, "tracking_id": tid, "event_type": etype, "status": status, "level": "Warning",
               "event_title": f"Synthetic {etype} {tid}", "summary": "synthetic", "impact_start_utc": utc_iso(start),
               "impact_end_utc": utc_iso(end), "last_update_utc": utc_iso(upd), "platform_initiated": True, "tags": "[]",
               "services": services, "regions": regions, "source": source}
        return stamp(row, row_key("synthetic-ev", SUB + source, tid, row["last_update_utc"]), now=now, synthetic=True)

    events = [
        ev("SYN-U1", "ServiceIssue", "Resolved", ["Virtual Machines"], ["East US"], t0, m(t0, 120), m(t0, 150)),
        ev("SYN-U2", "ServiceIssue", "Resolved", ["Virtual Machines"], ["East US", "West Europe"], m(t0, 3 * 1440), m(t0, 3 * 1440 + 60), m(t0, 3 * 1440 + 90)),
        ev("SYN-U3", "ServiceIssue", "Resolved", ["Azure SQL Database"], ["West Europe"], m(t0, 4 * 1440), m(t0, 4 * 1440 + 90), m(t0, 4 * 1440 + 100)),
        ev("SYN-U4", "ServiceIssue", "Active", ["Storage Accounts"], ["Central India"], now - dt.timedelta(hours=2), None, now - dt.timedelta(hours=1)),
        # planned: two updates (first seen 5 days before the window -> lead time 5 d), lower precedence rest copy of U1
        ev("SYN-P1", "PlannedMaintenance", "Resolved", ["Virtual Machines"], ["East US"], m(t0, 5 * 1440), m(t0, 5 * 1440 + 120), m(t0, 0)),
        ev("SYN-P1", "PlannedMaintenance", "Resolved", ["Virtual Machines"], ["East US"], m(t0, 5 * 1440), m(t0, 5 * 1440 + 120), m(t0, 5 * 1440 + 130)),
        ev("SYN-P2", "PlannedMaintenance", "Active", ["Storage Accounts"], ["Central India"], now + dt.timedelta(days=7), now + dt.timedelta(days=7, hours=2), now),
        ev("SYN-U1", "ServiceIssue", "Resolved", ["Virtual Machines"], ["East US"], t0, m(t0, 125), m(t0, 160), source="rest"),
        ev("SYN-A1", "HealthAdvisory", "Active", ["App Service"], ["Global"], t0, None, t0),
    ]

    inv = []
    for snap, scale in ((now.date() - dt.timedelta(days=30), 1), (now.date(), 1)):
        for rtype, region, n in (("microsoft.compute/virtualmachines", "eastus", 10 * scale), ("microsoft.sql/servers/databases", "westeurope", 5 * scale)):
            snap_dt = dt.datetime.combine(snap, dt.time(), tzinfo=dt.UTC)
            row = {"snapshot_date": utc_iso(snap_dt), "subscription_id": SUB, "resource_type": rtype, "region": region, "resource_count": n}
            inv.append(stamp(row, row_key("synthetic-inv", SUB, f"{rtype}|{region}", row["snapshot_date"]), now=now, synthetic=True))

    ann = []
    for i, (rid, cat, ctx, t) in enumerate([
        (res("Microsoft.Compute/virtualMachines", "vm6"), "Planned", "Platform-Initiated", m(t0, 5 * 1440 + 10)),
        (res("Microsoft.Compute/virtualMachines", "vm2"), "Unplanned", "User-initiated", m(t0, 2 * 1440)),
    ]):
        row = {"subscription_id": SUB, "resource_id": rid, "region": "eastus", "annotation_name": "VirtualMachineRestarted" if i == 0 else "VirtualMachineStopped",
               "category": cat, "context": ctx, "reason": "Planned maintenance, reboot required" if i == 0 else "stopped by user",
               "availability_state": "Unavailable", "previous_availability_state": "Available", "occurred_utc": utc_iso(t), "summary": "synthetic"}
        ann.append(stamp(row, row_key("synthetic-ann", SUB, f"{rid}|{i}", row["occurred_utc"]), now=now, synthetic=True))

    # ---- forecast from the synthetic unplanned events (seeded RNG)
    cfg = forecast.load_config(None)
    cfg["seed"] = 7
    cfg["simulations"] = 2000
    fe = [
        forecast.ForecastEvent("SYN-U1", "Virtual Machines", "East US", "IaaS", 120, 30),
        forecast.ForecastEvent("SYN-U2", "Virtual Machines", "East US", "IaaS", 60, 45),
        forecast.ForecastEvent("SYN-U3", "Azure SQL Database", "West Europe", "Data", 90, 60),
    ]
    fc_rows = forecast.to_rows(forecast.compute_forecast(fe, 200, cfg), now)
    for r in fc_rows:
        r["is_synthetic"] = True

    health = []
    for src in ("servicehealth_events", "inventory", "forecast"):
        row = {"run_id": f"synthetic-{src}", "source": src, "started_utc": utc_iso(now), "finished_utc": utc_iso(now), "rows_read": 1, "rows_written": 1,
               "watermark_utc": utc_iso(now), "status": "success", "errors": []}
        health.append(stamp(row, row_key("synthetic-health", "-", src, utc_iso(now) or ""), now=now, synthetic=True))

    return {"AzResourceHealthEvents_CL": rh_rows, "AzSvcHealthEvents_CL": events, "AzInventoryCounts_CL": inv,
            "AzVmAnnotations_CL": ann, "AzMaintenanceForecast_CL": fc_rows, "AzMaintenanceIngestHealth_CL": health}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    load_env(ROOT / ".env")
    now = dt.datetime.now(dt.UTC)
    ing = DryRunIngestor() if a.dry_run else Ingestor()
    for table, rows in build(now).items():
        print(f"{table}: {ing.upload(table, rows)} synthetic rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
