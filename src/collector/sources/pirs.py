"""Public PIR source (undocumented endpoint: fragile, optional - see AGENTS.md A3.7).

Interface: `PirSource` yields raw PIR dicts {date, title, tracking_id, text}. `FetchPirSource` reads the public
status-history page; `JsonPirSource`/`CsvPirSource` are drop-in replacements (manual import, fixtures).
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import logging
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from ..ingest import row_key, stamp, utc_iso
from .pir_parser import PirWindow, category_of, load_overrides, normalize, parse_window

log = logging.getLogger("aol.pirs")

BASE_URL = "https://azure.status.microsoft/en-us/statushistoryapi/"
USER_AGENT = "azure-maintenance-ledger/0.1 (customer-run ledger; low volume, >=1s between requests)"
SOURCE_URL = "https://azure.status.microsoft/en-us/status/history/"


class PirSource(Protocol):
    def items(self) -> Iterable[dict]: ...


class JsonPirSource:
    def __init__(self, path: Path):
        self.path = path

    def items(self) -> Iterable[dict]:
        return json.loads(self.path.read_text(encoding="utf-8"))


class CsvPirSource:
    """Manual import: CSV with columns date (MM/DD/YYYY), title, tracking_id, text."""

    def __init__(self, path: Path):
        self.path = path

    def items(self) -> Iterable[dict]:
        with self.path.open(encoding="utf-8", newline="") as fh:
            yield from csv.DictReader(fh)


class FetchPirSource:
    def __init__(self, cache_dir: Path | None = None, max_pages: int = 80, delay_s: float = 1.0):
        self.cache_dir = cache_dir
        self.max_pages = max_pages
        self.delay_s = max(delay_s, 1.0)

    def _page_html(self, session, page: int) -> str | None:
        cache = self.cache_dir / f"pirs_page_{page:03d}.html" if self.cache_dir else None
        if cache and cache.exists():
            return cache.read_text(encoding="utf-8")
        params = {"serviceSlug": "all", "regionSlug": "all", "startDate": "all", "page": page, "shdrefreshflag": "true"}
        r = session.get(BASE_URL, params=params, timeout=60)
        time.sleep(self.delay_s)
        if r.status_code != 200:
            log.warning("PIR page %d returned HTTP %d", page, r.status_code)
            return None
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(r.text, encoding="utf-8")
        return r.text

    def items(self) -> Iterable[dict]:
        import requests
        from bs4 import BeautifulSoup

        session = requests.Session()
        session.headers.update({"X-Requested-With": "XMLHttpRequest", "User-Agent": USER_AGENT})
        page_size = 10
        previous = page_size
        for page in range(1, self.max_pages + 1):
            found: list[dict] = []
            # An empty or failed page right after a full page is usually a transient answer from the site, not the end of the list.
            for attempt in range(1, 4 if previous >= page_size else 2):
                html = self._page_html(session, page)
                found = parse_history_html(html, BeautifulSoup) if html else []
                if found:
                    break
                if attempt < 3 and previous >= page_size:
                    time.sleep(5 * attempt)
                    if self.cache_dir:  # never cache an empty answer
                        (self.cache_dir / f"pirs_page_{page:03d}.html").unlink(missing_ok=True)
            if not found:
                return
            previous = len(found)
            yield from found
            if previous < page_size:  # a short page is the last one
                return


def parse_history_html(html: str, bs4_cls=None) -> list[dict]:
    if bs4_cls is None:
        from bs4 import BeautifulSoup as bs4_cls
    soup = bs4_cls(html, "html.parser")
    out = []
    for it in soup.select("div.incident-history-item"):
        d = it.select_one("span.hide-text")
        t = it.select_one("div.incident-history-title")
        tid = it.select_one("div.incident-history-tracking-id")
        body = it.select_one("div.incident-history-collapse")
        out.append(
            {
                "date": d.get_text(strip=True) if d else None,
                "title": t.get_text(" ", strip=True) if t else None,
                "tracking_id": tid.get_text(" ", strip=True).replace("Tracking ID:", "").strip() if tid else None,
                "text": body.get_text("\n", strip=True) if body else "",
            }
        )
    return out


def build_row(raw: dict, overrides: dict[str, PirWindow]) -> dict:
    published = dt.datetime.strptime(raw["date"], "%m/%d/%Y")
    text = normalize(raw.get("text") or "")
    title = normalize(raw.get("title") or "")
    tid = (raw.get("tracking_id") or "").strip()
    window = parse_window(text, published.date())
    note = ""
    if tid in overrides:  # a manual override always wins over the regex result
        window = overrides[tid]
        note = window.note
    status = window.status if window else "unparsed"
    row = {
        "tracking_id": tid,
        "published_date": utc_iso(published),
        "event_title": title,
        "body_text": text[:30000],
        "window_start_utc": utc_iso(window.start) if window and window.start else None,
        "window_end_utc": utc_iso(window.end) if window and window.end else None,
        "duration_h": round(window.duration_h, 4) if window and window.duration_h is not None else None,
        "parse_status": status,
        "parse_note": note or ("" if window else "no 'Between/From <time> ... <date>' window found"),
        "category": category_of(title),
        "source_url": SOURCE_URL,
        "raw_hash": hashlib.sha256(text.encode()).hexdigest(),
    }
    return row


def build_rows(items: Iterable[dict], overrides_path: Path | None = None) -> list[dict]:
    overrides = load_overrides(overrides_path) if overrides_path else {}
    rows = []
    seen: set[str] = set()
    for raw in items:
        r = build_row(raw, overrides)
        key = row_key("pir", "-", r["tracking_id"], r["raw_hash"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(stamp(r, key))
    return rows
