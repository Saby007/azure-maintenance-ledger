"""First-run bootstrap for a fresh deployment: loads the service catalog, public PIRs and the available history once.

Runs from the Function app at start-up and daily as a safety net. A watermark in Table Storage makes it a no-op once every
step has succeeded; a failed step (for example Reader role still propagating) is retried at the next run.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from . import collectors
from .health import run_collector
from .ingest import Ingestor
from .sources import arg, pirs, rest
from .state import WatermarkStore

log = logging.getLogger("aol.bootstrap")

DONE_KEY = "bootstrap_done"


def _flag(name: str, default: bool = True) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes")


def run_bootstrap(ing: Ingestor, state: WatermarkStore, pir_cache: Path | None = None) -> bool:
    """Returns True when the bootstrap is (now) complete."""
    if state.get(DONE_KEY):
        return True
    subs = collectors.configured_subscriptions()
    collectors.record_config(ing, subs)
    client = arg.ArgClient()
    session = rest.ArmSession()

    run_collector("reference", lambda: collectors.run_reference(ing, state), ing)
    if _flag("AOL_ENABLE_PIRS"):
        run_collector("public_pirs", lambda: collectors.run_pirs(ing, pirs.FetchPirSource(cache_dir=pir_cache)), ing)
    run_collector("servicehealth_events", lambda: collectors.run_service_health(ing, client, state, subs), ing)
    run_collector("backfill_rest", lambda: collectors.run_rest_backfill(ing, session, subs, 365), ing)
    run_collector("backfill_activity", lambda: collectors.run_activity_backfill(ing, session, subs, 89), ing)
    run_collector("inventory", lambda: collectors.run_inventory(ing, client, subs), ing)
    state.set(DONE_KEY, "1")
    log.info("bootstrap complete")
    return True
