import datetime as dt

from collector.sources import arg
from collector.sources.rest import rest_event_row

NOW = dt.datetime(2026, 11, 17, tzinfo=dt.UTC)

ARG_REC = {
    "subscription_id": "s1",
    "tracking_id": "ABC-123",
    "event_type": "ServiceIssue",
    "status": "Resolved",
    "level": "Warning",
    "title": "Synthetic issue",
    "summary": "<p><strong>What happened?</strong></p><p>x &amp; y</p>",
    "impact_start_utc": "2026-10-14T13:57:30.907Z",
    "impact_end_utc": "2026-10-14T16:09:00Z",
    "last_update_utc": "2026-10-14T17:18:55.3593561Z",
    "platform_initiated": 1,
    "tags": "[]",
    "impact": [{"ImpactedService": "Storage", "ImpactedRegions": [{"ImpactedRegion": "East US", "Status": "Resolved"}]}],
}


def test_arg_event_row_shape_and_cleaning():
    r = arg.event_row(ARG_REC, now=NOW)
    assert r["source"] == "arg" and r["services"] == ["Storage"] and r["regions"] == ["East US"]
    assert r["summary"] == "What happened? x & y"
    assert r["last_update_utc"] == "2026-10-14T17:18:55.359356Z"  # 7-digit ticks truncated to microseconds
    assert r["platform_initiated"] is True and r["is_synthetic"] is False
    assert r["event_title"] == "Synthetic issue"


def test_zero_ticks_mean_not_set():
    r = arg.event_row({**ARG_REC, "impact_end_utc": "0001-01-01T00:00:00Z"}, now=NOW)
    assert r["impact_end_utc"] is None


def test_row_key_is_stable_and_changes_with_last_update():
    a = arg.event_row(ARG_REC, now=NOW)["row_key"]
    assert a == arg.event_row(ARG_REC, now=NOW + dt.timedelta(days=1))["row_key"]
    assert a != arg.event_row({**ARG_REC, "last_update_utc": "2026-10-15T00:00:00Z"}, now=NOW)["row_key"]
    assert a != arg.event_row({**ARG_REC, "subscription_id": "s2"}, now=NOW)["row_key"]


def test_same_tracking_id_in_two_subscriptions_gives_two_rows_one_event():
    rows = [arg.event_row({**ARG_REC, "subscription_id": s}, now=NOW) for s in ("s1", "s2")]
    assert len({r["row_key"] for r in rows}) == 2 and len({r["tracking_id"] for r in rows}) == 1


def test_inventory_and_impacted_rows():
    inv = arg.inventory_row({"subscription_id": "s", "resource_type": "microsoft.web/sites", "region": "eastus", "resource_count": 4}, dt.date(2026, 11, 17), now=NOW)
    assert inv["resource_count"] == 4 and inv["snapshot_date"].startswith("2026-11-17")
    imp = arg.impacted_row({"subscription_id": "s", "tracking_id": "T", "resource_id": "/A/B", "status": "Finished at x"}, now=NOW)
    assert imp["resource_id"] == "/a/b"
    assert arg.impacted_row({"subscription_id": "s"}) is None


def test_rest_event_row_maps_camel_case():
    item = {
        "name": "T1",
        "properties": {
            "trackingId": "T1", "eventType": "PlannedMaintenance", "status": "Active", "level": "Warning", "title": "t", "summary": "<p>s</p>",
            "impactStartTime": "2026-11-20T00:00:00Z", "impactMitigationTime": "2026-11-20T02:00:00Z", "lastUpdateTime": "2026-11-10T00:00:00Z",
            "platformInitiated": True, "eventTags": ["a", "b"],
            "impact": [{"impactedService": "SQL", "impactedRegions": [{"impactedRegion": "West US"}]}],
        },
    }
    r = rest_event_row("s", item, now=NOW)
    assert r["source"] == "rest" and r["services"] == ["SQL"] and r["regions"] == ["West US"] and r["tags"] == "a,b"
    assert r["event_type"] == "PlannedMaintenance"
