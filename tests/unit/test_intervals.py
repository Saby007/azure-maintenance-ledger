import datetime as dt

import pytest

from analytics.intervals import HealthEvent, build_intervals, clip, downtime_minutes, merge_intervals

T0 = dt.datetime(2026, 1, 1, 10, 0, tzinfo=dt.UTC)
NOW = T0 + dt.timedelta(days=2)


def ev(minutes: int, state: str, cause: str = "PlatformInitiated", rid: str = "/r/a", eid: str | None = None):
    return HealthEvent(rid, T0 + dt.timedelta(minutes=minutes), state, cause, eid)


def test_basic_interval_closes_on_available():
    ivs = build_intervals([ev(0, "Available"), ev(10, "Unavailable"), ev(15, "Available")], NOW)
    assert len(ivs) == 1 and ivs[0].minutes == 5 and not ivs[0].is_open


def test_open_incident_ends_at_now_and_is_flagged():
    ivs = build_intervals([ev(10, "Unavailable")], NOW)
    assert ivs[0].is_open and ivs[0].end == NOW


def test_duplicate_active_rows_do_not_split_or_double_count():
    ivs = build_intervals([ev(10, "Unavailable"), ev(11, "Unavailable"), ev(12, "Unavailable"), ev(20, "Available")], NOW)
    assert len(ivs) == 1 and ivs[0].minutes == 10


def test_duplicate_event_ids_are_dropped():
    ivs = build_intervals([ev(10, "Unavailable", eid="x"), ev(10, "Unavailable", eid="x"), ev(20, "Available", eid="y")], NOW)
    assert len(ivs) == 1


def test_out_of_order_rows():
    ivs = build_intervals([ev(20, "Available"), ev(10, "Unavailable"), ev(0, "Available")], NOW)
    assert len(ivs) == 1 and ivs[0].minutes == 10


def test_unknown_state_is_skipped_and_does_not_close():
    ivs = build_intervals([ev(10, "Unavailable"), ev(12, "Unknown"), ev(20, "Available")], NOW)
    assert len(ivs) == 1 and ivs[0].minutes == 10


def test_user_initiated_excluded_by_default():
    ivs = build_intervals([ev(10, "Unavailable", "UserInitiated"), ev(40, "Available")], NOW)
    assert downtime_minutes(ivs, T0, NOW) == 0
    assert downtime_minutes(ivs, T0, NOW, include_user_initiated=True) == 30


def test_degraded_reported_separately_from_unavailable():
    ivs = build_intervals([ev(10, "Degraded"), ev(30, "Unavailable"), ev(40, "Available")], NOW)
    assert downtime_minutes(ivs, T0, NOW) == 10
    assert downtime_minutes(ivs, T0, NOW, state="Degraded") == 20


def test_overlapping_intervals_merge_once():
    a = build_intervals([ev(10, "Unavailable"), ev(30, "Available")], NOW)
    b = build_intervals([ev(20, "Unavailable"), ev(50, "Available")], NOW)
    merged = merge_intervals(a + b)
    assert len(merged) == 1 and merged[0].minutes == 40
    assert downtime_minutes(a + b, T0, NOW) == 40


def test_interval_crossing_window_edge_is_clipped():
    ivs = build_intervals([ev(-30, "Unavailable"), ev(30, "Available")], NOW)
    ws = T0
    assert clip(ivs[0], ws, NOW).minutes == 30
    assert downtime_minutes(ivs, ws, NOW) == 30
    assert downtime_minutes(ivs, T0 + dt.timedelta(minutes=40), NOW) == 0


def test_resources_are_independent():
    ivs = build_intervals([ev(10, "Unavailable", rid="/r/a"), ev(10, "Available", rid="/r/b"), ev(20, "Available", rid="/r/a")], NOW)
    assert len(ivs) == 1 and ivs[0].resource_id == "/r/a"


def test_open_interval_older_than_three_days_is_stale_and_excluded():
    ivs = build_intervals([ev(10, "Unavailable")], T0 + dt.timedelta(days=10))
    assert ivs[0].is_open
    assert downtime_minutes(ivs, T0, T0 + dt.timedelta(days=10)) == 0
    fresh = build_intervals([ev(10, "Unavailable")], T0 + dt.timedelta(days=1))
    assert downtime_minutes(fresh, T0, T0 + dt.timedelta(days=1)) > 0


@pytest.mark.parametrize("n", [1])
def test_case_insensitive_resource_ids(n):
    ivs = build_intervals([ev(10, "Unavailable", rid="/R/A"), ev(20, "Available", rid="/r/a")], NOW)
    assert len(ivs) == 1 and ivs[0].minutes == 10
