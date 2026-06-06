# /log — ログ担当エージェント

**役割**: 直近の取引ログを分析し、勝率・損益・パターン・異常を抽出して報告する。

## ログ取得・分析コマンド

### 1. 直近7日間の取引結果サマリー
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib, glob
from datetime import datetime, timedelta

logs_dir = pathlib.Path('/home/ubuntu/trading_bot/logs')
today = datetime.now()
all_trades = []

for i in range(7):
    d = today - timedelta(days=i)
    f = logs_dir / f'trade_log_{d.strftime(\"%Y%m%d\")}.csv'
    if not f.exists():
        continue
    for row in csv.reader(f.open()):
        if len(row) < 5 or row[0] == 'timestamp':
            continue
        all_trades.append(row)

# result counts
results = {}
entries = []
for r in all_trades:
    res = r[1]
    results[res] = results.get(res, 0) + 1
    if res in ('CLOSE_BUY', 'CLOSE_SELL', 'PAPER_EXIT_TP', 'PAPER_EXIT_SL'):
        entries.append(r)

print('=== 直近7日間 result 集計 ===')
for k,v in sorted(results.items(), key=lambda x:-x[1]):
    print(f'  {v:4d}  {k}')

print(f'\n=== 取引結果（{len(entries)}件） ===')
wins = sum(1 for r in entries if 'TP' in r[1])
losses = sum(1 for r in entries if 'SL' in r[1])
print(f'  TP(勝): {wins}件  SL(負): {losses}件')
wr = wins/(wins+losses)*100 if (wins+losses) > 0 else 0
print(f'  勝率: {wr:.1f}%')
PYEOF"
```

### 2. 今日のentry_unfilled（約定失敗）分析
```bash
TODAY=$(date +%Y%m%d)
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "
grep 'entry_unfilled\|OBSERVE_OK' /home/ubuntu/trading_bot/logs/trade_log_${TODAY}.csv 2>/dev/null | \
python3 -c \"
import sys, csv
for line in sys.stdin:
    parts = line.strip().split(',')
    ts = parts[0] if parts else ''
    note = parts[-1][:200] if parts else ''
    if 'entry_unfilled' in note or 'OBSERVE_OK' in parts[1:2]:
        print(f'{ts}: {note[:150]}')
\" | head -10"
```

### 3. fx_below_min_lot エラー確認
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "
grep -r 'fx_below_min_lot\|HTTP 400\|send_failed' /home/ubuntu/trading_bot/logs/ 2>/dev/null | tail -5"
```

### 4. 時間帯別勝率（直近ログ）
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib, glob
from datetime import datetime, timedelta
from collections import defaultdict

logs_dir = pathlib.Path('/home/ubuntu/trading_bot/logs')
hour_stats = defaultdict(lambda: {'win':0,'loss':0})

for i in range(14):
    d = datetime.now() - timedelta(days=i)
    f = logs_dir / f'trade_log_{d.strftime(\"%Y%m%d\")}.csv'
    if not f.exists(): continue
    for row in csv.reader(f.open()):
        if len(row) < 2 or row[0] == 'timestamp': continue
        res = row[1]
        if res not in ('CLOSE_BUY','CLOSE_SELL','PAPER_EXIT_TP','PAPER_EXIT_SL'): continue
        try:
            hr = int(row[0][11:13])
        except: continue
        if 'TP' in res: hour_stats[hr]['win'] += 1
        elif 'SL' in res: hour_stats[hr]['loss'] += 1

print('時間帯  勝  負  WR')
for hr in sorted(hour_stats):
    w = hour_stats[hr]['win']
    l = hour_stats[hr]['loss']
    wr = w/(w+l)*100 if (w+l) > 0 else 0
    bar = '🟢' if wr>=50 else '🟡' if wr>=40 else '🔴'
    print(f' {hr:02d}h  {w:3d} {l:3d}  {wr:5.1f}%  {bar}')
PYEOF"
```

### 5. AIスコア分布とゲート通過率
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "
grep -h 'ai_score=' /home/ubuntu/trading_bot/logs/trade_log_$(date +%Y%m%d).csv 2>/dev/null | \
python3 -c \"
import sys, re
scores = []
for line in sys.stdin:
    m = re.search(r'ai_score=([0-9.]+)', line)
    if m: scores.append(float(m.group(1)))
if scores:
    avg = sum(scores)/len(scores)
    above_th = sum(1 for s in scores if s >= 0.70)
    print(f'AI score samples: {len(scores)}')
    print(f'平均スコア: {avg:.4f}')
    print(f'閾値(0.70)超え: {above_th}/{len(scores)} ({above_th/len(scores)*100:.1f}%)')
else:
    print('ai_score データなし')
\""
```

## 出力フォーマット

```
【ログ担当レポート】直近7日間 YYYY-MM-DD

📊 取引サマリー
  総クローズ: XX件  TP(勝): XX件  SL(負): XX件
  勝率: XX.X%  (目標: >44%)

⚠️ 異常パターン
  entry_unfilled: XX件 (limit注文未約定)
  fx_below_min_lot: X件 (証拠金不足)

📈 時間帯別勝率
  [テーブル形式]

🔍 AIスコア状況
  平均: X.XX  閾値(0.70)超え: XX%

【判定】
  問題なし / 〇〇要確認 / 要対応: 〇〇
```

## 異常検知ルール

| パターン | 閾値 | アクション |
|---------|------|-----------|
| `fx_below_min_lot` 1件以上 | 今日 | 証拠金を確認 → 入金検討 |
| `entry_unfilled` 全OBSERVE_OKの50%超 | 今週 | `limit_price_offset_ticks` 引き上げ検討 |
| 特定時間帯WR < 35% | 14日間 | `no_paper_hours` or `ai_score_bad_hours` 追加検討 |
| 連日SLヒット率 > 60% | 3日間 | トレンドフィルター強化を検討 |
