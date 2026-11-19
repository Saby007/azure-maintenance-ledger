"""Idempotent append-only ingestion helpers (AGENTS.md A4)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import random
import time
from collections.abc import Callable, Iterable, Iterator
from typing import Any, TypeVar

log = logging.getLogger("aml.ingest")

T = TypeVar("T")

# table name -> Logs Ingestion stream name
def stream_name(table: str) -> str:
    return f"Custom-{table}"


def utc_iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def row_key(source: str, subscription_id: str, key: str, last_update: str) -> str:
    return hashlib.sha256(f"{source}|{subscription_id}|{key}|{last_update}".encode()).hexdigest()


def stamp(row: dict[str, Any], key: str, *, now: dt.datetime | None = None, synthetic: bool = False) -> dict:
    """Add the common columns. `key` is the pre-computed row_key."""
    now_s = utc_iso(now or dt.datetime.now(dt.UTC))
    out = dict(row)
    out["TimeGenerated"] = now_s
    out["ingested_utc"] = now_s
    out["row_key"] = key
    out["is_synthetic"] = synthetic
    return out


def retry(fn: Callable[[], T], *, attempts: int = 5, base: float = 1.0, retry_on: tuple = (Exception,)) -> T:
    """Exponential backoff with jitter."""
    for i in range(attempts):
        try:
            return fn()
        except retry_on as exc:
            if i == attempts - 1:
                raise
            delay = base * (2**i) + random.uniform(0, base)
            log.warning("retry %d/%d after %.1fs: %s", i + 1, attempts, delay, type(exc).__name__)
            time.sleep(delay)
    raise RuntimeError("unreachable")


def chunked(rows: Iterable[T], size: int) -> Iterator[list[T]]:
    batch: list[T] = []
    for r in rows:
        batch.append(r)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


class Ingestor:
    """Uploads rows to the Direct DCR through the Logs Ingestion API using the managed identity."""

    def __init__(self, endpoint: str | None = None, rule_id: str | None = None, credential: Any = None):
        self.endpoint = endpoint or os.environ["AML_DCR_ENDPOINT"]
        self.rule_id = rule_id or os.environ["AML_DCR_IMMUTABLE_ID"]
        if credential is None:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
        from azure.monitor.ingestion import LogsIngestionClient

        self._client = LogsIngestionClient(endpoint=self.endpoint, credential=credential, logging_enable=False)

    def upload(self, table: str, rows: list[dict], batch_size: int = 500) -> int:
        written = 0
        for batch in chunked(rows, batch_size):
            retry(lambda b=batch: self._client.upload(rule_id=self.rule_id, stream_name=stream_name(table), logs=b))
            written += len(batch)
        return written


def dumps_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
