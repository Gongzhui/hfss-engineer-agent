import csv
import sys
from collections import defaultdict

path = sys.argv[1]
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


print("g1   g2   g3   S11(6.6) notch_f notch_dB  nwidth  hole2-4  hole4-6  fL  fH  rbw%")
for var in sorted(series, key=lambda v: (parse_var(v)["g1"], parse_var(v)["g2"], parse_var(v)["g3"])):
    p = parse_var(var)
    pts = sorted(series[var])
    s66 = next((s for f, s in pts if abs(f - 6.6) < 1e-9), None)
    pn = peak_in(pts, 6.0, 7.2)
    un = unmatched_bands(pts)
    ma = matched_bands(pts)
    # notch width: unmatched segment overlapping 6.4-7.0
    nseg = [u for u in un if u[0] <= 6.8 and u[1] >= 6.4]
    nw = nseg[0][2] if nseg else None
    h24 = [u for u in un if u[0] < 4.0 and u[1] > 2.0]
    h46 = [u for u in un if u[0] < 6.2 and u[1] > 3.8]
    # fL: start of first matched band that is below the 6.6 notch and not the 1-2 GHz island if followed by a big hole?
    # Use: lowest freq of matched band immediately below notch, walking down through filled regions.
    # For scoring: outer edges around the 6.6 notch: last matched start before notch, last matched end after notch.
    below = [m for m in ma if m[1] <= 6.5]
    above = [m for m in ma if m[0] >= 6.6]
    fL = below[0][0] if below else None
    # if first below is 1.0 and there's a hole then another band, still use 1.0 only if holes filled
    fH = above[-1][1] if above else None
    rbw = 2 * (fH - fL) / (fH + fL) * 100 if fL and fH else None
    print(
        f"{p['g1']:4.1f} {p['g2']:4.1f} {p['g3']:4.1f}  {s66:7.2f}  {pn[0]:5.1f}  {pn[1]:7.2f}  {nw}  {h24}  {h46}  {fL} {fH}  {rbw and round(rbw,1)}"
    )
    print(f"         unmatched {un}")
    print(f"         matched   {ma}")
