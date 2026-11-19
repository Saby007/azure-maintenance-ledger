"""Loads workbook KQL files (kql/workbook/*.kql): strips header comments and expands //#include directives.

Shared by tools/build_workbook.py and tools/run_kql_checks.py so both see exactly the same query text.
"""

from __future__ import annotations

import re
from pathlib import Path

WB_DIR = Path(__file__).resolve().parents[1] / "kql" / "workbook"
_INCLUDE = re.compile(r"^\s*//#include\s+(\S+)\s*$")
_PART = re.compile(r"^\s*//#part\s+(\w+)\s*$")
_PRELUDE_MARK = "__PRELUDE__"


def _prelude_parts() -> dict[str, str]:
    parts: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in (WB_DIR / "_prelude.kql").read_text(encoding="utf-8").splitlines():
        m = _PART.match(line)
        if m:
            current = parts.setdefault(m.group(1), [])
        elif current is not None and not line.lstrip().startswith("//"):
            current.append(line)
    return {k: "\n".join(v) for k, v in parts.items()}


def _prelude_for(rest: str) -> str:
    """Only the prelude parts the query references (directly or through another part), in file order."""
    parts = _prelude_parts()
    chosen: set[str] = set()
    changed = True
    while changed:
        changed = False
        haystack = rest + "\n".join(parts[p] for p in chosen)
        for name in parts:
            if name not in chosen and re.search(rf"\b{name}\b", haystack):
                chosen.add(name)
                changed = True
    return "\n".join(parts[p] for p in parts if p in chosen)


def _body(name: str) -> list[str]:
    text = (WB_DIR / f"{name}.kql").read_text(encoding="utf-8")
    out: list[str] = []
    for line in text.splitlines():
        m = _INCLUDE.match(line)
        if m and m.group(1) == "_prelude":
            out.append(_PRELUDE_MARK)
        elif m:
            out.extend(_body(m.group(1)))
        elif not line.lstrip().startswith("//"):
            out.append(line)
    return out


def load(name: str) -> str:
    lines = _body(name)
    if _PRELUDE_MARK in lines:
        prelude = _prelude_for("\n".join(ln for ln in lines if ln != _PRELUDE_MARK))
        first = lines.index(_PRELUDE_MARK)
        lines = [prelude if i == first else ln for i, ln in enumerate(lines) if i == first or ln != _PRELUDE_MARK]
    return "\n".join(lines).strip() + "\n"


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
    "{SelectedService}": "Virtual Machines",
    "{SelectedRegion}": "East US",
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
