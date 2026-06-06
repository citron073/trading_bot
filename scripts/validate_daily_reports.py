#!/usr/bin/env python3
"""
Validate daily_report_out JSON files against a simple SPEC-derived schema.
Writes a summary JSON report to audit_out/json_validation_report_<ts>.json
"""
from pathlib import Path
import json
from datetime import datetime
import re

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "daily_report_out"
AUDIT_DIR = ROOT / "audit_out"
AUDIT_DIR.mkdir(parents=True, exist_ok=True)

REPORT_TS = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
OUT_PATH = AUDIT_DIR / f"json_validation_report_{REPORT_TS}.json"

RE_DAY8 = re.compile(r"^\d{8}$")


def check_file(p: Path):
    res = {"file": str(p), "errors": [], "warnings": [], "normalized_added": []}
    try:
        txt = p.read_text(encoding="utf-8")
        data = json.loads(txt)
    except Exception as e:
        res["errors"].append(f"read_error: {e}")
        return res

    if not isinstance(data, dict):
        res["errors"].append("root_not_object")
        return res

    # meta
    meta = data.get("meta")
    if meta is None:
        res["errors"].append("missing.meta")
    elif not isinstance(meta, dict):
        res["errors"].append("meta_not_object")
    else:
        spec = meta.get("spec")
        if spec is None:
            res["warnings"].append("meta.spec_missing")
        gen = meta.get("generated_at_jst")
        if gen is None:
            res["warnings"].append("meta.generated_at_jst_missing")
        td = meta.get("target_day8")
        if td is None:
            res["warnings"].append("meta.target_day8_missing")
        else:
            if not isinstance(td, str) or not RE_DAY8.match(td):
                res["errors"].append("meta.target_day8_invalid")

    # daily
    daily = data.get("daily")
    if daily is None:
        res["errors"].append("missing.daily")
    elif not isinstance(daily, dict):
        res["errors"].append("daily_not_object")

    # by_side
    by_side = data.get("by_side")
    if by_side is None:
        res["errors"].append("missing.by_side")
    elif not isinstance(by_side, dict):
        res["errors"].append("by_side_not_object")
    else:
        for side in ("BUY", "SELL"):
            if side not in by_side:
                res["warnings"].append(f"by_side.{side}_missing")

    # by_hour
    by_hour = data.get("by_hour")
    if by_hour is None:
        res["errors"].append("missing.by_hour")
    elif not isinstance(by_hour, dict):
        res["errors"].append("by_hour_not_object")
    else:
        # expect keys '0'..'23' or subset
        keys = set(by_hour.keys())
        if not any(k in keys for k in [str(i) for i in range(24)]):
            res["warnings"].append("by_hour.keys_unusual")

    # spread
    spread = data.get("spread")
    if spread is None:
        res["warnings"].append("missing.spread")
    elif not isinstance(spread, dict):
        res["errors"].append("spread_not_object")

    # exit_integrity
    ei = data.get("exit_integrity")
    if ei is None:
        res["warnings"].append("missing.exit_integrity")
    elif not isinstance(ei, dict):
        res["errors"].append("exit_integrity_not_object")
    else:
        for k in ("paper_pos_ids", "exit_pos_ids", "open_pos_ids"):
            if k in ei and not isinstance(ei[k], list):
                res["errors"].append(f"exit_integrity.{k}_not_list")

    # mae_mfe
    mm = data.get("mae_mfe")
    if mm is None:
        res["warnings"].append("missing.mae_mfe")
    elif not isinstance(mm, dict):
        res["errors"].append("mae_mfe_not_object")

    # per_pos: allow top-level or under mae_mfe.per_pos
    per_pos = data.get("per_pos")
    if per_pos is None:
        mm_pp = None
        if isinstance(mm, dict):
            mm_pp = mm.get("per_pos")
        if mm_pp is None:
            res["warnings"].append("missing.per_pos")
        else:
            if not isinstance(mm_pp, dict):
                res["errors"].append("mae_mfe.per_pos_not_object")
    else:
        if not isinstance(per_pos, dict):
            res["errors"].append("per_pos_not_object")

    # issues
    issues = data.get("issues")
    if issues is None:
        res["warnings"].append("missing.issues")
    elif not isinstance(issues, list):
        res["errors"].append("issues_not_list")

    # capture normalization metadata if present
    norm = data.get("_normalized")
    if isinstance(norm, dict):
        added = norm.get("added_keys")
        if isinstance(added, list):
            res["normalized_added"] = added

    return res


def main():
    files = []
    if not OUT_DIR.exists():
        print("no daily_report_out dir")
        return 2
    for p in sorted(OUT_DIR.glob("daily_report_*.json")):
        files.append(p)

    summary = {"generated_at": datetime.utcnow().isoformat() + "Z", "files": []}
    for p in files:
        r = check_file(p)
        summary["files"].append(r)

    OUT_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote: {OUT_PATH}")
    # small human-friendly summary
    tot = len(summary["files"])
    err = sum(1 for f in summary["files"] for e in f.get("errors", []))
    warn = sum(1 for f in summary["files"] for w in f.get("warnings", []))
    print(f"Files: {tot}, errors: {err}, warnings: {warn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
