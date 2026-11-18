from pathlib import Path

import pytest

from collector import collectors
from collector.catalog import file_hash, read_catalog
from collector.state import MemoryState

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "reference" / "service_catalog.csv"


class FakeIngestor:
    def __init__(self):
        self.tables: dict[str, int] = {}

    def upload(self, table, rows, batch_size=500):
        self.tables[table] = self.tables.get(table, 0) + len(rows)
        return len(rows)


def test_reference_loads_once_per_content_hash():
    ing, state = FakeIngestor(), MemoryState()
    first = collectors.run_reference(ing, state, CATALOG)
    assert first.rows_written == len(read_catalog(CATALOG)) > 40
    assert state.get("reference_hash") == file_hash(CATALOG)
    second = collectors.run_reference(ing, state, CATALOG)
    assert second.rows_written == 0 and ing.tables["AzServiceCatalog_CL"] == first.rows_written


def test_catalog_rejects_sla_without_source(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("service_name,arm_resource_types,category,sla_percent,sla_source_url,sla_verified_on,notes\nX,a/b,IaaS,99.9,,,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="sla_source_url"):
        read_catalog(p)
