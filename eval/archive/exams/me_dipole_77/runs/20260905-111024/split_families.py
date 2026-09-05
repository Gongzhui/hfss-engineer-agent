import csv,re,sys
from pathlib import Path
p=Path(sys.argv[1]); key=sys.argv[2]; groups={}
with p.open() as f:
    reader=csv.DictReader(f); fields=reader.fieldnames
    for r in reader:
        match=re.search(r"(?:^|\s)"+re.escape(key)+r"='([^']+)'",r['variation'])
        if match: groups.setdefault(match.group(1),[]).append(r)
for value,rows in groups.items():
    dest=p.with_name(p.stem+'-'+key+'-'+value+'.csv')
    with dest.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    print(dest)
