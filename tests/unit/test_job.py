import datetime as dt

import pytest

from collector import job
from collector.health import RunResult
from collector.state import LogState, MemoryState, state_row

NOW = dt.datetime(2026, 11, 18, 10, 0, tzinfo=dt.UTC)


class FakeIngestor:
    def __init__(self):
        self.tables: dict[str, list] = {}

    def upload(self, table, rows, batch_size=500):
        self.tables.setdefault(table, []).extend(rows)
        return len(rows)


class FakeState(MemoryState):
    """MemoryState + controllable last_success per source."""

    def __init__(self, last=None):
        super().__init__()
        self.last = last or {}

    def last_success(self, source):
        return self.last.get(source)


@pytest.fixture()
def wired(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(job.collectors, "configured_subscriptions", lambda: ["s1"])
    monkeypatch.setattr(job.collectors, "record_config", lambda ing, subs: calls.append("config"))
    for name in ("run_reference", "run_pirs", "run_service_health", "run_rest_backfill", "run_activity_backfill", "run_inventory",
                 "run_vm_annotations"):
        monkeypatch.setattr(job.collectors, name, lambda *a, _n=name, **k: calls.append(_n) or RunResult())
    monkeypatch.setattr(job, "run_forecast", lambda *a, **k: calls.append("run_forecast") or RunResult())
    monkeypatch.setattr(job, "run_collector", lambda source, fn, ing: fn())
    monkeypatch.setenv("AOL_ENABLE_PIRS", "true")
    monkeypatch.setenv("AOL_ENABLE_VM_ANNOTATIONS", "true")
    return calls


def collect(state, now=NOW):
    return job.run_collect(FakeIngestor(), object(), state, now, client=object(), session=object())


def test_first_run_bootstraps_every_step_once(wired):
    state = FakeState()
    res = collect(state)
    assert all(v == "ok" for v in res.values()) and len(res) == 7
    assert state.get("bootstrap_done")
    assert wired[0] == "config" and wired.count("run_rest_backfill") == 1
    wired.clear()
    # a second run shortly after: nothing is re-bootstrapped and, with fresh successes recorded, nothing else is due
    state.last = {k: NOW for k in ("servicehealth_events", "inventory", "vm_annotations", "forecast")}
    state.set("pirs_month", "2026-11")
    res2 = collect(state, NOW + dt.timedelta(minutes=10))
    assert wired == ["run_reference"]
    assert "failed" not in " ".join(res2.values())


def test_failed_step_is_retried_alone_and_bootstrap_not_done(wired, monkeypatch):
    state = FakeState()
    boom = {"n": 0}

    def flaky(source, fn, ing):
        if source == "backfill_rest" and boom["n"] == 0:
            boom["n"] += 1
            raise RuntimeError("Reader role not propagated yet")
        return fn()

    monkeypatch.setattr(job, "run_collector", flaky)
    res = collect(state)
    assert res["rest"].startswith("failed") and state.get("bootstrap_done") is None
    assert state.get("bootstrap:rest") is None and state.get("bootstrap:inventory")
    wired.clear()
    res2 = collect(state, NOW + dt.timedelta(hours=1))
    assert res2 == {"rest": "ok"} and wired == ["config", "run_rest_backfill"]
    assert state.get("bootstrap_done")


def test_pirs_step_skipped_when_disabled(wired, monkeypatch):
    monkeypatch.setenv("AOL_ENABLE_PIRS", "false")
    monkeypatch.setenv("AOL_ENABLE_VM_ANNOTATIONS", "false")
    res = collect(FakeState())
    assert "pirs" not in res and "vm_annotations" not in res


def done_state(last):
    s = FakeState(last)
    for step in ("reference", "pirs", "servicehealth", "rest", "activity", "inventory", "vm_annotations"):
        s.set(f"bootstrap:{step}", "x")
    s.set("bootstrap_done", "2026-11-01T00:00:00Z")
    return s


def test_steady_state_runs_only_what_is_due(wired):
    fresh = NOW - dt.timedelta(hours=2)
    state = done_state({"servicehealth_events": fresh, "inventory": fresh, "vm_annotations": fresh, "forecast": fresh})
    state.set("pirs_month", "2026-11")
    res = collect(state)
    assert res["servicehealth"] == res["inventory"] == res["vm_annotations"] == res["forecast"] == res["pirs"] == "skipped"
    assert wired == ["run_reference"]


def test_steady_state_due_tasks_run(wired):
    old = NOW - dt.timedelta(hours=30)
    state = done_state({"servicehealth_events": old, "inventory": old, "vm_annotations": NOW - dt.timedelta(hours=6), "forecast": old})
    res = collect(state)
    assert {k: v for k, v in res.items() if k != "reference"} == {
        "servicehealth": "ok", "inventory": "ok", "vm_annotations": "ok", "pirs": "ok", "forecast": "ok"}
    assert state.get("pirs_month") == "2026-11"
    assert {"run_service_health", "run_inventory", "run_vm_annotations", "run_pirs", "run_forecast"} <= set(wired)


def test_pirs_wait_until_day_two(wired):
    state = done_state({k: NOW for k in ("servicehealth_events", "inventory", "vm_annotations", "forecast")})
    res = collect(state, dt.datetime(2026, 12, 1, 5, tzinfo=dt.UTC))
    assert res["pirs"] == "skipped"
    res = collect(state, dt.datetime(2026, 12, 2, 5, tzinfo=dt.UTC))
    assert res["pirs"] == "ok" and state.get("pirs_month") == "2026-12"


def test_forecast_waits_for_ingestion_after_bootstrap(wired):
    state = done_state({k: NOW for k in ("servicehealth_events", "inventory", "vm_annotations")})
    state.set("bootstrap_done", job.utc_iso(NOW - dt.timedelta(minutes=10)))
    assert collect(state)["forecast"] == "skipped"
    state.set("bootstrap_done", job.utc_iso(NOW - dt.timedelta(hours=2)))
    assert collect(state)["forecast"] == "ok"


def test_task_failure_is_reported_for_the_job_exit_code(wired, monkeypatch):
    state = done_state({})

    def boom(source, fn, ing):
        if source == "inventory":
            raise RuntimeError("x")
        return fn()

    monkeypatch.setattr(job, "run_collector", boom)
    res = collect(state)
    assert res["inventory"].startswith("failed") and res["servicehealth"] == "ok"


def test_log_state_reads_and_writes_through_health_table():
    ing = FakeIngestor()
    seen = []

    class Reader:
        def rows(self, q, days=800):
            seen.append(q)
            if "state_value" in q:
                return [{"state_value": "abc"}]
            return [{"last_success": dt.datetime(2026, 11, 18, 1, 0)}]

    st = LogState(Reader(), ing, lambda name: {"state_value": 'state_value | source == "state:{KEY}"', "state_last_success": 'last_success | source == "{KEY}"'}[name])
    assert st.get("reference_hash") == "abc"
    assert 'state:reference_hash' in seen[0]
    assert st.last_success("inventory") == dt.datetime(2026, 11, 18, 1, 0, tzinfo=dt.UTC)
    st.set("bootstrap_done", "v")
    row = ing.tables["AzMaintenanceIngestHealth_CL"][0]
    assert row["source"] == "state:bootstrap_done" and row["state_value"] == "v" and row["status"] == "state"
    assert state_row("k", "v", NOW)["row_key"] == state_row("k", "v", NOW)["row_key"]


def test_is_due():
    assert job.is_due(None, NOW, 20)
    assert not job.is_due(NOW - dt.timedelta(hours=19), NOW, 20)
    assert job.is_due(NOW - dt.timedelta(hours=20), NOW, 20)
