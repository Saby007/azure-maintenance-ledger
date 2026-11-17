"""Azure Functions (Flex Consumption, Python v2 model). Timer schedules are UTC (Linux Flex ignores WEBSITE_TIME_ZONE)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import azure.functions as func

from collector import collectors
from collector.forecast_job import LogsReader, run_forecast
from collector.health import RunResult, run_collector
from collector.ingest import Ingestor
from collector.sources import arg, pirs
from collector.state import TableState

app = func.FunctionApp()
log = logging.getLogger("aol.function")


def _flag(name: str, default: bool = True) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes")


@app.timer_trigger(schedule="0 15 2 * * *", arg_name="timer", run_on_startup=False)
def service_health_daily(timer: func.TimerRequest) -> None:
    ing, subs = Ingestor(), collectors.configured_subscriptions()
    state = TableState()
    collectors.record_config(ing, subs)
    run_collector("reference", lambda: collectors.run_reference(ing, state), ing)
    run_collector("servicehealth_events", lambda: collectors.run_service_health(ing, arg.ArgClient(), state, subs), ing)


@app.timer_trigger(schedule="0 0 4 * * *", arg_name="timer", run_on_startup=True)
def bootstrap_once(timer: func.TimerRequest) -> None:
    """Loads the catalog, public PIRs and history on a fresh deployment (no-op once complete)."""
    from collector.bootstrap import run_bootstrap

    run_bootstrap(Ingestor(), TableState(), Path("/tmp/aol-pir-cache"))


@app.timer_trigger(schedule="0 45 2 * * *", arg_name="timer", run_on_startup=False)
def inventory_daily(timer: func.TimerRequest) -> None:
    ing, subs = Ingestor(), collectors.configured_subscriptions()
    run_collector("inventory", lambda: collectors.run_inventory(ing, arg.ArgClient(), subs), ing)


@app.timer_trigger(schedule="0 15 3 * * *", arg_name="timer", run_on_startup=False)
def forecast_daily(timer: func.TimerRequest) -> None:
    ing = Ingestor()
    reader = LogsReader(os.environ["AOL_WORKSPACE_ID"])
    cfg = Path(__file__).resolve().parent / "config" / "forecast.yaml"
    run_collector("forecast", lambda: run_forecast(ing, reader, cfg if cfg.exists() else None), ing)


@app.timer_trigger(schedule="0 0 */6 * * *", arg_name="timer", run_on_startup=False)
def vm_annotations_6h(timer: func.TimerRequest) -> None:
    if not _flag("AOL_ENABLE_VM_ANNOTATIONS"):
        return
    ing, subs = Ingestor(), collectors.configured_subscriptions()
    run_collector("vm_annotations", lambda: collectors.run_vm_annotations(ing, arg.ArgClient(), subs), ing)


@app.timer_trigger(schedule="0 0 3 2 * *", arg_name="timer", run_on_startup=False)
def public_pirs_monthly(timer: func.TimerRequest) -> None:
    if not _flag("AOL_ENABLE_PIRS"):
        return
    ing = Ingestor()

    def job() -> RunResult:
        return collectors.run_pirs(ing, pirs.FetchPirSource(cache_dir=Path("/tmp/aol-pir-cache")))

    run_collector("public_pirs", job, ing)
