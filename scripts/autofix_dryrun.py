#!/usr/bin/env python3
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANUAL_CSV = ROOT / 'audit_out' / 'manual_fix_list.csv'
OUT_JSON = ROOT / 'audit_out' / 'autofix_dryrun_proposals.json'
POS_RE = re.compile(r"\d{8}-\d{6}-(?:BUY|SELL)-\d{3}")

proposals = []

with MANUAL_CSV.open('r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for r in reader:
        code = r.get('code','')
        file = r.get('file','')
        line = r.get('line','')
        sample = r.get('sample','') or ''
        if file in ('','(no-file)'):
            continue
        if code not in ('PAPER_MISSING_POS_ID','EXIT_MISSING_POS_ID'):
            continue
        # conservative: only propose when pos_id pattern exists in sample
        m = POS_RE.search(sample)
        if m:
            proposals.append({
                'file': file,
                'audit_line': line,
                'sample_excerpt': sample[:200],
                'suggested_pos_id': m.group(0),
                'reason': 'exact_pos_id_in_sample',
                'confidence': 1.0,
            })
        else:
            # search the file near the reported line for any pos_id-like token
            p = ROOT / file
            if not p.exists():
                continue
            try:
                lines = p.read_text(encoding='utf-8').splitlines()
            except Exception:
                continue
            # try to find the sample row in file
            found = None
            for idx, lf in enumerate(lines):
                if sample.strip() and sample.strip().split(',')[0] in lf:
                    found = (idx+1, lf)
                    break
            if found:
                m2 = POS_RE.search(found[1])
                if m2:
                    proposals.append({
                        'file': file,
                        'audit_line': line,
                        'file_line': found[0],
                        'row_text': found[1][:300],
                        'suggested_pos_id': m2.group(0),
                        'reason': 'pos_id_in_file_row',
                        'confidence': 0.9,
                    })
            # else: do not propose — too risky

OUT_JSON.parent.mkdir(exist_ok=True, parents=True)
with OUT_JSON.open('w', encoding='utf-8') as out:
    json.dump({'generated_at': __import__('datetime').datetime.utcnow().isoformat()+'Z', 'proposals': proposals}, out, indent=2, ensure_ascii=False)

print(f"dry-run proposals: {len(proposals)} -> {OUT_JSON}")
