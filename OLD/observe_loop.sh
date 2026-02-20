#!/bin/zsh
cd /Users/tani/trading_bot/trading_bot

# 収集間隔（秒）: まずは60秒を推奨。早くしたいなら30、軽くしたいなら120/300
INTERVAL=60

while true; do
  /usr/bin/python3 bot.py >> observe_run.log 2>&1
  sleep $INTERVAL
done
