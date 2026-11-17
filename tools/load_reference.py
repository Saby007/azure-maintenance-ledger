"""Load reference/service_catalog.csv into AzServiceCatalog_CL (run after editing the catalog).

  python tools/load_reference.py [--dry-run] [--file reference/service_catalog.csv]

SLA percentages are never invented: a row without sla_percent shows "SLA not set". A non-blank sla_percent
requires sla_source_url and sla_verified_on, otherwise the row is rejected.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from collector.backfill import DryRunIngestor, load_env  # noqa: E402
from collector.catalog import build_rows, read_catalog  # noqa: E402
from collector.ingest import Ingestor  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, default=ROOT / "reference" / "service_catalog.csv")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    load_env(ROOT / ".env")
    rows = build_rows(read_catalog(a.file))
    ing = DryRunIngestor() if a.dry_run else Ingestor()
    n = ing.upload("AzServiceCatalog_CL", rows)
    print(f"catalog rows {'validated' if a.dry_run else 'uploaded'}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
