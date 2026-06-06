#!/usr/bin/env python3
import json,glob,csv
from pathlib import Path

J = Path('audit_out/audit_20260121_20260221.json')
if not J.exists():
    raise SystemExit('audit json not found: ' + str(J))
rep = json.loads(J.read_text(encoding='utf-8'))
issues = [i for i in rep.get('issues',[]) if i['severity'] in ('FATAL','ERROR')]
files = sorted(glob.glob('logs/trade_log_*.csv'))
# build cumulative mapping
rows_map = {}
cur = 0
for p in files:
    with open(p, newline='', encoding='utf-8') as f:
        r = csv.reader(f)
        header = next(r, None)
        for ln,cols in enumerate(r, start=1):
            cur += 1
            rows_map[cur] = (p, ln, ','.join(cols))

out = Path('audit_out/manual_fix_list.csv')
with open(out, 'w', encoding='utf-8', newline='') as fo:
    w = csv.writer(fo)
    w.writerow(['code','severity','file','line','message','sample'])
    for it in issues:
        code = it.get('code')
        sev = it.get('severity')
        ctx = it.get('context',{})
        row = ctx.get('row')
        if isinstance(row,int) and row in rows_map:
            p,ln,samp = rows_map[row]
            w.writerow([code,sev,p,ln,it.get('message'),samp])
        else:
            w.writerow([code,sev,'(no-file)',row,it.get('message'),''])
print('wrote', out)
