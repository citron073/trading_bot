#!/usr/bin/env python3
import csv, re, shutil, glob, time, os
now_ts = time.strftime("%Y%m%d%H%M%S")
PID_RE = re.compile(r"\b(\d{8}-\d{6}-(?:BUY|SELL)-\d{3})\b")
files = sorted(glob.glob('logs/*.csv'))
print('files:', len(files))
for p in files:
    bak = f"{p}.bak_fix2_{now_ts}"
    shutil.copy2(p, bak)
    changed = False
    with open(p, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = []
        for r in reader:
            pid = (r.get('pos_id') or '').strip()
            note = (r.get('note') or '')
            # if pid contains comma-separated list, try first valid
            if pid and ',' in pid:
                parts = [x.strip() for x in pid.split(',') if x.strip()]
                newpid = None
                for part in parts:
                    m = PID_RE.search(part)
                    if m:
                        newpid = m.group(1)
                        break
                if not newpid and parts:
                    newpid = parts[0]
                if newpid != pid:
                    pid = newpid or ''
                    changed = True
            # if pid invalid, try extract from note
            if (not pid) or (not PID_RE.fullmatch(pid)):
                m = PID_RE.search(note)
                if m:
                    newpid = m.group(1)
                    if newpid != pid:
                        pid = newpid
                        changed = True
            # ensure note has single 'pos_id=...' if pid present
            if pid:
                # remove any existing pos_id=... occurrences
                note = re.sub(r"\bpos_id=[^\s,]+,?", "", note).strip()
                # append canonical pos_id
                if note:
                    note = (note + f" pos_id={pid}").strip()
                else:
                    note = f"pos_id={pid}"
                changed = True
            else:
                # no pid: remove any 'pos_id=...' fragments
                n2 = re.sub(r"\bpos_id=[^\s,]+,?", "", note).strip()
                if n2 != note:
                    note = n2
                    changed = True
            r['pos_id'] = pid or ''
            r['note'] = note
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
