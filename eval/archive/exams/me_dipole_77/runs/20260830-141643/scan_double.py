import csv, glob
from collections import defaultdict
for path in sorted(glob.glob("round-0*[1-9]-s11.csv")):
    rows = defaultdict(list)
    with open(path, newline='', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            rows[r["variation"]].append((float(r["freq_ghz"]), float(r["s11_db"])))
    for var, pts in sorted(rows.items()):
        pts.sort()
        # find local minima below -8 dB with at least 2 GHz separation
        mins = []
        for i in range(1, len(pts)-1):
            if pts[i][1] < pts[i-1][1] and pts[i][1] <= pts[i+1][1] and pts[i][1] < -8:
                if not mins or pts[i][0]-mins[-1][0] > 2.5:
                    mins.append(pts[i])
                elif pts[i][1] < mins[-1][1]:
                    mins[-1] = pts[i]
        if len(mins) >= 2:
            print(path, var, [(round(f,1), round(s,1)) for f,s in mins])
