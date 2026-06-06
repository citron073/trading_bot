#!/usr/bin/env python3
import json
from pathlib import Path
import shutil
import csv
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
PROPOSAL_JSON = ROOT / 'audit_out' / 'autofix_dryrun_proposals.json'
REPORT_JSON = ROOT / 'audit_out' / f'autofix_apply_report_{datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")}.json'
BACKUP_SUFFIX = f'.bak_autofix_{datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")}'

if not PROPOSAL_JSON.exists():
    print('proposal file missing:', PROPOSAL_JSON)
    raise SystemExit(1)

data = json.loads(PROPOSAL_JSON.read_text(encoding='utf-8'))
proposals = data.get('proposals', [])

applied = []

for p in proposals:
    rel = p['file']
    suggested = p['suggested_pos_id']
    filep = ROOT / rel
    if not filep.exists():
        applied.append({'file': rel, 'status': 'missing_file'})
        continue
    text = filep.read_text(encoding='utf-8')
    lines = text.splitlines()
    changed = False
    # backup once per file
    backup_path = filep.with_name(filep.name + BACKUP_SUFFIX)
    if not backup_path.exists():
        shutil.copy(filep, backup_path)
    for idx, line in enumerate(lines):
        if suggested in line:
            # parse CSV row
            try:
                row = next(csv.reader([line]))
            except Exception:
                continue
            # header length expected >= 16; pos_id index is 14
            if len(row) > 14:
                pos_val = row[14].strip()
                if pos_val == '':
                    row[14] = suggested
                    # rewrite line with csv
                    from io import StringIO
                    out = StringIO()
                    writer = csv.writer(out)
                    writer.writerow(row)
                    new_line = out.getvalue().strip('\r\n')
                    lines[idx] = new_line
                    changed = True
                    applied.append({'file': rel, 'line_idx': idx+1, 'action': 'filled_pos_id', 'suggested': suggested})
                    # don't modify other occurrences in same file for same proposal
                    break
    if changed:
        filep.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    else:
        applied.append({'file': rel, 'status': 'no_change_or_already_present'})

REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
REPORT_JSON.write_text(json.dumps({'generated_at': datetime.utcnow().isoformat()+'Z', 'applied': applied}, indent=2, ensure_ascii=False), encoding='utf-8')
print('apply complete ->', REPORT_JSON)
