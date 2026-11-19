"""Idempotency check: run each collector twice and prove the deduplicated function output does not grow.

  python tools/check_idempotency.py [--wait 240]

Appends are real (raw rows grow) but AzMaintenance_* functions dedupe on row_key, so their row counts must not change.
Writes to the sandbox workspace from .env; read-only against Azure sources.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from collector.backfill import load_env  # noqa: E402
from collector.forecast_job import LogsReader  # noqa: E402

DEDUP = {
    "AzMaintenance_Events": "AzMaintenance_Events() | count",
    "AzMaintenance_EventServices": "AzMaintenance_EventServices() | count",
    "AzMaintenance_ResourceIntervals": "AzMaintenance_ResourceIntervals() | count",
    "AzMaintenance_PirBaseline": "AzMaintenance_PirBaseline() | count",
    "AzMaintenance_Catalog": "AzMaintenance_Catalog() | count",
    "AzMaintenance_Planned": "AzMaintenance_Planned() | count",
    "inventory (latest snapshot rows)": "AzInventoryCounts_CL | where is_synthetic != true | summarize arg_max(ingested_utc, *) by row_key | count",
}
RAW = {
    "raw AzSvcHealthEvents_CL": "AzSvcHealthEvents_CL | where is_synthetic != true | count",
    "raw AzResourceHealthEvents_CL": "AzResourceHealthEvents_CL | where is_synthetic != true | count",
    "raw AzPublicPirs_CL": "AzPublicPirs_CL | where is_synthetic != true | count",
    "raw AzInventoryCounts_CL": "AzInventoryCounts_CL | where is_synthetic != true | count",
}


def snapshot(reader: LogsReader, queries: dict[str, str]) -> dict[str, int]:
    return {k: int(reader.rows(q)[0]["Count"]) for k, q in queries.items()}


def run_collectors() -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    subprocess.run([sys.executable, "-m", "collector.backfill", "--only", "pirs,arg,rest,activity,inventory"], check=True, env=env, cwd=ROOT,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wait", type=int, default=240, help="seconds to wait for ingestion after each run")
    a = ap.parse_args()
    load_env(ROOT / ".env")
    reader = LogsReader(os.environ["AML_WORKSPACE_ID"])

    base_d, base_r = snapshot(reader, DEDUP), snapshot(reader, RAW)
    print("baseline dedup:", base_d, "\nbaseline raw:  ", base_r)
    results = []
    for i in (1, 2):
        print(f"collector run {i} ...", flush=True)
        run_collectors()
        time.sleep(a.wait)
        d, r = snapshot(reader, DEDUP), snapshot(reader, RAW)
        results.append((d, r))
        print(f"after run {i} dedup:", d, "\n         raw:  ", r, flush=True)
    (d1, r1), (d2, r2) = results
    # A first run may legitimately add rows (new events, resources created meanwhile); the SECOND run must add none.
    grew = {k: (d1[k], d2[k]) for k in d1 if d2[k] != d1[k]}
    print("raw rows appended by run 2 (expected > 0, duplicates are deduplicated):", {k: r2[k] - r1[k] for k in r2})
    if grew:
        print("FAIL: deduplicated output changed on the second run:", grew)
        return 1
    print("PASS: the second run of every collector added 0 rows to the deduplicated function output")
    return 0


if __name__ == "__main__":
    sys.exit(main())
