import csv, sys
from collections import defaultdict
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

path = sys.argv[1]
out = sys.argv[2]
picks = sys.argv[3:] if len(sys.argv) > 3 else None
rows = defaultdict(list)
with open(path, newline='', encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        rows[r["variation"]].append((float(r["freq_ghz"]), float(r["s11_db"])))
plt.figure(figsize=(11, 6.5))
for var, pts in sorted(rows.items()):
    pts.sort()
    if picks and not any(p in var for p in picks):
        continue
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    plt.plot(xs, ys, lw=1.4, label=var.replace("mm","").replace("'",""))
plt.axhline(-10, color="k", ls="--", lw=0.8)
plt.axvline(77, color="r", ls=":", lw=0.8)
plt.xlabel("GHz"); plt.ylabel("S11 dB"); plt.ylim(-32, 0)
plt.grid(alpha=0.3); plt.legend(fontsize=7, ncol=2)
plt.tight_layout(); plt.savefig(out, dpi=110)
print("wrote", out)
