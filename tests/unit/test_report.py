import datetime as dt
import re
from pathlib import Path

from reporting import render_report as rr


class FakeReader:
    """Returns canned rows by recognising which query was asked for."""

    def __init__(self, empty: bool = False):
        self.empty = empty
        self.queries: list[str] = []

    def rows(self, query: str, days: int = 800) -> list[dict]:
        self.queries.append(query)
        if self.empty:
            return []
        if "01_overview_tiles" in query or "datatable(order: int)[1, 2, 3, 4, 5, 6]" in query:
            return [{"metric": "Unplanned events", "value": 3.0, "subtitle": "Azure incidents nobody scheduled", "status": "warn"},
                    {"metric": "Observed downtime (minutes)", "value": 45.0, "subtitle": "x", "status": "good"}]
        if "summarize events = dcount(tracking_id) by category, class" in query:
            return [{"category": "IaaS", "class": "Planned", "events": 1}, {"category": "IaaS", "class": "Unplanned", "events": 2}]
        if "startofmonth(impact_start_utc)" in query:
            return [{"month": dt.datetime(2026, 9, 1), "class": "Unplanned", "events": 2}, {"month": dt.datetime(2026, 10, 1), "class": "Planned", "events": 1}]
        if "startofmonth(start_utc)" in query:
            return [{"month": dt.datetime(2026, 10, 1), "class": "Unplanned", "downtime_min": 45.0}]
        if "AzMaintenance_Forecast" in query:
            return [{"baseline": "customer", "scope_level": "service", "scope_key": "Virtual Machines", "n_events": 2, "window_days": 200,
                     "confidence": "insufficient", "events_per_year": 3.65, "p50_annual_h": 1.0, "p90_annual_h": 2.0, "duration_basis": "resource_health"},
                    {"baseline": "public_pir", "scope_level": "category", "scope_key": "Network", "n_events": 12, "window_days": 1800,
                     "confidence": "high", "events_per_year": 2.4, "p50_annual_h": 20.0, "p90_annual_h": 40.0, "duration_basis": "resource_health"}]
        if "AzMaintenance_DataHealth" in query:
            return [{"section": "ingest", "item": "inventory", "status": "STALE", "value": 1, "detail": "x"}]
        return [{"a": 1, "b": "<script>alert(1)</script>", "d": dt.datetime(2026, 10, 1, tzinfo=dt.UTC), "dyn": ["x"]}]


def test_report_files_are_generated_and_self_contained(tmp_path: Path):
    h, x = rr.generate(FakeReader(), 90, tmp_path, now=dt.datetime(2026, 11, 17, tzinfo=dt.UTC))
    text = h.read_text(encoding="utf-8")
    assert "Methodology and caveats" in text and text.index("Methodology") < text.index("Overview")
    assert not re.search(r'(src|href)\s*=\s*["\']https?://', text), "no external resources"
    assert "<script" not in text.lower().replace("&lt;script", ""), "cell content must be escaped"
    assert "&lt;script&gt;" in text
    assert "<svg" in text and "not a forecast or a guarantee" in text
    assert "attention needed" in text  # stale data health is surfaced

    from openpyxl import load_workbook

    wb = load_workbook(x)
    assert wb.sheetnames == ["Summary", *rr.SHEETS]
    assert wb["Events"]["A2"].value == 1


def test_empty_ledger_renders_empty_states(tmp_path: Path):
    h, x = rr.generate(FakeReader(empty=True), 90, tmp_path, now=dt.datetime(2026, 11, 17, tzinfo=dt.UTC))
    text = h.read_text(encoding="utf-8")
    assert "No data yet." in text and "No events in the window." in text and "No planning ranges yet." in text
    from openpyxl import load_workbook

    assert load_workbook(x)["Events"]["A1"].value == "(no rows)"


def test_window_token_is_applied_to_every_query():
    r = FakeReader()
    rr.collect(r, 45)
    assert not any("{WindowDays}" in q or "{TimeRange" in q for q in r.queries)
    assert any("ago(45d)" in q for q in r.queries)
