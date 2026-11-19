"""Count parity: distinct tracking ids in the ledger must be >= those returned by ARG for the same scope. Prints ARG, REST and ledger counts.

  python tools/check_parity.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from collector import collectors  # noqa: E402
from collector.backfill import load_env  # noqa: E402
from collector.forecast_job import LogsReader  # noqa: E402
from collector.sources import arg, rest  # noqa: E402

LEDGER_Q = "AzSvcHealthEvents_CL | where is_synthetic != true | summarize ids = dcount(tracking_id)"


def main() -> int:
    load_env(ROOT / ".env")
    subs = collectors.configured_subscriptions()
    arg_ids = {r["tracking_id"] for r in arg.ArgClient().query(arg.load_query("service_health_events"), subs)}
    session = rest.ArmSession()
    rest_ids = {
        (i.get("properties") or {}).get("trackingId") or i.get("name")
        for s in subs
        for i in rest.fetch_rest_events(session, s, 365)
    }
    ledger = int(LogsReader(os.environ["AML_WORKSPACE_ID"]).rows(LEDGER_Q)[0]["ids"])
    union = len(arg_ids | rest_ids)
    print(f"ARG distinct tracking ids : {len(arg_ids)}")
    print(f"REST distinct tracking ids: {len(rest_ids)} (365 d)")
    print(f"ARG union REST            : {union}")
    print(f"Ledger distinct tracking ids: {ledger}")
    ok = ledger >= len(arg_ids)
    print("PASS: ledger >= ARG" if ok else "FAIL: ledger < ARG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
