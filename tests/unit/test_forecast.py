import random

import pytest

from analytics.forecast import (
    ForecastEvent,
    compute_forecast,
    confidence,
    load_config,
    percentile,
    pir_baseline,
    poisson,
    to_rows,
)

CFG = load_config(None)
CFG["seed"] = 42
CFG["simulations"] = 4000


def events(n, minutes=60.0, rh=None, svc="Storage", reg="East US"):
    return [ForecastEvent(f"E{i}", svc, reg, "Data", minutes, rh) for i in range(n)]


@pytest.mark.parametrize(
    "n,w,expected",
    [(2, 365, "insufficient"), (10, 60, "insufficient"), (3, 365, "low"), (5, 400, "low"), (8, 200, "low"),
     (6, 365, "medium"), (11, 365, "medium"), (12, 365, "high"), (30, 365, "high")],
)
def test_confidence_rules(n, w, expected):
    assert confidence(n, w) == expected


def test_poisson_mean():
    rng = random.Random(1)
    vals = [poisson(rng, 4.0) for _ in range(20000)]
    assert sum(vals) / len(vals) == pytest.approx(4.0, abs=0.1)
    assert poisson(rng, 0) == 0


def test_percentile_edges():
    assert percentile([1, 2, 3, 4], 0.5) == 2
    assert percentile([1, 2, 3, 4], 0.9) == 4


def test_seeded_forecast_is_reproducible_and_sensible():
    a = compute_forecast(events(12, 60.0, 30.0), 365, CFG)
    b = compute_forecast(events(12, 60.0, 30.0), 365, CFG)
    assert [r.p90_annual_h for r in a] == [r.p90_annual_h for r in b]
    svc = next(r for r in a if r.scope_level == "service")
    assert svc.n_events == 12 and svc.confidence == "high" and svc.duration_basis == "resource_health"
    assert svc.mean_annual_h == pytest.approx(12 * 0.5, rel=0.1)  # 12 events/yr x 30 min
    assert svc.p90_annual_h >= svc.p50_annual_h


def test_service_health_basis_when_any_event_lacks_resource_health():
    evs = events(3, 120.0, 30.0) + [ForecastEvent("X", "Storage", "East US", "Data", 120.0, None)]
    r = next(r for r in compute_forecast(evs, 365, CFG) if r.scope_level == "service")
    assert r.duration_basis == "service_health"


def test_thin_history_is_insufficient_and_every_row_has_n_window_confidence():
    results = compute_forecast(events(2), 365, CFG) + compute_forecast(events(10), 45, CFG)
    assert all(r.confidence == "insufficient" for r in results)
    for row in to_rows(results):
        assert row["n_events"] is not None and row["window_days"] is not None and row["confidence"]


def test_window_is_capped_by_coverage():
    r = compute_forecast(events(6), 200, CFG)[0]
    assert r.window_days == 200 and r.confidence == "low"


def test_duplicate_tracking_ids_count_once():
    evs = [ForecastEvent("E1", "S", "R1", "Data", 60, None), ForecastEvent("E1", "S", "R2", "Data", 60, None)]
    svc = next(r for r in compute_forecast(evs, 365, CFG) if r.scope_level == "service")
    assert svc.n_events == 1


def test_pir_baseline_labelled_public_pir():
    rows = to_rows(pir_baseline([("A", "Network", 4.0), ("B", "Network", 8.0), ("C", "AI", 2.0)], 1800, CFG))
    assert {r["baseline"] for r in rows} == {"public_pir"}
    assert any(r["scope_key"] == "(all categories)" for r in rows)
