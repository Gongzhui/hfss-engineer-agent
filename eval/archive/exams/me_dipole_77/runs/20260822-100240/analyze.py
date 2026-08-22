import csv, collections, sys

fn = sys.argv[1]
data = collections.defaultdict(list)
with open(fn) as f:
    for r in csv.DictReader(f):
        data[r['variation']].append((float(r['freq_ghz']), float(r['s11_db'])))

def metrics(pts):
    pts.sort()
    f = [p[0] for p in pts]; s = [p[1] for p in pts]
    smin = min(s); fmin = f[s.index(smin)]
    # closest to 77
    i77 = min(range(len(f)), key=lambda k: abs(f[k]-77))
    # contiguous <=-10 segments
    segs = []
    cur = None
    for j in range(len(f)):
        if s[j] <= -10:
            if cur is None: cur = [j, j]
            else: cur[1] = j
        else:
            if cur: segs.append(cur); cur = None
    if cur: segs.append(cur)
    seg77 = [g for g in segs if g[0] <= i77 <= g[1]]
    bw = None; fl = fh = None
    if seg77 and s[i77] <= -10:
        g = seg77[0]; fl, fh = f[g[0]], f[g[1]]
        bw = 2*(fh-fl)/(fh+fl)*100
    return smin, fmin, f[i77], s[i77], fl, fh, bw, len(segs)

rows = []
for v, pts in data.items():
    smin, fmin, f77, s77, fl, fh, bw, nseg = metrics(pts)
    rows.append((v, smin, fmin, s77, fl, fh, bw, nseg))

rows.sort(key=lambda r: (r[6] is None, -(r[6] or 0)))
print(f"{'variation':45s} {'minS11':>7s} {'@f':>6s} {'S11@77':>7s} {'fL':>6s} {'fH':>6s} {'BW%':>6s} {'nseg':>4s}")
for v, smin, fmin, s77, fl, fh, bw, nseg in rows:
    fls = f"{fl:.1f}" if fl else "-"; fhs = f"{fh:.1f}" if fh else "-"
    bws = f"{bw:.1f}" if bw is not None else "-"
    print(f"{v:45s} {smin:7.2f} {fmin:6.1f} {s77:7.2f} {fls:>6s} {fhs:>6s} {bws:>6s} {nseg:4d}")
