"""Backfill CLI: python -m collector.backfill [--dry-run] [--only pirs,arg,rest,activity,inventory] [--pir-file path]

Uses DefaultAzureCredential (your `az login` locally). Needs Reader on the subscriptions and Monitoring Metrics
Publisher on the DCR. Env: AML_DCR_ENDPOINT, AML_DCR_IMMUTABLE_ID (see .env.example).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from . import collectors
from .health import RunResult, run_collector
from .ingest import Ingestor
from .sources import arg, pirs, rest
from .state import MemoryState

log = logging.getLogger("aml.backfill")
STEPS = ("pirs", "arg", "rest", "activity", "inventory")
EXTRA_STEPS = ("forecast", "vm_annotations")  # runnable on demand, not part of the default backfill


class DryRunIngestor:
    """Counts rows instead of uploading (no DCR access needed)."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def upload(self, table: str, rows: list[dict], batch_size: int = 500) -> int:
        self.counts[table] = self.counts.get(table, 0) + len(rows)
        return len(rows)


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if v.strip():
                os.environ.setdefault(k.strip(), v.strip())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", default=",".join(STEPS))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--pir-file", type=Path, help="JSON or CSV with PIRs instead of fetching the public site")
    p.add_argument("--pir-cache", type=Path, default=Path("cache/pirs"))
    p.add_argument("--rest-days", type=int, default=365)
    p.add_argument("--activity-days", type=int, default=89)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    load_env(Path(__file__).resolve().parents[2] / ".env")

    steps = [s.strip() for s in a.only.split(",") if s.strip()]
    bad = set(steps) - set(STEPS) - set(EXTRA_STEPS)
    if bad:
        p.error(f"unknown step(s): {', '.join(sorted(bad))}")
    subs = collectors.configured_subscriptions()
    ing = DryRunIngestor() if a.dry_run else Ingestor()
    health_ing = ing

    def run(source: str, fn) -> RunResult:
        r = run_collector(source, fn, health_ing)
        log.info("%s: read=%d written=%d errors=%s", source, r.rows_read, r.rows_written, r.errors)
        return r

    state = MemoryState()
    if not a.dry_run:
        collectors.record_config(ing, subs)
    session = rest.ArmSession() if {"rest", "activity"} & set(steps) else None
    client = arg.ArgClient() if {"arg", "inventory", "vm_annotations"} & set(steps) else None

    if "pirs" in steps:
        if a.pir_file:
            src = pirs.CsvPirSource(a.pir_file) if a.pir_file.suffix == ".csv" else pirs.JsonPirSource(a.pir_file)
        else:
            src = pirs.FetchPirSource(cache_dir=a.pir_cache)
        run("public_pirs", lambda: collectors.run_pirs(ing, src))
    if "arg" in steps:
        run("servicehealth_events", lambda: collectors.run_service_health(ing, client, state, subs))
    if "rest" in steps:
        run("backfill_rest", lambda: collectors.run_rest_backfill(ing, session, subs, a.rest_days))
    if "activity" in steps:
        run("backfill_activity", lambda: collectors.run_activity_backfill(ing, session, subs, a.activity_days))
    if "inventory" in steps:
        run("inventory", lambda: collectors.run_inventory(ing, client, subs))
    if "vm_annotations" in steps:
        run("vm_annotations", lambda: collectors.run_vm_annotations(ing, client, subs))
    if "forecast" in steps:
        from .forecast_job import LogsReader, run_forecast

        cfg = Path(__file__).resolve().parents[2] / "config" / "forecast.yaml"
        run("forecast", lambda: run_forecast(ing, LogsReader(os.environ["AML_WORKSPACE_ID"]), cfg))
    if a.dry_run:
        print(json.dumps(ing.counts, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
