# /keiba-status — KEIBA 詳細ステータス

**役割**: KEIBA ディレクトリに居るときの詳細状態確認。ルートの `/keiba` と同等。

## クイック確認

```python
python3 << 'PYEOF'
import json, csv, pathlib
from datetime import datetime

BASE = pathlib.Path('.')  # KEIBA/ ディレクトリから実行想定
data = BASE / 'data'

cyc = json.loads((data / 'auto_cycle_status.json').read_text()) if (data / 'auto_cycle_status.json').exists() else {}
cfg = json.loads((data / 'auto_cycle_config.json').read_text()) if (data / 'auto_cycle_config.json').exists() else {}

print('=== KEIBA ステータス ===')
print(f'稼働: {"実行中" if cyc.get("running") else "停止中"}  '
      f'最終: {cyc.get("last_completed_at", "-")}  '
      f'成功: {cyc.get("last_success", "-")}')
print(f'interval: {cfg.get("interval_sec","?")}秒  '
      f'学習: {"ON" if cfg.get("run_tuning") else "OFF"}  '
      f'予測: {"ON" if cfg.get("run_weekly_predictions") else "OFF"}')

rep = cyc.get('report', {})
print(f'履歴: {rep.get("history_rows",0):,}行 / {rep.get("history_races",0):,}R  '
      f'今週: {rep.get("weekly_races",0):,}R')

fb = data / 'prediction_feedback.csv'
if fb.exists():
    rows = list(csv.DictReader(open(fb)))
    done = [r for r in rows if r.get('result_available','').lower()=='true']
    hits = [r for r in done if r.get('top_horse_hit','').lower()=='true']
    wr = len(hits)/len(done)*100 if done else 0
    print(f'予測: {len(rows)}件  結果確認: {len(done)}件  1着的中: {wr:.1f}%')

print()
print(cyc.get('last_summary', '-'))
PYEOF
```

## 予測実績内訳（的中タイプ別）

```python
python3 << 'PYEOF'
import csv, pathlib

rows = list(csv.DictReader(open('data/prediction_feedback.csv')))
done = [r for r in rows if r.get('result_available','').lower()=='true']
if not done:
    print('結果確認済み予測なし')
else:
    keys = ['top_horse_hit','single_hit','place_hit','quinella_hit','wide_hit','trio_hit','trifecta_hit']
    labels = ['1着','単勝','複勝','馬連','ワイド','3連複','3連単']
    print(f'=== 的中率内訳 (n={len(done)}) ===')
    for k, lbl in zip(keys, labels):
        hits = sum(1 for r in done if r.get(k,'').lower()=='true')
        print(f'  {lbl:<6}: {hits}/{len(done)} = {hits/len(done)*100:.1f}%')
PYEOF
```
