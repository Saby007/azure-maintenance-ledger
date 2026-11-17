"""Resource Health interval builder (docs/method.md items 1 and 4)."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace

KNOWN_STATES = {"available": "Available", "unavailable": "Unavailable", "degraded": "Degraded"}
OPEN_STATES = ("Unavailable", "Degraded")
STALE_OPEN_AFTER = dt.timedelta(days=3)


@dataclass(frozen=True)
class HealthEvent:
    resource_id: str
    ts: dt.datetime
    state: str  # currentHealthStatus
    cause: str = ""
    event_id: str | None = None


@dataclass(frozen=True)
class Interval:
    resource_id: str
    start: dt.datetime
    end: dt.datetime
    state: str
    is_open: bool = False
    cause: str = ""

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60.0

    @property
    def user_initiated(self) -> bool:
        return self.cause.lower() == "userinitiated"


def build_intervals(events: Iterable[HealthEvent], now: dt.datetime, states: tuple[str, ...] = OPEN_STATES) -> list[Interval]:
    """Open on a change into Unavailable/Degraded, close at the next state change.

    Duplicate Active/Updated rows (same state) and Unknown states are ignored; rows are ordered by time so
    out-of-order input is handled; open intervals end at `now` and are flagged.
    """
    by_res: dict[str, list[HealthEvent]] = defaultdict(list)
    seen_ids: set[str] = set()
    for e in events:
        if e.event_id:
            if e.event_id in seen_ids:
                continue
            seen_ids.add(e.event_id)
        canon = KNOWN_STATES.get(e.state.lower()) if e.state else None
        if canon is None:  # Unknown / empty
            continue
        by_res[e.resource_id.lower()].append(replace(e, state=canon, resource_id=e.resource_id.lower()))

    out: list[Interval] = []
    for rid, evs in by_res.items():
        evs.sort(key=lambda x: x.ts)
        changes: list[HealthEvent] = []
        for e in evs:
            if not changes or changes[-1].state != e.state:
                changes.append(e)
        for i, e in enumerate(changes):
            if e.state not in states:
                continue
            if i + 1 < len(changes):
                out.append(Interval(rid, e.ts, changes[i + 1].ts, e.state, False, e.cause))
            else:
                out.append(Interval(rid, e.ts, max(now, e.ts), e.state, True, e.cause))
    return sorted(out, key=lambda x: (x.resource_id, x.start))


def merge_intervals(intervals: Iterable[Interval]) -> list[Interval]:
    """Merge overlapping or touching intervals per (resource, state) so downtime is never double counted."""
    groups: dict[tuple[str, str], list[Interval]] = defaultdict(list)
    for iv in intervals:
        groups[(iv.resource_id, iv.state)].append(iv)
    merged: list[Interval] = []
    for _key, ivs in groups.items():
        ivs.sort(key=lambda x: x.start)
        cur = ivs[0]
        for nxt in ivs[1:]:
            if nxt.start <= cur.end:
                cur = replace(cur, end=max(cur.end, nxt.end), is_open=cur.is_open or nxt.is_open,
                              cause=cur.cause if not cur.user_initiated else nxt.cause)
            else:
                merged.append(cur)
                cur = nxt
        merged.append(cur)
    return sorted(merged, key=lambda x: (x.resource_id, x.start))


def clip(iv: Interval, win_start: dt.datetime, win_end: dt.datetime) -> Interval | None:
    s, e = max(iv.start, win_start), min(iv.end, win_end)
    return replace(iv, start=s, end=e) if e > s else None


def downtime_minutes(
    intervals: Iterable[Interval],
    win_start: dt.datetime,
    win_end: dt.datetime,
    *,
    include_user_initiated: bool = False,
    state: str = "Unavailable",
    stale_open_after: dt.timedelta = STALE_OPEN_AFTER,
) -> float:
    """Total merged minutes of `state` inside the window; user-initiated excluded by default.

    Intervals still open after `stale_open_after` (no closing event: usually a deleted or deallocated resource) are excluded.
    """
    chosen = [
        iv
        for iv in intervals
        if iv.state == state
        and (include_user_initiated or not iv.user_initiated)
        and not (iv.is_open and win_end - iv.start > stale_open_after)
    ]
    total = 0.0
    for iv in merge_intervals(chosen):
        c = clip(iv, win_start, win_end)
        if c:
            total += c.minutes
    return total
