#!/usr/bin/env python3
import csv, re, shutil, glob, time, os
now_ts = time.strftime("%Y%m%d%H%M%S")
files = sorted(glob.glob('logs/*.csv'))
print('files:', len(files))
for p in files:
    bak = f"{p}.bak_fix_{now_ts}"
    shutil.copy2(p, bak)
    changed = False
    with open(p, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = []
        for r in reader:
            note = (r.get('note') or '')
            note2 = re.sub(r'\bpos_id=None(?:,None)?\b,?', '', note)
            note2 = re.sub(r',\s*$', '', note2).strip()
            if note2 != note:
                changed = True
            r['note'] = note2
            pid = (r.get('pos_id') or '').strip()
            if 'None' in pid:
                if pid != '':
                    changed = True
                pid = ''
            r['pos_id'] = pid
            rows.append(r)
    if changed:
        with open(p, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            w.writeheader()
            w.writerows(rows)
        print('fixed', p, '-> backup', bak)
    else:
        os.remove(bak)
        print('nochange', p)
print('done')
