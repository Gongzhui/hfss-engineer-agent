import csv
import sys
from collections import defaultdict

path = sys.argv[1]
want_patch = {9.0, 9.5, 10.0, 10.5}
want_slot = {19.5, 20.0, 20.5, 21.0}

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


def unmatched_near(pts, f0, window=1.2, thr=-10.0):
    segs = []
    start = None
    prev = None
    for f, s in pts:
        if abs(f - f0) > window:
            if start is not None:
                segs.append((start, prev, round(prev - start, 2)))
                start = None
            prev = f
            continue
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


def local_peak(pts, lo, hi):
    window = [(f, s) for f, s in pts if lo <= f <= hi]
    if not window:
        return None
    return max(window, key=lambda x: x[1])


rows = []
for var, pts in series.items():
    p = parse_var(var)
    if p.get("patch_r") not in want_patch or p.get("slot_length") not in want_slot:
        continue
    pts = sorted(pts)
    s66 = next((s for f, s in pts if abs(f - 6.6) < 1e-9), None)
    # slot notch lives ~6-8; matching hole ~4-5.5
    peak_notch = local_peak(pts, 5.8, 8.0)
    peak_hole = local_peak(pts, 3.8, 5.5)
    segs = unmatched_near(pts, 6.6, window=1.5) if peak_notch else []
    rows.append((p["patch_r"], p["slot_length"], s66, peak_notch, peak_hole, segs, var))

rows.sort()
print(f"round traces: {len(rows)}")
print("patch  slot   S11(6.6)  notch_f  notch_dB  hole_f  hole_dB  unmatched_near_6.6")
for pr, sl, s66, pn, ph, segs, var in rows:
    nf, nd = (pn if pn else (None, None))
    hf, hd = (ph if ph else (None, None))
    print(
        f"{pr:4.1f} {sl:5.1f}  {s66:7.2f}  {nf:6.1f}  {nd:7.2f}  {hf:5.1f}  {hd:7.2f}  {segs}"
    )
