#!/usr/bin/env python3
import csv
import json
from pathlib import Path
from datetime import datetime
import shutil
import csv as pycsv

ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / 'audit_out' / 'manual_fix_list.csv'
PROPOSALS = ROOT / 'audit_out' / 'autofix_dryrun_proposals_ext.json'
REPORT = ROOT / 'audit_out' / f'autofix_apply_manual_block_{datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")}.json'
BACKUP_SUFFIX = f'.bak_autofix_manual_{datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")}'
START_IDX = 20
END_IDX = 40

if not MANUAL.exists():
    print('manual list missing')
    raise SystemExit(1)
if not PROPOSALS.exists():
    print('proposals missing')
    raise SystemExit(1)

with MANUAL.open('r', encoding='utf-8') as f:
    rows = list(csv.DictReader(f))
with PROPOSALS.open('r', encoding='utf-8') as f:
    proposals_all = json.load(f).get('proposals', [])

applied = []

for idx in range(START_IDX, min(END_IDX, len(rows))):
    r = rows[idx]
    file = r.get('file','').strip()
    line = r.get('line','').strip()
    sample = r.get('sample','')
    if not file or not line.isdigit():
        applied.append({'entry': idx+1, 'file': file, 'line': line, 'status': 'invalid_manual_entry'})
        continue
    # find proposals matching file and audit_line
    matches = [p for p in proposals_all if p.get('file')==file and str(p.get('audit_line'))==line]
    # also allow proposals with same file and file_line equal to target
    # pick best confidence
    if not matches:
        applied.append({'entry': idx+1, 'file': file, 'line': line, 'status': 'no_proposal'})
        continue
    best = sorted(matches, key=lambda x: -(x.get('confidence') or 0))[0]
    sug = best.get('suggested_pos_id')
    file_line = best.get('file_line')
    p = ROOT / file
    if not p.exists():
        applied.append({'entry': idx+1, 'file': file, 'line': line, 'status': 'file_missing'})
        continue
    lines = p.read_text(encoding='utf-8').splitlines()
    # determine target row index
    row_idx = int(line)-1
    target_idxs = []
    if file_line and isinstance(file_line, int):
        target_idxs = [file_line-1]
    elif 0 <= row_idx < len(lines):
        # prefer the audit-reported line if pos_id column empty
        target_idxs = [row_idx]
    else:
        # fallback: search for sug in file
        found = False
        for i, ln in enumerate(lines):
            if sug and sug in ln:
                target_idxs = [i]
                found = True
                break
        if not found:
            applied.append({'entry': idx+1, 'file': file, 'line': line, 'status': 'no_target_found'})
            continue
    # backup
    backup = p.with_name(p.name + BACKUP_SUFFIX)
    if not backup.exists():
        shutil.copy(p, backup)
    changed = False
    for ti in target_idxs:
        try:
            row = next(pycsv.reader([lines[ti]]))
        except Exception:
            continue
        if len(row) <= 14:
            row += [''] * (15 - len(row))
        existing = row[14].strip()
        if existing:
            applied.append({'entry': idx+1, 'file': file, 'file_line': ti+1, 'status': 'already_present', 'existing': existing})
            continue
        row[14] = sug
        from io import StringIO
        out = StringIO()
        writer = pycsv.writer(out)
        writer.writerow(row)
        new_line = out.getvalue().rstrip('\r\n')
        lines[ti] = new_line
        applied.append({'entry': idx+1, 'file': file, 'file_line': ti+1, 'action': 'filled_pos_id', 'suggested': sug, 'confidence': best.get('confidence'), 'reason': best.get('reason')})
        changed = True
        break
    if changed:
        p.write_text('\n'.join(lines) + '\n', encoding='utf-8')

REPORT.parent.mkdir(parents=True, exist_ok=True)
REPORT.write_text(json.dumps({'generated_at': datetime.utcnow().isoformat()+'Z', 'range': [START_IDX+1, min(END_IDX, len(rows))], 'results': applied}, indent=2, ensure_ascii=False), encoding='utf-8')
print('manual block apply complete ->', REPORT)
