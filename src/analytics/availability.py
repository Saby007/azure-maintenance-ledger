"""Observed availability vs SLA (docs/method.md items 4-5)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Availability:
    availability_pct: float | None
    sla_allowance_min: float | None
    sla_status: str


def observed_availability(downtime_min: float, resources: int, window_days: int) -> float | None:
    if resources <= 0 or window_days <= 0:
        return None
    return (1.0 - downtime_min / (resources * window_days * 1440.0)) * 100.0


def sla_allowance_min(sla_percent: float | None, window_days: int) -> float | None:
    """Allowed downtime per resource over the window, minutes. None when no SLA is set."""
    if sla_percent is None:
        return None
    return (1.0 - sla_percent / 100.0) * window_days * 1440.0


def evaluate(downtime_min: float, resources: int, window_days: int, sla_percent: float | None) -> Availability:
    av = observed_availability(downtime_min, resources, window_days)
    allow = sla_allowance_min(sla_percent, window_days)
    if sla_percent is None:
        status = "SLA not set"
    elif av is None:
        status = "No inventory"
    else:
        status = "Within SLA" if av >= sla_percent else "Below SLA"
    return Availability(av, allow, status)
