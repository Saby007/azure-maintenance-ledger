"""Compares two compiled ARM templates ignoring compiler metadata (templateHash, generator version) and line-ending differences.

  python tools/check_template.py <freshly compiled azuredeploy.json> <committed infra/azuredeploy.json>

Used by CI: the committed one-click template must match what `az bicep build infra/azuredeploy.bicep` produces from the sources,
whatever Bicep version compiled it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def normalise(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: normalise(v) for k, v in node.items() if k not in ("templateHash", "_generator")}
    if isinstance(node, list):
        return [normalise(v) for v in node]
    if isinstance(node, str):
        return node.replace("\r\n", "\n")
    return node


def load(path: str) -> Any:
    return normalise(json.loads(Path(path).read_text(encoding="utf-8")))


def first_difference(a: Any, b: Any, path: str = "$") -> str | None:
    if type(a) is not type(b):
        return f"{path}: type {type(a).__name__} != {type(b).__name__}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k}: present in only one template"
            d = first_difference(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            d = first_difference(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else f"{path}: values differ"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    diff = first_difference(load(argv[1]), load(argv[2]))
    if diff:
        print(f"templates differ: {diff}\nRebuild: az bicep build --file infra/azuredeploy.bicep --outfile infra/azuredeploy.json")
        return 1
    print("templates match")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
