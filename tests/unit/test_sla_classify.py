import datetime as dt

import pytest

from analytics import sla
from analytics.availability import evaluate, observed_availability, sla_allowance_min
from analytics.classify import Annotation, PlannedWindow, classify_event, classify_interval
from analytics.intervals import Interval

T0 = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


def test_sla_vectors():
    assert sla.allowance_h_per_year(99.9) == pytest.approx(8.76, abs=1e-6)
    assert sla.allowance_h_per_year(99.95) == pytest.approx(4.38, abs=1e-6)
    assert sla.allowance_h_per_year(99.99) * 60 == pytest.approx(52.56, abs=1e-6)
    av, h = sla.composite([99.95, 99.99], "serial")
    assert av == pytest.approx(99.940005, abs=1e-9) and h == pytest.approx(5.26, abs=0.01)
    av, h = sla.composite([99.9, 99.9], "redundant")
    assert av == pytest.approx(99.9999, abs=1e-9) and h * 3600 == pytest.approx(31.5, abs=0.05)


def test_availability_and_allowance():
    assert observed_availability(0, 10, 30) == 100.0
    assert observed_availability(43.2, 1, 30) == pytest.approx(99.9)
    assert sla_allowance_min(99.9, 30) == pytest.approx(43.2)
    assert sla_allowance_min(None, 30) is None
    assert observed_availability(1, 0, 30) is None


def test_sla_status():
    assert evaluate(100, 1, 30, None).sla_status == "SLA not set"
    assert evaluate(100, 1, 30, 99.9).sla_status == "Below SLA"
    assert evaluate(1, 1, 30, 99.9).sla_status == "Within SLA"
    assert evaluate(1, 0, 30, 99.9).sla_status == "No inventory"


def test_event_classification():
    assert classify_event("ServiceIssue") == "Unplanned"
    assert classify_event("PlannedMaintenance") == "Planned"
    assert classify_event("HealthAdvisory") == "Advisory"


def iv(start_min, end_min):
    return Interval("/r/a", T0 + dt.timedelta(minutes=start_min), T0 + dt.timedelta(minutes=end_min), "Unavailable")


def test_interval_classification_precedence():
    ann = [Annotation("/r/a", T0 + dt.timedelta(minutes=1), "Planned")]
    planned = [PlannedWindow("PM1", "s1", "Virtual Machines", T0, T0 + dt.timedelta(hours=1))]
    assert classify_interval(iv(0, 10), "s1", "Virtual Machines", ann, planned) == ("Planned", "vm_annotation", None)
    assert classify_interval(iv(0, 10), "s1", "Virtual Machines", [], planned) == ("Planned", "overlaps_planned_event", "PM1")
    assert classify_interval(iv(0, 10), "s2", "Virtual Machines", [], planned) == ("Unplanned", "default", None)
    assert classify_interval(iv(200, 210), "s1", "Virtual Machines", [], planned) == ("Unplanned", "default", None)
    assert classify_interval(iv(0, 10), "s1", "Other", [], planned)[1] == "default"
