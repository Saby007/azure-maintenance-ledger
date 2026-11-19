"""Service Health via ARM REST (up to 1 year, needs queryStartTime) and Activity Log backfill (last 89 days)."""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from collections.abc import Iterator
from typing import Any

from ..ingest import retry, row_key, stamp, utc_iso
from .arg import clean_summary, parse_ts, services_and_regions

log = logging.getLogger("aml.rest")

ARM = "https://management.azure.com"
SCOPE = "https://management.azure.com/.default"
EVENTS_API = "2022-10-01"
ACTIVITY_API = "2015-04-01"


class ArmSession:
    def __init__(self, credential: Any = None):
        import requests

        if credential is None:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
        self._cred = credential
        self._s = requests.Session()
        self._lock = threading.Lock()
        self._token: Any = None

    def _bearer(self) -> str:
        with self._lock:  # one token fetch at a time (the az CLI credential spawns a process per call)
            if self._token is None or self._token.expires_on - time.time() < 300:
                self._token = self._cred.get_token(SCOPE)
            return self._token.token

    def get(self, url: str, params: dict | None = None) -> dict:
        import requests

        def call() -> dict:
            token = self._bearer()
            r = self._s.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=120)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")  # not retried
            return r.json()

        return retry(call, attempts=6, base=2.0, retry_on=(requests.HTTPError, requests.ConnectionError, requests.Timeout))

    def pages(self, url: str, params: dict | None = None) -> Iterator[dict]:
        data = self.get(url, params)
        while True:
            yield from data.get("value", [])
            nxt = data.get("nextLink")
            if not nxt:
                return
            data = self.get(nxt)


def _impact_pascal(impact: list[dict] | None) -> list[dict]:
    """REST uses camelCase; normalise to the ARG shape consumed by services_and_regions."""
    out = []
    for i in impact or []:
        out.append(
            {
                "ImpactedService": i.get("impactedService"),
                "ImpactedRegions": [
                    {"ImpactedRegion": r.get("impactedRegion"), "Status": r.get("status")} for r in i.get("impactedRegions") or []
                ],
            }
        )
    return out


def rest_event_row(subscription_id: str, item: dict, now: dt.datetime | None = None) -> dict | None:
    p = item.get("properties") or {}
    tracking_id = p.get("trackingId") or item.get("name")
    last_update = parse_ts(p.get("lastUpdateTime"))
    if not tracking_id or last_update is None:
        return None
    services, regions = services_and_regions(_impact_pascal(p.get("impact")))
    row = {
        "subscription_id": subscription_id,
        "tracking_id": tracking_id,
        "event_type": p.get("eventType"),
        "status": p.get("status"),
        "level": p.get("level"),
        "event_title": p.get("title"),
        "summary": clean_summary(p.get("summary")),
        "impact_start_utc": utc_iso(parse_ts(p.get("impactStartTime"))),
        "impact_end_utc": utc_iso(parse_ts(p.get("impactMitigationTime"))),
        "last_update_utc": utc_iso(last_update),
        "platform_initiated": bool(p.get("platformInitiated")),
        "tags": ",".join(p.get("eventTags") or []),
        "services": services,
        "regions": regions,
        "source": "rest",
    }
    return stamp(row, row_key("rest", subscription_id, tracking_id, row["last_update_utc"]), now=now)


def fetch_rest_events(session: ArmSession, subscription_id: str, days: int = 365) -> Iterator[dict]:
    start = (dt.datetime.now(dt.UTC) - dt.timedelta(days=days)).strftime("%m/%d/%Y")
    url = f"{ARM}/subscriptions/{subscription_id}/providers/Microsoft.ResourceHealth/events"
    yield from session.pages(url, {"api-version": EVENTS_API, "queryStartTime": start})


def resource_type_from_id(resource_id: str) -> str | None:
    """Namespace/type[/childtype...] from an ARM resource id (…/providers/ns/type/name[/childtype/name]…)."""
    marker = "/providers/"
    if marker not in resource_id:
        return None
    segs = resource_id.rsplit(marker, 1)[1].split("/")
    if len(segs) < 2:
        return None
    return "/".join([segs[0], *segs[1::2][:1], *segs[3::2][:2]])


def activity_resource_health_row(subscription_id: str, item: dict, now: dt.datetime | None = None) -> dict | None:
    cat = (item.get("category") or {}).get("value")
    if cat != "ResourceHealth":
        return None
    p = item.get("properties") or {}
    resource_id = (item.get("resourceId") or "").lower()
    event_data_id = item.get("eventDataId")
    event_ts = parse_ts(item.get("eventTimestamp"))
    if not resource_id or not event_data_id or event_ts is None:
        return None
    resource_type = resource_type_from_id(resource_id)
    row = {
        "event_data_id": event_data_id,
        "resource_id": resource_id,
        "resource_type": resource_type,
        "subscription_id": subscription_id,
        "status": (item.get("status") or {}).get("value"),
        "current_status": p.get("currentHealthStatus"),
        "previous_status": p.get("previousHealthStatus"),
        "health_type": p.get("type"),
        "cause": p.get("cause"),
        "event_utc": utc_iso(event_ts),
    }
    return stamp(row, row_key("activitylog", subscription_id, event_data_id, row["event_utc"]), now=now)


def fetch_activity_log(session: ArmSession, subscription_id: str, days: int = 89, workers: int = 6) -> Iterator[dict]:
    """Activity Log keeps 90 days. Category cannot be filtered server side: filter client side.

    The range is split into day slices fetched in parallel (pages are small and slow), with $select to cut payload.
    """
    from concurrent.futures import ThreadPoolExecutor

    end = dt.datetime.now(dt.UTC)
    slices = []
    for i in range(days):
        s_end = end - dt.timedelta(days=i)
        slices.append((s_end - dt.timedelta(days=1), s_end))
    url = f"{ARM}/subscriptions/{subscription_id}/providers/Microsoft.Insights/eventtypes/management/values"
    select = "eventDataId,resourceId,eventTimestamp,status,properties,category"

    def one(rng: tuple[dt.datetime, dt.datetime]) -> list[dict]:
        s, e = rng
        flt = f"eventTimestamp ge '{s:%Y-%m-%dT%H:%M:%SZ}' and eventTimestamp le '{e:%Y-%m-%dT%H:%M:%SZ}'"
        return [
            it
            for it in session.pages(url, {"api-version": ACTIVITY_API, "$filter": flt, "$select": select})
            if (it.get("category") or {}).get("value") == "ResourceHealth"
        ]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for chunk in pool.map(one, slices):
            yield from chunk
