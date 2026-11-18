"""Watermarks and 'already done' markers.

The deployed collector runs as a Container Apps Job with no storage account (many tenants disable public access on storage by
policy), so its state lives in the workspace: LogState reads the ingest-health table and writes marker rows to it.
MemoryState is used by the local CLI and tests.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Protocol

from .ingest import row_key, stamp, utc_iso

HEALTH_TABLE = "AzMaintenanceIngestHealth_CL"


class WatermarkStore(Protocol):
    def get(self, source: str) -> str | None: ...
    def set(self, source: str, value: str) -> None: ...


class MemoryState:
    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    def get(self, source: str) -> str | None:
        return self._d.get(source)

    def set(self, source: str, value: str) -> None:
        self._d[source] = value

    def last_success(self, source: str) -> dt.datetime | None:
        return None


def state_row(key: str, value: str, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.UTC)
    stamp_s = utc_iso(now) or ""
    row = {
        "run_id": f"state-{key}",
        "source": f"state:{key}",
        "started_utc": stamp_s,
        "finished_utc": stamp_s,
        "rows_read": 0,
        "rows_written": 0,
        "watermark_utc": stamp_s,
        "status": "state",
        "state_value": value,
        "errors": [],
    }
    return stamp(row, row_key("state", "-", key, stamp_s), now=now)


class LogState:
    """State kept as rows of the ingest-health table. `reader` runs the KQL in kql/queries, `ingestor` writes marker rows."""

    def __init__(self, reader: Any, ingestor: Any, load_query: Any):
        self._reader = reader
        self._ing = ingestor
        self._load = load_query

    def _query(self, name: str, key: str) -> list[dict]:
        return self._reader.rows(self._load(name).replace("{KEY}", key.replace('"', "")))

    def get(self, key: str) -> str | None:
        rows = self._query("state_value", key)
        value = rows[0].get("state_value") if rows else None
        return str(value) if value else None

    def set(self, key: str, value: str) -> None:
        self._ing.upload(HEALTH_TABLE, [state_row(key, value)])

    def last_success(self, source: str) -> dt.datetime | None:
        rows = self._query("state_last_success", source)
        value = rows[0].get("last_success") if rows else None
        if value is None:
            return None
        if isinstance(value, dt.datetime):
            return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
