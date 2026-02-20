import time
from datetime import datetime
import bot  # 同じフォルダに bot.py がある前提

INTERVAL_SEC = 600  # 10分

def main():
    print("[RUNNER] 10分ごとに bot.main() を実行します。Ctrl+Cで停止。")
    while True:
        now = datetime.now()
        print(f"[RUNNER] tick: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            bot.main()
        except Exception as e:
            # 落ちてもループは継続（ログを取り続ける）
            print(f"[RUNNER][ERROR] {e}")

        time.sleep(INTERVAL_SEC)

if __name__ == "__main__":
    main()
