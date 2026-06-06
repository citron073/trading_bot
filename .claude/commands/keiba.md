# /keiba — KEIBA システム状態確認エージェント

**役割**: 競馬予想システム（KEIBA）の稼働状態・予測状況・データ品質を確認する。

---

## 基本状態確認

```python
# ローカルで実行
python3 << 'PYEOF'
import json, pathlib, csv
from datetime import datetime

BASE = pathlib.Path('/Users/tani/trading_bot/trading_bot/KEIBA')
data = BASE / 'data'

# --- auto_cycle_status ---
cyc = json.loads((data / 'auto_cycle_status.json').read_text()) if (data / 'auto_cycle_status.json').exists() else {}
cfg = json.loads((data / 'auto_cycle_config.json').read_text()) if (data / 'auto_cycle_config.json').exists() else {}
ops = json.loads((data / 'local_operation_status.json').read_text()) if (data / 'local_operation_status.json').exists() else {}

print('=== KEIBA システム状態 ===')
print(f'稼働状態: {"実行中" if cyc.get("running") else "停止中"}')
print(f'最終実行: {cyc.get("last_started_at", "-")}')
print(f'最終完了: {cyc.get("last_completed_at", "-")}')
print(f'成功フラグ: {cyc.get("last_success", "-")}')
print(f'進捗: {cyc.get("progress_pct", "-")}%  フェーズ: {cyc.get("last_phase", "-")}')
print()
print(f'--- データ ---')
rep = cyc.get('report', {})
print(f'履歴行数: {rep.get("history_rows", "-"):,}')
print(f'エントリー行数: {rep.get("entries_rows", "-"):,}')
print(f'履歴レース数: {rep.get("history_races", "-"):,}')
print(f'今週レース数: {rep.get("weekly_races", "-"):,}')
print()
print(f'--- サイクル設定 ---')
print(f'interval: {cfg.get("interval_sec", "-")}秒')
print(f'学習: {"ON" if cfg.get("run_tuning") else "OFF"}')
print(f'予測生成: {"ON" if cfg.get("run_weekly_predictions") else "OFF"}')
print()
print(f'--- サマリー ---')
print(cyc.get('last_summary', '-'))

# --- prediction_feedback.csv ---
fb_path = data / 'prediction_feedback.csv'
if fb_path.exists():
    rows = list(csv.DictReader(open(fb_path)))
    total = len(rows)
    with_result = [r for r in rows if r.get('result_available', '').lower() == 'true']
    hits = [r for r in with_result if r.get('top_horse_hit', '').lower() == 'true']
    wr = len(hits)/len(with_result)*100 if with_result else 0
    print()
    print(f'=== 予測実績 ===')
    print(f'総予測数: {total}件  結果確認済: {len(with_result)}件')
    print(f'1着的中率: {wr:.1f}%  ({len(hits)}/{len(with_result)})')
PYEOF
```

---

## 今週の予測一覧

```python
python3 << 'PYEOF'
import csv, pathlib
from datetime import datetime

f = pathlib.Path('/Users/tani/trading_bot/trading_bot/KEIBA/data/weekly_predictions_auto.csv')
if not f.exists():
    print('予測ファイルなし')
else:
    rows = list(csv.DictReader(open(f)))
    print(f'=== 今週の予測 ({len(rows)}レース) ===')
    for r in rows[:20]:
        date = r.get('race_date', '')[:10]
        name = r.get('race_name', '-')[:20]
        top  = r.get('top_horse', '-')
        hit  = r.get('top_horse_hit', '')
        mark = '✅' if hit.lower() == 'true' else ('❌' if hit.lower() == 'false' else '⏳')
        print(f'{mark} {date} {name:<20} → {top}')
PYEOF
```

---

## 自動サイクル・ログ確認

```python
python3 << 'PYEOF'
import json, pathlib
from datetime import datetime

BASE = pathlib.Path('/Users/tani/trading_bot/trading_bot/KEIBA')

# agent_status
ag = json.loads((BASE / 'data/auto_agent_status.json').read_text()) if (BASE / 'data/auto_agent_status.json').exists() else {}
print('=== エージェント状態 ===')
print(f'エージェントID: {ag.get("agent_id", "-")}')
print(f'モード: {ag.get("mode", "-")}')
print(f'最終更新: {ag.get("updated_at", "-")}')

# auto_improve_state
imp = json.loads((BASE / 'data/auto_improve_state.json').read_text()) if (BASE / 'data/auto_improve_state.json').exists() else {}
print()
print('=== 自動改善状態 ===')
print(f'フェーズ: {imp.get("phase", "-")}')
print(f'サイクル数: {imp.get("cycle_count", "-")}')
print(f'最終改善: {imp.get("last_improved_at", "-")}')
PYEOF
```

---

## launchd タイマー確認（ローカル）

```bash
launchctl list | grep -i keiba
launchctl print gui/$(id -u) | grep -A3 keiba
```

---

## KEIBA 出力フォーマット例

```
【KEIBA ステータスレポート】

🏇 稼働状態: 停止中（最終: 2026-04-26 03:08）
✅ 最終成功: True  進捗: 100%  フェーズ: 完了

📊 データ規模
  履歴: 65,026行 / 4,684レース
  今週: 1,706行 / 130レース

🎯 予測実績（結果確認済: 284件）
  1着的中率: 42.3%（120/284）

⚙️ サイクル設定
  interval: 1800秒（30分）
  学習=OFF / 予測生成=ON

📝 最終サマリー:
  "history 65,026行 / entries 1,706行 / ..."
```

---

## キーファイルマップ

| ファイル | 内容 |
|---------|------|
| `KEIBA/data/auto_cycle_status.json` | 最新サイクル状態・サマリー |
| `KEIBA/data/auto_cycle_config.json` | サイクル設定（interval, 学習フラグ等） |
| `KEIBA/data/prediction_feedback.csv` | 予測実績（1着的中率等） |
| `KEIBA/data/weekly_predictions_auto.csv` | 今週の予測一覧 |
| `KEIBA/data/auto_agent_status.json` | エージェント実行状態 |
| `KEIBA/data/keiba_best_weights.json` | 特徴量重み（学習済み） |
| `KEIBA/data/local_operation_status.json` | ローカル操作履歴 |
