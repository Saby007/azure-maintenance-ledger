"""Azure Resource Graph collectors: Service Health events/impacted resources, inventory counts, VM annotations."""

from __future__ import annotations

import datetime as dt
import html
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..ingest import dumps_compact, retry, row_key, stamp, utc_iso

log = logging.getLogger("aml.arg")

def _find_kql_dir() -> Path:
    here = Path(__file__).resolve()
    for base in (here.parents[2], here.parents[3]):  # packaged app root, then repo root
        if (base / "kql" / "arg").exists():
            return base / "kql" / "arg"
    raise FileNotFoundError("kql/arg directory not found")


KQL_DIR = _find_kql_dir()

MAX_SUBS_PER_REQUEST = 1000
EPOCH_FLOOR = dt.datetime(2000, 1, 1, tzinfo=dt.UTC)


def load_query(name: str) -> str:
    """Return the ARG query text from kql/arg/<name>.kql without the comment header."""
    text = (KQL_DIR / f"{name}.kql").read_text(encoding="utf-8")
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))


def parse_ts(value: Any) -> dt.datetime | None:
    """ISO-8601 -> aware UTC datetime. Years before 2000 are treated as 'not set' (zero ticks)."""
    if not value:
        return None
    s = str(value).replace("Z", "+00:00")
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)  # ticks give 7 fractional digits
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.UTC)
    d = d.astimezone(dt.UTC)
    return None if d < EPOCH_FLOOR else d


class ArgClient:
    def __init__(self, credential: Any = None):
        from azure.mgmt.resourcegraph import ResourceGraphClient

        if credential is None:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
        self._c = ResourceGraphClient(credential)

    def query(self, query: str, subscriptions: list[str]) -> Iterator[dict]:
        from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions, ResultFormat

        for i in range(0, len(subscriptions), MAX_SUBS_PER_REQUEST):
            batch = subscriptions[i : i + MAX_SUBS_PER_REQUEST]
            skip: str | None = None
            while True:
                req = QueryRequest(
                    subscriptions=batch,
                    query=query,
                    options=QueryRequestOptions(top=1000, skip_token=skip, result_format=ResultFormat.OBJECT_ARRAY),
                )
                resp = retry(lambda r=req: self._c.resources(r), attempts=6, base=2.0)
                yield from resp.data
                skip = resp.skip_token
                if not skip:
                    break


_TAG = re.compile(r"<[^>]+>")


def clean_summary(value: str | None, limit: int = 2000) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", value or ""))).strip()[:limit]


def services_and_regions(impact: Any) -> tuple[list[str], list[str]]:
    services: list[str] = []
    regions: list[str] = []
    for item in impact or []:
        if not isinstance(item, dict):
            continue
        svc = item.get("ImpactedService")
        if svc and svc not in services:
            services.append(svc)
        for r in item.get("ImpactedRegions") or []:
            name = r.get("ImpactedRegion") if isinstance(r, dict) else None
            if name and name not in regions:
                regions.append(name)
    return services, regions


def event_row(rec: dict, now: dt.datetime | None = None) -> dict | None:
    last_update = parse_ts(rec.get("last_update_utc"))
    tracking_id = rec.get("tracking_id")
    if not tracking_id or last_update is None:
        return None
    services, regions = services_and_regions(rec.get("impact"))
    sub = rec["subscription_id"]
    row = {
        "subscription_id": sub,
        "tracking_id": tracking_id,
        "event_type": rec.get("event_type"),
        "status": rec.get("status"),
        "level": rec.get("level"),
        "event_title": rec.get("title"),
        "summary": clean_summary(rec.get("summary")),
        "impact_start_utc": utc_iso(parse_ts(rec.get("impact_start_utc"))),
        "impact_end_utc": utc_iso(parse_ts(rec.get("impact_end_utc"))),
        "last_update_utc": utc_iso(last_update),
        "platform_initiated": bool(rec.get("platform_initiated")),
        "tags": rec.get("tags") if isinstance(rec.get("tags"), str) else dumps_compact(rec.get("tags") or []),
        "services": services,
        "regions": regions,
        "source": "arg",
    }
    return stamp(row, row_key("arg", sub, tracking_id, row["last_update_utc"]), now=now)


def impacted_row(rec: dict, now: dt.datetime | None = None) -> dict | None:
    if not rec.get("tracking_id"):
        return None
    sub = rec["subscription_id"]
    status = rec.get("status") or ""
    row = {
        "subscription_id": sub,
        "tracking_id": rec["tracking_id"],
        "resource_id": (rec.get("resource_id") or "").lower(),
        "resource_type": rec.get("resource_type"),
        "resource_name": rec.get("resource_name"),
        "region": rec.get("region"),
        "maintenance_start_utc": utc_iso(parse_ts(rec.get("maintenance_start_utc"))),
        "maintenance_end_utc": utc_iso(parse_ts(rec.get("maintenance_end_utc"))),
        "status": status,
    }
    # status text carries the state and its timestamp ("Finished at ..."), so it versions the row
    return stamp(row, row_key("arg", sub, f"{rec['tracking_id']}|{row['resource_id']}", status), now=now)


def inventory_row(rec: dict, snapshot: dt.date, now: dt.datetime | None = None) -> dict:
    snap = dt.datetime.combine(snapshot, dt.time(), tzinfo=dt.UTC)
    sub = rec["subscription_id"]
    row = {
        "snapshot_date": utc_iso(snap),
        "subscription_id": sub,
        "resource_type": rec.get("resource_type"),
        "region": rec.get("region"),
        "resource_count": int(rec.get("resource_count") or 0),
    }
    key = row_key("inventory", sub, f"{row['resource_type']}|{row['region']}", row["snapshot_date"])
    return stamp(row, key, now=now)


def annotation_row(rec: dict, now: dt.datetime | None = None) -> dict | None:
    occurred = parse_ts(rec.get("occurred_utc"))
    if occurred is None:
        return None
    sub = rec["subscription_id"]
    row = {
        "subscription_id": sub,
        "resource_id": rec.get("resource_id"),
        "region": rec.get("region"),
        "annotation_name": rec.get("annotation_name"),
        "category": rec.get("category"),
        "context": rec.get("context"),
        "reason": rec.get("reason"),
        "availability_state": rec.get("availability_state"),
        "previous_availability_state": rec.get("previous_availability_state"),
        "occurred_utc": utc_iso(occurred),
        "summary": rec.get("summary"),
    }
    key = row_key("vm_annotation", sub, f"{row['resource_id']}|{row['annotation_name']}", row["occurred_utc"])
    return stamp(row, key, now=now)
