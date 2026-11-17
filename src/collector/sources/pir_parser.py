"""Parse public Azure PIR text into an incident window (UTC) and a coarse category.

Method: docs/method.md item 9. Pure functions, no network access.
"""

from __future__ import annotations

import csv
import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

MAX_WINDOW_DAYS = 14

_MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]  # fmt: skip
_MONTHS = {m: i for i, m in enumerate(_MONTH_NAMES, 1)}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})
_MONTHS["sept"] = 9

_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_DMY_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?(?:,?\s+(\d{4}))?\b")
_MDY_RE = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,\s*(\d{4}))?\b")
_SENTENCE_END_RE = re.compile(r"(?<=[A-Za-z\)])\.\s")
_START_RE = re.compile(r"\b(?:Between|From)\b", re.IGNORECASE)


@dataclass(frozen=True)
class PirWindow:
    start: dt.datetime
    end: dt.datetime
    status: str  # ok | manual | unparsed
    note: str = ""

    @property
    def duration_h(self) -> float | None:
        if self.status == "unparsed" or self.end is None or self.start is None:
            return None
        return (self.end - self.start).total_seconds() / 3600


def normalize(text: str) -> str:
    return re.sub(r"[\s\u00a0\u202f\u2009]+", " ", text or "").strip()


def _month(token: str) -> int | None:
    return _MONTHS.get(token.lower())


def _dates(segment: str) -> list[tuple[int, int, int | None]]:
    found: list[tuple[int, int, int, int | None]] = []
    for m in _DMY_RE.finditer(segment):
        mon = _month(m.group(2))
        if mon:
            found.append((m.start(), int(m.group(1)), mon, int(m.group(3)) if m.group(3) else None))
    for m in _MDY_RE.finditer(segment):
        mon = _month(m.group(1))
        if mon:
            found.append((m.start(), int(m.group(2)), mon, int(m.group(3)) if m.group(3) else None))
    found.sort()
    out: list[tuple[int, int, int | None]] = []
    seen_pos: set[int] = set()
    for pos, day, mon, year in found:
        if pos in seen_pos:
            continue
        seen_pos.add(pos)
        out.append((day, mon, year))
    return out


def parse_window(text: str, published: dt.date) -> PirWindow | None:
    """Return the first 'Between/From <time> ... <date>' window, or None if unparseable."""
    text = normalize(text)
    for m in _START_RE.finditer(text):
        segment = text[m.start() : m.start() + 420]
        parts = _SENTENCE_END_RE.split(segment, maxsplit=1)
        segment = parts[0]
        times = [(int(h), int(mi)) for h, mi in _TIME_RE.findall(segment)]
        if len(times) < 2:
            continue
        dates = _dates(segment)
        if not dates:
            continue
        default_year = next((d[2] for d in dates if d[2]), published.year)
        d1 = dates[0]
        d2 = dates[1] if len(dates) > 1 else dates[0]
        try:
            start = dt.datetime(d1[2] or default_year, d1[1], d1[0], *times[0])
            end = dt.datetime(d2[2] or default_year, d2[1], d2[0], *times[1])
        except ValueError:
            continue
        if end < start and len(dates) == 1:
            end += dt.timedelta(days=1)
        if end < start or (end - start) > dt.timedelta(days=MAX_WINDOW_DAYS):
            continue
        return PirWindow(start, end, "ok")
    return None


# Category rules are ordered: first match wins. Word boundaries avoid e.g. "Central" matching "entra".
_CATEGORY_RULES: list[tuple[str, str]] = [
    ("AI", r"\b(openai|cognitive|foundry|ai services?|speech|machine learning|ai search|copilot)\b"),
    ("Identity", r"\b(entra|active directory|sign[- ]?in|authentication|managed identit\w*|access panel|microsoft graph)\b"),
    ("Network", r"\b(network\w*|front door|expressroute|gateway|dns|vpn|load balancer|cdn|firewall|traffic manager|virtual wan)\b"),
    ("Data", r"\b(storage|sql|cosmos|data factory|databricks|synapse|postgres\w*|mysql|redis|event hubs?|service bus|managed disks?)\b"),
    ("Management", r"\b(portal|monitor|log analytics|application insights|alerts|activity log|arm|resource manager|key vault|policy|service health)\b"),
    ("PaaS", r"\b(app service|functions|kubernetes|aks|container\w*|batch|logic apps|web apps?)\b"),
    ("IaaS", r"\b(virtual machines?|vms?|compute|scale sets?|power|cooling|datacenter|availability zone)\b"),
]  # fmt: skip


def category_of(title: str) -> str:
    low = normalize(title).lower()
    for name, rx in _CATEGORY_RULES:
        if re.search(rx, low):
            return name
    return "Other"


def load_overrides(path: Path) -> dict[str, PirWindow]:
    """reference/pir_overrides.csv: tracking_id,window_start_utc,window_end_utc,note (ISO-8601, may be blank)."""
    out: dict[str, PirWindow] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(line for line in fh if not line.lstrip().startswith("#")):
            tid = (row.get("tracking_id") or "").strip()
            if not tid:
                continue
            start_s = (row.get("window_start_utc") or "").strip()
            end_s = (row.get("window_end_utc") or "").strip()
            note = (row.get("note") or "").strip()
            if start_s and end_s:
                start = dt.datetime.fromisoformat(start_s.replace("Z", ""))
                end = dt.datetime.fromisoformat(end_s.replace("Z", ""))
                out[tid] = PirWindow(start, end, "manual", note)
            else:
                out[tid] = PirWindow(None, None, "manual", note)  # type: ignore[arg-type]
    return out
