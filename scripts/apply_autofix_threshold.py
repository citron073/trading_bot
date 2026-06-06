#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime
import shutil
import csv

ROOT = Path(__file__).resolve().parents[1]
PROPOSAL_JSON = ROOT / 'audit_out' / 'autofix_dryrun_proposals_ext.json'
REPORT_JSON = ROOT / 'audit_out' / f'autofix_apply_report_thr_{datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")}.json'
BACKUP_SUFFIX = f'.bak_autofix_thr_{datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")}'
THRESHOLD = 0.80

if not PROPOSAL_JSON.exists():
    print('proposal file missing:', PROPOSAL_JSON)
    raise SystemExit(1)

with PROPOSAL_JSON.open('r', encoding='utf-8') as f:
    data = json.load(f)
proposals_all = data.get('proposals', [])
proposals = [p for p in proposals_all if (p.get('confidence') or 0) >= THRESHOLD]

# group proposals by file
by_file = {}
for p in proposals:
    file = p.get('file')
    if not file:
        continue
    by_file.setdefault(file, []).append(p)

applied = []

for rel, items in by_file.items():
    filep = ROOT / rel
    if not filep.exists():
        applied.append({'file': rel, 'status': 'missing_file'})
        continue
    text = filep.read_text(encoding='utf-8')
    lines = text.splitlines()
    backup_path = filep.with_name(filep.name + BACKUP_SUFFIX)
    if not backup_path.exists():
        shutil.copy(filep, backup_path)
    changed = False
    # Sort proposals: prefer higher confidence and those with file_line
    items_sorted = sorted(items, key=lambda x: (-(x.get('confidence',0)), 'file_line' not in x))
    for p in items_sorted:
        sug = p.get('suggested_pos_id')
        file_line = p.get('file_line')
        row_idx = None
        if file_line:
            try:
                row_idx = int(file_line) - 1
            except Exception:
                row_idx = None
        target_idxs = []
        if row_idx is not None and 0 <= row_idx < len(lines):
            target_idxs = [row_idx]
        else:
            row_text = p.get('row_text')
            found = False
            for i, ln in enumerate(lines):
                if sug and sug in ln:
                    target_idxs = [i]
                    found = True
                    break
            if not found and row_text:
                for i, ln in enumerate(lines):
                    if row_text.strip() and row_text.strip().split(',')[0] in ln:
                        target_idxs = [i]
                        found = True
                        break
        if not target_idxs:
            applied.append({'file': rel, 'status': 'no_target_row', 'suggested': sug, 'reason': p.get('reason')})
            continue
        for ti in target_idxs:
            try:
                row = next(csv.reader([lines[ti]]))
            except Exception:
                continue
            if len(row) <= 14:
                row += [''] * (15 - len(row))
            existing = row[14].strip()
            if existing:
                applied.append({'file': rel, 'file_line': ti+1, 'status': 'already_present', 'existing': existing})
                continue
            row[14] = sug
            from io import StringIO
            out = StringIO()
            writer = csv.writer(out)
            writer.writerow(row)
            new_line = out.getvalue().rstrip('\r\n')
            lines[ti] = new_line
            applied.append({'file': rel, 'file_line': ti+1, 'action': 'filled_pos_id', 'suggested': sug, 'reason': p.get('reason'), 'confidence': p.get('confidence')})
            changed = True
            break
    if changed:
        filep.write_text('\n'.join(lines) + '\n', encoding='utf-8')

REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
REPORT_JSON.write_text(json.dumps({'generated_at': datetime.utcnow().isoformat()+'Z', 'threshold': THRESHOLD, 'applied': applied}, indent=2, ensure_ascii=False), encoding='utf-8')
print('apply complete ->', REPORT_JSON)
