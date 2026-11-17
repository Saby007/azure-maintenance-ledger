from pathlib import Path

import pytest

from collector import bootstrap, collectors
from collector.catalog import file_hash, read_catalog
from collector.health import RunResult
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


@pytest.fixture()
def wired(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(bootstrap.collectors, "configured_subscriptions", lambda: ["s1"])
    monkeypatch.setattr(bootstrap.collectors, "record_config", lambda ing, subs: calls.append("config"))
    monkeypatch.setattr(bootstrap.arg, "ArgClient", lambda *a, **k: object())
    monkeypatch.setattr(bootstrap.rest, "ArmSession", lambda *a, **k: object())
    for name in ("run_reference", "run_pirs", "run_service_health", "run_rest_backfill", "run_activity_backfill", "run_inventory"):
        monkeypatch.setattr(bootstrap.collectors, name, lambda *a, _n=name, **k: calls.append(_n) or RunResult())
    monkeypatch.setattr(bootstrap, "run_collector", lambda source, fn, ing: fn())
    monkeypatch.setenv("AOL_ENABLE_PIRS", "true")
    return calls


def test_bootstrap_runs_every_step_once_then_is_a_noop(wired):
    state = MemoryState()
    assert bootstrap.run_bootstrap(FakeIngestor(), state) is True
    assert wired == ["config", "run_reference", "run_pirs", "run_service_health", "run_rest_backfill", "run_activity_backfill", "run_inventory"]
    wired.clear()
    assert bootstrap.run_bootstrap(FakeIngestor(), state) is True
    assert wired == []


def test_bootstrap_failure_is_not_marked_done_and_retries(wired, monkeypatch):
    state = MemoryState()

    def boom(source, fn, ing):
        if source == "backfill_rest":
            raise RuntimeError("Reader role not propagated yet")
        return fn()

    monkeypatch.setattr(bootstrap, "run_collector", boom)
    with pytest.raises(RuntimeError):
        bootstrap.run_bootstrap(FakeIngestor(), state)
    assert state.get(bootstrap.DONE_KEY) is None


def test_bootstrap_skips_pirs_when_disabled(wired, monkeypatch):
    monkeypatch.setenv("AOL_ENABLE_PIRS", "false")
    bootstrap.run_bootstrap(FakeIngestor(), MemoryState())
    assert "run_pirs" not in wired
