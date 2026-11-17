"""The function app registers every timer with a UTC schedule, and each is gated/wired as documented."""

import importlib
import os

import pytest


@pytest.fixture()
def app_module(monkeypatch):
    monkeypatch.setenv("AOL_DCR_ENDPOINT", "https://example.invalid")
    monkeypatch.setenv("AOL_DCR_IMMUTABLE_ID", "dcr-test")
    return importlib.import_module("collector.function_app")


def test_timer_schedules(app_module):
    funcs = {f.get_function_name(): f for f in app_module.app.get_functions()}
    sched = {}
    for name, f in funcs.items():
        trig = f.get_trigger()
        sched[name] = trig.schedule
    assert sched == {
        "service_health_daily": "0 15 2 * * *",  # 02:15 UTC
        "inventory_daily": "0 45 2 * * *",  # 02:45 UTC
        "forecast_daily": "0 15 3 * * *",  # 03:15 UTC
        "bootstrap_once": "0 0 4 * * *",  # safety-net retry; also runs at start-up
        "vm_annotations_6h": "0 0 */6 * * *",  # every 6 h
        "public_pirs_monthly": "0 0 3 2 * *",  # day 2, 03:00 UTC
    }


def test_flags_disable_modules(app_module, monkeypatch):
    monkeypatch.setenv("AOL_ENABLE_VM_ANNOTATIONS", "false")
    monkeypatch.setenv("AOL_ENABLE_PIRS", "false")
    # Gated functions must return before touching Azure (no credentials in tests).
    app_module.vm_annotations_6h.build().get_user_function()(None)
    app_module.public_pirs_monthly.build().get_user_function()(None)
    assert os.environ["AOL_ENABLE_PIRS"] == "false"
