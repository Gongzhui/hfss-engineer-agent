import csv, json, sys
from pathlib import Path
p=Path(sys.argv[1])
groups={}
for r in csv.DictReader(p.open(encoding='utf-8-sig')):
    groups.setdefault(r.get('variation','nominal'),[]).append((float(r['freq_ghz']),float(r['s11_db'])))
out=[]
for name,pts in groups.items():
    pts.sort()
    i=min(range(len(pts)),key=lambda j:abs(pts[j][0]-77))
    bands=[]
    j=0
    while j<len(pts):
        if pts[j][1]>-10:
            j+=1
            continue
        k=j
        while k+1<len(pts) and pts[k+1][1]<=-10:k+=1
        bands.append([pts[j][0],pts[k][0]])
        j=k+1
    band=next((b for b in bands if b[0]<=pts[i][0]<=b[1]),None)
    fbw=2*(band[1]-band[0])/sum(band) if band else 0
    out.append(dict(variation=name,near_77=pts[i],bands=bands,target_band=band,fbw=fbw))
out.sort(key=lambda r:(r['fbw'], -r['near_77'][1]),reverse=True)
p.with_suffix('.summary.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
print(json.dumps(out[:12],indent=2))
