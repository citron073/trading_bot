#!/usr/bin/env python3
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / 'audit_out' / 'manual_fix_list.csv'
N = 20

if not P.exists():
    print('manual_fix_list missing:', P)
    raise SystemExit(1)

with P.open('r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for idx, row in enumerate(reader):
        if idx >= N:
            break
        file = (ROOT / row.get('file','').strip())
        line = row.get('line','').strip()
        msg = row.get('message','').strip()
        sample = row.get('sample','').strip()
        print('--- ENTRY', idx+1, '---')
        print('file:', row.get('file',''), 'line:', line, 'message:', msg)
        if not file.exists():
            print('  (file missing) sample:', sample)
            print()
            continue
        try:
            ln = int(line)
        except Exception:
            print('  (invalid line) sample:', sample)
            print()
            continue
        lines = file.read_text(encoding='utf-8').splitlines()
        start = max(1, ln-2)
        end = min(len(lines), ln+2)
        for i in range(start, end+1):
            prefix = '>' if i == ln else ' '
            print(f"{prefix}{i:6d}: {lines[i-1]}")
        print()
