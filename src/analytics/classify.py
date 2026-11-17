"""Planned / unplanned classification (docs/method.md item 2)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass

from .intervals import Interval

ANNOTATION_WINDOW = dt.timedelta(minutes=15)


def classify_event(event_type: str | None) -> str:
    t = (event_type or "").lower()
    if t == "serviceissue":
        return "Unplanned"
    if t == "plannedmaintenance":
        return "Planned"
    return "Advisory"


@dataclass(frozen=True)
class Annotation:
    resource_id: str
    occurred: dt.datetime
    category: str  # Planned | Unplanned | Not Applicable | Null
    context: str = ""  # Platform-Initiated | User-initiated | VM-initiated


@dataclass(frozen=True)
class PlannedWindow:
    tracking_id: str
    subscription_id: str
    service: str
    start: dt.datetime
    end: dt.datetime
    regions: tuple[str, ...] = ()


def classify_interval(
    iv: Interval,
    subscription_id: str,
    service: str | None,
    annotations: Iterable[Annotation] = (),
    planned: Iterable[PlannedWindow] = (),
    region: str | None = None,
) -> tuple[str, str, str | None]:
    """Return (class, classification_basis, planned_tracking_id)."""
    for a in annotations:
        if a.resource_id.lower() == iv.resource_id.lower() and abs(a.occurred - iv.start) <= ANNOTATION_WINDOW:
            if a.category in ("Planned", "Unplanned"):
                return a.category, "vm_annotation", None
    for p in planned:
        if p.subscription_id != subscription_id or service is None or p.service.lower() != service.lower():
            continue
        if region and p.regions and region.lower() not in [r.lower() for r in p.regions]:
            continue
        if iv.start < p.end and iv.end > p.start:
            return "Planned", "overlaps_planned_event", p.tracking_id
    return "Unplanned", "default", None


def vm_initiated(annotations: Iterable[Annotation], iv: Interval) -> bool:
    return any(
        a.resource_id.lower() == iv.resource_id.lower()
        and abs(a.occurred - iv.start) <= ANNOTATION_WINDOW
        and a.context.lower() in ("user-initiated", "vm-initiated")
        for a in annotations
    )
