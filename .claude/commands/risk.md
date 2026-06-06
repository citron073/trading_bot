# /risk — リスク担当エージェント

**役割**: 証拠金・日次損益・連敗・安全フロアをリアルタイムで監視し、リスク状態を報告する。

VMのstate.jsonとCONTROL.csvを読み取り、以下を評価してください:

## チェック項目

### 1. FX証拠金チェック
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 -c \"
import json, pathlib
state = json.loads(pathlib.Path('/home/ubuntu/trading_bot/MAIN/state.json').read_text())
collateral = state.get('_risk_day_start_jpy', 0) or 0
ltp = state.get('_last_ltp', 0) or 0
lot = 0.001
use_ratio = 0.90
required = lot * ltp / use_ratio if ltp > 0 else 0
margin = collateral - required
print(f'証拠金: {collateral:,.0f} JPY')
print(f'必要額: {required:,.0f} JPY')
print(f'余裕:   {margin:+,.0f} JPY ({margin/required*100:+.1f}%)' if required>0 else '余裕: N/A')
print(f'状態:   {\"OK\" if collateral >= required else \"不足\"}')
print(f'LTP:    {ltp:,.0f} JPY')
\""
```

### 2. 日次損益・リスク状態
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 -c \"
import json, pathlib
state = json.loads(pathlib.Path('/home/ubuntu/trading_bot/MAIN/state.json').read_text())
print('日次損失 (JPY):', state.get('_risk_daily_loss_jpy'))
print('連敗数:        ', state.get('_streak_losses'))
print('連敗ストップ:  ', state.get('_streak_stop'))
print('日次損失停止:  ', state.get('_daily_loss_stop'))
print('安全ハードブロック:', state.get('_safety_hard_block'))
print('ポジション:    ', state.get('position'))
\""
```

### 3. 今日の取引サマリー
```bash
TODAY=$(date +%Y%m%d)
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "
if [ -f /home/ubuntu/trading_bot/logs/trade_log_${TODAY}.csv ]; then
  python3 -c \"
import csv, pathlib, sys
rows = list(csv.reader(pathlib.Path('/home/ubuntu/trading_bot/logs/trade_log_${TODAY}.csv').open()))
results = {}
for r in rows[1:]:
    res = r[1] if len(r)>1 else '?'
    results[res] = results.get(res,0) + 1
for k,v in sorted(results.items(), key=lambda x:-x[1]):
    print(f'{v:4d}  {k}')
\"
fi"
```

### 4. .ops_checks.json ステータス
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 -c \"
import json, pathlib
f = pathlib.Path('/home/ubuntu/trading_bot/MAIN/.ops_checks.json')
if f.exists():
    d = json.loads(f.read_text())
    for k,v in d.items():
        ok = v.get('ok', '?')
        ts = v.get('timestamp', v.get('checked_at', '?'))
        print(f'{k}: ok={ok} at={ts}')
else:
    print('ops_checks.json not found')
\""
```

## 出力フォーマット

上記コマンドを実行し、以下の形式で報告してください:

```
【リスク担当レポート】YYYY-MM-DD HH:MM JST

🔴/🟡/🟢 証拠金: XX,XXX JPY / 必要: XX,XXX JPY (余裕: +/- XX JPY)
🔴/🟡/🟢 日次損益: -X,XXX JPY (上限: -2.0%)
🔴/🟡/🟢 連敗: N回 (上限: 3回)
🔴/🟡/🟢 ポジション: あり/なし

【今日の取引】
  ENTRY_xx: N件 / PAPER: N件 / OBSERVE_OK: N件
  entry_unfilled: N件 (limit未約定 — 正常範囲)

【判定】
  総合: 正常運転中 / 要注意 / 要対応
  推奨アクション: なし / 〇〇を確認 / 〇〇を実施
```

## 判定基準

| 指標 | 🟢正常 | 🟡注意 | 🔴要対応 |
|------|--------|--------|---------|
| 証拠金余裕 | +500 JPY以上 | 0〜+500 JPY | マイナス |
| 日次損失 | -1%未満 | -1%〜-1.5% | -1.5%以上 |
| 連敗数 | 0〜1 | 2 | 3（ストップ発動） |
