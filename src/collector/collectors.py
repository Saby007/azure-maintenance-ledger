"""Collector run functions. Each returns a RunResult and is wrapped by health.run_collector in job / backfill."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from collections.abc import Iterable
from pathlib import Path

from .health import RunResult
from .ingest import Ingestor, utc_iso
from .sources import arg, pirs, rest
from .state import WatermarkStore

log = logging.getLogger("aol.collectors")

MIN_PLAUSIBLE_PIRS = 30  # the public history holds ~80; far fewer means a truncated fetch


def _root() -> Path:
    here = Path(__file__).resolve()
    for base in (here.parents[1], here.parents[2]):  # packaged app root, then repo root
        if (base / "config").exists():
            return base
    return here.parents[2]


def configured_subscriptions() -> list[str]:
    env = os.environ.get("AOL_SUBSCRIPTIONS", "").strip()
    if env:
        return [s.strip() for s in env.split(",") if s.strip()]
    cfg = _root() / "config" / "subscriptions.json"
    return [s["id"] for s in json.loads(cfg.read_text(encoding="utf-8"))["subscriptions"]]


def record_config(ing: Ingestor, subs: list[str]) -> None:
    from .health import health_row

    now = dt.datetime.now(dt.UTC)
    ing.upload("AzMaintenanceIngestHealth_CL", [health_row("config", now, now, RunResult(rows_read=len(subs)), "success")])


def run_service_health(ing: Ingestor, client: arg.ArgClient, state: WatermarkStore, subs: list[str]) -> RunResult:
    res = RunResult()
    wm_raw = state.get("servicehealth_events")
    wm = arg.parse_ts(wm_raw) if wm_raw else None
    rows = []
    max_update = wm
    for rec in client.query(arg.load_query("service_health_events"), subs):
        res.rows_read += 1
        row = arg.event_row(rec)
        if row is None:
            continue
        lu = arg.parse_ts(row["last_update_utc"])
        if wm is not None and lu is not None and lu < wm:
            continue
        rows.append(row)
        if lu and (max_update is None or lu > max_update):
            max_update = lu
    res.rows_written += ing.upload("AzSvcHealthEvents_CL", rows)

    imp_rows = []
    for rec in client.query(arg.load_query("service_health_impacted"), subs):
        res.rows_read += 1
        r = arg.impacted_row(rec)
        if r:
            imp_rows.append(r)
    res.rows_written += ing.upload("AzSvcHealthImpacted_CL", imp_rows)  # row_key includes status: unchanged rows dedupe in KQL
    if max_update:
        state.set("servicehealth_events", utc_iso(max_update))
        res.watermark = max_update
    return res


def run_inventory(ing: Ingestor, client: arg.ArgClient, subs: list[str], today: dt.date | None = None) -> RunResult:
    res = RunResult()
    today = today or dt.datetime.now(dt.UTC).date()
    rows = []
    for rec in client.query(arg.load_query("inventory_counts"), subs):
        res.rows_read += 1
        rows.append(arg.inventory_row(rec, today))
    res.rows_written = ing.upload("AzInventoryCounts_CL", rows)
    res.watermark = dt.datetime.combine(today, dt.time(), tzinfo=dt.UTC)
    return res


def run_vm_annotations(ing: Ingestor, client: arg.ArgClient, subs: list[str]) -> RunResult:
    res = RunResult()
    rows = []
    for rec in client.query(arg.load_query("vm_annotations"), subs):
        res.rows_read += 1
        r = arg.annotation_row(rec)
        if r:
            rows.append(r)
    res.rows_written = ing.upload("AzVmAnnotations_CL", rows)
    return res


def run_pirs(ing: Ingestor, source: pirs.PirSource, overrides: Path | None = None) -> RunResult:
    res = RunResult()
    items = list(source.items())
    res.rows_read = len(items)
    rows = pirs.build_rows(items, overrides or _root() / "reference" / "pir_overrides.csv")
    unparsed = [r["tracking_id"] for r in rows if r["parse_status"] == "unparsed"]
    if unparsed:
        res.errors.append(f"{len(unparsed)} PIR(s) without a parsable window: {', '.join(unparsed[:8])}")
    if len(items) < MIN_PLAUSIBLE_PIRS and isinstance(source, pirs.FetchPirSource):
        res.errors.append(f"only {len(items)} PIR(s) fetched (expected at least {MIN_PLAUSIBLE_PIRS}): the status site may have returned a truncated list")
    res.rows_written = ing.upload("AzPublicPirs_CL", rows)
    return res


def run_rest_backfill(ing: Ingestor, session: rest.ArmSession, subs: list[str], days: int = 365) -> RunResult:
    res = RunResult()
    rows = []
    for sub in subs:
        for item in rest.fetch_rest_events(session, sub, days):
            res.rows_read += 1
            r = rest.rest_event_row(sub, item)
            if r:
                rows.append(r)
    res.rows_written = ing.upload("AzSvcHealthEvents_CL", rows)
    res.watermark = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)  # start of the covered range
    return res


def run_activity_backfill(ing: Ingestor, session: rest.ArmSession, subs: list[str], days: int = 89) -> RunResult:
    res = RunResult()
    rows = []
    for sub in subs:
        for item in rest.fetch_activity_log(session, sub, days):
            r = rest.activity_resource_health_row(sub, item)
            if r:
                rows.append(r)
            res.rows_read += 1
    res.rows_written = ing.upload("AzResourceHealthEvents_CL", rows)
    return res


def run_reference(ing: Ingestor, state: WatermarkStore, path: Path | None = None) -> RunResult:
    """Load the service catalog when its content changed since the last load (hash watermark)."""
    from .catalog import build_rows, file_hash, read_catalog

    res = RunResult()
    path = path or _root() / "reference" / "service_catalog.csv"
    digest = file_hash(path)
    if state.get("reference_hash") == digest:
        return res
    rows = build_rows(read_catalog(path))
    res.rows_read = len(rows)
    res.rows_written = ing.upload("AzServiceCatalog_CL", rows)
    state.set("reference_hash", digest)
    return res


def distinct_tracking_ids(rows: Iterable[dict]) -> int:
    return len({r["tracking_id"] for r in rows if r.get("tracking_id")})
