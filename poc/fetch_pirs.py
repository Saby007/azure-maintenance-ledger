import json, re, sys, time
import requests
from bs4 import BeautifulSoup

BASE = "https://azure.status.microsoft/en-us/statushistoryapi/"
OUT = sys.argv[1]
S = requests.Session()
S.headers.update({"X-Requested-With": "XMLHttpRequest", "User-Agent": "Mozilla/5.0 (PoC; low-volume research fetch)"})

rows = []
page = 1
while True:
    r = S.get(BASE, params={"serviceSlug": "all", "regionSlug": "all", "startDate": "all", "page": page, "shdrefreshflag": "true"}, timeout=60)
    if r.status_code != 200:
        print("HTTP", r.status_code, "on page", page)
        break
    soup = BeautifulSoup(r.text, "html.parser")
    items = soup.select("div.incident-history-item")
    if not items:
        break
    for it in items:
        d = it.select_one("span.hide-text")
        t = it.select_one("div.incident-history-title")
        tid = it.select_one("div.incident-history-tracking-id")
        body = it.select_one("div.incident-history-collapse")
        rows.append({
            "date": d.get_text(strip=True) if d else None,
            "title": t.get_text(" ", strip=True) if t else None,
            "tracking_id": tid.get_text(" ", strip=True).replace("Tracking ID:", "").strip() if tid else None,
            "text": body.get_text("\n", strip=True) if body else "",
        })
    print("page", page, "items", len(items), "total", len(rows), flush=True)
    page += 1
    time.sleep(1.0)
    if page > 80:
        break

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False)
print("saved", len(rows), "to", OUT)
