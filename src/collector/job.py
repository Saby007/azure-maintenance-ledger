"""Scheduled collector run (Container Apps Job): python -m collector.job collect

Runs hourly. First runs bootstrap the ledger step by step (catalog, public PIRs, Service Health history, Resource Health history,
inventory, VM annotations); a step that fails (for example a role still propagating) is simply retried at the next run. Afterwards each
task runs when due: Service Health and inventory daily, VM annotations every 6 h, public PIRs monthly, planning ranges daily.
State is kept in the workspace (see state.LogState): no storage account is needed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import collectors
from .forecast_job import LogsReader, load_query, run_forecast
from .health import RunResult, run_collector
from .ingest import Ingestor, utc_iso
from .sources import arg, pirs, rest
from .state import LogState

log = logging.getLogger("aol.job")

DAILY_H = 20.0
ANNOTATIONS_H = 5.0
FORECAST_DELAY = dt.timedelta(minutes=45)


def _flag(name: str, default: bool = True) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes")


def is_due(last: dt.datetime | None, now: dt.datetime, hours: float) -> bool:
    return last is None or (now - last) >= dt.timedelta(hours=hours)


def run_collect(ing: Any, reader: Any, state: Any, now: dt.datetime | None = None, *, client: Any = None, session: Any = None,
                pir_cache: Path | None = None) -> dict[str, str]:
    """Run whatever is due. Returns {task: ok|skipped|failed:<reason>}; the caller fails the job when any task failed."""
    now = now or dt.datetime.now(dt.UTC)
    subs = collectors.configured_subscriptions()
    client = client or arg.ArgClient()
    session = session or rest.ArmSession()
    results: dict[str, str] = {}

    def task(name: str, source: str, fn: Callable[[], RunResult]) -> bool:
        try:
            run_collector(source, fn, ing)
            results[name] = "ok"
            return True
        except Exception as exc:
            results[name] = f"failed:{type(exc).__name__}"
            log.error("task %s failed: %s", name, exc)
            return False

    steps: list[tuple[str, str, Callable[[], RunResult]]] = [
        ("reference", "reference", lambda: collectors.run_reference(ing, state)),
        ("servicehealth", "servicehealth_events", lambda: collectors.run_service_health(ing, client, state, subs)),
        ("rest", "backfill_rest", lambda: collectors.run_rest_backfill(ing, session, subs, 365)),
        ("activity", "backfill_activity", lambda: collectors.run_activity_backfill(ing, session, subs, 89)),
        ("inventory", "inventory", lambda: collectors.run_inventory(ing, client, subs)),
    ]
    if _flag("AOL_ENABLE_PIRS"):
        steps.insert(1, ("pirs", "public_pirs", lambda: collectors.run_pirs(ing, pirs.FetchPirSource(cache_dir=pir_cache))))
    if _flag("AOL_ENABLE_VM_ANNOTATIONS"):
        steps.append(("vm_annotations", "vm_annotations", lambda: collectors.run_vm_annotations(ing, client, subs)))

    # ---- bootstrap: each step is marked done once, so a failed step is retried alone at the next run
    pending = [s for s in steps if not state.get(f"bootstrap:{s[0]}")]
    if pending:
        collectors.record_config(ing, subs)
        for name, source, fn in pending:
            if task(name, source, fn):
                state.set(f"bootstrap:{name}", utc_iso(now) or "")
        if all(v == "ok" for v in results.values()):
            state.set("bootstrap_done", utc_iso(now) or "")
        return results

    # ---- steady state
    done_at = parse_state_time(state.get("bootstrap_done"))
    by_name = {s[0]: s for s in steps}
    task("reference", "reference", by_name["reference"][2])  # no-op unless the catalog file changed
    for name, hours in (("servicehealth", DAILY_H), ("inventory", DAILY_H), ("vm_annotations", ANNOTATIONS_H)):
        if name not in by_name:
            continue
        if is_due(state.last_success(by_name[name][1]), now, hours):
            task(name, by_name[name][1], by_name[name][2])
        else:
            results[name] = "skipped"
    if "pirs" in by_name:
        month = f"{now:%Y-%m}"
        if state.get("pirs_month") != month and now.day >= 2:
            if task("pirs", by_name["pirs"][1], by_name["pirs"][2]):
                state.set("pirs_month", month)
        else:
            results["pirs"] = "skipped"

    if (done_at is None or now - done_at >= FORECAST_DELAY) and is_due(state.last_success("forecast"), now, DAILY_H):
        cfg = Path(__file__).resolve().parents[1] / "config" / "forecast.yaml"
        task("forecast", "forecast", lambda: run_forecast(ing, reader, cfg if cfg.exists() else None))
    else:
        results["forecast"] = "skipped"
    return results


def parse_state_time(value: str | None) -> dt.datetime | None:
    return arg.parse_ts(value) if value else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["collect"])
    ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    ing = Ingestor()
    reader = LogsReader(os.environ["AOL_WORKSPACE_ID"])
    state = LogState(reader, ing, load_query)
    results = run_collect(ing, reader, state, pir_cache=Path("/tmp/aol-pir-cache"))
    for k, v in results.items():
        log.info("%s: %s", k, v)
    failed = {k: v for k, v in results.items() if v.startswith("failed")}
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
