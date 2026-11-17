"""Quarterly report: self-contained HTML (inline CSS/SVG, no CDN) and XLSX (summary sheet + one sheet per AzOutage_* function).

  python -m reporting.render_report [--days 90] [--out reports] [--workspace <customerId>]

Reads only through the AzOutage_* functions (azure-monitor-query). Methodology and caveats are on page 1.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import wbkql  # noqa: E402

REPORT_KQL = ROOT / "kql" / "report"

SUMMARY_QUERIES = {
    "tiles": "01_overview_tiles",
    "by_category": "01_overview_by_category",
    "timeline_events": "02_timeline_events",
    "timeline_downtime": "02_timeline_downtime",
    "services": "03_services",
    "regions": "04_regions",
    "planned_upcoming": "06_planned_upcoming",
    "planned_history": "06_planned_history",
    "pir_category": "07_pir_by_category",
}
SHEETS = ["Events", "EventServices", "Planned", "ResourceIntervals", "Availability", "PirBaseline", "Forecast", "DataHealth"]

CAVEATS = [
    "Event window (exposure) and downtime (minutes a resource was Unavailable per Resource Health) are different measures and are never added together.",
    "Planned maintenance windows are scheduled windows, not downtime. Notice lead time is a lower bound (first update seen in the ledger).",
    "Events are counted once per tracking ID. Per-service and per-region rows overlap and must not be summed to a total.",
    "User-initiated and VM-initiated unavailability is excluded from downtime. Intervals open for more than 3 days with no closing event are excluded (stale).",
    "Observed availability uses the latest resource inventory as denominator and is marked approximate when counts changed in the window.",
    "Planning ranges are evidence from history (sample size, window and confidence shown), not a forecast or a guarantee.",
    "Public PIRs are Azure-wide, broad-impact incidents only, not this estate.",
]


class Reader(Protocol):
    def rows(self, query: str, days: int = ...) -> list[dict]: ...


def report_query(name: str, days: int) -> str:
    text = (REPORT_KQL / f"{name}.kql").read_text(encoding="utf-8")
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("//")).replace("{WindowDays}", str(days))


def summary_query(file: str, days: int) -> str:
    return wbkql.render(file, **{"{TimeRange:start}": f"ago({days}d)"})


def collect(reader: Reader, days: int) -> dict[str, Any]:
    out: dict[str, Any] = {"summary": {}, "sheets": {}}
    for key, file in SUMMARY_QUERIES.items():
        out["summary"][key] = reader.rows(summary_query(file, days), max(days, 800))
    for sheet in SHEETS:
        out["sheets"][sheet] = reader.rows(report_query(sheet, days), 800)
    return out


# ------------------------------------------------------------------ HTML
CSS = """
body{font:14px/1.45 Segoe UI,Arial,sans-serif;margin:0;color:#1b1b1b;background:#fff}
main{max-width:1100px;margin:0 auto;padding:24px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:28px 0 8px;border-bottom:1px solid #ddd;padding-bottom:4px}
.meta{color:#555;margin-bottom:16px}.box{background:#f5f7fa;border:1px solid #d9dee5;border-radius:6px;padding:12px 16px;margin:12px 0}
.tiles{display:flex;flex-wrap:wrap;gap:10px}.tile{background:#f5f7fa;border:1px solid #d9dee5;border-left:5px solid #2f6db5;border-radius:6px;padding:10px 14px;min-width:210px}
.tile.good{border-left-color:#3a9d4a}.tile.warn{border-left-color:#e0a030}.tile.bad{border-left-color:#c8372d}.tile small{display:block;color:#666;font-size:12px}
.tile b{display:block;font-size:22px}table{border-collapse:collapse;width:100%;margin:8px 0;font-size:13px}
th,td{border:1px solid #d9dee5;padding:4px 8px;text-align:left;vertical-align:top}th{background:#eef1f5}
.empty{color:#777;font-style:italic}.num{text-align:right}.pagebreak{page-break-before:always}
@media print{main{max-width:none}}
"""


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, list | dict):
        return html.escape(json.dumps(v, default=str))
    return html.escape(str(v))


def table(rows: list[dict], empty: str, limit: int = 50, cols: list[str] | None = None) -> str:
    if not rows:
        return f'<p class="empty">{html.escape(empty)}</p>'
    cols = cols or list(rows[0].keys())
    head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    body = "".join(
        "<tr>" + "".join(f'<td class="{"num" if isinstance(r.get(c), int | float) else ""}">{_fmt(r.get(c))}</td>' for c in cols) + "</tr>"
        for r in rows[:limit]
    )
    more = f'<p class="empty">Showing {limit} of {len(rows)} rows; the XLSX has the full data.</p>' if len(rows) > limit else ""
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>{more}"


def svg_bars(rows: list[dict], x: str, y: str, group: str | None, title: str, empty: str) -> str:
    """Stacked bar chart in inline SVG. rows: {x, y, group?}."""
    if not rows:
        return f'<p class="empty">{html.escape(empty)}</p>'
    xs = sorted({str(r[x])[:7] for r in rows})
    groups = sorted({str(r.get(group, "")) for r in rows}) if group else [""]
    palette = ["#2f6db5", "#e07b39", "#6a9f58", "#8e6bb0"]
    data = {(str(r[x])[:7], str(r.get(group, "")) if group else ""): float(r[y] or 0) for r in rows}
    totals = {k: sum(data.get((k, g), 0.0) for g in groups) for k in xs}
    top = max(totals.values()) or 1.0
    w, h, pad = 720, 220, 36
    bw = max(8, (w - 2 * pad) // max(len(xs), 1) - 6)
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{html.escape(title)}" xmlns="http://www.w3.org/2000/svg">']
    for i, k in enumerate(xs):
        cx = pad + i * (bw + 6)
        yb = h - 28
        for gi, g in enumerate(groups):
            v = data.get((k, g), 0.0)
            bh = (h - 60) * v / top
            yb -= bh
            parts.append(f'<rect x="{cx}" y="{yb:.1f}" width="{bw}" height="{bh:.1f}" fill="{palette[gi % 4]}"><title>{html.escape(k)} {html.escape(g)}: {v:g}</title></rect>')
        parts.append(f'<text x="{cx + bw / 2}" y="{h - 12}" font-size="10" text-anchor="middle">{html.escape(k)}</text>')
    legend = "".join(
        f'<text x="{pad + gi * 120}" y="14" font-size="11" fill="{palette[gi % 4]}">&#9632; {html.escape(g or y)}</text>' for gi, g in enumerate(groups)
    )
    parts.append(legend + "</svg>")
    return "".join(parts)


def fmt_tile_value(v: Any) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, int | float):
        return f"{v:,.3f}".rstrip("0").rstrip(".")
    return str(v)


def pivot_category(rows: list[dict]) -> list[dict]:
    """category/class/events rows -> one row per category with Planned and Unplanned columns."""
    out: dict[str, dict] = {}
    for r in rows:
        d = out.setdefault(str(r["category"]), {"category": r["category"], "Planned": 0, "Unplanned": 0})
        d[str(r["class"])] = int(r["events"] or 0)
    return sorted(out.values(), key=lambda x: str(x["category"]))


def render_html(data: dict[str, Any], days: int, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.UTC)
    s = data["summary"]
    tiles = "".join(
        f'<div class="tile {html.escape(str(r.get("status") or "info"))}">{html.escape(str(r["metric"]))}'
        f'<b>{html.escape(fmt_tile_value(r["value"]))}</b><small>{html.escape(str(r.get("subtitle") or ""))}</small></div>'
        for r in s["tiles"]
    )
    health = data["sheets"]["DataHealth"]
    stale = [h for h in health if h.get("status") in ("STALE", "WARN")]
    caveats = "".join(f"<li>{html.escape(c)}</li>" for c in CAVEATS)
    forecast = [r for r in data["sheets"]["Forecast"] if r.get("baseline") == "customer"]
    pir_forecast = [r for r in data["sheets"]["Forecast"] if r.get("baseline") == "public_pir"]
    fc_cols = ["scope_level", "scope_key", "n_events", "window_days", "confidence", "events_per_year", "p50_annual_h", "p90_annual_h", "duration_basis"]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Azure Outage Ledger - report</title>
<style>{CSS}</style></head><body><main>
<h1>Azure Outage Ledger</h1>
<div class="meta">Window: last {days} days &middot; generated {now:%Y-%m-%d %H:%M} UTC &middot; every figure is derived from the ledger; nothing here is a guarantee.</div>
<div class="box"><b>Methodology and caveats</b><ul>{caveats}</ul>
<p>Data health: {"<b>attention needed</b> - " + html.escape("; ".join(f"{h['item']}: {h['status']}" for h in stale)) if stale else "all sources reporting"}.</p></div>
<h2>Overview</h2><div class="tiles">{tiles or '<p class="empty">No data yet.</p>'}</div>
<h2>Events by category</h2>{table(pivot_category(s["by_category"]), "No events in the window.")}
<h2>Timeline</h2>
{svg_bars(s["timeline_events"], "month", "events", "class", "Events by month", "No events in the window.")}
{svg_bars(s["timeline_downtime"], "month", "downtime_min", "class", "Downtime minutes by month", "No Resource Health downtime in the window.")}
<h2 class="pagebreak">Services</h2>{table(s["services"], "No service data.", 60)}
<h2>Regions</h2>{table(s["regions"], "No regional data.", 40)}
<h2>Planned maintenance</h2><p>Scheduled windows, not downtime.</p>
{table(s["planned_upcoming"], "No upcoming planned maintenance.", 20)}{table(s["planned_history"], "No planned maintenance in the window.", 30)}
<h2 class="pagebreak">Expected downtime (planning ranges)</h2>
<p>Evidence from history: P50/P90 hours per year, with sample size (n), window and confidence. Not a forecast or guarantee.</p>
{table(forecast, "No planning ranges yet.", 50, fc_cols)}
<h3>Azure-wide PIR baseline (not your estate)</h3>{table(pir_forecast, "No PIR baseline.", 20, fc_cols)}
<h2>Public PIR benchmark (Azure-wide)</h2>{table(s["pir_category"], "No public PIRs loaded.")}
<h2>Data health</h2>{table(health, "No ingest runs recorded.", 40)}
</main></body></html>"""


# ------------------------------------------------------------------ XLSX
def _cell(v: Any) -> Any:
    if isinstance(v, dt.datetime):
        return v.replace(tzinfo=None) if v.tzinfo else v
    if isinstance(v, list | dict):
        return json.dumps(v, default=str)
    return v


def write_xlsx(data: dict[str, Any], path: Path, days: int) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Azure Outage Ledger", f"window: last {days} days", f"generated {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M} UTC"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])
    for r in data["summary"]["tiles"]:
        ws.append([str(r["metric"]), r["value"], str(r.get("subtitle") or "")])
    ws.append([])
    ws.append(["Caveats"])
    ws.cell(ws.max_row, 1).font = Font(bold=True)
    for c in CAVEATS:
        ws.append([c])
    ws.column_dimensions["A"].width = 60
    for sheet in SHEETS:
        rows = data["sheets"][sheet]
        w = wb.create_sheet(sheet)
        if not rows:
            w.append(["(no rows)"])
            continue
        cols = list(rows[0].keys())
        w.append(cols)
        for c in w[1]:
            c.font = Font(bold=True)
        for r in rows:
            w.append([_cell(r.get(c)) for c in cols])
        w.freeze_panes = "A2"
    wb.save(path)


def generate(reader: Reader, days: int, out_dir: Path, now: dt.datetime | None = None, stem: str | None = None) -> tuple[Path, Path]:
    now = now or dt.datetime.now(dt.UTC)
    out_dir.mkdir(parents=True, exist_ok=True)
    data = collect(reader, days)
    stem = stem or f"azure-outage-ledger-{now:%Y%m%d}"
    html_path, xlsx_path = out_dir / f"{stem}.html", out_dir / f"{stem}.xlsx"
    html_path.write_text(render_html(data, days, now), encoding="utf-8")
    write_xlsx(data, xlsx_path, days)
    return html_path, xlsx_path


def main(argv: list[str] | None = None, reader_factory: Callable[[str], Reader] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--out", type=Path, default=ROOT / "reports")
    ap.add_argument("--workspace")
    a = ap.parse_args(argv)
    from collector.backfill import load_env

    load_env(ROOT / ".env")
    ws = a.workspace or os.environ["AOL_WORKSPACE_ID"]
    if reader_factory is None:
        from collector.forecast_job import LogsReader

        reader_factory = LogsReader
    h, x = generate(reader_factory(ws), a.days, a.out)
    print(f"wrote {h}\nwrote {x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
