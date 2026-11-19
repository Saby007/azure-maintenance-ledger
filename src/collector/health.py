"""Per-run health rows (AzMaintenanceIngestHealth_CL) written by every collector run."""

from __future__ import annotations

import datetime as dt
import logging
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .ingest import row_key, stamp, utc_iso

log = logging.getLogger("aml.health")


@dataclass
class RunResult:
    rows_read: int = 0
    rows_written: int = 0
    watermark: dt.datetime | None = None
    errors: list[str] = field(default_factory=list)


def health_row(source: str, started: dt.datetime, finished: dt.datetime, result: RunResult, status: str) -> dict:
    run_id = str(uuid.uuid4())
    row = {
        "run_id": run_id,
        "source": source,
        "started_utc": utc_iso(started),
        "finished_utc": utc_iso(finished),
        "rows_read": result.rows_read,
        "rows_written": result.rows_written,
        "watermark_utc": utc_iso(result.watermark),
        "status": status,
        "state_value": "",
        "errors": result.errors[:10],
    }
    return stamp(row, row_key("health", "-", run_id, utc_iso(finished) or ""))


def run_collector(source: str, fn: Callable[[], RunResult], ingestor: Any) -> RunResult:
    """Run `fn`, always record a health row (success or failure). Failures are re-raised after recording."""
    started = dt.datetime.now(dt.UTC)
    try:
        result = fn()
        status = "success" if not result.errors else "partial"
    except Exception as exc:  # recorded then re-raised
        log.error("collector %s failed: %s", source, type(exc).__name__)
        result = RunResult(errors=[f"{type(exc).__name__}: {str(exc)[:300]}"])
        ingestor.upload("AzMaintenanceIngestHealth_CL", [health_row(source, started, dt.datetime.now(dt.UTC), result, "failed")])
        log.debug(traceback.format_exc())
        raise
    ingestor.upload("AzMaintenanceIngestHealth_CL", [health_row(source, started, dt.datetime.now(dt.UTC), result, status)])
    return result
