"""Service catalog (reference/service_catalog.csv) -> AzServiceCatalog_CL rows. Shared by tools/load_reference.py and the Function bootstrap.

SLA percentages are never invented: a row without sla_percent shows "SLA not set". A non-blank sla_percent requires
sla_source_url and sla_verified_on, otherwise the row is rejected.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
from pathlib import Path

from .ingest import row_key, stamp, utc_iso


def read_catalog(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8", newline="") as fh:
        for i, r in enumerate(csv.DictReader(fh), start=2):
            name = (r.get("service_name") or "").strip()
            if not name:
                continue
            sla_raw = (r.get("sla_percent") or "").strip()
            sla = float(sla_raw) if sla_raw else None
            if sla is not None:
                if not (0 < sla <= 100):
                    raise ValueError(f"line {i}: sla_percent {sla} out of range")
                if not (r.get("sla_source_url") or "").strip() or not (r.get("sla_verified_on") or "").strip():
                    raise ValueError(f"line {i}: sla_percent set for '{name}' without sla_source_url and sla_verified_on")
            rows.append(
                {
                    "service_name": name,
                    "arm_resource_types": (r.get("arm_resource_types") or "").strip(),
                    "category": (r.get("category") or "").strip(),
                    "sla_percent": sla,
                    "sla_source_url": (r.get("sla_source_url") or "").strip(),
                    "sla_verified_on": (r.get("sla_verified_on") or "").strip(),
                    "notes": (r.get("notes") or "").strip(),
                }
            )
    return rows


def build_rows(catalog: list[dict], now: dt.datetime | None = None) -> list[dict]:
    now = now or dt.datetime.now(dt.UTC)
    stamp_s = utc_iso(now) or ""
    # one load = one ingested_utc, so AzOutage_Catalog() can select the latest complete load
    return [stamp(c, row_key("catalog", "-", c["service_name"], stamp_s), now=now) for c in catalog]


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
