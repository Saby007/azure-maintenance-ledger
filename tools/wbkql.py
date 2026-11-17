"""Loads workbook KQL files (kql/workbook/*.kql): strips header comments and expands //#include directives.

Shared by tools/build_workbook.py and tools/run_kql_checks.py so both see exactly the same query text.
"""

from __future__ import annotations

import re
from pathlib import Path

WB_DIR = Path(__file__).resolve().parents[1] / "kql" / "workbook"
_INCLUDE = re.compile(r"^\s*//#include\s+(\S+)\s*$")


def _body(name: str) -> list[str]:
    text = (WB_DIR / f"{name}.kql").read_text(encoding="utf-8")
    out: list[str] = []
    for line in text.splitlines():
        m = _INCLUDE.match(line)
        if m:
            out.extend(_body(m.group(1)))
        elif not line.lstrip().startswith("//"):
            out.append(line)
    return out


def load(name: str) -> str:
    return "\n".join(_body(name)).strip() + "\n"


def all_names() -> list[str]:
    return sorted(p.stem for p in WB_DIR.glob("*.kql") if not p.stem.startswith("_"))


# Values substituted for workbook tokens when queries are executed outside the workbook (run_kql_checks.py).
TEST_TOKENS = {
    "{TimeRange:start}": "ago(365d)",
    "{TimeRange:end}": "now()",
    "{Subscriptions}": "'*'",
    "{Category}": "'*'",
    "{Service}": "'*'",
    "{Region}": "'*'",
    "{IncludeUserInitiated}": "false",
    "{IncludeSynthetic}": "{synthetic}",
    "{PlannerService}": "Virtual Machines",
    "{PlannerRegion}": "East US",
    "{PlannerHorizon}": "1",
    "{CompositeSlas}": "99.95,99.99",
    "{CompositeMode}": "serial",
}


def render(name: str, synthetic: bool = False, **overrides: str) -> str:
    q = load(name)
    tokens = {**TEST_TOKENS, **overrides}
    for k, v in tokens.items():
        q = q.replace(k, v.replace("{synthetic}", "true" if synthetic else "false"))
    return q
