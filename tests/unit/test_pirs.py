import datetime as dt
from pathlib import Path

import pytest

from collector.sources.pir_parser import category_of, load_overrides, parse_window
from collector.sources.pirs import JsonPirSource, build_rows

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "pirs.json"
OVERRIDES = ROOT / "reference" / "pir_overrides.csv"
PUB = dt.date(2026, 9, 30)


def test_dmy_format_two_times_one_date():
    w = parse_window("Between 08:00 UTC and 16:09 UTC on 14 October 2026, some customers", PUB)
    assert w.start == dt.datetime(2026, 10, 14, 8, 0)
    assert w.end == dt.datetime(2026, 10, 14, 16, 9)
    assert w.status == "ok"


def test_mdy_format():
    w = parse_window("Between 13:10 UTC and 18:55 UTC on September 30, 2026, customers", PUB)
    assert w.start == dt.datetime(2026, 9, 30, 13, 10)
    assert w.duration_h == pytest.approx(5.75)


def test_end_before_start_rolls_to_next_day():
    w = parse_window("From 22:00 UTC on 3 May 2025 to 02:30 UTC, customers", PUB)
    assert w.end == dt.datetime(2025, 5, 4, 2, 30)


def test_two_dates():
    w = parse_window("Between 23:00 UTC on 1 March 2025 and 04:00 UTC on 2 March 2025, impact", PUB)
    assert w.duration_h == pytest.approx(5.0)


def test_window_over_14_days_rejected():
    assert parse_window("Between 00:00 UTC on 1 January 2025 and 00:00 UTC on 20 January 2025, x", PUB) is None


def test_narrow_nbsp_and_lowercase():
    text = "between\u202f00:55 UTC and 06:28 UTC on 12 July 2024. All identities"
    w = parse_window(text, dt.date(2024, 7, 12))
    assert w is not None and w.duration_h == pytest.approx(5.55, abs=0.01)


def test_no_window_returns_none():
    assert parse_window("Customers may have experienced issues.", PUB) is None


def test_category_word_boundaries():
    # "Central" must not match "entra"
    assert category_of("Azure OpenAI Service - Sweden Central") == "AI"
    assert category_of("Entra ID sign-in failures") == "Identity"
    assert category_of("Gateway service degradation") == "Network"
    assert category_of("Virtual Machines startup failures") == "IaaS"


def test_known_unparsed_fixtures_resolve_via_overrides():
    rows = build_rows(JsonPirSource(FIXTURE).items(), OVERRIDES)
    by_id = {r["tracking_id"]: r for r in rows}
    for tid in ("1VT1-LX0", "FTVR-L9Z", "VVTQ-J98"):
        assert by_id[tid]["parse_status"] == "manual"
    assert by_id["FTVR-L9Z"]["duration_h"] == pytest.approx(5.55, abs=0.01)
    assert by_id["1VT1-LX0"]["duration_h"] is None


def test_fixture_parse_rate():
    items = list(JsonPirSource(FIXTURE).items())
    assert len(items) == 80
    rows = build_rows(items, None)
    ok = [r for r in rows if r["parse_status"] == "ok"]
    assert len(ok) >= 77  # acceptance: >= 77 of 80 (target >= 95% = 76)
    with_overrides = build_rows(items, OVERRIDES)
    assert sum(r["parse_status"] == "unparsed" for r in with_overrides) == 0


def test_overrides_loader_skips_comments():
    o = load_overrides(OVERRIDES)
    assert set(o) == {"1VT1-LX0", "FTVR-L9Z", "VVTQ-J98"}


def test_rows_are_idempotent_keys():
    items = list(JsonPirSource(FIXTURE).items())
    a = {r["row_key"] for r in build_rows(items, OVERRIDES)}
    b = {r["row_key"] for r in build_rows(items, OVERRIDES)}
    assert a == b and len(a) == 80
