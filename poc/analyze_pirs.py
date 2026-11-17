import json, re, datetime as dt, statistics as st, collections

rows = json.load(open("pirs.json", encoding="utf-8"))
MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], 1)}
MON_ABBR = {k[:3]: v for k, v in MONTHS.items()}

time_re = re.compile(r"\b(\d{1,2}):(\d{2})\b")
date_re = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?(?:,?\s+(\d{4}))?\b")
date_re2 = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,\s*(\d{4}))?\b")


def month_num(s):
    s = s.lower()
    return MONTHS.get(s) or MON_ABBR.get(s[:3]) if (s in MONTHS or s[:3] in MON_ABBR) else None


def parse_window(text, pir_year):
    m = re.search(r"\b(?:Between|From)\b", text)
    if not m:
        return None
    seg = text[m.start(): m.start() + 420]
    seg = re.split(r"(?<=[a-z\)])\.\s", seg)[0] if re.search(r"(?<=[a-z\)])\.\s", seg) else seg
    times = [(int(h), int(mi)) for h, mi in time_re.findall(seg)]
    if len(times) < 2:
        return None
    dates = []
    for dm in date_re.finditer(seg):
        mn = month_num(dm.group(2))
        if mn:
            dates.append((int(dm.group(1)), mn, int(dm.group(3)) if dm.group(3) else None, dm.start()))
    if not dates:
        for dm in date_re2.finditer(seg):
            mn = month_num(dm.group(1))
            if mn:
                dates.append((int(dm.group(2)), mn, int(dm.group(3)) if dm.group(3) else None, dm.start()))
    if not dates:
        return None
    y_default = next((d[2] for d in dates if d[2]), pir_year)
    d1 = dates[0]
    d2 = dates[1] if len(dates) > 1 else dates[0]
    try:
        start = dt.datetime(d1[2] or y_default, d1[1], d1[0], *times[0])
        end = dt.datetime(d2[2] or y_default, d2[1], d2[0], *times[1])
    except ValueError:
        return None
    if end < start and len(dates) == 1:
        end += dt.timedelta(days=1)
    if end < start:
        return None
    return start, end


AREAS = [
    ("Identity / Entra", r"active directory|entra|sign.?in|authenticat|access panel|microsoft graph"),
    ("Networking", r"network|front door|expressroute|gateway|dns|vpn|load balancer|cdn|firewall|traffic manager|virtual wan"),
    ("Storage / Data", r"storage|sql|cosmos|data factory|databricks|synapse|postgres|mysql|redis|event hub|service bus|managed disk"),
    ("Compute / Containers / App", r"virtual machine|\bvm\b|compute|app service|functions|kubernetes|aks|container|scale set|batch|power/cooling|multiple services|control plane|resource manager|datacenter|cooling|power"),
    ("AI / Cognitive", r"openai|cognitive|foundry|ai service|speech|machine learning|ai search"),
    ("Management / Monitoring", r"portal|monitor|log analytics|application insights|alerts|activity log|arm\b|key vault|policy|service health"),
]


def area_of(title):
    tl = title.lower()
    for name, rx in AREAS:
        if re.search(rx, tl):
            return name
    return "Other"


out = []
for r in rows:
    d = dt.datetime.strptime(r["date"], "%m/%d/%Y")
    w = parse_window(r["text"], d.year)
    dur = None
    if w:
        dur = (w[1] - w[0]).total_seconds() / 3600
        if dur > 24 * 14:
            dur = None
    out.append({"date": d, "title": r["title"], "id": r["tracking_id"], "dur_h": dur, "area": area_of(r["title"]),
                "multi_region": bool(re.search(r"multiple regions|multiple services", r["title"], re.I))})

ok = [o for o in out if o["dur_h"] is not None]
print(f"PIRs: {len(out)}  parsed duration: {len(ok)} ({len(ok)/len(out):.0%})")
print()
print("Duration stats (hours) on parsed PIRs: median {:.1f}  mean {:.1f}  p90 {:.1f}  max {:.1f}".format(
    st.median(o["dur_h"] for o in ok), st.mean(o["dur_h"] for o in ok),
    sorted(o["dur_h"] for o in ok)[int(0.9 * len(ok)) - 1], max(o["dur_h"] for o in ok)))
print()
print("By year  (PIRs | parsed | median h | total impact h):")
for y in sorted({o["date"].year for o in out}):
    yo = [o for o in out if o["date"].year == y]
    yp = [o for o in yo if o["dur_h"] is not None]
    med = st.median(o["dur_h"] for o in yp) if yp else float("nan")
    tot = sum(o["dur_h"] for o in yp)
    print(f"  {y}: {len(yo):3d} | {len(yp):3d} | {med:5.1f} | {tot:6.1f}")
print()
print("By area (PIRs | median h | total h):")
byarea = collections.defaultdict(list)
for o in out:
    byarea[o["area"]].append(o)
for a, lst in sorted(byarea.items(), key=lambda kv: -len(kv[1])):
    p = [o for o in lst if o["dur_h"] is not None]
    med = st.median(o["dur_h"] for o in p) if p else float("nan")
    print(f"  {a:30s} {len(lst):3d} | {med:5.1f} | {sum(o['dur_h'] for o in p):6.1f}")
print()
print("Sample parsed rows:")
for o in sorted(ok, key=lambda x: x["date"])[-8:]:
    print(f"  {o['date'].date()} {o['id']:10s} {o['dur_h']:6.1f} h  {o['area']:28s} {o['title'][:70]}")
print()
print("Unparsed examples:")
for o in [o for o in out if o["dur_h"] is None][:6]:
    print("  ", o["date"].date(), o["id"], o["title"][:80])
json.dump([{**o, "date": o["date"].strftime("%Y-%m-%d")} for o in out], open("pir_parsed.json", "w"), indent=1)
