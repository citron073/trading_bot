#!/usr/bin/env python3
"""
Apply normalize_daily_report_json to all files in daily_report_out with backups.
Writes audit_out/normalize_apply_report_<ts>.json
"""
from pathlib import Path
import json
from datetime import datetime
import importlib
import sys

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "daily_report_out"
AUDIT_DIR = ROOT / "audit_out"
AUDIT_DIR.mkdir(parents=True, exist_ok=True)

# import normalize from MAIN.dashboard
sys.path.insert(0, str(ROOT))
try:
    from MAIN.dashboard import normalize_daily_report_json
except Exception as e:
    print("ERROR importing normalize_daily_report_json:", e)
    raise

TS = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
REPORT = {"generated_at": datetime.utcnow().isoformat() + "Z", "processed": []}

if not OUT_DIR.exists():
    print("no daily_report_out dir")
    raise SystemExit(2)

for p in sorted(OUT_DIR.glob("daily_report_*.json")):
    entry = {"file": str(p), "status": "unchanged", "backup": None, "added_keys": []}
    try:
        txt = p.read_text(encoding="utf-8")
        data = json.loads(txt)
    except Exception as e:
        entry["status"] = "read_error"
        entry["error"] = str(e)
        REPORT["processed"].append(entry)
        continue

    norm = normalize_daily_report_json(data)
    # compare
    if json.dumps(norm, sort_keys=True, ensure_ascii=False) != json.dumps(data, sort_keys=True, ensure_ascii=False):
        bak = p.with_name(p.name + f".bak_{TS}")
        try:
            p.replace(bak)
            p.write_text(json.dumps(norm, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            entry["status"] = "normalized_written"
            entry["backup"] = str(bak)
            if isinstance(norm, dict) and isinstance(norm.get("_normalized"), dict):
                entry["added_keys"] = norm.get("_normalized").get("added_keys", [])
        except Exception as e:
            entry["status"] = "write_error"
            entry["error"] = str(e)
    else:
        # if normalize attached _normalized earlier but file equal, still capture
        if isinstance(norm, dict) and isinstance(norm.get("_normalized"), dict):
            entry["added_keys"] = norm.get("_normalized").get("added_keys", [])
    REPORT["processed"].append(entry)

OUT_PATH = AUDIT_DIR / f"normalize_apply_report_{TS}.json"
OUT_PATH.write_text(json.dumps(REPORT, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Wrote: {OUT_PATH}")
print(f"Files processed: {len(REPORT['processed'])}")
