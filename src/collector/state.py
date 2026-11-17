"""Watermarks in Azure Table Storage (identity auth only)."""

from __future__ import annotations

import os
from typing import Protocol


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


class TableState:
    TABLE = "aolstate"

    def __init__(self, account_url: str | None = None, credential=None):
        from azure.data.tables import TableServiceClient

        if credential is None:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
        svc = TableServiceClient(endpoint=account_url or os.environ["AOL_STATE_ACCOUNT_URL"], credential=credential)
        self._t = svc.create_table_if_not_exists(self.TABLE)

    def get(self, source: str) -> str | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return self._t.get_entity("wm", source).get("value")
        except ResourceNotFoundError:
            return None

    def set(self, source: str, value: str) -> None:
        self._t.upsert_entity({"PartitionKey": "wm", "RowKey": source, "value": value})
