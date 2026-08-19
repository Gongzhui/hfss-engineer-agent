import csv
import sys
from collections import defaultdict

path = sys.argv[1]
series = defaultdict(list)
with open(path, newline="") as f:
    r = csv.DictReader(f)
    for row in r:
        series[row["variation"]].append((float(row["freq_ghz"]), float(row["s11_db"])))


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
            segs.append((start, prev))
            start = None
        prev = f
    if start is not None:
        segs.append((start, prev))
    return segs


def s_at(pts, f0):
    for f, s in pts:
        if abs(f - f0) < 1e-9:
            return s
    return None


print(f"variations: {len(series)}")
for var in sorted(series.keys()):
    pts = sorted(series[var])
    unmatched = unmatched_bands(pts)
    matched = matched_bands(pts)
    s66 = s_at(pts, 6.6)
    window = [(f, s) for f, s in pts if 4.5 <= f <= 8.5]
    peak = max(window, key=lambda x: x[1]) if window else None
    window2 = [(f, s) for f, s in pts if 2.0 <= f <= 4.5]
    peak2 = max(window2, key=lambda x: x[1]) if window2 else None
    print("---")
    print(var)
    print(f"  S11(6.6)={s66:.3f}" if s66 is not None else "  S11(6.6)=NA")
    print(f"  unmatched S11>-10: {unmatched}")
    print(f"  matched S11<=-10: {matched}")
    if peak:
        print(f"  4.5-8.5 peak: {peak[0]} GHz, {peak[1]:.2f} dB")
    if peak2:
        print(f"  2-4.5 peak: {peak2[0]} GHz, {peak2[1]:.2f} dB")
