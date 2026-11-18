"""Generates workbook/workbook.template.json (diffable) from kql/workbook/*.kql and docs/method.md.

  python tools/build_workbook.py [--check]

--check exits non-zero if the committed template differs from what would be generated. The deployed workbook is
Microsoft.Insights/workbooks (infra/modules/workbook.bicep); the literal __WORKSPACE_ID__ is replaced at deploy time.

Visual conventions: orange = unplanned, blue = planned; green tick = fine, amber warning = look at it, red = act, blue info = for your information.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wbkql  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "workbook" / "workbook.template.json"
OUT_DEPLOY = ROOT / "workbook" / "workbook.deploy.json"
WS = "__WORKSPACE_ID__"
LA = "microsoft.operationalinsights/workspaces"
NS = uuid.UUID("5d0f4ad0-3a56-4d56-9d3a-aa0c0a0d0e01")

# Grid / tile formatter ids used by the Workbooks renderer
F_NUMBER, F_TEXT, F_HEATMAP, F_BAR, F_DATE, F_BIGNUM, F_THRESHOLDS = 2, 1, 3, 4, 6, 12, 18

COLOR_UNPLANNED, COLOR_PLANNED = "orange", "blue"
CLASS_COLORS = {"Unplanned": COLOR_UNPLANNED, "Planned": COLOR_PLANNED}


def uid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


# ---------------------------------------------------------------- parameters
def p_dropdown_query(name: str, label: str, qfile: str, *, multi: bool = True, default=None) -> dict:
    p = {
        "id": uid("param", name),
        "version": "KqlParameterItem/1.0",
        "name": name,
        "label": label,
        "type": 2,
        "isRequired": True,
        "query": wbkql.load(qfile),
        "queryType": 0,
        "resourceType": LA,
        "crossComponentResources": [WS],
        "typeSettings": {"additionalResourceOptions": ["value::all"] if multi else [], "showDefault": False},
        "timeContext": {"durationMs": 86400000},
    }
    if multi:
        p.update({"multiSelect": True, "quote": "'", "delimiter": ",", "selectAllValue": "*", "value": ["value::all"]})
    elif default is not None:
        p["value"] = default
    return p


def p_static(name: str, label: str, options: list[tuple[str, str]], default: str, *, hidden: bool = False, local: bool = False) -> dict:
    p = {
        "id": uid("param", name),
        "version": "KqlParameterItem/1.0",
        "name": name,
        "label": label,
        "type": 2,
        "isRequired": True,
        "typeSettings": {"additionalResourceOptions": [], "showDefault": False},
        "jsonData": json.dumps([{"value": v, "label": lbl, "selected": v == default} for v, lbl in options]),
        "value": default,
        "timeContext": {"durationMs": 86400000},
    }
    if hidden:
        p["isHiddenWhenLocked"] = True
    if not local:
        p["isGlobal"] = True
    return p


def p_text(name: str, label: str, default: str, *, hidden: bool = False, local: bool = False) -> dict:
    p = {"id": uid("param", name), "version": "KqlParameterItem/1.0", "name": name, "label": label, "type": 1,
         "isRequired": True, "value": default, "timeContext": {"durationMs": 86400000}}
    if hidden:
        p["isHiddenWhenLocked"] = True
    if not local:
        p["isGlobal"] = True
    return p


def param_item(name: str, params: list[dict]) -> dict:
    return {
        "type": 9,
        "content": {
            "version": "KqlParameterItem/1.0",
            "crossComponentResources": [WS],
            "parameters": params,
            "style": "pills",
            "queryType": 0,
            "resourceType": LA,
        },
        "name": name,
    }


def global_params() -> dict:
    day = 86400000
    time_range = {
        "id": uid("param", "TimeRange"),
        "version": "KqlParameterItem/1.0",
        "name": "TimeRange",
        "label": "Time range",
        "type": 4,
        "isRequired": True,
        "isGlobal": True,
        "value": {"durationMs": 365 * day},
        "typeSettings": {
            "selectableValues": [{"durationMs": d * day} for d in (90, 180, 365, 730)],
            "allowCustom": True,
        },
        "timeContext": {"durationMs": day},
    }
    params = [
        p_static("IncludeSynthetic", "Include synthetic test rows", [("false", "No"), ("true", "Yes (diagnostics only)")], "false", hidden=True),
        p_text("tab", "tab", "overview", hidden=True),
        time_range,
        p_dropdown_query("Subscriptions", "Subscriptions", "p_subscriptions"),
        p_dropdown_query("Category", "Category", "p_category"),
        p_dropdown_query("Service", "Service", "p_service"),
        p_dropdown_query("Region", "Region", "p_region"),
        p_static("IncludeUserInitiated", "Include user-initiated downtime", [("false", "No (default)"), ("true", "Yes")], "false"),
    ]
    for p in params:
        p.setdefault("isGlobal", True)
    return param_item("parameters-global", params)


# ---------------------------------------------------------------- generic items
def text(name: str, markdown: str, style: str | None = None) -> dict:
    content: dict = {"json": markdown}
    if style:
        content["style"] = style
    return {"type": 1, "content": content, "name": name}


def describe(name: str, shows: str, read: list[str]) -> dict:
    """Plain-language box at the top of a tab: what the page is for and how to read it."""
    body = f"**What this page shows**\n\n{shows}\n\n**How to read it**\n\n" + "\n".join(f"- {r}" for r in read)
    return text(name, body, style="info")


def section(name: str, markdown: str) -> dict:
    return text(name, markdown)


def query(name: str, title: str, qfile: str, viz: str = "table", empty: str = "No data for the current filters.", **extra) -> dict:
    content = {
        "version": "KqlItem/1.0",
        "query": wbkql.load(qfile),
        "size": extra.pop("size", 1),
        "title": title,
        "noDataMessage": empty,
        "noDataMessageStyle": 4,
        "timeContext": {"durationMs": 86400000},
        "queryType": 0,
        "resourceType": LA,
        "crossComponentResources": [WS],
        "visualization": viz,
    }
    content.update(extra)
    return {"type": 3, "content": content, "name": name}


def group(name: str, title: str, items: list[dict], visible_when: str | None = None) -> dict:
    g = {"type": 12, "content": {"version": "NotebookGroup/1.0", "groupType": "editable", "title": title, "items": items,
                                 "expandable": False}, "name": name}
    if visible_when:
        g["conditionalVisibility"] = {"parameterName": "tab", "comparison": "isEqualTo", "value": visible_when}
    return g


def tabs(pages: list[tuple[str, str]]) -> dict:
    links = [
        {"id": uid("tab", pid), "cellValue": "tab", "linkTarget": "parameter", "linkLabel": label, "subTarget": pid, "style": "link"}
        for pid, label in pages
    ]
    return {"type": 11, "content": {"version": "LinkItem/1.0", "style": "tabs", "links": links}, "name": "tabs"}


# ---------------------------------------------------------------- formatters
def thr(col: str, rules: list[tuple[str, str | None, str]], mode: str = "icons", label_text: str = "{0}{1}") -> dict:
    grid = [{"operator": op, "thresholdValue": val, "representation": rep, "text": label_text} for op, val, rep in rules]
    return {"columnMatch": col, "formatter": F_THRESHOLDS, "formatOptions": {"thresholdsOptions": mode, "thresholdsGrid": grid}}


STATUS_ICONS = [("==", "good", "success"), ("==", "warn", "warning"), ("==", "bad", "critical"), ("Default", None, "info")]


def bar(col: str, palette: str = "blue", digits: int = 1) -> dict:
    return {"columnMatch": col, "formatter": F_BAR, "formatOptions": {"min": 0, "palette": palette},
            "numberFormat": {"unit": 17, "options": {"style": "decimal", "maximumFractionDigits": digits, "useGrouping": True}}}


def heat(col: str, palette: str = "blue", digits: int = 1) -> dict:
    return {"columnMatch": col, "formatter": F_HEATMAP, "formatOptions": {"min": 0, "palette": palette},
            "numberFormat": {"unit": 17, "options": {"style": "decimal", "maximumFractionDigits": digits, "useGrouping": True}}}


def num(col: str, digits: int = 1, empty: str | None = None) -> dict:
    nf: dict = {"unit": 17, "options": {"style": "decimal", "maximumFractionDigits": digits, "useGrouping": True}}
    if empty:
        nf["emptyValCustomText"] = empty
    return {"columnMatch": col, "formatter": F_NUMBER, "numberFormat": nf}


def when(col: str) -> dict:
    return {"columnMatch": col, "formatter": F_DATE, "dateFormat": {"showUtcTime": True, "formatName": "shortDateTimeNoMsPattern"}}


def class_colors(col: str = "class") -> dict:
    return thr(col, [("==", "Unplanned", COLOR_UNPLANNED), ("==", "Planned", COLOR_PLANNED), ("Default", None, "gray")], mode="colors")


def grid(name: str, title: str, qfile: str, formatters: list[dict], labels: dict[str, str] | None = None,
         empty: str = "No data for the current filters.", filterable: bool = True, **extra) -> dict:
    gs: dict = {"formatters": formatters, "filter": filterable}
    if labels:
        gs["labelSettings"] = [{"columnId": k, "label": v} for k, v in labels.items()]
    return query(name, title, qfile, "table", empty, size=3, gridSettings=gs, showExportToExcel=True, **extra)


def kpi_tiles(name: str, title: str, qfile: str, empty: str) -> dict:
    ts = {
        "titleContent": {"columnMatch": "metric", "formatter": F_TEXT},
        "leftContent": {"columnMatch": "value", "formatter": F_BIGNUM, "formatOptions": {"palette": "none"},
                        "numberFormat": {"unit": 17, "options": {"maximumFractionDigits": 3, "useGrouping": True}}},
        "secondaryContent": {"columnMatch": "subtitle", "formatter": F_TEXT},
        "rightContent": thr("status", STATUS_ICONS, label_text=""),
        "showBorder": True,
        "size": "auto",
    }
    return query(name, title, qfile, "tiles", empty, size=3, tileSettings=ts)


def chart(name: str, title: str, qfile: str, viz: str, x: str, y: list[str], *, group_by: str | None = None,
          colors: dict[str, str] | None = None, labels: dict[str, str] | None = None, empty: str = "No data for the current filters.",
          width: str | None = None, **extra) -> dict:
    cs: dict = {"xAxis": x, "yAxis": y, "showLegend": True}
    if group_by:
        cs["group"] = group_by
        cs["createOtherGroup"] = None
    series = []
    for k, c in (colors or {}).items():
        s = {"seriesName": k, "label": (labels or {}).get(k, k), "color": c}
        series.append(s)
    if series:
        cs["seriesLabelSettings"] = series
    if width:
        extra["customWidth"] = width
    return query(name, title, qfile, viz, empty, size=1, chartSettings=cs, **extra)


def donut(name: str, title: str, qfile: str, colors: dict[str, str], empty: str, width: str | None = None) -> dict:
    cs = {"seriesLabelSettings": [{"seriesName": k, "label": k, "color": c} for k, c in colors.items()]}
    extra = {"customWidth": width} if width else {}
    return query(name, title, qfile, "piechart", empty, size=1, chartSettings=cs, **extra)


def build() -> dict:
    method_md = (ROOT / "docs" / "method.md").read_text(encoding="utf-8").replace("# Method\n", "", 1).strip()
    pages: list[tuple[str, str]] = [
        ("overview", "🏠 Overview"), ("timeline", "📈 Timeline"), ("services", "🧩 Services"), ("regions", "🌍 Regions"),
        ("resources", "🖥️ Resources"), ("planned", "🛠️ Planned maintenance"), ("pir", "📰 Public PIR benchmark"),
        ("planner", "🔮 Expected downtime"), ("health", "❤️ Data health"), ("method", "ℹ️ About, method and caveats"),
    ]
    items: list[dict] = [
        text("header", "# 🛰️ Azure Maintenance Ledger\n"
                       "*Planned and unplanned maintenance of your Azure services, kept as a durable history.* "
                       "**Exposure** (how long an event was open) and **downtime** (minutes a resource was Unavailable) are different measures and are never added together.\n\n"
                       "Orange = unplanned, blue = planned. Pick a time range and filters, then choose a tab."),
        global_params(),
        tabs(pages),
    ]

    # ------------------------------------------------------------ Overview
    items.append(group("page-overview", "Overview", [
        describe("ov-desc",
                 "A quick summary of the problems and maintenance Azure has reported for your subscriptions in the selected time range, "
                 "and how much your resources were actually unavailable.",
                 ["Start with **What needs your attention**: a short checklist. Green tick = fine, amber warning = take a look, red = act, blue info = for your information.",
                  "**Unplanned events** are Azure incidents that nobody scheduled. **Planned maintenance** is work Azure announced in advance.",
                  "**Event time open** (exposure) is how long events were officially open. It is *not* how long your resources were down.",
                  "**Observed downtime** is the number of minutes your resources were reported *Unavailable*. Time you caused yourself (for example stopping a VM) is left out.",
                  "**Observed availability** is the share of time your resources were up, from that downtime and the number of resources you have.",
                  "Each event is counted once, even if it affected several services or regions. Use the filters at the top to narrow the view."]),
        grid("ov-attention", "✅ What needs your attention right now", "01_attention",
             [thr("status", STATUS_ICONS, label_text=""), {"columnMatch": "message", "formatter": F_TEXT}, {"columnMatch": "detail", "formatter": F_TEXT}],
             labels={"status": " ", "message": "Status", "detail": "What to do"}, filterable=False,
             empty="No status information yet. See the Data health tab."),
        kpi_tiles("ov-tiles", "📊 At a glance", "01_overview_tiles", "No events in the ledger yet. See the Data health tab."),
        donut("ov-split", "Planned vs unplanned events", "01_overview_split", CLASS_COLORS, "No events for the current filters.", width="35"),
        chart("ov-category", "Events by category", "01_overview_by_category", "barchart", "category", ["events"], group_by="class",
              colors=CLASS_COLORS, empty="No events for the current filters.", width="65"),
        chart("ov-services", "Top 10 services by number of events", "01_overview_top_services", "barchart", "service", ["events"], group_by="class",
              colors=CLASS_COLORS, empty="No events for the current filters."),
    ], "overview"))

    # ------------------------------------------------------------ Timeline
    items.append(group("page-timeline", "Timeline", [
        describe("tl-desc",
                 "How things changed month by month, so you can spot busy periods and trends, plus the longest events.",
                 ["The **first chart** counts events per month, orange for unplanned and blue for planned.",
                  "The **second chart** shows the minutes your resources were actually unavailable each month.",
                  "The two charts measure different things: a month can have many events and little or no downtime for your resources.",
                  "The **table** lists the longest events. The bar shows how long the event was open (exposure), which is not downtime."]),
        chart("tl-events", "📅 Events per month", "02_timeline_events", "columnchart", "month", ["events"], group_by="class",
              colors=CLASS_COLORS, empty="No events in the selected range."),
        chart("tl-downtime", "⏱️ Minutes your resources were unavailable, per month", "02_timeline_downtime", "columnchart", "month", ["downtime_min"],
              group_by="class", colors=CLASS_COLORS,
              empty="🎉 No Resource Health downtime recorded in the selected range."),
        grid("tl-longest", "🐢 Longest events in the range", "02_timeline_longest",
             [thr("status", [("==", "Open", "warning"), ("==", "Resolved", "success"), ("Default", None, "info")]),
              class_colors("class"), bar("exposure_h", "orange"), when("started")],
             labels={"status": "Status", "class": "Type", "event_title": "Event", "services": "Services", "started": "Started (UTC)",
                     "exposure_h": "Open for (hours)"},
             empty="No events in the selected range."),
    ], "timeline"))

    # ------------------------------------------------------------ Services
    items.append(group("page-services", "Services (IaaS / PaaS / Network / Data / Identity / AI)", [
        describe("sv-desc",
                 "Each Azure service you use, grouped by type, with how often it had problems and how available it was.",
                 ["**IaaS** = infrastructure you manage (virtual machines, disks). **PaaS** = managed services (App Service, containers). The other groups are Network, Data, Identity and AI.",
                  "**Events** = number of incidents and maintenance notices. **Typical / long event** = how long events lasted: half were shorter than *typical*, 9 in 10 were shorter than *long*.",
                  "**Downtime** = minutes your resources of that service were unavailable. **Availability** is coloured green (99.9% or better), yellow (99% or better) or red.",
                  "**SLA not set** means no SLA percentage has been entered for that service yet. SLA values are never guessed; they come from `reference/service_catalog.csv` with a source."]),
        chart("sv-downtime", "⏱️ Services with the most unavailable minutes", "03_services_downtime", "barchart", "service_name", ["downtime_min"],
              colors={"downtime_min": "redBright"}, labels={"downtime_min": "Unavailable minutes"},
              empty="🎉 No downtime recorded for these services in the selected range."),
        grid("sv-table", "🧩 Service scorecard", "03_services",
             [bar("events", "blue", 0), bar("unplanned", "orange", 0), bar("planned", "blue", 0), num("exposure_p50_h"), num("exposure_p90_h"),
              bar("downtime_min", "redBright"),
              thr("availability_pct", [(">=", "99.9", "green"), (">=", "99", "yellow"), ("Default", None, "redBright")], mode="colors"),
              thr("sla_status", [("==", "Within SLA", "success"), ("==", "Below SLA", "critical"), ("Default", None, "Disable")])],
             labels={"category": "Type", "service": "Service", "events": "Events", "unplanned": "Unplanned", "planned": "Planned",
                     "exposure_p50_h": "Typical event (h)", "exposure_p90_h": "Long event (h)", "resources": "Resources",
                     "downtime_min": "Downtime (min)", "availability_pct": "Availability (%)", "sla_percent": "SLA (%)",
                     "sla_status": "SLA check", "approximate": "Approximate"},
             empty="No service data for the current filters."),
    ], "services"))

    # ------------------------------------------------------------ Regions
    items.append(group("page-regions", "Regions", [
        describe("rg-desc",
                 "Which Azure regions were affected by events in the selected range.",
                 ["Darker or larger bubbles on the map mean more events in that region.",
                  "One event can affect several regions, so the same event appears on several rows. **Do not add the rows up to get a total**; use the Overview page for totals.",
                  "Use this to see whether problems cluster in the regions you rely on."]),
        query("rg-map", "🗺️ Events by region", "04_regions", "map", "No regional data for the current filters.", size=1, customWidth="50",
              mapSettings={"locInfo": "AzureLoc", "locInfoColumn": "region", "sizeSettings": "events", "sizeAggregation": "Sum",
                           "legendMetric": "events", "legendAggregation": "Sum", "itemColorSettings": {"nodeColorField": "events",
                           "colorAggregation": "Sum", "type": "heatmap", "heatmapPalette": "greenRed"}}),
        chart("rg-bar", "Top regions by number of events", "04_regions_top", "barchart", "region", ["unplanned", "planned"],
              colors={"unplanned": COLOR_UNPLANNED, "planned": COLOR_PLANNED}, labels={"unplanned": "Unplanned", "planned": "Planned"},
              empty="No regional data for the current filters.", width="50"),
        grid("rg-table", "🌍 All regions", "04_regions",
             [bar("events", "blue", 0), bar("unplanned", "orange", 0), bar("planned", "blue", 0), num("exposure_p50_h"), num("exposure_p90_h")],
             labels={"region": "Region", "events": "Events", "unplanned": "Unplanned", "planned": "Planned",
                     "exposure_p50_h": "Typical event (h)", "exposure_p90_h": "Long event (h)"},
             empty="No regional data for the current filters."),
    ], "regions"))

    # ------------------------------------------------------------ Resources
    items.append(group("page-resources", "Resources", [
        describe("rs-desc",
                 "A closer look at individual resources: which ones were unavailable and when.",
                 ["The **chart** lists the resources with the most unavailable minutes.",
                  "The **table** lists every period a resource was *Unavailable* or *Degraded*, with start, end, length, whether it was planned or unplanned, and whether it is still ongoing.",
                  "Periods you caused yourself (for example stopping a VM) are hidden unless you switch on *Include user-initiated downtime* at the top.",
                  "A period that has stayed open for more than 3 days with no recovery signal is marked **Stale** and is not counted (this is usually a resource that was deleted or scaled in)."]),
        chart("rs-top", "🔥 Resources with the most unavailable minutes", "05_resources_top", "barchart", "resource", ["downtime_min"],
              colors={"downtime_min": "redBright"}, labels={"downtime_min": "Unavailable minutes"},
              empty="🎉 No Resource Health downtime recorded in the selected range."),
        grid("rs-intervals", "🧾 Downtime periods", "05_resources_intervals",
             [thr("status", [("==", "Ongoing", "critical"), ("==", "Recovered", "success"), ("Default", None, "Disable")]),
              thr("state", [("==", "Unavailable", "redBright"), ("==", "Degraded", "orange"), ("Default", None, "gray")], mode="colors"),
              class_colors("class"), when("start_utc"), when("end_utc"), bar("minutes", "redBright")],
             labels={"status": "Status", "resource": "Resource", "service_name": "Service", "state": "Health state", "class": "Type",
                     "start_utc": "Started (UTC)", "end_utc": "Ended (UTC)", "minutes": "Minutes", "cause": "Cause",
                     "classification_basis": "Why this type"},
             empty="No downtime periods in the selected range."),
    ], "resources"))

    # ------------------------------------------------------------ Planned maintenance
    items.append(group("page-planned", "Planned maintenance", [
        describe("pl-desc",
                 "Maintenance that Azure announced in advance, what is coming up, and what has already happened.",
                 ["**Upcoming** lists maintenance that has not started yet. The *days until* colour shows urgency: red within 3 days, orange within 7 days, blue later.",
                  "**History** lists maintenance in the selected time range. **Scheduled hours** is the planned window. It is *not* downtime; most of the time nothing is noticed.",
                  "**Notice (days)** is how far ahead the notice was first seen by this ledger. It can be shorter than the real notice if collection started late, and is blank if the ledger first saw the notice after the work had started.",
                  "**Realised downtime** is the minutes your resources were actually unavailable during the window, or *not measured* when there is no data.",
                  "The last table lists planned VM maintenance and whether a reboot was mentioned."]),
        kpi_tiles("pl-tiles", "📊 Maintenance at a glance", "06_planned_tiles", "No planned maintenance in the ledger yet."),
        chart("pl-timeline", "📅 Maintenance notices per month", "06_planned_timeline", "columnchart", "month", ["notices"],
              colors={"notices": COLOR_PLANNED}, labels={"notices": "Notices"}, empty="No planned maintenance in the selected range."),
        grid("pl-upcoming", "⏭️ Upcoming maintenance", "06_planned_upcoming",
             [thr("days_until", [("<=", "3", "redBright"), ("<=", "7", "orange"), ("Default", None, "blue")], mode="colors"),
              when("window_start_utc"), when("window_end_utc"), num("scheduled_h")],
             labels={"days_until": "Starts in (days)", "event_title": "Maintenance", "services": "Services", "regions": "Regions",
                     "window_start_utc": "Window start (UTC)", "window_end_utc": "Window end (UTC)", "scheduled_h": "Scheduled (h)"},
             empty="✅ No upcoming planned maintenance."),
        grid("pl-history", "⏮️ Maintenance history", "06_planned_history",
             [when("window_start_utc"), bar("scheduled_h", "blue"), heat("lead_time_days", "greenRed"),
              num("realised_downtime_min", 1, empty="not measured"), num("affected_resources", 0)],
             labels={"event_title": "Maintenance", "services": "Services", "window_start_utc": "Window start (UTC)",
                     "scheduled_h": "Scheduled (h)", "lead_time_days": "Notice (days)",
                     "realised_downtime_min": "Realised downtime (min)", "affected_resources": "Resources affected"},
             empty="No planned maintenance in the selected range."),
        grid("pl-vm", "💻 VM planned maintenance notes", "06_planned_vm_reboot",
             [when("occurred_utc"), thr("reboot_mentioned", [("==", "true", "warning"), ("Default", None, "Blank")])],
             labels={"occurred_utc": "When (UTC)", "reboot_mentioned": "Reboot mentioned"},
             empty="No VM annotations. The VM annotation module is optional and needs VMs in scope."),
    ], "planned"))

    # ------------------------------------------------------------ PIR benchmark
    items.append(group("page-pir", "Public PIR benchmark", [
        describe("pir-desc",
                 "After a major incident Azure publishes a public report called a Post Incident Review (PIR). This page lists them as a benchmark for context.",
                 ["This is **Azure-wide, not your estate**. It shows what happened across Azure, whether or not your resources were affected.",
                  "Only large, broad incidents get a public PIR, so small issues are not here.",
                  "**Incident window** is how long the incident lasted, read from the report text. If a window could not be read, the table says so in *Window read*."]),
        kpi_tiles("pir-tiles", "📊 Azure-wide at a glance", "07_pir_tiles", "No public PIRs loaded."),
        chart("pir-year", "📅 Public PIRs per year", "07_pir_by_year", "columnchart", "year", ["pirs"], group_by="category",
              empty="No public PIRs loaded.", width="50"),
        chart("pir-cat", "⏱️ Incident length by category (hours)", "07_pir_by_category", "barchart", "category", ["median_h", "p90_h"],
              colors={"median_h": "blue", "p90_h": "orange"}, labels={"median_h": "Typical", "p90_h": "Long (9 in 10 shorter)"},
              empty="No public PIRs loaded.", width="50"),
        grid("pir-list", "📰 Public PIRs", "07_pir_list",
             [when("published_date"), bar("duration_h", "orange"),
              thr("parse_status", [("==", "ok", "success"), ("==", "manual", "info"), ("Default", None, "warning")])],
             labels={"published_date": "Published", "category": "Category", "event_title": "Incident", "duration_h": "Length (h)",
                     "parse_status": "Window read", "tracking_id": "Tracking ID"},
             empty="No public PIRs loaded."),
    ], "pir"))

    # ------------------------------------------------------------ Expected downtime
    planner_params = param_item("planner-params", [
        {**p_dropdown_query("PlannerService", "Service", "p_service", multi=False, default="Virtual Machines"), "isGlobal": False},
        {**p_dropdown_query("PlannerRegion", "Region", "p_region", multi=False), "isGlobal": False},
        p_static("PlannerHorizon", "Horizon (years)", [("1", "1"), ("3", "3"), ("5", "5")], "1", local=True),
        p_text("CompositeSlas", "Component SLAs % (comma separated)", "99.95,99.99", local=True),
        p_static("CompositeMode", "Composition", [("serial", "Serial (all must be up)"), ("redundant", "Redundant (any one is enough)")], "serial", local=True),
    ])
    conf_icons = [("==", "high", "success"), ("==", "medium", "info"), ("Default", None, "warning")]
    range_colors = {"p50_annual_h": "blue", "p90_annual_h": "orange"}
    range_labels = {"p50_annual_h": "Typical year (P50)", "p90_annual_h": "Bad year (P90)"}
    items.append(group("page-planner", "Expected-downtime planner", [
        describe("pn-desc",
                 "A guide to how much downtime to plan for, based on what has actually happened in your own history. It is evidence, not a forecast or a promise.",
                 ["Pick a **service** and **region**. The tiles show a *typical year* (P50) and a *bad year* (P90) in hours of downtime.",
                  "The icon on the tile is the **confidence**: green = high, blue = medium, amber = low or insufficient history. Few past events means low confidence.",
                  "The charts compare categories: your estate on the left, the **Azure-wide PIR baseline** on the right (not about your estate, shown for context when your own history is thin).",
                  "**SLA allowance** is how much downtime the SLA permits per year, shown only when an SLA has been entered.",
                  "**Composite SLA**: type the SLAs of the parts of your solution. *Serial* means every part must be up (availability goes down). *Redundant* means any one part is enough (availability goes up)."]),
        planner_params,
        kpi_tiles("pn-tiles", "🎯 Planning range for the chosen service and region", "08_planner_tiles",
                  "No planning range yet for this service. Ranges are computed daily once events are in the ledger."),
        chart("pn-estate", "🏢 Your estate: typical vs bad year by category (hours)", "08_planner_by_category", "barchart", "scope_key",
              ["p50_annual_h", "p90_annual_h"], colors=range_colors, labels=range_labels, empty="No planning ranges for your estate yet.", width="50"),
        chart("pn-pir", "🌐 Azure-wide (public PIRs): typical vs bad year by category (hours)", "08_planner_pir_category", "barchart", "scope_key",
              ["p50_annual_h", "p90_annual_h"], colors=range_colors, labels=range_labels, empty="No PIR baseline yet.", width="50"),
        grid("pn-forecast", "📋 Planning range details", "08_planner_forecast",
             [thr("confidence", conf_icons), bar("p50_annual_h", "blue"), bar("p90_annual_h", "orange"), num("events_per_year", 2),
              num("mean_over_horizon_h", 1)],
             labels={"basis": "Based on", "scope_level": "Scope", "scope_key": "Scope key", "n_events": "Past events (n)", "window_days": "Window (days)",
                     "confidence": "Confidence", "events_per_year": "Events per year", "p50_annual_h": "Typical year (h)",
                     "p90_annual_h": "Bad year (h)", "mean_over_horizon_h": "Average over horizon (h)", "duration_basis": "Duration from", "note": "Note"},
             empty="No planning ranges yet. They are computed daily once events are in the ledger."),
        grid("pn-sla", "📜 SLA allowance (service catalog)", "08_planner_sla",
             [num("sla_percent", 3), num("allowance_h_per_year", 2), num("allowance_min_per_year", 1),
              thr("status", [("==", "SLA from catalog", "success"), ("Default", None, "Disable")])],
             labels={"service_name": "Service", "category": "Type", "sla_percent": "SLA (%)", "allowance_h_per_year": "Allowed downtime (h/year)",
                     "allowance_min_per_year": "Allowed downtime (min/year)", "sla_source_url": "Source", "sla_verified_on": "Verified on", "status": "Status"},
             filterable=False, empty="Service not in the catalog."),
        kpi_tiles("pn-composite", "🧮 Composite SLA calculator", "08_planner_composite", "Enter component SLAs, e.g. 99.95,99.99."),
    ], "planner"))

    # ------------------------------------------------------------ Data health
    items.append(group("page-health", "Data health", [
        describe("dh-desc",
                 "A check that the ledger itself is working and how far back its data goes. Look here first if the numbers on other pages look wrong or empty.",
                 ["**ingest** rows show when each data source last updated. A red cross (STALE) means no successful update in the last 36 hours.",
                  "**coverage** rows show the earliest data held for each source, so you know how much history the numbers are based on.",
                  "**quality** shows problems reading data, for example public reports whose incident window could not be read.",
                  "**subscriptions** compares the subscriptions that have data with the subscriptions configured."]),
        kpi_tiles("dh-tiles", "📊 Is the ledger up to date?", "09_health_tiles", "No ingest runs recorded yet."),
        grid("dh-main", "🩺 Data sources and quality", "09_health_main",
             [thr("status", [("==", "OK", "success"), ("==", "STALE", "critical"), ("==", "WARN", "warning"), ("Default", None, "info")]),
              num("hours_since_success", 1), num("rows_last_7d", 0, empty="")],
             labels={"status": "Status", "section": "Area", "item": "Item", "hours_since_success": "Hours since last success",
                     "rows_last_7d": "Rows added (7 days)", "detail": "Detail"},
             filterable=False, empty="No ingest runs recorded yet."),
    ], "health"))

    # ------------------------------------------------------------ About
    items.append(group("page-method", "About, method and caveats", [
        text("mt-about", "### About this workbook\n"
             "**Azure Maintenance Ledger** gives a customer one place to see the planned and unplanned maintenance of their Azure IaaS and PaaS services, "
             "and the downtime to expect, from a durable history. Azure itself only keeps Service Health and Resource Health data for a limited time "
             "(90 days to 1 year); the ledger keeps it for 730 days so trends can be reviewed after Azure has aged the data out.\n\n"
             "**Purpose**\n"
             "- Keep a durable record of Service Health events, Resource Health downtime and public Azure post-incident reviews (PIRs).\n"
             "- Separate **planned** from **unplanned** events, **IaaS** from **PaaS** services, and **exposure** (the event window) from **downtime** (minutes a resource was Unavailable).\n"
             "- Report observed availability against the SLA (where an SLA has been supplied) and an evidence-based expected-downtime planning range, always with sample size, window and confidence.\n\n"
             "Figures are evidence from history. They are not a forecast, a guarantee or a billing-grade availability measure."),
        text("mt-legend", "### Colours and icons\n"
             "- 🟧 **Orange** = unplanned. 🟦 **Blue** = planned.\n"
             "- ✅ **Green tick** = fine. ⚠️ **Amber warning** = take a look. ❌ **Red** = act. ℹ️ **Blue info** = for your information.\n"
             "- Bars inside tables show relative size within that column. Colour-filled cells show how good or bad the value is."),
        text("mt-method", "### Method\n" + method_md),
        text("mt-caveats", "### Caveats\n"
             "- Azure keeps Service Health 90 days to 1 year and Resource Health 30 days; the ledger starts when collection starts (see Data health coverage).\n"
             "- Resource Health records transitions to or from Unhealthy and states lasting more than 15 minutes; Unknown states and very short blips are not recorded.\n"
             "- Planned/unplanned classification of a Resource Health interval uses the VM annotation, else overlap with a planned event for the same subscription and service (region is not available on Resource Health rows).\n"
             "- Observed availability depends on the resource counts of the latest inventory snapshot and is marked approximate when counts changed.\n"
             "- Public PIRs are fetched from an undocumented endpoint and cover broad-impact incidents only.\n"
             "- Planning ranges are evidence from history, not a forecast or an SLA."),
    ], "method"))

    return {
        "version": "Notebook/1.0",
        "items": items,
        "defaultResourceIds": [WS],
        "fallbackResourceIds": [WS],
        "$schema": "https://github.com/Microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    wb = build()
    outputs = {
        OUT: json.dumps(wb, indent=1, ensure_ascii=False) + "\n",  # readable, diffable
        OUT_DEPLOY: json.dumps(wb, separators=(",", ":"), ensure_ascii=False) + "\n",  # minified: Bicep loadTextContent limit is 131072 chars
    }
    if a.check:
        stale = [p.name for p, t in outputs.items() if not p.exists() or p.read_text(encoding="utf-8") != t]
        if stale:
            print(f"{', '.join(stale)} out of date: run python tools/build_workbook.py")
            return 1
        print("workbook template files are up to date")
        return 0
    for p, t in outputs.items():
        p.write_text(t, encoding="utf-8")
        print(f"wrote {p} ({len(t)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
