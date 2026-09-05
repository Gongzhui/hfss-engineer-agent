import csv, sys
from collections import defaultdict

path = sys.argv[1]
target = float(sys.argv[2]) if len(sys.argv) > 2 else 77.0
rows = defaultdict(list)
with open(path, newline='', encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        rows[r["variation"]].append((float(r["freq_ghz"]), float(r["s11_db"])))
print(f"{len(rows)} variations in {path}")
for var, pts in sorted(rows.items()):
    pts.sort()
    near = min(pts, key=lambda p: abs(p[0]-target))
    mn = min(pts, key=lambda p: p[1])
    seg = ""
    if near[1] <= -10:
        run = [near[0]]
        freqs = [f for f, _ in pts]
        i = freqs.index(near[0])
        j = i - 1
        while j >= 0 and pts[j][1] <= -10:
            run.append(pts[j][0]); j -= 1
        j = i + 1
        while j < len(pts) and pts[j][1] <= -10:
            run.append(pts[j][0]); j += 1
        fl, fh = min(run), max(run)
        fbw = 2*(fh-fl)/(fh+fl)*100
        seg = f"PASS? band[{fl:.1f},{fh:.1f}] FBW={fbw:.1f}%"
    print(f"{var:45s} near{target:.0f}={near[1]:6.2f}@{near[0]:.1f}  min={mn[1]:6.2f}@{mn[0]:.1f}  {seg}")
