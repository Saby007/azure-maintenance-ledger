"""Planning ranges (docs/method.md item 6): evidence-based P50/P90 annual downtime hours, never a guarantee.

Model: N ~ Poisson(lambda) events per simulated year, lambda = n / (W / 365); each event's duration is drawn with
replacement from the observed durations. Scope fallback is service+region, then service, then category.
"""

from __future__ import annotations

import datetime as dt
import math
import random
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from collector.ingest import row_key, stamp, utc_iso

DEFAULT_CONFIG: dict[str, Any] = {
    "window_days": 365,
    "min_window_days": 90,
    "simulations": 10000,
    "seed": None,
    "confidence": {
        "insufficient_below_n": 3,
        "insufficient_below_window_days": 90,
        "low_max_n": 5,
        "low_below_window_days": 365,
        "medium_max_n": 11,
        "high_min_n": 12,
        "high_min_window_days": 365,
    },
}


def load_config(path: Path | None = None) -> dict[str, Any]:
    cfg = {**DEFAULT_CONFIG, "confidence": dict(DEFAULT_CONFIG["confidence"])}
    if path and path.exists():
        user = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        conf = {**cfg["confidence"], **(user.pop("confidence", None) or {})}
        cfg.update(user)
        cfg["confidence"] = conf
    return cfg


@dataclass(frozen=True)
class ForecastEvent:
    """One distinct unplanned event (TrackingId)."""

    tracking_id: str
    service: str
    region: str
    category: str
    sh_minutes: float  # Service Health exposure window
    rh_minutes: float | None = None  # Resource Health downtime overlapping the event, None if not measured


@dataclass
class ScopeResult:
    scope_level: str
    scope_key: str
    window_days: int
    n_events: int
    events_per_year: float
    mean_annual_h: float | None
    p50_annual_h: float | None
    p90_annual_h: float | None
    duration_basis: str
    confidence: str
    baseline: str = "customer"
    extra: dict = field(default_factory=dict)


def confidence(n: int, window_days: int, cfg: dict[str, Any] | None = None) -> str:
    c = (cfg or DEFAULT_CONFIG)["confidence"]
    if n < c["insufficient_below_n"] or window_days < c["insufficient_below_window_days"]:
        return "insufficient"
    if n <= c["low_max_n"] or window_days < c["low_below_window_days"]:
        return "low"
    if n <= c["medium_max_n"]:
        return "medium"
    return "high"


def poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:  # normal approximation, avoids exp underflow
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def percentile(sorted_vals: Sequence[float], q: float) -> float:
    if not sorted_vals:
        return float("nan")
    idx = min(len(sorted_vals) - 1, max(0, math.ceil(q * len(sorted_vals)) - 1))
    return sorted_vals[idx]


def simulate_annual_hours(durations_min: Sequence[float], n_events: int, window_days: int, sims: int, rng: random.Random):
    lam = n_events / (window_days / 365.0)
    totals = []
    for _ in range(sims):
        k = poisson(rng, lam)
        totals.append(sum(rng.choices(durations_min, k=k)) / 60.0 if k else 0.0)
    totals.sort()
    return lam, sum(totals) / len(totals), percentile(totals, 0.5), percentile(totals, 0.9)


def _scope(level: str, key: str, evs: Sequence[ForecastEvent], window_days: int, cfg: dict[str, Any], rng: random.Random,
           baseline: str = "customer") -> ScopeResult:
    n = len({e.tracking_id for e in evs})
    use_rh = bool(evs) and all(e.rh_minutes is not None for e in evs)
    basis = "resource_health" if use_rh else "service_health"
    conf = confidence(n, window_days, cfg)
    if n == 0 or window_days <= 0:
        return ScopeResult(level, key, window_days, n, 0.0, None, None, None, basis, "insufficient", baseline)
    seen: set[str] = set()
    durs: list[float] = []
    for e in evs:  # one duration per distinct event
        if e.tracking_id in seen:
            continue
        seen.add(e.tracking_id)
        durs.append(float(e.rh_minutes if use_rh else e.sh_minutes))
    lam, mean_h, p50, p90 = simulate_annual_hours(durs, n, window_days, int(cfg["simulations"]), rng)
    return ScopeResult(level, key, window_days, n, round(lam, 3), round(mean_h, 3), round(p50, 3), round(p90, 3), basis, conf, baseline)


def compute_forecast(events: Iterable[ForecastEvent], coverage_days: int, cfg: dict[str, Any] | None = None) -> list[ScopeResult]:
    """Return one row per scope at each fallback level. Effective window = min(window_days, coverage_days)."""
    cfg = cfg or DEFAULT_CONFIG
    rng = random.Random(cfg.get("seed"))
    window = max(0, min(int(cfg["window_days"]), int(coverage_days)))
    evs = list(events)
    results: list[ScopeResult] = []
    by_sr: dict[tuple[str, str], list[ForecastEvent]] = defaultdict(list)
    by_s: dict[str, list[ForecastEvent]] = defaultdict(list)
    by_c: dict[str, list[ForecastEvent]] = defaultdict(list)
    for e in evs:
        by_sr[(e.service, e.region)].append(e)
        by_s[e.service].append(e)
        by_c[e.category].append(e)
    for (svc, reg), group in sorted(by_sr.items()):
        results.append(_scope("service_region", f"{svc}|{reg}", group, window, cfg, rng))
    for svc, group in sorted(by_s.items()):
        results.append(_scope("service", svc, group, window, cfg, rng))
    for cat, group in sorted(by_c.items()):
        results.append(_scope("category", cat, group, window, cfg, rng))
    return results


def pir_baseline(pirs: Iterable[tuple[str, str, float]], span_days: int, cfg: dict[str, Any] | None = None) -> list[ScopeResult]:
    """Azure-wide baseline from public PIRs: (tracking_id, category, duration_h). NOT the customer's estate."""
    cfg = cfg or DEFAULT_CONFIG
    rng = random.Random(cfg.get("seed"))
    by_c: dict[str, list[ForecastEvent]] = defaultdict(list)
    for tid, cat, dur_h in pirs:
        by_c[cat].append(ForecastEvent(tid, cat, "global", cat, dur_h * 60.0, dur_h * 60.0))
        by_c["(all categories)"].append(ForecastEvent(tid, cat, "global", "(all categories)", dur_h * 60.0, dur_h * 60.0))
    return [
        _scope("category", cat, group, span_days, cfg, rng, baseline="public_pir")
        for cat, group in sorted(by_c.items())
    ]


def to_rows(results: Iterable[ScopeResult], computed: dt.datetime | None = None) -> list[dict]:
    computed = computed or dt.datetime.now(dt.UTC)
    stamp_s = utc_iso(computed)
    rows = []
    for r in results:
        row = {
            "computed_utc": stamp_s,
            "scope_level": r.scope_level,
            "scope_key": r.scope_key,
            "window_days": r.window_days,
            "n_events": r.n_events,
            "events_per_year": r.events_per_year,
            "mean_annual_h": r.mean_annual_h,
            "p50_annual_h": r.p50_annual_h,
            "p90_annual_h": r.p90_annual_h,
            "duration_basis": r.duration_basis,
            "confidence": r.confidence,
            "baseline": r.baseline,
        }
        rows.append(stamp(row, row_key("forecast", r.baseline, f"{r.scope_level}|{r.scope_key}", stamp_s or ""), now=computed))
    return rows
