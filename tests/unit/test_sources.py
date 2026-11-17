from collector.sources.rest import activity_resource_health_row, resource_type_from_id


def test_resource_type_from_id():
    base = "/subscriptions/s/resourcegroups/rg/providers"
    assert resource_type_from_id(f"{base}/microsoft.compute/virtualmachines/vm1") == "microsoft.compute/virtualmachines"
    assert resource_type_from_id(f"{base}/microsoft.sql/servers/srv/databases/db") == "microsoft.sql/servers/databases"
    assert resource_type_from_id(f"{base}/microsoft.web/sites/a/slots/s") == "microsoft.web/sites/slots"
    assert resource_type_from_id("/subscriptions/s") is None


def test_activity_row_mapping_matches_observed_shape():
    item = {
        "eventDataId": "e1",
        "resourceId": "/SUBSCRIPTIONS/S/RESOURCEGROUPS/RG/PROVIDERS/MICROSOFT.DBFORPOSTGRESQL/FLEXIBLESERVERS/PG1",
        "eventTimestamp": "2026-11-14T19:09:13.8021622Z",
        "status": {"value": "Active"},
        "category": {"value": "ResourceHealth"},
        "properties": {"currentHealthStatus": "Degraded", "previousHealthStatus": "Available", "type": "Downtime", "cause": "UserInitiated"},
    }
    r = activity_resource_health_row("s", item)
    assert r["resource_type"] == "microsoft.dbforpostgresql/flexibleservers"
    assert (r["current_status"], r["previous_status"], r["health_type"], r["cause"]) == ("Degraded", "Available", "Downtime", "UserInitiated")
    assert r["event_utc"] == "2026-11-14T19:09:13.802162Z" and r["is_synthetic"] is False
    assert activity_resource_health_row("s", {**item, "category": {"value": "Administrative"}}) is None
