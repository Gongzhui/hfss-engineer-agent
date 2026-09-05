import csv, sys
from collections import defaultdict

path = sys.argv[1]
rows = defaultdict(list)
with open(path, newline='', encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        rows[r["variation"]].append((float(r["freq_ghz"]), float(r["s11_db"])))

for var, pts in sorted(rows.items()):
    pts.sort()
    mn = min(pts, key=lambda p: p[1])
    # all -10 dB runs
    runs = []
    cur = []
    for f, s in pts:
        if s <= -10:
            cur.append(f)
        else:
            if cur: runs.append(cur); cur = []
    if cur: runs.append(cur)
    run_desc = []
    for run in runs:
        fbw = 2*(max(run)-min(run))/(max(run)+min(run))*100
        run_desc.append(f"[{min(run):.1f},{max(run):.1f}]={fbw:.1f}%")
    # second dip detection: local max between dips
    print(f"{var:42s} min={mn[1]:6.2f}@{mn[0]:5.1f}  -10dB runs: {' '.join(run_desc) if run_desc else '-'}")
