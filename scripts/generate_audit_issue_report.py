#!/usr/bin/env python3
import json,glob,csv
rep = json.load(open('audit_out/audit_20260121_20260221.json', encoding='utf-8'))
issues = [i for i in rep.get('issues',[]) if i['severity'] in ('FATAL','ERROR')]
files = sorted(glob.glob('logs/trade_log_*.csv'))
# build cumulative mapping
rows_map = {}
cum=0
for p in files:
    with open(p, newline='', encoding='utf-8') as f:
        r=csv.reader(f)
        header=next(r, None)
        for ln,cols in enumerate(r, start=1):
            cum += 1
            rows_map[cum] = (p, ln, ','.join(cols))
# write details
out='audit_out/issues_details.txt'
with open(out,'w',encoding='utf-8') as fo:
    fo.write(f'total FATAL/ERROR: {len(issues)}\n')
    # counts by code
    from collections import Counter
    codes = Counter([i['code'] for i in issues])
    fo.write('counts by code:\n')
    for c,n in codes.most_common():
        fo.write(f'  {c}: {n}\n')
    fo.write('\nDetailed list:\n')
    for it in issues:
        sev=it['severity']; code=it['code']; msg=it['message']; ctx=it.get('context',{})
        row=ctx.get('row')
        if isinstance(row,int) and row in rows_map:
            p,ln,samp = rows_map[row]
            fo.write(f'{sev} {code} -> {p} line {ln}\n')
            fo.write(f'  message: {msg}\n')
            fo.write(f'  sample: {samp[:300]}\n')
        else:
            fo.write(f'{sev} {code} -> row {row} (no mapping)\n')
            fo.write(f'  message: {msg}\n')
print('wrote', out)
