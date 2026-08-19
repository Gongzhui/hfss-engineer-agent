import csv
from collections import defaultdict

path = r"C:\Users\Gongzhui\Documents\Projects\hfss-mcp\eval\exams\uwb_circular_notch\runs\20260817-165848\round-005-s11.csv"
want_g1 = {8.5, 10.5, 12.5, 14.5}
want_l2 = {1.0, 1.6, 2.2, 3.0}

series = defaultdict(list)
with open(path, newline="") as f:
    for row in csv.DictReader(f):
        series[row["variation"]].append((float(row["freq_ghz"]), float(row["s11_db"])))


def parse_var(var):
    d = {}
    for part in var.split():
        k, v = part.split("=")
        d[k] = float(v.strip("'\"").replace("mm", ""))
    return d


def unmatched_bands(pts, thr=-10.0):
    segs = []
    start = None
    prev = None
    for f, s in pts:
        above = s > thr
        if above and start is None:
            start = f
        if (not above) and start is not None:
            segs.append((start, prev, round(prev - start, 2)))
            start = None
        prev = f
    if start is not None:
        segs.append((start, prev, round(prev - start, 2)))
    return segs


def matched_bands(pts, thr=-10.0):
    segs = []
    start = None
    prev = None
    for f, s in pts:
        ok = s <= thr
        if ok and start is None:
            start = f
        if (not ok) and start is not None:
            segs.append((start, prev, round(prev - start, 2)))
            start = None
        prev = f
    if start is not None:
        segs.append((start, prev, round(prev - start, 2)))
    return segs


def peak_in(pts, lo, hi):
    w = [(f, s) for f, s in pts if lo <= f <= hi]
    return max(w, key=lambda x: x[1]) if w else None


print("g1    l2   S11(6.6)  peak6-8     nseg     hole4-6          matched")
for var in sorted(series, key=lambda v: (parse_var(v).get("g1", 0), parse_var(v).get("l2", 0))):
    p = parse_var(var)
    if p.get("g1") not in want_g1 or p.get("l2") not in want_l2:
        continue
    pts = sorted(series[var])
    s66 = next((s for f, s in pts if abs(f - 6.6) < 1e-9), None)
    pn = peak_in(pts, 6.0, 8.0)
    un = unmatched_bands(pts)
    ma = matched_bands(pts)
    nseg = [u for u in un if u[0] <= 7.2 and u[1] >= 6.2]
    h46 = [u for u in un if u[0] < 6.3 and u[1] > 3.5]
    print(
        f"{p['g1']:4.1f} {p['l2']:4.1f}  {s66:7.2f}  {pn}  {nseg}  {h46}"
    )
    print(f"         un {un}")
    print(f"         ma {ma}")
    for f, s in pts:
        if 6.3 <= f <= 7.0:
            m = " *" if abs(f - 6.6) < 1e-9 else ""
            print(f"           {f:.1f} {s:7.2f}{m}")
