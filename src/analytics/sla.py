"""Composite SLA maths (docs/method.md item 8). The KQL twin is kql/AzOutage_CompositeSla.kql."""

from __future__ import annotations

from collections.abc import Sequence
from math import prod

HOURS_PER_YEAR = 8760.0


def serial(slas_pct: Sequence[float]) -> float:
    """Availability % of components that must ALL be up."""
    return prod(s / 100.0 for s in slas_pct) * 100.0


def redundant(slas_pct: Sequence[float]) -> float:
    """Availability % when ANY one component being up is enough."""
    return (1.0 - prod(1.0 - s / 100.0 for s in slas_pct)) * 100.0


def allowance_h_per_year(availability_pct: float) -> float:
    return (1.0 - availability_pct / 100.0) * HOURS_PER_YEAR


def composite(slas_pct: Sequence[float], mode: str = "serial") -> tuple[float, float]:
    av = redundant(slas_pct) if mode == "redundant" else serial(slas_pct)
    return av, allowance_h_per_year(av)
