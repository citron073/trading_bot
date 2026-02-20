# paper_outcome_from_mae_mfe.py
import csv
import argparse
from pathlib import Path

def get_logs_dir() -> Path:
    here = Path(__file__).resolve().parent
    candidate = here.parent / "logs"
    return candidate if candidate.exists() else Path(".")

def read_detail(path: Path):
    rows = []
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    return rows

def to_float(x):
    try:
        return float(x)
    except Exception:
        return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", required=True, help="YYYYMMDD 例: 20260127")
    ap.add_argument("--tp", type=float, required=True, help="TP(%) 例: 0.155")
    ap.add_argument("--sl", type=float, required=True, help="SL(%) 例: -0.222 (BUY想定でマイナス)")
    args = ap.parse_args()

    logs_dir = get_logs_dir()
    detail_path = logs_dir / f"mae_mfe_detail_{args.day}.csv"
    if not detail_path.exists():
        raise FileNotFoundError(f"not found: {detail_path}")

    rows = read_detail(detail_path)

    tp = args.tp
    sl = args.sl

    # 判定ルール（BUY前提）
    # TP到達: mfe_pct >= tp
    # SL到達: mae_pct <= sl  （slはマイナス想定）
    # 両方到達: どっちが先かはログだけでは不明 → "BOTH" 扱い
    # どちらもなし: "NONE"
    cnt = {"TP": 0, "SL": 0, "BOTH": 0, "NONE": 0}
    valid = 0

    out_path = logs_dir / f"paper_outcome_{args.day}_tp{tp:.3f}_sl{sl:.3f}.csv"

    out_rows = []
    for row in rows:
        mae = to_float(row.get("mae_pct"))
        mfe = to_float(row.get("mfe_pct"))
        if mae is None or mfe is None:
            continue
        valid += 1

        hit_tp = (mfe >= tp)
        hit_sl = (mae <= sl)

        if hit_tp and hit_sl:
            outcome = "BOTH"
        elif hit_tp:
            outcome = "TP"
        elif hit_sl:
            outcome = "SL"
        else:
            outcome = "NONE"

        cnt[outcome] += 1

        out_rows.append({
            "day": args.day,
            "idx": row.get("idx"),
            "entry_time_jst": row.get("entry_time_jst"),
            "entry_price": row.get("entry_price"),
            "mae_pct": mae,
            "mfe_pct": mfe,
            "tp_pct": tp,
            "sl_pct": sl,
            "outcome": outcome,
        })

    # 保存
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()) if out_rows else [])
        if out_rows:
            w.writeheader()
            for r in out_rows:
                w.writerow(r)

    # 集計表示
    print(f"[INFO] detail: {detail_path}")
    print(f"[INFO] TP={tp:.3f}% SL={sl:.3f}% (BUY判定)")
    print(f"[INFO] valid={valid}")
    if valid > 0:
        for k in ["TP", "SL", "BOTH", "NONE"]:
            print(f"{k:>4}: {cnt[k]:>3}/{valid}  rate {cnt[k]/valid*100:5.1f}%")
    print(f"[INFO] saved: {out_path}")

if __name__ == "__main__":
    main()
