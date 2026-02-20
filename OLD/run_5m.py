# run_5m.py
import time
import bot

print("[RUNNER] 5分ごとに bot.main() を実行します。Ctrl+Cで停止。")

while True:
    bot.main()
    time.sleep(300)  # 5分
