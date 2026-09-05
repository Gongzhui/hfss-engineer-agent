import csv, math, sys, json
from pathlib import Path
p=Path(sys.argv[1]); z=list(csv.DictReader(p.open()))
groups={}
for r in csv.DictReader(Path(sys.argv[2]).open()):
    groups.setdefault(r.get('variation','nominal'),[]).append(r)
zs={float(r['freq_ghz']):20*math.log10(abs((complex(float(r['re']),float(r['im']))-50)/(complex(float(r['re']),float(r['im']))+50))) for r in z}
matches=sorted((max(abs(zs[float(r['freq_ghz'])]-float(r['s11_db'])) for r in rows),name) for name,rows in groups.items())
out={'matches':matches[:3], 'samples':[min(z,key=lambda a:abs(float(a['freq_ghz'])-f)) for f in map(float,sys.argv[3:] or [77])], 'x_zero_intervals':[[a['freq_ghz'],b['freq_ghz']] for a,b in zip(z,z[1:]) if float(a['im'])*float(b['im'])<0]}
print(json.dumps(out,indent=2));p.with_suffix('.validation.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
