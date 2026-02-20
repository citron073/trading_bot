import csv
from datetime import datetime, timedelta

CSV_FILE = "trade_log_20260122.csv"
WINDOW_MIN = 60

def parse_time(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")

def main():
    rows = []
    with open(CSV_FILE, newline="") as f:
        r = csv.DictReader(f)
        rows = list(r)

    papers = [r for r in rows if r["result"] == "PAPER"]
    print(f"PAPER件数: {len(papers)}\n")

    for i, p in enumerate(papers, 1):
        entry_time = parse_time(p["time"])
        entry_price = float(p["price"])
        end_time = entry_time + timedelta(minutes=WINDOW_MIN)

        prices = []
        for r in rows:
            t = parse_time(r["time"])
            if entry_time <= t <= end_time:
                if r.get("ltp"):
                    prices.append(float(r["ltp"]))

        if not prices:
            print(f"PAPER #{i} データ不足")
            continue

        low = min(prices)
        high = max(prices)

        mae = (low - entry_price) / entry_price * 100
        mfe = (high - entry_price) / entry_price * 100

        print(f"PAPER #{i}")
        print(f" entry : {entry_price:.0f}")
        print(f" MAE   : {mae:.3f}%")
        print(f" MFE   : {mfe:.3f}%")
        print("-" * 30)

if __name__ == "__main__":
    main()
