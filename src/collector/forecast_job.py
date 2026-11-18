"""Daily planning-range job: reads the ledger through the AzMaintenance_* functions, computes ranges, writes AzMaintenanceForecast_CL."""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Any

from analytics import forecast

from .health import RunResult
from .ingest import Ingestor

log = logging.getLogger("aol.forecast")


def _query_dir() -> Path:
    here = Path(__file__).resolve()
    for base in (here.parents[1], here.parents[2]):
        if (base / "kql" / "queries").exists():
            return base / "kql" / "queries"
    raise FileNotFoundError("kql/queries not found")


def load_query(name: str) -> str:
    text = (_query_dir() / f"{name}.kql").read_text(encoding="utf-8")
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("//"))


class LogsReader:
    def __init__(self, workspace_id: str, credential: Any = None):
        from azure.monitor.query import LogsQueryClient

        if credential is None:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
        self.workspace_id = workspace_id
        self._c = LogsQueryClient(credential)

    def rows(self, query: str, days: int = 800) -> list[dict]:
        from azure.monitor.query import LogsQueryStatus

        resp = self._c.query_workspace(self.workspace_id, query, timespan=dt.timedelta(days=days))
        if resp.status != LogsQueryStatus.SUCCESS:
            raise RuntimeError(f"log query failed: {getattr(resp, 'partial_error', None)}")
        out: list[dict] = []
        for table in resp.tables:
            cols = [c if isinstance(c, str) else c.name for c in table.columns]
            out.extend(dict(zip(cols, list(r), strict=False)) for r in table.rows)
        return out


def _dt(value: Any) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def run_forecast(ing: Ingestor, reader: LogsReader, cfg_path: Path | None = None, now: dt.datetime | None = None) -> RunResult:
    now = now or dt.datetime.now(dt.UTC)
    cfg = forecast.load_config(cfg_path)
    res = RunResult()

    cov = reader.rows(load_query("forecast_coverage"))
    start = _dt(cov[0]["coverage_start"]) if cov else None
    coverage_days = int((now - start).days) if start else 0

    events = [
        forecast.ForecastEvent(
            tracking_id=r["tracking_id"],
            service=r["service"] or "(unknown)",
            region=r["region"] or "(unknown)",
            category=r["category"] or "Unmapped",
            sh_minutes=float(r["sh_minutes"] or 0.0),
            rh_minutes=float(r["rh_minutes"]) if r.get("rh_minutes") is not None else None,
        )
        for r in reader.rows(load_query("forecast_events"))
    ]
    res.rows_read = len(events)
    results = forecast.compute_forecast(events, coverage_days, cfg)

    pirs = reader.rows(load_query("forecast_pirs"))
    if pirs:
        dates = [d for d in (_dt(p["published_date"]) for p in pirs) if d]
        span = max(1, (max(dates) - min(dates)).days) if dates else 365
        results += forecast.pir_baseline([(p["tracking_id"], p["category"] or "Other", float(p["duration_h"])) for p in pirs], span, cfg)
        res.rows_read += len(pirs)

    res.rows_written = ing.upload("AzMaintenanceForecast_CL", forecast.to_rows(results, now))
    res.watermark = now
    return res
