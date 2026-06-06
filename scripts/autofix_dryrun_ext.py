#!/usr/bin/env python3
import csv
import json
import re
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
MANUAL_CSV = ROOT / 'audit_out' / 'manual_fix_list.csv'
OUT_JSON = ROOT / 'audit_out' / 'autofix_dryrun_proposals_ext.json'
POS_RE = re.compile(r"(\d{8}-\d{6}-(?:BUY|SELL)-\d{3})")
POS_IN_NOTE = re.compile(r"pos_id=([\w\-]+)")

# Tunable heuristics
NEARBY_WINDOW = 50
NEARBY_CONFIDENCE = 0.75
SINGLE_POS_MIN_COUNT = 3
SINGLE_POS_DOMINANCE = 0.8
SINGLE_POS_CONFIDENCE = 0.7

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
        p = ROOT / file
        if not p.exists():
            continue
        try:
            lines = p.read_text(encoding='utf-8').splitlines()
        except Exception:
            continue
        # try exact sample match first (high confidence)
        proposed = None
        m = POS_RE.search(sample)
        if m:
            proposed = {'file': file, 'audit_line': line, 'suggested_pos_id': m.group(1), 'reason': 'pos_in_sample', 'confidence': 1.0}
            proposals.append(proposed)
            continue
        # parse target row (if numeric line available)
        row_idx = None
        try:
            row_idx = int(line)-1 if line and line.isdigit() else None
        except Exception:
            row_idx = None
        # attempt to inspect the reported row's text
        if row_idx is not None and 0 <= row_idx < len(lines):
            text = lines[row_idx]
            # search for pos_id in 'note' substrings like 'pos_id=...'
            m2 = POS_IN_NOTE.search(text)
            if m2:
                proposals.append({'file': file, 'audit_line': line, 'file_line': row_idx+1, 'suggested_pos_id': m2.group(1), 'reason': 'pos_in_note', 'confidence': 0.95, 'row_text': text[:300]})
                continue
            # search for any pos-like token in the same row
            m3 = POS_RE.search(text)
            if m3:
                proposals.append({'file': file, 'audit_line': line, 'file_line': row_idx+1, 'suggested_pos_id': m3.group(1), 'reason': 'pos_like_in_row', 'confidence': 0.9, 'row_text': text[:300]})
                continue
        # scan nearby lines for pos_id in pos_id column (expanded window)
        if row_idx is not None:
            start = max(0, row_idx-NEARBY_WINDOW)
            end = min(len(lines)-1, row_idx+NEARBY_WINDOW)
            for i in range(start, end+1):
                ln = lines[i]
                m4 = POS_RE.search(ln)
                if m4:
                    proposals.append({'file': file, 'audit_line': line, 'file_line': i+1, 'suggested_pos_id': m4.group(1), 'reason': 'nearby_row_pos', 'confidence': NEARBY_CONFIDENCE, 'row_text': ln[:300]})
                    break
        # last resort: search entire file for pos_id frequency patterns
        all_pos_list = POS_RE.findall('\n'.join(lines))
        all_pos = set(all_pos_list)
        if len(all_pos) == 1 and all_pos_list:
            proposals.append({'file': file, 'audit_line': line, 'suggested_pos_id': list(all_pos)[0], 'reason': 'single_pos_in_file', 'confidence': SINGLE_POS_CONFIDENCE})
        elif all_pos_list:
            # consider a dominant pos_id if it appears many times or is dominant
            from collections import Counter
            c = Counter(all_pos_list)
            most, count = c.most_common(1)[0]
            if count >= SINGLE_POS_MIN_COUNT:
                total = sum(c.values())
                if total == 0:
                    frac = 0
                else:
                    frac = count/total
                if frac >= SINGLE_POS_DOMINANCE:
                    proposals.append({'file': file, 'audit_line': line, 'suggested_pos_id': most, 'reason': 'dominant_pos_in_file', 'confidence': SINGLE_POS_CONFIDENCE, 'occurrences': count, 'total_pos_found': total})

OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
OUT_JSON.write_text(json.dumps({'generated_at': datetime.utcnow().isoformat()+'Z', 'proposals': proposals}, indent=2, ensure_ascii=False), encoding='utf-8')
print('ext dry-run proposals:', len(proposals), '->', OUT_JSON)
