#!/usr/bin/env python3
import csv
import glob
import re
import shutil
from pathlib import Path
from datetime import datetime

LOG_GLOB = 'logs/trade_log_*.csv'
POS_RE = re.compile(r"([0-9]{8}-[0-9]{6}-(?:BUY|SELL)-\d{3})")
now = datetime.now().strftime('%Y%m%d%H%M%S')
summary = {
    'files_scanned': 0,
    'files_modified': 0,
    'rows_examined': 0,
    'rows_filled': 0,
    'skipped_files': [],
}

for p in sorted(glob.glob(LOG_GLOB)):
    summary['files_scanned'] += 1
    path = Path(p)
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            summary['skipped_files'].append((p,'empty'))
            continue
        rows = [row for row in reader]

    # Determine fieldnames and whether pos_id exists
    fieldnames = list(header)
    has_pos = 'pos_id' in fieldnames
    has_note = 'note' in fieldnames
    if not has_pos:
        # we'll add pos_id column at end
        fieldnames.append('pos_id')
    # Rebuild dict rows
    dict_rows = []
    changed = False
    for i,row in enumerate(rows, start=1):
        # pad row to header length
        if len(row) < len(fieldnames):
            row = row + [''] * (len(fieldnames) - len(row))
        d = dict(zip(fieldnames, row))
        summary['rows_examined'] += 1
        res = (d.get('result') or '').strip()
        pid = (d.get('pos_id') or '').strip()
        note = (d.get('note') or '')
        # target: PAPER or PAPER_EXIT_* rows missing pos_id
        if (res == 'PAPER' or (res and res.startswith('PAPER_EXIT_'))) and not pid:
            # try extract from note
            m = POS_RE.search(note)
            if m:
                candidate = m.group(1)
                d['pos_id'] = candidate
                summary['rows_filled'] += 1
                changed = True
        dict_rows.append(d)

    if changed:
        # backup
        bak = path.with_suffix(path.suffix + f'.bak_autofix_{now}')
        shutil.copy2(path, bak)
        # write back
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for d in dict_rows:
                # ensure all fieldnames present
                row = {k: (d.get(k) or '') for k in fieldnames}
                writer.writerow(row)
        summary['files_modified'] += 1

print('auto-fix summary:')
for k,v in summary.items():
    print(' ', k, ':', v)

# write report
out = Path('audit_out')
out.mkdir(parents=True, exist_ok=True)
with open(out / f'autofix_report_{now}.json', 'w', encoding='utf-8') as fo:
    import json
    json.dump(summary, fo, ensure_ascii=False, indent=2)
print('wrote', out / f'autofix_report_{now}.json')
